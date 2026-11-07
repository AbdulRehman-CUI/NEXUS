# Security boundary and known limits

## Personal BYOK

See [BYOK ownership, credential encryption, operator trust and backup rules](BYOK_SETUP.md). Personal configurations use AES-256-GCM and a runtime master outside the database, with owner/configuration/provider/destination authentication. API operations never return keys and do not grant administrators access to another account's personal configurations. Password/session and workspace roles still apply. Local mode is explicitly one shared loopback installation owner.

Cloud inference requires personal destination consent plus workspace cloud permission. Custom endpoints are approved HTTPS origins with public DNS addresses pinned for TLS requests. Ollama cloud tags and remote-backed aliases are blocked before excerpt transmission. Streaming previews are provisional; saved citations still pass the existing verifier. Stopping delivery cannot guarantee provider-side cancellation or billing reversal. No live paid key was used in automated tests.

The runtime master and `.env` are excluded from Git and Docker build contexts. Keep key backups separately protected; local credential removal is not provider revocation or forensic erasure of historical encrypted WAL/backups.

## Existing boundaries

Current Phase 3 adds an authenticated server profile: salted scrypt passwords, random hashed-token expiring sessions, secure cookies, logout/reset/disable revocation, session-bound CSRF and centralized owner/editor/viewer membership checks. Local mode stays anonymous but rejects non-loopback peers/hosts. Global defaults require a server administrator; workspace owners control policies/members/diagnostics/exports. See [current threat model and residual risks](THREAT_MODEL.md). The following Phase 2 storage/content boundaries are preserved; references to its prior no-auth scope describe local mode only.

Phase 2 extends these boundaries without adding multi-user auth. Both FTS5 and Chroma apply the same authorized current-document set before ranking; SQL then verifies workspace, version, note/content hash and exact source span. Graph, note, backlink, unresolved-candidate, manifest and generation endpoints all require workspace scope. A stale note revision never resolves to new content. Historical citation metadata is retained with explicit unavailable flags.

Vault archives are read into bounded regular-file staging, never extracted using supplied paths. Paths/devices/traversal/symlinks/special entries/link-bearing metadata, case/NFC collisions, ratio/count/size violations and unsafe YAML are rejected. External embeds/URLs are not fetched or rendered. Model/document text never becomes system/developer instructions. Native SVG/React text escaping prevents executing hostile HTML labels. Tests cover malicious YAML, instructions, links and source references; they do not prove perfect cloud prompt-injection resistance.

The folder agent is explicitly launched with an approved root, rejects symlinks/junctions/hardlinks and changing files, uses no-follow opens where supported, restricts its API origin to loopback and disables environment proxies. It is not a hardened sandbox against malicious local directory-replacement races. No HTTP endpoint reads arbitrary local folders. Snapshot staging and index validation are retryable; old active indexes stay available on failed migration. Optional reranking is local and cache-only by default. Default ONNX inference uses a pinned public model with no remote code execution and no generative cloud call.

New Python dependencies are existing CPU runtime/tokenizer dependencies promoted to direct pins plus safe PyYAML; the default profile does not install PyTorch. Model weights are ignored local data, not credentials or source artifacts. No new server logs contain private passages. Diagnostics are workspace-scoped and may contain the user's reformulated question; they are not public analytics.

Local mode is **single-user**: a loopback caller can list local workspaces. Server mode requires authenticated membership for workspace/source/search/graph/vault/job/chat/settings access; workspace IDs remain scopes, not access tokens. Neither profile encrypts data at rest. Server deployment requires TLS, exact hosts/origins, protected volumes and egress/backup controls; tests do not establish tenant-grade certification.

Implemented boundaries:

- Every resource endpoint requires workspace scope; SQL lookups verify ownership; Chroma applies metadata filters before retrieval. SQL revalidates every vector hit and source span. Documents/jobs/chats/messages/citations carry workspace IDs.
- Uploads reject folder/path characters, control characters, unsupported extensions, invalid MIME/signatures, empty/binary/non-UTF-8 text, and oversized files. PDFs are parsed by PyMuPDF; originals use generated UUID keys. Storage paths are resolved and checked under a fixed root, including symlinks. Atomic writes use unique temp names, flush/fsync, and rename.
- A bounded job queue and one worker limit simultaneous ingestion. Extracted text/page counts and embedding batches are bounded. PDF parsing still occurs in-process; a hostile compressed PDF may consume resources before post-extraction limits. Use trusted personal documents until parser subprocess isolation is added.
- File deletion is a persisted job. A deleting document is excluded from retrieval. Vectors across all index namespaces and the original file are removed before SQL is deleted. Cleanup is idempotent; failures stay visible and can be retried by Delete in the library. Processing jobs are recovered at startup. Do not run multiple API processes.
- Cloud consent defaults off per workspace. Keys come from the server environment, are never persisted in SQL/provider.json, are never returned in settings/health, and provider error bodies are not forwarded. The Groq endpoint is fixed HTTPS and redirects are disabled. No automatic paid/provider fallback exists.
- Mutating browser requests with an unapproved Origin are rejected in addition to CORS. A localhost Host allowlist reduces DNS-rebinding exposure. These checks do not supply authentication or defend against malicious local software.
- Document text is escaped in the browser and treated as untrusted data in cloud prompts. No raw HTML/Markdown execution or agent tools. Plain-text originals download as text attachments; PDF originals use their MIME type with nosniff.

Do not put keys in `NEXT_PUBLIC_*`, commit `.env`, or commit `data/`. Git ignores credentials and local data. The server does not log document bodies or raw provider errors. Back up SQLite, Chroma, originals and non-secret provider settings together while stopped. There is no telemetry added by NEXUS; Chroma anonymized telemetry is disabled. Model/package downloads and your configured cloud provider involve their own networks and policies.
