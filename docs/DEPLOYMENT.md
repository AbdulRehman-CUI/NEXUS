# Local operation

## BYOK runtime secrets

Follow [BYOK setup](BYOK_SETUP.md) to create or inject the AES master. Persistent cloud-key storage fails closed without it. Keep the master outside `NEXUS_DATA_DIR`, separate from database backups, and readable only by the API service identity. The `.secrets` directory is excluded from Git and Docker builds. Containers must receive a separate read-only secret mount, for example `/run/secrets/nexus-byok-master`, and `NEXUS_BYOK_MASTER_KEY_FILE` must point to that mounted file; do not bake the host `.env` or key into an image.

Use HTTPS and secure cookies in the server profile, with trusted reverse-proxy forwarding and explicit hosts/origins. Disable response buffering for `/api/chats/*/messages/stream`; NEXUS supplies `X-Accel-Buffering: no`. Test metadata endpoints and a grounded answer after deploying each provider configuration. No cloud model, credential, public deployment or Ollama download is installed automatically.

## Phase 3 profiles and release operations

Run Windows `scripts/setup.ps1`, then `scripts/api.ps1` / `scripts/web.ps1`. Unix uses `sh scripts/setup.sh` and `sh scripts/run.sh api|web`. The CPU ONNX/model profile is unchanged. Static development checking additionally installs `requirements-typecheck.txt`; production Docker uses only the runtime CPU lock. Keep several GB free for a fresh install. Only Windows installed-runtime operation was executed; a fresh Linux/macOS install remains a release gate.

`NEXUS_PROFILE=local` rejects non-loopback clients/hosts. For network service use `server`, create accounts while stopped with `scripts/manage_users.py`, explicitly claim legacy workspaces if appropriate, configure TLS/reverse proxy and Secure cookies, exact allowed hosts/CORS origins, private persistent volumes, restricted egress and backup scheduling. Match frontend/API sites for Strict cookies; use a same-origin reverse proxy where possible. Disable URL query-string access logs (provided run scripts do). Forward only trusted proxy headers and apply perimeter request/login/body limits. NEXUS's in-process peer limiter is not a distributed firewall.

`docker compose config --quiet` and the `local-llm` profile config both validated. Default Compose publishes ports only on 127.0.0.1, uses authenticated server mode because Docker bridge peers are not loopback, keeps SQLite/Chroma/originals in one persistent volume and bounds memory/CPU/PIDs with non-root app users. Default generation is mock; CPU MiniLM weights may download on first use. Start with `docker compose build`, create the first account while API is stopped with `docker compose run --rm api python scripts/manage_users.py owner --admin`, then `docker compose up -d`. Default loopback HTTP demo explicitly disables Secure cookies; override to true behind production TLS. Public API origin is a frontend build argument; rebuild when changing it.

Ollama is behind explicit `--profile local-llm`; no heavyweight model is pulled. The optional service shares the API network namespace for literal-loopback access and has separate model storage. Operators must install a chosen model explicitly, then select Local Optional in workspace policy. Redis/PostgreSQL/distributed workers are not implemented, so no decorative unused services are included. Docker engine was unavailable on this host; image builds/container runtime have **not** passed validation. Hosted GitHub CI is prepared, not executed/published from this checkout.

Use [backup/restore](BACKUP_RESTORE.md), [provider guide](PROVIDER_GUIDE.md), [troubleshooting](TROUBLESHOOTING.md) and [release checklist](RELEASE_CHECKLIST.md). No public deployment was performed. All API processes/maintenance commands must share the OS data lease; a second process is rejected. Parser subprocesses have wall limits and Unix resource limits; Windows resource isolation is not a complete OS sandbox.

## Preserved Phase 2 CPU/storage notes

Phase 2 default setup uses the pinned ONNX CPU profile; `.\scripts\setup.ps1 -WithTorch` adds the optional larger sentence-transformers/cross-encoder runtime. No GPU/paid service is required. First ONNX use downloads the public pinned quantized MiniLM (~23 MB) and tokenizer to `NEXUS_MODEL_CACHE_DIR` (default `data/models`). Models load lazily, two CPU threads and batch eight. Set `HF_HUB_OFFLINE=1` after caching. ARM/Linux fresh-install compatibility is not claimed as tested; the verified host is Windows AMD64.

Before upgrading, stop the API and back up `data/` as a unit. Migration 0003 adds FTS5, vault/graph/sync/index tables and citation snapshots; it does not rebuild or wipe the Phase 1 parent tables. Startup adopts a compatible legacy namespace and schedules a replacement if desired embedding config differs. Per-workspace index choices persist and take precedence over server defaults. Rebuild/validation/cancel/rollback progress is visible in Settings. Retired namespaces are retained intentionally; do not manually delete an active or referenced namespace.

Schema downgrade is deliberately refused before any destructive operation; restore the stopped full data backup instead. This is separate from supported embedding-index rollback through the API. The upgrade path from an actual 0002 schema, including existing citations and FTS backfill, is regression-tested.

Folder sync runs only while the explicitly invoked local CLI is running; ZIP snapshots are manual. See `docs/OBSIDIAN_SYNC.md`. Keep exactly one API process per data directory. Native SVG graph subsetting avoids rendering every note of a large vault. Public hosting, authentication, distributed queueing, daemon/service installation and parser process isolation remain outside Phase 2.

Use the root PowerShell scripts and `.env.example`. Servers bind to 127.0.0.1. No Docker or external database is required. The web uses `NEXT_PUBLIC_API_URL`; root `scripts/web.ps1` loads that one public setting into Next's process. Manual `npm run dev` uses `http://localhost:8000` by default; put a different public API origin in `apps/web/.env.local` if starting Next manually. CORS must include the actual browser origin.

For a local production frontend: `cd apps/web; npm run build; npm start`. Build-time public environment values are embedded into the browser bundle. The Python API still runs one worker. Use a Python virtual environment. CPU PyTorch wheels avoid Linux CUDA downloads; dependency resolution can be large despite the small embedding model.

Startup runs Alembic to head and verifies SQLite/Chroma creation. `/health` performs SQLite and vector reads and reports file writability, active embedding adapter and worker liveness without secrets or absolute data paths. The first model load is lazy on ingestion/query. A model-download failure need not stop the HTTP server; the failed job is visible and retryable.

The worker recovers processing jobs on restart. Repeated index jobs overwrite the same stable Chroma IDs. A desired embedding-config change schedules a separate versioned namespace and resumable rebuild; activation follows exact chunk-coverage validation. Deleting a document cleans vectors across namespaces. Failed cleanup remains a deleting record with an error and can be retried. After a crash between file creation and SQL commit, a UUID-named unreferenced original can remain; inspect against `documents.storage_key` while stopped before manual cleanup. Do not delete unknown files based on user-controlled paths.

Backups: stop both servers and copy all of `NEXUS_DATA_DIR` (including SQLite WAL files if present). Restore it as one unit. There is no public deployment, cloud hosting, durable external worker, auth or automatic backup implementation. Keep the API on localhost.
