# Generation and embeddings

## Offline mode

`NEXUS_GENERATION_PROVIDER=mock` is the safe no-key default. `MockGenerationProvider` quotes retrieved passages with real server citations and a visible extractive-demo label. It does not synthesize facts or obey document instructions. `NEXUS_EMBEDDING_PROVIDER=hash` also eliminates model downloads for offline tests/demo; normal use defaults to the ONNX MiniLM adapter.

## Groq Free Plan

Groq was selected after checking its official [rate-limit documentation](https://console.groq.com/docs/rate-limits) and [OpenAI-compatible API contract](https://console.groq.com/docs/openai) on 4 November 2026. Its [billing FAQ](https://console.groq.com/docs/billing-faqs) and your account console determine eligibility. Free-tier models, quotas, regions, account conditions and availability can change. An example model ID is configuration, not a guarantee of ongoing eligibility.

1. Use an eligible **Free Plan** account; obtain an API key from the provider's console. No paid signup is needed to run NEXUS locally.
2. In the repository-root `.env`, set `NEXUS_GROQ_API_KEY=...`, then restart the API. Do not paste the key into the browser or a document.
3. Open Settings, choose Groq, enter a model ID currently available to your free account, confirm free eligibility, and explicitly opt in for the selected workspace. Save.
4. Check the saved provider configuration. This calls `/models` without transmitting document excerpts. It confirms key/model reachability, **not billing tier or remaining quota**.
5. Ask a question. Only the current question and bounded retrieved evidence are transmitted. The adapter uses the fixed Groq HTTPS chat-completions endpoint, no vendor SDK, no model/provider fallback, and a 45-second timeout. Rate limits return actionable HTTP 429; missing/rejected keys and unavailable models fail clearly.

`NEXUS_FREE_TIER_CONFIRMED=true` is an operator assertion. **The API cannot verify an account's billing tier or guarantee zero charges if you use a paid account/key.** Keep the provider account on its Free Plan and do not enable billing. NEXUS makes no automatic upgrades and supplies no other paid endpoint. Consent can be revoked in Settings; a request already sent cannot be recalled.

Only Groq and mock generation are implemented. OpenAI, Anthropic, Gemini, Ollama, generic OpenAI-compatible endpoints and hosted rerankers are future adapters, not completed integrations. Changing generation does not rebuild the index. Provider/model settings are global for this local app; cloud consent is per workspace.

## CPU semantic embeddings

Phase 2 default: **ONNX MiniLM**, using the official [quantized artifact](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/onnx/model_quint8_avx2.onnx) at pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The downloaded graph was **23,046,789 bytes**, plus tokenizer JSON. ONNX Runtime and Rust tokenizers were already Chroma dependencies. The adapter runs CPUExecutionProvider, two intra-op threads, batch eight, max 256 tokenizer tokens, attention-mask mean pooling and L2 normalization. It emits verified 384-dimensional sentence embeddings without PyTorch. Real paraphrase retrieval and the labeled benchmark were executed successfully.

`NEXUS_EMBEDDING_PROVIDER=onnx` is now the normal default; `hash` is a deterministic plumbing demo. `sentence-transformers` retains the optional PyTorch adapter described below. Install optional ML packages with `scripts/setup.ps1 -WithTorch` for that adapter or a local cross-encoder. The default lock no longer installs PyTorch. Optional cross-encoder execution remains lazy/cache-only unless `NEXUS_RERANKER_ALLOW_DOWNLOAD=true`; failure preserves the original rank with a warning. No hosted reranker is implemented.

Choose model/revision/dimension/artifact in the versioned rebuild workflow. The model identifier is validated and the revision is immutable. Fingerprints include provider, revision, vector dimension, quantized artifact/pooling/normalization and adapter/preprocessing revision; dependency versions remain locked. Changing preprocessing implementation requires a new adapter/preprocessing revision. Models cache under `NEXUS_MODEL_CACHE_DIR`, default `data/models`; after caching, `HF_HUB_OFFLINE=1` disables model-download network access. Model downloads do not send document passages to Hugging Face.

The following original PyTorch option remains supported but was not executed on this host:

Optional PyTorch model: `sentence-transformers/all-MiniLM-L6-v2`, pinned revision, CPU, normalized vectors, batch eight, two CPU threads, no remote model code. The [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) describes the ~90.9 MB float32 weights. Dependencies are substantially larger. Use a validated replacement index to change model configuration; current source citations survive model-only index changes.

No local generative LLM is downloaded. The default model's first load needs network unless cached. After caching, use `HF_HUB_OFFLINE=1` for a model-offline run. A failed model download leaves a failed/retryable job; it never silently switches to hash embeddings.
