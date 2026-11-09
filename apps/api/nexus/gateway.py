"""Workspace model routing, explicit destination consent and bounded no-fallback calls."""

import ipaddress
import json
import socket
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from .database import ModelRegistry, RoutePolicy, UsageEvent
from .providers import SYSTEM_PROMPT, MockGenerationProvider, ProviderError, generation_provider

ProviderID = Literal["mock", "groq", "openai", "anthropic", "google", "compatible", "ollama"]
ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}


class GenerationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderID = "mock"
    model: str = Field("extractive-demo", min_length=1, max_length=150, pattern=r"^[\w.:-]+(?:/[\w.:-]+)*$")
    preset: Literal["free-cpu", "local-optional", "cloud-optional"] = "free-cpu"
    consent_destination: str = Field("", max_length=500)
    allow_paid: bool = False
    free_tier_confirmed: bool = False
    max_calls_per_day: int = Field(20, ge=0, le=10000)
    max_output_tokens: int = Field(1000, ge=64, le=4096)
    timeout_seconds: int = Field(45, ge=1, le=120)
    # No automatic retries: a timed-out generation may already have incurred usage.
    retries: Literal[0] = 0


def destination(settings, provider):
    if provider == "mock":
        return "local:extractive-demo"
    if provider == "ollama":
        base = settings.ollama_base_url.rstrip("/")
        url = urlsplit(base)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "::1"}
            or url.path
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ProviderError(
                "Ollama must use a literal loopback HTTP origin; no model is downloaded automatically."
            )
        return base
    if provider == "compatible":
        base = settings.compatible_base_url.rstrip("/")
        url = urlsplit(base)
        origin = f"{url.scheme}://{url.netloc}"
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/v1"}
            or origin not in settings.provider_allowed_origins
        ):
            raise ProviderError(
                "Custom provider requires an explicitly allowlisted HTTPS origin with an optional /v1 path."
            )
        try:
            addresses = socket.getaddrinfo(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                raise ValueError()
        except (OSError, ValueError) as error:
            raise ProviderError("Custom provider DNS must resolve only to public addresses.") from error
        return base
    return ENDPOINTS[provider]


def is_remote(provider):
    return provider not in {"mock", "ollama"}


class RemoteAdapter:
    def __init__(self, settings, policy):
        self.settings, self.policy, self.name = settings, policy, policy.provider
        self.usage = None

    def generate(self, question, evidence):
        policy, provider = self.policy, self.name
        if provider == "ollama":
            from .provider_transport import ProviderTransport

            ProviderTransport(
                self.settings, {"provider": "ollama", "model": policy.model}
            ).assert_local_model()
        base = destination(self.settings, provider)
        headers = {}
        if provider != "ollama":
            key_name = {
                "compatible": "compatible_api_key",
                "google": "google_api_key",
                "anthropic": "anthropic_api_key",
                "openai": "openai_api_key",
                "groq": "groq_api_key",
            }[provider]
            key = getattr(self.settings, key_name).get_secret_value()
            if not key:
                raise ProviderError(f"{provider} server credential is missing. See the provider guide.")
            headers = {"Authorization": f"Bearer {key}"}
        content = json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
        if provider == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            endpoint, body = (
                base + "/messages",
                {
                    "model": policy.model,
                    "system": SYSTEM_PROMPT,
                    "messages": messages[1:],
                    "max_tokens": policy.max_output_tokens,
                    "stream": False,
                },
            )
        elif provider == "google":
            headers = {"x-goog-api-key": key}
            endpoint = base + f"/models/{policy.model}:generateContent"
            body = {
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": content}]}],
                "generationConfig": {"maxOutputTokens": policy.max_output_tokens},
            }
        elif provider == "ollama":
            endpoint, body = (
                base + "/api/chat",
                {
                    "model": policy.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_predict": policy.max_output_tokens, "num_ctx": 8192, "num_thread": 2},
                    "keep_alive": "1m",
                },
            )
        else:
            endpoint = base + "/chat/completions"
            budget_key = "max_tokens" if provider == "compatible" else "max_completion_tokens"
            body = {
                "model": policy.model,
                "messages": messages,
                budget_key: policy.max_output_tokens,
                "stream": False,
            }
        try:
            with httpx.Client(
                timeout=policy.timeout_seconds, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream("POST", endpoint, headers=headers, json=body) as response:
                    if response.status_code == 429:
                        raise ProviderError(
                            "Provider quota/rate limit reached. No retry or fallback was used.", 429
                        )
                    if not response.is_success:
                        raise ProviderError(
                            f"Provider returned HTTP {response.status_code}. Check credentials/model; no fallback was used."
                        )
                    raw = bytearray()
                    for part in response.iter_bytes():
                        raw.extend(part)
                        if len(raw) > 256_000:
                            raise ProviderError("Provider response exceeds the bounded answer limit.")
            data = json.loads(raw)
            if provider == "anthropic":
                answer = "".join(p["text"] for p in data["content"] if p["type"] == "text")
                usage = data.get("usage", {})
                self.usage = (usage.get("input_tokens"), usage.get("output_tokens"))
            elif provider == "google":
                answer = "".join(
                    p["text"] for p in data["candidates"][0]["content"]["parts"] if not p.get("thought")
                )
                usage = data.get("usageMetadata", {})
                self.usage = (usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
            elif provider == "ollama":
                answer = data["message"]["content"]
                self.usage = (data.get("prompt_eval_count"), data.get("eval_count"))
            else:
                answer = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                self.usage = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 20000:
                raise ValueError()
            return answer
        except httpx.TimeoutException as error:
            raise ProviderError(
                "Provider timed out. Usage may have occurred; no automatic retry was used.", 504
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError("Provider connection failed. No fallback was used.") from error
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderError("Provider returned an unsupported or invalid response.", 502) from error


class WorkspaceGenerator:
    def __init__(self, gateway, workspace_id, policy, legacy=None):
        self.gateway, self.workspace_id, self.policy, self.legacy = gateway, workspace_id, policy, legacy
        self.name = legacy.name if legacy else policy.provider

    def generate(self, question, evidence):
        return self.gateway.invoke(self.workspace_id, self.policy, question, evidence, self.legacy)


class ModelGateway:
    def __init__(self, service):
        self.service = service

    def seed_registry(self):
        with self.service.sessions.begin() as session:
            if self.service.postgres:
                from sqlalchemy import text

                session.execute(text("SELECT pg_advisory_xact_lock(834102, 3)"))
            for provider in GenerationPolicy.model_fields["provider"].annotation.__args__:
                session.merge(
                    ModelRegistry(
                        id=f"generation:{provider}",
                        configuration={
                            "provider": provider,
                            "kind": "generation",
                            "manual_model_id": True,
                            "privacy": "remote" if is_remote(provider) else "local",
                            "implemented": True,
                            "capabilities": {
                                "streaming": False,
                                "tools": False,
                                "structured_output": False,
                                "context_limit": None,
                            },
                            "schema": GenerationPolicy.model_json_schema(),
                        },
                    )
                )
            for kind, providers in {
                "embedding": ["onnx", "hash", "sentence-transformers"],
                "reranking": ["none", "cross-encoder"],
                "vector": ["postgresql" if self.service.postgres else "chroma"],
            }.items():
                for provider in providers:
                    session.merge(
                        ModelRegistry(
                            id=f"{kind}:{provider}",
                            configuration={
                                "provider": provider,
                                "kind": kind,
                                "privacy": "local",
                                "implemented": True,
                                "optional": provider in {"sentence-transformers", "cross-encoder"},
                            },
                        )
                    )

    def policy(self, session, workspace_id):
        row = session.get(RoutePolicy, workspace_id)
        return GenerationPolicy.model_validate(row.configuration) if row else None

    def generator(self, session, workspace_id):
        from .auth import principal

        workspace = self.service.repo.workspace(session, workspace_id)
        personal = self.service.byok.generator(session, workspace_id)
        if personal is not None:
            return personal
        if principal.get() and principal.get().guest:
            raise HTTPException(409, "Select an LLM to start chatting.")
        policy = self.policy(session, workspace_id)
        if policy is None:
            legacy = generation_provider(self.service.settings)
            if legacy.name != "mock" and not workspace.cloud_opt_in:
                raise HTTPException(
                    403, "Opt in to sending retrieved document excerpts to the cloud in Settings first."
                )
            policy = GenerationPolicy(
                provider=legacy.name,
                model=self.service.settings.generation_model,
                free_tier_confirmed=self.service.settings.free_tier_confirmed,
            )
            return WorkspaceGenerator(self, workspace_id, policy, legacy)
        return WorkspaceGenerator(self, workspace_id, policy)

    def validate_permission(self, session, workspace_id, policy):
        workspace = self.service.repo.workspace(session, workspace_id)
        if policy.provider == "mock":
            return
        expected_preset = (
            "free-cpu"
            if policy.provider == "groq"
            else "local-optional"
            if policy.provider == "ollama"
            else "cloud-optional"
        )
        if policy.preset != expected_preset:
            raise HTTPException(403, f"Select the {expected_preset} resource preset for this provider.")
        target = destination(self.service.settings, policy.provider)
        if is_remote(policy.provider):
            if not workspace.cloud_opt_in or policy.consent_destination != f"{policy.provider}|{target}":
                raise HTTPException(
                    403,
                    "Explicit workspace consent for this provider/destination is required before transmitting excerpts.",
                )
            if policy.provider == "groq" and not policy.free_tier_confirmed:
                raise HTTPException(403, "Confirm free-tier account/model eligibility first.")
            if policy.provider not in {"groq"} and not policy.allow_paid:
                raise HTTPException(
                    403,
                    "This optional provider requires explicit paid-usage permission; no free eligibility is assumed.",
                )
            if (
                policy.provider != "groq"
                and policy.provider not in self.service.settings.paid_provider_allowlist
            ):
                raise HTTPException(
                    403,
                    "This optional provider is disabled by the server operator's paid-provider allowlist.",
                )
        elif policy.preset != "local-optional":
            raise HTTPException(403, "Explicitly select Local Optional to use your installed Ollama model.")

    def invoke(self, workspace_id, policy, question, evidence, legacy=None):
        svc = self.service
        with svc.lock, svc.sessions.begin() as session:
            if legacy is None:
                self.validate_permission(session, workspace_id, policy)
            else:
                workspace = svc.repo.workspace(session, workspace_id)
                if legacy.name != "mock" and not workspace.cloud_opt_in:
                    raise HTTPException(403, "Cloud consent was revoked.")
            if policy.provider != "mock":
                day = datetime.now(timezone.utc).date().isoformat()
                count = session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(
                        UsageEvent.workspace_id == workspace_id,
                        UsageEvent.provider != "mock",
                        UsageEvent.created_at >= day,
                    )
                )
                persisted = self.policy(session, workspace_id)
                ceiling = min(policy.max_calls_per_day, persisted.max_calls_per_day if persisted else 20)
                if count >= ceiling:
                    raise HTTPException(429, "Workspace daily call budget reached. No provider was called.")
            event = UsageEvent(
                workspace_id=workspace_id,
                provider=policy.provider,
                model=policy.model,
                status="reserved",
                input_tokens=max(
                    1, len(json.dumps({"question": question, "evidence": evidence}).encode()) // 4
                ),
            )
            session.add(event)
            session.flush()
            event_id = event.id
        adapter = legacy or (
            MockGenerationProvider() if policy.provider == "mock" else RemoteAdapter(svc.settings, policy)
        )
        started = time.perf_counter()
        answer, status = "", "failed"
        try:
            answer = adapter.generate(question, evidence)
            status = "ok"
            return answer
        except ProviderError as error:
            status = f"http_{error.status}"
            raise
        finally:
            with svc.sessions.begin() as session:
                stored = session.get(UsageEvent, event_id)
                stored.status, stored.elapsed_ms = status, int((time.perf_counter() - started) * 1000)
                usage = getattr(adapter, "usage", None)
                if usage and all(isinstance(v, int) and 0 <= v <= 10_000_000 for v in usage):
                    stored.input_tokens, stored.output_tokens = usage
                    stored.token_source = "provider_reported"
                else:
                    stored.output_tokens = len(answer.encode()) // 4
