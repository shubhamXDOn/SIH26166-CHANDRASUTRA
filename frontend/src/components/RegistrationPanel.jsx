import { useEffect, useMemo, useState } from "react";

import { Badge, Icon, Modal } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

function stateTone(state) {
  if (state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED" || state === "INSUFFICIENT") return "warn";
  return "neutral";
}

function verdictTone(v) {
  if (v === "PASS") return "ok";
  if (v === "FAIL") return "danger";
  if (v === "INSUFFICIENT") return "warn";
  return "neutral";
}

function Fmt({ label, value, mono }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[11px] text-muted">{label}</span>
      <span className={`text-xs font-semibold ${mono ? "font-mono" : ""} text-slate-200`}>{value ?? "—"}</span>
    </div>
  );
}

export default function RegistrationPanel({ pairId, notify }) {
  const { canMutate } = useAuth();
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [transform, setTransform] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [validation, setValidation] = useState(null);
  const [provenance, setProvenance] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [visualizations, setVisualizations] = useState([]);
  const [selectedViz, setSelectedViz] = useState("before_after");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      let st = null;
      try {
        st = await apiGet(`/registration/${pairId}/status`);
        setStatus(st);
      } catch (e) {
        setError(e);
        return;
      }
      if (st.state === "COMPLETE" || st.state === "INSUFFICIENT") {
        const get = async (ep, key) => {
          try {
            const r = await apiGet(`/registration/${pairId}/${ep}`);
            return key ? r[key] : r;
          } catch {
            return null;
          }
        };
        setSummary(await get("summary", "summary"));
        setTransform(await get("transform", "transform"));
        setDiagnostics(await get("diagnostics", "diagnostics"));
        setValidation(await get("validation", "validation"));
        setProvenance(await get("provenance", "provenance"));
        try {
          const v = await apiGet(`/registration/${pairId}/visualizations`);
          setVisualizations(v.visualizations ?? []);
        } catch {
          setVisualizations([]);
        }
      } else {
        setSummary(null);
        setTransform(null);
        setDiagnostics(null);
        setValidation(null);
        setProvenance(null);
        setVisualizations([]);
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
  }, [pairId]);

  async function runRegistration() {
    setBusy(true);
    setError(null);
    try {
      const st = await apiPost(`/registration/${pairId}/run`, {
        registration_configuration_id: "RG-M6-001",
      });
      setStatus(st);
      if (st.state === "BLOCKED") {
        notify({
          title: `REGISTRATION blocked · ${st.block_code ?? "?"}`,
          message: st.reasons?.join(", ") ?? "Blocked honestly at the registration gate.",
          tone: "warn",
        });
      } else if (st.state === "COMPLETE") {
        notify({
          title: `Registration complete · ${pairId}`,
          message: "Homography fit, validated warp and jury-ready workspace produced.",
          tone: "ok",
        });
      } else if (st.state === "FAILED") {
        notify({
          title: `REGISTRATION failed · ${pairId}`,
          message: st.reasons?.join(", ") ?? "No trustworthy registration artifact could be produced.",
          tone: "warn",
        });
      } else if (st.state === "INSUFFICIENT") {
        notify({
          title: `Registration insufficient · ${pairId}`,
          message: "Validation verdict did not meet PASS; no registered output produced.",
          tone: "warn",
        });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "REGISTRATION run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function resetRegistration() {
    setBusy(true);
    try {
      const r = await apiPost(`/registration/${pairId}/reset`);
      setStatus(r.status);
      setSummary(null);
      setTransform(null);
      setDiagnostics(null);
      setValidation(null);
      setProvenance(null);
      notify({
        title: `${pairId} registration reset`,
        message: "Only derived registration artifacts were removed. M5/M4/M3/M2/raw data untouched.",
        tone: "ok",
      });
    } catch (e) {
      notify({ title: "Reset failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function openManifest() {
    try {
      const m = (await apiGet(`/registration/${pairId}/manifest`)).manifest;
      setManifest(m);
    } catch (e) {
      notify({ title: "No registration manifest", message: e.message, tone: "danger" });
    }
  }

  const matrix = transform?.matrix;
  const diag = diagnostics;

  return (
    <section className="space-y-4">
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">M6 · Image Alignment</p>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Registration — <span className="font-mono text-teal-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(status?.state ?? "NOT_STARTED")}>
                {status?.state ?? "NOT_STARTED"}
              </Badge>
              {validation?.verdict && (
                <Badge tone={verdictTone(validation.verdict)}>
                  verdict: {validation.verdict}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">RG-M6-001</code> ·
              homography fit with affine fallback, validation diagnostics, warp output ·
              <strong className="text-slate-200"> low residual ≠ physically exact registration</strong>.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run verified registration" : "Analyst or admin required"} onClick={runRegistration}>
              <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "Run REGISTRATION"}
            </button>
            <button className="btn-ghost" disabled={busy || !canMutate} title={canMutate ? "Reset pair state" : "Analyst or admin required"} onClick={resetRegistration}>
              <Icon.Refresh className="h-4 w-4" /> Reset
            </button>
            <button
              className="btn-ghost"
              disabled={busy || status?.state !== "COMPLETE"}
              onClick={openManifest}
              title="Registration provenance manifest"
            >
              <Icon.Database className="h-4 w-4" /> Manifest
            </button>
          </div>
        </div>
        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}
      </div>

      {/* blocked / failed */}
      {status?.state === "BLOCKED" && (
        <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-warn">
            <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {status.block_code}
          </p>
          {status.reasons?.length > 0 && (
            <p className="mt-1 text-xs leading-relaxed text-muted">{status.reasons.join("; ")}</p>
          )}
        </div>
      )}

      {status?.state === "FAILED" && (
        <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> FAILED · {status.reasons?.join(", ") ?? "unknown"}
          </p>
        </div>
      )}

      {/* transform matrix */}
      {matrix && (
        <div className="grid gap-4 lg:grid-cols-3">
          {/* matrix card */}
          <div className="card p-4">
            <h4 className="mb-2 text-xs font-bold text-slate-200">Transform matrix</h4>
            <p className="mb-2 text-[10px] text-muted">
              {transform.transform_type} · inlier ratio {transform.inlier_ratio} · seed {transform.seed_used}
            </p>
            <div className="font-mono text-[10px] leading-relaxed text-slate-300">
              {matrix.map((row, i) => (
                <div key={i} className="flex gap-3">
                  {row.map((v, j) => (
                    <span key={j} className="w-28 text-right">{v.toFixed(6)}</span>
                  ))}
                </div>
              ))}
            </div>
            <p className="mt-2 text-[10px] text-muted">
              Maps <strong className="text-slate-300">{transform.source_space?.frame ?? "sensor_a_pixel"}</strong>{" "}
              → <strong className="text-slate-300">{transform.target_space?.frame ?? "sensor_b_pixel"}</strong>.
              Fit on M5-selected evidence.
            </p>
          </div>

          {/* diagnostics card */}
          {diag && (
            <div className="card p-4">
              <h4 className="mb-2 text-xs font-bold text-slate-200">Diagnostics</h4>
              <div className="space-y-1">
                <Fmt label="Inliers" value={`${diag.correspondences?.inliers ?? "?"} / ${diag.correspondences?.valid_for_fit ?? "?"}`} />
                <Fmt label="Residual mean" value={`${diag.residuals?.mean_px?.toFixed(3) ?? "?"} px`} />
                <Fmt label="Residual p95" value={`${diag.residuals?.p95_px?.toFixed(3) ?? "?"} px`} />
                <Fmt label="Symmetric transfer max" value={`${diag.symmetric_transfer?.max_px?.toFixed(3) ?? "?"} px`} />
                <Fmt label="Determinant" value={diag.numerics?.determinant?.toFixed(4) ?? "?"} />
                <Fmt label="Condition number" value={diag.numerics?.condition_number?.toFixed(4) ?? "?"} />
                {diag.numerics?.degeneracy_flags?.length > 0 && (
                  <p className="text-[10px] text-warn">
                    Degeneracy flags: {diag.numerics.degeneracy_flags.join(", ")}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* validation card */}
          {validation && (
            <div className="card p-4">
              <h4 className="mb-2 text-xs font-bold text-slate-200">Validation</h4>
              <Badge tone={verdictTone(validation.verdict)}>{validation.verdict}</Badge>
              {validation.issues?.length > 0 ? (
                <ul className="mt-2 space-y-1">
                  {validation.issues.map((issue, i) => (
                    <li key={i} className="text-[10px] text-danger">{issue}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-[10px] text-ok">All validation checks passed.</p>
              )}
              {validation.checks && (
                <div className="mt-2 space-y-0.5">
                  {Object.entries(validation.checks).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between text-[10px]">
                      <span className="text-muted">{k}</span>
                      <span className={v ? "text-ok" : "text-danger"}>{v ? "pass" : "fail"}</span>
                    </div>
                  ))}
                </div>
              )}
              {validation.independent_check?.recomputed && (
                <p className="mt-2 text-[10px] text-muted">
                  Independent recompute: residual mean{" "}
                  <strong className="text-slate-300">{validation.independent_check.residual_mean_px} px</strong>, symmetric
                  transfer max{" "}
                  <strong className="text-slate-300">{validation.independent_check.symmetric_transfer_max_px} px</strong>
                  {" "}— {validation.independent_check.consistent_with_fit ? "consistent with fit." : "inconsistent with fit."}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* registered output */}
      {summary?.warp && status?.state === "COMPLETE" && (
        <div className="card p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
            <h4 className="text-xs font-bold text-slate-200">Registered output &amp; visualizations</h4>
            {visualizations.length > 1 && (
              <div className="flex flex-wrap gap-1.5">
                {visualizations.map((viz) => (
                  <button
                    key={viz.name}
                    onClick={() => setSelectedViz(viz.name)}
                    className={`rounded-md border px-2 py-1 text-[10px] font-medium transition ${
                      selectedViz === viz.name
                        ? "border-orbit-500/50 bg-orbit-500/[0.08] text-orbit-300"
                        : "border-white/[0.08] bg-white/[0.02] text-muted hover:text-slate-200"
                    }`}
                  >
                    {viz.name.replace(".png", "").replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-start gap-4">
            <div className="shrink-0 overflow-hidden rounded-lg border border-white/[0.08] bg-space-950">
              <VizPreview pairId={pairId} name={selectedViz} />
            </div>
            <div className="min-w-[180px] space-y-1">
              <Fmt label="Source tile" value={summary.warp.source_tile_id} mono />
              <Fmt label="Output size" value={`${summary.warp.out_rows}×${summary.warp.out_cols}`} mono />
              <Fmt label="Transform" value={summary.transform_type} />
              <Fmt label="Mapping" value="sensor_a_pixel → sensor_b_pixel" mono />
              <Fmt label="Selection reason" value={summary.selection_reason} />
              <Fmt
                label="Correspondences (inliers)"
                value={`${summary.correspondences?.inliers ?? "?"} / ${summary.correspondences?.fit_used ?? "?"}`}
              />
              <p className="pt-1 text-[10px] leading-relaxed text-muted">
                Side-by-side, difference, correspondence and footprint overlays are best-effort
                inspection aids — not scientific alignment evidence.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* scientific note */}
      {status?.state === "COMPLETE" && (
        <div className="rounded-lg border border-white/[0.08] bg-space-900/40 p-3.5">
          <p className="text-[10px] leading-relaxed text-muted">
            {status.scientific_note ?? "Diagnostics are measurements, not proof of physical registration accuracy."}
          </p>
        </div>
      )}

      {/* provenance chain */}
      {provenance?.chain && (
        <div className="card p-4">
          <h4 className="mb-2 text-xs font-bold text-slate-200">Provenance chain</h4>
          <div className="flex flex-wrap gap-2">
            {provenance.chain.map((c, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-space-900/60 px-2.5 py-1.5"
              >
                <span className="text-[10px] font-bold text-slate-300">{c.milestone}</span>
                {c.artifacts?.length > 0 && (
                  <span className="text-[9px] text-muted">
                    {c.artifacts.length} artifact{c.artifacts.length !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            ))}
          </div>
          <p className="mt-2 text-[10px] text-muted">
            Chain computed from M2→M3→M4→M5→M6 artifacts. SHA-256 hashes are deterministic; paths are relative to data root.
          </p>
        </div>
      )}

      {/* manifest modal */}
      <Modal open={!!manifest} onClose={() => setManifest(null)} title={`Registration manifest · ${pairId}`}>
        {manifest && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(manifest, null, 2)}
          </pre>
        )}
      </Modal>
    </section>
  );
}

function VizPreview({ pairId, name }) {
  const src = `/api/registration/${pairId}/visualizations/${name}`;

  const [imgBroken, setImgBroken] = useState(false);

  useEffect(() => {
    setImgBroken(false);
  }, [name]);

  if (imgBroken) {
    return (
      <div className="flex h-32 w-32 items-center justify-center p-2 text-center text-[10px] text-muted">
        Visualization unavailable
      </div>
    );
  }

  return (
    <img
      key={name}
      src={src}
      alt={`Registration visualization — ${name.replace(".png", "")}`}
      className="h-56 w-56 object-contain sm:h-64 sm:w-64"
      onError={() => setImgBroken(true)}
    />
  );
}
