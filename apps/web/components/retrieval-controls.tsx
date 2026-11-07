"use client";

import { useEffect, useState } from "react";
import {
  api,
  type Document,
  type RetrievalSettings,
  type SearchFilters,
  type Vault,
} from "../lib/api";

export type ChatRetrieval = {
  options?: RetrievalSettings;
  filters: SearchFilters;
  diagnostics: boolean;
};

export function RetrievalControls({
  workspaceId,
  documents,
  disabled,
  onChange,
  onError,
}: {
  workspaceId: string;
  documents: Document[];
  disabled: boolean;
  onChange: (value: ChatRetrieval) => void;
  onError: (cause: unknown) => void;
}) {
  const [profile, setProfile] = useState<RetrievalSettings | null>(null);
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [diagnostics, setDiagnostics] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!workspaceId) return;
    Promise.all([
      api<RetrievalSettings>(
        `/api/workspaces/${workspaceId}/retrieval-settings`,
      ),
      api<Vault[]>(`/api/workspaces/${workspaceId}/vaults`),
    ])
      .then(([config, values]) => {
        if (!cancelled) {
          setProfile(config);
          setVaults(values);
          setFilters({});
          onChange({ options: config, filters: {}, diagnostics: false });
        }
      })
      .catch(onError);
    return () => {
      cancelled = true;
    };
    // Callbacks only deliver results; re-fetching is tied to workspace selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);
  function change(
    nextProfile = profile,
    nextFilters = filters,
    nextDiagnostics = diagnostics,
  ) {
    setProfile(nextProfile);
    setFilters(nextFilters);
    setDiagnostics(nextDiagnostics);
    onChange({
      options: nextProfile || undefined,
      filters: nextFilters,
      diagnostics: nextDiagnostics,
    });
  }
  return (
    <div className="retrieval-toolbar">
      <label>
        Search mode
        <select
          aria-label="Retrieval mode"
          disabled={disabled || !profile}
          value={profile?.mode || "hybrid"}
          onChange={(event) =>
            profile &&
            change({
              ...profile,
              mode: event.target.value as RetrievalSettings["mode"],
            })
          }
        >
          <option value="hybrid">Hybrid · keyword + vector</option>
          <option value="keyword">Keyword · exact terms</option>
          <option value="semantic">Dense · active embedding</option>
        </select>
      </label>
      <button
        className="text-button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        Source filters {expanded ? "−" : "+"}
      </button>
      <label className="inline-check">
        <input
          type="checkbox"
          disabled={disabled}
          checked={diagnostics}
          onChange={(event) => change(profile, filters, event.target.checked)}
        />
        Diagnostics
      </label>
      {expanded && (
        <div className="retrieval-filter-grid">
          <label>
            Vault
            <select
              disabled={disabled}
              value={filters.vault_id || ""}
              onChange={(event) =>
                change(profile, {
                  ...filters,
                  vault_id: event.target.value || undefined,
                })
              }
            >
              <option value="">All sources</option>
              {vaults.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Document
            <select
              disabled={disabled}
              value={filters.document_ids?.[0] || ""}
              onChange={(event) =>
                change(profile, {
                  ...filters,
                  document_ids: event.target.value ? [event.target.value] : [],
                })
              }
            >
              <option value="">All documents</option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tags (match any)
            <input
              disabled={disabled}
              placeholder="research, work"
              value={filters.tags?.join(", ") || ""}
              onChange={(event) =>
                change(profile, {
                  ...filters,
                  tags: event.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label>
            Folder prefix
            <input
              disabled={disabled}
              placeholder="Projects/"
              value={filters.path_prefix || ""}
              onChange={(event) =>
                change(profile, {
                  ...filters,
                  path_prefix: event.target.value || undefined,
                })
              }
            />
          </label>
          <label>
            File type
            <select
              disabled={disabled}
              value={filters.types?.[0] || ""}
              onChange={(event) =>
                change(profile, {
                  ...filters,
                  types: event.target.value ? [event.target.value] : [],
                })
              }
            >
              <option value="">All types</option>
              <option value=".md">Markdown</option>
              <option value=".pdf">PDF</option>
              <option value=".txt">Text</option>
            </select>
          </label>
        </div>
      )}
    </div>
  );
}
