# Data model

## Phase 2 additions (migration 0003)

| Table / field | Role |
| --- | --- |
| workspaces.index_configuration | Persisted explicit embedding/index preference; null uses server defaults |
| documents.origin | Upload versus vault content; preserves Phase 1 workspace/hash uniqueness |
| messages.evidence_snapshot / diagnostics | Historical citation metadata and optional retrieval explanation; unavailable sources remain marked |
| retrieval_profiles | Per-workspace validated retrieval strategy/resource/evidence settings |
| vaults | Workspace/name, snapshot or agent kind, scan requests/status/errors/timestamps |
| notes | Stable logical ID, vault/path/hash, current immutable document pointer, status/deleted flag, tags and parsed metadata |
| note_tags | Normalized workspace/note/tag memberships |
| note_links | Directed authored source/target IDs, link kind/anchor, resolution status and authorized ambiguous candidates |
| sync_runs | Durable snapshot hash, staged changed-note manifest, cursor, create/update/rename/delete counts and bounded attempts |
| index_generations | Workspace, namespace/fingerprint/config, building/validating/ready/failed/retired state, unique active row, document-version checkpoint/progress |
| chunk_fts | FTS5 text/title/path/tag metadata plus unindexed scope/document/version/fingerprint keys; synchronized by SQL triggers |

All new resource entities are workspace-associated and use constrained foreign keys. A partial unique SQL index permits only one active generation per workspace. No existing parent table is recreated or cleared. Existing citations are backfilled into message snapshots. Distinct vault notes with identical bytes share an immutable content document but retain their own note IDs/paths/relationships. After an edit, the note points to a different content document; unreferenced vault content is queued for cleanup.

| Table | Purpose / key invariants |
| --- | --- |
| workspaces | UUID, name, explicit cloud_opt_in=false, creation timestamp |
| documents | workspace_id, title, extension, SHA-256 hash, unique storage key, immutable content version UUID, size, status/error, active index fingerprint; unique workspace/hash |
| spans | workspace/document/version, ordinal, PDF page or Markdown heading path, normalized stored source text |
| chunks | workspace/document/version/span, exact start/end offsets in normalized span, excerpt, index fingerprint; deterministic SHA-256 ID |
| jobs | workspace/document, index/delete kind, queued/processing/ready/failed/needs_ocr/cancelled status, attempts, error |
| chats | workspace, title and creation timestamp |
| messages | workspace/chat, monotonic per-chat position, user/assistant role, content, provider label and timestamp |
| citations | workspace/message/document/chunk, server-created citation ID, immutable serialized evidence metadata |

SQLite foreign keys are on, deletes cascade, WAL is enabled, resource lookups require workspace ID. Files have random UUID names under the configured originals directory; user names are display metadata only. Document version means immutable uploaded bytes; reindexing does not invent a content revision. A new hash creates a new document in Phase 1.

Chroma collection namespaces are hashes of the embedding fingerprint, chunk configuration and parser version. Nodes contain workspace/document/version/fingerprint metadata and stable SQL chunk IDs. Both Chroma and SQL filter the workspace and active fingerprint. SQL also checks ready status/version. Old namespaces cannot enter current retrieval.

Reindex merges stable spans/chunks. Same-configuration reindex preserves IDs. Phase 2 retains chunks from retired index fingerprints, so a model change does not break an otherwise current source citation. Deletion cascades live rows, while message snapshots retain metadata marked unavailable. A note revision/deletion or pending content hash never silently resolves to a different revision. Raw historical originals are not retained once unreferenced vault content cleanup finishes; a configurable archival retention policy remains Phase 3.
# Phase 3 additions (migration 0004)

`users` stores unique usernames, salted scrypt password hashes, administrator/disabled flags; `memberships` has a composite workspace/user key and constrained owner/editor/viewer role; `auth_sessions` stores hashed opaque tokens/user/expiry, never raw cookies. Existing workspaces receive no guessed owner. Administrator CLI can explicitly claim only unowned legacy workspaces.

`model_registry` stores adapter capability/schema/privacy metadata; `route_policies` stores one validated generation policy per workspace. `usage_events` records reservations/results, provider/model, elapsed time and estimated/reported token counts. `request_events` records correlation ID, opaque user/workspace IDs, route template/method/status/latency/time, never full URLs or excerpts. `feedback` references an assistant message and stores explicit private rating/comment; owners can review it with its saved chat ID. These additions preserve all existing parent records and FTS triggers. Downgrade refuses destructive removal; restore the stopped older backup instead.

