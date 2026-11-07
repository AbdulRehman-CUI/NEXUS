# Phase 2 implementation checklist

- [x] Review Phase 1 reports, contracts, architecture, code and tests; baseline: 28 pytest tests, Ruff, TypeScript and ESLint passed.
- [x] SQLite FTS5, dense/keyword/hybrid strategies, filters, diagnostics, local query reformulation and optional reranking.
- [x] Secure ZIP parsing, normalized vault/note/tag/link records and citation provenance.
- [x] Durable incremental snapshot/agent sync, immediate revocation, rename matching and recovery.
- [x] Scoped graph API and accessible graph/vault UI integrated into existing navigation.
- [x] Resumable index generations, validation/activation/rollback and safe old-index availability.
- [x] Synthetic corpus, reproducible retrieval metrics, security/regression/browser checks; real quantized MiniLM ONNX inference passed without PyTorch.
- [x] Updated contracts/setup/security/decisions and actual Phase 2 handoff report.

Constraints: preserve existing data and local single-user scope; no heavyweight local LLM or paid dependency. Initial host free space was about 120 MB; the CPU ONNX profile was validated using a small pinned model download. Hash-vector results are not semantic model quality. No live cloud request without existing privacy/key/free-tier gates.
