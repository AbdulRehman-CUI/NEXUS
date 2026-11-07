# NEXUS — Phase 3 release candidate report

Date: 4 November 2026. Release notes prepared as **0.3.0-rc.1**, unpublished. No public deployment, push, tag, paid inference call or user-data publication was performed. The three-phase implementation stops with this handoff; no further phase is proposed.

## Delivery and readiness

The existing application now has separate bounded local and authenticated server profiles, expiring opaque sessions and workspace roles; a durable model registry and per-workspace generation routing/consent/budgets; optional vendor adapters exercised with mocked contracts; disposable extraction processes, DOCX and optional OCR; recoverable job/sync controls; local redacted diagnostics, usage, feedback and identical-evidence comparison; settings transfer; stopped verified backup/restore; Docker profiles, CI and release documentation. Existing PDF/Markdown/TXT, citations, hybrid retrieval, vault sync, graph and index generations are preserved.

**Readiness: a locally verified release candidate with deployment gates outstanding, not a production-security certification.** Authentication, isolation, restore and offline inference have executable evidence. A fresh installation on another machine, hosted CI and Docker runtime remain unverified. Optional live API/OCR/Ollama/cross-encoder paths are disabled until deliberately configured and are not represented as live passing integrations.

| Workstream | Implemented | Deferred / blocked and remediation |
| --- | --- | --- |
| Identity/security | Local peer/host limits; server scrypt sessions, expiry/logout/disable/reset, CSRF, explicit roles, A/B route matrix, safe HTTP/error/rate boundaries | No MFA, public signup or email recovery. Add standards-based identity/MFA if the deployment requires it; validate intended TLS/proxy perimeter |
| Model control | Registry/schema/status, manual IDs, workspace policies, destination/paid gates, daily attempt and output/timeout budgets, no retries/fallback, mocked six-adapter contracts | Live accounts/hardware unavailable; validate only intentionally enabled integrations. Remote embedding/reranking and vendor tool/image capabilities are not advertised |
| Ingestion/jobs | Bounded parser process, existing safe ZIP/root checks, DOCX text/tables, optional page-limited OCR, queued cancellation, bounded retries, batch reindex, sync cancellation, missing-index warning/rebuild | OCR binary/output unverified. No multimodal image understanding or distributed queue. Windows process isolation is not an OS sandbox |
| Evaluation/operations | Fixed retrieval labels plus release scenarios; measured source/abstention checks; scoped request/usage/job diagnostics and feedback/comparison | Real-model entailment/abstention calibration remains incomplete; no external judge. Verified responses remain non-streaming; TTFT unavailable |
| Recovery/release | OS data lease, stopped multi-store backup, manifest/checksums, new-directory restore/session revocation, isolated restore tests; Compose syntax and pinned-action CI | Docker engine stopped; no image build/runtime, hosted CI run, separate-machine install or disaster-recovery drill. Run documented gates before deployment |
| UX | Login/logout, first workspace, model policy/membership, diagnostic/help/review flows, settings transfer, original design and responsive regression | No broad assistive-technology/WCAG audit; manually review intended browser PDF viewer and deployment accessibility |

## Baseline audit and risk priorities

Read the master reference, both earlier reports, README/environment, architecture/API/data/RAG/security/vault documents, migrations, lockfiles, tests and deployment scripts. Inspected actual main/Next entrypoints, providers, Repository, extraction/storage, worker/vault agent/graph, source resolver and index registry. Required prior documents were present; the master reference and historical reports remain intact.

Before edits: `python -m pytest apps/api -q --basetemp artifacts/phase3-baseline` with cached ONNX enabled: **55 passed, 1 optional PyTorch skip in 30.51s**. Ruff passed. Frontend typecheck/lint/build passed. Preserved browser flows: **2 passed in 21.8s**. No pre-existing failing test was recorded. Existing Phase 2 data was copied while stopped to ignored `artifacts/phase2-data-backup`.

Critical initial risks were anonymous reachable endpoints, absent memberships, generic cloud consent, possible cross-route privacy/budget bypass, inconsistent live backups and resource failures. The shared Repository and HTTP admission now enforce membership/role scope; all branches retain SQL/vector/source checks. An administrator does not automatically receive all workspace content. Legacy workspaces are unclaimed in server mode until an explicit stopped administrator command assigns them.

Residual risks are ranked in `docs/THREAT_MODEL.md`: high if TLS/proxy/local-profile exposure is misconfigured; medium/high native parser risk for hostile public intake on Windows without an OS sandbox; medium same-user disk/backup compromise, absent at-rest encryption, custom-provider DNS rebinding window, limited single-process rate limiting and imperfect real-model grounding. Mitigations include authenticated server mode, exact origins/hosts, protected volumes/encrypted offsite backups, egress controls, container/OS parser isolation and deployment-specific identity/perimeter review. No compliance claim is made.

## Files, data and compatibility

Main additions: `nexus/auth.py`, `http_boundary.py`, `gateway.py`, `routes_release.py`, `lease.py`, `backup.py`, `extract_worker.py`, `logging_setup.py`; changes in main/Repository/service/config/providers/extraction/storage/indexes/retrieval/contracts/database. Scripts add stopped account administration, Windows/Unix setup/run/check support, grounding evaluation, 100-document measurement and explicit synthetic server browser fixtures.

Frontend adds `auth-gate.tsx`, `release-controls.tsx`, `diagnostics-panel.tsx`, `/diagnostics`, release/server Playwright flows and credential/CSRF transport. Workspace UI, source handling, layout, uploads and original pages remain. Dockerfiles/Compose/.dockerignore and `.github/workflows/ci.yml` are new. Documentation includes threat model, provider guide, backup/restore, troubleshooting, demo, release checklist, changelog and updated existing contracts. No unrelated user data was removed.

Migration **0004** adds `users`, constrained `memberships`, hashed `auth_sessions`, `model_registry`, `route_policies`, `usage_events`, `request_events` and message-linked `feedback`. It preserves existing source/chat/FTS/vault/index records and infers no owner. It is an explicit frozen migration, not a destructive reset. Schema downgrade refuses before removing data; restore a stopped verified older backup. Existing local routes stay compatible. Server mode intentionally adds authenticated cookie/CSRF/membership requirements. Existing non-streaming chat remains non-streaming.

`IndexManager.ensure` now serializes first-generation creation, fixing a race between new-workspace polling and the worker. Startup checks active SQL/vector ID coverage; a missing/corrupt index becomes an actionable 503 and can be rebuilt from originals while preserving sources. Index generations still isolate model/dimension changes; generation-provider changes do not rebuild vectors. Retired namespaces remain retained; automatic GC is deferred.

## Identity, HTTP and source boundaries

Passwords use random-salt stdlib scrypt n=131072/r=8/p=1 with bounded length. Login uses generic errors and a dummy KDF for absent accounts. Session tokens have 256 random bits; only their SHA-256 hashes are stored. Cookies are HttpOnly, Strict, Secure by default, with bounded lifetime; logout, disable/reset and restore revoke sessions. The session-bound CSRF token is returned by authenticated login/me and required for mutations. Provided local HTTP server tests explicitly disable Secure cookies only for loopback testing.

Viewer can read/search; editor can add/update sources/chats/jobs; owner controls memberships/policies/indexes/diagnostics/exports/comparison. Server administrator controls accounts/global legacy defaults, with no implicit workspace content entitlement. Shared request context reaches synchronous service calls; previously admitted worker jobs run under an explicit narrow system scope. No cache bypass is introduced; no retrieval cache was added without measured need.

HTTP uses explicit hosts/origins, credentials-aware CORS outside the admission error boundary, CSRF/Origin checks, body/input limits, peer-based request/login limits, eight admitted concurrent requests, security headers and sanitized errors/correlation IDs. PDF frame ancestors allow configured frontend origins so the existing source viewer remains usable. Swagger gets a narrowly scoped docs CSP. Provided scripts disable raw URL access logs. Metrics use a short SQLite busy timeout off the event loop, avoiding long telemetry writer waits on a full disk.

Uploads retain signature/MIME/name/hash/size/page/ZIP/root controls. DOCX preflight checks a bounded valid package; XML entities/DOCTYPE are rejected, headings/tables stored, fields/objects/links never executed and page numbers never invented. Parser subprocesses have wall deadlines, stripped sensitive environment names and Unix memory/CPU bounds. Windows uses process/time isolation, not a hardened sandbox. OCR is opt-in, English/Tesseract-dependent and page/time bounded; default installation works without it. Images are never silently transmitted.

## Model registry and privacy/cost behavior

Registry entries separate generation, local embeddings, reranking and vector backend, including capability schema/privacy/installed/configured status. Manual model IDs remain supported. The application implements verified non-streaming text responses, not generic vendor tools/streaming/image capabilities. Configuring an unavailable provider does not fabricate output.

Workspace routes support mock, Groq, OpenAI, Anthropic, Google, compatible HTTPS and literal-loopback Ollama. The latter six have realistic mocked request/response tests (headers, envelopes, answer/usage parsing), not live availability claims. Existing global mock/Groq settings stay backward compatible unless overridden. Keys come only from operator environment; UI/export/diagnostics never echo them.

Every remote transmission requires workspace cloud permission plus exact provider/destination consent. Switching destination/provider cannot reuse prior consent. Optional potentially paid providers also require the operator's initially empty `NEXUS_PAID_PROVIDER_ALLOWLIST` and workspace `allow_paid`. Groq requires account/model Free Plan confirmation; exact billing eligibility cannot be verified by NEXUS. Ollama requires Local Optional and an installed chosen model; no model pull/start occurs. Presets select enforced routing classes; CPU embeddings stay two-thread/batch-eight.

Non-mock attempts reserve usage before calling, including failures, against a daily cap. Comparison cannot exceed the saved workspace cap. Output and timeout are bounded; retries are fixed to zero because a timeout may already consume usage. No provider/model fallback occurs. Provider-reported token counts are distinguished from UTF-8-bytes/4 estimates; cost remains null/unknown rather than a billed or invented price. Catalog checks send no passages and do not establish quota/billing eligibility. Custom origins require exact HTTPS allowlisting/public-address DNS validation; redirects/proxy environment are disabled. An egress policy is still needed against DNS-rebinding races.

## APIs and user journeys

Original APIs remain. New surfaces: auth me/login/logout; workspace membership GET/PUT/DELETE; `/api/models`; workspace route-policy GET/PUT and provider-check POST; jobs list and retry/cancel; batch-reindex; vault cancel; workspace diagnostics GET/DELETE; assistant message feedback and owner reviews; owner same-evidence compare; settings-export/import. `docs/API.md` and authenticated OpenAPI document exact bodies, scope and errors. Settings import is schema v1, rejects extra fields, clears cloud/paid consent and treats the index config as a reference, not an automatic rebuild.

Pages remain chat/library/vaults/graph/settings, with added diagnostics/help. Server users get sign-in/out, first workspace and membership controls. Chat has source-verified citations and private feedback. Diagnostics shows scoped timings/errors/queue/usage, bounded retry/cancel, comparison, reviews and searchable onboarding/help. Adapter status never implies reachability until explicitly checked. Settings disclose destination/paid privacy choices and export/import exclusions. Short-height sidebar overflow was corrected so saved conversations remain clickable after the added navigation item.

## Executed verification

| Command / scenario | Actual outcome |
| --- | --- |
| Pre-change backend / Ruff | 55 passed, 1 skipped, 30.51s; lint passed |
| Pre-change frontend type/lint/build / browser | Passed; 2 browser flows passed, 21.8s |
| Full Phase 3 backend with cached real ONNX | **72 passed, 1 skipped in 129.62s** on final run, including owner/preset/CORS assertions |
| Targeted authorization/gateway matrix | **12 passed in 40.02s**; final full run includes subsequent owner/preset/CORS assertions |
| Scoped `python scripts/typecheck.py` | Passed, two configuration/contract modules; no claim of strict typing of all services |
| Ruff; frontend typecheck/lint/production build | Passed on integrated code; final formatting/status recorded below |
| Local browser matrix | **3 passed, 1 intentional server-fixture skip in 58.9s**; includes preserved PDF/chat/source and vault/graph/update/rollback plus release controls |
| Separate authenticated server browser | **1 passed in 9.6s** (8.3s body); login, cookie/CSRF upload, membership and logout |
| Stopped backup/restore / checksum / lease / missing index | Passed in release operations tests; SQL/source/chat/FTS/vector/graph/sync continuity verified |
| CPU semantic/keyword/hybrid evaluation | Executed; measured metrics below, no live generator |
| Docker Compose default + local-llm syntax | Passed `docker compose … config --quiet` |
| Docker build/runtime | **BLOCKED**: named-pipe Docker Linux engine unavailable; no image pull/build/run claimed |
| Hosted GitHub CI / fresh full install on other OS | **NOT RUN**; workflow syntax and local constituent checks only |
| Live Groq/other APIs, OCR, cross-encoder, Ollama | **NOT RUN** without credentials/installed optional binaries/models; contract/fallback checks only |

Commands executed include pytest with temporary artifact roots, Ruff check/format, `npm run typecheck`, `npm run lint`, `npm run build`, `npm run test:e2e`, separate server Playwright, both retrieval/grounding scripts, 100-document benchmark, Compose config for both profiles and scoped mypy. Browser used the installed Chromium override. Test storage is synthetic and isolated from normal data.

Development failures were distinguished and corrected: the no-auth baseline passed; new concurrent first-index creation exposed a uniqueness race, fixed in the shared manager and covered by a thread-pool test; rapid test polling needed a test-only raised rate limit after parser isolation; CORS needed credentials for local requests and outer wrapping for server 401 responses; added navigation exposed short-height chat overlap; unsafe DOCX signatures needed package preflight. Low disk interrupted two full runs and compiled mypy installation; incomplete task-added mypy was removed, the smaller pure-Python wheel installed, disposable outputs cleared and task dependencies compressed. Diagnostics were moved off the async event loop with a short writer wait after full-disk behavior exposed a stall. No failed/unperformed run is counted as passing.

## Evaluation and measurements

The original fixed corpus is two-page PDF plus ten synthetic vault notes, twelve questions (ten answerable, two unsupported) with stable source hashes mapped to actual stored IDs. `release-v2` adds seven separately executable state/security scenarios for controlled empty/no-hit abstention, known source IDs, changed/deleted notes, mixed users and hostile content; they do not inflate recall sample size.

| Cached CPU MiniLM mode | Recall@3 | MRR |
| --- | ---: | ---: |
| Semantic | 1.0000 | 0.9500 |
| Keyword | 1.0000 | 0.9500 |
| Hybrid | 1.0000 | 0.9500 |

Same k=3/candidates=15/no rewrite/reranker; total **4.822s**. Both unsupported questions returned candidates in all modes. Keyword/hybrid/semantic tie; no superiority or calibrated abstention is claimed. Optional reranker quality was not measured. Raw output: `docs/retrieval-evaluation-release.json`.

Grounding: one known-answer mock case, **three valid/cited IDs out of three**, exact source substrings checked through resolver; **two controlled abstentions passed out of two** (empty workspace, lexical nonce). This verifies formatting/provenance, not real-model factual synthesis, claim entailment or natural-language unanswerable handling. Raw output: `docs/grounding-evaluation-release.json`.

100-document CPU run: **134.580s**, **0.743 docs/s**, **200 chunks**, **3,980,891 data bytes** excluding weights; first semantic query after restart **367.58ms**; warm median semantic/keyword/hybrid **58.69/60.24/87.35ms**, ten observations each. Mock cited chat **140.62ms**, TTFT null/non-streaming. RSS snapshots **179,326,976 → 299,896,832 → 335,044,608 bytes**, not measured peak. Windows 11 build 26200/AMD64, Intel64 Family 6 Model 140, Python 3.12.14, two CPU inference threads, cached pinned ~23MB quantized MiniLM, no GPU. Sequential single run; warm p95 is maximum of ten, not a capacity or performance certification. No invented before/after speedup or speculative cache was added. Raw output: `docs/benchmark-release-onnx.json`.

## Setup, recovery, CI and handoff

Windows fresh-checkout instructions: install Python 3.11–3.13 x64 and supported Node, allow several GB free, run `scripts/setup.ps1`, then API/web scripts in separate terminals. Default is ONNX + labeled mock. Unix equivalents: `sh scripts/setup.sh`, then `sh scripts/run.sh api` and `sh scripts/run.sh web`; these scripts are prepared, not executed on a separate Unix host. Runtime dependencies stay pinned; mypy is a development-only profile. No mandatory paid key, GPU, database service, Docker or heavyweight local generator.

Server accounts are created while stopped: set `PYTHONPATH=apps/api`; run `python scripts/manage_users.py owner --admin --claim-legacy` for an explicitly authorized legacy claim, or without claim for a new administrator. Passwords are prompted. Set server profile/TLS/secure cookies/hosts/origins and run one API process. Other accounts use the same CLI; owners manage roles in Settings. Do not use the synthetic browser accounts against normal data.

Backup: `python -m nexus.backup backup --data data --output backups/nexus.zip` while stopped. Restore: `python -m nexus.backup restore --archive backups/nexus.zip --target new-data`. All stores/config except secrets/optional public models are covered; `--include-models` caches weights too. Restore requires a new directory, checks hashes before writing, retains a blocking marker on incomplete output and revokes sessions. Protect confidential originals/password hashes with OS ACLs/encryption; NEXUS does not encrypt archives. See BACKUP_RESTORE.md for isolated paths and Docker/Unix commands.

CI pins action commits resolved from official repositories and caches Python/npm dependencies. It runs no-key backend lint/scoped types/security/recovery/migration tests, grounding/retrieval fixtures, frontend type/lint/build and local/server browser paths. It was not pushed or executed remotely. No secrets are required. Docker Compose uses loopback-published authenticated CPU services/persistent volume/resource bounds and an explicit optional Ollama profile; no decorative unused Redis/Postgres services or default LLM weights are started.

Manual release gates: run a fresh clone on a second CPU machine and hosted CI; start Docker and validate both images/default runtime; check intended TLS/proxy cookie/Host/CSRF/source embedding behavior; perform offsite restore and backup scheduling; review screen-reader/real PDF rendering; validate only optional provider/OCR/local models actually intended for use. A real RC tag needs a reviewed committed revision. This checkout started with untracked Phase 1/2 files and no commit; release notes are prepared without inventing or publishing a tag.

## Final confirmation and local review state

- Final full backend run: **72 passed, 1 optional PyTorch test skipped, 129.62s**. The real cached ONNX test ran. Ruff, scoped mypy (two modules), frontend type/lint and final RC production build passed. `pip check` reported no broken requirements. The unusual pre-existing workspace virtual environment's missing pip was restored from Python's bundled installer; no runtime stack upgrade was performed.
- A final narrow health/privacy/session/CORS/role confirmation after the minimal anonymous server-health read check passed **3 tests in 36.08s**. Anonymous health still checks storage and returns no workspace counts.
- Local browser matrix: **3 passed, 1 intentionally skipped server-fixture case, 58.9s**. Separate authenticated server fixture: **1 passed, 9.6s**, including cookie/CSRF source upload, account login, workspace creation, role assignment and logout. Final original-data production UI review opened a citation and checked diagnostics/mobile with zero page errors or horizontal overflow.
- Actual authenticated CLI: **three real invocations passed**: create 2 notes; modify 1 and rename 1; delete 1 with 1 unchanged. Graph ended at one note; old token had zero lexical hits. Windows redirected masked prompting initially timed out; the explicit `--password-stdin` secure-pipe path fixed automation while retaining masked interactive prompting by default. Only synthetic credentials/root were used; no personal folder watcher/daemon was installed.
- Executable normal-data backup passed: 22 files, 1,108,450 archive bytes, source revision 0003, stored in ignored `artifacts/backups/phase2-before-release.zip`. Normal startup then upgraded to **0004**; five original citation URLs, ten vault notes/current graph, cached ONNX paraphrase and five new cited answer sources all verified. Backup/model cache/originals were preserved. Public frontend origin was aligned to `127.0.0.1`; key/generation/privacy settings were preserved.
- Proof artifacts remain ignored: `phase3-upgrade-verification.json`, `phase3-agent-verification.json`, `phase3-final-review.json`, screenshots and stopped backup under `artifacts/`. The API and production frontend were left on loopback ports 8000/3000 in the configured **local** profile. No synthetic server account was added to normal data.
- Saved review demo: `http://127.0.0.1:3000/?chat=26d7abfc-85d1-4dcc-b570-df7aac5f1439`. Normal health showed 21 active-generation chunks, ready SQLite/vectors/files/worker and loaded ONNX.
- Compose default/optional profile syntax rechecked successfully. Docker engine runtime, hosted CI, independent fresh install, intended TLS deployment, optional live provider/OCR/cross-encoder/Ollama and a full assistive-technology audit remain **NOT RUN / BLOCKED** as described above. Automatic job backoff scheduling/dead-letter infrastructure, provider token streaming and repository-wide strict Python typing are explicitly deferred; current retries are manual/bounded, failed states are visible and verified responses are non-streaming.

The release candidate is ready for the documented local review and deployment gates, not an assertion that those unperformed gates passed. Phase 3 implementation ends here.
