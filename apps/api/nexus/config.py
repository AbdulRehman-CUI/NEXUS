from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    profile: Literal["local", "server"] = "local"
    database_url: SecretStr = SecretStr("")
    guest_access: bool = False
    guest_session_secret: SecretStr = SecretStr("")
    guest_session_hours: int = Field(168, ge=1, le=720)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    secure_cookies: bool = True
    session_hours: int = Field(12, ge=1, le=168)
    rate_limit_per_minute: int = Field(120, ge=5, le=10000)
    login_limit_per_minute: int = Field(5, ge=1, le=30)
    telemetry_retention_days: int = Field(7, ge=1, le=90)
    extraction_timeout_seconds: int = Field(45, ge=1, le=300)
    isolated_extraction: bool = True
    ocr_enabled: bool = False
    ocr_max_pages: int = Field(20, ge=1, le=100)
    provider_allowed_origins: list[str] = []
    paid_provider_allowlist: list[Literal["openai", "anthropic", "google", "compatible"]] = []
    compatible_base_url: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    google_api_key: SecretStr = SecretStr("")
    compatible_api_key: SecretStr = SecretStr("")
    byok_master_key: SecretStr = SecretStr("")
    byok_master_key_file: Path | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    generation_provider: Literal["mock", "groq"] = "mock"
    generation_model: str = Field(
        "llama-3.1-8b-instant", min_length=1, max_length=150, pattern=r"^[\w./:-]+$"
    )
    groq_api_key: SecretStr = SecretStr("")
    free_tier_confirmed: bool = False
    embedding_provider: Literal["onnx", "sentence-transformers", "hash"] = "onnx"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    embedding_dimension: int = Field(384, ge=8, le=4096)
    embedding_onnx_file: str = "onnx/model_quint8_avx2.onnx"
    model_cache_dir: Path | None = None
    reranker_allow_download: bool = False
    max_vault_files: int = Field(2000, ge=1, le=10000)
    max_note_bytes: int = Field(2_000_000, ge=1000, le=10_000_000)
    max_vault_bytes: int = Field(20_000_000, ge=1000, le=100_000_000)
    max_zip_ratio: int = Field(100, ge=1, le=500)
    vault_excludes: list[str] = ["*.tmp", "~*", ".DS_Store"]
    chunk_size: int = Field(700, ge=100, le=2000)
    chunk_overlap: int = Field(100, ge=0)
    context_budget: int = Field(4000, ge=200, le=32000)
    max_retrieval_results: int = Field(5, ge=1, le=20)
    max_upload_mb: int = Field(20, ge=1, le=100)
    max_source_characters: int = Field(2_000_000, ge=1000, le=10_000_000)
    max_pdf_pages: int = Field(1000, ge=1, le=3000)
    max_queued_jobs: int = Field(50, ge=1, le=500)
    max_distance: float = Field(0.85, ge=0, le=2)
    worker_enabled: bool = True

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.database_url.get_secret_value() and self.profile != "server":
            raise ValueError("PostgreSQL requires the server profile.")
        if self.guest_access and (
            self.profile != "server"
            or not self.secure_cookies
            or len(self.guest_session_secret.get_secret_value()) < 32
        ):
            raise ValueError(
                "Guest access requires the server profile, Secure cookies and a guest session secret of at least 32 characters."
            )
        if self.profile == "local" and any(
            host not in {"localhost", "127.0.0.1", "testserver", "[::1]"} for host in self.allowed_hosts
        ):
            raise ValueError(
                "Local profile only permits loopback hosts. Use authenticated server mode for other hosts."
            )
        if "*" in self.cors_origins or any("*" in h for h in self.allowed_hosts):
            raise ValueError("Use explicit CORS origins and hosts, without wildcards.")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self
