import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M5 CONDITION ESTIMATOR — pair-level condition & difficulty
   characterization evaluated BEFORE any matcher selection. It describes
   each side (texture energy, edge density, Laplacian variance, entropy,
   robust intensity stats, invalid-mask coverage) plus the pair comparison
   (appearance histogram distance, recorded scale/GSD relationships).

   Explicitly NOT a matcher-selection layer: it never selects, recommends or
   routes a matcher and never reports a confidence or a quality verdict.
   Optional latest-baseline matcher observations appear only inside a
   separated, explicitly-labelled section. */

function stateTone(state) {
  if (state === "SUCCESS" || state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED") return "danger";
  return "neutral";
}

export default function ConditionAnalysisCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [caps, setCaps] = useState(null);
  const [status, setStatus] = useState(null);
  const [latest, setLatest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        setCaps((await apiGet("/matching/conditions/capabilities")) ?? null);
      } catch (e) {
        setError(e);
      }
      try {
        const st = (await apiGet(`/pairs/${pairId}/conditions/status`)) ?? null;
        setStatus(st);
        setLatest(st?.latest_run ?? null);
      } catch (e) {
        setError(e);
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runConditions() {
    setBusy(true);
    setError(null);
    try {
      const payload = await apiPost(`/pairs/${pairId}/conditions/run`);
      setLatest(payload);
      setStatus((prev) => ({ ...(prev ?? {}), latest_run: payload }));
      if (payload.status === "SUCCESS") {
        notify({
          title: `Condition estimate recorded`,
          message: "Reproducible engineering labels — never a quality verdict and never matcher selection.",
          tone: "ok",
        });
      } else if (payload.status === "BLOCKED") {
        notify({
          title: `Condition estimate BLOCKED · ${payload.error_code ?? "?"}`,
          message: payload.error_detail ?? "Blocked honestly at a condition gate.",
          tone: "warn",
        });
      } else {
        notify({ title: "Condition estimate failed", message: payload.error_detail ?? "Run failed.", tone: "danger" });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Condition estimate failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  const gate = status?.data_gate ?? caps?.data_gate;
  const configId = latest?.configuration_id ?? "CE-M5-001";

  return (
    <section className="space-y-4">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Condition estimator · M5 — <span className="font-mono text-lunar-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(latest?.status ?? "NOT_RUN")}>{latest?.status ?? "NOT_RUN"}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{configId}</code> · pair-level condition and
              difficulty characterization evaluated BEFORE any matcher selection. This layer never selects or routes a
              matcher.
            </p>
          </div>
          <button
            className="btn-primary"
            disabled={busy || !canMutate}
            title={
              canMutate
                ? "Estimate this pair's condition from its M2 validated products"
                : `Viewer access — ${user?.username ?? "you"} can read evidence but cannot run pipeline mutations`
            }
            onClick={runConditions}
          >
            <Icon.Activity className="h-4 w-4" /> {busy ? "Estimating…" : "Estimate condition"}
          </button>
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}

        {gate && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted">
            <Badge tone={gate.real_data_available ? "ok" : "warn"}>{gate.code}</Badge>
            <span>{gate.message}</span>
          </div>
        )}

        {latest?.status === "BLOCKED" && (
          <div className="mt-3 rounded-lg border border-warn/30 bg-warn/[0.06] p-3">
            <p className="flex items-center gap-2 text-xs font-bold text-warn">
              <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {latest.error_code}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{latest.error_detail}</p>
          </div>
        )}
      </div>

      {latest && (
        <RunSummary latest={latest} onToggle={() => setExpanded((v) => !v)} expanded={expanded} />
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="neutral">Intrinsic condition</Badge>
        <span>— reproducible engineering labels from M2 validated products.</span>
        <Badge tone="blue">Matcher-observed</Badge>
        <span>
          — optional, recorded inside a separated labelled section for context only; it never influences this layer.
        </span>
        <Badge tone="gold">Scale/GSD</Badge>
        <span>— recorded geometry or PDS4 labels only; UNKNOWN when absent, never inferred.</span>
      </div>
    </section>
  );
}

function RunSummary({ latest, onToggle, expanded }) {
  const ic = latest?.intrinsic_image_condition ?? {};
  const pc = latest?.pair_comparison ?? {};
  const scale = pc?.scale ?? {};
  const appearance = pc?.appearance ?? {};
  const source = latest.synthetically_derived
    ? "SYNTHETIC / fixture — structural software validation only"
    : "REAL-shaped / operator-data path";
  const levels = latest?.levels ?? {};

  const side = (obj, label) => {
    const cls = obj?.classification ?? {};
    const mask = obj?.invalid_mask ?? {};
    const texture = obj?.texture ?? {};
    return (
      <div className="card bg-space-900/40 p-3">
        <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Side {label}</p>
        <dl className="space-y-1">
          <Readout
            k="Textural complexity"
            v={cls.textural_complexity?.bin ?? "UNKNOWN"}
          />
          <Readout k="Dynamic range" v={cls.dynamic_range?.bin ?? "UNKNOWN"} />
          <Readout k="Invalid coverage" v={cls.invalid_fraction?.bin ?? "UNKNOWN"} />
          <Readout k="Lap. variance" v={fmt(texture.laplacian_variance)} />
          <Readout k="Edge density" v={fmt(texture.canny_edge_fraction)} />
          <Readout k="Valid fraction" v={fmt(mask.valid_fraction)} />
          <Readout k="Entropy (bits)" v={fmt(obj?.appearance?.entropy_bits)} />
          <Readout
            k="DN p5 · p50 · p95"
            v={joinP(obj?.appearance?.robust_intensity_dn)}
          />
        </dl>
      </div>
    );
  };

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="ok">GSD ratio {fmt(scale.gsd_ratio_relationship) ?? "—"}</Badge>
          <Badge tone="neutral">χ² hist {fmt(appearance.histogram_distance_chi_square)}</Badge>
          <Badge tone={latest.synthetically_derived ? "warn" : "blue"}>{source}</Badge>
          <Badge tone="neutral">geometry {latest?.geometry_source ?? "UNKNOWN"}</Badge>
        </div>
        <button className="btn-ghost" onClick={onToggle}>
          {expanded ? "Hide details" : "Details"}
        </button>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        run <code className="font-mono text-slate-300">{latest.run_id}</code> · {latest.created_at_utc} ·{" "}
        {latest.status === "SUCCESS"
          ? `sample ${latest.intrinsic_image_condition?.side_a?.sampling?.method ?? "—"} (${latest.intrinsic_image_condition?.side_a?.sampling?.windows_total ?? "—"} windows)`
          : latest.status === "BLOCKED"
            ? `BLOCKED · ${latest.error_code ?? "?"}`
            : `FAILED · ${latest.error_detail ?? "?"}`}
      </p>

      {latest.status === "SUCCESS" && (
        <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          {side(ic.side_a, "A")}
          {side(ic.side_b, "B")}
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">
              Pair comparison
            </p>
            <dl className="space-y-1">
              <Readout k="Appearance χ² (shared bins)" v={fmt(appearance.histogram_distance_chi_square)} />
              <Readout k="GSD relationship" v={fmt(scale.gsd_ratio_relationship)} />
              <Readout
                k="Side A GSD"
                v={`${scale.side_a_gsd?.gsd_m ?? "—"} · ${scale.side_a_gsd?.gsd_source ?? "UNKNOWN"}`}
              />
              <Readout
                k="Side B GSD"
                v={`${scale.side_b_gsd?.gsd_m ?? "—"} · ${scale.side_b_gsd?.gsd_source ?? "UNKNOWN"}`}
              />
              <Readout
                k="Native pixel ratio"
                v={fmt(scale.native_scale_gap?.absolute_pixel_ratio)}
              />
            </dl>
            <p className="pt-1 text-[10px] leading-snug text-muted">
              Classification bins are engineering-level ordinals with explicit thresholds, not a scientific verdict.
            </p>
          </div>
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">
              Levels
            </p>
            <dl className="space-y-1">
              {Object.entries(levels.side_a ?? {}).map(([k, v]) => (
                <Readout key={k} k={`A · ${k}`} v={v} />
              ))}
              {Object.entries(levels.side_b ?? {}).map(([k, v]) => (
                <Readout key={k} k={`B · ${k}`} v={v} />
              ))}
            </dl>
            {latest.matcher_derived_observations && (
              <p className="mt-2 text-[10px] leading-snug text-muted">
                A separated matcher-observed section is present (for context only) — this card never selects a matcher.
              </p>
            )}
          </div>
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

function fmt(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  return String(v);
}

function joinP(s) {
  if (!s || s.p5 == null) return "—";
  return `${s.p5} · ${s.p50} · ${s.p95}`;
}

function Readout({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}