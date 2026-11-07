"""Private BYOK ownership, authenticated encryption and gateway integration."""

import base64
import json
import os
import time
from datetime import datetime, timezone
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import func, select

from .auth import principal
from .database import ProviderConfiguration, ProviderSelection, ProviderUsage, now, uid
from .gateway import is_remote
from .provider_transport import (
    GenerationCancelled,
    ProviderFailure,
    ProviderTransport,
    base_url,
    temperature_supported,
)
from .providers import SYSTEM_PROMPT


def owner_id(settings):
    if settings.profile == "local":
        return "local-single-user"
    actor = principal.get()
    if not actor:
        raise HTTPException(401, "Sign in to continue.")
    return "user:" + actor.id


class ConfigurationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    provider: Literal["openrouter", "google", "openai", "anthropic", "groq", "ollama", "compatible"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[\w.:-]+(?:/[\w.:-]+)*$")
    base_url: str = Field("", max_length=500)
    api_key: SecretStr | None = Field(None, repr=False)
    remote_consent: bool = False
    allow_paid: bool = False
    streaming: bool = True
    temperature: float | None = Field(None, ge=0, le=2)
    max_output_tokens: int = Field(1000, ge=64, le=32768)
    context_window: int = Field(8192, ge=2048, le=2_000_000)
    context_budget_bytes: int = Field(4000, ge=200, le=32000)
    max_calls_per_day: int = Field(20, ge=0, le=10000)
    spending_warning_usd: float | None = Field(None, ge=0, le=1_000_000)
    timeout_seconds: int = Field(45, ge=1, le=120)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"

    @field_validator("api_key")
    @classmethod
    def safe_key(cls, value):
        if value is not None:
            secret = value.get_secret_value()
            if not 8 <= len(secret) <= 4096 or any(not 33 <= ord(c) <= 126 for c in secret):
                raise ValueError(
                    "Use a credential of 8–4096 printable characters, without spaces or line breaks."
                )
        return value

    @model_validator(mode="after")
    def limits(self):
        if self.provider == "google":
            self.model = self.model.removeprefix("models/")
        if self.max_output_tokens + 1024 >= self.context_window:
            raise ValueError("Reserve context space for instructions, question and evidence.")
        if any(part in {".", ".."} for part in self.model.split("/")):
            raise ValueError("Invalid model identifier.")
        if self.provider != "compatible" and self.base_url:
            raise ValueError("Only custom providers accept an endpoint URL.")
        if self.provider == "ollama" and self.api_key is not None:
            raise ValueError("Local Ollama does not accept a cloud credential.")
        if self.provider == "ollama" and self.model.endswith(("-cloud", ":cloud")):
            raise ValueError("Ollama cloud models require an explicitly configured cloud provider.")
        return self


class CredentialVault:
    def __init__(self, settings):
        self.cipher = None
        try:
            raw = settings.byok_master_key.get_secret_value()
            if settings.byok_master_key_file:
                if raw:
                    raise ValueError()
                path = settings.byok_master_key_file.resolve()
                if path.is_relative_to(settings.data_dir.resolve()) or path.stat().st_size > 1024:
                    raise ValueError()
                if os.name != "nt" and path.stat().st_mode & 0o077:
                    raise ValueError()
                raw = path.read_text("ascii").strip()
            key = base64.b64decode(raw, validate=True)
            if len(key) != 32:
                raise ValueError()
            self.cipher = AESGCM(key)
        except (OSError, ValueError, UnicodeError):
            # Failure is closed for persistent credentials, not for the free local application.
            pass

    @property
    def enabled(self):
        return self.cipher is not None

    @staticmethod
    def aad(row):
        c = row.configuration
        return json.dumps(["nexus-byok-v1", row.owner, row.id, c["provider"], c["destination"]]).encode()

    def require(self):
        if not self.cipher:
            raise HTTPException(
                503,
                "Encrypted credential storage is disabled. Ask the operator to configure a valid BYOK master key outside the data directory.",
            )

    def encrypt(self, row, secret):
        self.require()
        nonce = os.urandom(12)
        return (
            "v1."
            + base64.b64encode(nonce + self.cipher.encrypt(nonce, secret.encode(), self.aad(row))).decode()
        )

    def decrypt(self, row):
        self.require()
        try:
            if not row.encrypted_key or not row.encrypted_key.startswith("v1."):
                raise ValueError()
            raw = base64.b64decode(row.encrypted_key[3:], validate=True)
            return self.cipher.decrypt(raw[:12], raw[12:], self.aad(row)).decode()
        except (InvalidTag, ValueError, UnicodeError):
            raise HTTPException(
                503,
                "The saved credential cannot be decrypted. Restore the correct master key or replace this credential.",
            ) from None


class ByokStore:
    def __init__(self, service):
        self.service = service
        self.vault = CredentialVault(service.settings)

    def get(self, session, identifier, owner=None):
        row = session.get(ProviderConfiguration, identifier)
        if row is None or row.deleted or row.owner != (owner or owner_id(self.service.settings)):
            raise HTTPException(404, "Provider configuration not found.")
        return row

    def public(self, row):
        c = row.configuration
        metadata = next((m for m in row.models if m["id"] == c["model"]), None)
        return {
            "id": row.id,
            **c,
            "is_default": row.is_default,
            "credential_configured": bool(row.encrypted_key),
            "connection": row.connection,
            "updated_at": row.updated_at,
            "temperature_supported": temperature_supported(c["provider"], c["model"], metadata),
            "model_metadata": metadata,
        }

    def save(self, body, identifier=None):
        svc, owner = self.service, owner_id(self.service.settings)
        destination = base_url(svc.settings, body.provider, body.base_url)
        c = body.model_dump(exclude={"api_key"})
        c.update(destination=destination, base_url=destination if body.provider == "compatible" else "")
        with svc.lock, svc.sessions.begin() as session:
            if identifier:
                row = self.get(session, identifier, owner)
                if (
                    row.configuration["provider"] != body.provider
                    or row.configuration["destination"] != destination
                ):
                    raise HTTPException(
                        409,
                        "Create a separate configuration to change provider or endpoint. A saved key is never moved to another destination.",
                    )
            else:
                count = session.scalar(
                    select(func.count())
                    .select_from(ProviderConfiguration)
                    .where(ProviderConfiguration.owner == owner, ProviderConfiguration.deleted.is_(False))
                )
                if count >= 20:
                    raise HTTPException(409, "At most 20 provider configurations are supported per account.")
                row = ProviderConfiguration(id=uid(), owner=owner, configuration=c)
                session.add(row)
            row.configuration, row.updated_at, row.revision = c, now(), uid()
            if body.api_key is not None:
                row.encrypted_key = self.vault.encrypt(row, body.api_key.get_secret_value())
                row.models = []
            metadata = next((m for m in (row.models or []) if m["id"] == body.model), None)
            if body.temperature is not None and not temperature_supported(
                body.provider, body.model, metadata
            ):
                raise HTTPException(
                    422, "Temperature is not advertised for this model. Leave it on provider default."
                )
            row.connection = {
                "status": "not_tested",
                "message": "Saved. Test the connection; inference has not been verified.",
            }
            session.flush()
            return self.public(row)

    def resolve(self, session, workspace_id, allow_removed=False):
        if self.service.settings.profile == "server" and principal.get() is None:
            return None
        owner = owner_id(self.service.settings)
        selected = session.get(ProviderSelection, (owner, workspace_id))
        if selected:
            row = (
                session.get(ProviderConfiguration, selected.configuration_id)
                if selected.configuration_id
                else None
            )
        else:
            row = session.scalar(
                select(ProviderConfiguration).where(
                    ProviderConfiguration.owner == owner, ProviderConfiguration.is_default.is_(True)
                )
            )
        if row and row.owner != owner:
            raise HTTPException(404, "Provider configuration not found.")
        if row and row.deleted:
            if allow_removed:
                return row
            raise HTTPException(
                409,
                "The selected configuration was removed. Choose a model explicitly; no fallback was used.",
            )
        return row

    def validate(self, session, workspace_id, row):
        svc, c = self.service, row.configuration
        workspace = svc.repo.workspace(session, workspace_id)
        target = base_url(svc.settings, c["provider"], c.get("base_url", ""))
        if target != c["destination"]:
            raise HTTPException(
                409, "Provider destination changed. Review and save a new configuration before use."
            )
        if is_remote(c["provider"]):
            if not row.encrypted_key:
                raise HTTPException(
                    409, "Configure a credential for the selected model. No fallback was used."
                )
            self.vault.require()
            if not c["remote_consent"] or not workspace.cloud_opt_in:
                raise HTTPException(
                    403,
                    "Both personal provider consent and workspace cloud permission are required before sending excerpts remotely.",
                )
            metadata = next((m for m in row.models if m["id"] == c["model"]), {})
            if metadata.get("cost_status") != "free" and not c["allow_paid"]:
                raise HTTPException(
                    403,
                    "This model has paid or unknown pricing. Explicitly acknowledge provider billing/quota terms before inference.",
                )

    def generator(self, session, workspace_id):
        row = self.resolve(session, workspace_id)
        if row is None:
            return None
        self.validate(session, workspace_id, row)
        return PersonalGenerator(self, workspace_id, row)

    def transport(self, row, cancelled=None):
        key = self.vault.decrypt(row) if is_remote(row.configuration["provider"]) else ""
        metadata = next((m for m in row.models if m["id"] == row.configuration["model"]), None)
        return ProviderTransport(self.service.settings, row.configuration, key, metadata, cancelled)


class PersonalGenerator:
    def __init__(self, store, workspace_id, row):
        self.store, self.workspace_id = store, workspace_id
        self.identifier, self.owner, self.revision = row.id, row.owner, row.revision
        self.config, self.name = dict(row.configuration), row.configuration["provider"]
        self.metadata = next((m for m in row.models if m["id"] == self.config["model"]), {})
        self.on_delta = self.cancelled = None

    def context_limit(self, question):
        window = min(self.config["context_window"], self.metadata.get("context_window") or 2_000_000)
        if self.config["max_output_tokens"] > (self.metadata.get("max_output_tokens") or 32768):
            raise HTTPException(422, "Output limit exceeds this model's advertised maximum.")
        # Conservative byte budget; never pretend a universal character/token ratio is exact.
        overhead = len(SYSTEM_PROMPT.encode()) + len(question.encode()) + 1500
        available = min(
            self.config["context_budget_bytes"], window - self.config["max_output_tokens"] - overhead
        )
        if available < 200:
            raise HTTPException(
                422, "The model context window is too small for this question and output limit."
            )
        return available

    def generate(self, question, evidence):
        svc, store = self.store.service, self.store
        with svc.lock, svc.sessions.begin() as session:
            row = store.get(session, self.identifier, self.owner)
            if row.revision != self.revision:
                raise HTTPException(
                    409, "Model settings changed during retrieval. Ask again using the new configuration."
                )
            store.validate(session, self.workspace_id, row)
            day = datetime.now(timezone.utc).date().isoformat()
            calls = session.scalar(
                select(func.count())
                .select_from(ProviderUsage)
                .where(
                    ProviderUsage.owner == self.owner,
                    ProviderUsage.configuration_id == row.id,
                    ProviderUsage.created_at >= day,
                )
            )
            if calls >= self.config["max_calls_per_day"]:
                raise HTTPException(429, "Personal model daily call limit reached. No provider was called.")
            # Check the complete serialized grounded prompt, including generated locator IDs.
            window = min(self.config["context_window"], self.metadata.get("context_window") or 2_000_000)
            prompt_bytes = len(SYSTEM_PROMPT.encode()) + len(
                json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False).encode()
            )
            if prompt_bytes + self.config["max_output_tokens"] + 256 > window:
                raise HTTPException(
                    422,
                    "Grounded prompt exceeds this model's conservative context budget. Reduce retrieval/output limits.",
                )
            event = ProviderUsage(
                owner=self.owner,
                configuration_id=row.id,
                workspace_id=self.workspace_id,
                provider=self.name,
                model=self.config["model"],
                status="reserved",
            )
            session.add(event)
            session.flush()
            event_id = event.id
            adapter = store.transport(row, self.cancelled)
        started, status, answer = time.perf_counter(), "failed", ""
        try:
            answer = adapter.generate(question, evidence, self.on_delta)
            status = "ok"
            return answer
        except GenerationCancelled:
            status = "cancelled"
            raise
        except ProviderFailure as error:
            status = error.code
            raise
        finally:
            with svc.sessions.begin() as session:
                event = session.get(ProviderUsage, event_id)
                event.status, event.elapsed_ms = status, int((time.perf_counter() - started) * 1000)
                event.input_tokens, event.output_tokens = adapter.input_tokens, adapter.output_tokens
                if adapter.cost is not None:
                    event.cost_usd, event.cost_source = adapter.cost, "provider_reported"
                elif (
                    adapter.input_tokens is not None
                    and adapter.output_tokens is not None
                    and self.metadata.get("pricing")
                ):
                    prices = self.metadata["pricing"]
                    event.cost_usd = (
                        adapter.input_tokens * prices["input_per_token"]
                        + adapter.output_tokens * prices["output_per_token"]
                    )
                    event.cost_source = "estimated_model_pricing"
