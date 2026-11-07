# Model routing, consent and budgets

Personal encrypted BYOK configurations now take precedence when selected. They support private provider catalogs, metadata connection tests, capability-aware parameters, provisional streaming and private usage. Start with [BYOK setup, ownership and endpoint safeguards](BYOK_SETUP.md). The registry, environment credentials and non-streaming workspace routes described below remain the legacy fallback **only when explicitly selected or no personal default exists**. A removed active/default personal configuration blocks its route instead of silently falling back.

Generation, embeddings, reranking and vector storage are independent. `/api/models` returns the durable installed adapter registry, capability schema, configuration status and destination. Model IDs are manual because catalogs change. Capabilities describe what NEXUS implements: verified non-streaming text generation, no tool/image execution and no generic structured-output promises. Provider-native features are not automatically enabled.

| Generation route | Configuration | Gates / status |
| --- | --- | --- |
| mock | No key or weights | Default extractive diagnostic, not an intelligent LLM |
| Groq | `NEXUS_GROQ_API_KEY` | Workspace cloud opt-in, exact destination consent, operator/account free eligibility confirmation |
| OpenAI | `NEXUS_OPENAI_API_KEY` | Operator paid allowlist + workspace allow_paid + cloud/destination consent |
| Anthropic | `NEXUS_ANTHROPIC_API_KEY` | Same paid/remote gates |
| Google | `NEXUS_GOOGLE_API_KEY` | Same paid/remote gates; no free eligibility assumed |
| compatible | Key, `NEXUS_COMPATIBLE_BASE_URL`, exact `NEXUS_PROVIDER_ALLOWED_ORIGINS` | HTTPS public-address endpoint with optional `/v1`; same paid/remote gates |
| Ollama | Explicit installed server/model at literal loopback `NEXUS_OLLAMA_BASE_URL` | Local Optional preset; no automatic server start/model pull, no remote key |

All optional adapters have realistic mocked request/response contract tests. No live optional provider result is claimed without supplied credentials/hardware. The legacy global mock/Groq controls remain backward compatible; a saved workspace route overrides them. Generation changes do not rebuild embeddings. Per-workspace policies persist in SQL; embedding changes remain isolated validated index-generation rebuilds.

Default paid allowlist is empty. To intentionally configure a paid adapter, the operator sets e.g. `NEXUS_PAID_PROVIDER_ALLOWLIST=["openai"]` and its environment key, restarts, then a workspace owner selects Cloud Optional, a model ID and bounded settings, enables workspace cloud permission and checks the exact destination and paid permission. A key alone does not activate an adapter. New remote provider/destination consent cannot reuse the previous destination string. Revocation blocks subsequent requests; already transmitted data cannot be recalled.

Presets are conservative routing choices: Free/CPU = mock or eligible Groq with existing two-thread/batch-eight CPU embedding path; Local Optional explicitly enables a chosen installed Ollama model with two threads/8192 context; Cloud/Hybrid Optional enables only individually permitted remote routes. Retrieval candidates/context and embedding jobs remain bounded independently. Do not interpret a preset as proof of available RAM or provider quota.

Generation timeout is 1–120 seconds, output cap 64–4096 tokens, retries fixed at zero. A timeout may have consumed provider usage, so there is no automatic generation retry or provider/model fallback. Every reserved non-mock attempt counts toward the persisted daily cap, including failures; deleting diagnostics keeps today's enforcement counters. The same-evidence comparison respects the saved workspace cap. No price catalog is embedded: cost is unknown, not billed cost. Tokens are provider-reported when present, otherwise explicitly estimated as UTF-8 bytes/4. Catalog checking sends no passages and does not establish remaining quota/billing eligibility.

The UI never accepts or echoes API keys. Keys stay in operator environment/system secrets; no encrypted key database is claimed. Custom credentials are sent only to the validated configured endpoint; redirects and environment proxies are disabled. Restrict network egress for server deployment; the custom-host DNS validation does not eliminate DNS-rebinding races. No remote embedding or reranker adapter is advertised as implemented; those interfaces remain independent extension boundaries.

Official contracts consulted: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Google GenerateContent](https://aistudio.google.com/api-reference/generate-content), [Ollama chat](https://docs.ollama.com/api/chat). The Anthropic adapter uses its established 2023-06-01 compatibility header. Unknown/incompatible models/parameters fail explicitly rather than silently changing routes. Existing Groq instructions remain in [PROVIDERS.md](PROVIDERS.md).
