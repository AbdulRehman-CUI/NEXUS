# Deployment

## Vercel and Neon guest access

Enable `NEXUS_GUEST_ACCESS=true` on the **FastAPI service**. The repository's Vercel Services deployment uses `NEXUS_HOSTED=true` and Neon pgvector. See the [Vercel runbook](VERCEL.md) for the hosted schema, request-driven ingestion, and preview isolation.

| Variable | Value |
| --- | --- |
| `NEXUS_HOSTED` | `true` |
| `NEXUS_GUEST_ACCESS` | `true` |
| `NEXUS_PROFILE` | `server` |
| `NEXUS_SECURE_COOKIES` | `true` |
| `DATABASE_URL` or `NEXUS_DATABASE_URL` | The existing Neon PostgreSQL connection URL with TLS, for example `?sslmode=require`. |
| `NEXUS_GUEST_SESSION_SECRET` | A stable Secret generated from at least 32 random bytes. Use separate values for Production and Preview, and preserve any valid existing value. |
| `NEXUS_BYOK_MASTER_KEY` | The existing base64-encoded AES master key. Keep the same value across instances and releases to preserve access to encrypted credentials. |
| `NEXUS_ALLOWED_HOSTS` | JSON array of exact API hostnames the proxy sends in `Host`. |
| `NEXUS_CORS_ORIGINS` | JSON array of exact HTTPS frontend origins, for example `["https://nexus.example.com"]`. |
| `NEXUS_DATA_DIR` | A writable runtime directory, such as `/tmp/nexus` for a function. |
| `NEXUS_GUEST_SESSION_HOURS` | Optional fixed lifetime in hours. Defaults to `168` (7 days), with an allowed range of 1–720. |

Add the guest flag and secret under **Settings → Environment Variables**. Save a Secret for Production and a separately generated Secret for Preview. Keep both values out of source control, logs, and `NEXT_PUBLIC_*` variables. The [Vercel runbook](VERCEL.md#enable-guest-access) includes a Windows clipboard command and the production redeployment steps.

Serve the API under the frontend origin so the browser can send its host-only, Strict cookie with app requests. With separate frontend and API projects, set `NEXT_PUBLIC_API_URL=/` and `NEXUS_API_ORIGIN=https://<your-api-host>` on the **Next.js project**, then rebuild. The rewrite forwards `/api/*` to the FastAPI deployment. If your deployment already routes `/api/*` on the frontend origin, set just `NEXT_PUBLIC_API_URL=/`. Keep the API routes uncached and configure trusted proxy forwarding so FastAPI sees HTTPS. [Vercel external rewrites](https://vercel.com/docs/routing/rewrites)

Vercel startup adds the guest-session table in hosted schema version `2`. Standalone API deployments apply Alembic migration `0006`. Use a database role that can apply the migration, and a separate Neon branch for preview/test environments. Keep the current database connection, schema, and BYOK master when upgrading an existing hosted deployment. Local SQLite/Chroma data remains in its local store. Moving it to PostgreSQL requires a separate data migration.

A missing or expired browser cookie opens a new, empty guest workspace. Refreshes keep the same workspace until the fixed expiry. Expiry revokes access to the old workspace and its credentials. Expired rows, encrypted keys, and documents are retained. First-visit coordination across browser tabs uses Web Locks. Existing account sessions and private memberships continue to work through the authenticated API. Guest sessions have one workspace and cannot manage memberships or use server-wide generation credentials. Guest Ollama is disabled because a hosted API has no access to the visitor’s loopback interface.

PostgreSQL stores original files and vectors as well as the workspace records. Vector and keyword retrieval scope results to the authorized workspace. The Vercel service processes queued work while clients poll. Standalone PostgreSQL deployments can run the existing persistent ingestion worker with `NEXUS_WORKER_ENABLED=true`. Existing PostgreSQL backup tooling should include the new tables. A Vercel environment variable change takes effect on the next deployment. [Vercel environment variables](https://vercel.com/docs/environment-variables/managing-environment-variables)

### Guest verification

- Run `python -m pytest apps/api/tests` from the repository root. Set `NEXUS_TEST_POSTGRES_URL` to a disposable PostgreSQL database to run the guest integration tests across two API instances. The tests use temporary schemas.
- Build Next.js with `NEXT_PUBLIC_API_URL=/` and start it on loopback port 3000. Start `python scripts/guest_test_fixture.py --cert <test-certificate> --key <test-private-key>` with a disposable TLS certificate. Run `npm run test:e2e -- tests/guest.spec.ts` from `apps/web` with `NEXUS_GUEST_BROWSER_URL=https://127.0.0.1:3443`. The fixture serves the real API over HTTPS with a synthetic provider transport and temporary data.

## BYOK runtime secrets

Follow [BYOK setup](BYOK_SETUP.md) to create or inject the AES master. Persistent cloud-key storage fails closed without it. Keep the master outside `NEXUS_DATA_DIR`, separate from database backups, and readable only by the API service identity. The `.secrets` directory is excluded from Git and Docker builds. Containers must receive a separate read-only secret mount, for example `/run/secrets/nexus-byok-master`, and `NEXUS_BYOK_MASTER_KEY_FILE` must point to that mounted file; do not bake the host `.env` or key into an image.

Use HTTPS and secure cookies in the server profile, with trusted reverse-proxy forwarding and explicit hosts/origins. Disable response buffering for `/api/chats/*/messages/stream`; NEXUS supplies `X-Accel-Buffering: no`. Test metadata endpoints and a grounded answer after deploying each provider configuration. No cloud model, credential, public deployment or Ollama download is installed automatically.

## Phase 3 profiles and release operations

Run Windows `scripts/setup.ps1`, then `scripts/api.ps1` / `scripts/web.ps1`. Unix uses `sh scripts/setup.sh` and `sh scripts/run.sh api|web`. The CPU ONNX/model profile is unchanged. Static development checking additionally installs `requirements-typecheck.txt`; production Docker uses only the runtime CPU lock. Keep several GB free for a fresh install. Only Windows installed-runtime operation was executed; a fresh Linux/macOS install remains a release gate.

`NEXUS_PROFILE=local` rejects non-loopback clients/hosts. For network service use `server`, create accounts while stopped with `scripts/manage_users.py`, explicitly claim legacy workspaces if appropriate, configure TLS/reverse proxy and Secure cookies, exact allowed hosts/CORS origins, private persistent volumes, restricted egress and backup scheduling. Match frontend/API sites for Strict cookies; use a same-origin reverse proxy where possible. Disable URL query-string access logs (provided run scripts do). Forward only trusted proxy headers and apply perimeter request/login/body limits. NEXUS's in-process peer limiter is not a distributed firewall.

`docker compose config --quiet` and the `local-llm` profile config both validated. Default Compose publishes ports only on 127.0.0.1, uses authenticated server mode because Docker bridge peers are not loopback, keeps SQLite/Chroma/originals in one persistent volume and bounds memory/CPU/PIDs with non-root app users. Default generation is mock; CPU MiniLM weights may download on first use. Start with `docker compose build`, create the first account while API is stopped with `docker compose run --rm api python scripts/manage_users.py owner --admin`, then `docker compose up -d`. Default loopback HTTP demo explicitly disables Secure cookies; override to true behind production TLS. Public API origin is a frontend build argument; rebuild when changing it.

Ollama is behind explicit `--profile local-llm`; no heavyweight model is pulled. The optional service shares the API network namespace for literal-loopback access and has separate model storage. Operators must install a chosen model explicitly, then select Local Optional in workspace policy. Default Compose uses the SQLite profile described above. Docker engine was unavailable on the original release host, so container runtime verification remains separate.

Use [backup/restore](BACKUP_RESTORE.md), [provider guide](PROVIDER_GUIDE.md), [troubleshooting](TROUBLESHOOTING.md) and [release checklist](RELEASE_CHECKLIST.md). With SQLite, API processes and maintenance commands share the OS data lease and a second process is rejected. Parser subprocesses have wall limits and Unix resource limits.

## Preserved Phase 2 CPU/storage notes

Phase 2 default setup uses the pinned ONNX CPU profile; `.\scripts\setup.ps1 -WithTorch` adds the optional larger sentence-transformers/cross-encoder runtime. No GPU/paid service is required. First ONNX use downloads the public pinned quantized MiniLM (~23 MB) and tokenizer to `NEXUS_MODEL_CACHE_DIR` (default `data/models`). Models load lazily, two CPU threads and batch eight. Set `HF_HUB_OFFLINE=1` after caching. ARM/Linux fresh-install compatibility is not claimed as tested; the verified host is Windows AMD64.

Before upgrading, stop the API and back up `data/` as a unit. Migration 0003 adds FTS5, vault/graph/sync/index tables and citation snapshots; it does not rebuild or wipe the Phase 1 parent tables. Startup adopts a compatible legacy namespace and schedules a replacement if desired embedding config differs. Per-workspace index choices persist and take precedence over server defaults. Rebuild/validation/cancel/rollback progress is visible in Settings. Retired namespaces are retained intentionally; do not manually delete an active or referenced namespace.

Schema downgrade is deliberately refused before any destructive operation; restore the stopped full data backup instead. This is separate from supported embedding-index rollback through the API. The upgrade path from an actual 0002 schema, including existing citations and FTS backfill, is regression-tested.

Folder sync runs only while the explicitly invoked local CLI is running; ZIP snapshots are manual. See `docs/OBSIDIAN_SYNC.md`. Keep exactly one API process per data directory. Native SVG graph subsetting avoids rendering every note of a large vault. Public hosting, authentication, distributed queueing, daemon/service installation and parser process isolation remain outside Phase 2.

Use the root PowerShell scripts and `.env.example`. Servers bind to 127.0.0.1. No Docker or external database is required. The web uses `NEXT_PUBLIC_API_URL`; root `scripts/web.ps1` loads that one public setting into Next's process. Manual `npm run dev` uses `http://localhost:8000` by default; put a different public API origin in `apps/web/.env.local` if starting Next manually. CORS must include the actual browser origin.

For a local production frontend: `cd apps/web; npm run build; npm start`. Build-time public environment values are embedded into the browser bundle. The Python API still runs one worker. Use a Python virtual environment. CPU PyTorch wheels avoid Linux CUDA downloads; dependency resolution can be large despite the small embedding model.

Startup runs Alembic to head and verifies SQLite/Chroma creation. `/health` performs SQLite and vector reads and reports file writability, active embedding adapter and worker liveness without secrets or absolute data paths. The first model load is lazy on ingestion/query. A model-download failure need not stop the HTTP server; the failed job is visible and retryable.

The worker recovers processing jobs on restart. Repeated index jobs overwrite the same stable Chroma IDs. A desired embedding-config change schedules a separate versioned namespace and resumable rebuild; activation follows exact chunk-coverage validation. Deleting a document cleans vectors across namespaces. Failed cleanup remains a deleting record with an error and can be retried. After a crash between file creation and SQL commit, a UUID-named unreferenced original can remain; inspect against `documents.storage_key` while stopped before manual cleanup. Do not delete unknown files based on user-controlled paths.

For local SQLite backups, stop both servers and copy all of `NEXUS_DATA_DIR` (including SQLite WAL files if present). Restore it as one unit.
