import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M8 SPATIAL SELECTION — deterministic GRID_BALANCED correspondence selection
   over the M7 trusted set (SR-M8-001).

   Consumes one ACCEPTED M7 trust gate artifact (explicit run or the latest
   ACCEPT run for the pair), recovers the trusted correspondences by
   deterministic re-verification, computes per-side spatial bookkeeping
   evidence and records the selection. The M7 verdict is never overridden and
   the status is a state — never a confidence or registration claim. */

function stateTone(state) {
  if (state === "SELECTED") return "ok";
  if (state === "SELECTED_WITH_WARNINGS" || state === "ABSTAIN") return "warn";
  if (state === "BLOCKED") return "neutral";
  return "danger";
}

function fmt(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(4);
  }
  return String(v);
}

function hashShort(h) {
  if (!h) return "—";
  return `${h.slice(0, 10)}…${h.slice(-6)}`;
}

export default function M8SpatialReliabilityCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [trustRuns, setTrustRuns] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [trustRunChoice, setTrustRunChoice] = useState("auto");

  const latest = runs[0] ?? status?.latest_run ?? null;
  const configId = status?.configured?.configuration_id ?? "SR-M8-001";

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const st = (await apiGet(`/pairs/${pairId}/spatial-m8/status`)) ?? null;
        setStatus(st);
      } catch (e) {
        setError(e);
      }
      try {
        const rr = (await apiGet(`/pairs/${pairId}/spatial-m8/runs`)) ?? null;
        setRuns(rr?.runs ?? []);
      } catch (e) {
        setError(e);
      }
      try {
        const tr = (await apiGet(`/pairs/${pairId}/trust/runs`)) ?? null;
        setTrustRuns(tr?.runs ?? []);
      } catch (e) {
        /* trust run source is optional */
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runSpatial() {
    setBusy(true);
    setError(null);
    try {
      const body = {};
      if (trustRunChoice && trustRunChoice !== "auto") {
        body.trust_run_id = trustRunChoice;
      }
      const payload = await apiPost(`/pairs/${pairId}/spatial-m8/run`, body);
      const dec = payload.decision ?? {};
      const tone = stateTone(dec.state);
      notify({
        title: `Spatial selection · ${dec.state ?? "?"} · ${payload.run_id ?? "?"}`,
        message: dec.explanation ?? "Recorded an M8 spatial selection.",
        tone: tone === "danger" ? "danger" : tone === "ok" ? "ok" : "warn",
      });
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Spatial selection run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  const acceptRuns = trustRuns.filter((r) => r.state === "ACCEPT");

  const trustOptions = [
    { id: "auto", label: "auto — latest ACCEPT trust run" },
    ...acceptRuns.map((r) => ({
      id: r.run_id,
      label: `${r.run_id} · ${fmt(r.inlier_count)} inliers · ${r.matcher_id ?? "—"}`,
    })),
  ];

  return (
    <section className="space-y-4">
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">M8 · Spatial Selection Instrument</p>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Spatial selection · M8 — <span className="font-mono text-teal-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(latest?.state ?? "NOT_RUN")}>
                {latest?.state ?? "NOT_RUN"}
              </Badge>
            </div>
            <p className="mt-1 max-w-2xl text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{configId}</code> · deterministic
              GRID_BALANCED selection over the M7 trusted set. The result is a{" "}
              <strong className="text-slate-200">state + spatial bookkeeping evidence</strong>, never a
              confidence or accuracy claim;{" "}
              <code className="font-mono text-slate-300">{status?.configured?.reference_status ?? "REFERENCE_UNAVAILABLE"}</code>.
              The M7 verdict is never overridden.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="input w-64 font-mono text-xs"
              value={trustRunChoice}
              onChange={(e) => setTrustRunChoice(e.target.value)}
              disabled={busy}
            >
              {trustOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              className="btn-primary"
              disabled={busy || !canMutate}
              title={
                canMutate
                  ? "Run M8 spatial selection over an ACCEPTED M7 trust run (recorded, never overwritten)"
                  : `Viewer access — ${user?.username ?? "you"} can read selections but cannot run the spatial selection`
              }
              onClick={runSpatial}
            >
              <Icon.Activity className="h-4 w-4" /> {busy ? "Selecting…" : "Run spatial selection"}
            </button>
          </div>
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}

        {status && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted">
            <Badge tone="neutral">{configId}</Badge>
            <span className="font-mono">{status.configured?.policy ?? "GRID_BALANCED"}</span>
            <span className="font-mono">
              grid {status.configured?.grid_rows ?? 8}×{status.configured?.grid_cols ?? 8}
            </span>
            <span className="font-mono">
              max {status.configured?.max_selected ?? "?"} selected
            </span>
            <span className={`font-mono ${status.synthetically_derived ? "text-warn" : "text-ok"}`}>
              {status.synthetically_derived ? "synthetic fixture" : "real-data gate"}
            </span>
            <span className="font-mono">
              {status.source_class_a} / {status.source_class_b}
            </span>
          </div>
        )}

        {latest?.state === "BLOCKED" && (
          <div className="mt-3 rounded-lg border border-white/[0.08] bg-space-900/40 p-3">
            <p className="flex items-center gap-2 text-xs font-bold text-slate-200">
              <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {latest.block_code}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              {latest.reason_codes?.join(", ") ?? latest.block_code}
            </p>
          </div>
        )}
      </div>

      {latest && (
        <ResultPanel latest={latest} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
      )}

      {runs.length > 0 && (
        <div className="card p-4">
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-wider text-muted">Spatial runs</p>
          <ul className="space-y-1.5">
            {runs.map((r) => (
              <li key={r.run_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.06] bg-space-900/40 px-3 py-2 text-[11px]">
                <span className="font-mono text-slate-200">{r.run_id}</span>
                <Badge tone={stateTone(r.state)}>{r.state}</Badge>
                <span className="text-muted">trust {r.trust_run_id}</span>
                <span className="text-muted/60">{r.created_at_utc}</span>
                <span className="ml-auto font-mono text-slate-300">
                  {fmt(r.selected_count)}/{fmt(r.trusted_count)} selected · src {fmt(r.source_coverage_ratio)} · tgt {fmt(r.target_coverage_ratio)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="gold">State</Badge>
        <span>— SELECTED / SELECTED_WITH_WARNINGS / ABSTAIN / BLOCKED / FAILED.</span>
        <Badge tone="blue">Determinism</Badge>
        <span>— same M7 artifact ⇒ same selection + decision hash.</span>
        <Badge tone="warn">Boundary</Badge>
        <span>— trusted set is always a subset of the M7 inliers; never re-decided.</span>
      </div>
    </section>
  );
}

function ResultPanel({ latest, onToggle, expanded }) {
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={stateTone(latest.state)}>{latest.state ?? "—"}</Badge>
          {latest.reason_codes?.map((code) => (
            <Badge key={code} tone="neutral">{code}</Badge>
          ))}
          {latest.block_code && <Badge tone="warn">block {latest.block_code}</Badge>}
          {latest.abstain_code && <Badge tone="warn">abstain {latest.abstain_code}</Badge>}
        </div>
        <button className="btn-ghost" onClick={onToggle}>
          {expanded ? "Hide details" : "Details"}
        </button>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        run <code className="font-mono text-slate-300">{latest.run_id}</code> · {latest.created_at_utc} ·
        trust <code className="font-mono text-slate-300">{latest.trust_run_id ?? "—"}</code> ·
        matcher <code className="font-mono text-slate-300/70">{latest.matcher_id ?? "—"}</code>{" "}
        <code className="font-mono text-slate-300/70">{latest.matcher_run_id ?? "—"}</code>
      </p>

      {latest.explanation && (
        <p className="mt-2 rounded-lg bg-space-900/40 p-2.5 text-xs leading-relaxed text-slate-300">
          {latest.explanation}
        </p>
      )}

      <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div className="card bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Selection</p>
          <dl className="space-y-1">
            <Readout k="Trusted (recovered)" v={fmt(latest.trusted_count)} />
            <Readout k="Selected" v={fmt(latest.selected_count)} />
            <Readout k="Excluded" v={fmt(latest.excluded_count)} />
            <Readout k="Limit applied" v={latest.limit_applied ? "yes" : "no"} />
            <Readout k="Decision hash" v={hashShort(latest.decision_hash)} />
          </dl>
        </div>
        <div className="card bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Spatial coverage</p>
          <dl className="space-y-1">
            <Readout k="Source coverage" v={fmt(latest.source_coverage_ratio)} />
            <Readout k="Target coverage" v={fmt(latest.target_coverage_ratio)} />
            <Readout k="Configuration" v={latest.configuration_id ?? "—"} />
            <Readout k="Runtime" v={latest.runtime_ms == null ? "—" : `${latest.runtime_ms} ms`} />
            <Readout k="Tone" v={latest.tone ?? "—"} />
          </dl>
        </div>
      </div>

      {expanded && (
        <details className="mt-3" open>
          <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-wider text-muted">
            Full evidence record
          </summary>
          <pre className="mt-2 max-h-[420px] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(latest, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function Readout({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}