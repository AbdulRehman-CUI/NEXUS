# Troubleshooting and low-resource operation

| Symptom | Action |
| --- | --- |
| Cannot connect / retry screen | Start the API and web scripts from the repository root. Confirm `/health`. Use matching browser/API hostnames (`127.0.0.1` consistently), exact CORS origins, and rebuild after changing a public API URL. |
| Server login will not retain a session | HTTPS requires Secure cookies. Only explicit loopback HTTP testing may set `NEXUS_SECURE_COOKIES=false`. Cross-site cookies are intentionally Strict; use the same site/reverse proxy and credentials-aware CORS. |
| No workspaces after switching to server | Expected: legacy workspaces are unclaimed. Stop API; an administrator may use `scripts/manage_users.py owner --admin --claim-legacy` when creating the account. A new account can create its own workspace and invite existing accounts. |
| Workspace 404 / role 403 | A workspace ID is not permission. Ask its owner for viewer/editor/owner membership. Owners manage settings; server administrators manage global defaults/accounts. |
| CSRF error / expired session | Reload for the session-bound CSRF token, or sign in again. The CLI agent's server session also expires; stop and reconnect with `--username`. |
| Missing/disabled provider | Configure the server environment key and operator paid allowlist if applicable, restart, then save workspace destination/cloud consent. Check the saved connection explicitly. No key is displayed in UI/export. |
| Quota/timeout | Wait or deliberately change the saved policy. No automatic retry/provider fallback occurs. A timeout may already consume provider usage. Daily attempt caps survive diagnostic deletion. |
| Index integrity warning / no vector store | Preserve the directory, inspect storage, then build a replacement from original files or restore a verified backup. Failed rebuilds keep the previous ready index; do not manually remove namespaces. |
| Sync snapshot missing notes | A ZIP is a complete snapshot: missing paths are deletions. Use the agent for a live folder and reuse its vault ID. Cancelled sync may have completed some notes; retry or upload a complete replacement. |
| OCR needed | Default has no OCR requirement. Install Tesseract and English tessdata, set `TESSDATA_PREFIX` and explicitly enable `NEXUS_OCR_ENABLED=true`; keep the OCR page/time budget small. No OCR output is claimed without the binary. |
| DOCX malformed / embedded images absent | Export a valid DOCX/PDF/Markdown. NEXUS indexes DOCX text/headings/tables only; no field execution, image understanding, external-link fetch or fabricated page numbers. |
| Data directory in use | Stop the one API process before backup/account maintenance. Locks release on process exit; the `.nexus.lock` file's presence alone does not mean an active process. Do not delete lock files as a bypass. |
| Disk full / install fails | Free several GB first. Stop writes, preserve originals/backups, remove only disposable build/test caches. Model cache is ~23 MB; Python/Node dependencies and compiled development tools are much larger. Do not delete Chroma/SQL independently. |

Low-RAM defaults: one API worker, one ingestion worker, two embedding threads, batches of eight, no cross-encoder/OCR/Ollama, 15 retrieval candidates and a bounded context. CPU inference is real; the optional hash profile tests plumbing only. Do not add worker processes against one data directory. The 100-document measurement is a sequential feasibility result, not a memory/concurrency capacity guarantee.

If installing mypy on a very low-disk Windows machine, the pure-Python wheel is smaller than its compiled wheel. The provided type-check wrapper disables persistent cache writes. Static checking currently covers configuration/contracts; dynamic service paths are covered by tests, not a claim of repository-wide strict typing.
