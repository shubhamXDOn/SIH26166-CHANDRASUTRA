import { useEffect, useMemo, useState } from "react";

import { Badge, EmptyState, Icon, Modal, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet, apiPost } from "../api.js";

const OVERLAP_OPTIONS = [
  { value: "OVERLAP_UNCONFIRMED", label: "Overlap unconfirmed", note: "Candidate — not benchmark-ready until footprint evidence exists." },
  { value: "CONFIRMED_OVERLAP", label: "Overlap confirmed", note: "Requires documented footprint/geometry evidence." },
  { value: "NO_OVERLAP", label: "No overlap", note: "Documented non-overlapping geometry." },
  { value: "UNKNOWN", label: "Unknown", note: "No geometry data available yet." },
];

const WIZ = {
  IDLE: "idle",
  SCANNING: "scanning",
  SELECT: "select",
  READING: "reading",
  REVIEW: "review",
  REGISTERING: "registering",
  DONE: "done",
  FAILED: "failed",
};

export default function Data({ notify, onNavigate }) {
  const [status, setStatus] = useState(null);
  const [sensors, setSensors] = useState(null);
  const [pairs, setPairs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [validation, setValidation] = useState(null);
  const [processing, setProcessing] = useState(null);
  const [matching, setMatching] = useState(null);
  const [trust, setTrust] = useState(null);
  const [spatial, setSpatial] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [wizard, setWizard] = useState(null);

  const load = useMemo(
    () => async () => {
      setRefreshing(true);
      try {
        const [s, sen, pl] = await Promise.all([apiGet("/data/status"), apiGet("/data/sensors"), apiGet("/pairs")]);
        setStatus(s);
        setSensors(sen);
        setPairs(pl.pairs ?? []);
        setError(null);
      } catch (e) {
        setError(e);
        throw e;
      } finally {
        setRefreshing(false);
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [s, sen, pl] = await Promise.all([apiGet("/data/status"), apiGet("/data/sensors"), apiGet("/pairs")]);
        if (!alive) return;
        setStatus(s);
        setSensors(sen);
        setPairs(pl.pairs ?? []);
      } catch (e) {
        if (alive) setError(e);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  async function openDetail(pairId) {
    try {
      const det = await apiGet(`/pairs/${pairId}`);
      const val = await apiGet(`/pairs/${pairId}/validate`);
      let proc = null;
      try {
        proc = await apiGet(`/processing/${pairId}/status`);
      } catch {
        /* processing not staged */
      }
      let mat = null;
      try {
        mat = await apiGet(`/matching/${pairId}/status`);
      } catch {
        /* matching not staged */
      }
      let tr = null;
      try {
        tr = await apiGet(`/trust/${pairId}/status`);
      } catch {
        /* trust not staged */
      }
      let sp = null;
      try {
        sp = await apiGet(`/spatial/${pairId}/status`);
      } catch {
        /* spatial not staged */
      }
      setSelected(pairId);
      setDetail(det);
      setValidation(val);
      setProcessing(proc);
      setMatching(mat);
      setTrust(tr);
      setSpatial(sp);
    } catch (e) {
      notify({ title: "Could not open pair", message: e.message, tone: "danger" });
    }
  }

  async function runValidate() {
    if (!selected) return;
    try {
      const v = await apiPost(`/pairs/${selected}/validate`);
      setValidation(v);
      notify({ title: `Validation complete · ${selected}`, message: `Status: ${v.status} — raw integrity ${v.raw_integrity}.`, tone: v.status === "VALID" ? "ok" : "danger" });
      await load();
      if (detail) setDetail(await apiGet(`/pairs/${selected}`));
    } catch (e) {
      notify({ title: "Validation failed", message: e.message, tone: "danger" });
    }
  }

  if (loading) return <PageSkeleton rows={3} />;

  if (error || !status) {
    return (
      <div className="card p-6">
        <p className="flex items-center gap-2 text-sm font-semibold text-danger">
          <Icon.Alert className="h-4 w-4" /> Unable to access the configured scientific data source.
        </p>
        <p className="mt-1 text-xs text-muted">{String(error?.message ?? error)}</p>
        <button className="btn-ghost mt-4" onClick={() => window.location.reload()}>
          <Icon.Refresh className="h-4 w-4" /> Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* HEADER */}
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl space-y-2">
          <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-lunar-400">CHANDRASUTRA</p>
          <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">
            Lunar Data Workspace
          </h2>
          <p className="text-sm leading-relaxed text-muted">
            Register and validate real Chandrayaan-2 OHRC × TMC-2 image pairs from ISSDC PRADAN.
            Raw products are immutable; every preview and derived artifact is stored separately.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <button className="btn-ghost !px-3 !py-2 text-xs" onClick={() => { load().catch(() => {}); notify({ title: "Workspace refreshed", tone: "ok" }); }}>
            <Icon.Refresh className="h-3.5 w-3.5" /> Refresh
          </button>
          <button className="btn-primary" onClick={() => setWizard({ step: WIZ.IDLE })}>
            <Icon.Database className="h-4 w-4" /> Load / Register Pair
          </button>
        </div>
      </section>

      {/* A. DATA SOURCE */}
      <section className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-sm font-bold text-slate-100">
              <Icon.Database className="h-4 w-4 text-lunar-400" /> ISRO / ISSDC PRADAN
            </p>
            <p className="mt-1 text-xs text-muted">
              Chandrayaan-2 science data archive — OHRC (~0.25 m/px) &amp; TMC-2 (~5 m/px).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="blue">Chandrayaan-2</Badge>
            {status.source?.access?.anonymous !== undefined && (
              <Badge tone={status.source.access.anonymous ? "ok" : "warn"}>
                {status.source.access.anonymous ? "Anonymous access" : "Registered access only"}
              </Badge>
            )}
            <Badge tone="neutral">
              {status.raw_products_present} raw product{status.raw_products_present === 1 ? "" : "s"} on disk
            </Badge>
          </div>
        </div>
        <p className="mt-3 max-w-3xl text-[11.5px] leading-relaxed text-muted">
          {status.source?.access?.note ??
            "PRADAN requires user registration and administrator approval before downloads are permitted."}{" "}
          Place downloaded <code className="font-mono text-slate-300">.img</code> products and their{" "}
          <code className="font-mono text-slate-300">.xml</code> PDS4 labels under{" "}
          <code className="font-mono text-slate-300">data/raw/ohrc</code> and{" "}
          <code className="font-mono text-slate-300">data/raw/tmc2</code>, then register them here.
        </p>
        <a
          className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-orbit-300 underline decoration-orbit-500/40 underline-offset-2 hover:text-orbit-200"
          href="https://pradan.issdc.gov.in/ch2/"
          target="_blank"
          rel="noreferrer"
        >
          pradan.issdc.gov.in/ch2 <Icon.Chevron className="h-3 w-3" />
        </a>
      </section>

      {/* B. REGISTERED PAIRS */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-slate-100">Registered pairs</h3>
            <p className="text-xs text-muted">
              {status.pairs_registered} registered · {status.pairs_valid} valid · {status.pairs_confirmed_overlap} confirmed overlap
            </p>
          </div>
          <Badge tone={status.pairs_registered > 0 ? "ok" : "neutral"}>
            <StatusDot state={status.pairs_registered > 0 ? "ok" : "neutral"} /> {(status.first_pair_status?.pair_id ?? "none").replace("none", "no pair yet")}
          </Badge>
        </div>

        {pairs.length === 0 ? (
          <div className="card p-4">
            <EmptyState
              icon={<Icon.Info className="h-5 w-5" />}
              title="No registered pairs yet"
              message="Real OHRC/TMC-2 products are not present on disk. Once PRADAN-approval files are placed under data/raw, use 'Load / Register Pair' to build the first traceable pair (CS-P001)."
              action={
                <button className="btn-primary !px-3 !py-1.5 text-xs" onClick={() => setWizard({ step: WIZ.IDLE })}>
                  Start ingestion
                </button>
              }
            />
          </div>
        ) : (
          <div className="card overflow-x-auto">
            <table className="table-base whitespace-nowrap">
              <thead>
                <tr>
                  <th>Pair ID</th>
                  <th>Sensors</th>
                  <th>Dimensions</th>
                  <th>GSD (nominal)</th>
                  <th>Overlap</th>
                  <th>Metadata</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {pairs.map((p) => (
                  <tr key={p.pair_id} className="cursor-pointer" onClick={() => openDetail(p.pair_id)}>
                    <td className="font-mono text-xs font-semibold text-lunar-300">{p.pair_id}</td>
                    <td className="text-xs text-slate-200">{p.sensor_a} → {p.sensor_b}</td>
                    <td className="font-mono text-xs text-slate-300">{p.dimensions_a} · {p.dimensions_b}</td>
                    <td className="font-mono text-xs text-slate-300">{trimGsd(p.nominal_gsd_a)} · {trimGsd(p.nominal_gsd_b)}</td>
                    <td><OverlapBadge value={p.overlap_status} /></td>
                    <td className="font-mono text-xs text-slate-300">{Math.round((p.metadata_completeness?.fraction ?? 0) * 100)}%</td>
                    <td><Badge tone={p.validation_status === "VALID" ? "ok" : "neutral"}>{p.validation_status}</Badge></td>
                    <td className="text-right">
                      <button className="btn-ghost !px-2 !py-1 text-xs" onClick={(e) => { e.stopPropagation(); openDetail(p.pair_id); }}>
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* C+D+E. PAIR DETAIL */}
      {selected && detail && <PairInspection detail={detail} validation={validation} processing={processing} matching={matching} trust={trust} spatial={spatial} onValidate={runValidate} onNavigate={onNavigate} />}

      {/* Ingestion wizard */}
      {wizard && (
        <IngestionWizard
          notify={notify}
          onClose={() => setWizard(null)}
          onRegistered={async () => {
            await load();
            setWizard(null);
            notify({ title: "Pair registered", message: "Registered and validated a real CHANDRASUTRA pair.", tone: "ok" });
          }}
        />
      )}
    </div>
  );
}

function trimGsd(gsd) {
  if (!gsd || gsd === "UNKNOWN") return "n/a";
  return gsd.replace(" (nominal, sensor) *", "");
}

function OverlapBadge({ value }) {
  const map = {
    CONFIRMED_OVERLAP: { tone: "ok", label: "Confirmed" },
    OVERLAP_UNCONFIRMED: { tone: "warn", label: "Unconfirmed" },
    NO_OVERLAP: { tone: "danger", label: "No overlap" },
    UNKNOWN: { tone: "neutral", label: "Unknown" },
  };
  const m = map[value] ?? map.UNKNOWN;
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

/* ------------------------------------------------------------------ */
/* Pair inspection workspace                                           */
/* ------------------------------------------------------------------ */

function PairInspection({ detail, validation, processing, matching, trust, spatial, onValidate, onNavigate }) {
  const r = detail.record;
  const comp = detail.completeness;
  const overlap = validation?.overlap ?? { status: r.overlap_status, evidence: r.overlap_evidence || "No evidence recorded." };
  const readyM2 = (detail.record.validation_status === "VALID") && overlap.status === "CONFIRMED_OVERLAP";
  const pState = processing?.state ?? "NOT_STARTED";
  const pLevel = processing?.matcher_readiness?.level ?? null;
  const pBlocked = processing?.blocked ?? null;
  const mState = matching?.state ?? "NOT_STARTED";
  const mRun = matching?.summary ?? null;
  const tState = trust?.gate_state ?? "NOT_STARTED";
  const sState = spatial?.gate_state ?? "NOT_STARTED";

  const checks = validation?.checks ?? [];
  const integrity = {
    "Raw file A": checks.find((c) => c.check === "image_a_exists")?.status ?? "—",
    "Raw file B": checks.find((c) => c.check === "image_b_exists")?.status ?? "—",
    "Hash A": checks.find((c) => c.check === "raw_hash_a")?.status ?? "—",
    "Hash B": checks.find((c) => c.check === "raw_hash_b")?.status ?? "—",
    "Label A": checks.find((c) => c.check === "label_a_exists")?.status ?? "—",
    "Label B": checks.find((c) => c.check === "label_b_exists")?.status ?? "—",
    "Readable A": checks.find((c) => c.check === "image_a_readable")?.status ?? "—",
    "Readable B": checks.find((c) => c.check === "image_b_readable")?.status ?? "—",
  };

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-extrabold tracking-tight text-slate-100">
            Pair inspection — <span className="font-mono text-lunar-300">{r.pair_id}</span>
          </h3>
          <p className="text-xs text-muted">
            Registered {r.registered_at_utc?.replace("T", " ")?.replace("+00:00", " UTC")}
            {r.last_validated_utc ? ` · last validated ${r.last_validated_utc.replace("T", " ").replace("+00:00", " UTC")}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={detail.record.validation_status === "VALID" ? "ok" : "warn"}>
            <StatusDot state={detail.record.validation_status === "VALID" ? "ok" : "warn"} /> {detail.record.validation_status}
          </Badge>
          <Badge tone={readyM2 ? "ok" : "neutral"}>
            {readyM2 ? "Ready for preprocessing (M2)" : "Awaiting M1 validation"}
          </Badge>
          <button className="btn-ghost !px-3 !py-1.5 text-xs" onClick={onValidate}>
            <Icon.Activity className="h-3.5 w-3.5" /> Validate now
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ProductCard side="a" record={r} />
        <ProductCard side="b" record={r} />
      </div>

      {/* F. M2 PROCESSING READINESS */}
      <div className="card p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h4 className="text-sm font-bold text-slate-100">M2 preprocessing readiness</h4>
<div className="flex flex-wrap items-center gap-2">
          <Badge tone={pState === "READY_FOR_MATCHING" ? "ok" : pState === "BLOCKED" ? "warn" : "neutral"}>
            <StatusDot state={pState === "READY_FOR_MATCHING" ? "ok" : pState === "BLOCKED" ? "warn" : "info"} /> {pState}
          </Badge>
          {pLevel && <Badge tone={pLevel === "READY" || pLevel === "CONDITIONAL" ? "ok" : "warn"}>Matcher {pLevel}</Badge>}
          <Badge tone={mState === "COMPLETE" ? "ok" : mState === "BLOCKED" ? "warn" : mState === "RUNNING" ? "blue" : "neutral"}>
            M3 {mState} {mRun ? `· ${mRun.total_candidates ?? 0} candidates` : ""}
          </Badge>
          <Badge tone={tState === "COMPLETE" ? "ok" : tState === "BLOCKED" ? "warn" : tState === "FAILED" ? "warn" : tState === "RUNNING" ? "blue" : "neutral"}>
            Trust {tState}
          </Badge>
          <Badge tone={sState === "COMPLETE" ? "ok" : sState === "BLOCKED" ? "warn" : sState === "FAILED" || sState === "INSUFFICIENT" ? "warn" : sState === "RUNNING" ? "blue" : "neutral"}>
            Spatial {sState}
          </Badge>
          <Badge tone="neutral">M6 Registration LOCKED</Badge>
          <button className="btn-ghost !px-3 !py-1.5 text-xs" onClick={() => onNavigate?.("analysis")}>
            <Icon.Activity className="h-3.5 w-3.5" /> Open in Analysis
          </button>
        </div>
        </div>

        {pBlocked ? (
          <div className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/[0.06] p-3 text-[11px] leading-relaxed text-warn">
            <Icon.Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              PREPARE stopped truthfully at <strong className="text-warn">{pBlocked.stage}</strong> ({pBlocked.code}):{" "}
              {pBlocked.reason}
            </span>
          </div>
        ) : pState === "READY_FOR_MATCHING" ? (
          <p className="text-xs leading-relaxed text-slate-300">
            All matcher-readiness requirements met. Preprocessed products, invalid-data masks,
            sensor-native crops and per-tile scene conditions are available under{" "}
            <code className="font-mono text-slate-300">data/derived/processing/{r.pair_id}/</code>.
          </p>
        ) : (
          <p className="text-xs leading-relaxed text-muted">
            {processing
              ? `${r.pair_id} has a PREPARE run in state ${pState}. Real pairs have no documented ground geometry in M2 yet, so PREPARE stops transparently at the overlap gate.`
              : "No PREPARE run yet for this pair. Open it in Analysis to run the honest M2 preparation pipeline."}
          </p>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* D. DATA INTEGRITY */}
        <div className="card p-5">
          <h4 className="mb-3 text-sm font-bold text-slate-100">Data integrity</h4>
          <ul className="grid grid-cols-2 gap-x-4 gap-y-2">
            {Object.entries(integrity).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-muted">{k}</span>
                <IntegrityBadge v={v} />
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-muted">
            Raw products are never written by the backend. SHA-256 hashes below are recorded at
            registration and re-verified on every validation.
          </p>
        </div>

        {/* E. OVERLAP */}
        <div className="card p-5">
          <h4 className="mb-3 text-sm font-bold text-slate-100">Overlap evidence</h4>
          <OverlapBadge value={overlap.status} />
          <p className="mt-3 text-xs leading-relaxed text-slate-300">{overlap.evidence || r.overlap_evidence}</p>
          {r.overlap_status === "OVERLAP_UNCONFIRMED" && (
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/[0.06] p-3 text-[11px] leading-relaxed text-warn">
              <Icon.Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              This pair is a candidate. No footprint/geometry confirms overlap yet; it is not a
              benchmark pair until evidence exists.
            </p>
          )}
          <div className="mt-3 space-y-1.5 text-[11px] leading-relaxed text-muted">
            {r.illumination_info && r.illumination_info !== "UNKNOWN" && (<p>· Illumination: {r.illumination_info}</p>)}
            {r.viewing_geometry_info && r.viewing_geometry_info !== "UNKNOWN" && (<p>· Viewing geometry: {r.viewing_geometry_info}</p>)}
            {r.footprint_a && r.footprint_a !== "UNKNOWN" && (<p>· Footprint A: {r.footprint_a}</p>)}
            {r.footprint_b && r.footprint_b !== "UNKNOWN" && (<p>· Footprint B: {r.footprint_b}</p>)}
            {!(r.illumination_info && r.illumination_info !== "UNKNOWN") && (<p>· Illumination: UNKNOWN · No map coordinates are fabricated.</p>)}
          </div>
        </div>
      </div>

      {/* Metadata table + completeness */}
      <div className="grid gap-4 lg:grid-cols-5">
        <div className="card p-5 lg:col-span-3">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-bold text-slate-100">Metadata</h4>
            <Badge tone={comp.level === "COMPLETE_ENOUGH" ? "ok" : comp.level === "PARTIAL" ? "warn" : "neutral"}>
              {comp.present}/{comp.total} fields · {Math.round(comp.fraction * 100)}%
            </Badge>
          </div>
          <MetaTable r={r} />
          {comp.missing?.length > 0 && (
            <p className="mt-3 text-[11px] text-muted">Missing/UNKNOWN: {comp.missing.join(", ")}</p>
          )}
        </div>
        <div className="card p-5 lg:col-span-2">
          <h4 className="mb-3 text-sm font-bold text-slate-100">Validation checks</h4>
          <ul className="max-h-64 space-y-1.5 overflow-y-auto pr-1 text-xs">
            {checks.map((c) => (
              <li key={c.check} className="flex items-start justify-between gap-2 border-b border-white/[0.04] pb-1.5">
                <span>
                  <span className="font-medium text-slate-200">{c.check}</span>
                  {c.detail && <span className="block text-[10.5px] text-muted">{c.detail}</span>}
                </span>
                <IntegrityBadge v={c.status} />
              </li>
            ))}
            {checks.length === 0 && <li className="text-muted">No checks yet — run validation.</li>}
          </ul>
        </div>
      </div>

<div className="card p-4">
        <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
          <Icon.Info className="mt-0.5 h-3.5 w-3.5 text-orbit-400" />
          <span>
            {r.pair_id} is registered and its raw products are hashed. M3 candidate correspondences
            are raw observations. The M4 Trust Gate state for this pair is{" "}
            <strong className="text-slate-200">{tState}</strong> and the M5 spatial reliability state is{" "}
            <strong className="text-slate-200">{sState}</strong> — independent geometric verification, when run in
            the Analysis workspace, converts qualified tiles into verified spatial evidence and then
            selects a supported reliability region; nothing here ever carries a fabricated accuracy or
            trust verdict. Registration (M6) is locked until implemented.
          </span>
        </p>
      </div>
    </section>
  );
}

function ProductCard({ side, record }) {
  const proxy = side === "a";
  const filename = proxy ? record.image_a_filename : record.image_b_filename;
  const sensor = proxy ? record.sensor_a : record.sensor_b;
  const width = proxy ? record.image_a_width : record.image_b_width;
  const height = proxy ? record.image_a_height : record.image_b_height;
  const dtype = proxy ? record.dtype_a : record.dtype_b;
  const gsd = proxy ? record.nominal_gsd_a : record.nominal_gsd_b;
  const hash = proxy ? record.raw_file_hash_a : record.raw_file_hash_b;
  const acq = proxy ? record.acquisition_datetime_a : record.acquisition_datetime_b;
  const prodId = proxy ? record.image_a_product_id : record.image_b_product_id;
  const level = proxy ? record.processing_level_a : record.processing_level_b;
  const labelName = proxy ? record.label_a_filename : record.label_b_filename;

  const [imgBroken, setImgBroken] = useState(false);

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-white/[0.06] p-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider text-orbit-400">Image {side.toUpperCase()}</p>
          <p className="text-sm font-bold text-slate-100">{sensor === "tmc2" ? "TMC-2" : sensor === "ohrc" ? "OHRC" : sensor}</p>
        </div>
        <Badge tone="blue">{labelName ? "PDS4 label" : "no label"}</Badge>
      </div>
      <div className="relative aspect-[16/9] w-full bg-space-900/60">
        <img
          key={`${record.pair_id}-${side}`}
          src={`/api/pairs/${record.pair_id}/preview/${side}`}
          alt={`Image ${side} scientific preview (derived)`}
          loading="lazy"
          onError={() => setImgBroken(true)}
          className={`h-full w-full object-contain ${imgBroken ? "hidden" : ""}`}
        />
        {imgBroken && (
          <div className="flex h-full items-center justify-center">
            <p className="max-w-[80%] text-center text-xs leading-relaxed text-muted">
              Scientific preview unavailable — the derived 8-bit preview could not be generated.
              Raw product remains untouched.
            </p>
          </div>
        )}
        <span className="absolute bottom-2 left-2 rounded border border-white/10 bg-space-950/70 px-2 py-0.5 text-[10px] text-muted backdrop-blur">
          derived preview · not the raw product
        </span>
      </div>
      <div className="space-y-2.5 p-4 text-xs">
        <MetaLine k="Product ID" v={prodId} mono />
        <MetaLine k="File" v={filename} mono />
        <MetaLine k="Dimensions" v={`${width} × ${height} px`} mono />
        <MetaLine k="dtype" v={dtype} mono />
        <MetaLine k="GSD" v={gsd === "UNKNOWN" ? "UNKNOWN" : `~${trimGsd(gsd)} m/px`} />
        <MetaLine k="Acquisition" v={acq} mono />
        <MetaLine k="Processing level" v={level} />
        <div className="flex items-center justify-between gap-2 border-t border-white/[0.05] pt-2">
          <span className="text-muted">SHA-256</span>
          <span className="max-w-[210px] truncate font-mono text-[10px] text-slate-300" title={hash}>{hash || "—"}</span>
        </div>
      </div>
    </div>
  );
}

function MetaLine({ k, v, mono = false }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 text-muted">{k}</span>
      <span className={`min-w-0 truncate text-right text-slate-200 ${mono ? "font-mono text-[11px]" : "font-medium"}`}>{v === "" || v == null ? "—" : v}</span>
    </div>
  );
}

function MetaTable({ r }) {
  const rows = [
    ["Source archive", r.source_archive],
    ["Source URL", r.source_url],
    ["Sensor A", r.sensor_a],
    ["Sensor B", r.sensor_b],
    ["Image A product ID", r.image_a_product_id],
    ["Image B product ID", r.image_b_product_id],
    ["Product type A/B", `${r.product_type_a} / ${r.product_type_b}`],
    ["Overlap status", r.overlap_status],
    ["Overlap evidence", r.overlap_evidence || "—"],
    ["Attribution", r.attribution_notes],
    ["Data use", r.data_use_notes],
    ["Notes", r.notes || "—"],
  ];
  return (
    <dl className="divide-y divide-white/[0.05] text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[7rem_1fr] gap-3 py-1.5">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-slate-200">{Array.isArray(v) ? v.join(", ") : v}</dd>
        </div>
      ))}
    </dl>
  );
}

function IntegrityBadge({ v }) {
  if (v === "PASS") return <Badge tone="ok">pass</Badge>;
  if (v === "FAIL") return <Badge tone="danger">fail</Badge>;
  return <Badge tone="neutral">{v}</Badge>;
}

/* ------------------------------------------------------------------ */
/* Ingestion wizard                                                    */
/* ------------------------------------------------------------------ */

function IngestionWizard({ notify, onClose, onRegistered }) {
  const [step, setStep] = useState(WIZ.IDLE);
  const [scan, setScan] = useState(null);
  const [nextId, setNextId] = useState("CS-P001");
  const [pickA, setPickA] = useState("");
  const [pickB, setPickB] = useState("");
  const [overlap, setOverlap] = useState("OVERLAP_UNCONFIRMED");
  const [evidence, setEvidence] = useState("");
  const [notes, setNotes] = useState("");
  const [probing, setProbing] = useState(null); // {a, b}
  const [review, setReview] = useState(null); // payload ready to register
  const [result, setResult] = useState(null); // register/validate result
  const [errorMsg, setErrorMsg] = useState(null);

  function startScan() {
    setStep(WIZ.SCANNING);
    Promise.all([apiGet("/pairs/scan"), apiGet("/pairs/next-id")])
      .then(([s, n]) => {
        setScan(s);
        setNextId(n.pair_id);
        setStep(WIZ.SELECT);
      })
      .catch((e) => {
        setErrorMsg(e.message);
        setStep(WIZ.FAILED);
      });
  }

  const productsA = useMemo(() => productsFor(scan, "ohrc"), [scan]);
  const productsB = useMemo(() => productsFor(scan, "tmc2"), [scan]);

  function analyze() {
    setStep(WIZ.READING);
    setErrorMsg(null);
    Promise.all([apiGet(`/pairs/probe?path=${encodeURIComponent(pickA)}`), apiGet(`/pairs/probe?path=${encodeURIComponent(pickB)}`)])
      .then(([pa, pb]) => {
        setProbing({ a: pa.product, b: pb.product });
        setStep(WIZ.REVIEW);
      })
      .catch((e) => {
        setErrorMsg(e.message);
        setStep(WIZ.FAILED);
      });
  }

  function register() {
    setStep(WIZ.REGISTERING);
    const payload = {
      image_a: pickA,
      image_b: pickB,
      overlap_status: overlap,
      overlap_evidence: evidence,
      notes,
    };
    apiPost("/pairs/register", payload)
      .then(async (reg) => {
        const val = await apiPost(`/pairs/${reg.pair_id}/validate`);
        setResult({ register: reg, validation: val });
        notify({ title: `${reg.pair_id} registered`, message: `Raw files referenced and hashed — never modified.`, tone: "ok" });
        setStep(WIZ.DONE);
      })
      .catch((e) => {
        setErrorMsg(e.message);
        setStep(WIZ.FAILED);
      });
  }

  const evidenceRequired = overlap === "CONFIRMED_OVERLAP" || overlap === "OVERLAP_UNCONFIRMED";
  const canReview = pickA && pickB && (!evidenceRequired || evidence.trim().length > 0);

  return (
    <Modal
      open
      onClose={onClose}
      title="Register real pair"
      footer={null}
    >
      <WizardProgress step={step} />
      <div className="mt-4 space-y-4">
        {step === WIZ.IDLE && (
          <div className="space-y-4">
            <p className="text-sm leading-relaxed text-muted">
              This flow registers a real OHRC (Image A) and TMC-2 (Image B) pair already placed under{" "}
              <code className="font-mono text-slate-300">data/raw</code>. Raw files are referenced and
              hashed — they are never copied, converted or modified.
            </p>
            <button className="btn-primary w-full justify-center" onClick={startScan}>
              <Icon.Database className="h-4 w-4" /> Scan data/raw
            </button>
          </div>
        )}

        {step === WIZ.SCANNING && <BusyLine label="Scanning data/raw for products…" detail="Listing candidate .img/.xml files only." />}

        {step === WIZ.SELECT && (
          <div className="space-y-4">
            <SelectField label="Image A — OHRC (raw/ohrc)" options={productsA} value={pickA} onChange={setPickA} />
            <SelectField label="Image B — TMC-2 (raw/tmc2)" options={productsB} value={pickB} onChange={setPickB} />
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-200">Overlap status</label>
              <select className="input w-full" value={overlap} onChange={(e) => setOverlap(e.target.value)}>
                {OVERLAP_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <p className="text-[11px] text-muted">{OVERLAP_OPTIONS.find((o) => o.value === overlap)?.note}</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-200">
                Overlap evidence {evidenceRequired && <span className="text-warn">(required)</span>}
              </label>
              <textarea
                className="input min-h-[72px] w-full"
                placeholder="Documented footprint/geometry basis for overlap (for example: same orbit swath, map-browse footprint). Never 'looks similar'."
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-200">Notes (optional)</label>
              <input className="input w-full" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Selection rationale, provenance notes…" />
            </div>
            <button className="btn-primary w-full justify-center" disabled={!canReview} onClick={analyze}>
              <Icon.Activity className="h-4 w-4" /> Read metadata &amp; validate products
            </button>
            {!canReview && (
              <p className="text-[11px] text-warn">Select both images{evidenceRequired ? " and provide overlap evidence" : ""} to continue.</p>
            )}
          </div>
        )}

        {step === WIZ.READING && <BusyLine label="Reading PDS4 metadata…" detail="Parsing CH-2 product labels and hashing raw bytes." />}

        {step === WIZ.REVIEW && probing && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-orbit-500/30 bg-orbit-500/[0.06] p-3">
              <span className="text-xs font-semibold text-slate-100">Confirm Pair ID</span>
              <span className="font-mono text-sm font-bold text-orbit-300">{nextId}</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <ReviewProduct title="A · OHRC" p={probing.a} />
              <ReviewProduct title="B · TMC-2" p={probing.b} />
            </div>
            <label className="flex items-center gap-2 text-[11px] text-muted">
              <input type="checkbox" defaultChecked className="accent-lunar-400" /> I confirm these are the intended official products and the raw files remain unmodified.
            </label>
            <button className="btn-primary w-full justify-center" onClick={register}>
              <Icon.Check className="h-4 w-4" /> Register {nextId} &amp; validate
            </button>
          </div>
        )}

        {step === WIZ.REGISTERING && <BusyLine label="Registering pair…" detail="Writing metadata record only — data/raw is never touched." />}

        {step === WIZ.DONE && result && (
          <div className="space-y-4">
            <div className="rounded-lg border border-ok/40 bg-ok/[0.06] p-4">
              <p className="flex items-center gap-2 text-sm font-bold text-ok">
                <Icon.Check className="h-4 w-4" /> {result.register.pair_id} registered &amp; validated
              </p>
              <p className="mt-1 text-xs text-muted">
                Status <strong className="text-slate-200">{result.validation.status}</strong> · raw integrity{" "}
                <strong className="text-slate-200">{result.validation.raw_integrity}</strong> · overlap{" "}
                <strong className="text-slate-200">{overlapBadgeLabel(overlap)}</strong>
              </p>
              <p className="mt-1 text-[11px] text-muted">
                Scientific matching: <strong className="text-slate-200">NOT_RUN</strong> — M1 ends at validation.
              </p>
            </div>
            <button
              className="btn-primary w-full justify-center"
              onClick={async () => {
                await onRegistered();
                onClose();
              }}
            >
              Open registered pair
            </button>
          </div>
        )}

        {step === WIZ.FAILED && (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-danger">
              <Icon.Alert className="h-4 w-4" /> Ingestion failed
            </p>
            <p className="text-xs leading-relaxed text-muted">{errorMsg}</p>
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => setStep(WIZ.SELECT)}>Back to selection</button>
              <button className="btn-ghost" onClick={onClose}>Close</button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

function WizardProgress({ step }) {
  const order = ["Scan", "Select", "Read", "Review", "Register"];
  const activeIdx = { idle: 0, scanning: 1, select: 2, reading: 3, review: 4, registering: 5, done: 5, failed: 2 }[step] ?? 0;
  return (
    <div className="flex items-center gap-1.5">
      {order.map((label, i) => {
        const state = i < activeIdx ? "done" : i === activeIdx ? "active" : "todo";
        return (
          <div key={label} className="flex flex-1 items-center gap-1.5">
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                state === "done" ? "bg-ok/20 text-ok" : state === "active" ? "bg-orbit-500/20 text-orbit-300 ring-1 ring-orbit-500/50" : "bg-white/[0.04] text-muted"
              }`}
            >
              {state === "done" ? <Icon.Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className={`text-[10px] font-medium ${state === "active" ? "text-slate-100" : "text-muted"}`}>{label}</span>
            {i < order.length - 1 && <span className="h-px flex-1 bg-white/[0.07]" />}
          </div>
        );
      })}
    </div>
  );
}

function BusyLine({ label, detail }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-space-900/60 p-4">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-orbit-400 border-t-transparent" />
      <div>
        <p className="text-sm font-semibold text-slate-100">{label}</p>
        <p className="text-[11px] text-muted">{detail}</p>
      </div>
    </div>
  );
}

function productsFor(scan, sensorId) {
  if (!scan?.raw_dirs) return [];
  const dir = scan.raw_dirs.find((d) => d.id === `raw/${sensorId}`);
  if (!dir?.exists) return [];
  return dir.products
    .filter((p) => p.kind === "product")
    .map((p) => ({ rel: `raw/${sensorId}/${p.image}`, name: p.image }))
    .sort((x, y) => x.name.localeCompare(y.name));
}

function SelectField({ label, options, value, onChange }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-slate-200">{label}</label>
      {options.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/10 p-3 text-[11px] text-muted">
          No products found. Place downloaded <code className="font-mono">.img</code> + labels under <code className="font-mono">data/raw</code> first.
        </p>
      ) : (
        <select className="input w-full" value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Select product…</option>
          {options.map((o) => (
            <option key={o.rel} value={o.rel}>{o.name}</option>
          ))}
        </select>
      )}
    </div>
  );
}

function ReviewProduct({ title, p }) {
  return (
    <div className="rounded-lg border border-white/[0.07] bg-space-900/50 p-3">
      <p className="text-[10px] font-bold uppercase tracking-wider text-orbit-400">{title}</p>
      <p className="mt-1 truncate font-mono text-[11px] text-slate-200">{p.filename}</p>
      <div className="mt-2 space-y-1 text-[11px] text-muted">
        <p>Product ID: <span className="font-mono text-slate-300">{p.product_id}</span></p>
        <p>{p.width} × {p.height} px · {p.dtype}</p>
        <p>GSD: {p.gsd === "UNKNOWN" ? "UNKNOWN" : `~${trimGsd(p.gsd)} m/px`}</p>
        <p>Acquired: {p.acquisition_datetime}</p>
        <p>SHA-256: <span className="font-mono">{p.raw_sha256?.slice(0, 12)}…</span></p>
      </div>
    </div>
  );
}

function overlapBadgeLabel(v) {
  return OVERLAP_OPTIONS.find((o) => o.value === v)?.label ?? v;
}