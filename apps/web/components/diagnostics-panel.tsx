"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { GenerationPolicy } from "./release-controls";

type Job = {
  id: string;
  document_id: string;
  kind: string;
  status: string;
  attempts: number;
  error: string | null;
};
type Metrics = {
  request_sample_count: number;
  p50_ms: number | null;
  p95_ms: number | null;
  errors: Record<string, number>;
  queue_depth: number;
  rss_bytes: number | null;
  cpu_seconds: number | null;
  retention_days: number;
  jobs: Job[];
  usage: {
    id: string;
    provider: string;
    model: string;
    status: string;
    elapsed_ms: number;
    input_tokens: number;
    output_tokens: number;
    token_source: string;
  }[];
  cost_note: string;
  sync_runs: {
    id: string;
    vault_id: string;
    status: string;
    error: string | null;
  }[];
};
type Compare = {
  same_evidence_chunk_ids: string[];
  note: string;
  answers: {
    provider: string;
    model: string;
    answer?: string;
    unavailable?: boolean;
    detail?: string;
    elapsed_ms?: number;
    citations?: { title: string; excerpt: string; citation_id: string }[];
  }[];
};
const help = [
  [
    "Start without a key",
    "Use the included PDF/Markdown/vault sample from examples/evaluation. Offline demo quotes stored passages and verifies citation links; it is not an intelligent local LLM.",
  ],
  [
    "Connect a folder",
    "Run scripts/vault_sync.py with --root and --workspace, then reuse the printed --vault-id. Stop the process to disconnect. Only the explicitly selected root is scanned. Server mode adds --username and prompts for a password. ZIP imports are manual snapshots.",
  ],
  [
    "Use a remote provider",
    "Choose a workspace provider/model in Settings, configure the matching server environment key, enable workspace cloud permission and confirm the exact destination. Optional paid providers require separate permission. No fallback or automatic retry occurs.",
  ],
  [
    "Citations and unsupported questions",
    "Open a numbered citation to inspect the stored source. An available source verifies identity, not whether every model claim follows from it. Changed/deleted sources are explicitly unavailable. Retrieval hits alone are not proof that a question is answerable.",
  ],
  [
    "Backup and recovery",
    "Stop the API and run python -m nexus.backup backup --data data --output backups/nexus.zip with PYTHONPATH=apps/api. Restore into a new directory with the restore subcommand. Read docs/BACKUP_RESTORE.md. Backups contain private documents and password hashes; protect them.",
  ],
  [
    "Low memory / model errors",
    "Keep one worker and the Free/CPU profile. Hash embeddings need no weights but do not understand semantics. Cached ONNX is about 23 MB; installations need several GB free. Cross-encoder, OCR and Ollama are optional. Failed indexes preserve the previous ready index.",
  ],
];

export function DiagnosticsPanel({
  workspaceId,
  onError,
}: {
  workspaceId: string;
  onError: (cause: unknown) => void;
}) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [reviews, setReviews] = useState<
    {
      id: string;
      message_id: string;
      chat_id?: string;
      rating: string;
      comment: string;
    }[]
  >([]);
  const [query, setQuery] = useState("");
  const [question, setQuestion] = useState("");
  const [comparison, setComparison] = useState<Compare | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(
    () => api<Metrics>(`/api/workspaces/${workspaceId}/diagnostics`),
    [workspaceId],
  );
  useEffect(() => {
    let active = true;
    load()
      .then((value) => {
        if (active) setMetrics(value);
      })
      .catch(onError);
    return () => {
      active = false;
    };
  }, [load, onError]);
  async function action(path: string) {
    setBusy(true);
    try {
      await api(path, { method: "POST" });
      setMetrics(await load());
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-content diagnostics-content">
      <span className="eyebrow">LOCAL OPERATIONS</span>
      <h1>Understand your workspace.</h1>
      <p>
        Scoped request timings, jobs and model usage. Prompts, excerpts and
        secrets are excluded from telemetry. No external analytics service is
        used.
      </p>
      <section className="settings-card">
        <div className="card-heading">
          <h2>Diagnostics</h2>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => load().then(setMetrics).catch(onError)}
          >
            Refresh diagnostics
          </button>
        </div>
        {metrics ? (
          <>
            <div className="metrics-grid">
              <p>
                <strong>{metrics.request_sample_count}</strong>request samples
              </p>
              <p>
                <strong>
                  {metrics.p50_ms ?? "—"} / {metrics.p95_ms ?? "—"} ms
                </strong>
                p50 / p95 request latency
              </p>
              <p>
                <strong>{metrics.queue_depth}</strong>queued / processing jobs
              </p>
              <p>
                <strong>
                  {metrics.rss_bytes
                    ? (metrics.rss_bytes / 1024 / 1024).toFixed(1) + " MB"
                    : "admin only / unavailable"}
                </strong>
                API process resident memory
              </p>
            </div>
            <p>
              Errors:{" "}
              {Object.entries(metrics.errors)
                .map(([code, count]) => `${code}: ${count}`)
                .join(" · ") || "none in sample"}
              . Retention: {metrics.retention_days} days. First-token timing
              unavailable: responses are verified before display.
            </p>
            <p className="field-help">
              {metrics.cost_note} Usage below includes attempts and may include
              quota failures. Estimated tokens use UTF-8 bytes ÷ 4;
              provider-reported usage is labeled separately.
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Provider / model</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Input / output tokens</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.usage.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.provider}
                        <br />
                        {row.model}
                      </td>
                      <td>{row.status}</td>
                      <td>{row.elapsed_ms} ms</td>
                      <td>
                        {row.input_tokens} / {row.output_tokens}
                      </td>
                      <td>{row.token_source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              className="text-button"
              onClick={async () => {
                try {
                  await api(`/api/workspaces/${workspaceId}/diagnostics`, {
                    method: "DELETE",
                  });
                  setMetrics(await load());
                } catch (cause) {
                  onError(cause);
                }
              }}
            >
              Clear retained diagnostics (today&apos;s budget counters remain)
            </button>
          </>
        ) : (
          <p role="status">Loading diagnostics…</p>
        )}
      </section>
      <section className="settings-card">
        <h2>Recoverable jobs</h2>
        <p>
          Retry is bounded to three attempts per job. Cancellation applies to
          queued ingestion; deletion cleanup must finish. Completed partial sync
          notes remain current.
        </p>
        {metrics?.jobs.length ? (
          metrics.jobs.map((job) => (
            <div className="job-row" key={job.id}>
              <div>
                <strong>
                  {job.kind} · {job.status}
                </strong>
                <p className="field-help">
                  {job.id} · attempts {job.attempts}
                </p>
                {job.error && <p className="document-error">{job.error}</p>}
              </div>
              {["failed", "cancelled", "needs_ocr"].includes(job.status) && (
                <button
                  className="button secondary"
                  disabled={busy || job.attempts >= 3}
                  onClick={() =>
                    action(
                      `/api/jobs/${job.id}/retry?workspace_id=${workspaceId}`,
                    )
                  }
                >
                  Retry job
                </button>
              )}
              {job.status === "queued" && job.kind === "index" && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    action(
                      `/api/jobs/${job.id}/cancel?workspace_id=${workspaceId}`,
                    )
                  }
                >
                  Cancel queued job
                </button>
              )}
            </div>
          ))
        ) : (
          <p>No ingestion jobs yet.</p>
        )}
        {metrics?.sync_runs
          .filter((run) => ["queued", "processing"].includes(run.status))
          .map((run) => (
            <button
              key={run.id}
              className="button secondary"
              disabled={busy}
              onClick={() =>
                action(
                  `/api/vaults/${run.vault_id}/cancel?workspace_id=${workspaceId}`,
                )
              }
            >
              Cancel sync {run.id.slice(0, 8)}
            </button>
          ))}
      </section>
      <section className="settings-card">
        <h2>Compare the same evidence</h2>
        <p>
          Run the offline extractive baseline beside your saved workspace
          provider on identical passages. The selected provider receives
          excerpts only under its existing consent/budget policy. Each permitted
          call counts toward the daily cap.
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            try {
              const policy = await api<GenerationPolicy>(
                `/api/workspaces/${workspaceId}/route-policy`,
              );
              const mock = {
                ...policy,
                provider: "mock",
                model: "extractive-demo",
                preset: "free-cpu",
                consent_destination: "",
                allow_paid: false,
              };
              setComparison(
                await api<Compare>(`/api/workspaces/${workspaceId}/compare`, {
                  method: "POST",
                  body: JSON.stringify({ question, policies: [mock, policy] }),
                }),
              );
              setMetrics(await load());
            } catch (cause) {
              onError(cause);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Comparison question
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              required
              maxLength={4000}
            />
          </label>
          <button
            className="button secondary"
            disabled={busy || !question.trim()}
          >
            {busy ? "Comparing…" : "Compare saved provider with demo"}
          </button>
        </form>
        {comparison && (
          <>
            <p>{comparison.note}</p>
            <p className="field-help">
              {comparison.same_evidence_chunk_ids.length} identical evidence
              chunks
            </p>
            <div className="comparison-grid">
              {comparison.answers.map((answer, index) => (
                <article key={index}>
                  <h3>
                    {answer.provider} · {answer.model}
                  </h3>
                  {answer.unavailable ? (
                    <p role="status">Unavailable: {answer.detail}</p>
                  ) : (
                    <>
                      <p>{answer.elapsed_ms} ms</p>
                      <pre className="comparison-answer">{answer.answer}</pre>
                      <p>
                        {answer.citations?.length || 0} verified citation IDs.
                        Cost unknown.
                      </p>
                    </>
                  )}
                </article>
              ))}
            </div>
          </>
        )}
      </section>
      <section className="settings-card">
        <h2>Private review queue</h2>
        <p>
          Feedback stays in this workspace; opening the saved chat lets you
          inspect the exact answer and source. No external evaluator is called.
        </p>
        <button
          className="button secondary"
          onClick={() =>
            api<typeof reviews>(`/api/workspaces/${workspaceId}/reviews`)
              .then(setReviews)
              .catch(onError)
          }
        >
          Load feedback reviews
        </button>
        {reviews.map((review) => (
          <p key={review.id}>
            {review.rating.replaceAll("_", " ")} · message {review.message_id}{" "}
            {review.comment}
            {review.chat_id && (
              <Link href={`/?chat=${encodeURIComponent(review.chat_id)}`}>
                Open saved answer ↗
              </Link>
            )}
          </p>
        ))}
      </section>
      <section className="settings-card">
        <h2>Help & onboarding</h2>
        <label>
          Search help
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Try backup, key, folder or citation"
          />
        </label>
        {help
          .filter((item) =>
            item.join(" ").toLowerCase().includes(query.toLowerCase()),
          )
          .map(([title, text]) => (
            <details key={title}>
              <summary>{title}</summary>
              <p>{text}</p>
            </details>
          ))}
      </section>
    </div>
  );
}
