# Executable backup and restore

Stop the API before backup. The OS data lease prevents an updated API, another backup or account-maintenance command using the same directory concurrently. Old Phase 1/2 binaries do not know this lease, so stop those explicitly too. Never copy a live multi-store data directory as a consistent backup.

PowerShell at repository root:

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m nexus.backup backup --data data --output artifacts/backups/nexus-2026-11-04.zip
.\.venv\Scripts\python.exe -m nexus.backup restore --archive artifacts/backups/nexus-2026-11-04.zip --target artifacts/restored-nexus
# To inspect an isolated restore without touching normal data:
$env:NEXUS_DATA_DIR='artifacts/restored-nexus'
.\scripts\api.ps1
```

Unix: `PYTHONPATH=apps/api .venv/bin/python -m nexus.backup backup --data data --output backups/nexus.zip`, then use the same module's `restore --archive ... --target new-data` subcommand. Docker: stop `api` and use `docker compose run --rm -v "$PWD/backups:/backups" api python -m nexus.backup backup --data /app/data --output /backups/nexus.zip`. Docker execution was not run on this host.

The archive covers SQLite users/memberships/chat/citations/FTS/vault/graph/index/policy/usage records, originals (including source DOCX/images in originals), Chroma files and non-secret legacy provider.json. It checkpoints WAL, runs SQLite integrity/FK checks, includes a schema-version/hash/length manifest, refuses symlinks/junctions/hardlinks and excludes arbitrary operator files, `.env`, session cookies and absolute local vault roots. Public downloaded models are excluded by default; add `--include-models` for a fully cached/offline model restore. Model identity is in index metadata either way. Restore may need the pinned public model cache/download if not included.

Restore requires a nonexistent destination. It rejects traversal/device/link/duplicate archive entries, verifies every file before writing, sets an incomplete-restore marker while copying, checks SQL integrity and schema identity, and revokes all saved sessions. The API refuses an incomplete restore. Bad checksums write nothing. Failed partial output remains visibly blocked; investigate it or restore again into another new directory. No command overwrites or recursively deletes the original directory.

Backups contain confidential documents and password hashes. They are **not encrypted by NEXUS**. POSIX mode 0600 is applied; Windows inherits the destination ACL. Use a private destination, OS encryption and an explicitly managed encrypted/offsite backup policy. Keys are excluded; record and rotate secrets separately. Restored settings do not recover environment keys. Keep schema downgrade separate from index rollback: migrations refuse destructive downgrade; restore a verified older stopped backup instead.

Executed isolated restore test verifies source citation URLs, saved chat, files, keyword and semantic retrieval, graph notes/links and sync status; corrupt archive and live-backup refusal tests pass. This is not evidence of an offsite disaster-recovery drill or a restore on a second machine.
