import { useEffect, useState } from "react";

import { Badge, EmptyState, Icon, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet } from "../api.js";

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

  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">
          AI insights
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          An <strong className="text-slate-200">explanatory</strong> layer around the scientific
          pipeline. It explains what the system found; it never authorizes a registration and never
          produces scientific numbers. In M1 — with real data registered but matching not yet run —
          there is nothing for the AI to explain, so the panel stays honestly empty.
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
                <p className="font-mono text-xs text-muted">{status?.model ?? "—"}</p>
              </div>
            </div>
            {status?.status === "READY" ? (
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
                <li>· Science truth comes from the backend pipeline</li>
                <li>· No fabricated AI responses — ever</li>
              </ul>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-space-900/50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Security</p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
                <li>· API key lives <em>only</em> on the backend</li>
                <li>· Browser never receives or holds the key</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Explanation panel placeholder */}
      <div className="card p-5">
        <h3 className="mb-3 text-sm font-bold text-slate-100">Explanation panel</h3>
        <div className="rounded-lg border border-dashed border-white/10 bg-space-900/40 p-5">
          <EmptyState
            icon={<Icon.Spark className="h-5 w-5" />}
            title="No explanation available"
            message="Explanations are generated only for real, validated pair artifacts once matching runs (M2+) and a Gemini passphrase key is configured. Nothing is prewritten."
            action={
              <Badge tone="neutral">
                Awaiting real results + Gemini configuration
              </Badge>
            }
          />
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Endpoint contract: <code className="font-mono text-slate-300">POST /api/ai/explain</code>{" "}
          receives application context and returns a structured, verifiable explanation. With no key
          configured the service reports{" "}
          <code className="font-mono text-warn">NOT_CONFIGURED</code> cleanly and the application
          keeps running.
        </p>
      </div>
    </div>
  );
}