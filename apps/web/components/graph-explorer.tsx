"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type GraphData,
  type GraphNode,
  type NoteLink,
  type Source,
  type Vault,
  type VaultNote,
} from "../lib/api";
import { Icon } from "./icon";

export function GraphExplorer({
  workspaceId,
  onSource,
  onError,
}: {
  workspaceId: string;
  onSource: (source: Source) => void;
  onError: (cause: unknown) => void;
}) {
  const [data, setData] = useState<GraphData | null>(null);
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [vaultId, setVaultId] = useState("");
  const [tag, setTag] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [limit, setLimit] = useState(150);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [detail, setDetail] = useState<{
    note: VaultNote;
    backlinks: NoteLink[];
    outlinks: NoteLink[];
  } | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, zoom: 1 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const drag = useRef<{
    x: number;
    y: number;
    startX: number;
    startY: number;
  } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    let cancelled = false;
    api<Vault[]>(`/api/workspaces/${workspaceId}/vaults`)
      .then((values) => {
        if (!cancelled) {
          setVaults(values);
          const id = new URLSearchParams(window.location.search).get("vault");
          if (id && values.some((v) => v.id === id)) setVaultId(id);
        }
      })
      .catch(onError);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);
  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    if (vaultId) params.set("vault_id", vaultId);
    if (tag) params.set("tag", tag);
    if (kind) params.set("kind", kind);
    return api<GraphData>(`/api/workspaces/${workspaceId}/graph?${params}`);
  }, [workspaceId, vaultId, tag, kind, query, limit]);
  useEffect(() => {
    let cancelled = false;
    refresh()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setLoading(false);
          onError(cause);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);
  async function select(node: GraphNode) {
    setSelected(node);
    setDetail(null);
    if (node.type === "tag") return;
    try {
      setDetail(await api(`/api/notes/${node.id}?workspace_id=${workspaceId}`));
    } catch (cause) {
      onError(cause);
    }
  }
  async function inspectId(id: string) {
    try {
      const value = await api<{
        note: VaultNote;
        backlinks: NoteLink[];
        outlinks: NoteLink[];
      }>(`/api/notes/${id}?workspace_id=${workspaceId}`);
      setDetail(value);
      setSelected({
        id: value.note.id,
        label: value.note.path,
        type: "note",
        source_url: value.note.source_url,
      });
    } catch (cause) {
      onError(cause);
    }
  }
  async function open(node: GraphNode) {
    if (!node.source_url) return;
    try {
      onSource(await api<Source>(node.source_url));
    } catch (cause) {
      onError(cause);
    }
  }
  function zoom(delta: number) {
    setView((v) => ({
      ...v,
      zoom: Math.min(3, Math.max(0.35, v.zoom + delta)),
    }));
  }
  const neighbors = useMemo(() => {
    const ids = new Set<string>();
    if (selected) {
      ids.add(selected.id);
      data?.edges.forEach((edge) => {
        if (edge.source === selected.id) ids.add(edge.target);
        if (edge.target === selected.id) ids.add(edge.source);
      });
    }
    return ids;
  }, [data, selected]);
  const positions = useMemo(
    () =>
      new Map(
        (data?.nodes || []).map((node, index, nodes) => {
          const angle = index * Math.PI * (3 - Math.sqrt(5));
          const radius =
            30 + 250 * Math.sqrt(index / Math.max(1, nodes.length));
          return [
            node.id,
            {
              x: 450 + radius * 1.25 * Math.cos(angle),
              y: 300 + radius * Math.sin(angle),
            },
          ];
        }),
      ),
    [data?.nodes],
  );
  return (
    <div className="page-content graph-content">
      <span className="eyebrow">SEE THE CONNECTIONS</span>
      <div className="page-heading">
        <div>
          <h1>A map of your thinking.</h1>
          <p>Authored note links and tags. Every connection has a source.</p>
        </div>
        <button
          className="button secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              setData(await refresh());
            } catch (cause) {
              onError(cause);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Icon name="refresh" size={16} />
          Refresh graph
        </button>
      </div>
      <div className="graph-filters">
        <label>
          Vault
          <select
            value={vaultId}
            onChange={(event) => setVaultId(event.target.value)}
          >
            <option value="">All vaults</option>
            {vaults.map((v) => (
              <option value={v.id} key={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Find a node
          <input
            value={query}
            placeholder="Note path"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          Tag
          <input
            value={tag}
            placeholder="research"
            onChange={(event) => setTag(event.target.value)}
          />
        </label>
        <label>
          Connection type
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">All authored connections</option>
            <option value="wikilink">Wikilinks</option>
            <option value="markdown">Markdown links</option>
            <option value="embed">Embeds</option>
            <option value="tag">Tag membership</option>
          </select>
        </label>
        <label>
          Note limit
          <select
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          >
            <option value={75}>75</option>
            <option value={150}>150</option>
            <option value={300}>300</option>
          </select>
        </label>
      </div>
      <div className="graph-summary" role="status">
        {loading
          ? "Loading your graph…"
          : `${data?.shown_notes || 0} of ${data?.total_notes || 0} notes · ${data?.edges.length || 0} connections`}
        {data?.truncated &&
          " · Subset shown: narrow your filters to explore more."}
        <span>
          Solid: note links · dashed: tags · no inferred relationships
        </span>
      </div>
      <div className="graph-stage">
        <div className="graph-zoom">
          <button aria-label="Zoom in graph" onClick={() => zoom(0.2)}>
            +
          </button>
          <span>{Math.round(view.zoom * 100)}%</span>
          <button aria-label="Zoom out graph" onClick={() => zoom(-0.2)}>
            −
          </button>
          <button onClick={() => setView({ x: 0, y: 0, zoom: 1 })}>
            Reset
          </button>
        </div>
        {!loading && !data?.nodes.length ? (
          <div className="graph-empty">
            <Icon name="book" size={32} />
            <h2>No connections here yet.</h2>
            <p>
              Import a vault with [[note links]] or tags, or clear your filters.
            </p>
          </div>
        ) : (
          <svg
            ref={svg}
            viewBox="0 0 900 600"
            role="group"
            aria-label="Knowledge graph. Drag to pan. Use zoom buttons or keyboard plus and minus."
            tabIndex={0}
            onKeyDown={(event) => {
              if (
                [
                  "+",
                  "=",
                  "-",
                  "ArrowLeft",
                  "ArrowRight",
                  "ArrowUp",
                  "ArrowDown",
                ].includes(event.key)
              )
                event.preventDefault();
              if (["+", "="].includes(event.key)) zoom(0.2);
              else if (event.key === "-") zoom(-0.2);
              else if (event.key.startsWith("Arrow"))
                setView((v) => ({
                  ...v,
                  x:
                    v.x +
                    (event.key === "ArrowLeft"
                      ? 30
                      : event.key === "ArrowRight"
                        ? -30
                        : 0),
                  y:
                    v.y +
                    (event.key === "ArrowUp"
                      ? 30
                      : event.key === "ArrowDown"
                        ? -30
                        : 0),
                }));
            }}
            onWheel={(event) => zoom(event.deltaY < 0 ? 0.1 : -0.1)}
            onPointerDown={(event) => {
              if ((event.target as Element).closest("[data-node]")) return;
              drag.current = {
                x: event.clientX,
                y: event.clientY,
                startX: view.x,
                startY: view.y,
              };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (drag.current) {
                const factor =
                  900 /
                  Math.max(
                    1,
                    svg.current?.getBoundingClientRect().width || 900,
                  );
                setView((v) => ({
                  ...v,
                  x:
                    drag.current!.startX +
                    (event.clientX - drag.current!.x) * factor,
                  y:
                    drag.current!.startY +
                    (event.clientY - drag.current!.y) * factor,
                }));
              }
            }}
            onPointerUp={() => {
              drag.current = null;
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
          >
            <defs>
              <marker
                id="edge-arrow"
                markerWidth="6"
                markerHeight="6"
                refX="16"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L0,6 L6,3 z" fill="#a0b18f" />
              </marker>
            </defs>
            <g
              transform={`translate(${view.x + 450 * (1 - view.zoom)} ${view.y + 300 * (1 - view.zoom)}) scale(${view.zoom})`}
            >
              {data?.edges.map((edge) => {
                const from = positions.get(edge.source),
                  to = positions.get(edge.target);
                return from && to ? (
                  <line
                    key={edge.id}
                    className={`graph-edge ${edge.type === "tag" ? "tag-edge" : ""} ${selected ? ([edge.source, edge.target].includes(selected.id) ? "highlighted" : "dimmed") : ""}`}
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke={edge.type === "tag" ? "#b4c5a3" : "#94ab82"}
                    strokeWidth={
                      selected &&
                      [edge.source, edge.target].includes(selected.id)
                        ? 2
                        : 1
                    }
                    strokeDasharray={edge.type === "tag" ? "4 4" : undefined}
                    markerEnd={
                      edge.type !== "tag" ? "url(#edge-arrow)" : undefined
                    }
                  />
                ) : null;
              })}
              {data?.nodes.map((node) => {
                const point = positions.get(node.id)!;
                return (
                  <g
                    key={node.id}
                    data-node={node.id}
                    className={`${node.type === "tag" ? "tag-node" : ""} ${selected ? (selected.id === node.id ? "selected" : neighbors.has(node.id) ? "connected" : "dimmed") : ""}`}
                    transform={`translate(${point.x} ${point.y})`}
                    role="button"
                    tabIndex={-1}
                    aria-label={node.label}
                    onClick={() => select(node)}
                  >
                    <title>{node.label}</title>
                    <circle
                      r={node.type === "tag" ? 7 : 10}
                      fill={
                        selected?.id === node.id
                          ? "#315e47"
                          : node.type === "tag"
                            ? "#d9e5ca"
                            : "#8da978"
                      }
                      stroke="#fcfdf8"
                      strokeWidth="2"
                    />
                    <text
                      y="24"
                      textAnchor="middle"
                      fontSize={data.nodes.length > 100 ? 8 : 10}
                      fill="#536548"
                    >
                      {node.label.length > 25
                        ? "…" + node.label.slice(-24)
                        : node.label}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        )}
      </div>
      <div className="graph-lower">
        <section className="settings-card">
          <h2>Nodes · keyboard-friendly list</h2>
          <p className="field-help">
            Select a note to inspect its backlinks and open its authorized
            source.
          </p>
          <div className="graph-node-list">
            {data?.nodes.map((node) => (
              <button
                className={selected?.id === node.id ? "selected" : ""}
                key={node.id}
                onClick={() => select(node)}
              >
                {node.type === "tag" ? "#" : "↗"} {node.label}
              </button>
            ))}
          </div>
        </section>
        <section className="settings-card graph-inspector">
          <h2>{selected?.label || "Follow a connection"}</h2>
          {selected ? (
            <>
              <p className="field-help">
                {selected.type === "tag"
                  ? "Explicit tag membership"
                  : "Authored Markdown note"}
              </p>
              {selected.type === "tag" ? (
                <button
                  className="button secondary"
                  onClick={() => setTag(selected.label.slice(1))}
                >
                  Filter this tag
                </button>
              ) : (
                <>
                  <button
                    className="button primary"
                    disabled={!selected.source_url}
                    onClick={() => open(selected)}
                  >
                    Open note source
                    <Icon name="external" size={15} />
                  </button>
                  <h3>Outgoing · {detail?.outlinks.length || 0}</h3>
                  {detail?.outlinks.map((link) => (
                    <div className="link-row" key={link.id}>
                      <span>
                        {link.target}
                        {link.anchor ? `#${link.anchor}` : ""}
                        <small>
                          {link.status} · {link.kind}
                        </small>
                      </span>
                      {link.target_id && (
                        <button
                          className="text-button"
                          onClick={() => {
                            const node = data?.nodes.find(
                              (n) => n.id === link.target_id,
                            );
                            if (node) void select(node);
                            else void inspectId(link.target_id!);
                          }}
                        >
                          Follow
                        </button>
                      )}
                    </div>
                  ))}
                  <h3>Backlinks · {detail?.backlinks.length || 0}</h3>
                  {detail?.backlinks.map((link) => (
                    <div className="link-row" key={link.id}>
                      <span>
                        {data?.nodes.find((n) => n.id === link.source_id)
                          ?.label || "Linked note"}
                      </span>
                      <button
                        className="text-button"
                        onClick={() => {
                          const node = data?.nodes.find(
                            (n) => n.id === link.source_id,
                          );
                          if (node) void select(node);
                          else void inspectId(link.source_id);
                        }}
                      >
                        Select source
                      </button>
                    </div>
                  ))}
                </>
              )}
            </>
          ) : (
            <p className="field-help">
              Select a node in the map or the list. Graph subsets keep larger
              vaults responsive.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
