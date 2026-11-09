"""Bounded provider protocols. Secrets never enter URLs, prompts, errors or telemetry."""

import ipaddress
import json
import math
import socket
import time
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .gateway import ENDPOINTS, destination
from .providers import SYSTEM_PROMPT, ProviderError

BASES = {**ENDPOINTS, "openrouter": "https://openrouter.ai/api/v1"}
PROVIDERS = [
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "description": "One key, a searchable model catalog.",
        "remote": True,
    },
    {
        "id": "google",
        "name": "Google Gemini",
        "description": "Gemini's native generation API.",
        "remote": True,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "OpenAI chat models with your account.",
        "remote": True,
    },
    {"id": "anthropic", "name": "Anthropic", "description": "Claude's native Messages API.", "remote": True},
    {
        "id": "groq",
        "name": "Groq",
        "description": "Fast inference; account quotas still apply.",
        "remote": True,
    },
    {
        "id": "ollama",
        "name": "Ollama",
        "description": "Installed models on this server's loopback interface.",
        "remote": False,
    },
    {
        "id": "compatible",
        "name": "Custom endpoint",
        "description": "An operator-approved OpenAI-compatible HTTPS endpoint.",
        "remote": True,
    },
]


class ProviderFailure(ProviderError):
    def __init__(self, code, message, status=502):
        self.code = code
        super().__init__(message, status)


class GenerationCancelled(ProviderFailure):
    def __init__(self):
        super().__init__(
            "cancelled", "Response stopped; the provider may still account for partial usage.", 409
        )


def base_url(settings, provider, custom=""):
    if provider == "compatible":
        return destination(settings.model_copy(update={"compatible_base_url": custom}), provider)
    if provider == "ollama":
        from .auth import principal

        if principal.get() and principal.get().guest:
            raise ProviderFailure(
                "local_unavailable",
                "Ollama requires a server-local installation and is unavailable in guest mode.",
                403,
            )
        return destination(settings, provider)
    return BASES[provider]


def temperature_supported(provider, model, metadata=None):
    if provider == "openrouter":
        return "temperature" in (metadata or {}).get("supported_parameters", [])
    if provider == "openai":
        return model.startswith(("gpt-4", "gpt-3.5", "chatgpt-4"))
    # Omit for unadvertised Claude/reasoning models, rather than guessing support.
    return provider in {"google", "groq", "ollama"}


def nonnegative(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 <= value <= 1_000_000 else None
    except (ValueError, TypeError):
        return None


def token_count(value):
    return value if type(value) is int and 0 <= value <= 10_000_000 else None


class ProviderTransport:
    def __init__(self, settings, config, key="", metadata=None, cancelled=None):
        self.settings, self.config, self.key = settings, dict(config), key
        self.provider = config["provider"]
        self.base = base_url(settings, self.provider, config.get("base_url", ""))
        self.metadata, self.cancelled = metadata or {}, cancelled
        self.input_tokens = self.output_tokens = self.cost = None
        self.client_factory = httpx.Client

    def stopped(self):
        if self.cancelled and self.cancelled.is_set():
            raise GenerationCancelled()

    def headers(self):
        if self.provider == "ollama":
            return {}
        if not self.key:
            raise ProviderFailure("not_configured", "Configure a provider credential first.", 409)
        if self.provider == "anthropic":
            return {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        if self.provider == "google":
            return {"x-goog-api-key": self.key}
        return {"Authorization": f"Bearer {self.key}"}

    def request(self, client, method, path, **kwargs):
        self.stopped()
        url, headers, extensions = self.base + path, self.headers(), {}
        if self.provider == "compatible":
            # Pin a freshly validated public address. Re-resolving after validation permits DNS rebinding.
            parsed = urlsplit(url)
            try:
                addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
                if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                    raise ValueError()
                ip = addresses[0][4][0]
                host = f"[{ip}]" if ":" in ip else ip
                netloc = host + (f":{parsed.port}" if parsed.port else "")
                url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
                headers["Host"] = parsed.netloc
                extensions["sni_hostname"] = parsed.hostname
            except (OSError, ValueError):
                raise ProviderFailure(
                    "network_failure", "Custom endpoint must resolve only to public addresses."
                ) from None
        return client.stream(method, url, headers=headers, extensions=extensions, **kwargs)

    def status(self, response):
        if response.is_success:
            return
        status = response.status_code
        code, message = {
            401: ("invalid_credentials", "Authentication failed. Replace the API key and test again."),
            403: ("invalid_credentials", "Provider access was denied. Check the key's permissions."),
            402: (
                "insufficient_quota",
                "Provider quota or credit is exhausted. Check your provider account.",
            ),
            404: ("model_unavailable", "Model or endpoint is unavailable. Check the model identifier."),
            429: (
                "rate_limit_exceeded",
                "Provider rate limit reached. Wait and retry; no fallback was used.",
            ),
        }.get(
            status, ("provider_unavailable", "Provider request failed. Check its status and model settings.")
        )
        if status == 429:
            # Some providers distinguish exhausted credit from a temporary rate limit by code.
            # Inspect only a small body and return fixed messages, never provider text.
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw) > 16384:
                    break
            try:
                data = json.loads(raw) if len(raw) <= 16384 else {}
                error = data.get("error") if isinstance(data, dict) else None
                marker = (error.get("code") or error.get("type")) if isinstance(error, dict) else None
                if marker in {"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"}:
                    code, message = (
                        "insufficient_quota",
                        "Provider quota or credit is exhausted. Check your provider account before retrying.",
                    )
            except (ValueError, TypeError):
                pass
        # Never reflect raw provider messages or bodies, including validation errors.
        raise ProviderFailure(code, message, 429 if status == 429 else 502)

    def json_request(self, path, method="GET", body=None):
        try:
            with self.client_factory(timeout=15, follow_redirects=False, trust_env=False) as client:
                with self.request(
                    client, method, path, **({"json": body} if body is not None else {})
                ) as response:
                    self.status(response)
                    raw = bytearray()
                    for part in response.iter_bytes():
                        raw.extend(part)
                        if len(raw) > 4_000_000:
                            raise ValueError()
            data = json.loads(raw)
            # A broken/malicious endpoint must not reflect a credential into model metadata.
            return (
                json.loads(json.dumps(data).replace(json.dumps(self.key)[1:-1], "[redacted]"))
                if self.key
                else data
            )
        except httpx.TimeoutException:
            raise ProviderFailure(
                "network_failure", "Provider connection timed out. Retry when available.", 504
            ) from None
        except httpx.HTTPError:
            raise ProviderFailure(
                "network_failure", "Cannot reach the provider. Check network and endpoint settings."
            ) from None
        except (ValueError, TypeError, KeyError):
            raise ProviderFailure(
                "provider_unavailable", "Provider returned invalid or oversized metadata."
            ) from None

    def models(self):
        data = self.json_request("/api/tags" if self.provider == "ollama" else "/models")
        if not isinstance(data, dict):
            raise ProviderFailure("provider_unavailable", "Provider returned an unsupported model list.")
        entries = data.get("models", []) if self.provider in {"google", "ollama"} else data.get("data", [])
        if not isinstance(entries, list):
            raise ProviderFailure("provider_unavailable", "Provider returned an unsupported model list.")
        models = []
        for item in entries[:1500]:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id") or item.get("name") or item.get("model")
            if not isinstance(identifier, str) or len(identifier) > 200:
                continue
            if self.provider == "ollama" and (
                item.get("remote_model")
                or item.get("remote_host")
                or identifier.endswith(("-cloud", ":cloud"))
            ):
                continue
            if self.provider in {"openai", "groq"} and identifier.startswith(
                ("text-embedding", "whisper", "tts", "dall-e", "gpt-image", "sora", "omni-moderation")
            ):
                continue
            if self.provider == "google":
                identifier = identifier.removeprefix("models/")
                if "generateContent" not in item.get("supportedGenerationMethods", []):
                    continue
            pricing = item.get("pricing") or {}
            pricing = pricing if isinstance(pricing, dict) else {}
            prompt, completion = nonnegative(pricing.get("prompt")), nonnegative(pricing.get("completion"))
            free = prompt == completion == 0 and nonnegative(pricing.get("request", 0)) == 0
            context = item.get("context_length") or item.get("inputTokenLimit") or item.get("context_window")
            params = item.get("supported_parameters") or []
            params = params if isinstance(params, list) else []
            architecture = item.get("architecture")
            capabilities = architecture.get("output_modalities", []) if isinstance(architecture, dict) else []
            capabilities = (
                [c for c in capabilities if c in {"text", "image", "audio"}]
                if isinstance(capabilities, list) and all(isinstance(c, str) for c in capabilities)
                else []
            )
            top = item.get("top_provider")
            top = top if isinstance(top, dict) else {}
            models.append(
                {
                    "id": identifier,
                    "name": str(item.get("displayName") or item.get("name") or identifier)[:200],
                    "provider": self.provider,
                    "context_window": token_count(context),
                    "max_output_tokens": token_count(
                        item.get("outputTokenLimit") or top.get("max_completion_tokens")
                    ),
                    "supported_parameters": [
                        p
                        for p in params
                        if isinstance(p, str) and p in {"temperature", "max_tokens", "top_p", "reasoning"}
                    ],
                    "capabilities": capabilities or ["Model capabilities not reported"],
                    "pricing": {
                        "input_per_token": prompt,
                        "output_per_token": completion,
                        "currency": "USD",
                        "source": "provider_catalog",
                    }
                    if prompt is not None and completion is not None
                    else None,
                    "cost_status": "free"
                    if free
                    else "paid"
                    if prompt is not None and completion is not None
                    else "unknown",
                }
            )
        return models

    def check(self):
        if self.provider == "openrouter":
            self.json_request("/auth/key")  # /models is public and cannot validate an OpenRouter key.
        models = self.models()
        found = any(m["id"] == self.config["model"] for m in models)
        if self.provider == "ollama" and self.config["model"] != "unselected":
            self.assert_local_model()
        return models, {
            "status": "connected",
            "model_status": "listed" if found else "not_listed",
            "message": (
                "Provider metadata endpoint responded. "
                if self.provider in {"ollama", "compatible"}
                else "Provider authentication succeeded. "
            )
            + (
                "Selected model is listed; inference was not run."
                if found
                else "Choose a model from the catalog."
                if self.config["model"] == "unselected"
                else "Manual model ID is not listed; inference compatibility is unverified."
            ),
            "scope": "metadata_only",
        }

    def assert_local_model(self):
        if self.config["model"].endswith(("-cloud", ":cloud")):
            raise ProviderFailure(
                "privacy_blocked",
                "Ollama cloud models cannot use the Local configuration. Choose an explicitly consented cloud provider.",
                403,
            )
        info = self.json_request("/api/show", method="POST", body={"model": self.config["model"]})
        if not isinstance(info, dict) or info.get("remote_model") or info.get("remote_host"):
            raise ProviderFailure(
                "privacy_blocked",
                "This Ollama model is remote-backed or cannot be verified as local. No document excerpts were sent.",
                403,
            )
        if info.get("capabilities") and "completion" not in info["capabilities"]:
            raise ProviderFailure(
                "model_unavailable", "The selected Ollama model does not advertise text completion."
            )
        return info

    def payload(self, question, evidence, stream):
        c, p = self.config, self.provider
        system = SYSTEM_PROMPT
        content = json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False)
        if c.get("general_chat"):
            system = "Answer the user's question directly. No documents or tools are available. Do not fabricate citations."
            content = question
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        temperature = c.get("temperature")
        if temperature is not None and not temperature_supported(p, c["model"], self.metadata):
            raise ProviderFailure(
                "unsupported_parameter",
                "Temperature is not advertised for this model. Use the provider default.",
                422,
            )
        if p == "anthropic":
            path, body = (
                "/messages",
                {
                    "model": c["model"],
                    "system": system,
                    "messages": messages[1:],
                    "max_tokens": c["max_output_tokens"],
                    "stream": stream,
                },
            )
        elif p == "google":
            path = f"/models/{quote(c['model'], safe='-_.:')}:" + (
                "streamGenerateContent?alt=sse" if stream else "generateContent"
            )
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": content}]}],
                "generationConfig": {"maxOutputTokens": c["max_output_tokens"]},
            }
            if temperature is not None:
                body["generationConfig"]["temperature"] = temperature
        elif p == "ollama":
            path, body = (
                "/api/chat",
                {
                    "model": c["model"],
                    "messages": messages,
                    "stream": stream,
                    "options": {
                        "num_predict": c["max_output_tokens"],
                        "num_ctx": c["context_window"],
                        "num_thread": 2,
                    },
                    "keep_alive": "1m",
                },
            )
            if temperature is not None:
                body["options"]["temperature"] = temperature
        else:
            token_key = (
                c.get("token_parameter", "max_tokens")
                if p == "compatible"
                else "max_tokens"
                if p == "openrouter"
                else "max_completion_tokens"
            )
            path, body = (
                "/chat/completions",
                {
                    "model": c["model"],
                    "messages": messages,
                    token_key: c["max_output_tokens"],
                    "stream": stream,
                },
            )
            if stream and p != "compatible":
                body["stream_options"] = {"include_usage": True}
            if temperature is not None:
                body["temperature"] = temperature
            if p == "openrouter":
                body["provider"] = {"allow_fallbacks": False}
                if not c["allow_paid"]:
                    body["provider"]["max_price"] = {"prompt": 0, "completion": 0}
        return path, body

    def parse(self, data, streaming):
        if not isinstance(data, dict) or data.get("error") or data.get("type") == "error":
            raise ProviderFailure(
                "provider_unavailable", "Provider interrupted the response. No fallback was used."
            )
        p = self.provider
        if p == "anthropic":
            usage = (data.get("message") or {}).get("usage") or data.get("usage") or {}
            text = (
                (data.get("delta") or {}).get("text", "")
                if streaming
                else "".join(v.get("text", "") for v in data.get("content", []) if v.get("type") == "text")
            )
        elif p == "google":
            usage = data.get("usageMetadata") or {}
            parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            text = "".join(v.get("text", "") for v in parts if not v.get("thought"))
        elif p == "ollama":
            usage, text = data, (data.get("message") or {}).get("content", "")
        else:
            usage = data.get("usage") or (data.get("x_groq") or {}).get("usage") or {}
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("delta") if streaming else choice.get("message") or {}) or {}
            text = text.get("content") or ""
        input_key, output_key = {
            "anthropic": ("input_tokens", "output_tokens"),
            "google": ("promptTokenCount", "candidatesTokenCount"),
            "ollama": ("prompt_eval_count", "eval_count"),
        }.get(p, ("prompt_tokens", "completion_tokens"))
        for attribute, key in [("input_tokens", input_key), ("output_tokens", output_key)]:
            count = token_count(usage.get(key))
            if count is not None:
                setattr(self, attribute, count)
        if p == "openrouter" and nonnegative(usage.get("cost")) is not None:
            self.cost = nonnegative(usage["cost"])
        if not isinstance(text, str):
            raise ValueError()
        return text

    def generate(self, question, evidence, on_delta=None):
        if self.provider == "ollama":
            self.assert_local_model()
        stream = bool(self.config["streaming"])
        path, body = self.payload(question, evidence, stream)
        answer, pending = "", ""
        deadline = time.monotonic() + self.config["timeout_seconds"]

        def lines(response):
            buffer, consumed = b"", 0
            for part in response.iter_bytes():
                self.stopped()
                if time.monotonic() > deadline:
                    raise ProviderFailure(
                        "network_failure",
                        "Provider response deadline exceeded. Partial usage may have occurred.",
                        504,
                    )
                consumed += len(part)
                buffer += part
                if consumed > 1_000_000:
                    raise ValueError()
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > 256_000:
                        raise ValueError()
                    yield line.rstrip(b"\r").decode("utf-8")
                if len(buffer) > 256_000:
                    raise ValueError()
            if buffer:
                yield buffer.decode("utf-8")

        def emit(text, final=False):
            nonlocal pending, answer
            pending += text
            if self.key:
                pending = pending.replace(self.key, "[redacted]")
            # Retain a suffix so a credential split over provider deltas cannot leak.
            keep = 0 if final else max(0, len(self.key) - 1)
            safe = pending[:-keep] if keep else pending
            pending = pending[-keep:] if keep else ""
            if len(pending) < keep:
                safe = ""
            answer += safe
            if len(answer) + len(pending) > 20000:
                raise ValueError()
            if safe and on_delta:
                on_delta(safe)

        try:
            with self.client_factory(
                timeout=self.config["timeout_seconds"], follow_redirects=False, trust_env=False
            ) as client:
                with self.request(client, "POST", path, json=body) as response:
                    self.status(response)
                    if stream:
                        finished = False
                        for line in lines(response):
                            self.stopped()
                            if self.provider != "ollama":
                                if not line.startswith("data:"):
                                    continue
                                line = line[5:].strip()
                                if line == "[DONE]":
                                    finished = True
                                    break
                            if line:
                                data = json.loads(line)
                                emit(self.parse(data, True))
                                if self.provider == "ollama":
                                    finished = finished or data.get("done") is True
                                elif self.provider == "anthropic":
                                    finished = (
                                        finished
                                        or data.get("type") == "message_stop"
                                        or bool((data.get("delta") or {}).get("stop_reason"))
                                    )
                                elif self.provider == "google":
                                    finished = finished or any(
                                        c.get("finishReason") for c in data.get("candidates", [])
                                    )
                                else:
                                    finished = finished or any(
                                        c.get("finish_reason") for c in data.get("choices", [])
                                    )
                        if not finished:
                            raise ProviderFailure(
                                "network_failure",
                                "Provider stream ended before completion. No verified answer was saved.",
                            )
                    else:
                        raw = bytearray()
                        for part in response.iter_bytes():
                            self.stopped()
                            raw.extend(part)
                            if len(raw) > 256_000:
                                raise ValueError()
                        emit(self.parse(json.loads(raw), False))
            self.stopped()
            emit("", True)
            if not answer.strip():
                raise ValueError()
            return answer
        except httpx.TimeoutException:
            raise ProviderFailure(
                "network_failure",
                "Provider timed out. Partial usage may have occurred; no retry was used.",
                504,
            ) from None
        except httpx.HTTPError:
            raise ProviderFailure(
                "network_failure", "Provider connection failed. No fallback was used."
            ) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise ProviderFailure(
                "provider_unavailable", "Provider returned an invalid, empty or oversized answer."
            ) from None
