# API contracts — Phase 2 (Phase 1 routes preserved)

## Phase 3 identity and release additions

Local profile preserves existing routes. Server profile requires the HttpOnly session cookie for every route except minimal `/health` and `/api/auth/login`; browser mutations additionally require the `X-CSRF-Token` returned by login/me. Explicit Origin/CORS/Host checks apply. Workspace admission/central Repository require membership; viewer reads/searches, editor mutates sources/chats/jobs, owner manages settings/members/indexes/diagnostics/exports/comparison. Global legacy settings require server admin. Missing membership is 404; insufficient role 403; missing/expired identity 401; rate/quota limits 429. `X-Request-ID` correlates safe diagnostics. No raw secrets, full query URLs or excerpts are logged.

| Method / path | Contract |
| --- | --- |
| GET /api/auth/me | profile, safe user identity, session-bound CSRF; local has no account |
| POST /api/auth/login | `{username,password}` → expiring opaque cookie + safe identity/CSRF; no public signup |
| POST /api/auth/logout | 204, revoke session |
| GET/PUT /api/workspaces/{id}/members | owner list or `{username,role}` add/update; last owner cannot be removed |
| DELETE /api/workspaces/{id}/members/{user_id} | owner revoke, 204 |
| GET /api/models | durable adapters/capabilities/schemas/privacy/installed/configured status; no automatic inference |
| GET/PUT /api/workspaces/{id}/route-policy | validated provider/model/preset/destination consent/paid/free flags/daily cap/output/timeout; retries=0 |
| POST /api/workspaces/{id}/provider-check | check saved provider catalog without passages; reachability is not quota/billing proof |
| GET /api/workspaces/{id}/jobs | bounded limit (1–100) and offset; actual persisted jobs |
| POST /api/jobs/{id}/{retry\|cancel}?workspace_id=… | bounded failed/cancelled retry; only queued ingestion cancellation |
| POST /api/workspaces/{id}/batch-reindex | `{document_ids:[…]}` up to 100, authorize all before admission, per-document accepted/error results |
| POST /api/vaults/{id}/cancel?workspace_id=… | stop queued/processing sync at a step boundary; partial current notes remain |
| GET/DELETE /api/workspaces/{id}/diagnostics | owner timings/errors/queue/usage; clear retained records while keeping today's budget counters |
| POST /api/messages/{id}/feedback?workspace_id=… | `{rating,comment?}`; assistant messages only |
| GET /api/workspaces/{id}/reviews | owner private feedback and saved chat IDs |
| POST /api/workspaces/{id}/compare | owner `{question,filters?,policies:[policyA,policyB]}`; same retrieved evidence, separate verified answers or unavailable state; no fallback |
| GET /api/workspaces/{id}/settings-export | schema v1 retrieval/generation/index reference; no keys/paths or transferable remote/paid consent |
| POST /api/workspaces/{id}/settings-import | typed export body; clears cloud/paid consent; index reference does not auto-rebuild |

DOCX is now supported in upload/type filters and remains an attachment download; no invented page numbers. OCR runs only under operator opt-in and limits. Token usage records distinguish provider-reported vs estimates; price/TTFT are null when unavailable. Original chat API remains non-streaming. Server `/health` before login returns only status. Pydantic/OpenAPI is executable at `/docs` after authentication; model/policy/import inputs reject unknown fields.

## New typed surfaces

| Method / path | Request / result |
| --- | --- |
| POST /api/workspaces/{id}/search | `{query, filters?, options?, diagnostics?}` → typed results and optional diagnostics |
| GET/PATCH /api/workspaces/{id}/retrieval-settings | Full workspace settings; PATCH merges provided fields |
| POST /api/workspaces/{id}/vaults/import | Multipart ZIP `file`; optional query `name`, `source_kind=snapshot\|agent` → 202 vault + persisted run |
| GET /api/workspaces/{id}/vaults | Typed vault list with note/unresolved counts and scan status |
| GET /api/vaults/{id}/notes?workspace_id=… | `{notes,total}`; q/tag/prefix/offset/limit filters |
| GET /api/notes/{id}?workspace_id=… | Note + typed backlinks/outlinks; deleted note → 410 |
| GET /api/vaults/{id}/links?workspace_id=… | `{links,total}`; optional resolution-status/offset/limit |
| POST /api/vaults/{id}/sync?workspace_id=… | Multipart complete next ZIP snapshot, or no file to request a running agent rescan; snapshot without file → 409 |
| GET /api/vaults/{id}/sync-status?workspace_id=… | Vault + latest run/counts/cursor/attempts/errors |
| POST /api/vaults/{id}/retry?workspace_id=… | Retry latest failed sync; bounded to three attempts |
| GET /api/workspaces/{id}/graph | Typed nodes/edges/counts; optional vault_id/tag/kind/q/limit (max 300 notes) |
| GET /api/workspaces/{id}/index-versions | Workspace generation configurations/states/progress/active flag |
| POST /api/workspaces/{id}/indexes/rebuild | Embedding/index configuration overrides current config → 202 resumable build |
| POST /api/index-versions/{id}/{retry\|activate\|cancel}?workspace_id=… | Bounded retry, validated activation/rollback, or cancel inactive build |

All resource IDs are checked against the supplied workspace before data is returned. Existing `POST /chats/{id}/messages` now also accepts `filters`, `options`, and `diagnostics`. Options merge with workspace defaults; omitted options preserve them. Modes: semantic (actual active embedding), keyword (FTS5/BM25), hybrid (weighted RRF). Filters: `document_ids[]`, `vault_id`, `path_prefix`, `tags[]` (any), `types[]` (`.pdf/.md/.txt`); filter categories combine with AND.

```json
{
  "query": "When does Aurora launch?",
  "options": {"mode": "hybrid", "candidate_count": 15, "top_k": 5, "rrf_constant": 60},
  "filters": {"vault_id": "vault-uuid", "tags": ["launch"]},
  "diagnostics": true
}
```

Search results add `score`, `source_span_id`, logical `note_id`, `vault_id`, `path` and tags to source/version/locator/excerpt metadata. Score is final RRF/reranker rank, not a probability. Diagnostic stages name BM25/cosine/cross-encoder scores separately and include candidate counts, current index identity, local rewrite/variants, total elapsed time, warnings and zero extra cloud-call accounting. Server logs exclude excerpts/query text. Search source URLs use a checked `chunk_id`; saved citations add their server-generated `citation_id`.

Source endpoints now accept `note_id` and `chunk_id`; they verify document/version/note/hash consistency. Historical unavailable citations return 404/410 and chat snapshots include `available:false` with a reason. Changing only an embedding generation preserves current source citations. Deleting a document removes live citation rows while retaining unavailable snapshot metadata.

Index config: `embedding_provider=onnx|hash|sentence-transformers`, model identifier, immutable 40-character revision, dimension, ONNX artifact path, `normalization=l2`, `preprocessing=normalized-v1`, chunk size/overlap. Generations transition building → validating → ready/active, or failed; prior validated generations become retired. Cancelled builds are failed and cannot be activated. Coverage/version mismatch rejects rollback with 409. No index activation silently changes generation-provider privacy/cost settings.

The original routes below remain compatible; their document/job lifecycle is supplemented by durable vault and index records.

FastAPI OpenAPI at `/docs` is the executable schema. JSON unless noted; errors use `{ "detail": "actionable message" }`. Validation failures use FastAPI's typed detail array. Resource endpoints require `workspace_id` query scope; workspace-owned list/create endpoints carry scope in their path. Cross-scope/missing resources return 404. No authentication is implemented.

| Method / path | Request / result |
| --- | --- |
| GET /health | storage and worker readiness; indexed_chunks counts SQL chunks in active workspace generations, no paths/secrets |
| GET /api/workspaces | workspace list (one local Personal workspace is created initially) |
| POST /api/workspaces | `{name}` → 201 workspace |
| PATCH /api/workspaces/{id} | optional `{name, cloud_opt_in}` → workspace |
| GET /api/workspaces/{id}/documents | document list with ingestion status/errors |
| POST /api/workspaces/{id}/documents | multipart `file` → 202 `{document, job_id, duplicate}`; duplicate returns same document/job |
| GET /api/documents/{id}?workspace_id=… | document, jobs, chunk_count, needs_reindex |
| POST /api/documents/{id}/reindex?workspace_id=… | 202 persisted job; queued/processing retry is idempotent |
| DELETE /api/documents/{id}?workspace_id=… | 202 delete job; document becomes deleting, then 404 after cleanup |
| GET /api/jobs/{id}?workspace_id=… | persisted status/error/attempts; document deletion cascades jobs, so completed delete job becomes 404 |
| GET /api/documents/{id}/source?workspace_id=… | `{document, spans[], citation, file_url}`; optional page/heading/citation_id locates exact evidence; 404 if unavailable |
| GET /api/documents/{id}/file?workspace_id=… | scoped original; PDF inline, UTF-8 text attachment |
| GET /api/workspaces/{id}/chats | newest-first chat list |
| POST /api/workspaces/{id}/chats | no body → 201 chat |
| GET /api/chats/{id}?workspace_id=… | chat with ordered messages and each message's live citations |
| PATCH /api/chats/{id}?workspace_id=… | `{title}` → renamed chat |
| DELETE /api/chats/{id}?workspace_id=… | 204; messages/citations cascade |
| POST /api/chats/{id}/messages?workspace_id=… | `{content}` → assistant message + answer + citations; non-streaming |
| GET /api/providers | implemented providers, safe configuration availability, privacy details; no network call |
| POST /api/providers/groq/check | explicit network model-list check, no excerpts; safe model availability result |
| GET /api/settings/public | safe model/index config, key-present boolean, disclosures; never secret values |
| PATCH /api/settings/public | `{generation_provider: "mock"|"groq", generation_model, free_tier_confirmed}`; persists non-secret settings |

Message result:

```json
{
  "id": "message-uuid", "workspace_id": "workspace-uuid", "chat_id": "chat-uuid",
  "role": "assistant", "provider": "mock", "created_at": "ISO timestamp",
  "content": "Offline demo … [C…]", "answer": "Offline demo … [C…]",
  "citations": [{
    "citation_id": "C…", "workspace_id": "workspace-uuid",
    "document_id": "document-uuid", "document_version_id": "version-uuid", "chunk_id": "sha256",
    "title": "notes.md", "page": null, "heading": "Project / Launch",
    "start": 0, "end": 36, "excerpt": "An actual normalized source substring",
    "source_url": "/api/documents/document-uuid/source?workspace_id=workspace-uuid&citation_id=C…"
  }]
}
```

No evidence returns a saved insufficient-evidence answer with empty citations and makes no cloud call. Consent failures are 403; missing keys/free confirmation/unreachable cloud are 503; quotas are 429; unknown model-created citations are 502; sources changed during generation are 409. Generation failures do not save a partial turn. User/assistant turns are persisted together after verification.

Ingestion state sequence: queued → processing → ready / failed / needs_ocr. Reindex queues a fresh job with stable IDs. Delete uses a persisted `kind=delete` job and document state deleting; failed cleanup remains explicit, invisible to retrieval, and retryable. Upload returns 413 on size limits or 415 on unsupported/signature/encoding validation. PDF extraction failures appear asynchronously on document/job records.
