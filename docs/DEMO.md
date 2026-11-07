# Reproducible no-key demo

1. Run the Windows setup and API/web scripts from README; keep `mock` generation and CPU ONNX embeddings (or explicit hash for no cached weights). Open `http://127.0.0.1:3000`. The mock label remains visible.
2. In local mode use the initial workspace; in server mode sign in and create a private workspace. Import `examples/aurora-brief.pdf` and `examples/aurora-notes.md`. Wait for ready. A duplicate upload should reuse the same content document.
3. Ask “When is the Aurora launch and readiness review?” Open a citation and inspect its exact stored passage/page or heading. No secret/key is needed. An available citation proves source identity, not generated-claim entailment.
4. Import `examples/evaluation/vault.zip` in Obsidian vaults. Expected: ten notes, curated tags, resolved authored links, and explicitly unresolved/ambiguous/blocked targets. Browse `Projects/Aurora.md`, inspect backlinks and open its graph node/source. Use keyword/vault/tag filters in chat.
5. Update with `examples/evaluation/vault-update.zip`: nine notes, a changed Aurora date/token, renamed recovery note and deleted Mira note. Old citations become unavailable; the changed text is retrieved; graph reflects the current manifest.
6. In Settings build a compatible replacement index; old index remains active during the build. Verify progress, activation and a coverage-valid rollback. For a simple deterministic dimension demonstration use an explicitly selected hash provider; ONNX model/dimension must match its real output.
7. Save a workspace mock model ID and reload to verify persistence. Optional providers show missing/disabled status until configured. Enabling a remote provider requires exact destination/cloud consent and any paid/operator permission; never use a live paid key just to make the demo pass.
8. Mark an assistant answer helpful/wrong citation; inspect the private review queue under Diagnostics & help. Run a same-evidence comparison with the saved mock route. Both answers are extractive demos; no fake unavailable output is generated. Export settings; inspect the JSON for absent keys/local paths; import clears consent and leaves index rebuild explicit.
9. Stop the API, create a backup and restore to a new isolated directory using BACKUP_RESTORE.md. Restart with that directory, open the saved citation, query and inspect graph. Restore revokes sessions, so server accounts sign in again.

All bundled documents/vault/evaluation questions are synthetic and contain no user PDF. The hostile fixture is deliberately untrusted text. No original user data is packaged into a release artifact.

Manual release review still required: fresh installation on another machine, real browser PDF viewer appearance, TLS/proxy cookie/host behavior for the intended server domain, optional OCR and chosen live provider/account quota. None is implied by mock/browser tests.
