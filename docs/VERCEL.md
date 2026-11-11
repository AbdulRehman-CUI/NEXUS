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

### Enable guest access

1. Open the **nexus** project in Vercel, then go to **Settings → Environment Variables**. Add `NEXUS_GUEST_ACCESS` with value `true` for **Production** and **Preview**.
2. For each environment that lacks a valid `NEXUS_GUEST_SESSION_SECRET`, generate a new value from at least 32 random bytes and add it as type **Secret**. Use distinct values for Production and Preview. On Windows, run the following from PowerShell to copy a new value directly to the clipboard without printing it. Paste it into Vercel, save it, then run the command again for the other environment. Clear the clipboard after both saves.

   ```powershell
   python -c "import secrets, subprocess; subprocess.run(['clip.exe'], input=secrets.token_urlsafe(32), text=True, check=True)"
   ```

3. Retain `NEXUS_HOSTED=true`, `NEXUS_PROFILE=server`, `NEXUS_SECURE_COOKIES=true`, the existing `DATABASE_URL`, and the existing `NEXUS_BYOK_MASTER_KEY`. Keep exact values in `NEXUS_ALLOWED_HOSTS` and `NEXUS_CORS_ORIGINS`. Production uses `["nexus-livid-delta.vercel.app"]` and `["https://nexus-livid-delta.vercel.app"]`, respectively. The backend adds exact Vercel preview hostnames from exposed system variables. If a preview uses another hostname, add that host and its HTTPS origin to the Preview allowlists.
4. In **Deployments**, open the menu for the intended **Production** deployment and choose **Redeploy**. Confirm the Production target and wait for **Ready**. Preview settings take effect on the next Preview deployment. [Vercel environment variables](https://vercel.com/docs/environment-variables/managing-environment-variables) · [Redeploy a deployment](https://vercel.com/docs/deployments/managing-deployments)
5. Open the production URL in a fresh browser context. Check that `POST /api/auth/guest` returns 200, the browser stores the Secure, HttpOnly guest cookie, `GET /api/auth/me` reports `guest=true`, and the workspace loads. Refresh to confirm the workspace stays the same, then repeat in an independent context to check isolation. A successful guest initialization exercises the table added by hosted schema version 2.

Each browser automatically opens a private workspace on first visit. The fixed lifetime defaults to seven days. See [deployment settings](DEPLOYMENT.md) for the complete configuration.

Open **Select LLM** to add an API key, test a provider, and choose a model. Chat requires a selected model. Remote providers require consent before receiving questions or excerpts, and paid models or models with unknown pricing require billing consent. Keep the existing `NEXUS_BYOK_MASTER_KEY` stable to preserve stored credentials. The existing account API still supports private users. The one-time setup endpoint is available only when guest access is disabled and an operator has configured `NEXUS_SETUP_TOKEN_HASH`.

## Verification and recovery

`/health` checks SQL and vector storage and gives anonymous callers only `{"status":"ok"}`. Authenticated health identifies the database and processing mode. GitHub runs the existing offline suite plus a separate PostgreSQL/pgvector integration job covering private setup, authentication, upload, three retrieval modes, tenant scoping, cold-start persistence and deletion. Neither test job uses production credentials.

The local backup command backs up local installations only. Configure and verify recovery using Neon's database backup/restore facilities for hosted data; plan retention according to the selected Neon plan. Vercel deployment rollback restores code, not database state. Preserve the encryption key with the operational recovery records.
