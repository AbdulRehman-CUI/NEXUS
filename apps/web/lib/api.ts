export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
let csrf: string | null = null;
export function setCsrf(value: string | null) {
  csrf = value;
}

export type Workspace = { id: string; name: string; cloud_opt_in: boolean };
export type Chat = { id: string; title: string };
export type Document = {
  id: string;
  title: string;
  status: string;
  needs_reindex?: boolean;
  error: string | null;
  size: number;
  extension: string;
  created_at: string;
};
export type Citation = {
  citation_id: string;
  document_id: string;
  document_version_id: string;
  chunk_id: string;
  title: string;
  page: number | null;
  heading: string | null;
  excerpt: string;
  source_url: string;
  start: number;
  end: number;
  note_id?: string | null;
  path?: string | null;
  available?: boolean;
  unavailable_reason?: string;
};
export type Message = {
  id: string;
  role: string;
  content: string;
  provider: string | null;
  citations: Citation[];
  diagnostics?: RetrievalDiagnostics | null;
};

export type RetrievalSettings = {
  mode: "semantic" | "keyword" | "hybrid";
  candidate_count: number;
  top_k: number;
  rrf_constant: number;
  lexical_weight: number;
  semantic_weight: number;
  title_weight: number;
  context_budget: number;
  max_per_document: number;
  rewrite: boolean;
  multi_query: boolean;
  max_variants: number;
  reranker: "none" | "cross-encoder";
  reranker_model: string;
};
export type RetrievalDiagnostics = {
  mode: string;
  embedding_provider: string;
  embedding_model: string;
  index_id: string;
  standalone_query: string;
  variants: string[];
  additional_cloud_calls: number;
  authorized_documents: number;
  candidate_count: number;
  excerpt_bytes: number;
  elapsed_ms: number;
  warnings: string[];
  stages: Record<string, unknown[]>;
  final: unknown[];
};
export type SearchFilters = {
  vault_id?: string;
  document_ids?: string[];
  tags?: string[];
  path_prefix?: string;
  types?: string[];
};
export type Vault = {
  id: string;
  workspace_id: string;
  name: string;
  source_kind: "snapshot" | "agent";
  status: string;
  last_scan: string | null;
  scan_requested_at: string | null;
  error: string | null;
  note_count: number;
  unresolved_count: number;
};
export type VaultNote = {
  id: string;
  vault_id: string;
  path: string;
  document_id: string | null;
  status: string;
  tags: string[];
  source_url: string | null;
};
export type NoteLink = {
  id: string;
  source_id: string;
  target_id: string | null;
  target: string;
  label: string;
  kind: string;
  anchor: string | null;
  status: string;
  candidates: string[];
};
export type SyncStatus = {
  vault: Vault;
  run: {
    id: string;
    status: string;
    cursor: number;
    manifest: unknown[];
    counts: Record<string, number>;
    attempts: number;
    error: string | null;
  } | null;
};
export type GraphNode = {
  id: string;
  label: string;
  type: "note" | "tag";
  source_url: string | null;
  status?: string;
};
export type GraphData = {
  nodes: GraphNode[];
  edges: {
    id: string;
    source: string;
    target: string;
    type: string;
    provenance: string;
  }[];
  total_notes: number;
  shown_notes: number;
  truncated: boolean;
};
export type IndexConfig = {
  embedding_provider: "hash" | "onnx" | "sentence-transformers";
  embedding_model: string;
  embedding_revision: string;
  embedding_dimension: number;
  embedding_onnx_file: string;
  normalization: "l2";
  preprocessing: "normalized-v1";
  chunk_size: number;
  chunk_overlap: number;
};
export type IndexVersion = {
  id: string;
  namespace: string;
  fingerprint: string;
  configuration: IndexConfig;
  status: string;
  active: boolean;
  progress: number;
  total: number;
  attempts: number;
  error: string | null;
};
export type PublicSettings = {
  generation_provider: "mock" | "groq";
  generation_model: string;
  free_tier_confirmed: boolean;
  groq_key_configured: boolean;
  embedding_provider: string;
  embedding_model: string;
  max_upload_mb: number;
  disclosure: string;
  security: string;
};
export type Source = {
  document: Document;
  spans: {
    id: string;
    text: string;
    page: number | null;
    heading: string | null;
  }[];
  file_url: string;
  citation: Citation | null;
};

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    if (
      response.status === 401 &&
      !path.startsWith("/api/auth/") &&
      typeof window !== "undefined"
    )
      window.dispatchEvent(new Event("nexus-auth-required"));
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `Request failed (${response.status}). Please check your input and try again.`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export async function streamAnswer(
  path: string,
  body: unknown,
  signal: AbortSignal,
  onProvisional: (text: string) => void,
): Promise<Message> {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    signal,
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("nexus-auth-required"));
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : `Response failed (${response.status}).`,
    );
  }
  if (!response.body)
    throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    provisional = "",
    complete: Message | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    while (!complete) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(
        /\r\n/g,
        "\n",
      );
      if (buffer.length > 2_000_000)
        throw new Error("Response event exceeds the safe display limit.");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const event = block
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!raw) continue;
        const data = JSON.parse(raw);
        if (event === "error")
          throw new Error(
            typeof data.detail === "string"
              ? data.detail
              : "The response could not be verified.",
          );
        if (event === "delta" && typeof data.text === "string") {
          provisional += data.text;
          if (provisional.length > 20000)
            throw new Error("Response exceeds the safe display limit.");
          if (!timer)
            timer = setTimeout(() => {
              timer = undefined;
              onProvisional(provisional);
            }, 50);
        }
        if (
          event === "complete" &&
          typeof data.content === "string" &&
          typeof data.id === "string" &&
          Array.isArray(data.citations)
        )
          complete = data;
      }
    }
    if (!complete)
      throw new Error(
        "Connection ended before a verified answer arrived. Check conversation history before retrying.",
      );
    return complete;
  } finally {
    if (timer) clearTimeout(timer);
    await reader.cancel().catch(() => {});
  }
}

export function uploadFile(
  workspaceId: string,
  file: File,
  onProgress: (percent: number) => void,
): Promise<{ duplicate: boolean }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/api/workspaces/${workspaceId}/documents`);
    xhr.withCredentials = true;
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error("The server returned an unreadable upload response."));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else
        reject(
          new Error(
            typeof body.detail === "string"
              ? body.detail
              : `Upload failed (${xhr.status}).`,
          ),
        );
    };
    xhr.onerror = () =>
      reject(
        new Error("Cannot reach the API. Start the local server and retry."),
      );
    xhr.timeout = 120000;
    xhr.ontimeout = () =>
      reject(new Error("Upload timed out. Try a smaller file."));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
