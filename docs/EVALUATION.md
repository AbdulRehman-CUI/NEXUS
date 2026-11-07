# Evaluation and reproducible checks

## Actual Phase 3 measurements

Version `release-v2` adds seven separately tested transition/security expectations (`examples/evaluation/release-cases.json`) to the original twelve labeled relevance questions. They are not added to the recall denominator. On 4 November 2026, cached CPU ONNX semantic/keyword/hybrid each measured Recall@3 **1.0000** and MRR **0.9500**, ten answerable/two unsupported cases, total **4.822s**. Both unsupported cases still returned retrieval candidates. No general hybrid improvement or perfect abstention is claimed. Raw run: `docs/retrieval-evaluation-release.json`.

`python scripts/evaluate_grounding.py` measured **3/3 citation IDs valid and cited**, verified excerpts against stored source endpoints, and **2/2 controlled abstentions** (empty workspace and exact unmatched keyword nonce). One known-answer mock case is formatting/provenance evidence, not real model synthesis/entailment. Raw run: `docs/grounding-evaluation-release.json`. Local feedback and owner-only identical-evidence comparison enable human/provider review without an external judge; optional providers are unavailable until all explicit gates are satisfied.

`python scripts/benchmark_release.py --documents 100 --data artifacts/new-benchmark` executed 100 unique synthetic Markdown uploads, disposable extraction processes, CPU ONNX and 200 chunks: ingestion **134.580s**, **0.743 docs/s**, **3,980,891 bytes** data excluding model cache. After restart, first semantic query **367.58ms**; warm medians semantic **58.69ms**, keyword **60.24ms**, hybrid **87.35ms** (10 observations each); mock cited chat total **140.62ms**. RSS observations 179,326,976 before, 299,896,832 after ingestion, 335,044,608 after warm queries. These are process snapshots, not peak memory. Windows 11 build 26200 / AMD64 / Intel64 Family 6 Model 140 / Python 3.12.14, cached pinned MiniLM, two inference threads. Single sequential run; p95 is the maximum of ten warm samples; TTFT is unavailable because responses are non-streaming. Raw run: `docs/benchmark-release-onnx.json`.

No retrieval cache/concurrency optimization was introduced without a measured need. Parser isolation and diagnostic writes add real work; no fabricated before/after speedup is claimed. Existing Phase 2 timings use a smaller corpus and are not comparable throughput benchmarks. Cross-encoder, OCR, Ollama/live cloud, Docker runtime and second-machine install validation remain separate unperformed checks.

Release commands: `python scripts/typecheck.py` checks two typed configuration/contract modules; Ruff + pytest cover dynamic services; frontend `npm run typecheck`, `npm run lint`, `npm run build`; local `npm run test:e2e`; separate server fixture with `NEXUS_SERVER_TEST=1 npx playwright test server.spec.ts`. Exact final counts and environment failures/fixes are recorded in PHASE_3_REPORT.md. Hosted CI is prepared and not claimed to have run.

Phase 2 adds a labeled PDF/vault retrieval benchmark, secure sync/index regression tests, and a second browser flow. See [measured Phase 2 results](RETRIEVAL_EVALUATION.md) and [the delivery report](../PHASE_2_REPORT.md). The real ONNX paraphrase test runs with `NEXUS_TEST_ONNX=1`; the optional PyTorch adapter remains unverified on this host.

Run `scripts/test.ps1` for pytest, Ruff, TypeScript, ESLint and production build. Backend tests use actual temporary SQLite/Chroma, hash embeddings and mock generation. The pytest API happy path uploads a generated two-page PDF and Markdown, waits for the real worker, asks a question, verifies excerpts against source spans, and opens original files.

Coverage includes PDF page extraction, OCR state, nested Markdown heading paths/code fences, chunk offsets/progress, duplicates, reindex/vector count stability, deletion cleanup, SQL/vector/source/chat/job isolation, unsafe filename/MIME/signature/encoding rejection, upload limits, storage root enforcement, missing keys, cloud consent, quota/unknown-citation errors, provider request hierarchy, excerpt budget, citation/document mismatch, interrupted-job recovery, persisted settings, chat lifecycle, and untrusted Origin rejection.

The adversarial fixture asks the assistant to output PWNED. Mock behavior remains labelled extractive quotation, and tests inspect the cloud adapter's system/user boundary using a mocked HTTP response. This does not prove a real model ignores every injection; no live provider test is possible without user credentials and opt-in. Source provenance is verified; semantic entailment is not.

Browser check: generate the PDF fixture; run API with mock generation and hash embeddings in an isolated data directory; run Next; then `npm run test:e2e` in `apps/web`. Playwright uploads two files through the real UI, waits for ready, asks and opens a citation, checks persisted history, inspects consent defaults, and checks a 390px mobile library with screenshots and no page errors.

Optional legacy PyTorch semantic smoke check (requires optional ML dependencies and cached model or network):

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -c "from nexus.providers import SentenceTransformerEmbeddingProvider; p=SentenceTransformerEmbeddingProvider('sentence-transformers/all-MiniLM-L6-v2'); v=p.embed(['Aurora launches in November','When does Aurora launch?']); print('vectors:',len(v),'dimensions:',len(v[0])); assert len(v)==2 and len(v[0])==384"
```

See `PHASE_1_REPORT.md` for exact commands actually run and their results. Instructions here are not a claim that every optional check has run.
