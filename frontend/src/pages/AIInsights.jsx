import { useEffect, useState } from "react";

import { Badge, EmptyState, Icon, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet, apiPost } from "../api.js";

const TASKS = [
  { id: "summarize-experiment", label: "Summarize experiment" },
  { id: "explain-failure", label: "Explain failures / blockers" },
  { id: "explain-routing", label: "Explain matcher routing" },
  { id: "chat", label: "Chat about the pair" },
];

export default function AIInsights() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    apiGet("/ai/status")
      .then((s) => alive && setStatus(s))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <PageSkeleton rows={2} />;

  const configured = status?.configured === true && status?.status === "READY";
  const policy = status?.policy || {};

  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">
          AI Copilot
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          A{" "}
          <strong className="text-slate-200">
            live, evidence-grounded Gemini copilot
          </strong>{" "}
          over the validated Chandrasutra pipeline (M2..M8). Every answer is built from the recorded
          artifact evidence, cross-checked against the canonical metric registry, and never
          fabricated. It explains what the system found; it never authorizes a registration and never
          produces scientific numbers.
        </p>
      </section>

      {/* Service card */}
      {error ? (
        <div className="card p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-danger">
            <Icon.Alert className="h-4 w-4" /> Could not reach the AI service endpoint.
          </p>
          <p className="mt-1 text-xs text-muted">{String(error.message)}</p>
        </div>
      ) : (
        <div className="card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-orbit-500/30 bg-orbit-500/10 text-orbit-300">
                <Icon.Spark className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-bold text-slate-100">{status?.service ?? "AI service"}</p>
                <p className="font-mono text-xs text-muted">
                  {status?.model ?? "—"} · {status?.configuration_id ?? "—"}
                </p>
              </div>
            </div>
            {configured ? (
              <Badge tone="ok">
                <StatusDot state="ok" pulse /> Ready
              </Badge>
            ) : (
              <Badge tone="warn">
                <StatusDot state="warn" /> NOT_CONFIGURED
              </Badge>
            )}
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Policy</p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
                <li>· Explanatory & assistive only</li>
                <li>
                  · Science truth comes from the backend pipeline
                  {policy.core_science_source ? ` (${policy.core_science_source})` : ""}
                </li>
                <li>· Never fabricates — responses are schema-validated</li>
                <li>· Never authorizes a registration</li>
              </ul>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Security</p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
                <li>· API key lives <em>only</em> on the backend</li>
                <li>· Browser never receives or holds the key</li>
                <li>· Full provenance + audit trail on every request</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      <ExplainPanel configured={configured} status={status} />
    </div>
  );
}

function ExplainPanel({ configured, status }) {
  const [pair, setPair] = useState("");
  const [task, setTask] = useState(TASKS[0].id);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  if (!configured) {
    return (
      <div className="card p-5">
        <h3 className="mb-3 text-sm font-bold text-slate-100">Copilot console</h3>
        <div className="rounded-lg border border-dashed border-white/10 bg-space-900/40 p-5">
          <EmptyState
            icon={<Icon.Spark className="h-5 w-5" />}
            title="Copilot is not configured"
            message="Set GEMINI_API_KEY on the backend to arm the copilot. Until then the panel stays honestly empty — no fabricated answers, ever."
            action={
              <Badge tone="neutral">
                Awaiting GEMINI_API_KEY · {status?.status ?? "NOT_CONFIGURED"}
              </Badge>
            }
          />
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Endpoint contract: <code className="font-mono text-slate-300">POST /api/ai/&lt;task&gt;</code>{" "}
          receives a pair id and optional scope/question and returns a structured, verifiable
          explanation with cited evidence milestones and suggested inspections.
        </p>
      </div>
    );
  }

  async function run(event) {
    event.preventDefault();
    setBusy(true);
    setErr(null);
    setResult(null);
    const payload = { pair_id: pair.trim(), question: question.trim() };
    try {
      const body = await apiPost(`/ai/${task}`, payload);
      setResult(body);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5">
      <h3 className="mb-3 text-sm font-bold text-slate-100">Copilot console</h3>
      <form onSubmit={run} className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs font-semibold text-muted">
          Pair id
          <input
            value={pair}
            onChange={(e) => setPair(e.target.value)}
            placeholder="e.g. CS-TEST"
            className="mt-1 w-full rounded-lg border border-white/10 bg-space-900/60 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-muted/50 focus:border-lunar-400/50"
            required
          />
        </label>
        <label className="block text-xs font-semibold text-muted">
          Task
          <select
            value={task}
            onChange={(e) => setTask(e.target.value)}
            className="mt-1 w-full rounded-lg border border-white/10 bg-space-900/60 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-lunar-400/50"
          >
            {TASKS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs font-semibold text-muted sm:col-span-2">
          Question (optional, used and required only for chat)
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Which matcher was routed and why?"
            className="mt-1 w-full rounded-lg border border-white/10 bg-space-900/60 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-muted/50 focus:border-lunar-400/50"
          />
        </label>
        <div className="flex items-center gap-3 sm:col-span-2">
          <button type="submit" disabled={busy} className="btn-primary px-4 py-2 text-sm">
            {busy ? "Working…" : "Run"}
          </button>
          {status?.model && (
            <span className="text-[11px] text-muted">model {status.model}</span>
          )}
        </div>
      </form>

      {err && (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          <p className="flex items-center gap-2 font-semibold">
            <Icon.Alert className="h-4 w-4" /> {err.code || "Request failed"}
          </p>
          <p className="mt-1 text-xs leading-relaxed">{String(err.message)}</p>
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted">
              Answer · {result.task} · {result.request_id}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-100">{result.answer}</p>
          </div>

          {(result.evidence || []).length > 0 && (
            <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Evidence</p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
                {result.evidence.map((e, i) => (
                  <li key={i}>
                    <span className="text-slate-300">· {e.claim}</span>{" "}
                    <span className="font-mono text-[10px]">
                      [src {e.source_milestone} · {e.source_metric}]
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(result.limitations || []).length > 0 && (
            <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Limitations</p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
                {result.limitations.map((l, i) => (
                  <li key={i}>· {l}</li>
                ))}
              </ul>
            </div>
          )}

          {(result.suggested_inspections || []).length > 0 && (
            <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted">
                Suggested inspections
              </p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
                {result.suggested_inspections.map((s, i) => (
                  <li key={i}>· {s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}