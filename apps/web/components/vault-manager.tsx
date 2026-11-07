"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type NoteLink,
  type Source,
  type SyncStatus,
  type Vault,
  type VaultNote,
} from "../lib/api";
import { Icon } from "./icon";

export function VaultManager({
  workspaceId,
  onSource,
  onError,
}: {
  workspaceId: string;
  onSource: (source: Source) => void;
  onError: (cause: unknown) => void;
}) {
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [vaultId, setVaultId] = useState("");
  const [notes, setNotes] = useState<VaultNote[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [prefix, setPrefix] = useState("");
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [links, setLinks] = useState<NoteLink[]>([]);
  const [detail, setDetail] = useState<{
    note: VaultNote;
    backlinks: NoteLink[];
    outlinks: NoteLink[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [reindexId, setReindexId] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const updating = useRef(false);
  const selected = vaults.find((v) => v.id === vaultId);
  const refresh = useCallback(async () => {
    return api<Vault[]>(`/api/workspaces/${workspaceId}/vaults`);
  }, [workspaceId]);
  useEffect(() => {
    let cancelled = false;
    if (!workspaceId) return;
    refresh()
      .then((values) => {
        if (!cancelled) {
          setVaults(values);
          if (!vaultId && values[0]) setVaultId(values[0].id);
        }
      })
      .catch(onError)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    const timer = setInterval(() => {
      if (!cancelled)
        refresh()
          .then((values) => {
            if (!cancelled) setVaults(values);
          })
          .catch(() => {});
    }, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, vaultId]);
  useEffect(() => {
    if (!vaultId) return;
    let cancelled = false;
    const params = new URLSearchParams({
      workspace_id: workspaceId,
      q: query,
      tag,
      prefix,
      offset: String(offset),
      limit: "100",
    });
    async function load() {
      try {
        const [listing, sync, relationships] = await Promise.all([
          api<{ notes: VaultNote[]; total: number }>(
            `/api/vaults/${vaultId}/notes?${params}`,
          ),
          api<SyncStatus>(
            `/api/vaults/${vaultId}/sync-status?workspace_id=${workspaceId}`,
          ),
          api<{ links: NoteLink[] }>(
            `/api/vaults/${vaultId}/links?workspace_id=${workspaceId}&limit=300`,
          ),
        ]);
        if (!cancelled) {
          setNotes(listing.notes);
          setTotal(listing.total);
          setStatus(sync);
          setLinks(relationships.links);
        }
      } catch (cause) {
        if (!cancelled) onError(cause);
      }
    }
    void load();
    const timer = setInterval(load, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, vaultId, query, tag, prefix, offset]);
  async function upload(archive: File | undefined) {
    if (!archive) return;
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", archive);
      const path =
        updating.current && vaultId
          ? `/api/vaults/${vaultId}/sync?workspace_id=${workspaceId}`
          : `/api/workspaces/${workspaceId}/vaults/import?name=${encodeURIComponent(archive.name.replace(/\.zip$/i, ""))}`;
      const result = await api<SyncStatus>(path, {
        method: "POST",
        body: form,
      });
      setVaultId(result.vault.id);
      setStatus(result);
      setVaults(await refresh());
      setMessage(
        "Snapshot accepted. Only changed notes will be indexed; removed notes stop being searchable immediately.",
      );
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  }
  async function inspect(noteId: string) {
    try {
      setDetail(await api(`/api/notes/${noteId}?workspace_id=${workspaceId}`));
    } catch (cause) {
      onError(cause);
    }
  }
  async function openNote(note: VaultNote) {
    if (!note.source_url) return;
    try {
      onSource(await api<Source>(note.source_url));
    } catch (cause) {
      onError(cause);
    }
  }
  async function action(kind: "retry" | "sync") {
    setBusy(true);
    try {
      const result = await api<SyncStatus>(
        `/api/vaults/${vaultId}/${kind}?workspace_id=${workspaceId}`,
        { method: "POST" },
      );
      setStatus(result);
      setVaults(await refresh());
      setMessage(
        kind === "sync"
          ? "Rescan requested. The approved local agent will pick it up on its next scan."
          : "Sync retry queued.",
      );
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function reindex(note: VaultNote) {
    if (!note.document_id) return;
    setReindexId(note.id);
    try {
      await api(
        `/api/documents/${note.document_id}/reindex?workspace_id=${workspaceId}`,
        { method: "POST" },
      );
      setMessage(`Reindex queued for ${note.path}.`);
    } catch (cause) {
      onError(cause);
    } finally {
      setReindexId("");
    }
  }
  const broken = links.filter((e) =>
    ["unresolved", "ambiguous", "blocked", "missing_anchor"].includes(e.status),
  );
  return (
    <div className="page-content knowledge-content">
      <span className="eyebrow">OBSIDIAN, CONNECTED</span>
      <div className="page-heading">
        <div>
          <h1>Your notes belong together.</h1>
          <p>
            Bring in a vault. Keep its paths, tags, and authored connections.
          </p>
        </div>
        <button
          className="button primary"
          disabled={busy}
          onClick={() => {
            updating.current = false;
            file.current?.click();
          }}
        >
          <Icon name="upload" size={17} />
          Import vault ZIP
        </button>
      </div>
      <input
        type="file"
        accept=".zip"
        className="sr-only"
        aria-label="Vault ZIP file"
        ref={file}
        onChange={(event) => upload(event.target.files?.[0])}
      />
      <div className="knowledge-disclosure">
        ZIP imports are snapshots. A folder is synced only while your explicitly
        configured local agent is running. Plugins and vault scripts are never
        executed.
      </div>
      {message && (
        <p className="inline-notice" role="status">
          {message}
        </p>
      )}
      {loading ? (
        <div className="loading-state" role="status">
          Loading vaults…
        </div>
      ) : !vaults.length ? (
        <div className="library-empty">
          <Icon name="book" size={32} />
          <h3>A place for connected thinking.</h3>
          <p>
            Import a ZIP with Markdown notes, frontmatter tags, and
            [[wikilinks]].
          </p>
        </div>
      ) : (
        <>
          <div className="vault-selector">
            <label>
              Vault
              <select
                value={vaultId}
                onChange={(event) => {
                  setVaultId(event.target.value);
                  setOffset(0);
                  setDetail(null);
                }}
              >
                {vaults.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} · {v.note_count} notes
                  </option>
                ))}
              </select>
            </label>
            <span className={`document-status ${selected?.status}`}>
              {selected?.source_kind === "agent"
                ? "Local agent"
                : "ZIP snapshot"}{" "}
              · {selected?.status}
            </span>
            <Link className="button secondary" href={`/graph?vault=${vaultId}`}>
              Explore graph ↗
            </Link>
          </div>
          <section className="sync-card">
            <div>
              <h2>Manifest & synchronization</h2>
              <p>
                {status?.vault.last_scan
                  ? `Last successful scan: ${new Date(status.vault.last_scan).toLocaleString()}`
                  : "Waiting for the first successful scan"}
              </p>
              <p>
                {status?.run
                  ? Object.entries(status.run.counts)
                      .map(([key, value]) => `${value} ${key}`)
                      .join(" · ")
                  : "No pending manifest"}
              </p>
              {status?.run?.status === "processing" && (
                <p role="status">
                  Applied {status.run.cursor} of {status.run.manifest.length}{" "}
                  changed notes
                </p>
              )}
              {status?.vault.error && (
                <p className="document-error" role="alert">
                  {status.vault.error}
                </p>
              )}
            </div>
            <div className="action-row">
              {selected?.source_kind === "snapshot" ? (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => {
                    updating.current = true;
                    file.current?.click();
                  }}
                >
                  Update snapshot
                </button>
              ) : (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => action("sync")}
                >
                  Request agent rescan
                </button>
              )}
              {status?.run?.status === "failed" && (
                <button
                  className="button secondary"
                  disabled={busy || status.run.attempts >= 3}
                  onClick={() => action("retry")}
                >
                  Retry sync ({status.run.attempts}/3)
                </button>
              )}
            </div>
          </section>
          <div className="note-filter-row">
            <label>
              Find a note
              <input
                value={query}
                placeholder="Filename or path"
                onChange={(event) => {
                  setQuery(event.target.value);
                  setOffset(0);
                }}
              />
            </label>
            <label>
              Folder
              <input
                value={prefix}
                placeholder="Projects/"
                onChange={(event) => {
                  setPrefix(event.target.value);
                  setOffset(0);
                }}
              />
            </label>
            <label>
              Tag
              <input
                value={tag}
                placeholder="research"
                onChange={(event) => {
                  setTag(event.target.value);
                  setOffset(0);
                }}
              />
            </label>
          </div>
          <div className="library-summary">
            <h2>
              Notes <span>{total}</span>
            </h2>
            <span>Paths are relative to the vault root</span>
          </div>
          <div className="document-list">
            {notes.length ? (
              notes.map((note) => (
                <article key={note.id} className="document-row">
                  <span className="file-symbol md">
                    <Icon name="files" size={20} />
                  </span>
                  <div className="document-info">
                    <button
                      className="document-title"
                      disabled={!note.source_url}
                      onClick={() => openNote(note)}
                    >
                      {note.path}
                    </button>
                    <span>
                      {note.tags.map((value) => `#${value}`).join(" ") ||
                        "No tags"}
                    </span>
                  </div>
                  <span className={`document-status ${note.status}`}>
                    {note.status}
                  </span>
                  <button
                    className="icon-button"
                    aria-label={`Connections for ${note.path}`}
                    onClick={() => inspect(note.id)}
                  >
                    <Icon name="book" size={17} />
                  </button>
                  <button
                    className="icon-button"
                    disabled={
                      !note.document_id ||
                      reindexId === note.id ||
                      note.status === "pending"
                    }
                    aria-label={`Reindex ${note.path}`}
                    onClick={() => reindex(note)}
                  >
                    <Icon name="refresh" size={17} />
                  </button>
                </article>
              ))
            ) : (
              <div className="library-empty">
                <p>No notes match these filters.</p>
              </div>
            )}
          </div>
          <div className="pagination">
            <button
              className="button secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 100))}
            >
              Previous
            </button>
            <span>
              {total ? offset + 1 : 0}–{Math.min(total, offset + 100)} of{" "}
              {total}
            </span>
            <button
              className="button secondary"
              disabled={offset + 100 >= total}
              onClick={() => setOffset(offset + 100)}
            >
              Next
            </button>
          </div>
          {detail && (
            <section className="settings-card connection-detail">
              <div className="card-heading">
                <Icon name="book" />
                <div>
                  <h2>{detail.note.path}</h2>
                  <p>Explicit outgoing links and backlinks</p>
                </div>
                <button
                  className="icon-button"
                  onClick={() => setDetail(null)}
                  aria-label="Close note connections"
                >
                  <Icon name="close" size={16} />
                </button>
              </div>
              <h3>Outgoing · {detail.outlinks.length}</h3>
              {detail.outlinks.map((link) => (
                <div className="link-row" key={link.id}>
                  <span>
                    {link.label} {link.anchor ? `#${link.anchor}` : ""}
                    <small>
                      {link.kind} · {link.status}
                    </small>
                  </span>
                  {link.target_id && (
                    <button
                      className="text-button"
                      onClick={() => inspect(link.target_id!)}
                    >
                      Inspect target
                    </button>
                  )}
                </div>
              ))}
              <h3>Backlinks · {detail.backlinks.length}</h3>
              {detail.backlinks.map((link) => (
                <div className="link-row" key={link.id}>
                  <span>
                    {link.label}
                    <small>{link.kind} · authored link</small>
                  </span>
                  <button
                    className="text-button"
                    onClick={() => inspect(link.source_id)}
                  >
                    Inspect source
                  </button>
                </div>
              ))}
            </section>
          )}
          <details className="settings-card">
            <summary>
              Unresolved, ambiguous & blocked links · {broken.length}
              {selected && selected.unresolved_count > broken.length
                ? ` (first ${links.length} links shown)`
                : ""}
            </summary>
            {broken.map((link) => (
              <div className="link-row" key={link.id}>
                <span>
                  {link.target || "This note"}
                  {link.anchor ? `#${link.anchor}` : ""}
                  <small>
                    {link.status}
                    {link.candidates.length
                      ? ` · candidates: ${link.candidates.join(", ")}`
                      : ""}
                  </small>
                </span>
                <button
                  className="text-button"
                  onClick={() => inspect(link.source_id)}
                >
                  Inspect source
                </button>
              </div>
            ))}
          </details>
        </>
      )}
      <details className="settings-card agent-instructions">
        <summary>Sync an approved local folder</summary>
        <p>
          The browser cannot watch your disk. Run the opt-in local agent
          yourself, with the exact folder you approve. Use <code>--once</code>{" "}
          for one scan; leave it running for periodic scans. The agent only
          sends to localhost.
        </p>
        <pre>{`.\\.venv\\Scripts\\python.exe scripts/vault_sync.py --root "C:\\My Vault" --workspace ${workspaceId}${selected?.source_kind === "agent" ? ` --vault-id ${vaultId}` : ""} --interval 15`}</pre>
        <p>
          After the first scan, use the vault ID printed by the agent with{" "}
          <code>--vault-id</code> on subsequent runs. Symlinks, junctions,
          unsafe paths, and changing files are rejected.
        </p>
      </details>
    </div>
  );
}
