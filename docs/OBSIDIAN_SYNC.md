# Obsidian import and synchronization

## ZIP snapshots

Import a regular, unencrypted ZIP in **Obsidian vaults**. Paths are preserved as normalized relative note paths; storage uses unrelated UUID filenames. Only `.md` notes are ingested. `.obsidian`, `.git`, `.trash`, `__MACOSX`, `node_modules`, OS metadata and configured temporary patterns are ignored. Plugin/config content is never executed. The ZIP may contain attachments, but Phase 2 does not index or render them; their embeds remain unresolved.

A ZIP is **a snapshot**, not a watched folder. **Update snapshot** submits the next complete manifest. Omitted notes are deletions, including an explicitly empty updated snapshot. The server compares path + SHA-256, stages only changed bytes, and runs a persisted `SyncRun` through the existing single worker. Unchanged imports reuse the completed run. A unique old/new content-hash match preserves the stable note ID on rename; ambiguous duplicate-content renames are not guessed.

Limits default to 2,000 archive entries, 2 MB per file, 20 MB total uncompressed data, 20 MB upload and 100:1 expansion. Limits include ignored entries. Absolute/drive/device paths, `..` entries, backslashes, control characters, case/NFC collisions, symlinks, special files, link-bearing/unrecognized ZIP extra metadata, encrypted archives and invalid UTF-8 are rejected before staging. Files are read with bounded streams; archive paths are never passed to filesystem extraction.

## Approved local folders

The HTTP API does **not** accept a folder path. The user explicitly runs the dedicated local agent:

```powershell
.\.venv\Scripts\python.exe scripts/vault_sync.py --root 'C:\Notes\My Vault' --workspace WORKSPACE_ID --once
# Use the ID printed by the first scan for later runs:
.\.venv\Scripts\python.exe scripts/vault_sync.py --root 'C:\Notes\My Vault' --workspace WORKSPACE_ID --vault-id VAULT_ID --interval 15
```

On macOS/Linux use `.venv/bin/python` and a platform-native root. The default 15-second periodic scan is intentionally simple; it reads a bounded manifest and transmits a snapshot only when content changes or a browser rescan is requested. `--once` exits after submission, not after background indexing; inspect the vault manager or sync-status endpoint for completion. Stop the foreground agent with Ctrl+C. **Request agent rescan** is picked up by a running agent; it does not start one or grant browser filesystem access.

The scanner rejects symlinks/junctions, hardlinks, special files, out-of-root resolutions and files that change during reading. Linux uses `O_NOFOLLOW` where available. The HTTP origin is restricted to localhost/127.0.0.1. It does not execute scripts, plugins or document instructions. Race resistance against a hostile local process replacing directories is not a hardened filesystem sandbox; parser/scanner process isolation remains Phase 3.

## Note and relationship model

Each `Note` has its own stable ID, vault/path/hash/tags/metadata and a pointer to an immutable content `Document`. Distinct notes with identical bytes may share a document while retaining distinct IDs/paths/graph relationships. This reuses Phase 1's unique workspace/content-hash constraint without rebuilding its parent table. Citations include both content document/version and logical note identity/path.

Safe YAML frontmatter supports title, aliases and scalar/list tags; anchors, aliases/expansion and unsafe object tags are rejected. Unknown properties are ignored. Inline tags, ATX headings, simple fenced code, wikilinks, `[[Note|Display]]`, ordinary Markdown links, embeds and simple heading/block anchors are parsed. Resolution order is same-folder relative path, vault-root path, then unique basename. Duplicate basenames are ambiguous. Frontmatter aliases are recorded; they are not invented destinations. External URLs are recorded as external and never fetched. Unsafe schemes and escaping paths are blocked. Missing notes/anchors remain explicit.

The graph stores directed authored note links plus normalized tag memberships. There are no AI-inferred edges. The API filters scope before returning nodes, links, backlinks or unresolved candidates. The explorer defaults to 150 notes, supports 75/150/300-note subsets, and includes at most an additional equal number of tag nodes. It has pan/zoom, filters, source navigation and a keyboard-friendly node list. Counts describe the filtered subset, not a fabricated full rendering of a large vault.

## Consistency and failure handling

Manifest preparation marks changed notes pending and deleted notes deleted **before** indexing, so old passages stop satisfying the authoritative SQL filters immediately. Content-hash guards prevent an older queued reindex from restoring a superseded revision. Immutable content documents and cursor/checkpoint updates make replay idempotent. The worker processes document jobs before further sync steps, then resolves graph edges and commits last-successful-scan/counts.

Processing runs resume after restart. A failed run keeps staged inputs for explicit retry, capped at three attempts. A replacement manifest supersedes failed runs; successful completion cleans obsolete staging. Failed note jobs are retried through the same source pointer. Filesystem write/cleanup failures remain visible. Deletion uses the persisted cleanup queue across SQL/FTS/vectors/files; source snapshots become unavailable, never redirected to a new note version. Historical quote metadata remains in chat snapshots, even after live citation rows are cascaded away.

If a sync fails: inspect the note's ingestion error, fix permissions/runtime or the source file, then retry or upload a corrected complete snapshot. For an agent permission/conflict warning, fix the approved root and let the next scan run. Do not point the agent at an untrusted concurrently mutated directory. ZIP parsing is bounded, but still runs in the local API process.
# Phase 3 identity and cancellation

Noninteractive automation may explicitly add `--password-stdin` with `--username` and pass one password line through a protected pipe. Default interactive prompting is masked; never embed production passwords in scripts, arguments or shell history. Windows automation verification used synthetic credentials through this explicit stdin path.

Server mode requires workspace editor/owner membership for import/sync. The explicitly loopback agent accepts `--username`, prompts for a password, retains only an expiring session in memory and sends its CSRF header; no key/password is saved or placed in CLI arguments. Start with an allowlisted explicit `--root`, reuse the printed vault ID, and stop the process to disconnect. If the session expires, stop/reconnect. Local mode still needs no account. There is no remote arbitrary-folder HTTP reader.

Diagnostics exposes step-boundary sync cancellation. Completed notes remain current; pending notes are failed/retryable, older jobs cannot revive superseded content. Cancelled snapshots can be retried within the existing bound or replaced by a complete next snapshot. ZIP snapshots are still not live folder watches.

