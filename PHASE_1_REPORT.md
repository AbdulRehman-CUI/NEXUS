# NEXUS — Phase 1 implementation report

Date: 4 November 2026. Existing `NEXUS_Three_Phase_Master_Reference.md` preserved unchanged. Phase 2/3 features were not implemented.

## Delivery status

**The offline end-to-end vertical slice is implemented and verified. Full Phase 1 acceptance is not claimed:** the semantic embedding runtime could not finish installing because the host ran out of disk space, and live cloud generation was not exercised without user credentials. No paid account, provider request with private data, GPU or Ollama was used.

Implemented:

- FastAPI/Pydantic API; SQLAlchemy SQLite with Alembic startup migrations, FK cascades, WAL, readiness endpoint.
- Workspace-scoped documents, jobs, spans/chunks, chats/messages/citations. Explicit local single-user boundary; no claim of multi-tenant authentication.
- PDF/Markdown/TXT uploads, extension/MIME/signature/encoding checks, request and file size limits, UUID storage paths, containment checks, atomic writes, SHA-256 deduplication.
- Page-based PDF extraction; nested Markdown heading paths; normalized stored source spans and exact chunk offsets; explicit needs-OCR and unsupported DOCX states.
- LlamaIndex splitting, node serialization and filtered Chroma retrieval; persistent vectors, stable IDs, fingerprint namespaces and small embedding batches.
- Bounded persistent job queue, interrupted-job recovery, status/errors, reindex and retry, idempotent deletion cleanup across vector namespaces/files/SQL.
- Generation/embedding/vector protocols; deterministic mock and Groq HTTP generation adapters; hash and CPU sentence-transformer adapters. No vendor SDK in business logic. Other generation providers are future integrations.
- Bounded evidence context, untrusted-data instruction hierarchy, server-generated/validated citation IDs, actual stored excerpts/version/locators, source endpoint, original-file endpoint and source viewer.
- Persisted conversations, monotonic per-chat message ordering, rename/delete, live citations, non-streaming answers and pending UI state.
- Responsive Next App Router + TypeScript + Tailwind interface: workspace/chat sidebar, document library with real upload progress and ingestion polling, evidence panel, highlighted source dialog, provider settings, explicit per-workspace cloud consent and disclosures. Native dialog keyboard focus; escaped document text; visible focus; mobile navigation.
- Pinned direct packages, full resolver-plan lock, npm lock, `.env.example`, Windows scripts, fixtures, automated tests and focused documentation.

## Repository map and contracts

```text
apps/api/nexus/        config, database, repository, extraction, storage,
                      providers, vectors, service, middleware, main
apps/api/migrations/   0001 initial schema; 0002 stable message positions
apps/api/tests/        parsing, pipeline, safety/recovery/provider checks
apps/web/app/          /, /library, /settings and shared styles/layout
apps/web/components/   workspace UI, source viewer, icons
apps/web/lib/          typed API and upload client
apps/web/tests/        real Playwright happy path
docs/                 ARCHITECTURE, API, DATA_MODEL, RAG_DESIGN, SECURITY,
                      PROVIDERS, DECISIONS, DEPLOYMENT, EVALUATION
scripts/              setup.ps1, api.ps1, web.ps1, test.ps1, create_demo.py
examples/             generated PDF, Markdown and adversarial TXT
```

New files are confined to the Phase 1 application, scripts, fixtures and documentation. Build outputs, local environments, local settings/data and browser artifacts are ignored. The complete route table and JSON response examples are in [docs/API.md](docs/API.md); executable contracts are served at `/docs`.

Main routes: `/health`; GET/POST workspaces; PATCH workspace consent; GET/POST workspace documents; scoped document detail/reindex/delete/source/file; scoped job detail; GET/POST workspace chats; scoped chat detail/rename/delete/messages; safe public settings GET/PATCH; provider list and explicit Groq model check. Non-streaming message response carries `content`, `answer`, `provider`, and server-verified `citations[]`.

## Exact validation performed

Environment: Windows, bundled Python **3.12.14**, Node **24.16.0**, npm **11.13.0**. Package versions were queried from package registries on 4 November 2026; pinned versions are not a promise to remain latest. Core Python dependencies installed into the workspace `.venv`; no-key tests used mock generation/hash embeddings with real SQLite and persistent Chroma.

| Command / check | Actual result |
| --- | --- |
| `python -m compileall -q apps/api scripts/create_demo.py` | Passed initial syntax check |
| `python -m ruff check apps/api --fix` / `python -m ruff format apps/api` | Initial import issues fixed; subsequent lint clean |
| `python -m pytest apps/api -q --disable-warnings --maxfail=1` | **28 passed in 16.75s** on final backend run |
| `npm run typecheck` | Passed |
| `npm run lint` | Passed with no warnings after navigation/export fixes |
| `npm run build` (`next build --webpack`, two build workers) | Passed; `/`, `/library`, `/settings` statically built; final build after UI contrast/reindex changes also passed |
| `npm start` | Production web server started successfully on localhost |
| `python scripts/create_demo.py` | Generated the two-page Aurora PDF |
| `python -m uvicorn nexus.main:app --host 127.0.0.1 --port 8000 --workers 1` with isolated mock/hash settings | Startup migrations and local server passed |
| `npm run test:e2e` with installed Chromium executable override | **1 passed in 14.7s** (test body 10.4s); real browser + API + SQL/vector/files flow |
| `pip --python .venv/Scripts/python.exe check` | No broken requirements in the installed core environment |
| CPU sentence-transformer dependency installation | **Blocked**: repeated `[Errno 28] No space left on device`; no semantic inference result claimed |
| Live Groq generation | **Not run**: no user key/free-plan confirmation/cloud consent; adapter HTTP behavior tested with mocked responses |
| Final normal-directory startup and seeded demo | `/health` returned ok; two example documents ready; answer returned five citations; source endpoint returned 200 |

The browser test uploads PDF + Markdown through the UI, waits for two ready documents, asks about Aurora, opens a numbered citation, checks highlighted evidence, reloads and opens saved history, verifies consent defaults, and checks a 390px mobile library for overflow and page errors. It passed with **no page errors**. Test browser: existing local Chromium at `chromium-1161`, selected via `NEXUS_CHROMIUM_EXECUTABLE`; standard setup uses Playwright's downloaded Chromium.

Initial verification found and fixed a timestamp-tie message ordering bug. A filename test was corrected to distinguish framework-normalized Windows drive paths from rejected traversal paths; storage containment is still enforced. A browser assertion was corrected to handle the PDF's uppercase AURORA title. Earlier runs failed until those fixes; the final results above are actual successful runs.

Turbopack initially failed its child-process connection in the sandbox. Webpack compilation succeeded, but one sandbox build then hit EPERM on a generated directory. A host-context Webpack build passed; the scripts use Webpack and two build workers. Browser/server loopback contexts were aligned before the successful browser test.

## Screenshots / visual review

Generated and visually inspected local artifacts (ignored by Git):

- `artifacts/chat-desktop.png` — cited response and evidence cards.
- `artifacts/source-desktop.png` — correct PDF page locator and exact highlighted normalized source.
- `artifacts/settings-desktop.png` — provider setup and cloud consent.
- `artifacts/library-mobile.png` — 390px library, real statuses and actions, no horizontal overflow.

The native PDF iframe is blank/dark in the headless screenshot; the PDF endpoint returned 200 and the page-navigation URL is constructed correctly. Rendering the original PDF page in a normal browser remains a manual check; the stored text passage and highlight were browser-verified.

## Setup / local state

Normal clean setup, with sufficient disk space and standard Python:

```powershell
.\scripts\setup.ps1
# Two terminals:
.\scripts\api.ps1
.\scripts\web.ps1
# Tests:
.\scripts\test.ps1
```

See [README.md](README.md) for manual commands, demo flow, prerequisites, CPU install and provider setup. Allow several GB of disk space for dependency/cache/temp files. The 91 MB embedding model is much smaller than the Python/PyTorch dependency footprint.

This host's full dependency install failed for disk space. An incomplete environment was removed, the completed core environment consolidated into `.venv`, task-owned dependency files received transparent NTFS compression, and disposable build cache was removed. No unrelated user data was removed. The local ignored `.env` explicitly selects **hash embeddings + mock generation** so this checkout can run the verified demo; `.env.example` retains **MiniLM semantic embeddings + mock generation** as the normal default. No key was added.

The API and production frontend were left running on localhost for review, using the normal `data/` directory. The Personal workspace contains the two included demo sources and a saved cited conversation. Restart later with the run scripts above. Git was initialized on `main`; no commit was created. `.env`, local data, environments, dependency folders and browser/build artifacts were confirmed ignored.

`requirements.lock.txt` combines the installed core resolution with exact versions from the successful semantic dependency resolver plan. It is labelled accordingly; a full clean install of that plan did not complete on this host. Pin/CPU-wheel compatibility across other operating systems remains unverified. The example model revision is pinned and represented in index fingerprints.

## Remaining acceptance gates / known limits

1. Free sufficient disk space, finish the locked CPU semantic dependency install, switch `NEXUS_EMBEDDING_PROVIDER=sentence-transformers`, and run the semantic smoke check plus PDF/MD indexing/retrieval. This gate is outstanding, not a completed integration test.
2. With the user's own eligible Groq Free Plan key, confirm current account/model eligibility, explicitly opt in, then run a live generated-answer/source check. The API cannot inspect account billing tier. There is no paid fallback or automatic model/provider switch.
3. Single-user localhost only. No authentication, memberships, tenant-grade access control, at-rest encryption, external worker leases or parser process isolation.
4. Hash retrieval demonstrates lexical plumbing rather than semantic understanding. Mock generation quotes actual passages rather than synthesizing answers. Distance thresholds are heuristic; valid citation provenance does not prove claim entailment.
5. No SSE, OCR, DOCX, vault import/watcher, hybrid retrieval, reranking, query rewriting, graph, or additional cloud/local generation adapters in Phase 1.
6. Each question is independently retrieved; saved history does not resolve conversational follow-ups. Markdown handling covers ATX headings/basic fences rather than a full AST. Mixed PDFs index readable pages, not text in images.
7. Same-configuration reindex preserves citation IDs/chunks. An index-config change removes obsolete live citations; document deletion removes live citations while retaining historical answer text. Immutable evidence archives are future work.
8. Delete failures remain explicitly pending and retryable. A crash between original-file write and SQL commit may leave an orphan file; inspect/clean while stopped. No periodic orphan sweeper is claimed.

## Precise Phase 2 handoff

- First close the two acceptance gates above; do not interpret the offline test as measured semantic retrieval quality or a live cloud integration result.
- Add hybrid lexical/semantic retrieval behind the vector/retrieval boundary, using a small labelled evaluation set and the current evidence/source invariants. Preserve both Chroma and SQL workspace filters.
- Add Obsidian/vault ingestion, safe relative paths, wikilink metadata and incremental content-version handling; reuse durable jobs, stored spans and deterministic chunk identities.
- Introduce immutable document versions/citation archives before automatic file synchronization invalidates historical sources. Define index migration/cleanup behavior explicitly.
- Keep generation isolated behind `GenerationProvider`; new provider adapters must have explicit privacy/cost policy and contract tests. Do not silently enable paid services.
- Authentication, hardened authorization, parser subprocess limits, leases/multiple workers, backups/operations and public deployment stay Phase 3 unless the phase plan is explicitly changed.
