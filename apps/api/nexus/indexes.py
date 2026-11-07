import json
import re

from fastapi import HTTPException
from sqlalchemy import select

from .contracts import IndexConfiguration
from .database import Chunk, Document, IndexGeneration, Workspace, uid
from .providers import embedding_provider
from .vectors import vector_index


class IndexManager:
    """One active index per workspace; build checkpoints are independent of ingestion jobs."""

    def __init__(self, service):
        self.service = service
        self.adapters = {}

    def desired(self, workspace_id=None):
        if workspace_id:
            with self.service.sessions() as session:
                workspace = self.service.repo.workspace(session, workspace_id)
                if workspace.index_configuration:
                    return IndexConfiguration.model_validate(workspace.index_configuration)
        settings = self.service.settings
        return IndexConfiguration(
            **{
                key: getattr(settings, key)
                for key in (
                    "embedding_provider",
                    "embedding_model",
                    "embedding_revision",
                    "embedding_dimension",
                    "embedding_onnx_file",
                    "chunk_size",
                    "chunk_overlap",
                )
            }
        )

    def adapters_for(self, generation):
        if generation.id not in self.adapters:
            config = IndexConfiguration.model_validate(generation.configuration)
            settings = self.service.settings.model_copy(
                update=config.model_dump(exclude={"normalization", "preprocessing"})
            )
            embeddings = embedding_provider(settings)
            index = vector_index(
                settings,
                self.service.sessions,
                embeddings.fingerprint,
                config.chunk_size,
                config.chunk_overlap,
                config.embedding_dimension,
                generation.namespace,
                generation.fingerprint,
            )
            self.adapters[generation.id] = (embeddings, index)
        return self.adapters[generation.id]

    def ensure(self, workspace_id):
        with self.service.lock:
            return self._ensure(workspace_id)

    def _ensure(self, workspace_id):
        with self.service.sessions.begin() as session:
            self.service.repo.workspace(session, workspace_id)
            active = session.scalar(
                select(IndexGeneration).where(
                    IndexGeneration.workspace_id == workspace_id, IndexGeneration.active.is_(True)
                )
            )
            if active:
                return active
            config = self.desired(workspace_id)
            index = self.service.index
            existing = session.scalar(
                select(Document).where(
                    Document.workspace_id == workspace_id,
                    Document.status == "ready",
                    Document.fingerprint.is_not(None),
                )
            )
            fingerprint, namespace = index.fingerprint, index.collection.name
            if existing and existing.fingerprint != fingerprint:
                # Phase 1 stored configuration in Chroma, not SQL. Adopt that namespace before building a replacement.
                collection = index.client.get_collection(f"nexus_{existing.fingerprint}")
                stored = json.loads(collection.metadata["configuration"])
                old = stored["embedding"]
                if old.startswith("hash-sha256-"):
                    config.embedding_provider = "hash"
                    config.embedding_dimension = int(re.search(r"hash-sha256-(\d+)", old)[1])
                elif old.startswith("st:"):
                    identity = old[3:].split(":")[0]
                    config.embedding_model, config.embedding_revision = identity.split("@", 1)
                    config.embedding_provider = "sentence-transformers"
                    config.embedding_dimension = int(collection.metadata.get("dimension", 384))
                else:
                    raise ValueError(
                        "Unknown legacy embedding identity. Restore its provider configuration before migration."
                    )
                config.chunk_size, config.chunk_overlap = stored["chunk_size"], stored["overlap"]
                fingerprint, namespace = existing.fingerprint, collection.name
            docs = list(
                session.scalars(
                    select(Document).where(Document.workspace_id == workspace_id, Document.status == "ready")
                )
            )
            generation = IndexGeneration(
                workspace_id=workspace_id,
                namespace=namespace,
                fingerprint=fingerprint,
                configuration=config.model_dump(),
                status="ready",
                active=True,
                checkpoint={d.id: d.version_id for d in docs},
                total=len(docs),
                progress=len(docs),
            )
            session.add(generation)
            session.flush()
            if namespace == index.collection.name:
                self.adapters[generation.id] = (self.service.embeddings, index)
            return generation

    def startup(self):
        with self.service.sessions.begin() as session:
            workspaces = list(session.scalars(select(Workspace.id)))
            for generation in session.scalars(
                select(IndexGeneration).where(IndexGeneration.status == "validating")
            ):
                generation.status = "building"
        for workspace_id in workspaces:
            active = self.ensure(workspace_id)
            try:
                _, active_index = self.adapters_for(active)
                with self.service.sessions() as session:
                    expected = set(
                        session.scalars(
                            select(Chunk.id).where(
                                Chunk.workspace_id == workspace_id, Chunk.fingerprint == active.fingerprint
                            )
                        )
                    )
                actual = set(
                    active_index.collection.get(where={"workspace_id": workspace_id}, include=[])["ids"]
                )
                if expected != actual:
                    raise ValueError("Active vector/SQL coverage mismatch")
            except Exception as error:
                with self.service.sessions.begin() as session:
                    session.get(
                        IndexGeneration, active.id
                    ).error = "Active index integrity check failed. Build a replacement from original sources or restore a verified backup."
                self.service.log_failure("active_index_integrity", active.id, error)
            if active.configuration != self.desired(workspace_id).model_dump():
                self.rebuild(workspace_id, self.desired(workspace_id))

    def rebuild(self, workspace_id, config):
        self.ensure(workspace_id)
        with self.service.lock, self.service.sessions.begin() as session:
            self.service.repo.workspace(session, workspace_id).index_configuration = config.model_dump()
            pending = session.scalar(
                select(IndexGeneration).where(
                    IndexGeneration.workspace_id == workspace_id,
                    IndexGeneration.status.in_(["building", "validating"]),
                )
            )
            if pending:
                if pending.configuration != config.model_dump():
                    raise HTTPException(
                        409, "Finish or cancel the current rebuild before choosing another configuration."
                    )
                return pending
            settings = self.service.settings.model_copy(
                update=config.model_dump(exclude={"normalization", "preprocessing"})
            )
            embeddings = embedding_provider(settings)
            namespace = f"nexus_{uid().replace('-', '')}"
            index = vector_index(
                settings,
                self.service.sessions,
                embeddings.fingerprint,
                config.chunk_size,
                config.chunk_overlap,
                config.embedding_dimension,
                namespace,
            )
            generation = IndexGeneration(
                workspace_id=workspace_id,
                namespace=namespace,
                fingerprint=index.fingerprint,
                configuration=config.model_dump(),
                status="building",
                active=False,
                checkpoint={},
                attempts=1,
            )
            session.add(generation)
            session.flush()
            self.adapters[generation.id] = (embeddings, index)
        self.service.wake.set()
        return generation

    def current_documents(self, session, workspace_id):
        return list(
            session.scalars(
                select(Document).where(Document.workspace_id == workspace_id, Document.status == "ready")
            )
        )

    def activate(self, session, generation):
        current = self.current_documents(session, generation.workspace_id)
        if generation.checkpoint != {d.id: d.version_id for d in current}:
            raise HTTPException(
                409,
                "Documents changed since this index was validated. Rebuild before activation or rollback.",
            )
        for old in session.scalars(
            select(IndexGeneration).where(
                IndexGeneration.workspace_id == generation.workspace_id, IndexGeneration.active.is_(True)
            )
        ):
            old.active, old.status = False, "retired"
        session.flush()  # release the unique active-workspace slot before activating its replacement
        generation.active, generation.status = True, "ready"
        for document in current:
            document.fingerprint = generation.fingerprint

    def process_one(self):
        with self.service.lock:
            with self.service.sessions.begin() as session:
                generation = session.scalar(
                    select(IndexGeneration)
                    .where(IndexGeneration.status.in_(["building", "validating"]))
                    .order_by(IndexGeneration.created_at)
                )
                if generation is None:
                    return False
                generation_id = generation.id
                documents = self.current_documents(session, generation.workspace_id)
                generation.total = len(documents)
                todo = next((d for d in documents if generation.checkpoint.get(d.id) != d.version_id), None)
            try:
                embeddings, index = self.adapters_for(generation)
                if todo:
                    doc = {c.name: getattr(todo, c.name) for c in todo.__table__.columns}
                    config = IndexConfiguration.model_validate(generation.configuration)
                    self.service.index_document(doc, index, embeddings, config)
                    with self.service.sessions.begin() as session:
                        stored = session.get(IndexGeneration, generation_id)
                        checkpoint = dict(stored.checkpoint)
                        checkpoint[todo.id] = todo.version_id
                        stored.checkpoint = checkpoint
                        stored.progress = len(checkpoint)
                    return True
                with self.service.sessions.begin() as session:
                    stored = session.get(IndexGeneration, generation_id)
                    stored.status = "validating"
                    current = self.current_documents(session, stored.workspace_id)
                    live = {d.id: d.version_id for d in current}
                    # Remove deleted/replaced documents from the unfinished namespace before activation.
                    for stale in set(stored.checkpoint) - set(live):
                        index.collection.delete(
                            where={"$and": [{"workspace_id": stored.workspace_id}, {"document_id": stale}]}
                        )
                    stored.checkpoint = {k: v for k, v in stored.checkpoint.items() if k in live}
                    expected = set(
                        session.scalars(
                            select(Chunk.id).where(
                                Chunk.workspace_id == stored.workspace_id,
                                Chunk.document_id.in_(list(live)),
                                Chunk.fingerprint == stored.fingerprint,
                            )
                        )
                    )
                    actual = set(
                        index.collection.get(where={"workspace_id": stored.workspace_id}, include=[])["ids"]
                    )
                    if actual != expected:
                        raise ValueError("Index sanity check failed: SQL and vector chunk IDs differ.")
                    self.activate(session, stored)
                    stored.progress = stored.total = len(live)
            except Exception as error:
                with self.service.sessions.begin() as session:
                    stored = session.get(IndexGeneration, generation_id)
                    stored.status = "failed"
                    stored.error = "Rebuild failed; the old index remains active. Check the declared model/dimension and local storage, then retry."
                self.service.log_failure("index_rebuild", generation_id, error)
            return True

    def action(self, workspace_id, generation_id, action):
        with self.service.lock, self.service.sessions.begin() as session:
            generation = self.service.repo.get(session, IndexGeneration, generation_id, workspace_id)
            if action == "activate":
                if generation.status not in {"ready", "retired"}:
                    raise HTTPException(409, "Only a validated ready/retired index may be activated.")
                self.activate(session, generation)
                self.service.repo.workspace(
                    session, workspace_id
                ).index_configuration = generation.configuration
            elif action == "retry":
                if generation.status != "failed" or generation.attempts >= 3:
                    raise HTTPException(
                        409,
                        "Retry requires a failed index with fewer than three attempts. Start a new rebuild otherwise.",
                    )
                generation.status, generation.error = "building", None
                generation.attempts += 1
            elif action == "cancel":
                if generation.active:
                    raise HTTPException(409, "Cannot cancel an active index.")
                generation.status = "failed"
                generation.error = "Rebuild cancelled by user; the old index remains active."
            self.service.wake.set()
            return generation
