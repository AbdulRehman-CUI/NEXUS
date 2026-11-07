# Phase 3 implementation and risk register

Baseline (before edits, 4 November 2026): backend 55 passed / 1 optional PyTorch skip, 30.51s; Ruff clean. Frontend typecheck, lint and production build passed. Preserved browser suite: 2 passed, 21.8s. Existing Phase 2 data copied while stopped to ignored `artifacts/phase2-data-backup`.

| Priority / requirement | Existing path / intended change | Verification |
| --- | --- | --- |
| Critical: identity/IDOR | Central Repository + new session/membership policy; explicit loopback local vs authenticated server profile; migration preserves unclaimed legacy data | Synthetic A/B users across every route, roles, CSRF, expiry/logout and local exposure |
| Critical: outbound consent/secrets/cost | Keep old Groq contract; workspace route policy + durable model registry; optional vendor adapters, destination allowlist, no fallback | Mocked vendor contracts, SSRF, consent switches, timeouts/429/redaction/budgets |
| High: upload/process/resource limits | Existing ZIP/path guards; bounded extraction subprocess, DOCX text/tables, optional OCR; persistent job controls | Malformed DOCX, worker timeout, retry/cancel/recovery, stale source |
| High: backup/index failure | Stopped-process backup/restore with manifest hashes and isolated validation; corruption must fail visibly, not silently mix | Restore fixture SQL/files/FTS/graph/vectors; missing vector/index tests |
| Medium: observability/evaluation | Safe correlation/request/job/usage events; feedback and identical-evidence comparison; expand golden cases | Redaction/retention/AuthZ tests; actual offline metrics and 100-document measurement |
| Release: reproducibility | Keep pinned stack; Docker CPU/local + explicit optional Ollama; Windows/Unix scripts, CI and migration checks | Available syntax/runtime checks; report Docker/fresh install blockers accurately |
| Product | Login/logout/membership, workspace model control, jobs/diagnostics/feedback/help/settings transfer, original design | Backend + browser full regressions, mobile/focus/source navigation |

Implementation uses finished vertical slices. No external deployment, paid calls, new heavyweight model, destructive reset, or publication. Optional unavailable OCR/model/provider runtime tests will be marked blocked or skipped. Authentication is a release gate, not a certification. User-provided Phase 3 prompt takes precedence over historical phase stop instructions.

Completed local implementation and validation: 72 backend passes / one optional skip, three local browser passes plus separate server pass, real authenticated CLI create/edit/rename/delete, isolated backup/restore and original-data 0003→0004 upgrade. Final status/remediation for unperformed Docker runtime/remote CI/fresh install/optional live integrations is in PHASE_3_REPORT.md. No further phase started.
