"""Durable PostgreSQL adapters for serverless deployments; local mode stays SQLite/Chroma."""

import hashlib
import json
import math
import re
import threading

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .database import Base
from .storage import FileStorage


class DatabaseLock:
    """Reentrant transaction advisory lock, compatible with Neon's transaction pooler."""

    def __init__(self, engine, schema):
        self.engine = engine
        self.key = int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)
        self.local = threading.RLock()
        self.state = threading.local()

    def __enter__(self):
        self.local.acquire()
        depth = getattr(self.state, "depth", 0)
        if not depth:
            connection = None
            try:
                connection = self.engine.connect()
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": self.key})
            except Exception:
                if connection is not None:
                    connection.close()
                self.local.release()
                raise HTTPException(503, "NEXUS is processing another operation. Retry shortly.") from None
            self.state.connection = connection
        self.state.depth = depth + 1
        return self

    def __exit__(self, *_):
        self.state.depth -= 1
        if not self.state.depth:
            self.state.connection.close()  # rollback releases the transaction-scoped lock
        self.local.release()


def postgres_database(settings):
    schema = settings.database_schema
    if not re.fullmatch(r"nexus(?:_[a-z0-9_]+)?", schema):
        raise ValueError("Use a dedicated nexus or nexus_* database schema.")
    url = make_url(settings.database_url.get_secret_value())
    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("Hosted storage requires PostgreSQL.")
    url = url.set(drivername="postgresql+psycopg")
    engine = create_engine(
        url, poolclass=NullPool, connect_args={"connect_timeout": 10}, hide_parameters=True
    )
    # SET LOCAL runs for every transaction, including across pooled Neon connections.
    from sqlalchemy import event

    @event.listens_for(engine, "begin")
    def search_path(connection):
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')

    with DatabaseLock(engine, schema), engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        Base.metadata.create_all(connection)
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_index ON index_generations (workspace_id) WHERE active"
            )
        )
        connection.execute(text("CREATE TABLE IF NOT EXISTS hosted_schema (version integer PRIMARY KEY)"))
        versions = list(connection.scalars(text("SELECT version FROM hosted_schema")))
        if versions and versions != [1]:
            raise RuntimeError("Unsupported hosted schema version; deploy its matching application.")
        connection.execute(text("INSERT INTO hosted_schema VALUES (1) ON CONFLICT DO NOTHING"))
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS stored_files (key text PRIMARY KEY, content bytea NOT NULL)")
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS vector_collections (name text PRIMARY KEY, metadata jsonb NOT NULL)"
            )
        )
        connection.execute(
            text("""CREATE TABLE IF NOT EXISTS stored_vectors (
            namespace text REFERENCES vector_collections(name) ON DELETE CASCADE,
            id text, workspace_id text NOT NULL, document_id text NOT NULL,
            fingerprint text NOT NULL, embedding public.vector NOT NULL,
            PRIMARY KEY (namespace, id))""")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS vectors_scope ON stored_vectors (namespace,workspace_id,document_id)"
            )
        )
    return engine, sessionmaker(engine, expire_on_commit=False)


class PostgresFiles(FileStorage):
    def __init__(self, root, engine, prefix=""):
        super().__init__(root)
        self.engine, self.prefix = engine, prefix

    def path(self, key):
        target = super().path(key)
        with self.engine.connect() as connection:
            content = connection.scalar(
                text("SELECT content FROM stored_files WHERE key=:key"), {"key": self.prefix + key}
            )
        if content is None:
            target.unlink(missing_ok=True)
            return target
        # Materialize only a disposable extraction cache. The database is authoritative.
        target.parent.mkdir(parents=True, exist_ok=True)
        FileStorage(self.root).write(key, bytes(content))
        return target

    def write(self, key, content):
        super().path(key)  # path traversal check without a read
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO stored_files(key, content) VALUES (:key,:content)
                ON CONFLICT (key) DO UPDATE SET content=excluded.content"""),
                {"key": self.prefix + key, "content": content},
            )

    def delete(self, key):
        target = super().path(key)
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM stored_files WHERE key=:key"), {"key": self.prefix + key})
        target.unlink(missing_ok=True)


def conditions(where, params):
    if not where:
        return "TRUE"
    if "$and" in where:
        return " AND ".join("(" + conditions(item, params) + ")" for item in where["$and"])
    clauses = []
    for key, value in where.items():
        if key not in {"workspace_id", "document_id", "fingerprint"}:
            raise ValueError("Unsupported vector filter")
        param = f"p{len(params)}"
        if isinstance(value, dict):
            if set(value) != {"$eq"}:
                raise ValueError("Unsupported vector operator")
            value = value["$eq"]
        params[param] = value
        clauses.append(f"{key}=:{param}")
    return " AND ".join(clauses)


class Collection:
    def __init__(self, engine, name, metadata=None):
        self.engine, self.name = engine, name
        with engine.begin() as connection:
            if metadata is not None:
                connection.execute(
                    text("""INSERT INTO vector_collections(name,metadata) VALUES (:name,CAST(:metadata AS jsonb))
                    ON CONFLICT DO NOTHING"""),
                    {"name": name, "metadata": json.dumps(metadata)},
                )
            self.metadata = connection.scalar(
                text("SELECT metadata FROM vector_collections WHERE name=:name"), {"name": name}
            )
            if self.metadata is None:
                raise ValueError("Vector collection does not exist")

    def get(self, where=None, include=None):
        params = {"namespace": self.name}
        predicate = conditions(where, params)
        with self.engine.connect() as connection:
            return {
                "ids": list(
                    connection.scalars(
                        text(f"SELECT id FROM stored_vectors WHERE namespace=:namespace AND {predicate}"),
                        params,
                    )
                )
            }

    def count(self):
        with self.engine.connect() as connection:
            return connection.scalar(
                text("SELECT count(*) FROM stored_vectors WHERE namespace=:namespace"),
                {"namespace": self.name},
            )

    def delete(self, where=None, ids=None):
        params = {"namespace": self.name}
        predicate = conditions(where, params)
        if ids is not None:
            predicate += " AND id=ANY(:ids)"
            params["ids"] = ids
        with self.engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM stored_vectors WHERE namespace=:namespace AND {predicate}"), params
            )


class PostgresIndex:
    def __init__(
        self,
        engine,
        embedding_fingerprint,
        chunk_size,
        overlap,
        dimension=384,
        namespace=None,
        fingerprint=None,
    ):
        self.engine, self.dimension = engine, dimension
        self.configuration = {
            "embedding": embedding_fingerprint,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "parser": "bounded-sentence-v2",
        }
        self.fingerprint = (
            fingerprint
            or hashlib.sha256(json.dumps(self.configuration, sort_keys=True).encode()).hexdigest()[:24]
        )
        self.collection = Collection(
            engine,
            namespace or f"nexus_{self.fingerprint}",
            {
                "configuration": json.dumps(self.configuration, sort_keys=True),
                "dimension": dimension,
                "normalization": "l2",
            },
        )
        self.client = self

    def get_collection(self, name):
        return Collection(self.engine, name)

    def upsert(self, chunks, embeddings):
        if len(chunks) != len(embeddings) or any(
            len(v) != self.dimension or not all(math.isfinite(x) for x in v) for v in embeddings
        ):
            raise ValueError("Vector dimension or value mismatch")
        if not chunks:
            return
        rows = [
            {
                "namespace": self.collection.name,
                "id": c["id"],
                "workspace": c["metadata"]["workspace_id"],
                "document": c["metadata"]["document_id"],
                "fingerprint": self.fingerprint,
                "vector": json.dumps(v),
            }
            for c, v in zip(chunks, embeddings)
        ]
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO stored_vectors(namespace,id,workspace_id,document_id,fingerprint,embedding)
                VALUES (:namespace,:id,:workspace,:document,:fingerprint,CAST(:vector AS public.vector))
                ON CONFLICT (namespace,id) DO UPDATE SET embedding=excluded.embedding,
                workspace_id=excluded.workspace_id,document_id=excluded.document_id,fingerprint=excluded.fingerprint"""),
                rows,
            )

    def search(self, workspace_id, vector, limit, document_ids=None):
        if len(vector) != self.dimension:
            raise ValueError("Query dimension mismatch")
        if document_ids == []:
            return []
        params = {
            "namespace": self.collection.name,
            "workspace": workspace_id,
            "fingerprint": self.fingerprint,
            "vector": json.dumps(vector),
            "limit": limit,
        }
        predicate = ""
        if document_ids is not None:
            predicate = " AND document_id=ANY(:documents)"
            params["documents"] = document_ids
        with self.engine.connect() as connection:
            return [
                (r.id, r.distance)
                for r in connection.execute(
                    text(f"""SELECT id, embedding <=> CAST(:vector AS public.vector) AS distance
                FROM stored_vectors WHERE namespace=:namespace AND workspace_id=:workspace AND fingerprint=:fingerprint {predicate}
                ORDER BY distance,id LIMIT :limit"""),
                    params,
                )
            ]

    def delete_document(self, workspace_id, document_id):
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM stored_vectors WHERE workspace_id=:workspace AND document_id=:document"),
                {"workspace": workspace_id, "document": document_id},
            )


class PostgresLexicalIndex:
    def search(self, session, query, workspace_id, fingerprint, document_ids, limit, title_weight):
        if not document_ids:
            return []
        # OR matches the local retrieval contract; quote lexical terms as tsquery data.
        terms = [
            f'"{phrase}"' if phrase else word
            for phrase, word in re.findall(r'"([^"\n]+)"|(\w+)', query, re.UNICODE)
        ][:40]
        expression = " OR ".join(terms)
        if not expression:
            return []
        rows = session.execute(
            text("""WITH candidates AS (
            SELECT c.id, setweight(to_tsvector('simple',d.title),'A') ||
                setweight(to_tsvector('simple',c.text),'B') AS document
            FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE c.workspace_id=:workspace AND c.fingerprint=:fingerprint AND c.document_id=ANY(:documents))
            SELECT id,ts_rank(ARRAY[0.1,0.2,CAST(:body_weight AS real),CAST(:title_weight AS real)],document,websearch_to_tsquery('simple',:query)) AS rank
            FROM candidates WHERE document @@ websearch_to_tsquery('simple',:query) ORDER BY rank DESC,id LIMIT :limit"""),
            {
                "workspace": workspace_id,
                "fingerprint": fingerprint,
                "documents": document_ids,
                "query": expression,
                "title_weight": title_weight / max(1.0, title_weight),
                "body_weight": 1.0 / max(1.0, title_weight),
                "limit": limit,
            },
        )
        return [(r.id, r.rank) for r in rows]
