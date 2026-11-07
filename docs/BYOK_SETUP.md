# Personal AI providers (BYOK)

NEXUS remains free to install and use with the offline extractive demo or a locally installed Ollama model. Cloud accounts, free quotas and any provider charges belong to the person supplying the API key. NEXUS never upgrades a plan, retries generation automatically or silently falls back to another provider.

## Configure a personal model

1. Open **Settings → Models & privacy → Add configuration**. Choose OpenRouter, Google Gemini, OpenAI, Anthropic, Groq, local Ollama or a custom OpenAI-compatible endpoint.
2. Enter a configuration name. For cloud services, paste your API key into the masked field. Show/hide applies only to this unsaved input; a persisted key is never downloaded again.
3. Use **Test connection & load models**, then search/select a catalog model or enter a manual identifier. A metadata connection test checks reachability/authentication where supported; it does not generate an answer or prove that every model option will work. Public/custom metadata endpoints cannot prove authentication, which is stated in the result.
4. Set output/context limits and streaming. Unsupported/unadvertised temperature settings are omitted. For custom APIs, choose the output-limit parameter required by that endpoint.
5. For cloud inference, explicitly consent to sending the question, relevant conversation context and retrieved excerpts to the selected provider. Acknowledge the provider's billing/quota terms when prices are paid or unknown. This acknowledgement does not require a paid account; free-tier keys work too. Unknown pricing is never labeled free.
6. **Save personal configuration**, then **Use here** or **Make default**. Workspace owners must separately enable workspace cloud permission. A personal consent cannot override a workspace restriction.
7. Use **Active personal model** in chat to switch configurations, choose the personal default, or explicitly choose the workspace model. Generative model changes do not reindex documents.

You can edit model parameters, replace a key, remove the stored key, remove the configuration, and clear a personal default. Provider/destination changes require a separate configuration, so an existing key can never be silently transferred to another host. Removing an active/default configuration stops that route until you explicitly select a replacement. Removing a key from NEXUS does **not** revoke it at the provider; revoke it in that provider's account console when necessary.

## Enable encrypted storage as the operator

Install the updated API dependencies using the existing setup scripts or the pinned runtime lock. Persistent cloud credentials are disabled if no valid master key is configured. The offline demo and keyless local Ollama remain usable.

From the repository root:

```powershell
.venv\Scripts\python.exe scripts/manage_byok_key.py
```

Set this non-secret file reference in the API's `.env`/runtime configuration, then restart the API:

```dotenv
NEXUS_BYOK_MASTER_KEY_FILE=.secrets/byok-master.key
```

The helper generates 32 random bytes encoded as base64. On Windows its dedicated directory permits the current user and SYSTEM; on Unix it creates a private directory and a mode-0600 file. Existing keys are never overwritten or printed. Use a new/empty dedicated `.secrets` or `nexus-secrets` directory, outside `NEXUS_DATA_DIR`; existing directories containing files are not modified. Both names are ignored by Git. Run the helper as the account that runs NEXUS, or deliberately grant the service identity access using your deployment's secret-management system.

Alternatively inject `NEXUS_BYOK_MASTER_KEY` from a runtime secret manager as base64-encoded 32-byte key material. Set **one** source, not both. A missing, malformed, inaccessible, overly broad Unix key file or file inside the data directory disables credential persistence. Existing encrypted keys also fail closed if the correct master is unavailable. Do not change the master key without first planning credential re-encryption/replacement. Losing it makes saved credentials unrecoverable.

In the supplied local installation the helper has already created the private key file and `.env` contains its path. No personal provider API key was installed.

## Ownership, encryption and backups

Server configurations belong to the authenticated account, not to a shared workspace. Configurations, model catalogs, selections and usage are filtered by that owner even for server administrators using the API. Workspace membership and edit permissions still govern chat and retrieval; workspace owners govern cloud excerpt permission. The existing cookie, CSRF, CORS and host boundaries apply to every mutation.

The local profile explicitly treats loopback clients as a single local installation owner. It is not a multi-user deployment. Use the authenticated server profile whenever separate people/accounts need isolation.

The database stores AES-256-GCM ciphertext with a fresh 96-bit nonce and authenticated owner/configuration/provider/destination binding. The master stays outside the database. Plaintext is used only in process memory for the selected provider's authorization header; it is excluded from API responses, prompts, request logs, diagnostics, usage and settings exports. Unsaved browser input stays in React memory, never localStorage/sessionStorage.

The server operator and anyone able to read both the database and master key can decrypt credentials. This is server-side encryption, not end-to-end encryption against the operator. Protect both resources with filesystem/service permissions and a trusted runtime. Back up the master separately in a protected secret store. Database backups contain encrypted credentials but deliberately do not bundle this external master. Deleted keys may remain as encrypted historical bytes in SQLite WAL/backups until retention/maintenance removes them; local removal is not forensic erasure or provider revocation.

## Deployed HTTPS and endpoints

Keep the default secure-cookie setting for server deployments, terminate HTTPS at a trusted reverse proxy and configure trusted forwarded headers, exact allowed hosts and CORS origins. BYOK configuration endpoints require HTTPS in server mode with secure cookies enabled. The HTTP exception used by isolated tests is not a production setting.

Named providers use fixed HTTPS origins and their own API protocols. Google credentials are sent in a header, never in a query string. Redirects, environment proxies, fallback providers and automatic retries are disabled.

Custom endpoints require an operator-approved origin:

```dotenv
NEXUS_PROVIDER_ALLOWED_ORIGINS=["https://models.example.com"]
```

Users may then enter that HTTPS origin with an optional `/v1` path. User info, query strings, fragments and private/reserved network destinations are rejected. Custom requests pin a validated public DNS address while preserving the original TLS server name and Host, avoiding a second DNS lookup after validation. Do not add untrusted origins to the operator allowlist.

Ollama uses the operator-controlled `NEXUS_OLLAMA_BASE_URL`, a literal loopback HTTP origin (default `http://127.0.0.1:11434`). Install/pull models yourself. NEXUS filters cloud-tagged entries and checks `/api/show` before inference; remote-backed aliases are refused before excerpts are transmitted. A local endpoint alone is not accepted as proof that a model is local.

## Streaming, usage and limits

BYOK adapters support provider SSE or Ollama NDJSON. The chat SSE endpoint labels deltas provisional. Provisional text has no interactive citations; the existing source/citation validation runs before the final answer is saved and displayed with source buttons. Unknown citation IDs, changed sources, malformed/truncated streams and provider failures do not save an unverified answer. The original non-streaming JSON endpoint remains supported, and disabling streaming uses non-streaming provider inference.

Stopping delivery closes the browser request and signals the worker to stop/discard where possible. A provider may still finish/bill partial work; an in-flight read is bounded by HTTP timeouts. Check history before retrying. Four simultaneous streams and bounded response/queue sizes limit resource use; this is the existing single-process deployment model, not a distributed cancellation system.

Private usage records include model/provider, timestamp, latency, outcome and provider-reported token counts when available. Unknown tokens/costs remain unknown. OpenRouter-reported cost is labeled **provider reported**; costs computed from reliable catalog token prices are **estimated model pricing**. Monthly warnings include known costs and explicitly disclose unknown-cost requests. Warnings are local observations, not provider-side spending enforcement. Daily per-configuration call limits count attempted generations, including failures that might have been billed.

Catalogs are bounded to 1,500 entries from a provider response; paginated catalogs may be incomplete. The UI filters up to 200 matching options. Manual IDs remain available. Context assembly uses a conservative UTF-8 byte bound against configured/advertised token windows and output reservations; it is not a claim of universal exact tokenization. Provider-specific reasoning/tool/image options beyond the implemented text controls are not enabled.
