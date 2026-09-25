import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M10 METRICS & BENCHMARK — descriptive funnel, variant/ablation comparison
   and FT-M10-001 failure taxonomy over settled M3..M9 artefacts.

   The M10 controller is a READER: every number is a measurement of artefacts
   already on disk. V5/V6 are offline ablations whose downstream stages stay
   NOT_RUN/BLOCKED. Reference status is REFERENCE_UNAVAILABLE in this build so
   no accuracy/geolocation/winner claim is ever emitted (no_claim: true). */

function fmt(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (typeof v === "object") return fmt(v.median ?? v.mean ?? v.count ?? v.diff);
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(3);
  }
  return String(v);
}

function stateTone(state) {
  if (state === "COMPLETE") return "ok";
  if (state === "ABSTAIN") return "warn";
  if (state === "BLOCKED") return "neutral";
  return "danger";
}

export default function M10MetricsBenchmarkCard({ notify }) {
  const { canMutate } = useAuth();
  const [overview, setOverview] = useState(null);
  const [variants, setVariants] = useState([]);
  const [runs, setRuns] = useState([]);
  const [analyze, setAnalyze] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pairId, setPairId] = useState("");
  const [variantId, setVariantId] = useState("V4");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const [ov, vv, rr, aa] = await Promise.all([
          apiGet("/metrics-m10/overview"),
          apiGet("/metrics-m10/variants"),
          apiGet("/metrics-m10/runs"),
          apiGet("/metrics-m10/analyze"),
        ]);
        setOverview(ov);
        setVariants(vv.variants ?? []);
        setRuns(rr.runs ?? []);
        setAnalyze(aa);
      } catch (e) {
        setError(e);
      }
    },
    []
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadFailure() {
    setError(null);
    try {
      setFailure(await apiGet("/metrics-m10/failure-analysis"));
    } catch (e) {
      setError(e);
    }
  }

  async function runBenchmark() {
    if (!pairId) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost("/metrics-m10/runs", { pair_id: pairId, variant_id: variantId });
      await load();
      notify({ title: "M10 benchmark run recorded", message: `observational run for ${pairId} · ${variantId}` });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const sum = analyze?.summary?.metrics ?? {};
  const ref = overview?.reference_status?.value ?? "REFERENCE_UNAVAILABLE";
  const tuned = overview?.scientifically_tuned;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-slate-100">Metrics &amp; benchmark · M10</h3>
          <p className="text-xs text-muted">
            Descriptive funnel, variant/ablation comparison and FT-M10-001 failure taxonomy over
            settled M3..M9 artefacts. Read-only: the controller never re-runs matcher/trust/spatial/
            registration logic and never emits an accuracy/geolocation/winner claim.
          </p>
        </div>
        <Badge tone="gold">MET-M10-001 config</Badge>
      </div>

      {error && <p className="text-xs text-danger">{String(error)}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* reference + variants */}
        <div className="card space-y-3 p-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-200">Reference status</p>
            <Badge tone={ref === "REFERENCE_UNAVAILABLE" ? "warn" : "ok"}>{ref}</Badge>
          </div>
          <p className="text-[11px] leading-relaxed text-muted">
            {tuned === false
              ? "Engineering-only configuration; no calibrated thresholds, no winner verdict."
              : ""}
          </p>
          <div className="space-y-1.5">
            {variants.map((v) => (
              <div key={v.id} className="rounded-lg border border-white/[0.06] bg-space-900/40 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-[11px] font-semibold text-slate-200">
                    {v.id} <span className="text-muted">·</span> {v.name}
                  </p>
                  {v.is_ablation || v.trust_gate === "DISABLED_FOR_ABLATION" || v.spatial_selection === "DISABLED_FOR_ABLATION" ? (
                    <Badge tone="neutral">ablation</Badge>
                  ) : (
                    <Badge tone="blue">{v.routing}</Badge>
                  )}
                </div>
                <p className="mt-1 text-[10px] leading-snug text-muted">
                  trust · {v.trust_gate} — spatial · {v.spatial_selection}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* observational run + registry */}
        <div className="card space-y-3 p-4">
          <p className="text-xs font-semibold text-slate-200">Observational benchmark run</p>
          <div className="flex gap-2">
            <input
              value={pairId}
              onChange={(e) => setPairId(e.target.value)}
              placeholder="pair id (e.g. CS-P001)"
              className="w-full rounded-lg border border-white/10 bg-space-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-lunar-400/50"
            />
          </div>
          <div className="flex items-center gap-2">
            <select
              value={variantId}
              onChange={(e) => setVariantId(e.target.value)}
              className="flex-1 rounded-lg border border-white/10 bg-space-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-lunar-400/50"
            >
              {variants.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id} — {v.name}
                </option>
              ))}
            </select>
            <button
              onClick={runBenchmark}
              disabled={busy || !pairId || !canMutate()}
              className="rounded-lg bg-lunar-400 px-4 py-2 text-xs font-semibold text-space-950 transition hover:bg-lunar-300 disabled:opacity-40"
            >
              {busy ? "recording…" : "Record observation"}
            </button>
          </div>
          <div className="max-h-64 space-y-1.5 overflow-auto">
            {runs.length === 0 && <p className="text-[11px] text-muted">No benchmark runs recorded yet.</p>}
            {runs.map((r) => (
              <div key={r.run_id} className="flex items-center justify-between rounded-lg border border-white/[0.06] bg-space-900/40 px-2.5 py-1.5">
                <div>
                  <p className="font-mono text-[10px] text-slate-300">
                    {r.pair_id} · {r.variant_id}
                  </p>
                  <p className="text-[9.5px] text-muted">{r.run_id} · {r.created_at}</p>
                </div>
                <Badge tone={stateTone(r.state)}>{r.state}</Badge>
              </div>
            ))}
          </div>
          <button onClick={loadFailure} className="text-left text-[11px] font-medium text-lunar-300 hover:text-lunar-200">
            Load failure taxonomy breakdown →
          </button>
          {failure && (
            <div className="rounded-lg border border-white/[0.06] bg-space-900/40 p-2.5 text-[11px]">
              <p className="text-slate-300">
                failed: {failure.counts?.failed} · abstain: {failure.counts?.abstain}
              </p>
              <Badge tone="warn">no winner · descriptive only</Badge>
            </div>
          )}
        </div>

        {/* descriptive summary */}
        <div className="card space-y-3 p-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-200">Descriptive summary</p>
            <Badge tone="neutral">median-preferred</Badge>
          </div>
          {Object.entries(sum).map(([key, v]) => (
            <div key={key} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="font-mono text-muted">{key}</span>
              <span className="font-medium text-slate-200">
                {v == null ? "—" : (
                  <span>
                    median {fmt(v?.median)} · mean {fmt(v?.mean)} · p95 {fmt(v?.p95)}
                  </span>
                )}
              </span>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Icon.Chart className="h-3.5 w-3.5 text-lunar-300" />
            <p className="text-[10.5px] text-muted">no_claim · reference {ref}</p>
          </div>
        </div>
      </div>
    </section>
  );
}