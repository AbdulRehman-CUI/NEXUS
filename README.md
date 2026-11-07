# NEXUS · Phase 3 release candidate

A local document and Obsidian workspace with evidence-linked answers, SQLite FTS5/dense/hybrid search, incremental vault synchronization, and an authored-link knowledge graph. FastAPI + Next.js, SQLite, persistent Chroma, LlamaIndex, PyMuPDF, and CPU MiniLM embeddings. No paid service, GPU, Ollama, Redis, or PostgreSQL is required.

Phase 3 adds expiring authenticated server sessions and workspace roles, per-workspace model routing/consent/budgets, optional vendor adapters, DOCX extraction and bounded parser processes, job controls, local diagnostics/feedback/comparison, portable settings, verified stopped backup/restore, Docker profiles and CI. This is a release candidate, not a security certification. See [actual release results and outstanding gates](PHASE_3_REPORT.md).

**Personal BYOK is available in Settings → Models & privacy.** Connect your own OpenRouter, Gemini, OpenAI, Anthropic or Groq key, an approved custom endpoint, or a local Ollama model. Keys are encrypted outside the browser; separate accounts have independent configurations, selections and usage. See [BYOK setup and privacy](docs/BYOK_SETUP.md) and [implementation/validation report](BYOK_UI_BRANDING_REPORT.md).

**Default mode is a labelled offline extractive demo**, not a generative AI simulation. Free-tier provider accounts and local models remain supported. Paid usage is optional and requires explicit consent; no provider or paid fallback is automatic. No cloud API key is bundled with NEXUS.

## Windows setup

Install Python **3.11–3.13 (64-bit)** and Node **22.9+ or 24 LTS**. Allow several GB of free disk space for dependencies, caches and installation temporary files (4 GB recommended). Python 3.12 and Node 24 were used for validation. Run from this repository root in PowerShell:

```powershell
# Allow scripts for this terminal only if your execution policy requires it.
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
# For a Python executable in a custom location:
# .\scripts\setup.ps1 -Python 'C:\path\to\python.exe'
```

Open two terminals at the repository root:

```powershell
.\scripts\api.ps1
```

```powershell
.\scripts\web.ps1
```

Visit [NEXUS](http://127.0.0.1:3000), [API health](http://127.0.0.1:8000/health), or [interactive API contracts](http://127.0.0.1:8000/docs). The API applies additive Alembic migrations automatically. Back up an existing `data/` directory while stopped before upgrading. Run exactly **one API process/worker** per data directory. The default CPU profile uses the official quantized MiniLM ONNX weights (~23 MB) plus a tokenizer, with two CPU threads. No PyTorch is needed by default. Model errors leave an explicit failed job/rebuild and preserve the previous active index. Optional PyTorch/cross-encoder support: `.\scripts\setup.ps1 -WithTorch`.

## Profiles and release operations

The default `NEXUS_PROFILE=local` is account-free and rejects non-loopback clients/hosts. The server profile requires expiring opaque sessions, CSRF tokens and explicit workspace membership. Before switching existing data to server mode, stop the API and create an administrator; claiming legacy workspaces is explicit:

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe scripts/manage_users.py owner --admin --claim-legacy
# Set NEXUS_PROFILE=server in .env. Keep secure cookies true behind HTTPS.
# Loopback HTTP testing only: NEXUS_SECURE_COOKIES=false.
```

Passwords are prompted, never passed as CLI arguments. Additional accounts use the same command without `--admin`; workspace owners grant viewer/editor/owner membership in Settings. New server accounts do not inherit legacy data. Optional remote providers require operator configuration and exact destination/workspace consent. Optional paid adapters also require `NEXUS_PAID_PROVIDER_ALLOWLIST` plus per-workspace permission; neither credentials nor a provider switch grants consent. No automatic fallback or generation retry occurs.

Diagnostics & help shows real jobs, request timings, reported/estimated token usage, feedback reviews and an identical-evidence model comparison. Settings exports omit secrets and local paths; imports clear cloud/paid consent. See [provider guide](docs/PROVIDER_GUIDE.md), [threat model](docs/THREAT_MODEL.md), [backup/restore](docs/BACKUP_RESTORE.md), [deployment](docs/DEPLOYMENT.md) and [demo](docs/DEMO.md).

```powershell
# API must be stopped; store the archive outside data/:
.\.venv\Scripts\python.exe -m nexus.backup backup --data data --output artifacts/backups/nexus.zip
.\.venv\Scripts\python.exe -m nexus.backup restore --archive artifacts/backups/nexus.zip --target artifacts/restored-nexus
# Actual measurement commands, synthetic data only:
.\.venv\Scripts\python.exe scripts/evaluate_grounding.py
.\.venv\Scripts\python.exe scripts/benchmark_release.py --data artifacts/new-benchmark --documents 100
```

## First evidence-backed answer

```powershell
.\.venv\Scripts\python.exe scripts/create_demo.py
```

1. Open **Document library**, upload `examples/aurora-brief.pdf` and `examples/aurora-notes.md`.
2. Wait for both to show **ready**. Original files and indexes stay in `data/`.
3. Open **Ask your knowledge**. Ask: “When is the Aurora launch and readiness review?”
4. Open a numbered citation or Source evidence card. The viewer highlights the exact normalized passage; PDF originals open at the corresponding page.
5. Previous conversations are available in the sidebar; rename/delete controls appear on hover or keyboard focus.

For a completely offline demo without cached weights, set `NEXUS_EMBEDDING_PROVIDER=hash` in `.env`. It tests vector plumbing and lexical similarity, **not semantic understanding**. Keyword search remains real FTS5/BM25. Normal semantic use defaults to `onnx`, running the sentence-transformers MiniLM model directly on CPU. Model revision, dimension, quantized artifact and preprocessing belong to the index identity. Use **Settings → Build a replacement index** to change configuration; the old index remains searchable until validation/activation. Per-workspace selections persist across restart.

## Vaults, graph, and retrieval

- Open **Obsidian vaults**, import `examples/evaluation/vault.zip`, and wait for ready. Browse folders/tags, preview notes, inspect backlinks and unresolved/ambiguous links, and open the graph. A ZIP is a snapshot; **Update snapshot** applies only changed notes and revokes deleted notes immediately.
- For a real local folder, explicitly run `python scripts/vault_sync.py --root "C:\My Vault" --workspace WORKSPACE_ID --interval 15`. Use the printed vault ID with `--vault-id` on later runs; `--once` scans once. The browser cannot read/watch folders. See [Obsidian sync](docs/OBSIDIAN_SYNC.md).
- Chat supports keyword, dense, and hybrid modes; vault/document/tag/path/type filters; local follow-up reformulation; and optional diagnostics. Hybrid uses weighted Reciprocal Rank Fusion. Default reranking is off; optional cross-encoder weights load only when enabled and cached/download-permitted.
- Old note citations become visibly unavailable after revision/deletion, rather than opening unrelated new content. Immutable content documents may be shared by distinct stable note IDs. Existing Phase 1 citations are migrated into snapshots.

## Real generation, without a paid dependency

See [provider setup and caveats](docs/PROVIDERS.md). Put `NEXUS_GROQ_API_KEY` in the server `.env`, restart the API, choose Groq and a currently eligible model under **Settings & providers**, confirm your account/model's free-tier eligibility, and explicitly opt in for the selected workspace. Save settings and optionally check model availability. No secrets are accepted through or returned by the browser API. Your question and retrieved excerpts are sent to Groq only after opt-in. In offline mode no generation request is made.

## Checks

```powershell
.\scripts\test.ps1
# Browser checks, with API + web already running in mock/hash mode:
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Backend tests run with temporary storage, mock generation, hash embeddings, and real local Chroma. They require neither a key nor model downloads. For a semantic embedding smoke check, see [evaluation](docs/EVALUATION.md). The test script runs pytest, Ruff, TypeScript, ESLint and a production Next build. Browser testing generates screenshots in ignored `artifacts/`.

## Other platforms / manual installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r apps/api/requirements.lock.txt
cp .env.example .env
PYTHONPATH=apps/api OMP_NUM_THREADS=2 uvicorn nexus.main:app --host 127.0.0.1 --port 8000 --workers 1
# Separate terminal:
cd apps/web && npm ci && npm run dev
```

`requirements.lock.txt` pins the verified ONNX CPU profile. `requirements-ml.lock.txt` preserves the optional PyTorch resolver plan; that larger install remains unverified on this host. For it, install a CPU `torch==2.15.0` wheel from the official CPU index first. A fresh install on other operating systems is not claimed as tested; record a separate compatible resolution if needed.

## Reproducible retrieval evaluation

```powershell
# Public model download on first run; no generative provider or key:
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --embedding-provider onnx
# Fully model-offline plumbing comparison:
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --embedding-provider hash --output artifacts/retrieval-evaluation-hash.json
# Opt in to the real ONNX paraphrase test using cached weights:
$env:NEXUS_TEST_ONNX='1'
$env:NEXUS_MODEL_CACHE_DIR='data/models'
.\.venv\Scripts\python.exe -m pytest apps/api -q
```

The checked-in PDF/vault corpus has 12 labeled cases with stable source-span fingerprints. [Measured results and limits](docs/RETRIEVAL_EVALUATION.md) include Recall@3/MRR, unsupported-query hits, actual run conditions and no claim of general hybrid superiority.

## Map

```text
apps/api/
  nexus/             settings, SQL entities, scoped repository, extraction,
                     provider adapters, vector adapter, services, HTTP API
  migrations/        Alembic schema history
  tests/             unit, integration, isolation and API happy-path tests
apps/web/
  app/               App Router: chat, library, vaults, graph, settings
  components/        workspace UI, evidence/source dialog, native SVG icons
  lib/               typed HTTP client and upload progress
  tests/             Playwright browser flow
scripts/             Windows setup/run/test, folder sync, retrieval evaluation
examples/            demo documents, adversarial fixture, labeled PDF/vault corpus
docs/                architecture, API, data model, security, decisions,
                     RAG design, providers, deployment, evaluation
PHASE_1_REPORT.md    actual validation results, limitations, Phase 2 handoff
PHASE_2_REPORT.md    Phase 2 implementation, measurements and Phase 3 handoff
```

Use local mode only on loopback. Server mode adds authentication and roles, with TLS/reverse-proxy hardening required for network deployment. One API process owns each data directory. DOCX text/headings/tables are supported; image understanding is not enabled. Optional OCR needs Tesseract/tessdata and explicit CPU/time/page limits. Distributed workers, PostgreSQL/Redis adapters and external analytics are not implemented. No public deployment was performed. See [security](docs/SECURITY.md), [API contracts](docs/API.md), [decisions](docs/DECISIONS.md) and [Phase 3 report](PHASE_3_REPORT.md).
