# NEXUS — Phase 2 delivery report

Delivered on 4 November 2026 in the existing Phase 1 checkout. Phase 3 was not started.

## Delivered behavior

Phase 1 PDF/Markdown/TXT ingestion, saved conversations, source highlighting, mock generation, Groq configuration and privacy gates remain available. Phase 2 adds actual SQLite FTS5 keyword retrieval, CPU semantic retrieval and deterministic hybrid fusion; scoped filters and retrieval diagnostics; secure Obsidian ZIP snapshots and an explicitly invoked local-folder sync agent; authored note/tag graph navigation; durable incremental jobs; and validated, resumable embedding-index generations with rollback.

The default embedding adapter now runs the official pinned MiniLM quantized ONNX graph directly, without PyTorch or a local generative LLM. Real inference, paraphrase retrieval and the labeled evaluation ran successfully. Hash vectors remain an explicit deterministic test/demo option. Generation remains the labeled extractive mock by default. No key, paid API, GPU, hosted database or cloud generation was needed for these checks.

Implemented optional capabilities: local heuristic follow-up reformulation, bounded local query variants, and a lazy local cross-encoder adapter with visible fallback. Full cross-encoder inference and the optional sentence-transformers/PyTorch runtime were not executed. Hosted reranking, generative rewriting, inferred graph edges, OCR, production authentication and distributed deployment remain deferred.

## Baseline and repository review

Read the required README, Phase 1 report, environment example, architecture, decisions, data model, API and RAG documents; the master three-phase reference was present and preserved. Inspected actual FastAPI/Next entrypoints, providers, extraction, SQL/Alembic, Chroma, ingestion workers, source/citation resolution and existing tests. Required documents were present.

Before implementation: **28 backend tests passed in 20.56 seconds**; Ruff, TypeScript and ESLint passed. No baseline failure was recorded. Existing Phase 1 files were already untracked in this checkout; no destructive reset, replacement checkout or commit was performed.

## Files and schema

| Area | Main implementation |
| --- | --- |
| Retrieval and contracts | `apps/api/nexus/retrieval.py`, `contracts.py`; integration in `service.py`, `main.py`, `routes_phase2.py` |
| Embeddings/vector generations | `providers.py`, `vectors.py`, new `indexes.py`, configuration in `config.py` |
| Vault parser/snapshots/graph | `vaults.py`, `local_agent.py`, `scripts/vault_sync.py`; Markdown extraction integration in `extraction.py` |
| Persistence | `database.py`, additive `migrations/versions/0003_knowledge.py` |
| Evaluation | `nexus/evaluate.py`, `scripts/evaluate_retrieval.py`, `examples/evaluation/`, checked-in measured JSON in `docs/` |
| Next UI | `vault-manager.tsx`, `graph-explorer.tsx`, `retrieval-controls.tsx`, `advanced-settings.tsx`; existing workspace/source UI, styles and typed API client extended |
| Tests | New retrieval, vault, sync-ordering, index and integrity backend tests; preserved original pipeline/security tests; `apps/web/tests/phase2.spec.ts` plus original browser flow |
| Operations | Core ONNX CPU dependency lock, optional ML lock/profile, setup script, `.env.example`, README and architecture/API/data/RAG/security/provider/deployment/evaluation documentation |

Migration 0003 adds workspace index preferences, document origin, message evidence snapshots/diagnostics, retrieval profiles, vaults, notes, note tags, note links, sync runs and index generations. It adds the FTS5 chunk table and maintenance triggers, backfills existing chunks, preserves parent document/chat/citation data, and enforces one active generation per workspace. Existing citations are copied into message snapshots. Note IDs are stable logical identities; immutable content documents/version IDs hold indexed passages. Distinct notes with identical bytes may share a content document while retaining separate paths and graph identities.

The tested upgrade starts from an actual 0002 schema containing citations and source passages. Schema downgrade deliberately refuses before making changes: restore a stopped full `data/` backup instead. Embedding-index rollback is a separate supported operation.

## Retrieval and evidence pipeline

1. Validate the workspace and filters. Compute live, authorized document IDs from SQL, including current note hash/version/status. Enforce this set before dense and lexical search and revalidate returned candidates.
2. Optionally reformulate a short follow-up using the previous scoped user turn. The current question is preserved; prior context is bounded. Optional local variants are deduplicated and bounded to at most three. These operations make zero extra cloud calls.
3. Keyword mode runs safe bound FTS5 MATCH queries with quoted terms/phrases and weighted BM25 over passage/title/path/tag metadata. Semantic mode embeds the query with the active generation and searches its compatible Chroma namespace. Hybrid executes both and merges stable chunk IDs with weighted Reciprocal Rank Fusion.
4. Optional cross-encoder reranking runs lazily on bounded candidates. Missing runtime/weights or failure retains original ranking and returns a warning. Default is no reranker; downloads require explicit server configuration.
5. Evidence assembly caps per-document passages, removes near-duplicates, and obeys a conservative UTF-8-byte context budget. A byte budget upper-bounds ordinary text token counts without pretending to measure a generation model's tokenizer. Preserve workspace/document/version/chunk/span/note/path/page/heading/offset/excerpt identity throughout.
6. Generation receives untrusted excerpts as evidence, not system instructions. Server-created citation IDs are validated against the stored authorized passage/version. Unknown IDs fail explicitly; source changes during generation reject the answer. Citation coverage/quality flags are observable. No evidence produces a saved insufficient-evidence response without a cloud call.

Defaults: hybrid; candidate count 15 per branch; top_k 5; RRF constant 60; equal branch weights; context budget 4,000; at most three passages per document; local follow-up rewrite on; multi-query off; reranker none. Per-request supplied fields merge with persisted workspace defaults. Filters support document IDs, vault, safe path prefix, tags and PDF/MD/TXT type; categories combine with AND, tags within a category with OR.

Diagnostics report mode, index/model identity, candidate counts, ranking stages, final chunk locators, total latency and warnings. BM25, cosine and cross-encoder scores have distinct names; fusion scores are ranks, not confidence probabilities. Server logs record counts/timing/error types rather than private query/excerpt text. Health checks read vector storage and report SQL chunk counts for active generations, including after migration to a new namespace.

## Vault import, sync and graph

ZIPs are read as bounded snapshots, never extracted to user-selected paths. Reject traversal/absolute/device/control paths, case/Unicode collisions, symlink/special/link metadata, unsafe encryption/encoding, file-count/size/ratio violations and malformed archives. Ignore `.obsidian`, plugins/caches, `.git`, trash, OS metadata and configured temporary patterns. Only Markdown notes are indexed; attachments are not fetched or executed.

The parser uses safe YAML with curated metadata and rejects anchors/aliases/unsafe types. It records frontmatter/inline tags, heading paths, wikilinks and display aliases, Markdown links/embeds and supported heading/block anchors. Resolve relative paths, root paths and unique basenames deterministically. Preserve ambiguous, unresolved, missing-anchor, blocked and external links explicitly. External URLs are never fetched. This is a practical Markdown parser, not complete Obsidian plugin/Markdown semantics.

Each complete manifest compares normalized relative paths and SHA-256 content hashes. Unchanged notes avoid indexing. Changed notes create current immutable content; unique-hash rename matches preserve logical IDs. Ambiguous renames become delete/create. Missing paths revoke SQL eligibility and graph links immediately; vector/file cleanup follows. Old jobs cannot reactivate superseded content. Partial failures have persisted cursor/errors and at most three retries. Repeated snapshots are idempotent; manually deleted content can be restored by an intact later snapshot. Identical-content failed ingestion is retryable rather than left pending forever.

`scripts/vault_sync.py` scans only an explicitly supplied root, rejects symlinks/junctions/hardlinks/out-of-root/special/changing files, and sends a bounded complete snapshot to the localhost API. HTTP proxy environment variables are disabled for this transport. `--once` scans once; otherwise the interval is at least five seconds (default 15). Use the printed vault ID on subsequent invocations. The browser cannot read/watch arbitrary folders. Its scan button requests a running agent scan; snapshot vaults require an updated ZIP. No daemon/service was installed and no personal folder was watched during verification.

Relational NoteLink/NoteTag records power a scoped directed authored graph. Native SVG supports pan/zoom, selection, source inspection and backlinks/outlinks, vault/tag/type/search filters, counts and empty/error states. The keyboard note list provides a parallel navigation path. Rendering is subset to at most 300 notes plus tags; this avoids drawing an entire large vault. Tag edges are visually distinct. No conceptual/AI-inferred edge is presented as an authored link.

Old chat snapshots retain citation provenance after a note revision/deletion but mark the source unavailable. The resolver returns 404/410 rather than opening new content under an old citation. Model-only reindexing preserves citations to current source versions.

## Versioned indexes

The fingerprint binds provider/model/pinned revision/dimension, artifact, normalization, pooling/adapter/preprocessing and chunk configuration. Dimensions are validated on writes and queries. Incompatible vectors never enter a shared generation.

A workspace has one active ready index. Replacement builds use a separate namespace, checkpoint document versions and resume one document at a time. Prior ready indexes remain searchable. Validation compares exact SQL/vector chunk IDs and current document versions; activation is atomic. Failed/cancelled/partial builds cannot activate. Retry is bounded. Retired namespaces are retained for rollback; rollback also verifies current coverage. Deletion cleans generation checkpoints, preventing false rollback failures after legitimate vault changes. Workspace choices persist across restarts and override server defaults.

Automatic retention/garbage collection is deferred: retained namespaces/chunks cost disk space. Do not manually delete them while referenced.

## API and UI

Preserved Phase 1 routes. Actual new `/api` routes:

```text
POST      /workspaces/{id}/search
GET/PATCH /workspaces/{id}/retrieval-settings
POST      /workspaces/{id}/vaults/import
GET       /workspaces/{id}/vaults
GET       /vaults/{id}/notes
GET       /vaults/{id}/links
GET       /vaults/{id}/sync-status
POST      /vaults/{id}/sync
POST      /vaults/{id}/retry
GET       /notes/{id}
GET       /workspaces/{id}/graph
GET       /workspaces/{id}/index-versions
POST      /workspaces/{id}/indexes/rebuild
POST      /index-versions/{id}/{retry|activate|cancel}
```

Resource-scoped routes require `workspace_id`; list/create routes carry workspace in their path. FastAPI `/docs` exposes the typed schemas. `docs/API.md` describes pagination, errors, bodies, filtering and output contracts. Existing chat requests now accept options/filters/diagnostics. Chat remains a non-streaming endpoint with visible pending/error UI.

Pages: `/` chat, `/library`, `/vaults`, `/graph`, `/settings`. Chat adds strategy/filters/diagnostics and unavailable-citation states. Library adds search/sort. Vaults add ZIP import/update, folder/tag browsing, status/counts/retry, source preview, reindex and link inspection. Settings add resource/retrieval/rewrite/variant/reranker options, generation states/fingerprints/progress and replacement/rollback controls. The existing visual design and provider controls are preserved.

## Setup and repeatable commands

Validated host: Windows 11 build 26200, AMD64, Intel64 Family 6 Model 140 Stepping 1, Python 3.12.14, Node 24.16.0, npm 11.13.0. CPUExecutionProvider uses two inference threads, batch eight. No GPU.

Windows, repository root:

```powershell
.\scripts\setup.ps1
# Separate terminals:
.\scripts\api.ps1
.\scripts\web.ps1
# Checks:
.\scripts\test.ps1
# Included ZIP: examples/evaluation/vault.zip
.\.venv\Scripts\python.exe scripts/vault_sync.py --root 'C:\My Vault' --workspace WORKSPACE_ID --once
.\.venv\Scripts\python.exe scripts/vault_sync.py --root 'C:\My Vault' --workspace WORKSPACE_ID --vault-id VAULT_ID --interval 15
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --embedding-provider onnx
```

Set `NEXUS_MODEL_CACHE_DIR=data/models` to share the app cache. `HF_HUB_OFFLINE=1` prevents model-download network access once cached. The official pinned graph was 23,046,789 bytes plus tokenizer JSON. No document text is sent for model download. Default core requirements exclude PyTorch. `setup.ps1 -WithTorch` selects the optional larger CPU ML profile; that fresh installation is unverified on this host.

Manual Unix-like commands (documented, not executed on this Windows host):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r apps/api/requirements.lock.txt
cp .env.example .env
PYTHONPATH=apps/api OMP_NUM_THREADS=2 uvicorn nexus.main:app --host 127.0.0.1 --port 8000 --workers 1
# Separate terminal:
cd apps/web
npm ci
npm run dev
```

The installed core runtime was checked against pinned dependencies; a completely fresh full setup was not rerun under the host's low disk space. Keep several GB free for installation. Windows scripts are the verified operation path. API binds localhost with one process per data directory. Back up stopped `data/` as a unit before upgrading/restoring.

## Executed checks and outcomes

| Check | Actual outcome |
| --- | --- |
| Pre-change Phase 1 pytest | 28 passed, 20.56 s |
| Pre-change Ruff / TypeScript / ESLint | Passed |
| Final Phase 2 backend, real cached ONNX enabled | 55 passed, 1 skipped in 23.94 s |
| Ruff, `apps/api` and `scripts` | Passed |
| Frontend `npm run typecheck`, `npm run lint` | Passed |
| Final `npm run build` | Passed; chat/library/vaults/graph/settings generated |
| `npm run test:e2e` | 2 passed, 21.5 s: preserved PDF/chat/source flow and Phase 2 vault/graph/filter/update/rebuild/rollback/mobile flow |
| Real local-folder CLI against localhost | Passed create 2; update 1 + rename 1; delete 1 + unchanged 1; remaining graph note 1; removed token absent from search |
| Existing Phase 1 data upgrade | Passed; five saved citations opened; old hash index retired; ONNX replacement ready/active |
| Default local semantic demo | Passed; ten-note included vault ready; vacation paraphrase retrieved `Policies/Leave.md`; saved cited mock answer |
| Final production UI review | Passed saved chat, ONNX artifact setting and populated graph; no page errors or 390px overflow; health reports 21 active-generation chunks |

Final backend command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:NEXUS_TEST_ONNX='1'
$env:NEXUS_MODEL_CACHE_DIR='data/models'
.\.venv\Scripts\python.exe -m pytest apps/api -q --basetemp artifacts/phase2-tests --maxfail=1
.\.venv\Scripts\python.exe -m ruff check apps/api scripts
```

Browser checks used installed Chromium with `NEXUS_CHROMIUM_EXECUTABLE` and mock/hash isolated test storage. API and browser had to run in the same host context; sandbox/host localhost mismatch was an execution-environment issue. Browser failures during development exposed and fixed empty legacy diagnostics causing a client crash and deleted document IDs remaining in rollback checkpoints. The test locator for a wrapping filter label was corrected. All final browser assertions passed without page errors, including 390px layout. Subsequent final UI change exposed the ONNX artifact field; final type/lint/build passed.

Backend coverage includes phrase/strategy/RRF/dedup/filter semantics, real no-shared-keyword ONNX paraphrase, workspace isolation, deleted-source exclusion, malformed archives/frontmatter/paths/links, rename/update/delete/idempotence/recovery, graph directionality/backlinks, stale citation handling, actual 0002 upgrade, dimension mismatch, interrupted/failed/cancelled rebuild behavior, rollback, shared-content failure retry and old-job ordering. The single opt-in PyTorch test is skipped because its optional runtime is absent. Model fallback behavior is tested; full cross-encoder inference is not marked passing.

Local proof files, ignored from version control: `artifacts/agent-cli-verification.json`, `artifacts/phase2-upgrade-verification.json`, `artifacts/phase2-final-review.json`, browser screenshots and `artifacts/phase1-data-backup`. The existing data backup was made while the original API was stopped. Default `.env` now selects cached ONNX; generation/key/consent settings were preserved. The API and production frontend were left running at `http://127.0.0.1:8000` and `http://127.0.0.1:3000`; the saved semantic demo is `http://127.0.0.1:3000/?chat=7830cb5c-2070-4105-8bbf-8f3fe83c3ee3`. Embedding weights load lazily after restart.

## Measured retrieval quality

Checked-in synthetic corpus: two-page PDF, ten vault notes, twelve labeled questions (ten answerable, two unsupported). Cases include phrases/exact codes, paraphrases, two-source relevance, dates/ownership, adversarial content, ambiguous links and missing targets. Source labels are stable SHA-256 IDs over canonical path/page/heading/text. Evaluation validates labels against extracted stored spans, records actual chunk/source ID mappings and opens returned sources.

Same k=3, candidates=15, no rewrite or reranker, same assembly/filters per run:

| Embedding / mode | Recall@3 | MRR |
| --- | ---: | ---: |
| Hash / dense | 0.9500 | 0.9000 |
| Hash / keyword | 1.0000 | 0.9500 |
| Hash / hybrid | 1.0000 | 0.9500 |
| MiniLM ONNX / semantic | 1.0000 | 0.9500 |
| MiniLM ONNX / keyword | 1.0000 | 0.9500 |
| MiniLM ONNX / hybrid | 1.0000 | 0.9500 |

Hash total 4.136 s; cached ONNX total 4.901 s. These are single-run timings, not benchmark medians. Metrics average the ten answerable cases; unsupported cases are separate. Both unsupported cases returned candidates in all six configurations. Retrieval hits do not establish sufficient evidence or generated-claim entailment. No general hybrid superiority, perfect abstention or prompt-injection immunity is claimed. The comparison baseline is dense-only under the same current pipeline, not a historical checkout. Hash quality is not semantic-model quality. Full methods/raw results: `docs/RETRIEVAL_EVALUATION.md`, `docs/retrieval-evaluation-hash.json`, `docs/retrieval-evaluation-onnx.json`.

## Security, limits and Phase 3 handoff

Verified traversal/ZIP/YAML/link defenses, scoped dense/lexical/graph/source APIs, prompt hierarchy with mocked cloud responses, malicious vault citation markers, document/version checks, stale-source rejection, privacy gates and missing-key errors. Uploaded originals/model weights/local configuration and test artifacts remain ignored; no credential was added to source. No paid service or external message was invoked.

Limits requiring explicit continuation in Phase 3:

1. Keep this localhost/single-user. Workspace scope is not authentication. Add actual identity/ownership checks before any public/multi-user deployment; preserve isolation tests across retrieval, graph, sources and jobs.
2. Move parsers into resource-limited processes before accepting hostile public uploads. Current extraction is in-process; Markdown/anchor parsing is intentionally partial. Attachments, OCR and additional formats remain out of scope.
3. Calibrate abstention and claim-level evidence/entailment on a larger held-out corpus before stronger answer-quality claims. Preserve the checked-in benchmark and add realistic multilingual/long-vault cases; measure latency/memory repeatedly.
4. Validate optional cross-encoder, PyTorch and live Groq with explicitly supplied credentials/privacy consent and host resources. No live provider call was possible or attempted without keys; no successful API/inference result is claimed for those paths.
5. Design generation retention/garbage collection and stopped-backup recovery tooling before growing many indexes. Rollback must continue to verify current coverage; never remove active/referenced namespaces. Schema downgrade remains unsupported.
6. Add leases/distributed jobs, authentication, deployment/CI/monitoring changes only with a Phase 3 scope. Current synchronous local operations use one lock/worker and one API process. Folder scanning is an explicit CLI, not an installed background service.

All Phase 2 work stops here. No production auth overhaul, public deployment, hosted reranker, inferred-edge feature or Phase 3 infrastructure was started.
