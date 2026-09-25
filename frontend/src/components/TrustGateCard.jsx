import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M7 TRUST GATE — deterministic geometric verification of candidate
   correspondences (TG-M7-001).

   Consumes one M3/M4 matcher run artifact (optionally the run the M6 router
   dispatched) and records an ACCEPT / REJECT / ABSTAIN / BLOCKED verdict with
   evidence. The verdict is geometric verification under explicit thresholds —
   never a physical-accuracy, registration-accuracy or confidence claim
   (reference_status stays REFERENCE_UNAVAILABLE). */

function stateTone(state) {
  if (state === "ACCEPT") return "ok";
  if (state === "REJECT") return "danger";
  if (state === "ABSTAIN") return "warn";
  if (state === "BLOCKED") return "neutral";
  return "neutral";
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

export default function TrustGateCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [routingRuns, setRoutingRuns] = useState([]);
  const [baselineRuns, setBaselineRuns] = useState([]);
  const [deepRuns, setDeepRuns] = useState([]);
  const [matcherRunId, setMatcherRunId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const latest = runs[0] ?? status?.latest_run ?? null;
  const configId = status?.configured?.configuration_id ?? "TG-M7-001";

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const st = (await apiGet(`/pairs/${pairId}/trust/status`)) ?? null;
        setStatus(st);
      } catch (e) {
        setError(e);
      }
      try {
        const rr = (await apiGet(`/pairs/${pairId}/trust/runs`)) ?? null;
        setRuns(rr?.runs ?? []);
      } catch (e) {
        setError(e);
      }
      try {
        const rt = (await apiGet(`/pairs/${pairId}/routing/runs`)) ?? null;
        setRoutingRuns(rt?.runs ?? []);
      } catch (e) {
        /* optional provenance source */
      }
      try {
        const bl = (await apiGet(`/matching/${pairId}/baseline/runs`)) ?? null;
        setBaselineRuns(bl?.runs ?? []);
      } catch (e) {
        /* optional matcher-run picker */
      }
      try {
        const dp = (await apiGet(`/matching/${pairId}/deep/runs`)) ?? null;
        setDeepRuns(dp?.runs ?? []);
      } catch (e) {
        /* optional matcher-run picker */
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runTrust() {
    setBusy(true);
    setError(null);
    try {
      const body = {};
      if (matcherRunId && matcherRunId !== "auto") body.matcher_run_id = matcherRunId;
      const payload = await apiPost(`/pairs/${pairId}/trust/run`, body);
      const dec = payload.decision ?? {};
      const tone = stateTone(dec.state);
      notify({
        title: `Trust Gate · ${dec.state ?? "?"} · ${payload.run_id ?? "?"}`,
        message: dec.explanation ?? "Recorded an M7 trust decision.",
        tone: tone === "danger" ? "danger" : tone === "ok" ? "ok" : "warn",
      });
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Trust Gate run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  const matcherOptions = [
    { id: "auto", label: "auto — latest matcher run (incl. M6 routing)" },
    ...baselineRuns.map((r) => ({
      id: r.run_id,
      label: `${r.matcher_id} · ${r.run_id} · ${fmt(r.counts?.candidates ?? 0)} cand`,
    })),
    ...deepRuns.map((r) => ({
      id: r.run_id,
      label: `${r.matcher_id} · ${r.run_id} · ${fmt(r.counts?.candidates ?? 0)} cand`,
    })),
  ];

  return (
    <section className="space-y-4">
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">M7 · Verification Instrument</p>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Trust Gate · M7 — <span className="font-mono text-teal-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(latest?.state ?? "NOT_RUN")}>
                {latest?.state ?? "NOT_RUN"}
              </Badge>
            </div>
            <p className="mt-1 max-w-2xl text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{configId}</code> · deterministic geometric
              verification of candidate correspondences. The verdict is a <strong className="text-slate-200">gate
              state</strong>, never a confidence or accuracy claim;{" "}
              <code className="font-mono text-slate-300">{status?.configured?.reference_status ?? "REFERENCE_UNAVAILABLE"}</code>.
              No spatial selection (M8) and no registration (M9) semantics.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="input w-56 font-mono text-xs"
              value={matcherRunId || "auto"}
              onChange={(e) => setMatcherRunId(e.target.value)}
              disabled={busy}
            >
              {matcherOptions.map((o) => (
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
                  ? "Run the M7 trust gate over a matcher run artifact (recorded, never overwritten)"
                  : `Viewer access — ${user?.username ?? "you"} can read verdicts but cannot run the trust gate`
              }
              onClick={runTrust}
            >
              <Icon.Activity className="h-4 w-4" /> {busy ? "Verifying…" : "Run trust gate"}
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
            <span className="font-mono">{status.configured?.preferred_model ?? "affine"}-first</span>
            <span className="font-mono">{status.configured?.min_inliers ?? "?"} min inliers</span>
            <span className="font-mono">ratio ≥ {fmt(status.configured?.min_inlier_ratio ?? 0.3)}</span>
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
        <VerdictPanel latest={latest} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
      )}

      {runs.length > 0 && (
        <div className="card p-4">
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-wider text-muted">Trust runs</p>
          <ul className="space-y-1.5">
            {runs.map((r) => (
              <li key={r.run_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.06] bg-space-900/40 px-3 py-2 text-[11px]">
                <span className="font-mono text-slate-200">{r.run_id}</span>
                <Badge tone={stateTone(r.state)}>{r.state}</Badge>
                <span className="font-mono text-slate-300">{r.matcher_id ?? "—"}</span>
                <span className="text-muted">{r.model_type ?? "—"}</span>
                <span className="text-muted/60">{r.created_at_utc}</span>
                <span className="ml-auto font-mono text-slate-300">
                  {fmt(r.inlier_count)}/{fmt(r.candidate_count)} inliers · {fmt(r.inlier_ratio)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="gold">State</Badge>
        <span>— ACCEPT / REJECT / ABSTAIN / BLOCKED, never numeric confidence.</span>
        <Badge tone="blue">Determinism</Badge>
        <span>— same matcher artifact ⇒ same decision hash.</span>
        <Badge tone="warn">Reference</Badge>
        <span>— no physical/registration accuracy claim is made.</span>
      </div>
    </section>
  );
}

function VerdictPanel({ latest, onToggle, expanded }) {
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={stateTone(latest.state)}>{latest.state ?? "—"}</Badge>
          {latest.model_type && <Badge tone="neutral">model {latest.model_type}</Badge>}
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
        matcher <code className="font-mono text-slate-300">{latest.matcher_id ?? "—"}</code>{" "}
        <code className="font-mono text-slate-300/70">{latest.matcher_run_id ?? "—"}</code>
        {latest.routing_mode ? (
          <>
            {" "}· routed via <code className="font-mono text-slate-300">{latest.routing_mode}</code>{" "}
            <code className="font-mono text-slate-300/70">{latest.routing_run_id}</code>
          </>
        ) : null}
      </p>

      {latest.explanation && (
        <p className="mt-2 rounded-lg bg-space-900/40 p-2.5 text-xs leading-relaxed text-slate-300">
          {latest.explanation}
        </p>
      )}

      <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div className="card bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Verification</p>
          <dl className="space-y-1">
            <Readout k="Candidates" v={fmt(latest.candidate_count)} />
            <Readout k="Verified" v={fmt(latest.verified_count)} />
            <Readout k="Inliers" v={fmt(latest.inlier_count)} />
            <Readout k="Inlier ratio" v={fmt(latest.inlier_ratio)} />
            <Readout k="Model" v={latest.model_type ?? "—"} />
            <Readout k="Decision hash" v={hashShort(latest.decision_hash)} />
          </dl>
        </div>
        <div className="card bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Provenance</p>
          <dl className="space-y-1">
            <Readout k="Matcher run" v={latest.matcher_run_id ?? "—"} />
            <Readout k="Routing mode" v={latest.routing_mode ?? "—"} />
            <Readout k="Routing run" v={latest.routing_run_id ?? "—"} />
            <Readout k="Synthetic" v={latest.synthetically_derived ? "yes" : "no"} />
            <Readout k="Experiment" v={latest.experiment_id ?? "—"} />
            <Readout k="Runtime" v={latest.runtime_ms == null ? "—" : `${latest.runtime_ms} ms`} />
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