# Phase 1 decisions

## Phase 2 decisions

- FTS5 SQL triggers keep lexical content/metadata in the same transaction as source rows. An interface permits a later PostgreSQL FTS implementation.
- Weighted RRF provides a deterministic, inspectable fusion rule without a new rank-model dependency. The measured small corpus does not show a general hybrid advantage.
- ONNX MiniLM is the default real CPU embedding adapter, reusing already-installed runtime/tokenizer dependencies and a ~23 MB published quantized artifact. The PyTorch adapter and optional cross-encoder remain available separately. Hash mode is explicitly a plumbing demo.
- Local heuristic follow-up rewriting and bounded variants avoid hidden additional cloud calls. No cloud rewrite, hosted reranker or inferred graph edge is claimed.
- Stable logical Note IDs point to immutable content Documents, allowing identical-byte notes without rebuilding Phase 1's unique hash parent table. A source revision revokes stale citations; archived quote metadata remains, originals do not.
- Full ZIP snapshots and an explicit periodic folder CLI replace browser filesystem pretending. Only changed notes are staged/indexed. Rename identity is preserved only for unique matching hashes.
- Relational authored links/tags feed a bounded native SVG graph with a keyboard list. No graph database or visualization dependency is required.
- Per-workspace index generations preserve old readiness while building, validate coverage, and atomically activate; safe retired generations can be rolled back. Invalid or cancelled builds never become active.
- Single API worker/local lock and non-streaming validated responses remain intentional Phase 1 constraints. Auth/distributed workers/parser sandboxing/OCR/public deployment remain Phase 3.

| Decision | Reason / ceiling |
| --- | --- |
| Single API process, one DB-backed worker, local lock | Recoverable queue on low-spec hardware; multi-process leases and parser subprocesses are Phase 3 |
| SQLite + Chroma + local originals | No mandatory infrastructure or services |
| Pinned direct dependencies + tested full resolution | Reproducible install; versions verified from registries, compatibility determined by actual checks |
| Protocol adapters only where requested | Generation, embeddings and vectors have actual replaceable implementations; no speculative provider stubs or generic service framework |
| Groq + explicit eligible-free assertion + per-workspace consent | One real cloud adapter; app cannot inspect billing tier; never auto-switches endpoints |
| Mock default; MiniLM semantic embedding default | No key required; honest extractive demo, real local retrieval; hash adapter for offline tests |
| Immutable content version per upload hash | Simple duplicate semantics and stable citations; editing/version history is deferred |
| Character-based LlamaIndex splitting | Offline-safe tokenizer, exact normalized-source offsets, small MiniLM passages |
| UTF-8 excerpt-byte context budget | Conservative excerpt token bound with no tokenizer asset downloads; envelope/question budget separate |
| Server-generated citations, unknown IDs rejected | Prevent invented source IDs; no claim of semantic entailment verification |
| Non-streaming Phase 1 responses | Fully validated answer/citations before display; SSE/provider streaming deferred rather than simulated |
| Native browser PDF viewer and dialog | Page navigation and accessible modal focus without heavy viewer dependencies |
| Safe settings stored locally, keys in env only | Browser config usable without persisting keys or adding secret-management infrastructure |
| No auth/users/membership in Phase 1 | Explicit local scope; real authentication is mandatory before public/multi-user deployment |
| No DOCX/OCR/vault watcher/hybrid retrieval | Explicit unsupported or needs-OCR states; Phase 2/3 scope stays deferred |
# Phase 3 decisions

- Keep the existing CPU SQLite/Chroma stack and one worker. Add opaque server sessions and centralized memberships rather than introducing a paid identity dependency. Local loopback remains explicit. Legacy ownership requires an operator action.
- Use salted stdlib scrypt, random hashed session tokens, Secure/HttpOnly/Strict cookies and session-bound CSRF. Role checks run in Repository and HTTP admission; background jobs have explicit internal execution scope.
- Model routing is per workspace; paid operator allowlist and exact workspace destination consent are independent gates. Never retry an ambiguous timed-out generation or silently change providers. Unknown pricing stays unknown.
- Disposable parsing processes bound wall time and isolate parser crashes; Windows is not claimed to have a hardened OS sandbox. DOCX text/tables use bounded ZIP/XML; OCR is explicitly optional.
- Backups require stopped multi-store access and a hash manifest; restore targets must be new and sessions are revoked. Retired indexes are retained intentionally. No destructive downgrade or automatic garbage collection.
- Safe local request metrics use a short busy timeout off the event loop. Full-disk verification exposed why telemetry must not use a long SQLite writer wait in async middleware.
- Added no speculative retrieval cache: measured warm medians are already 59–87ms on 100 synthetic documents. Optimize only with a larger workload. No distributed worker/Redis/Postgres or hosted analytics is advertised as implemented.
- Keep verified non-streaming answers and mark first-token timing unavailable. Streaming, full strict Python service typing and optional live inference remain explicit incomplete/deferred items, not simulated features.

