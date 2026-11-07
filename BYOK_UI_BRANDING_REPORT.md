# BYOK, UI and browser branding implementation

Implemented directly in the existing FastAPI/Next.js application. The retrieval, reranking, index, citation-verification and workspace authorization pipelines remain in place. Existing JSON chat and workspace policy APIs are compatible; new private configuration APIs and an SSE endpoint extend them.

## Files created or modified

| Area | Files |
| --- | --- |
| API | `nexus/byok.py`, `provider_transport.py`, `routes_byok.py`; updates to `config.py`, `database.py`, `gateway.py`, `service.py`, `main.py` under `apps/api/` |
| Schema/dependencies | `apps/api/migrations/versions/0005_byok.py`; runtime, CPU and optional-ML requirements/locks (cryptography 50.0.2, cffi 2.1.1, pycparser 3.12) |
| UI | `apps/web/components/byok-controls.tsx`, `lib/byok.ts`; updates to chat/workspace, release controls, navigation, icons, typed API client and shared CSS |
| Branding | Root/page metadata; `public/icon.svg`, `favicon.ico`, 16/32px PNGs, Apple 180px icon, optional 192/512px icons; `scripts/generate_branding.py` |
| Key management | `scripts/manage_byok_key.py`, `.env.example`, Git/Docker exclusions; the local ignored `.env` references a private runtime key file |
| Tests/docs | New `test_byok.py` and `byok.spec.ts`; updated gateway/migration and existing UI tests; `docs/BYOK_SETUP.md`, provider/security/deployment guides, README and this report |

## Provider architecture and ownership

Personal configurations support **OpenRouter, Google Gemini, OpenAI, Anthropic, Groq, local Ollama and approved custom OpenAI-compatible HTTPS endpoints**. Existing environment-key workspace routes remain available. Personal active/default selections take precedence; the chat selector can explicitly choose a personal configuration, personal default or workspace model. Generative switching does not change embeddings or reindex documents.

Each server configuration, cached catalog, selection and usage record belongs to its authenticated account. Shared workspace membership does not share credentials/model settings, and administrator status does not bypass personal ownership checks through the API. Cross-owner IDs return 404. Existing cookie authentication, session-bound CSRF, host/CORS controls and workspace roles remain active. The local profile explicitly uses one shared loopback installation owner; multi-user installations must use server mode.

Provider destinations are immutable for a configuration: changing provider/host requires a separate configuration. Removing a selected/default configuration leaves a non-secret route tombstone so a missing local model cannot silently become a cloud or paid fallback. Users can explicitly clear the default or choose a different route.

## Credential storage and encryption

API keys use **AES-256-GCM**, fresh random 96-bit nonces and authenticated owner/configuration/provider/destination binding. Only ciphertext is stored in SQLite. The master is a base64-encoded 32-byte runtime secret outside `NEXUS_DATA_DIR`, supplied by a protected file or environment secret manager. Missing/invalid/inaccessible configuration disables persistent credentials; plaintext fallback does not exist.

The local runtime master file was created under ignored `.secrets/`, with its path in ignored `.env`. Its bytes were preserved while directory/file ACLs were verified as the current Windows account plus SYSTEM. The helper refuses overwrites and prints no key material. Secrets are excluded from Docker contexts as well as Git. No personal cloud credential was installed.

Saved API responses return only `credential_configured`; they never return the key, ciphertext or a recoverable saved value. Browser input is password-masked, with show/hide for unsaved input only, and clears after save. Credentials never enter localStorage/sessionStorage, grounded prompts, usage or logs. Validation/provider errors are sanitized, including Pydantic's normal rejected-input reflection. Provider metadata/output redaction also handles escaped and split credential text.

The server operator remains trusted: someone with the database and master can decrypt credentials. Database backups contain ciphertext; master backups must be stored separately and protected. Removing a stored key is not provider-side revocation or forensic erasure of historical encrypted WAL/backups. See `docs/BYOK_SETUP.md` for access, loss and replacement procedures.

## Privacy, endpoint and inference behavior

Cloud inference requires **both** personal provider consent and workspace owner cloud permission. Paid/unknown pricing requires an explicit billing/quota acknowledgement; this does not require a paid plan. Free tiers and local/offline operation remain supported. Workspace permission stays synchronized across personal and legacy controls.

Named providers have fixed HTTPS destinations and distinct protocol/header/body handling. Custom endpoints require an operator-approved HTTPS origin and public addresses, with redirects/environment proxies disabled. A validated address is pinned while retaining TLS server name and Host, avoiding DNS re-resolution after validation. Ollama uses literal server loopback only; cloud tags and remote-backed aliases detected through `/api/show` are refused before excerpts are sent, including the legacy adapter.

Model catalogs support search, metadata, trustworthy free/paid labels and unknown-price states. Manual identifiers remain accepted independently of cached listings. Output tokens, configured/advertised context limits, excerpt-byte budget, streaming, supported temperature, timeout and daily call limits feed the actual gateway. Temperature is omitted for unadvertised/reasoning combinations. Conservative context reservations are checked before sending the complete grounded prompt.

BYOK streaming consumes SSE for supported cloud protocols or Ollama NDJSON. `/api/chats/{id}/messages/stream` emits provisional deltas; the frontend batches display updates and exposes no provisional citation buttons. The existing verifier rejects unknown citation IDs and changed sources before the final answer is saved/published. Provider errors, malformed/truncated streams and disconnects do not intentionally save an unverified answer. The JSON endpoint remains supported; turning streaming off uses non-streaming provider inference.

Stopping closes delivery and signals the worker. Provider-side cancellation and billing reversal are not guaranteed; an in-flight read can last until its timeout. Four simultaneous streams, bounded queues/response sizes and request caps limit resource use. No automatic generation retries or fallback providers run; OpenRouter fallback routing is explicitly disabled.

## Connection tests and usage transparency

Tests make real authenticated metadata requests, not a key-present check or unnecessary inference. OpenRouter uses `/auth/key` because its model list is public. Saved tests persist checked status; unsaved previews use credentials only in memory. Local/custom results explicitly say metadata endpoint response is not proof of inference/authentication compatibility. Missing manual IDs are reported as unlisted rather than being rejected at save.

Fixed recovery messages distinguish invalid credentials, quota/credit exhaustion, temporary rate limits, unavailable models/providers and network failures. Provider authentication failures do not masquerade as NEXUS session expiry. Raw upstream error bodies are never forwarded.

Private usage records provider/model, timestamp, outcome, latency and provider-reported token counts when supplied. Missing counts remain unknown. OpenRouter-reported USD cost is labeled reported; estimates from reliable catalog token rates are labeled estimated. Monthly summaries show known cost and unknown-cost request counts. Optional local spending warnings and daily attempt caps do not enforce provider-side billing or invent unknown prices.

## Dropdown root cause and correction

The retrieval selector inherited light text while native popup options could use a system-white surface, particularly on Windows/Chromium. Styling only the closed selector was insufficient. All native selects/options/optgroups now use shared theme surface/text tokens and an explicit color scheme, with a distinct selected surface, disabled styling and focus outline. This applies across retrieval, provider/model, graph, vault and settings controls.

The existing native select remains the accessible primitive; no second component framework was introduced. Browser tests verify dark/light option colors, keyboard selection and that choosing Keyword updates the actual RAG request's `options.mode`. Searchable provider catalogs pair a filter with the same native select and retain manual entry.

## Browser branding

An original geometric N with a connected-node accent matches the charcoal/periwinkle/mint palette. Real SVG, multi-size ICO (16/32/48/64), 16/32 PNG, Apple and optional web-app assets are included. Root metadata uses **NEXUS — Personal Knowledge Intelligence**; nested routes use Knowledge Library, Knowledge Graph, Models & Privacy, Obsidian Vaults and Diagnostics titles. Icons, description, application name and theme color use Next App Router metadata. Appearance changes update theme color.

Fresh Chromium contexts verify asset resolution and nested-route/reload metadata. Actual PNG dimensions and ICO entries were decoded/checked. Browser favicon caches may require a hard refresh or fresh profile after replacing an older generic icon. No service worker or private-data cache was introduced.

## Validation

| Check | Result |
| --- | --- |
| Complete backend pytest suite | **102 passed, 2 skipped**, 171.87 seconds. Skips are the opt-in real MiniLM/PyTorch and real ONNX download/runtime checks. |
| Ruff, API contract mypy, dependency consistency | Passed; no broken runtime requirements. |
| Frontend TypeScript, ESLint, production build | Passed. All existing routes generated. |
| Complete local Chromium suite | **11 passed, 1 server-fixture skip**, 2.3 minutes. Includes all prior upload/vault/graph/index/settings/auth-boundary frontend regressions and three new BYOK/branding scenarios. |
| Separate authenticated server Chromium test | **1 passed**, 6.9 seconds; login, private upload, memberships and logout. HTTP test cookies were confined to the synthetic fixture. |
| Key-file helper and Windows ACLs | Valid 256-bit generation, no printed material, overwrite refusal and unchanged existing key verified. Runtime file and directory each grant the current account and SYSTEM only. |
| Branding files | PNG dimensions decoded and ICO 16/32/48/64 entries verified; all asset URLs return 200, including nested/reloaded metadata. |

Backend coverage includes owner isolation, ciphertext/AAD integrity, replacement/removal, missing-master failure, seven protocols in streaming/non-streaming modes, auth/quota/network errors, private reported usage/cost, deleted-default blocking/recovery, conservative context, unknown citations, cancellation, truncated responses, escaped/split credential redaction and remote-backed Ollama refusal. A server SSE test preserves the authenticated actor and private usage across the worker boundary.

Browser coverage includes masked/show/hide unsaved keys, real encrypted configuration CRUD, consent refusal/approval, defaults and chat selection, local metadata checks, an actual loopback fixture → RAG → streaming → verified source flow, usage display, unchanged document versions, 390px settings, select themes/keyboard/request values, metadata and favicon resolution. Browser runtime errors are asserted absent. Cloud metadata was mocked in UI tests; local streaming used a synthetic HTTP provider, not a paid account.

Regressions corrected during validation included model-field accessible names, an asynchronously controlled cloud checkbox, shared permission state between personal/legacy settings, status assertions after adding a second status region, and the atomic provisional-to-verified response swap.

Normal local storage is restored. Schema 0005 passed SQLite integrity/foreign-key checks; original documents, chats, messages, citation payloads, workspace privacy flags, model policies and retrieval profiles compare exactly to `artifacts/backups/before-byok.zip`. The normal data has 12 documents, 21 indexed chunks and no synthetic personal configurations. The cached ONNX model profile and original source snapshots remain in use.

Read-only final review confirmed encrypted storage enabled, zero personal configurations, the existing Aurora source highlight, a 390px settings layout without page overflow and no browser runtime errors. SVG/ICO/PNG URLs returned their proper image MIME types. Evidence is retained in `artifacts/byok-final-review.json`, `byok-normal-data-validation.json` and `byok-final-*.png`.

## End-user and operator setup

Full instructions: **`docs/BYOK_SETUP.md`**. The local encryption master is already configured. Open Settings → Models & privacy, add a provider, enter your own key, test/load models, choose a model or manual ID, review privacy/billing controls, save and select **Use here** or **Make default**. Cloud inference also needs workspace cloud permission.

For a fresh installation, install pinned API dependencies, run `python scripts/manage_byok_key.py` in a new/empty dedicated secrets directory, set `NEXUS_BYOK_MASTER_KEY_FILE` outside the data directory, then restart the API. Use HTTPS/secure cookies and a separately mounted secret for deployed server mode. No live cloud key, billing setup, model download or deployment is required for the free local application.

## Remaining limitations

- Live commercial/free-tier accounts were not called during tests. Protocols were exercised with mocked responses; real end-to-end browser streaming used a synthetic loopback Ollama fixture. Provider availability, account scopes, regional limits and future model quirks still require the user's connection/inference check.
- Connection tests validate metadata/authentication where supported, not generation quality, billing eligibility or every parameter. Custom endpoints can expose public metadata; their status explicitly does not claim the key was authenticated.
- Catalogs are bounded to 1,500 entries from a response; pagination can be incomplete. The dropdown shows at most 200 filtered options. Manual IDs remain available. Only implemented text-generation protocols are supported; Responses-only APIs, arbitrary provider-specific tools/images/options and OAuth credentials are outside this implementation.
- Context accounting is deliberately conservative; unknown limits must be configured, and it is not a universal exact tokenizer. Local warnings cannot see external requests made directly with the same provider key.
- This remains the existing single-process deployment. Reverse-proxy HTTPS/stream buffering, physical-device/native-select behavior outside tested Chromium, fresh container installs and other browsers remain deployment checks. No security certification or provider-side cancellation guarantee is claimed.
- Losing/changing the encryption master makes old credentials unusable. Automated master-key rotation and provider-account revocation are not implemented; protect the master and replace credentials deliberately.
