import hashlib
import json
from heapq import nsmallest
from typing import Protocol

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from .database import StoredVector


def index_configuration(embedding, chunk_size, overlap):
    return {
        "embedding": embedding,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "parser": "bounded-sentence-v2",
    }


def index_fingerprint(configuration):
    return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()[:24]


class VectorIndex(Protocol):
    fingerprint: str

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]): ...
    def search(self, workspace_id: str, vector: list[float], limit: int) -> list[tuple[str, float]]: ...
    def delete_document(self, workspace_id: str, document_id: str): ...


class ChromaIndex:
    def __init__(
        self,
        path,
        embedding_fingerprint,
        chunk_size,
        overlap,
        dimension=384,
        namespace=None,
        fingerprint=None,
    ):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from llama_index.vector_stores.chroma import ChromaVectorStore

        self.dimension = dimension
        self.configuration = index_configuration(embedding_fingerprint, chunk_size, overlap)
        self.fingerprint = fingerprint or index_fingerprint(self.configuration)
        self.namespace = namespace or f"nexus_{self.fingerprint}"
        self.client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            self.namespace,
            metadata={
                "hnsw:space": "cosine",
                "configuration": json.dumps(self.configuration, sort_keys=True),
                "dimension": dimension,
                "normalization": "l2",
            },
        )
        self.store = ChromaVectorStore(chroma_collection=self.collection)

    def count(self):
        return self.collection.count()

    def ids(self, workspace_id):
        return self.collection.get(where={"workspace_id": workspace_id}, include=[])["ids"]

    def clear_document(self, workspace_id, document_id):
        self.collection.delete(where={"$and": [{"workspace_id": workspace_id}, {"document_id": document_id}]})

    def upsert(self, chunks, embeddings):
        from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

        if len(chunks) != len(embeddings) or any(len(vector) != self.dimension for vector in embeddings):
            raise ValueError("Vector dimension mismatch; rebuild with a compatible embedding configuration.")
        # Chroma's upsert makes interrupted/repeated jobs idempotent.
        for offset in range(0, len(chunks), 64):
            batch = chunks[offset : offset + 64]
            nodes = [
                TextNode(
                    id_=c["id"],
                    text=c["text"],
                    metadata=c["metadata"],
                    relationships={
                        NodeRelationship.SOURCE: RelatedNodeInfo(node_id=c["metadata"]["document_id"])
                    },
                )
                for c in batch
            ]
            # Use the same node serialization as LlamaIndex's Chroma adapter.
            from llama_index.core.vector_stores.utils import node_to_metadata_dict

            self.collection.upsert(
                ids=[n.node_id for n in nodes],
                documents=[n.text for n in nodes],
                embeddings=embeddings[offset : offset + 64],
                metadatas=[node_to_metadata_dict(n, remove_text=True, flat_metadata=True) for n in nodes],
            )

    def search(self, workspace_id, vector, limit, document_ids=None):
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
            VectorStoreQuery,
        )

        if len(vector) != self.dimension:
            raise ValueError("Query embedding dimension does not match index dimension.")
        if document_ids == []:
            return []
        filters = MetadataFilters(
            filters=[
                MetadataFilter(key="workspace_id", value=workspace_id, operator=FilterOperator.EQ),
                MetadataFilter(key="fingerprint", value=self.fingerprint, operator=FilterOperator.EQ),
            ]
        )
        if document_ids is not None:
            filters.filters.append(
                MetadataFilter(key="document_id", value=document_ids, operator=FilterOperator.IN)
            )
        result = self.store.query(
            VectorStoreQuery(query_embedding=vector, similarity_top_k=limit, filters=filters)
        )
        return [
            (node.node_id, 1 - similarity)
            for node, similarity in zip(result.nodes or [], result.similarities or [])
        ]

    def delete_document(self, workspace_id, document_id):
        # Delete across old fingerprints as well, so embedding migrations don't leak vectors.
        for item in self.client.list_collections():
            name = item.name if hasattr(item, "name") else item
            if name.startswith("nexus_"):
                self.client.get_collection(name).delete(
                    where={
                        "$and": [
                            {"workspace_id": {"$eq": workspace_id}},
                            {"document_id": {"$eq": document_id}},
                        ]
                    }
                )


class PostgresIndex:
    """Durable workspace-scoped exact vector search without database extensions."""

    def __init__(self, sessions, embedding, chunk_size, overlap, dimension, namespace=None, fingerprint=None):
        self.sessions, self.dimension = sessions, dimension
        self.fingerprint = fingerprint or index_fingerprint(
            index_configuration(embedding, chunk_size, overlap)
        )
        self.namespace = namespace or f"nexus_{self.fingerprint}"

    def count(self):
        with self.sessions() as session:
            return session.scalar(
                select(func.count()).select_from(StoredVector).where(StoredVector.namespace == self.namespace)
            )

    def scoped(self, statement, workspace_id):
        return statement.where(
            StoredVector.namespace == self.namespace, StoredVector.workspace_id == workspace_id
        )

    def ids(self, workspace_id):
        with self.sessions() as session:
            return list(session.scalars(self.scoped(select(StoredVector.chunk_id), workspace_id)))

    def clear_document(self, workspace_id, document_id):
        with self.sessions.begin() as session:
            session.execute(
                self.scoped(delete(StoredVector), workspace_id).where(StoredVector.document_id == document_id)
            )

    def delete_document(self, workspace_id, document_id):
        with self.sessions.begin() as session:
            session.execute(
                delete(StoredVector).where(
                    StoredVector.workspace_id == workspace_id, StoredVector.document_id == document_id
                )
            )

    def upsert(self, chunks, embeddings):
        if len(chunks) != len(embeddings) or any(len(vector) != self.dimension for vector in embeddings):
            raise ValueError("Vector dimension mismatch; rebuild with a compatible embedding configuration.")
        statement = insert(StoredVector)
        with self.sessions.begin() as session:
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[StoredVector.namespace, StoredVector.chunk_id],
                    set_={"embedding": statement.excluded.embedding},
                ),
                [
                    {
                        "namespace": self.namespace,
                        "chunk_id": chunk["id"],
                        "embedding": vector,
                        "workspace_id": chunk["metadata"]["workspace_id"],
                        "document_id": chunk["metadata"]["document_id"],
                    }
                    for chunk, vector in zip(chunks, embeddings)
                ],
            )

    def search(self, workspace_id, vector, limit, document_ids=None):
        if len(vector) != self.dimension:
            raise ValueError("Query embedding dimension does not match index dimension.")
        if document_ids == []:
            return []
        query = self.scoped(select(StoredVector.chunk_id, StoredVector.embedding), workspace_id)
        if document_ids is not None:
            query = query.where(StoredVector.document_id.in_(document_ids))
        target = np.asarray(vector)
        target_norm = np.linalg.norm(target)

        def ranked(rows):
            for chunk_id, embedding in rows:
                norm = target_norm * np.linalg.norm(embedding)
                yield chunk_id, float(1 - np.dot(target, embedding) / norm) if norm else 1.0

        with self.sessions() as session:
            rows = session.execute(query.execution_options(yield_per=256))
            return nsmallest(limit, ranked(rows), key=lambda row: (row[1], row[0]))
