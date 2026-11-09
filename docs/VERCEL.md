# NEXUS on Vercel and Neon

The root `vercel.json` deploys the Next.js UI and native FastAPI service together using Vercel Services (beta). The project root must be the repository root, with automatic framework detection; each service declares its own framework. `/api/*` and `/health` route to FastAPI; other paths route to Next.js. `NEXT_PUBLIC_API_URL` is empty for same-origin browser requests.

## Persistent data

Hosted mode (`NEXUS_HOSTED=true`) uses the connected Neon `DATABASE_URL`. It stores relational records, sessions, encrypted BYOK credentials, originals (bytea), and pgvector embeddings in the dedicated `nexus` schema. Preview deployments use `nexus_preview` and a separate BYOK encryption key. These schemas isolate application records but are not separate database security boundaries; trusted preview code has the database role's permissions. For untrusted branches, use an independently scoped Neon branch/database.

Startup performs additive schema initialization under a PostgreSQL transaction advisory lock and enables pgvector. Hosted schema version 2 adds private guest sessions while preserving the existing accounts, documents, and pgvector collections. Local mode continues to use its existing storage and Alembic migrations.

`/tmp/nexus` is only a disposable extraction/model cache. Original files are always read from Neon. The initial hosted upload limit is **3 MB per file/ZIP**, including a separate bounded multipart allowance under the platform request limit. Larger storage should move to object storage with signed direct uploads. Exact vector search is appropriate for the initial small corpus; larger deployments need indexed vector search and database capacity planning.

## Processing

Hosted mode does not start a daemon worker. Authenticated document, job, index, and vault status requests await one durable queued unit of work. The UI polls these routes. Processing pauses when no client is polling and resumes on the next visit; this is not an always-running background queue. Transaction advisory locks serialize writes across instances and are compatible with Neon's pooled endpoint. Busy clients receive a retryable 503. For unattended imports at scale, move processing to a durable queue/worker.

ONNX embeddings run on CPU with the pinned MiniLM model. The first embedding request downloads the model to the disposable cache and may be slower. Local Ollama and server filesystem vault paths are not available on Vercel; use uploads or the authenticated local sync agent. Optional PyTorch embedding/reranking packages are excluded from the hosted bundle.

## Guest access and AI providers

Set `NEXUS_GUEST_ACCESS=true` and provide a stable, independently generated `NEXUS_GUEST_SESSION_SECRET` to the FastAPI service. Keep Secure cookies enabled. Each browser automatically opens a private workspace on first visit. The fixed lifetime defaults to seven days. See [deployment settings](DEPLOYMENT.md) for the exact values and origin configuration.

Open **Select LLM** to add an API key, test a provider, and choose a model. Chat requires a selected model. Remote providers require consent before receiving questions or excerpts, and paid models or models with unknown pricing require billing consent. Keep the existing `NEXUS_BYOK_MASTER_KEY` stable to preserve stored credentials. The existing account API still supports private users. The one-time setup endpoint is available only when guest access is disabled and an operator has configured `NEXUS_SETUP_TOKEN_HASH`.

## Verification and recovery

`/health` checks SQL and vector storage and gives anonymous callers only `{"status":"ok"}`. Authenticated health identifies the database and processing mode. GitHub runs the existing offline suite plus a separate PostgreSQL/pgvector integration job covering private setup, authentication, upload, three retrieval modes, tenant scoping, cold-start persistence and deletion. Neither test job uses production credentials.

The local backup command backs up local installations only. Configure and verify recovery using Neon's database backup/restore facilities for hosted data; plan retention according to the selected Neon plan. Vercel deployment rollback restores code, not database state. Preserve the encryption key with the operational recovery records.
