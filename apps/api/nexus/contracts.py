from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["semantic", "keyword", "hybrid"] = "hybrid"
    candidate_count: int = Field(15, ge=1, le=100)
    top_k: int = Field(5, ge=1, le=20)
    rrf_constant: int = Field(60, ge=1, le=200)
    lexical_weight: float = Field(1, ge=0.1, le=5)
    semantic_weight: float = Field(1, ge=0.1, le=5)
    title_weight: float = Field(2, ge=0, le=5)
    context_budget: int = Field(4000, ge=200, le=32000)
    max_per_document: int = Field(3, ge=1, le=20)
    rewrite: bool = True
    multi_query: bool = False
    max_variants: int = Field(2, ge=1, le=3)
    reranker: Literal["none", "cross-encoder"] = "none"
    reranker_model: str = Field("cross-encoder/ms-marco-MiniLM-L6-v2", max_length=200, pattern=r"^[\w./-]+$")


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    vault_id: str | None = None
    path_prefix: str | None = Field(None, max_length=512)
    tags: list[str] = Field(default_factory=list, max_length=20)
    types: list[Literal[".pdf", ".md", ".txt", ".docx"]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def paths(self):
        if self.path_prefix and any(
            part in {"..", "."} for part in self.path_prefix.replace("\\", "/").split("/")
        ):
            raise ValueError("Path filters must stay inside a vault")
        return self


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000, pattern=r".*\S.*")
    filters: SearchFilters = Field(default_factory=SearchFilters)
    options: RetrievalSettings | None = None
    diagnostics: bool = False


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000, pattern=r".*\S.*")
    filters: SearchFilters = Field(default_factory=SearchFilters)
    options: RetrievalSettings | None = None
    diagnostics: bool = False


class IndexConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embedding_provider: Literal["hash", "onnx", "sentence-transformers"] = "hash"
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", max_length=200, pattern=r"^[\w.-]+/[\w.-]+$"
    )
    embedding_revision: str = Field("1110a243fdf4706b3f48f1d95db1a4f5529b4d41", pattern=r"^[a-fA-F0-9]{40}$")
    embedding_dimension: int = Field(384, ge=8, le=4096)
    embedding_onnx_file: str = Field("onnx/model_quint8_avx2.onnx", pattern=r"^onnx/[\w.-]+\.onnx$")
    normalization: Literal["l2"] = "l2"
    preprocessing: Literal["normalized-v1"] = "normalized-v1"
    chunk_size: int = Field(700, ge=100, le=2000)
    chunk_overlap: int = Field(100, ge=0)

    @model_validator(mode="after")
    def overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("Overlap must be smaller than chunk size")
        return self


class EvidenceResult(BaseModel):
    chunk_id: str
    score: float
    workspace_id: str
    document_id: str
    document_version_id: str
    source_span_id: str
    title: str
    note_id: str | None
    vault_id: str | None
    path: str | None
    tags: list[str]
    page: int | None
    heading: str | None
    start: int
    end: int
    excerpt: str
    source_url: str


class SearchOutput(BaseModel):
    results: list[EvidenceResult]
    diagnostics: dict | None = None


class GraphNodeOutput(BaseModel):
    id: str
    label: str
    type: Literal["note", "tag"]
    status: str | None = None
    source_url: str | None


class GraphEdgeOutput(BaseModel):
    id: str
    source: str
    target: str
    type: Literal["wikilink", "markdown", "embed", "tag"]
    provenance: Literal["authored"]


class GraphOutput(BaseModel):
    nodes: list[GraphNodeOutput]
    edges: list[GraphEdgeOutput]
    total_notes: int
    shown_notes: int
    truncated: bool


class VaultOutput(BaseModel):
    id: str
    workspace_id: str
    name: str
    source_kind: Literal["snapshot", "agent"]
    status: str
    last_scan: str | None
    scan_requested_at: str | None
    error: str | None
    created_at: str
    note_count: int = 0
    unresolved_count: int = 0


class NoteOutput(BaseModel):
    id: str
    workspace_id: str
    vault_id: str
    document_id: str | None
    path: str
    content_hash: str
    status: str
    deleted: bool
    tags: list[str]
    metadata_json: dict
    updated_at: str
    source_url: str | None = None


class NotesOutput(BaseModel):
    notes: list[NoteOutput]
    total: int


class LinkOutput(BaseModel):
    id: str
    workspace_id: str
    vault_id: str
    source_id: str
    target_id: str | None
    target: str
    label: str
    kind: Literal["wikilink", "markdown", "embed"]
    anchor: str | None
    status: Literal["resolved", "unresolved", "ambiguous", "external", "blocked", "missing_anchor"]
    candidates: list[str]


class NoteDetailOutput(BaseModel):
    note: NoteOutput
    outlinks: list[LinkOutput]
    backlinks: list[LinkOutput]


class LinksOutput(BaseModel):
    links: list[LinkOutput]
    total: int


class SyncRunOutput(BaseModel):
    id: str
    workspace_id: str
    vault_id: str
    manifest_hash: str
    manifest: list[dict]
    counts: dict[str, int]
    cursor: int
    status: str
    attempts: int
    error: str | None
    created_at: str


class SyncOutput(BaseModel):
    vault: VaultOutput
    run: SyncRunOutput | None


class IndexOutput(BaseModel):
    id: str
    workspace_id: str
    namespace: str
    fingerprint: str
    configuration: IndexConfiguration
    status: str
    active: bool
    checkpoint: dict
    progress: int
    total: int
    attempts: int
    error: str | None
    created_at: str
