import { useEffect, useMemo, useState } from "react";

import Pipeline, { STAGE_STYLE } from "../components/Pipeline.jsx";
import { Badge, EmptyState, Icon, Modal, PageSkeleton } from "../components/ui.jsx";
import MatchingPanel from "../components/MatchingPanel.jsx";
import TrustPanel from "../components/TrustPanel.jsx";
import SpatialReliabilityPanel from "../components/SpatialReliabilityPanel.jsx";
import RegistrationPanel from "../components/RegistrationPanel.jsx";
import MetricsPanel from "../components/MetricsPanel.jsx";
import M8Workspace from "../components/M8Workspace.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

const M2_PIPELINE = [
  { id: "reading", label: "Read", desc: "Raw integrity re-verified" },
  { id: "preprocessing", label: "Masks", desc: "Invalid data excluded" },
  { id: "preparing_overlap", label: "Overlap", desc: "Footprint intersection" },
  { id: "generating_crops", label: "Crops", desc: "Sensor-native tiles" },
  { id: "analyzing_condition", label: "Condition", desc: "Per-tile scene analysis" },
  { id: "matcher_ready", label: "Matcher", desc: "Readiness contract" },
];

const MODULE_PLAN = [
  {
    id: "condition",
    label: "Condition estimator",
    desc: "Valid coverage, illumination range, brightness, texture and saturation per tile plus a pair-level summary.",
    milestone: "M2",
    implemented: true,
  },
  {
    id: "matcher",
    label: "Matcher adapters",
    desc: "Uniform adapters over classical (SIFT) and robust (ORB) local matchers; deep matchers declared-but-unavailable in this build.",
    milestone: "M3",
    implemented: true,
  },
  {
    id: "routing",
    label: "Adaptive routing",
    desc: "Condition-informed, explainable choice of matcher strategy instead of a single blind default. Routing is a what-to-try decision, never a quality verdict.",
    milestone: "M3",
    implemented: true,
  },
  {
    id: "trust",
    label: "Trust Gate",
    desc: "Independent verification layer — matcher confidence is never the final truth signal. Deterministic RANSAC geometry + spatial support + symmetric cross-check.",
    milestone: "M4",
    implemented: true,
  },
  {
    id: "spatial",
    label: "Spatial selection",
    desc: "Temporal & spatial reliability of accepted correspondences before model fitting.",
    milestone: "M5",
    implemented: true,
  },
  {
    id: "registration",
    label: "Registration",
    desc: "Homography / affine fitting with diagnostics — low residual ≠ physically exact lunar registration.",
    milestone: "M6",
    implemented: true,
  },
  {
    id: "metrics",
    label: "Metrics & reporting",
    desc: "Quantitative diagnostics, reproducible experiment reports and independent recomputation — measurements, never accuracy claims.",
    milestone: "M7",
    implemented: true,
  },
  {
    id: "m8",
    label: "Deep matcher expansion",
    desc: "Adaptive expansion over deep + classical matchers with honest capability probing; benchmark rows are measurement comparisons — no winner, no accuracy claim.",
    milestone: "M8",
    implemented: true,
  },
];

const STATE_STAGE_STYLE = {
  pending: STAGE_STYLE.locked,
  running: STAGE_STYLE.running,
  complete: STAGE_STYLE.complete,
  blocked: STAGE_STYLE.warning,
  failed: STAGE_STYLE.failed,
};

function deriveStages(proc) {
  const stagesById = Object.fromEntries((proc?.stages ?? []).map((s) => [s.id, s]));
  return M2_PIPELINE.map((s) => {
    const raw = stagesById[s.id];
    if (!raw || s.id === "matcher_ready") {
      let state = "locked";
      if (s.id === "matcher_ready") {
        const level = proc?.matcher_readiness?.level;
        if (level === "READY" || level === "CONDITIONAL") state = "complete";
        else if (level === "BLOCKED") state = "warning";
        else if (proc?.state === "READY_FOR_MATCHING") state = "complete";
      }
      return { ...s, state };
    }
    const state = raw.state === "pending" ? "locked" : raw.state === "running" ? "running" : raw.state;
    return { ...s, state, detail: raw.detail };
  });
}

function toneFor(level) {
  if (level === "READY" || level === "CONDITIONAL") return "ok";
  if (level === "BLOCKED") return "warn";
  return "neutral";
}

function fmtUtc(v) {
  if (!v) return "—";
  return v.replace("T", " ").replace("+00:00", " UTC");
}

export default function Analysis({ notify, onNavigate }) {
  const { canMutate, user } = useAuth();
  const [pairs, setPairs] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [overview, setOverview] = useState(null);
  const [sel, setSel] = useState(null);
  const [proc, setProc] = useState(null);
  const [tiles, setTiles] = useState(null);
  const [conditions, setConditions] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [manifest, setManifest] = useState(null);

  const loadData = useMemo(
    () => async () => {
      setError(null);
      try {
        const [pl, cf, ov] = await Promise.all([
          apiGet("/pairs"),
          apiGet("/processing/configurations"),
          apiGet("/processing/overview"),
        ]);
        setPairs(pl.pairs ?? []);
        setConfigs(cf.configurations ?? []);
        setOverview(ov);
        if (sel && pl.pairs?.some((p) => p.pair_id === sel)) await reload(sel);
      } catch (e) {
        setError(e);
      }
    },
    [sel]
  );

  useEffect(() => {
    loadData().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function reload(pairId) {
    setError(null);
    try {
      const status = await apiGet(`/processing/${pairId}/status`);
      setProc(status);
      setSel(pairId);
      let t = null;
      let c = null;
      try {
        t = (await apiGet(`/processing/${pairId}/tiles`)).tiles;
      } catch {
        /* 404 — no tiles yet */
      }
      try {
        c = (await apiGet(`/processing/${pairId}/conditions`)).conditions;
      } catch {
        /* 404 — no condition analysis yet */
      }
      setTiles(t);
      setConditions(c);
    } catch (e) {
      setError(e);
    }
  }

  async function selectPair(pairId) {
    setProc(null);
    setSel(pairId);
    if (pairId) await reload(pairId);
  }

  async function runPrepare(pairId) {
    if (!pairId) return;
    setBusy(true);
    setError(null);
    try {
      const status = await apiPost(`/processing/${pairId}/prepare`, {});
      setProc(status);
      if (status.state === "BLOCKED") {
        notify({
          title: `PREPARE blocked · ${status.blocked?.code ?? "?"}`,
          message: status.blocked?.reason ?? "Processing stopped honestly at a gate.",
          tone: "warn",
        });
      } else if (status.state === "READY_FOR_MATCHING") {
        const lvl = status.matcher_readiness?.level ?? "READY";
        notify({
          title: `${pairId} matcher ready · ${lvl}`,
          message: status.matcher_readiness?.note ?? "All readiness requirements met.",
          tone: "ok",
        });
      }
      await reloadAfterPrepare(status);
    } catch (e) {
      setError(e);
      notify({ title: "PREPARE failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function reloadAfterPrepare(status) {
    let t = null;
    let c = null;
    try {
      t = (await apiGet(`/processing/${sel}/tiles`)).tiles;
    } catch {
      /* none */
    }
    try {
      c = (await apiGet(`/processing/${sel}/conditions`)).conditions;
    } catch {
      /* none */
    }
    setProc(status);
    setTiles(t);
    setConditions(c);
  }

  async function reset(pairId) {
    if (!pairId) return;
    setBusy(true);
    try {
      const r = await apiPost(`/processing/${pairId}/reset`);
      setProc(r.status);
      setTiles(null);
      setConditions(null);
      notify({ title: `${pairId} reset`, message: "Only derived processing artifacts were removed. raw/ is untouched.", tone: "ok" });
    } catch (e) {
      notify({ title: "Reset failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function openManifest(pairId) {
    try {
      const m = (await apiGet(`/processing/${pairId}/manifest`)).manifest;
      setManifest(m);
    } catch (e) {
      notify({ title: "No manifest", message: e.message, tone: "danger" });
    }
  }

  const readyMeta = useMemo(() => {
    if (!proc) return null;
    return proc.matcher_readiness;
  }, [proc]);

  if (!pairs) return <PageSkeleton rows={3} />;

  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Analysis workspace</h2>
        <p className="text-sm leading-relaxed text-muted">
          M2 executes a reproducible PREPARE run: raw-integrity re-verification, invalid-data masks,
          overlap evidence, sensor-native crops and per-tile scene conditions. Once preparatory
          readiness is met, M3 runs the <strong className="text-slate-200">adaptive matcher</strong> — an explainable
          per-tile strategy decision, explicit candidate filters and observable correspondences
          (which remain observations, never verified truth). M4 then independently verifies each
          candidate set geometrically and applies the Trust Gate. BLOCKED is a normal
          result — <strong className="text-slate-200">nothing is simulated and nothing is guessed</strong>.
        </p>
      </section>

      {overview?.blocked && (
        <section className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-warn/30 bg-warn/[0.06] p-4">
          <div className="flex items-start gap-3">
            <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${overview?.pairs?.length ? "bg-warn" : "bg-muted"}`} />
            <div>
              <p className="text-sm font-bold text-warn">Real-data processing: BLOCKED</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{overview.reason}</p>
            </div>
          </div>
          <button className="btn-ghost !px-3 !py-1.5 text-xs" onClick={() => onNavigate?.("data")}>
            <Icon.Database className="h-3.5 w-3.5" /> Open data workspace
          </button>
        </section>
      )}

      {/* pair selector + controls */}
      <section className="card p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-[240px] flex-1 space-y-1.5">
            <label className="text-xs font-semibold text-slate-200">Registered pair</label>
            <select className="input w-full" value={sel ?? ""} onChange={(e) => selectPair(e.target.value)}>
              <option value="">Select a pair…</option>
              {pairs.map((p) => (
                <option key={p.pair_id} value={p.pair_id}>
                  {p.pair_id} · {p.sensor_a} → {p.sensor_b} · {p.validation_status}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted">
              {pairs.length === 0
                ? "No registered pairs. Register validated real products in the Data workspace first."
                : "Real pairs have no documented ground geometry in M2 yet — PREPARE will stop transparently at the overlap gate."}
            </p>
          </div>
          <div className="min-w-[200px] flex-1 space-y-1.5">
            <label className="text-xs font-semibold text-slate-200">Configuration</label>
            <select className="input w-full" disabled={!configs.length || !sel} title={configs[0]?.configuration_id}>
              <option>{configs[0]?.configuration_id ?? "PC-M2-001 (default)"}</option>
            </select>
            <p className="text-[11px] text-muted">{configs[0]?.note ?? "Registered M2 engineering defaults — no scientific thresholds."}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={!sel || busy || !canMutate} title={canMutate ? "Run honest PREPARE to the matcher boundary" : "Analyst or admin required"} onClick={() => runPrepare(sel)}>
              <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "PREPARE for matching"}
            </button>
            <button className="btn-ghost" disabled={!sel || busy || !canMutate} title={canMutate ? "Reset derived artifacts" : "Analyst or admin required"} onClick={() => reset(sel)}>
              <Icon.Refresh className="h-4 w-4" /> Reset
            </button>
          </div>
        </div>
        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}
      </section>

      {/* stage introspection */}
      {sel && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-slate-100">PREPARE run · <span className="font-mono text-lunar-300">{sel}</span></h3>
              <p className="text-xs text-muted">
                {proc?.state === "NOT_STARTED" || !proc
                  ? "No PREPARE run yet for this pair."
                  : `State ${proc.state} · ${fmtUtc(proc.started_at)}`}
              </p>
            </div>
            <Badge tone={readyMeta ? toneFor(readyMeta.level) : "neutral"}>
              {readyMeta ? `Matcher ${readyMeta.level}` : "Not started"}
            </Badge>
          </div>

          <Pipeline stages={deriveStages(proc)} />

          {proc?.state === "BLOCKED" && proc.blocked && (
            <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
              <p className="flex items-center gap-2 text-xs font-bold text-warn">
                <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {proc.blocked.code}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{proc.blocked.reason}</p>
            </div>
          )}

          {proc?.state === "FAILED" && proc.error && (
            <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
              <p className="flex items-center gap-2 text-xs font-bold text-danger">
                <Icon.Alert className="h-3.5 w-3.5" /> FAILED · {proc.error.code}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{proc.error.message}</p>
            </div>
          )}

          {readyMeta && (
            <div className="grid gap-3 sm:grid-cols-2">
              {readyMeta.requirements.map((r) => (
                <div
                  key={r.id}
                  className={`card card-hover p-3 ${r.met ? STAGE_STYLE.complete.ring : STAGE_STYLE.warning.ring}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-slate-200">{r.id}</span>
                    <Badge tone={r.met ? "ok" : "warn"}>{r.met ? "met" : "not met"}</Badge>
                  </div>
                  <p className="mt-1 text-[11px] leading-snug text-muted">{r.label}</p>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost !px-3 !py-1.5 text-xs" disabled={!proc} onClick={() => openManifest(sel)}>
              <Icon.Database className="h-3.5 w-3.5" /> Provenance manifest
            </button>
          </div>
        </section>
      )}

      {/* conditions + tiles */}
      {sel && conditions && (
        <section className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-100">Scene conditions</h3>
              <Badge tone="blue">{conditions.summary.assessed}/{conditions.summary.tiles} assessed</Badge>
            </div>
            <div className="card p-4">
              <ConditionDistribution dist={conditions.summary.distribution ?? {}} />
              <p className="mt-3 text-[11px] leading-relaxed text-muted">{conditions.summary.note}</p>
            </div>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-100">Tile explorer</h3>
              <Badge tone={tiles ? "ok" : "neutral"}>{tiles?.count ?? 0} tiles</Badge>
            </div>
            <div className="card max-h-[420px] overflow-y-auto p-4">
              {!tiles || tiles.tiles?.length === 0 ? (
                <p className="text-xs text-muted">No crops generated.</p>
              ) : (
                <ul className="space-y-2">
                  {tiles.tiles.map((t) => (
                    <TileRow key={t.tile_id} tile={t} pairId={sel} />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>
      )}

      {/* gemometry + overlap diagnostics */}
      {sel && proc?.state === "READY_FOR_MATCHING" && (
        <section className="card p-4">
          <h3 className="mb-2 text-sm font-bold text-slate-100">Validation &amp; geometry evidence</h3>
          <p className="text-xs leading-relaxed text-muted">
            Geometry source: <code className="font-mono text-slate-300">{proc.geometry_source ?? "none"}</code> ·
            Tile count: <span className="font-mono text-slate-300">{proc.tiles?.count ?? "—"}</span> ·
            Usable per side: <code className="font-mono text-slate-300">{JSON.stringify(proc.tiles?.usable ?? {})}</code>
          </p>
          <p className="mt-2 text-[11px] text-muted">
            {proc.geometry_source === "TEST_FIXTURE"
              ? "This realization used a SOFTWARE-TEST fixture geometry — it validates the engine, not the Moon."
              : "No real ground geometry is available; the run stopped before any overlap claim."}
          </p>
        </section>
      )}

      {/* M3 matcher workspace */}
      {sel && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-100">Matcher intelligence · M3</h3>
              <p className="text-xs text-muted">
                Runs when M2 readiness is met: adaptive strategy routing then candidate localisation.
              </p>
            </div>
            <Badge tone="gold">MC-M3-001 config</Badge>
          </div>
          <MatchingPanel key={sel} pairId={sel} notify={notify} />
        </section>
      )}

      {/* M4 trust gate workspace */}
      {sel && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-100">Trust Gate · M4</h3>
              <p className="text-xs text-muted">
                Runs when M3 candidates exist: deterministic geometry verification, spatial support and
                symmetric cross-check per tile.
              </p>
            </div>
            <Badge tone="gold">TG-M4-001 config</Badge>
          </div>
          <TrustPanel key={`${sel}-trust`} pairId={sel} notify={notify} />
        </section>
      )}

      {/* M5 spatial reliability workspace */}
      {sel && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-100">Spatial Reliability · M5</h3>
              <p className="text-xs text-muted">
                Runs when M4 trusted tiles exist: overlap-normalised scene grid, per-cell verified evidence,
                neighbourhood support and reliability-aware selection.
              </p>
            </div>
            <Badge tone="gold">SR-M5-001 config</Badge>
          </div>
          <SpatialReliabilityPanel key={`${sel}-spatial`} pairId={sel} notify={notify} />
        </section>
      )}

      {/* M6 registration workspace */}
      {sel && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-100">Registration · M6</h3>
              <p className="text-xs text-muted">
                Runs when M5 selected correspondences exist: homography / affine transform fit,
                validation diagnostics, warp output and provenance. Low residual does not mean exact
                physical registration.
              </p>
            </div>
            <Badge tone="gold">RG-M6-001 config</Badge>
          </div>
          <RegistrationPanel key={`${sel}-registration`} pairId={sel} notify={notify} />
        </section>
      )}

      {/* M7 metrics workspace */}
      {sel && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-100">Metrics &amp; reporting · M7</h3>
              <p className="text-xs text-muted">
                Runs when M6 registration is complete: quantitative metrics, deterministic
                experiment reports and independent recomputation over the M2→M6 evidence chain.
                Every value is a measurement of artefacts — never a scientific accuracy claim.
              </p>
            </div>
            <Badge tone="gold">MT-M7-001 config</Badge>
          </div>
          <MetricsPanel key={`${sel}-metrics`} pairId={sel} notify={notify} />
        </section>
      )}

      {/* M8 deep matcher expansion workspace */}
      {sel && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-100">Deep matcher expansion &amp; benchmark · M8</h3>
              <p className="text-xs text-muted">
                Runs when M2/M3 prerequisites are met: honest capability probing, adaptive
                strategy expansion over deep + classical matchers, candidate localisation under
                the M8 contract and optional per-matcher benchmark rows. Deep matchers are
                declared unavailable unless their runtime and weights are provisioned — nothing
                is simulated, no winner is ever declared.
              </p>
            </div>
            <Badge tone="gold">DM-M8-001 config</Badge>
          </div>
          <M8Workspace key={`${sel}-m8`} pairId={sel} notify={notify} />
        </section>
      )}

      {/* module roadmap */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-100">Component roadmap</h3>
          <Badge tone="warn">Pipeline dormant for real matching</Badge>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {MODULE_PLAN.map((mod) => {
            const implementedState = mod.implemented ? (conditions ? "complete" : "ready") : "locked";
            const style = STAGE_STYLE[implementedState];
            return (
              <div key={mod.id} className={`card card-hover p-4 ${style.ring}`}>
                <div className="mb-2 flex items-center justify-between">
                  <span className={`flex h-2 w-2 rounded-full ${style.dot}`} />
                  <Badge tone={mod.implemented ? "blue" : "neutral"}>{mod.milestone}</Badge>
                </div>
                <p className={`text-sm font-bold ${style.label}`}>{mod.label}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted">{mod.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* manifest modal */}
      <Modal open={!!manifest} onClose={() => setManifest(null)} title={`Provenance manifest · ${sel ?? ""}`}>
        {manifest && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(manifest, null, 2)}
          </pre>
        )}
      </Modal>
    </div>
  );
}

function ConditionDistribution({ dist }) {
  const entries = Object.entries(dist);
  if (entries.length === 0) {
    return <p className="text-xs text-muted">No classified tiles.</p>;
  }
  const total = entries.reduce((s, [, v]) => s + v, 0);
  return (
    <div className="space-y-2">
      {entries.map(([level, count]) => {
        const tone =
          level === "TEXTURED" ? "ok" : level.includes("LOW") ? "warn" : level.includes("HIGH") ? "gold" : "neutral";
        const pct = Math.round((count / total) * 100);
        return (
          <div key={level} className="flex items-center gap-3">
            <span className="w-40 text-[11px] font-medium text-slate-200">{level}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div className={`h-full ${tone === "ok" ? "bg-ok" : tone === "warn" ? "bg-warn" : tone === "gold" ? "bg-lunar-400" : "bg-muted"}`} style={{ width: `${pct}%` }} />
            </div>
            <Badge tone={tone}>{count}</Badge>
          </div>
        );
      })}
    </div>
  );
}

function TileRow({ tile, pairId }) {
  const ind = tile.conditions?.indicators ?? {};
  const cls = tile.conditions?.classification ?? {};
  const [previewBroken, setPreviewBroken] = useState(false);
  return (
    <li className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-space-900/40 p-2.5">
      <div className="h-14 w-14 shrink-0 overflow-hidden rounded-md bg-space-950">
        <img
          src={`/api/processing/${pairId}/tiles/${tile.tile_id}/preview`}
          alt={`${tile.tile_id} display preview (derived)`}
          loading="lazy"
          onError={() => setPreviewBroken(true)}
          className={`h-full w-full object-cover ${previewBroken ? "hidden" : ""}`}
        />
        {previewBroken && <div className="flex h-full items-center justify-center text-[9px] text-muted">n/a</div>}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate font-mono text-xs font-semibold text-slate-200">{tile.tile_id}</p>
          <Badge tone={tile.sensor === "ohrc" ? "blue" : "gold"}>{tile.sensor}</Badge>
        </div>
        <p className="mt-0.5 text-[10.5px] text-muted">
          {tile.clipped ? "edge-clipped · " : ""}
          {tile.too_small ? "too small · " : ""}
          {cls.level ?? tile.classification?.level ?? "not classified"}
        </p>
        <p className="mt-0.5 truncate text-[10px] font-mono text-muted/70">{tile.array_rel}</p>
      </div>
    </li>
  );
}