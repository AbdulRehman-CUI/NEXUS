# Release candidate review

- [x] Phase 1/2 baseline recorded before edits; original data backed up while stopped.
- [x] Authenticated server sessions, CSRF, membership roles, A/B isolation and local exposure tests implemented.
- [x] Provider mocked contracts, exact destination consent, paid operator/workspace gates, no automatic fallback/retry.
- [x] Parser process bounds, DOCX, optional OCR path and job/index/sync recovery controls.
- [x] Executable stopped backup/restore and isolated consistency/tampering tests.
- [x] Offline labeled retrieval/source-grounding evaluation and actual 100-document CPU measurement.
- [x] Frontend type/lint/build and scoped Python static checks executed.
- [x] Docker profiles syntax validated; CI workflow and release notes prepared without publication.
- [x] Final local and server browser matrix and normal-data upgrade verified; see PHASE_3_REPORT.md for actual status.
- [ ] Fresh install on separate CPU Windows/Linux machine and hosted CI run.
- [ ] Docker engine runtime/build verification; engine unavailable on this host.
- [ ] Intended TLS/reverse-proxy domain validation and operational backup scheduling.
- [ ] Optional live provider/OCR/cross-encoder/Ollama checks if those features will be enabled.

Do not publish a security/compliance claim from this checklist. Optional live integrations may remain disabled. An RC tag requires a real reviewed commit; this checkout began with no commits, so release notes are prepared without inventing a tagged revision or pushing user data.
