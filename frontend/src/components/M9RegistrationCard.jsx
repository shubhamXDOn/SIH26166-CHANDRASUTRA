import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M9 REGISTRATION / IMAGE ALIGNMENT — consumes ONE usable M8 spatial-selection
   artifact (SELECTED / SELECTED_WITH_WARNINGS), estimates and independently
   validates a declared geometric transform (smallest-valid affine preferred,
   homography only on explicit escalation), records residual diagnostics in px
   of the effective matcher plane and produces a derived aligned/warped output.

   The verdicts of M7/M8 are never overridden. Residuals are geometric
   measurements — never a confidence, accuracy or physical-registration claim. */

function stateTone(state) {
  if (state === "SUCCESS") return "ok";
  if (state === "SUCCESS_WITH_WARNINGS" || state === "ABSTAIN") return "warn";
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

const MODEL_OPTIONS = [
  { id: "auto", label: "auto — smallest valid (affine preferred)" },
  { id: "affine", label: "affine — explicit least-squares" },
  { id: "homography", label: "homography — explicit normalized DLT" },
];

export default function M9RegistrationCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [m8Runs, setM8Runs] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [modelChoice, setModelChoice] = useState("auto");
  const [m8Choice, setM8Choice] = useState("auto");

  const latest = runs[0] ?? status?.latest_run ?? null;
  const configId = status?.configured?.configuration_id ?? "RG-M9-001";

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const st = (await apiGet(`/pairs/${pairId}/registration-m9/status`)) ?? null;
        setStatus(st);
      } catch (e) {
        setError(e);
      }
      try {
        const rr = (await apiGet(`/pairs/${pairId}/registration-m9/runs`)) ?? null;
        setRuns(rr?.runs ?? []);
      } catch (e) {
        setError(e);
      }
      try {
        const mr = (await apiGet(`/pairs/${pairId}/spatial-m8/runs`)) ?? null;
        setM8Runs(
          (mr?.runs ?? []).filter((r) =>
            ["SELECTED", "SELECTED_WITH_WARNINGS"].includes(r.state)
          )
        );
      } catch (e) {
        /* the availability of the M8 run picker is optional */
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runRegistration() {
    setBusy(true);
    setError(null);
    try {
      const body = { model: modelChoice };
      if (m8Choice && m8Choice !== "auto") {
        body.m8_run_id = m8Choice;
      }
      const payload = await apiPost(`/pairs/${pairId}/registration-m9/run`, body);
      const dec = payload.decision ?? {};
      const tone = stateTone(dec.state);
      notify({
        title: `Registration · ${dec.state ?? "?"} · ${payload.run_id ?? "?"}`,
        message: dec.explanation ?? "Recorded an M9 registration run.",
        tone: tone === "danger" ? "danger" : tone === "ok" ? "ok" : "warn",
      });
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Registration run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  const m8Options = [
    { id: "auto", label: "auto — latest usable M8 selection" },
    ...m8Runs.map((r) => ({
      id: r.run_id,
      label: `${r.run_id} · ${fmt(r.selected_count)} selected · ${r.state}`,
    })),
  ];

  return (
    <section className="space-y-4">
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">M9 · Registration Chamber</p>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Registration &amp; image alignment · M9 —{" "}
                <span className="font-mono text-teal-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(latest?.state ?? "NOT_RUN")}>
                {latest?.state ?? "NOT_RUN"}
              </Badge>
            </div>
            <p className="mt-1 max-w-2xl text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{configId}</code> · consumes ONE
              usable M8 spatial-selection artifact, estimates and independently validates a declared
              geometric transform, records residual diagnostics in px of the effective matcher plane
              and produces a derived aligned output. The result is a{" "}
              <strong className="text-slate-200">state + geometric measurements</strong>, never a
              confidence, accuracy or physical-registration claim;{" "}
              <code className="font-mono text-slate-300">
                {status?.configured?.reference_status ?? "REFERENCE_UNAVAILABLE"}
              </code>
              . The M7 verdict and M8 status are never overridden.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="input w-52 font-mono text-xs"
              value={modelChoice}
              onChange={(e) => setModelChoice(e.target.value)}
              disabled={busy}
              title="Declared transform model"
            >
              {MODEL_OPTIONS.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              className="input w-64 font-mono text-xs"
              value={m8Choice}
              onChange={(e) => setM8Choice(e.target.value)}
              disabled={busy}
            >
              {m8Options.map((o) => (
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
                  ? "Run an M9 registration over a usable M8 spatial-selection artifact (recorded, never overwritten)"
                  : `Viewer access — ${user?.username ?? "you"} can read registration runs but cannot run them`
              }
              onClick={runRegistration}
            >
              <Icon.Activity className="h-4 w-4" /> {busy ? "Registering…" : "Run registration"}
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
            <span className="font-mono">{status.configured?.model_preference ?? "smallest_valid"}</span>
            <span className="font-mono">
              max rmse {fmt(status.configured?.max_rmse_px)} px · max p95 {fmt(status.configured?.max_p95_px)} px
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
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-wider text-muted">
            Registration runs
          </p>
          <ul className="space-y-1.5">
            {runs.map((r) => (
              <li
                key={r.run_id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.06] bg-space-900/40 px-3 py-2 text-[11px]"
              >
                <span className="font-mono text-slate-200">{r.run_id}</span>
                <Badge tone={stateTone(r.state)}>{r.state}</Badge>
                <span className="text-muted">m8 {r.m8_run_id ?? "—"}</span>
                <span className="text-muted">{r.model_type ?? "—"}</span>
                <span className="text-muted/60">{r.created_at_utc}</span>
                <span className="ml-auto font-mono text-slate-300">
                  {fmt(r.selected_count)} pts · rmse {fmt(r.residual_rmse_px)} px ·{" "}
                  {r.warp_available ? "warped" : "no warp"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="gold">State</Badge>
        <span>— SUCCESS / SUCCESS_WITH_WARNINGS / ABSTAIN / BLOCKED / FAILED.</span>
        <Badge tone="blue">Determinism</Badge>
        <span>— same M8 artifact + model ⇒ same transform + decision hash (no RNG).</span>
        <Badge tone="warn">Boundary</Badge>
        <span>— one usable M8 artifact, affine-first smallest-valid policy, immutable recorded run.</span>
      </div>
    </section>
  );
}

function ResultPanel({ latest, onToggle, expanded }) {
  const [viz, setViz] = useState(null);
  const [vizError, setVizError] = useState(null);

  useEffect(() => {
    if (!expanded || !latest?.run_id) return;
    setVizError(null);
    apiGet(`/registration-m9/runs/${latest.run_id}/visualization`)
      .then((v) => setViz(v))
      .catch((e) => setVizError(e));
  }, [expanded, latest]);

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
        m8 <code className="font-mono text-slate-300">{latest.m8_run_id ?? "—"}</code> ·{" "}
        {latest.model_type ?? "no transform"} ·{" "}
        <code className="font-mono text-slate-300/70">{latest.selection_reason ?? "—"}</code>
      </p>

      {latest.explanation && (
        <p className="mt-2 rounded-lg bg-space-900/40 p-2.5 text-xs leading-relaxed text-slate-300">
          {latest.explanation}
        </p>
      )}

      <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div className="card bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Transform</p>
          <dl className="space-y-1">
            <Readout k="Model" v={latest.model_type ?? "—"} />
            <Readout k="Selection reason" v={latest.selection_reason ?? "—"} />
            <Readout k="Correspondences" v={fmt(latest.selected_count)} />
            <Readout k="Residual RMSE" v={latest.residual_rmse_px == null ? "—" : `${fmt(latest.residual_rmse_px)} px`} />
            <Readout k="Accepted by validation" v={latest.accepted === true ? "yes" : latest.accepted === false ? "no" : "—"} />
          </dl>
        </div>
        <div className="card bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Provenance</p>
          <dl className="space-y-1">
            <Readout k="Configuration" v={latest.configuration_id ?? "—"} />
            <Readout k="Warp" v={latest.warp_available ? "derived output" : "not produced"} />
            <Readout k="Decision hash" v={hashShort(latest.decision_hash)} />
            <Readout k="Runtime" v={latest.runtime_ms == null ? "—" : `${latest.runtime_ms} ms`} />
            <Readout k="Tone" v={latest.tone ?? "—"} />
          </dl>
        </div>
      </div>

      {expanded && latest.warp_available && (
        <div className="mt-3 space-y-2">
          {vizError && <p className="text-xs text-danger">{vizError.message}</p>}
          {viz?.visualizations?.length ? (
            <>
              <p className="text-[10.5px] font-bold uppercase tracking-wider text-muted">
                Derived diagnostics (no physical accuracy claim)
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {viz.visualizations.map((v) => (
                  <figure key={v.name} className="overflow-hidden rounded-lg border border-white/[0.06] bg-space-950">
                    <img
                      src={v.url}
                      alt={v.kind}
                      loading="lazy"
                      className="h-40 w-full bg-space-950 object-contain"
                    />
                    <figcaption className="px-2 py-1.5 font-mono text-[10px] text-muted">
                      {v.name}
                    </figcaption>
                  </figure>
                ))}
              </div>
            </>
          ) : (
            <p className="text-xs text-muted">No derived visualization recorded for this run.</p>
          )}
        </div>
      )}

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