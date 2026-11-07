"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import {
  configurationDraft,
  type AIConfiguration,
  type AISelection,
  type ConfigurationDraft,
  type Connection,
  type ProviderCatalog,
  type ProviderModel,
  type ProviderUsage,
} from "../lib/byok";
import { Icon } from "./icon";
import { Skeleton } from "./motion-system";

const root = "/api/me/provider-configurations";
export function ByokControls({
  workspaceId,
  selection,
  onChanged,
  onError,
}: {
  workspaceId: string;
  selection: AISelection | null;
  onChanged: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [catalog, setCatalog] = useState<ProviderCatalog | null>(null);
  const [usage, setUsage] = useState<ProviderUsage | null>(null);
  const [draft, setDraft] = useState<ConfigurationDraft>(() =>
    configurationDraft(),
  );
  const [editing, setEditing] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [query, setQuery] = useState("");
  const [connection, setConnection] = useState<Connection | null>(null);
  const [pending, setPending] = useState("");
  const [notice, setNotice] = useState("");
  const [cloudPending, setCloudPending] = useState<boolean | null>(null);
  const load = useCallback(async () => {
    const [next, events] = await Promise.all([
      api<ProviderCatalog>(root),
      api<ProviderUsage>("/api/me/provider-usage"),
    ]);
    setCatalog(next);
    setUsage(events);
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([
      api<ProviderCatalog>(root),
      api<ProviderUsage>("/api/me/provider-usage"),
    ])
      .then(([next, events]) => {
        if (active) {
          setCatalog(next);
          setUsage(events);
        }
      })
      .catch(onError);
    return () => {
      active = false;
    };
  }, [onError]);
  const stored = catalog?.configurations.find((c) => c.id === editing);
  const provider = catalog?.providers.find((p) => p.id === draft.provider);
  const selectedModel =
    models.find((m) => m.id === draft.model) ?? stored?.model_metadata;
  const temperatureAllowed =
    draft.provider === "openrouter"
      ? !!editing &&
        !!selectedModel?.supported_parameters.includes("temperature")
      : ["google", "groq", "ollama"].includes(draft.provider) ||
        (draft.provider === "openai" &&
          /^(gpt-4|gpt-3\.5|chatgpt-4)/.test(draft.model));
  const filtered = models
    .filter((m) =>
      (m.name + " " + m.id).toLowerCase().includes(query.toLowerCase()),
    )
    .slice(0, 200);
  function change<T extends keyof ConfigurationDraft>(
    field: T,
    value: ConfigurationDraft[T],
  ) {
    setDraft((d) => ({ ...d, [field]: value }));
  }
  function fresh() {
    setEditing(null);
    setDraft(configurationDraft());
    setApiKey("");
    setShowKey(false);
    setModels([]);
    setQuery("");
    setConnection(null);
    setNotice("");
  }
  async function edit(config: AIConfiguration) {
    setEditing(config.id);
    setDraft(configurationDraft(config));
    setApiKey("");
    setShowKey(false);
    setConnection(config.connection);
    setQuery("");
    setModels([]);
    setNotice("");
    try {
      setModels(
        (await api<{ models: ProviderModel[] }>(`${root}/${config.id}/models`))
          .models,
      );
    } catch (error) {
      onError(error);
    }
  }
  async function check() {
    setPending("test");
    setConnection({
      status: "testing",
      message: "Testing the provider's metadata endpoint…",
    });
    setNotice("");
    try {
      if (
        stored &&
        !apiKey &&
        JSON.stringify(configurationDraft(stored)) === JSON.stringify(draft)
      ) {
        const status = await api<Connection>(`${root}/${stored.id}/test`, {
          method: "POST",
        });
        setConnection(status);
        setModels(
          (
            await api<{ models: ProviderModel[] }>(
              `${root}/${stored.id}/models`,
            )
          ).models,
        );
        await load();
        await onChanged();
        return;
      }
      const result = await api<{
        models: ProviderModel[];
        connection: Connection;
      }>(`${root}/preview`, {
        method: "POST",
        body: JSON.stringify({
          ...draft,
          name: draft.name || "Unsaved configuration",
          model: draft.model || "unselected",
          temperature: null,
          ...(apiKey ? { api_key: apiKey } : {}),
          ...(editing ? { configuration_id: editing } : {}),
        }),
      });
      setConnection(result.connection);
      setModels(result.models);
    } catch (error) {
      setConnection({
        status: "network_failure",
        message:
          error instanceof Error ? error.message : "Connection test failed.",
      });
    } finally {
      setPending("");
    }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    setPending("save");
    setNotice("");
    try {
      const result = await api<AIConfiguration>(
        editing ? `${root}/${editing}` : root,
        {
          method: editing ? "PUT" : "POST",
          body: JSON.stringify({
            ...draft,
            ...(apiKey ? { api_key: apiKey } : {}),
          }),
        },
      );
      setEditing(result.id);
      setApiKey("");
      setShowKey(false);
      setConnection(result.connection);
      await load();
      await onChanged();
      setNotice(
        "Configuration saved. The stored key is never returned to this browser.",
      );
      try {
        setModels(
          (
            await api<{ models: ProviderModel[] }>(
              `${root}/${result.id}/models`,
              { method: "POST" },
            )
          ).models,
        );
      } catch {
        setNotice(
          "Configuration saved. Model listing is unavailable; you can keep a manual model ID and test again.",
        );
      }
    } catch (error) {
      onError(error);
    } finally {
      setPending("");
    }
  }
  async function action(
    kind: "default" | "use" | "delete" | "credential",
    config: AIConfiguration,
  ) {
    if (
      kind === "delete" &&
      !confirm(
        `Remove ${config.name}? Active selections will stop until you choose another model.`,
      )
    )
      return;
    if (
      kind === "credential" &&
      !confirm(
        "Remove this stored key from NEXUS? Revoke it at the provider separately if necessary.",
      )
    )
      return;
    setPending(kind);
    setNotice("");
    try {
      if (kind === "use")
        await api(`/api/workspaces/${workspaceId}/ai-selection`, {
          method: "PUT",
          body: JSON.stringify({ configuration_id: config.id }),
        });
      else
        await api(
          `${root}/${config.id}${kind === "default" ? "/default" : kind === "credential" ? "/credential" : ""}`,
          { method: kind === "default" ? "POST" : "DELETE" },
        );
      if (kind === "delete" && editing === config.id) fresh();
      if (kind === "credential" && editing === config.id) {
        setApiKey("");
        setShowKey(false);
        setConnection({
          status: "not_configured",
          message: "Credential removed.",
        });
      }
      await load();
      await onChanged();
      setNotice(
        kind === "use"
          ? "Personal model selected for this workspace. Documents do not need reindexing."
          : kind === "default"
            ? "Personal default saved. Explicit workspace selections remain in effect."
            : kind === "delete"
              ? "Configuration removed. No automatic fallback was selected."
              : "Stored key removed. Provider-side revocation is a separate action.",
      );
    } catch (error) {
      onError(error);
    } finally {
      setPending("");
    }
  }
  if (!catalog) return <Skeleton label="Loading your private model settings" />;
  return (
    <div className="byok-workspace">
      <section className="settings-card byok-intro">
        <div>
          <span className="eyebrow">YOUR KEYS · YOUR MODELS</span>
          <h2>Intelligence on your terms.</h2>
          <p>
            Connect a provider with your own account, or run a model locally.
            NEXUS remains free to self-host.
          </p>
        </div>
        <span className="privacy-badge">
          <Icon name="lock" size={16} />
          Private to your account
        </span>
      </section>
      {!catalog.credential_storage.enabled && (
        <p className="knowledge-disclosure" role="status">
          {catalog.credential_storage.message} You can test an unsaved key; it
          will remain only in memory.
        </p>
      )}
      <section className="settings-card">
        <div className="byok-section-heading">
          <div>
            <h2>Your configurations</h2>
            <p className="field-help">
              A personal default and optional workspace selections. Keys and
              model settings are never shared with other members.
            </p>
          </div>
          <button
            className="button secondary"
            onClick={fresh}
            disabled={!!pending}
          >
            <Icon name="plus" size={15} />
            Add configuration
          </button>
        </div>
        {(catalog.default_unavailable ||
          catalog.configurations.some((c) => c.is_default)) && (
          <button
            className="text-button clear-personal-default"
            disabled={!!pending}
            onClick={async () => {
              setPending("default");
              try {
                await api("/api/me/provider-default", { method: "DELETE" });
                await load();
                await onChanged();
                setNotice(
                  "Personal default cleared. Explicit workspace selections remain in effect.",
                );
              } catch (error) {
                onError(error);
              } finally {
                setPending("");
              }
            }}
          >
            Clear personal default
          </button>
        )}
        {catalog.configurations.length ? (
          <div className="saved-models">
            {catalog.configurations.map((config) => (
              <article
                className={`saved-model ${selection?.active?.id === config.id ? "is-active" : ""}`}
                key={config.id}
              >
                <button
                  className="saved-model-main"
                  aria-label={`Edit ${config.name}`}
                  disabled={!!pending}
                  onClick={() => edit(config)}
                >
                  <span className="provider-monogram">
                    {config.provider.slice(0, 1).toUpperCase()}
                  </span>
                  <span>
                    <strong>
                      {config.name}
                      {config.is_default && <small>Default</small>}
                    </strong>
                    <span>
                      {config.provider} · {config.model}
                    </span>
                    <small>
                      {config.provider === "ollama"
                        ? "Local model"
                        : config.credential_configured
                          ? "Key securely stored"
                          : "Credential missing"}{" "}
                      · {config.connection.status.replaceAll("_", " ")}
                    </small>
                  </span>
                </button>
                <div className="saved-model-actions">
                  <button
                    className="button secondary"
                    disabled={!!pending || selection?.active?.id === config.id}
                    onClick={() => action("use", config)}
                  >
                    {selection?.active?.id === config.id
                      ? "Active here"
                      : "Use here"}
                  </button>
                  <button
                    className="text-button"
                    disabled={!!pending || config.is_default}
                    onClick={() => action("default", config)}
                  >
                    Make default
                  </button>
                  <button
                    className="icon-button danger"
                    aria-label={`Remove ${config.name}`}
                    disabled={!!pending}
                    onClick={() => action("delete", config)}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="byok-empty">
            No personal providers yet. The existing workspace model remains
            available until you choose a configuration.
          </p>
        )}
        {selection?.unavailable && (
          <p className="field-help" role="alert">
            Your selected configuration was removed. Choose another model
            explicitly; NEXUS has not switched providers.
          </p>
        )}
      </section>
      <form onSubmit={save} className="byok-editor">
        <section className="settings-card">
          <div className="byok-section-heading">
            <div>
              <span className="eyebrow">01 · PROVIDER</span>
              <h2>
                {editing
                  ? "Edit your connection"
                  : "Choose where your model runs"}
              </h2>
            </div>
            {editing && (
              <button
                className="text-button"
                type="button"
                onClick={fresh}
                disabled={!!pending}
              >
                Create a different connection ↗
              </button>
            )}
          </div>
          <div
            className="provider-choices"
            role="group"
            aria-label="AI provider"
          >
            {catalog.providers.map((p) => (
              <button
                type="button"
                key={p.id}
                aria-pressed={draft.provider === p.id}
                disabled={!!pending || (!!editing && draft.provider !== p.id)}
                className={`provider-choice ${draft.provider === p.id ? "selected" : ""}`}
                onClick={() => {
                  setDraft({
                    ...configurationDraft(),
                    provider: p.id,
                    name: draft.name,
                  });
                  setApiKey("");
                  setShowKey(false);
                  setModels([]);
                  setConnection(null);
                }}
              >
                <span className="provider-choice-top">
                  <span className="provider-monogram">
                    {p.name.slice(0, 1)}
                  </span>
                  <small>{p.remote ? "Cloud" : "Local"}</small>
                </span>
                <strong>{p.name}</strong>
                <span>{p.description}</span>
                <small>
                  {catalog.configurations.some(
                    (c) => c.provider === p.id && c.credential_configured,
                  )
                    ? "Credential configured"
                    : p.remote
                      ? "Your API key"
                      : "No API key"}
                </small>
              </button>
            ))}
          </div>
          <label className="byok-name">
            Configuration name
            <input
              value={draft.name}
              onChange={(e) => change("name", e.target.value)}
              maxLength={80}
              required
              placeholder="e.g. My everyday model"
              disabled={!!pending}
            />
          </label>
          {draft.provider === "compatible" && (
            <label className="byok-name">
              Custom HTTPS endpoint
              <input
                type="url"
                value={draft.base_url}
                onChange={(e) => change("base_url", e.target.value)}
                placeholder="https://api.example.com/v1"
                disabled={!!pending || !!editing}
                required
              />
              <span className="field-help">
                Use an HTTPS origin approved by your server operator. Redirects
                and private-network destinations are blocked.
              </span>
            </label>
          )}
          {provider?.remote ? (
            <div className="byok-credential">
              <label htmlFor="byok-key">
                {stored?.credential_configured
                  ? "Replace API key (optional)"
                  : "API key"}
              </label>
              <div className="key-input">
                <input
                  id="byok-key"
                  aria-label="Provider API key"
                  autoComplete="off"
                  spellCheck={false}
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  maxLength={4096}
                  placeholder={
                    stored?.credential_configured
                      ? "Credential stored · enter a new key to replace"
                      : "Paste your provider API key"
                  }
                  disabled={!!pending}
                />
                <button
                  type="button"
                  className="text-button"
                  aria-pressed={showKey}
                  aria-label={showKey ? "Hide unsaved key" : "Show unsaved key"}
                  disabled={!apiKey || !!pending}
                  onClick={() => setShowKey((v) => !v)}
                >
                  {showKey ? "Hide" : "Show"}
                </button>
              </div>
              <div className="credential-meta">
                <span>
                  <Icon name="lock" size={12} />
                  {stored?.credential_configured
                    ? "Encrypted credential configured. Saved values cannot be displayed."
                    : "Unsaved keys stay in memory. Saved keys are encrypted on the server."}
                </span>
                {stored?.credential_configured && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={!!pending}
                    onClick={() => action("credential", stored)}
                  >
                    Remove stored key
                  </button>
                )}
              </div>
            </div>
          ) : (
            <p className="knowledge-disclosure">
              Ollama runs on this NEXUS server&apos;s loopback interface.
              Install a local model yourself; NEXUS does not download models or
              use Ollama cloud automatically.
            </p>
          )}
          <div className="connection-test">
            <button
              type="button"
              className="button secondary"
              onClick={check}
              disabled={
                !!pending ||
                (!!provider?.remote &&
                  !apiKey &&
                  !stored?.credential_configured)
              }
            >
              {pending === "test" ? (
                <span className="loader tiny" />
              ) : (
                <Icon name="refresh" size={15} />
              )}
              Test connection & load models
            </button>
            <span
              className={`connection-status ${connection?.status ?? "not_configured"}`}
              role="status"
            >
              {connection?.message ??
                "Not tested. Connection tests use metadata requests, not paid generation."}
            </span>
          </div>
        </section>
        <section className="settings-card">
          <span className="eyebrow">02 · MODEL & GENERATION</span>
          <h2>A model for the way you work.</h2>
          <div className="model-browser">
            <label>
              Search provider models
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search names or model IDs"
                disabled={!models.length || !!pending}
              />
            </label>
            <label>
              Available provider models
              <select
                aria-label="Available provider models"
                value={draft.model}
                disabled={!models.length || !!pending}
                onChange={(e) => {
                  change("model", e.target.value);
                  change("temperature", null);
                  const m = models.find((v) => v.id === e.target.value);
                  if (m?.context_window)
                    change("context_window", m.context_window);
                }}
              >
                <option value="" disabled>
                  {models.length
                    ? "Choose a model"
                    : "Test connection to load the catalog"}
                </option>
                {draft.model && !filtered.some((m) => m.id === draft.model) && (
                  <option value={draft.model}>{draft.model} · manual ID</option>
                )}
                {filtered.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} · {m.id} ·{" "}
                    {m.cost_status === "free"
                      ? "Free (provider catalog)"
                      : m.cost_status === "paid"
                        ? "Paid"
                        : "Price unknown"}
                    {m.context_window
                      ? ` · ${m.context_window.toLocaleString()} context`
                      : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {models.length > 0 && (
            <p className="field-help">
              {filtered.length} matching models shown (up to 200).{" "}
              {filtered.length === 0
                ? "No matches. You can enter a manual identifier below."
                : "Provider availability and account quotas may change."}
            </p>
          )}
          <label className="byok-name">
            Manual model ID
            <input
              value={draft.model}
              aria-label="Manual model ID"
              onChange={(e) => {
                change("model", e.target.value);
                change("temperature", null);
              }}
              placeholder="Provider model identifier"
              maxLength={200}
              required
              disabled={!!pending}
            />
            <span className="field-help">
              New IDs and aliases are allowed even when absent from the catalog.
              A metadata test does not prove inference compatibility.
            </span>
          </label>
          {selectedModel && (
            <div className="model-facts">
              <span>
                Context{" "}
                <strong>
                  {selectedModel.context_window?.toLocaleString() ??
                    "Not reported"}
                </strong>
              </span>
              <span>
                Capabilities{" "}
                <strong>{selectedModel.capabilities.join(" · ")}</strong>
              </span>
              <span>
                Pricing{" "}
                <strong>
                  {selectedModel.cost_status === "unknown"
                    ? "Not reported"
                    : selectedModel.cost_status === "free"
                      ? "Free text tokens, per catalog"
                      : `$${((selectedModel.pricing?.input_per_token ?? 0) * 1e6).toFixed(2)} in / $${((selectedModel.pricing?.output_per_token ?? 0) * 1e6).toFixed(2)} out per 1M tokens`}
                </strong>
              </span>
            </div>
          )}
          <div className="settings-field-grid">
            <label>
              Maximum output tokens
              <input
                type="number"
                min={64}
                max={32768}
                value={draft.max_output_tokens}
                onChange={(e) =>
                  change("max_output_tokens", Number(e.target.value))
                }
                required
                disabled={!!pending}
              />
            </label>
            <label>
              Context window (tokens)
              <input
                type="number"
                min={2048}
                max={2000000}
                value={draft.context_window}
                onChange={(e) =>
                  change("context_window", Number(e.target.value))
                }
                required
                disabled={!!pending}
              />
            </label>
          </div>
          <label className="check-label">
            <input
              type="checkbox"
              checked={draft.streaming}
              onChange={(e) => change("streaming", e.target.checked)}
              disabled={!!pending}
            />
            Stream provisional text; expose verified citations after completion.
          </label>
          <details className="byok-advanced">
            <summary>Advanced generation & local limits</summary>
            <div className="settings-field-grid">
              <label>
                Temperature (blank = provider default)
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={draft.temperature ?? ""}
                  onChange={(e) =>
                    change(
                      "temperature",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                  disabled={!temperatureAllowed || !!pending}
                />
                <span className="field-help">
                  {temperatureAllowed
                    ? "Sent only when supported by this adapter/model."
                    : "Not advertised for this model; the provider default is used."}
                </span>
              </label>
              <label>
                Retrieved excerpt budget (UTF-8 bytes)
                <input
                  type="number"
                  min={200}
                  max={32000}
                  value={draft.context_budget_bytes}
                  onChange={(e) =>
                    change("context_budget_bytes", Number(e.target.value))
                  }
                  required
                  disabled={!!pending}
                />
              </label>
              <label>
                Daily request limit
                <input
                  type="number"
                  min={0}
                  max={10000}
                  value={draft.max_calls_per_day}
                  onChange={(e) =>
                    change("max_calls_per_day", Number(e.target.value))
                  }
                  required
                  disabled={!!pending}
                />
              </label>
              <label>
                Request timeout (seconds)
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={draft.timeout_seconds}
                  onChange={(e) =>
                    change("timeout_seconds", Number(e.target.value))
                  }
                  required
                  disabled={!!pending}
                />
              </label>
              <label>
                Monthly local spending warning (USD)
                <input
                  type="number"
                  min={0}
                  max={1000000}
                  step="0.01"
                  value={draft.spending_warning_usd ?? ""}
                  onChange={(e) =>
                    change(
                      "spending_warning_usd",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                  disabled={!!pending}
                />
              </label>
              {draft.provider === "compatible" && (
                <label>
                  Output-limit API parameter
                  <select
                    value={draft.token_parameter}
                    onChange={(e) =>
                      change(
                        "token_parameter",
                        e.target.value as ConfigurationDraft["token_parameter"],
                      )
                    }
                    disabled={!!pending}
                  >
                    <option value="max_tokens">max_tokens</option>
                    <option value="max_completion_tokens">
                      max_completion_tokens
                    </option>
                  </select>
                </label>
              )}
            </div>
            <p className="field-help">
              Context is bounded conservatively before transmission. Local
              request limits and spending warnings do not enforce provider-side
              billing. No retries, paid upgrades or provider fallbacks run
              automatically.
            </p>
          </details>
        </section>
        <section className="settings-card">
          <span className="eyebrow">03 · PRIVACY & CONSENT</span>
          <h2>Know where your evidence goes.</h2>
          {provider?.remote ? (
            <>
              <p className="field-help">
                This provider receives your question, relevant conversation
                context and retrieved document excerpts. It does not receive
                your complete library automatically. Its own retention and
                billing terms apply.
              </p>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={draft.remote_consent}
                  onChange={(e) => change("remote_consent", e.target.checked)}
                  disabled={!!pending}
                />
                I allow relevant evidence and questions to be sent to{" "}
                {provider.name}
                {draft.provider === "compatible" && draft.base_url
                  ? ` (${draft.base_url})`
                  : ""}{" "}
                when I use this configuration.
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={draft.allow_paid}
                  onChange={(e) => change("allow_paid", e.target.checked)}
                  disabled={!!pending}
                />
                I acknowledge provider billing/quota terms, including paid or
                unknown model pricing. Free-tier accounts remain supported.
              </label>
            </>
          ) : (
            <p className="field-help">
              Local inference keeps the grounded prompt on this server.
              Switching models does not change document embeddings or require
              reindexing.
            </p>
          )}
          <div className="settings-footer">
            <span>
              Changes affect new requests. In-flight provider usage may still be
              charged.
            </span>
            <button
              className="button primary"
              type="submit"
              disabled={
                !!pending || (!!apiKey && !catalog.credential_storage.enabled)
              }
            >
              {pending === "save" ? "Saving…" : "Save personal configuration"}
              <Icon name="check" size={15} />
            </button>
          </div>
        </section>
      </form>
      <section className="settings-card">
        <h2>Workspace cloud permission</h2>
        <p className="field-help">
          Workspace owners control whether any member may send excerpts to a
          cloud provider. Your personal consent cannot override this permission.
        </p>
        <label className="check-label">
          <input
            type="checkbox"
            checked={
              cloudPending ?? selection?.workspace_cloud_allowed ?? false
            }
            disabled={!!pending}
            onChange={async (e) => {
              const allowed = e.target.checked;
              setCloudPending(allowed);
              setPending("privacy");
              try {
                await api(`/api/workspaces/${workspaceId}`, {
                  method: "PATCH",
                  body: JSON.stringify({ cloud_opt_in: allowed }),
                });
                await onChanged();
                setNotice("Workspace cloud permission saved.");
              } catch (error) {
                onError(error);
              } finally {
                setCloudPending(null);
                setPending("");
              }
            }}
          />
          Allow cloud excerpt transmission for this workspace
        </label>
      </section>
      {notice && (
        <p className="byok-notice" role="status">
          {notice}
        </p>
      )}
      <section className="settings-card byok-usage">
        <div className="byok-section-heading">
          <div>
            <span className="eyebrow">PRIVATE USAGE</span>
            <h2>Your requests, transparently.</h2>
          </div>
          <button
            className="button secondary"
            disabled={!!pending}
            onClick={() => load().catch(onError)}
          >
            <Icon name="refresh" size={15} />
            Refresh usage
          </button>
        </div>
        <p className="field-help">{usage?.note}</p>
        {usage?.summaries.map((s) => (
          <div
            className={`usage-summary ${s.warning_reached ? "warning" : ""}`}
            key={s.configuration_id}
          >
            <strong>
              {
                catalog.configurations.find((c) => c.id === s.configuration_id)
                  ?.name
              }
            </strong>
            <span>
              ${s.known_cost_usd.toFixed(6)} known this month ·{" "}
              {s.unknown_cost_requests} requests with unknown cost
            </span>
            {s.warning_usd !== null && (
              <span>
                {s.warning_reached ? "Local warning reached" : "Local warning"}:
                ${s.warning_usd.toFixed(2)}
              </span>
            )}
          </div>
        ))}
        {usage?.events.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Provider / model</th>
                  <th>Tokens in / out</th>
                  <th>Latency</th>
                  <th>Cost (USD)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {usage.events.map((e) => (
                  <tr key={e.id}>
                    <td>{new Date(e.created_at).toLocaleString()}</td>
                    <td>
                      {e.provider}
                      <br />
                      {e.model}
                    </td>
                    <td>
                      {e.input_tokens ?? "Unknown"} /{" "}
                      {e.output_tokens ?? "Unknown"}
                      <small>provider reported when present</small>
                    </td>
                    <td>{e.elapsed_ms} ms</td>
                    <td>
                      {e.cost_usd === null
                        ? "Unknown"
                        : `$${e.cost_usd.toFixed(6)}`}
                      <small>
                        {e.cost_source?.replaceAll("_", " ") ?? "Not reported"}
                      </small>
                    </td>
                    <td>{e.status.replaceAll("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="byok-empty">
            No personal-model requests yet. Connection tests do not generate
            answers or populate inference usage.
          </p>
        )}
      </section>
    </div>
  );
}
