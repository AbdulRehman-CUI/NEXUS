# NEXUS architecture — Phase 2

Phase 2 adds `retrieval.py` (FTS5, filtered dense search, weighted RRF, local reformulation, evidence diversity and lazy reranking), `vaults.py` (secure snapshots, manifests and authored graph), `indexes.py` (workspace index registry/checkpoints/activation), typed `contracts.py`, `routes_phase2.py`, the opt-in `local_agent.py`, and a reproducible `evaluate.py` command. Existing Phase 1 routes and data remain intact.

Default real embeddings now run the pinned sentence-transformers MiniLM model through ONNX Runtime and Rust tokenizers, attention-mask mean pooling and L2 normalization. The official quantized artifact is ~23 MB; ONNX was already a Chroma dependency. PyTorch is optional. No vendor generation SDK enters services. Global `.env` defaults can be overridden by explicit persisted workspace index choices.

Ingestion SQL writes maintain FTS5 in the same transaction via chunk/note triggers. Both retrieval branches receive the same authorized current-document set, then every candidate is revalidated against SQL scope/version/content hash/source offsets. Evidence is deduplicated and bounded before the generation gateway. Diagnostics carry ranking scores/IDs and total latency; logs carry counts/latency, never excerpt bodies.

One worker processes document jobs, then durable sync cursor steps, then index rebuild steps. Sync updates only changed notes and builds graph relationships after note indexing. New index generations preserve the old active namespace, checkpoint each document, validate SQL/vector ID parity, then atomically switch the active row. Retired namespaces and source chunks remain for rollback; source snapshots flag unavailable note revisions rather than pointing to current content.

The browser calls FastAPI directly on localhost. The API owns SQLAlchemy sessions and a scoped repository, a single DB-backed ingestion worker, local original files, a generation gateway, and embedding/vector adapters. No vendor SDK is used in service/business logic. HTTP provider access is isolated in `providers.py`.

```text
Next.js library → multipart API → validated/hashed atomic local file + SQL job
worker → PyMuPDF / heading parser → normalized source spans
       → LlamaIndex SentenceSplitter → CPU embeddings → persistent Chroma
       → SQL chunks + ready state
Next.js chat → workspace SQL lookup → query embedding
            → LlamaIndex ChromaVectorStore metadata-filtered query
            → SQL revalidation + bounded context → generation adapter
            → server citation validation + SQL messages/citations → UI
source link → workspace/citation/document/chunk checks → stored passage + original
```

`GenerationProvider`, `EmbeddingProvider`, and `VectorIndex` are small protocols. Mock and Groq generation share one retrieval pipeline. Hash and sentence-transformer embedding adapters share one vector adapter. Future OpenAI/Anthropic/Gemini/Ollama/OpenAI-compatible adapters can implement the generation protocol; they are not advertised as completed integrations.

LlamaIndex participates in real ingestion (sentence splitting), node serialization, and filtered vector retrieval. No default OpenAI LLM/embedding configuration is used or instantiated. Chroma gets explicit embeddings, so it never downloads its default ONNX embedding model. SQLite migrations run before worker startup.

The in-process storage lock serializes indexing, file/vector cleanup, and retrieval against deletion. The worker uses one thread and small embedding batches. Network generation happens outside that lock; all citations are rechecked before saving in case sources changed. This intentionally limits throughput and requires one API process per data directory. Durable leases, parser subprocess isolation, multi-process coordination and external queues belong in Phase 3.

Provider/model/free-confirmation settings are saved atomically as non-secret `data/provider.json`; `.env` holds secrets and index configuration. Saved provider UI choices take precedence over provider/model/free-confirmation environment defaults at restart. Remove that non-secret file to restore environment defaults. Workspace consent is SQL-persisted and defaults to false.
# Phase 3 current architecture

Two profiles share the existing FastAPI/SQL/Chroma/Next stack: loopback local and authenticated server. `auth.py` supplies expiring hashed-token sessions and workspace roles; `Repository` enforces membership with request-scoped context, including synchronous services. HTTP admission validates origins/CSRF/rates/roles; worker execution uses a narrow explicit system scope for previously admitted jobs. An OS data lease prevents concurrent API/maintenance writers. `IndexManager.ensure` serializes first-generation creation.

`gateway.py` routes per-workspace generation independently of retrieval/indexing, with durable registry/policies, destination consent, paid operator/workspace gates and usage reservations. No fallback or automatic generation retry. `routes_release.py` exposes model policy, job controls, comparison, feedback/reviews, redacted diagnostics and validated portable settings. Background parsing runs in a disposable process/time budget; DOCX text/tables and optional OCR reuse source span/version rules.

`backup.py` requires a stopped lease, manifests/hashes all stores, restores to a new directory and revokes sessions. Request/job logs exclude bodies/URLs; request diagnostics write off the event loop with a short SQLite busy timeout so failed metrics cannot stall normal requests. Remaining sections describe the preserved Phase 1/2 core.

