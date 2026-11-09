import logging
import re
import time
from collections import Counter
from typing import Protocol
from urllib.parse import urlencode

from sqlalchemy import and_, exists, or_, select, text

from .contracts import RetrievalSettings, SearchFilters
from .database import Chunk, Document, Message, Note, NoteTag, RetrievalProfile, Span, Vault, uid
from .providers import ProviderError

logger = logging.getLogger("nexus.retrieval")


class LexicalIndex(Protocol):
    def search(self, session, query, workspace_id, fingerprint, document_ids, limit, title_weight): ...


def match_expression(query):
    # User input is quoted FTS data, never SQL or an unchecked FTS expression.
    terms = [phrase or word for phrase, word in re.findall(r'"([^"\n]+)"|(\w+)', query, re.UNICODE)]
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:40])


class SQLiteLexicalIndex:
    def search(self, session, query, workspace_id, fingerprint, document_ids, limit, title_weight):
        expression = match_expression(query)
        if not expression or not document_ids:
            return []
        # json_each uses one bound value even for a large authorized document set.
        import json

        rows = session.execute(
            text("""SELECT chunk_id, bm25(chunk_fts,0,0,0,0,0,:title_weight,1,1) AS rank
            FROM chunk_fts WHERE chunk_fts MATCH :query AND workspace_id=:workspace AND fingerprint=:fingerprint
            AND document_id IN (SELECT value FROM json_each(:documents)) ORDER BY rank, chunk_id LIMIT :limit"""),
            {
                "query": expression,
                "workspace": workspace_id,
                "fingerprint": fingerprint,
                "documents": json.dumps(document_ids),
                "limit": limit,
                "title_weight": title_weight,
            },
        )
        return [(row.chunk_id, -row.rank) for row in rows]


class PostgresLexicalIndex:
    def search(self, session, query, workspace_id, fingerprint, document_ids, limit, title_weight):
        expression = " OR ".join(re.findall(r'"[^"\n]+"|\w+', query, re.UNICODE)[:40])
        if not expression or not document_ids:
            return []
        rows = session.execute(
            text("""WITH query AS (SELECT websearch_to_tsquery('simple', :query) AS terms),
            candidates AS (
                SELECT c.id, to_tsvector('simple', c.text) AS body,
                    to_tsvector('simple', d.title) AS title
                FROM chunks c JOIN documents d ON c.document_id = d.id
                WHERE c.workspace_id = :workspace AND c.fingerprint = :fingerprint
                AND c.document_id = ANY(:documents)
            )
            SELECT id, ts_rank(body, terms) + :title_weight * ts_rank(title, terms) AS score
            FROM candidates, query WHERE (body || title) @@ terms
            ORDER BY score DESC, id LIMIT :limit"""),
            {
                "query": expression,
                "workspace": workspace_id,
                "fingerprint": fingerprint,
                "documents": document_ids,
                "limit": limit,
                "title_weight": title_weight,
            },
        )
        return [(row.id, row.score) for row in rows]


def fuse(rankings, constant=60):
    scores = {}
    for ranking, weight in rankings:
        seen = set()
        for position, (chunk_id, _) in enumerate(ranking, 1):
            if chunk_id not in seen:
                scores[chunk_id] = scores.get(chunk_id, 0) + weight / (constant + position)
                seen.add(chunk_id)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class Reranker(Protocol):
    def rank(self, query: str, chunks: list[dict]) -> list[tuple[str, float]]: ...


class NoReranker:
    def rank(self, query, chunks):
        return [(item["chunk_id"], item["score"]) for item in chunks]


class CrossEncoderReranker:
    def __init__(self, model, allow_download=False):
        self.name, self.allow_download, self.model = model, allow_download, None

    def rank(self, query, chunks):
        if self.model is None:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(
                self.name,
                device="cpu",
                trust_remote_code=False,
                local_files_only=not self.allow_download,
                max_length=512,
            )
        scores = self.model.predict(
            [(query, item["excerpt"]) for item in chunks], batch_size=8, show_progress_bar=False
        )
        return sorted(
            [(item["chunk_id"], float(score)) for item, score in zip(chunks, scores)],
            key=lambda p: (-p[1], p[0]),
        )


def reformulate(question, previous, enabled):
    follow_up = len(question.split()) <= 16 and bool(
        re.search(
            r"\b(it|its|they|their|that|those|them)\b|^(and|what about|when|why|how about)\b", question, re.I
        )
    )
    previous_budget = min(1500, 4000 - len(question) - len(" Follow-up: "))
    return (
        f"{previous[:previous_budget]} Follow-up: {question}"
        if enabled and previous and follow_up and previous_budget > 0
        else question
    )


def visible_document_condition():
    note = exists(
        select(Note.id).where(
            Note.document_id == Document.id,
            Note.content_hash == Document.content_hash,
            Note.workspace_id == Document.workspace_id,
            Note.deleted.is_(False),
            Note.status == "ready",
        )
    )
    return or_(Document.origin == "upload", note)


class RetrievalPipeline:
    def __init__(self, service):
        self.service = service
        if service.settings.hosted:
            from .hosted import PostgresLexicalIndex as HostedLexicalIndex

            self.lexical = HostedLexicalIndex()
        else:
            self.lexical = PostgresLexicalIndex() if service.postgres else SQLiteLexicalIndex()
        self.rerankers = {}

    def profile(self, session, workspace_id):
        stored = session.get(RetrievalProfile, workspace_id)
        return (
            RetrievalSettings.model_validate(stored.configuration)
            if stored
            else RetrievalSettings(
                top_k=self.service.settings.max_retrieval_results,
                context_budget=self.service.settings.context_budget,
            )
        )

    def allowed(self, session, workspace_id, filters):
        self.service.repo.workspace(session, workspace_id)
        for document_id in filters.document_ids:
            self.service.repo.get(session, Document, document_id, workspace_id)
        if filters.vault_id:
            self.service.repo.get(session, Vault, filters.vault_id, workspace_id)
        query = select(Document.id).where(
            Document.workspace_id == workspace_id, Document.status == "ready", visible_document_condition()
        )
        if filters.document_ids:
            query = query.where(Document.id.in_(filters.document_ids))
        if filters.types:
            query = query.where(Document.extension.in_(filters.types))
        note_conditions = [
            Note.document_id == Document.id,
            Note.content_hash == Document.content_hash,
            Note.workspace_id == workspace_id,
            Note.deleted.is_(False),
            Note.status == "ready",
        ]
        if filters.vault_id:
            note_conditions.append(Note.vault_id == filters.vault_id)
        if filters.path_prefix:
            note_conditions.append(Note.path.startswith(filters.path_prefix, autoescape=True))
        if filters.tags:
            note_conditions.append(
                exists(
                    select(NoteTag.note_id).where(
                        NoteTag.note_id == Note.id,
                        NoteTag.workspace_id == workspace_id,
                        NoteTag.tag.in_(filters.tags),
                    )
                )
            )
        if filters.vault_id or filters.path_prefix or filters.tags:
            query = query.where(exists(select(Note.id).where(*note_conditions)))
        return list(session.scalars(query)), note_conditions

    def search(self, session, workspace_id, question, filters=None, options=None, chat_id=None):
        started = time.perf_counter()
        filters = filters or SearchFilters()
        profile = self.profile(session, workspace_id)
        options = (
            RetrievalSettings.model_validate(
                {**profile.model_dump(), **options.model_dump(exclude_unset=True)}
            )
            if options
            else profile
        )
        generation = self.service.indexes.ensure(workspace_id)
        if generation.error and generation.active:
            from fastapi import HTTPException

            raise HTTPException(503, generation.error)
        document_ids, note_conditions = self.allowed(session, workspace_id, filters)
        previous = (
            session.scalar(
                select(Message.content)
                .where(
                    Message.workspace_id == workspace_id, Message.chat_id == chat_id, Message.role == "user"
                )
                .order_by(Message.position.desc())
                .limit(1)
            )
            if chat_id
            else None
        )
        standalone = reformulate(question, previous, options.rewrite)
        variants = [standalone]
        if options.multi_query:
            variants += [question, " ".join(re.findall(r'"([^"\n]+)"', question))]
            variants = list(dict.fromkeys(q for q in variants if q.strip()))[: options.max_variants]
        rankings, stages, warnings = [], {}, []
        if document_ids:
            embeddings, index = self.service.indexes.adapters_for(generation)
            for number, query in enumerate(variants):
                if options.mode in {"semantic", "hybrid"}:
                    try:
                        dense = [
                            (key, 1 - distance)
                            for key, distance in index.search(
                                workspace_id,
                                embeddings.embed([query])[0],
                                options.candidate_count,
                                document_ids,
                            )
                            if distance <= self.service.settings.max_distance
                        ]
                    except Exception as error:
                        raise ProviderError(
                            "Dense retrieval is unavailable. Check the active embedding runtime or choose keyword mode."
                        ) from error
                    rankings.append((dense, options.semantic_weight))
                    stages[f"dense_{number}"] = [
                        {"chunk_id": key, "cosine_similarity": score} for key, score in dense
                    ]
                if options.mode in {"keyword", "hybrid"}:
                    lexical = self.lexical.search(
                        session,
                        query,
                        workspace_id,
                        generation.fingerprint,
                        document_ids,
                        options.candidate_count,
                        options.title_weight,
                    )
                    rankings.append((lexical, options.lexical_weight))
                    stages[f"lexical_{number}"] = [
                        {"chunk_id": key, "bm25_score": score} for key, score in lexical
                    ]
        candidates = fuse(rankings, options.rrf_constant)
        by_id = {}
        for chunk_id, score in candidates:
            chunk = session.scalar(
                select(Chunk)
                .join(Document, Document.id == Chunk.document_id)
                .where(
                    Chunk.id == chunk_id,
                    Chunk.workspace_id == workspace_id,
                    Document.workspace_id == workspace_id,
                    Document.id.in_(document_ids),
                    Document.status == "ready",
                    Chunk.version_id == Document.version_id,
                    Chunk.fingerprint == generation.fingerprint,
                    visible_document_condition(),
                )
            )
            if chunk is None:
                continue
            span = self.service.repo.get(session, Span, chunk.span_id, workspace_id)
            document = self.service.repo.get(session, Document, chunk.document_id, workspace_id)
            if span.text[chunk.start : chunk.end] != chunk.text:
                continue
            note = session.scalar(
                select(Note)
                .where(and_(*note_conditions), Note.document_id == document.id)
                .order_by(Note.path)
            )
            source_query = {"workspace_id": workspace_id}
            if note:
                source_query["note_id"] = note.id
            by_id[chunk_id] = {
                "chunk_id": chunk_id,
                "score": score,
                "workspace_id": workspace_id,
                "document_id": document.id,
                "document_version_id": document.version_id,
                "source_span_id": span.id,
                "title": note.path if note else document.title,
                "note_id": note.id if note else None,
                "vault_id": note.vault_id if note else None,
                "path": note.path if note else None,
                "tags": note.tags if note else [],
                "page": span.page,
                "heading": span.heading,
                "start": chunk.start,
                "end": chunk.end,
                "excerpt": chunk.text,
                "source_url": f"/api/documents/{document.id}/source?"
                + urlencode({**source_query, "chunk_id": chunk.id}),
            }
        stages = {
            name: [item for item in values if item["chunk_id"] in by_id] for name, values in stages.items()
        }
        candidates = [(key, score) for key, score in candidates if key in by_id]
        if options.reranker == "cross-encoder" and by_id:
            try:
                reranker = self.rerankers.setdefault(
                    options.reranker_model,
                    CrossEncoderReranker(
                        options.reranker_model, self.service.settings.reranker_allow_download
                    ),
                )
                candidates = reranker.rank(standalone, list(by_id.values()))
                stages["reranker"] = [
                    {"chunk_id": key, "cross_encoder_score": score} for key, score in candidates
                ]
            except Exception:
                warnings.append(
                    "Optional local reranker unavailable; the original ranking was retained. No model was downloaded unless explicitly enabled on the server."
                )
        else:
            candidates = NoReranker().rank(standalone, list(by_id.values()))
        selected, fingerprints, per_document, remaining = [], [], Counter(), options.context_budget
        for key, score in candidates:
            item = by_id[key]
            tokens = set(re.findall(r"\w+", item["excerpt"].casefold()))
            if any(len(tokens & old) / max(1, len(tokens | old)) > 0.9 for old in fingerprints):
                continue
            cost = len(item["excerpt"].encode("utf-8"))
            if cost > remaining or per_document[item["document_id"]] >= options.max_per_document:
                continue
            item["score"] = score
            selected.append(item)
            fingerprints.append(tokens)
            per_document[item["document_id"]] += 1
            remaining -= cost
            if len(selected) >= options.top_k:
                break
        diagnostic = {
            "mode": options.mode,
            "index_id": generation.id,
            "index_fingerprint": generation.fingerprint,
            "embedding_provider": generation.configuration["embedding_provider"],
            "embedding_model": generation.configuration["embedding_model"],
            "standalone_query": standalone,
            "variants": variants,
            "additional_cloud_calls": 0,
            "authorized_documents": len(document_ids),
            "candidate_count": len(candidates),
            "stages": stages,
            "final": [
                {
                    key: item[key]
                    for key in (
                        "chunk_id",
                        "document_id",
                        "source_span_id",
                        "page",
                        "heading",
                        "path",
                        "score",
                    )
                }
                for item in selected
            ],
            "excerpt_bytes": options.context_budget - remaining,
            "warnings": warnings,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        logger.info(
            "retrieval mode=%s candidates=%d selected=%d elapsed_ms=%s",
            options.mode,
            len(candidates),
            len(selected),
            diagnostic["elapsed_ms"],
        )
        return selected, diagnostic

    def evidence(self, results):
        evidence = []
        for item in results:
            citation = {**item, "citation_id": f"C{uid().replace('-', '')[:12]}", "order": len(evidence)}
            citation["source_url"] += "&citation_id=" + citation["citation_id"]
            evidence.append(citation)
        return evidence
