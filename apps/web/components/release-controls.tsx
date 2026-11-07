"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export type GenerationPolicy = {
  provider: string;
  model: string;
  preset: string;
  consent_destination: string;
  allow_paid: boolean;
  free_tier_confirmed: boolean;
  max_calls_per_day: number;
  max_output_tokens: number;
  timeout_seconds: number;
  retries: number;
};
type Model = {
  id: string;
  provider: string;
  kind: string;
  status: string;
  destination: string | null;
  capabilities?: Record<string, unknown>;
};
type Member = { user_id: string; username: string; role: string };
const labels: Record<string, string> = {
  mock: "Offline extractive demo",
  groq: "Groq · eligible Free Plan",
  openai: "OpenAI · optional",
  anthropic: "Anthropic · optional",
  google: "Google · optional",
  compatible: "Compatible endpoint · optional",
  ollama: "Ollama · installed local model",
};

export function ReleaseControls({
  workspaceId,
  onError,
  cloudPermission,
  onSaved,
}: {
  workspaceId: string;
  onError: (cause: unknown) => void;
  cloudPermission?: boolean;
  onSaved?: () => Promise<void>;
}) {
  const [models, setModels] = useState<Model[]>([]);
  const [policy, setPolicy] = useState<GenerationPolicy | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("viewer");
  const [identity, setIdentity] = useState<{ profile: string } | null>(null);
  const [loadedCloud, setLoadedCloud] = useState(false);
  const [cloudEdit, setCloudEdit] = useState<{
    base: boolean;
    value: boolean;
  } | null>(null);
  const cloudBase = cloudPermission ?? loadedCloud;
  const cloudAllowed =
    cloudEdit?.base === cloudBase ? cloudEdit.value : cloudBase;
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Model[]>("/api/models"),
      api<GenerationPolicy>(`/api/workspaces/${workspaceId}/route-policy`),
      api<{ profile: string }>("/api/auth/me"),
      api<{ id: string; cloud_opt_in: boolean }[]>("/api/workspaces"),
    ])
      .then(([items, route, who, spaces]) => {
        if (active) {
          setModels(items);
          setPolicy(route);
          setIdentity(who);
          setLoadedCloud(
            spaces.find((s) => s.id === workspaceId)?.cloud_opt_in || false,
          );
        }
      })
      .catch(onError);
    return () => {
      active = false;
    };
  }, [workspaceId, onError]);
  if (!policy)
    return (
      <section className="settings-card">
        <p role="status">Loading workspace model policy…</p>
      </section>
    );
  const selected = models.find(
    (item) => item.kind === "generation" && item.provider === policy.provider,
  );
  const remote = !["mock", "ollama"].includes(policy.provider);
  const consent = selected?.destination
    ? `${policy.provider}|${selected.destination}`
    : "";
  const update = (values: Partial<GenerationPolicy>) =>
    setPolicy({ ...policy, ...values });
  return (
    <>
      <section className="settings-card">
        <h2>Workspace model control</h2>
        <p>
          Used when you select Workspace model or have no personal default.
          Personal BYOK selections take precedence. Generation changes preserve
          the active index.
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            try {
              await api(`/api/workspaces/${workspaceId}/route-policy`, {
                method: "PUT",
                body: JSON.stringify(policy),
              });
              await api(`/api/workspaces/${workspaceId}`, {
                method: "PATCH",
                body: JSON.stringify({ cloud_opt_in: cloudAllowed }),
              });
              setNotice(
                "Workspace policy and privacy permission saved. Reload or return to chat to use this route.",
              );
              await onSaved?.();
            } catch (cause) {
              onError(cause);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="filter-grid">
            <label>
              Workspace generation provider
              <select
                value={policy.provider}
                onChange={(event) =>
                  update({
                    provider: event.target.value,
                    consent_destination: "",
                    allow_paid: false,
                    free_tier_confirmed: false,
                    preset:
                      event.target.value === "ollama"
                        ? "local-optional"
                        : ["groq", "mock"].includes(event.target.value)
                          ? "free-cpu"
                          : "cloud-optional",
                  })
                }
              >
                {Object.entries(labels).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Workspace model ID
              <input
                value={policy.model}
                onChange={(event) => update({ model: event.target.value })}
                maxLength={150}
                required
              />
            </label>
            <label>
              Resource preset
              <select
                value={policy.preset}
                onChange={(event) => update({ preset: event.target.value })}
              >
                <option value="free-cpu">Free / CPU</option>
                <option value="local-optional">Local Optional</option>
                <option value="cloud-optional">Cloud / Hybrid Optional</option>
              </select>
            </label>
            <label>
              Daily external/local model call cap
              <input
                type="number"
                min={0}
                max={10000}
                value={policy.max_calls_per_day}
                onChange={(event) =>
                  update({ max_calls_per_day: Number(event.target.value) })
                }
              />
            </label>
            <label>
              Maximum output tokens
              <input
                type="number"
                min={64}
                max={4096}
                value={policy.max_output_tokens}
                onChange={(event) =>
                  update({ max_output_tokens: Number(event.target.value) })
                }
              />
            </label>
            <label>
              Provider timeout (seconds)
              <input
                type="number"
                min={1}
                max={120}
                value={policy.timeout_seconds}
                onChange={(event) =>
                  update({ timeout_seconds: Number(event.target.value) })
                }
              />
            </label>
          </div>
          <p className="field-help">
            Availability: {selected?.status || "unknown"}. Destination:{" "}
            {selected?.destination || "not configured"}. Token streaming, tools
            and image transmission are not enabled. Retries: zero; a timeout may
            already have consumed provider usage.
          </p>
          <label className="check-label">
            <input
              type="checkbox"
              checked={cloudAllowed}
              onChange={(event) =>
                setCloudEdit({ base: cloudBase, value: event.target.checked })
              }
            />
            Allow remote excerpt transmission for this workspace, subject to the
            exact destination consent below.
          </label>
          {remote && (
            <>
              <label className="check-label">
                <input
                  type="checkbox"
                  disabled={!consent}
                  checked={!!consent && policy.consent_destination === consent}
                  onChange={(event) =>
                    update({
                      consent_destination: event.target.checked ? consent : "",
                    })
                  }
                />
                I allow my question and retrieved excerpts to be sent to{" "}
                {selected?.destination || "the configured destination"} for this
                provider.
              </label>
              {policy.provider === "groq" ? (
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={policy.free_tier_confirmed}
                    onChange={(event) =>
                      update({ free_tier_confirmed: event.target.checked })
                    }
                  />
                  I verified this account/model is eligible for the Free Plan.
                </label>
              ) : (
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={policy.allow_paid}
                    onChange={(event) =>
                      update({ allow_paid: event.target.checked })
                    }
                  />
                  I explicitly permit potentially paid usage for this optional
                  provider. No free eligibility is assumed.
                </label>
              )}
            </>
          )}
          {policy.provider === "ollama" && (
            <p>
              Install and choose your own local model first. NEXUS never pulls
              model weights or starts Ollama automatically.
            </p>
          )}
          <div className="settings-actions">
            <button className="button" disabled={busy}>
              Save workspace model policy
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await api<{
                    note: string;
                    model_available: boolean;
                  }>(`/api/workspaces/${workspaceId}/provider-check`, {
                    method: "POST",
                  });
                  setNotice(
                    `${result.model_available ? "Model listed" : "Model not listed"}. ${result.note}`,
                  );
                } catch (cause) {
                  onError(cause);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Check saved connection
            </button>
          </div>
        </form>
        <p className="field-help">
          Credentials come only from server environment variables:
          NEXUS_GROQ_API_KEY, NEXUS_OPENAI_API_KEY, NEXUS_ANTHROPIC_API_KEY,
          NEXUS_GOOGLE_API_KEY or NEXUS_COMPATIBLE_API_KEY. A key is never shown
          here.
        </p>
        {notice && <p role="status">{notice}</p>}
        <details>
          <summary>Adapter capabilities and installation status</summary>
          <ul>
            {models.map((item) => (
              <li key={item.id}>
                {item.id} · {item.status}{" "}
                {item.capabilities && `· ${JSON.stringify(item.capabilities)}`}
              </li>
            ))}
          </ul>
        </details>
      </section>
      <section className="settings-card">
        <h2>Portable settings</h2>
        <p>
          Exports contain no credentials, local vault paths or transferable
          cloud consent. Import clears remote/paid permission. Index
          configuration is a reference; rebuilding stays a separate action.
        </p>
        <div className="settings-actions">
          <button
            className="button secondary"
            onClick={async () => {
              try {
                const value = await api(
                  `/api/workspaces/${workspaceId}/settings-export`,
                );
                const url = URL.createObjectURL(
                  new Blob([JSON.stringify(value, null, 2)], {
                    type: "application/json",
                  }),
                );
                const link = document.createElement("a");
                link.href = url;
                link.download = "nexus-settings-v1.json";
                link.click();
                URL.revokeObjectURL(url);
              } catch (cause) {
                onError(cause);
              }
            }}
          >
            Export settings
          </button>
          <label className="button secondary">
            Import settings
            <input
              className="sr-only"
              type="file"
              accept=".json,application/json"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                try {
                  if (file.size > 100000)
                    throw new Error("Settings file exceeds 100 KB.");
                  await api(`/api/workspaces/${workspaceId}/settings-import`, {
                    method: "POST",
                    body: JSON.stringify(JSON.parse(await file.text())),
                  });
                  window.location.reload();
                } catch (cause) {
                  onError(cause);
                }
              }}
            />
          </label>
        </div>
      </section>
      {identity?.profile === "server" && (
        <section className="settings-card">
          <h2>Workspace members</h2>
          <p>
            Owner manages membership/settings. Editor adds sources and
            conversations. Viewer reads and searches. Accounts are created with
            the stopped administrator CLI.
          </p>
          <button
            className="button secondary"
            onClick={async () => {
              try {
                setMembers(
                  await api<Member[]>(`/api/workspaces/${workspaceId}/members`),
                );
              } catch (cause) {
                onError(cause);
              }
            }}
          >
            Load members
          </button>
          {members.map((member) => (
            <p key={member.user_id}>
              {member.username} · {member.role}{" "}
              <button
                className="text-button"
                onClick={async () => {
                  try {
                    await api(
                      `/api/workspaces/${workspaceId}/members/${member.user_id}`,
                      { method: "DELETE" },
                    );
                    setMembers(
                      members.filter((m) => m.user_id !== member.user_id),
                    );
                  } catch (cause) {
                    onError(cause);
                  }
                }}
              >
                Remove {member.username}
              </button>
            </p>
          ))}
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              try {
                await api(`/api/workspaces/${workspaceId}/members`, {
                  method: "PUT",
                  body: JSON.stringify({ username, role }),
                });
                setNotice("Membership saved.");
                setMembers(
                  await api<Member[]>(`/api/workspaces/${workspaceId}/members`),
                );
              } catch (cause) {
                onError(cause);
              }
            }}
          >
            <div className="filter-grid">
              <label>
                Member username
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                />
              </label>
              <label>
                Member role
                <select
                  value={role}
                  onChange={(event) => setRole(event.target.value)}
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="owner">Owner</option>
                </select>
              </label>
            </div>
            <button className="button secondary">Save membership</button>
          </form>
        </section>
      )}
    </>
  );
}
