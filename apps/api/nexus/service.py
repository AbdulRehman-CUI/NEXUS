import hashlib
import logging
import re
import threading

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select

from .database import (
    Chat,
    Chunk,
    Citation,
    Document,
    IndexGeneration,
    Job,
    Message,
    Note,
    NoteLink,
    NoteTag,
    Span,
    Workspace,
    uid,
)
from .extraction import NeedsOCR, bounded_extract, split_passage
from .indexes import IndexManager
from .providers import ProviderError, embedding_provider
from .repository import Repository
from .retrieval import RetrievalPipeline
from .storage import FileStorage, validate_upload
from .vaults import VaultService
from .vectors import ChromaIndex

logger = logging.getLogger("nexus")


def record(value):
    return {column.name: getattr(value, column.name) for column in value.__table__.columns}


class Service:
    def __init__(self, settings, sessions):
        self.settings, self.sessions = settings, sessions
        self.repo = Repository(sessions, settings)
        self.files = FileStorage(settings.data_dir / "originals")
        self.embeddings = embedding_provider(settings)
        self.index = ChromaIndex(
            settings.data_dir / "chroma",
            self.embeddings.fingerprint,
            settings.chunk_size,
            settings.chunk_overlap,
            settings.embedding_dimension,
        )
        # ponytail: serialize local storage operations; use document leases for multi-process deployment.
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.indexes = IndexManager(self)
        self.rag = RetrievalPipeline(self)
        self.vaults = VaultService(self)
        from .gateway import ModelGateway

        self.gateway = ModelGateway(self)
        from .byok import ByokStore

        self.byok = ByokStore(self)
        self.stream_slots = threading.BoundedSemaphore(4)

    def log_failure(self, kind, resource_id, error):
        logger.warning(
            "operation_failed kind=%s id=%s error_type=%s", kind, resource_id, type(error).__name__
        )

    def start(self):
        with self.sessions.begin() as session:
            for job in session.scalars(select(Job).where(Job.status == "processing")):
                job.status = "queued"
                document = session.get(Document, job.document_id)
                document.status = "deleting" if job.kind == "delete" else "queued"
            if self.settings.profile == "local" and not session.scalar(select(Workspace)):
                session.add(Workspace(name="Personal workspace"))
        from .auth import system_scope

        with system_scope():
            self.indexes.startup()
            self.gateway.seed_registry()
        if self.settings.worker_enabled:
            self.thread = threading.Thread(target=self.worker, name="nexus-ingestion", daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            # Finish the current atomic ingestion before disposing SQL connections.
            self.thread.join()

    def worker(self):
        while not self.stop_event.is_set():
            if not self.process_one():
                self.wake.wait(0.5)
                self.wake.clear()

    def capacity(self, session):
        count = session.scalar(
            select(func.count()).select_from(Job).where(Job.status.in_(["queued", "processing"]))
        )
        if count >= self.settings.max_queued_jobs:
            raise HTTPException(429, "The ingestion queue is full. Wait for current documents to finish.")

    def upload(self, workspace_id, filename, mime, content, origin="upload"):
        try:
            title, extension = validate_upload(filename, mime, content)
        except ValueError as error:
            raise HTTPException(415, str(error)) from error
        digest = hashlib.sha256(content).hexdigest()
        with self.lock, self.sessions.begin() as session:
            self.repo.workspace(session, workspace_id)
            existing = session.scalar(
                select(Document).where(Document.workspace_id == workspace_id, Document.content_hash == digest)
            )
            if existing:
                if existing.status == "deleting":
                    raise HTTPException(
                        409, "This document is awaiting deletion. Wait for cleanup before uploading again."
                    )
                job = session.scalar(
                    select(Job).where(Job.document_id == existing.id).order_by(Job.created_at.desc())
                )
                if origin == "upload":
                    existing.origin = "upload"
                return {"document": record(existing), "job_id": job.id if job else None, "duplicate": True}
            self.capacity(session)
            key = f"{uid()}{extension}"
            self.files.write(key, content)
            try:
                document = Document(
                    workspace_id=workspace_id,
                    title=title,
                    extension=extension,
                    content_hash=digest,
                    storage_key=key,
                    size=len(content),
                    origin=origin,
                )
                session.add(document)
                session.flush()
                job = Job(workspace_id=workspace_id, document_id=document.id)
                session.add(job)
                session.flush()
                result = {"document": record(document), "job_id": job.id, "duplicate": False}
                session.commit()
            except Exception:
                self.files.delete(key)
                raise
        self.wake.set()
        return result

    def enqueue(self, workspace_id, document_id, kind="index"):
        with self.lock, self.sessions.begin() as session:
            document = self.repo.get(session, Document, document_id, workspace_id)
            active = session.scalar(
                select(Job).where(Job.document_id == document_id, Job.status.in_(["queued", "processing"]))
            )
            if active and active.kind == kind:
                return record(active)
            if document.status == "deleting" and kind != "delete":
                raise HTTPException(409, "Document is awaiting deletion.")
            self.capacity(session)
            if active:
                active.status = "cancelled"
            job = Job(workspace_id=workspace_id, document_id=document_id, kind=kind)
            document.status = "deleting" if kind == "delete" else "queued"
            document.error = None
            for note in session.scalars(
                select(Note).where(Note.document_id == document_id, Note.workspace_id == workspace_id)
            ):
                if kind == "delete":
                    note.deleted, note.status = True, "deleted"
                    session.execute(delete(NoteTag).where(NoteTag.note_id == note.id))
                    session.execute(
                        delete(NoteLink).where(
                            or_(NoteLink.source_id == note.id, NoteLink.target_id == note.id)
                        )
                    )
                elif not note.deleted:
                    note.status = "pending"
            session.add(job)
            session.flush()
            result = record(job)
        self.wake.set()
        return result

    def process_one(self):
        from .auth import system_scope

        # Only already-admitted persisted jobs may execute without an HTTP principal.
        with system_scope():
            return self._process_one()

    def _process_one(self):
        with self.lock:
            with self.sessions.begin() as session:
                job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at))
                if job is None:
                    return self.vaults.process_one() or self.indexes.process_one()
                job.status = "processing"
                job.attempts += 1
                job_id, kind = job.id, job.kind
                document = self.repo.get(session, Document, job.document_id, job.workspace_id)
                document.status = "deleting" if kind == "delete" else "processing"
                doc = record(document)
            try:
                if kind == "delete":
                    self.index.delete_document(doc["workspace_id"], doc["id"])
                    self.files.delete(doc["storage_key"])
                    with self.sessions.begin() as session:
                        for generation in session.scalars(
                            select(IndexGeneration).where(IndexGeneration.workspace_id == doc["workspace_id"])
                        ):
                            if doc["id"] in generation.checkpoint:
                                generation.checkpoint = {
                                    key: value
                                    for key, value in generation.checkpoint.items()
                                    if key != doc["id"]
                                }
                                generation.progress = generation.total = len(generation.checkpoint)
                        session.delete(session.get(Document, doc["id"]))
                    return True
                generation = self.indexes.ensure(doc["workspace_id"])
                embeddings, index = self.indexes.adapters_for(generation)
                from .contracts import IndexConfiguration

                self.index_document(
                    doc, index, embeddings, IndexConfiguration.model_validate(generation.configuration)
                )
                with self.sessions.begin() as session:
                    document, job = session.get(Document, doc["id"]), session.get(Job, job_id)
                    document.status, document.error = "ready", None
                    document.fingerprint = index.fingerprint
                    job.status, job.error = "ready", None
                    for note in session.scalars(
                        select(Note).where(Note.document_id == doc["id"], Note.deleted.is_(False))
                    ):
                        if note.content_hash == document.content_hash:
                            note.status = "ready"
                    active = session.get(type(generation), generation.id)
                    active.checkpoint = {**active.checkpoint, doc["id"]: document.version_id}
                    active.progress = active.total = len(active.checkpoint)
            except Exception as error:
                state = "needs_ocr" if isinstance(error, NeedsOCR) else "failed"
                # Provider/library exceptions may contain credentials/paths: expose only known validation errors.
                public_error = (
                    str(error)
                    if isinstance(error, (NeedsOCR, ValueError, UnicodeError))
                    else (
                        "Indexing failed. Check the local embedding model download and storage permissions, then retry."
                    )
                )
                public_error = public_error[:500]
                with self.sessions.begin() as session:
                    document, job = session.get(Document, doc["id"]), session.get(Job, job_id)
                    document.status = "deleting" if kind == "delete" else state
                    document.error = public_error
                    job.status, job.error = "failed" if kind == "delete" else state, public_error
                    for note in session.scalars(
                        select(Note).where(Note.document_id == doc["id"], Note.deleted.is_(False))
                    ):
                        if note.content_hash == document.content_hash:
                            note.status = "failed"
                logger.warning("job_failed id=%s kind=%s error_type=%s", job_id, kind, type(error).__name__)
            return True

    def index_document(self, doc, index=None, embeddings=None, config=None):
        index, embeddings, config = (
            index or self.index,
            embeddings or self.embeddings,
            config or self.settings,
        )
        passages = bounded_extract(
            self.files.path(doc["storage_key"]),
            doc["extension"],
            self.settings,
        )
        spans, chunks = [], []
        for ordinal, passage in enumerate(passages):
            span_id = hashlib.sha256(f"{doc['version_id']}:span:{ordinal}".encode()).hexdigest()
            span = Span(
                id=span_id,
                workspace_id=doc["workspace_id"],
                document_id=doc["id"],
                version_id=doc["version_id"],
                ordinal=ordinal,
                page=passage.page,
                heading=passage.heading,
                text=passage.text,
            )
            spans.append(span)
            for text, start, end in split_passage(passage.text, config.chunk_size, config.chunk_overlap):
                chunk_id = hashlib.sha256(f"{span_id}:{start}:{end}:{index.fingerprint}".encode()).hexdigest()
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        workspace_id=doc["workspace_id"],
                        document_id=doc["id"],
                        version_id=doc["version_id"],
                        span_id=span_id,
                        start=start,
                        end=end,
                        text=text,
                        fingerprint=index.fingerprint,
                    )
                )
        index.collection.delete(
            where={"$and": [{"workspace_id": doc["workspace_id"]}, {"document_id": doc["id"]}]}
        )
        for offset in range(0, len(chunks), 32):
            batch = chunks[offset : offset + 32]
            vectors = embeddings.embed([c.text for c in batch])
            index.upsert(
                [
                    {
                        "id": c.id,
                        "text": c.text,
                        "metadata": {
                            "workspace_id": c.workspace_id,
                            "document_id": c.document_id,
                            "version_id": c.version_id,
                            "fingerprint": c.fingerprint,
                        },
                    }
                    for c in batch
                ],
                vectors,
            )
        with self.sessions.begin() as session:
            keep = {c.id for c in chunks}
            for old in session.scalars(
                select(Chunk).where(
                    Chunk.document_id == doc["id"],
                    Chunk.workspace_id == doc["workspace_id"],
                    Chunk.fingerprint == index.fingerprint,
                )
            ):
                if old.id not in keep:
                    session.delete(old)
            for span in spans:
                session.merge(span)
            session.flush()
            for chunk in chunks:
                session.merge(chunk)

    def retrieve(self, session, workspace_id, question):
        results, _ = self.rag.search(session, workspace_id, question)
        return self.rag.evidence(results)

    def citation_available(self, session, item):
        document = session.get(Document, item["document_id"])
        chunk = session.get(Chunk, item["chunk_id"])
        if document is None or chunk is None or document.workspace_id != item["workspace_id"]:
            return False
        if document.status != "ready" or document.version_id != item["document_version_id"]:
            return False
        if item.get("note_id"):
            note = session.get(Note, item["note_id"])
            if (
                note is None
                or note.deleted
                or note.status != "ready"
                or note.document_id != document.id
                or note.workspace_id != document.workspace_id
                or note.content_hash != document.content_hash
            ):
                return False
        return chunk.text == item["excerpt"] and chunk.version_id == item["document_version_id"]

    def answer(
        self,
        workspace_id,
        chat_id,
        question,
        filters=None,
        options=None,
        include_diagnostics=False,
        on_delta=None,
        cancelled=None,
    ):
        with self.lock, self.sessions() as session:
            self.repo.get(session, Chat, chat_id, workspace_id)
            provider = self.gateway.generator(session, workspace_id)
            if hasattr(provider, "context_limit"):
                options = options or self.rag.profile(session, workspace_id)
                options = options.model_copy(
                    update={"context_budget": min(options.context_budget, provider.context_limit(question))}
                )
                provider.on_delta = on_delta if provider.config["streaming"] else None
                provider.cancelled = cancelled
            results, diagnostic = self.rag.search(session, workspace_id, question, filters, options, chat_id)
            evidence = self.rag.evidence(results)
        # No network request if retrieval finds insufficient evidence.
        answer = (
            provider.generate(diagnostic["standalone_query"], evidence)
            if evidence
            else ("I don't have enough evidence in the indexed documents to answer this question.")
        )
        if cancelled and cancelled.is_set():
            from .provider_transport import GenerationCancelled

            raise GenerationCancelled()
        known = {e["citation_id"] for e in evidence}
        citation_pattern = (
            r"(?m)^\[(C[a-zA-Z0-9]+)\]\s*$" if provider.name == "mock" else r"\[(C[a-zA-Z0-9]+)\]"
        )
        cited = set(re.findall(citation_pattern, answer))
        if cited - known:
            raise ProviderError(
                "The model returned an unknown citation. Answer was not saved; please retry.", 502
            )
        if evidence and not cited:
            answer = "I don't have enough cited evidence to provide a verified answer. Try a more specific question."
        evidence = [e for e in evidence if e["citation_id"] in cited]
        diagnostic["quality_flags"] = (
            ["uncited_generation"] if known and not cited else (["no_evidence"] if not known else [])
        )
        diagnostic["citation_coverage"] = {
            "retrieved": len(known),
            "cited": len(evidence),
            "unknown_ids": 0,
            "note": "Source identity is verified; claim entailment is not guaranteed.",
        }
        with self.lock, self.sessions.begin() as session:
            chat = self.repo.get(session, Chat, chat_id, workspace_id)
            # A document may have been deleted/reindexed during remote generation.
            for item in evidence:
                if not self.citation_available(session, item):
                    raise HTTPException(409, "Sources changed during generation. Please ask again.")
                item["available"] = True
            position = (
                session.scalar(
                    select(func.max(Message.position)).where(
                        Message.chat_id == chat_id, Message.workspace_id == workspace_id
                    )
                )
                or 0
            )
            session.add(
                Message(
                    workspace_id=workspace_id,
                    chat_id=chat_id,
                    role="user",
                    content=question,
                    position=position + 1,
                )
            )
            message = Message(
                workspace_id=workspace_id,
                chat_id=chat_id,
                role="assistant",
                position=position + 2,
                content=answer,
                provider=provider.name,
                evidence_snapshot=evidence,
                diagnostics=diagnostic,
            )
            session.add(message)
            session.flush()
            for item in evidence:
                session.add(
                    Citation(
                        id=item["citation_id"],
                        workspace_id=workspace_id,
                        message_id=message.id,
                        document_id=item["document_id"],
                        chunk_id=item["chunk_id"],
                        payload=item,
                    )
                )
            if chat.title == "New conversation":
                chat.title = question[:60]
            return {
                **record(message),
                "answer": answer,
                "citations": evidence,
                "diagnostics": diagnostic if include_diagnostics else None,
            }

    def messages(self, session, chat):
        values = []
        for message in session.scalars(
            select(Message)
            .where(Message.chat_id == chat.id, Message.workspace_id == chat.workspace_id)
            .order_by(Message.position)
        ):
            citations = session.scalars(
                select(Citation).where(
                    Citation.message_id == message.id, Citation.workspace_id == chat.workspace_id
                )
            )
            snapshots = message.evidence_snapshot or [c.payload for c in citations]
            resolved = []
            for item in snapshots:
                available = self.citation_available(session, item)
                resolved.append(
                    {
                        **item,
                        "available": available,
                        **(
                            {"unavailable_reason": "Source was changed, deleted, or is being reindexed."}
                            if not available
                            else {}
                        ),
                    }
                )
            values.append(
                {
                    **record(message),
                    "diagnostics": message.diagnostics or None,
                    "citations": sorted(resolved, key=lambda item: item.get("order", 0)),
                }
            )
        return values
