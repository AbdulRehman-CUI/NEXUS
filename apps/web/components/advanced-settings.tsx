"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type IndexConfig,
  type IndexVersion,
  type RetrievalSettings,
} from "../lib/api";
import { Icon } from "./icon";

export function AdvancedSettings({
  workspaceId,
  onError,
}: {
  workspaceId: string;
  onError: (cause: unknown) => void;
}) {
  const [profile, setProfile] = useState<RetrievalSettings | null>(null);
  const [versions, setVersions] = useState<IndexVersion[]>([]);
  const [target, setTarget] = useState<IndexConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useRef(false);
  useEffect(() => {
    pending.current = versions.some((version) =>
      ["building", "validating"].includes(version.status),
    );
  }, [versions]);
  useEffect(() => {
    let cancelled = false;
    if (!workspaceId) return;
    Promise.all([
      api<RetrievalSettings>(
        `/api/workspaces/${workspaceId}/retrieval-settings`,
      ),
      api<IndexVersion[]>(`/api/workspaces/${workspaceId}/index-versions`),
    ])
      .then(([settings, values]) => {
        if (!cancelled) {
          setProfile(settings);
          setVersions(values);
          setTarget(
            (values.find((v) => v.active) || values[0])?.configuration || null,
          );
        }
      })
      .catch(onError);
    const timer = setInterval(async () => {
      if (
        !pending.current ||
        document.hidden ||
        document.getElementById("settings-retrieval")?.hidden
      )
        return;
      try {
        const values = await api<IndexVersion[]>(
          `/api/workspaces/${workspaceId}/index-versions`,
        );
        if (!cancelled) setVersions(values);
      } catch {
        /* foreground actions report failures */
      }
    }, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!profile) return;
    setBusy(true);
    try {
      setProfile(
        await api(`/api/workspaces/${workspaceId}/retrieval-settings`, {
          method: "PATCH",
          body: JSON.stringify(profile),
        }),
      );
      setMessage(
        "Workspace retrieval settings saved. Query reformulation and variants make zero additional cloud calls.",
      );
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function rebuild(event: React.FormEvent) {
    event.preventDefault();
    if (!target) return;
    setBusy(true);
    try {
      await api(`/api/workspaces/${workspaceId}/indexes/rebuild`, {
        method: "POST",
        body: JSON.stringify(target),
      });
      setVersions(await api(`/api/workspaces/${workspaceId}/index-versions`));
      setMessage(
        "Rebuild queued. The active index remains searchable until validation and atomic activation.",
      );
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function action(id: string, kind: "retry" | "activate" | "cancel") {
    setBusy(true);
    try {
      await api(
        `/api/index-versions/${id}/${kind}?workspace_id=${workspaceId}`,
        { method: "POST" },
      );
      setVersions(await api(`/api/workspaces/${workspaceId}/index-versions`));
      setMessage(`Index ${kind} completed or queued.`);
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="advanced-settings">
      {message && (
        <p className="inline-notice" role="status">
          {message}
        </p>
      )}
      {profile && (
        <form onSubmit={save} className="settings-card">
          <div className="card-heading">
            <Icon name="book" />
            <div>
              <h2>Retrieval & evidence</h2>
              <p>
                Workspace defaults. Chat can override strategy and source
                filters per question.
              </p>
            </div>
          </div>
          <div className="settings-field-grid">
            <label>
              Default search mode
              <select
                value={profile.mode}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    mode: e.target.value as RetrievalSettings["mode"],
                  })
                }
              >
                <option value="hybrid">Hybrid · RRF</option>
                <option value="keyword">Keyword · FTS5</option>
                <option value="semantic">Dense · active embedding</option>
              </select>
            </label>
            <label>
              Resource profile
              <select
                aria-label="Resource profile"
                value={profile.reranker === "none" ? "light" : "rerank"}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    reranker:
                      e.target.value === "light" ? "none" : "cross-encoder",
                    candidate_count: e.target.value === "light" ? 15 : 25,
                  })
                }
              >
                <option value="light">Light CPU · no reranker</option>
                <option value="rerank">
                  CPU · optional cached cross-encoder
                </option>
              </select>
            </label>
            <label>
              Candidate count
              <input
                type="number"
                min={1}
                max={100}
                value={profile.candidate_count}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    candidate_count: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Final top K
              <input
                type="number"
                min={1}
                max={20}
                value={profile.top_k}
                onChange={(e) =>
                  setProfile({ ...profile, top_k: Number(e.target.value) })
                }
              />
            </label>
            <label>
              RRF constant
              <input
                type="number"
                min={1}
                max={200}
                value={profile.rrf_constant}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    rrf_constant: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Excerpt budget (UTF-8 bytes)
              <input
                type="number"
                min={200}
                max={32000}
                value={profile.context_budget}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    context_budget: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Lexical fusion weight
              <input
                type="number"
                min={0.1}
                max={5}
                step={0.1}
                value={profile.lexical_weight}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    lexical_weight: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Dense fusion weight
              <input
                type="number"
                min={0.1}
                max={5}
                step={0.1}
                value={profile.semantic_weight}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    semantic_weight: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={profile.rewrite}
              onChange={(e) =>
                setProfile({ ...profile, rewrite: e.target.checked })
              }
            />
            Reformulate short follow-ups locally using the previous user
            question
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={profile.multi_query}
              onChange={(e) =>
                setProfile({ ...profile, multi_query: e.target.checked })
              }
            />
            Use bounded local query variants (no additional cloud calls)
          </label>
          <label className="stacked-label">
            Optional local reranker model
            <input
              value={profile.reranker_model}
              onChange={(e) =>
                setProfile({ ...profile, reranker_model: e.target.value })
              }
            />
          </label>
          <p className="field-help">
            No reranker runs by default. An enabled cross-encoder loads lazily
            on CPU. Downloads are blocked unless the server explicitly enables
            them; unavailable models retain the original ranking with a
            diagnostic warning.
          </p>
          <button className="button primary" disabled={busy}>
            Save retrieval settings
            <Icon name="check" size={15} />
          </button>
        </form>
      )}
      <section className="settings-card">
        <div className="card-heading">
          <Icon name="settings" />
          <div>
            <h2>Versioned embedding indexes</h2>
            <p>
              Build, validate, then activate. Old namespaces remain available
              for a safe rollback.
            </p>
          </div>
        </div>
        {versions.map((version) => (
          <article className="index-version" key={version.id}>
            <div>
              <strong>
                {version.active ? "Active index" : version.status}
              </strong>
              <span>
                {version.configuration.embedding_provider} ·{" "}
                {version.configuration.embedding_dimension} dimensions ·{" "}
                {version.progress}/{version.total} documents
              </span>
              <code>{version.fingerprint}</code>
              {version.error && (
                <p className="document-error">{version.error}</p>
              )}
            </div>
            <div className="action-row">
              {version.status === "retired" && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => action(version.id, "activate")}
                >
                  Activate / rollback
                </button>
              )}
              {version.status === "failed" && (
                <button
                  className="button secondary"
                  disabled={busy || version.attempts >= 3}
                  onClick={() => action(version.id, "retry")}
                >
                  Retry ({version.attempts}/3)
                </button>
              )}
              {["building", "validating"].includes(version.status) && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => action(version.id, "cancel")}
                >
                  Cancel rebuild
                </button>
              )}
            </div>
          </article>
        ))}
      </section>
      {target && (
        <form className="settings-card" onSubmit={rebuild}>
          <h2>Build a replacement index</h2>
          <p className="field-help">
            Explicit local configuration only. Generation providers are never
            invoked for backfills. Change the model revision and actual vector
            dimension together.
          </p>
          <div className="settings-field-grid">
            <label>
              Embedding adapter
              <select
                value={target.embedding_provider}
                onChange={(e) =>
                  setTarget({
                    ...target,
                    embedding_provider: e.target
                      .value as IndexConfig["embedding_provider"],
                  })
                }
              >
                <option value="hash">Hash · offline plumbing demo</option>
                <option value="onnx">ONNX · quantized MiniLM CPU</option>
                <option value="sentence-transformers">
                  Sentence-transformers · semantic
                </option>
              </select>
            </label>
            <label>
              Vector dimension
              <input
                type="number"
                min={8}
                max={4096}
                value={target.embedding_dimension}
                onChange={(e) =>
                  setTarget({
                    ...target,
                    embedding_dimension: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Embedding model
              <input
                value={target.embedding_model}
                required
                onChange={(e) =>
                  setTarget({ ...target, embedding_model: e.target.value })
                }
              />
            </label>
            <label>
              Model revision
              <input
                value={target.embedding_revision}
                required
                onChange={(e) =>
                  setTarget({ ...target, embedding_revision: e.target.value })
                }
              />
            </label>
            {target.embedding_provider === "onnx" && (
              <label>
                ONNX artifact
                <input
                  value={target.embedding_onnx_file}
                  required
                  onChange={(event) =>
                    setTarget({
                      ...target,
                      embedding_onnx_file: event.target.value,
                    })
                  }
                />
              </label>
            )}
            <label>
              Chunk size (characters)
              <input
                type="number"
                min={100}
                max={2000}
                value={target.chunk_size}
                onChange={(e) =>
                  setTarget({ ...target, chunk_size: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Overlap (characters)
              <input
                type="number"
                min={0}
                max={target.chunk_size - 1}
                value={target.chunk_overlap}
                onChange={(e) =>
                  setTarget({
                    ...target,
                    chunk_overlap: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <button
            className="button primary"
            disabled={
              busy ||
              versions.some((v) =>
                ["building", "validating"].includes(v.status),
              )
            }
          >
            Build & validate index
            <Icon name="refresh" size={15} />
          </button>
        </form>
      )}
    </div>
  );
}
