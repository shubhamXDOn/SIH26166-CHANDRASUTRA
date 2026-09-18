import { useEffect, useState } from "react";

import Pipeline, { PIPELINE } from "../components/Pipeline.jsx";
import { Badge, EmptyState, Icon, Modal, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet } from "../api.js";

function useMeta(online) {
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    if (!online && meta) return undefined; // backend down, keep last known meta
    setError(null);
    apiGet("/meta")
      .then((m) => alive && setMeta(m))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [online, meta]);
  return { meta, error };
}

function useDataStatus() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/data/status")
      .then((s) => alive && setStatus(s))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { status, error };
}

function useProcessingOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/processing/overview")
      .then((o) => alive && setOverview(o))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { overview, error };
}

function useMatchingOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/matching/overview")
      .then((o) => alive && setOverview(o))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { overview, error };
}

function useTrustOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/trust/overview")
      .then((o) => alive && setOverview(o))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { overview, error };
}

function useSpatialOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/spatial/overview")
      .then((o) => alive && setOverview(o))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { overview, error };
}

function useRegistrationOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/registration/overview")
      .then((o) => alive && setOverview(o))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { overview, error };
}

function useMetricsOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet("/metrics/overview")
      .then((o) => alive && setOverview(o))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);
  return { overview, error };
}

function StatCard({ label, value, sub, tone = "neutral", pulse = false }) {
  const valueTone = {
    neutral: "text-slate-100",
    gold: "text-lunar-300",
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
  };
  return (
    <div className="card card-hover p-4">
      <div className="mb-2 flex items-center gap-2">
        <StatusDot state={tone === "neutral" ? "info" : tone} pulse={pulse} />
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</p>
      </div>
      <p className={`text-2xl font-extrabold tracking-tight ${valueTone[tone]}`}>{value}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted">{sub}</p>
    </div>
  );
}

export default function Overview({ backend, onNavigate }) {
  const { meta, error: metaError } = useMeta(backend?.online === true);
  const { status, error: statusError } = useDataStatus();
  const { overview, error: procError } = useProcessingOverview();
  const { overview: mOverview, error: mError } = useMatchingOverview();
  const { overview: tOverview, error: tError } = useTrustOverview();
  const { overview: sOverview, error: sError } = useSpatialOverview();
  const { overview: rOverview, error: rError } = useRegistrationOverview();
  const { overview: metOverview, error: metError } = useMetricsOverview();
  const [modalStage, setModalStage] = useState(null);
  const [lockModal, setLockModal] = useState(false);

  if (!meta) {
    const offline = backend?.online === false;
    return (
      <div className="space-y-6">
        <div className="space-y-4">
          <Badge tone="gold">CHANDRASUTRA · SIH26166 · Milestone M5</Badge>
          <h2 className="text-2xl font-extrabold tracking-tight text-slate-100">
            Trustworthy Lunar Image Intelligence
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            Real Chandrayaan-2 OHRC &amp; TMC-2 image pairs, immutable raw data, hashed products,
            documented overlap and strict validation — before any matching is trusted.
          </p>
        </div>
        <PageSkeleton rows={4} />
        <div className="card p-4">
          {offline ? (
            <p className="flex items-center gap-2 text-sm text-danger">
              <Icon.Alert /> Backend unavailable — cannot load system metadata yet.
            </p>
          ) : (
            <p className="text-sm text-muted">Loading system metadata…</p>
          )}
        </div>
      </div>
    );
  }

  const settings = meta.settings || {};
  const s = status || {};
  const pairsRegistered = s.pairs_registered ?? 0;
  const pairsValid = s.pairs_valid ?? 0;
  const confirmed = s.pairs_confirmed_overlap ?? 0;
  const candidates = s.pairs_candidate ?? 0;
  const rawPresent = s.raw_products_present ?? 0;
  const avgCompleteness = Math.round((s.metadata_completeness?.average_fraction ?? 0) * 100);
  const firstPair = s.first_pair_status ?? null;
  const procPairs = (overview?.pairs ?? []).filter((p) => p.ready);
  const readyInM2 = procPairs.length;
  const procRows = overview?.pairs ?? null;

  const matchedTiles = mOverview?.pairs?.length ?? 0;
  const totalCandidates = mOverview?.total_candidates ?? 0;
  const matchedPairs = mOverview?.pairs ?? [];

  const trustedPairs = tOverview?.trusted_pairs ?? 0;
  const trustBlockedPairs = tOverview?.blocked_pairs ?? 0;
  const trustTotal = tOverview?.total_trust_pairs ?? 0;

  const spatialCompletePairs = sOverview?.complete_pairs ?? 0;
  const spatialTotal = sOverview?.total_spatial_pairs ?? 0;

  const regTotalPairs = rOverview?.total_registration_pairs ?? 0;
  const regCompletePairs = rOverview?.complete_pairs ?? 0;
  const regBlockedPairs = rOverview?.blocked_or_insufficient_pairs ?? 0;
  const regRegistered = regTotalPairs > 0;

  const metTotalPairs = metOverview?.total_metrics_pairs ?? 0;
  const metCompletePairs = metOverview?.complete_pairs ?? 0;
  const metNotCompletePairs = metOverview?.not_complete_pairs ?? 0;

  const pipeline = PIPELINE.map((stage) => ({
    ...stage,
    state:
      stage.id === "data"
        ? "ready"
        : stage.id === "validate"
          ? pairsRegistered > 0
            ? pairsValid > 0 ? "complete" : "warning"
            : "ready"
          : stage.id === "preprocess"
            ? readyInM2 > 0
              ? "complete"
              : procRows && procRows.length > 0
                ? "warning"
                : "locked"
            : stage.id === "match"
              ? matchedTiles > 0
                ? "complete"
                : readyInM2 > 0
                  ? "ready"
                  : "locked"
              : stage.id === "trust"
                ? trustedPairs > 0
                  ? "complete"
                  : trustTotal > 0
                    ? "warning"
                    : matchedTiles > 0
                      ? "ready"
                      : "locked"
                : stage.id === "reliability"
                  ? spatialCompletePairs > 0
                    ? "complete"
                    : spatialTotal > 0
                      ? "warning"
                      : trustedPairs > 0
                        ? "ready"
                        : "locked"
                    : stage.id === "register"
                      ? regCompletePairs > 0
                        ? "complete"
                        : regRegistered
                          ? "warning"
                          : spatialCompletePairs > 0
                            ? "ready"
                            : "locked"
                      : stage.id === "metrics"
                        ? metCompletePairs > 0
                          ? "complete"
                          : metNotCompletePairs > 0
                            ? "warning"
                            : regCompletePairs > 0
                              ? "ready"
                              : "locked"
                        : "locked",
  }));

  const anchor = backend?.online ? "green" : "gray";

  return (
    <div className="space-y-6">
      {/* Hero */}
      <section className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-2xl space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="gold">Milestone M7 — Reproducible Metrics</Badge>
            <Badge tone={metCompletePairs > 0 ? "ok" : metNotCompletePairs > 0 ? "warn" : regCompletePairs > 0 ? "blue" : regRegistered ? "blue" : spatialCompletePairs > 0 ? "blue" : trustedPairs > 0 ? "blue" : matchedTiles > 0 ? "blue" : readyInM2 > 0 ? "blue" : "neutral"}>
              {metCompletePairs > 0
                ? `Metrics complete — ${metCompletePairs} pair(s)`
                : metNotCompletePairs > 0
                  ? `${metNotCompletePairs} pair(s) without metrics — run Metrics`
                  : regCompletePairs > 0
                    ? "Registration complete — METRICS ready to run"
                    : regRegistered
                      ? `${regBlockedPairs} pair(s) blocked/insufficient — open Analysis`
                      : spatialCompletePairs > 0
                        ? "Spatial selection done — REGISTER ready to run"
                        : trustedPairs > 0
                          ? "Trusted evidence — SPATIAL ready to run"
                          : matchedTiles > 0
                            ? `${totalCandidates} candidates — TRUST not yet run`
                            : readyInM2 > 0
                              ? "Matcher-ready — matching can run"
                              : "Awaiting documented geometry"}
            </Badge>
          </div>
          <h2 className="text-2xl font-extrabold leading-tight tracking-tight text-slate-100 sm:text-[1.7rem]">
            Trustworthy <span className="text-lunar-400 text-glow">lunar image</span> intelligence
          </h2>
          <p className="text-sm leading-relaxed text-muted">
            Real Chandrayaan-2 OHRC × TMC-2 pairs are hashed and validated in M1; M2 executes an
            honest PREPARE — masks, overlap evidence, crops and per-tile conditions; M3 runs an
            explainable adaptive matcher that records candidate correspondences as observations;
            M4 independently verifies them geometrically through the Trust Gate; M5 then represents
            the overlap scene as a reliability grid and selects evidence; M6 fits and validates a
            transform on that M5-selected evidence and warps the source into the target sensor frame;
            M7 produces quantitative metrics and reproducible experiment reports from the whole
            evidence chain. Metrics are measurements, never a claim of scientific alignment.
            Nothing is simulated.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-3">
          <button onClick={() => onNavigate("data")} className="btn-primary">
            <Icon.Database className="h-4 w-4" /> {pairsRegistered > 0 ? "Open data workspace" : "Load & register pair"}
          </button>
          <button
            onClick={() => setLockModal(true)}
            className="btn-ghost"
            disabled={!meta}
            title="Opens Analysis — honest M2 PREPARE runs, the M3 adaptive matcher, the M4 Trust Gate, M5 spatial selection and the M6 verified registration"
          >
            <Icon.Activity className="h-4 w-4" /> Open Analysis
          </button>
        </div>
      </section>

      {/* Metrics */}
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="System status"
          value={backend?.online ? "Operational" : "Offline"}
          tone={backend?.online ? "ok" : "danger"}
          pulse={backend?.online}
          sub={`${settings.app_env ?? "development"} · v${meta.version ?? "—"} · M7`}
        />
        <StatCard
          label="Data source"
          value={rawPresent > 0 ? `${rawPresent} products` : "Empty (auth)"}
          tone={rawPresent > 0 ? "ok" : "warn"}
          sub={
            rawPresent > 0
              ? "PRADAN products on disk, ready to register"
              : "PRADAN downloads need registration + admin approval"
          }
        />
        <StatCard
          label="Registered pairs"
          value={`${pairsValid}/${pairsRegistered}`}
          tone={pairsValid > 0 ? "ok" : pairsRegistered > 0 ? "warn" : "neutral"}
          sub={`${pairsRegistered} registered · ${candidates} candidate${candidates === 1 ? "" : "s"} (unconfirmed overlap)`}
        />
        <StatCard
          label="Benchmark-ready"
          value={confirmed > 0 ? `${confirmed} pair${confirmed > 1 ? "s" : ""}` : "0"}
          tone={confirmed > 0 ? "ok" : "neutral"}
          sub={`${avgCompleteness}% avg metadata completeness · ${readyInM2} pair${readyInM2 === 1 ? "" : "s"} matcher-ready in M2`}
        />
      </section>

      {/* Pipeline */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-slate-100">Scientific pipeline</h3>
            <p className="text-xs text-muted">
              Data is ready; Validate reflects the real registered-pair state; M2 PREPARE runs trace
              honestly in the Analysis workspace. The Match stage reflects M3 candidate-matching
              progress, the Trust stage reflects M4 independent verification, the Reliability
              stage reflects M5 spatial selection, the Register stage reflects M6 verified
              registration and the Metrics stage reflects M7 reproducible reports — BLOCKED is a
              first-class, honest outcome.
            </p>
          </div>
          <Badge tone={regCompletePairs > 0 ? "ok" : regRegistered ? "warn" : spatialCompletePairs > 0 ? "ok" : spatialTotal > 0 ? "warn" : trustedPairs > 0 ? "blue" : trustTotal > 0 ? "warn" : matchedTiles > 0 ? "blue" : readyInM2 > 0 ? "blue" : backend?.online ? "neutral" : "danger"}>
            <StatusDot state={regCompletePairs > 0 ? "ok" : regRegistered ? "warn" : spatialCompletePairs > 0 ? "ok" : spatialTotal > 0 ? "warn" : trustedPairs > 0 ? "info" : trustTotal > 0 ? "warn" : matchedTiles > 0 ? "info" : readyInM2 > 0 ? "info" : backend?.online ? "info" : "danger"} />
            {regCompletePairs > 0 ? "REGISTRATION complete" : regRegistered ? "REGISTRATION reported" : spatialCompletePairs > 0 ? "REGISTRATION ready to run" : spatialTotal > 0 ? "SPATIAL reported" : trustedPairs > 0 ? "SPATIAL ready to run" : trustTotal > 0 ? "TRUST reported" : matchedTiles > 0 ? "TRUST ready to run" : "PREPARE ready to report BLOCKED"}
          </Badge>
        </div>
        <Pipeline stages={pipeline} onStageClick={(st) => setModalStage(st)} />
      </section>

      {/* Two-column lower */}
      <section className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <div className="card p-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-100">System status</h3>
              <span className={`h-1.5 w-1.5 rounded-full ${anchor === "green" ? "bg-ok shadow-[0_0_8px_rgba(61,220,151,0.9)]" : "bg-danger"}`} />
            </div>
            <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <MetaRow k="Application" v={meta.application} />
              <MetaRow k="Project" v={meta.project_identifier} mono />
              <MetaRow k="Version" v={meta.version} />
              <MetaRow k="Milestone" v={meta.milestone ?? "M1"} />
              <MetaRow k="Tagline" v={meta.tagline} />
              <MetaRow k="Data root" v={settings.data_root} mono />
              <MetaRow k="Raw policy" v={s.raw_policy ?? "immutable"} />
              <MetaRow k="Source" v={s.source ? `${s.source.archive} · ${s.source.mission}` : "PRADAN"} />
              <MetaRow k="Last validation" v={s.last_validation_utc ? s.last_validation_utc.replace("T", " ").replace("+00:00", " UTC") : "never"} mono />
            </dl>
            {(metaError || statusError) && (
              <p className="mt-3 flex items-center gap-2 text-xs text-danger">
                <Icon.Alert /> {String(metaError?.message ?? statusError?.message ?? "data unavailable")}
              </p>
            )}
          </div>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h3 className="mb-3 text-sm font-bold text-slate-100">Real data progress</h3>
            {pairsRegistered === 0 ? (
              <EmptyState
                icon={<Icon.Info className="h-5 w-5" />}
                title="No pair registered yet"
                message={s.pairs_note ?? "Official downloads from PRADAN require an approved account. Place .img + .xml products under data/raw and register them in the Data workspace."}
                action={
                  <button className="btn-primary !px-3 !py-1.5 text-xs" onClick={() => onNavigate("data")}>
                    Open data workspace
                  </button>
                }
              />
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-white/[0.07] bg-space-900/50 p-3">
                  <div>
                    <p className="font-mono text-sm font-bold text-lunar-300">{firstPair?.pair_id ?? "—"}</p>
                    <p className="text-[11px] text-muted">
                      {s.pairs_valid} valid · {s.pairs_confirmed_overlap} confirmed overlap
                    </p>
                  </div>
                  <Badge tone={firstPair?.validation_status === "VALID" ? "ok" : "neutral"}>
                    {firstPair?.validation_status ?? "—"}
                  </Badge>
                </div>
                <p className="text-[11px] leading-relaxed text-muted">
                  Every registration writes a metadata record (pairs.json/CSV) and re-verifies SHA-256
                  hashes on validation. Raw files are never modified.
                </p>
              </div>
            )}
          </div>

          <div className="card p-5">
            <h3 className="mb-3 text-sm font-bold text-slate-100">Integration status</h3>
            <ul className="space-y-2.5 text-sm">
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Chandrayaan-2 source (ISSDC PRADAN)</span>
                <Badge tone="blue">Documented</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">OHRC–TMC-2 pair registered</span>
                <Badge tone={pairsRegistered > 0 ? "ok" : "neutral"}>{pairsRegistered} pair{pairsRegistered === 1 ? "" : "s"}</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Raw integrity (hashed, immutable)</span>
                <Badge tone={pairsValid > 0 ? "ok" : "warn"}>{pairsValid > 0 ? "Verified" : "Awaiting pair"}</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Overlap evidence</span>
                <Badge tone={confirmed > 0 ? "ok" : "neutral"}>{confirmed > 0 ? "Confirmed" : "Unconfirmed"}</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Preprocessing / conditioning</span>
                <Badge tone={readyInM2 > 0 ? "ok" : procRows && procRows.length > 0 ? "warn" : "neutral"}>
                  {readyInM2 > 0 ? "M2 ready" : procRows && procRows.length > 0 ? "M2 runs reported (blocked)" : "Awaiting validated pair"}
                </Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Correspondence search (M3)</span>
                <Badge tone={matchedTiles > 0 ? "ok" : totalCandidates > 0 ? "ok" : readyInM2 > 0 ? "blue" : "neutral"}>
                  {matchedTiles > 0 ? `${totalCandidates} candidates` : readyInM2 > 0 ? "Ready to match" : "Awaiting M2 readiness"}
                </Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Geometric verification (M4)</span>
                <Badge tone={trustedPairs > 0 ? "ok" : trustTotal > 0 ? "warn" : matchedTiles > 0 ? "blue" : "neutral"}>
                  {trustedPairs > 0 ? `${trustedPairs} trusted pair(s)` : trustTotal > 0 ? "Reported (blocked/rejected)" : matchedTiles > 0 ? "Ready to verify" : "Awaiting candidates"}
                </Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Trust Gate decision</span>
                <Badge tone={trustedPairs > 0 ? "ok" : "neutral"}>
                  {trustedPairs > 0 ? "Gate open (evidence-based)" : "Gate closed — never fabricated"}
                </Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Spatial selection (M5)</span>
                <Badge tone={spatialCompletePairs > 0 ? "ok" : spatialTotal > 0 ? "warn" : trustedPairs > 0 ? "blue" : "neutral"}>
                  {spatialCompletePairs > 0 ? `${spatialCompletePairs} pair(s) selected` : spatialTotal > 0 ? "Reported (blocked/insufficient)" : trustedPairs > 0 ? "Ready to select" : "Awaiting trusted evidence"}
                </Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Registration (M6)</span>
                <Badge tone={regCompletePairs > 0 ? "ok" : regRegistered ? "warn" : spatialCompletePairs > 0 ? "blue" : "neutral"}>
                  {regCompletePairs > 0
                    ? `${regCompletePairs} pair(s) registered successfully`
                    : regRegistered
                      ? "Reported (blocked/insufficient)"
                      : spatialCompletePairs > 0
                        ? "Ready to run"
                        : "Awaiting spatial selection"}
                </Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">AI explanatory layer</span>
                <Badge tone={settings.ai?.configured ? "ok" : "warn"}>
                  {settings.ai?.configured ? "Ready" : "Not configured"}
                </Badge>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <Modal
        open={!!modalStage}
        onClose={() => setModalStage(null)}
        title={`Pipeline stage — ${modalStage?.label ?? ""}`}
        footer={
          <button className="btn-ghost" onClick={() => setModalStage(null)}>
            Close
          </button>
        }
      >
        <p>
          Stage <strong className="text-slate-100">{modalStage?.label}</strong> is{" "}
          {modalStage?.state === "locked" ? "locked" : modalStage?.state === "complete" ? "complete" : "ready"}.
        </p>
        <p className="mt-2">
          {modalStage?.state === "locked"
            ? "This stage executes only on real, validated pairs and is gated by the preceding milestone (M2+). No processing is simulated."
            : modalStage?.state === "complete"
              ? modalStage?.id === "match"
                ? "M3 candidate correspondences were produced as observations — run the M4 Trust Gate in the Analysis workspace to independently verify them."
                : modalStage?.id === "trust"
                  ? "M4 Trust Gate produced per-tile geometric verification decisions — TRUSTED tiles are verified spatial evidence for model fitting, not absolute accuracy claims."
                  : modalStage?.id === "reliability"
                    ? "M5 spatial reliability represented the overlap scene as a grid and selected a supported reliability region — inputs are trusted evidence, outputs never claim scientific alignment."
                    : modalStage?.id === "register"
                      ? "M6 registration consumes only the M5-selected correspondences, fits a homography (affine fallback), validates it, and warps the source crop into the target sensor frame — every diagnostic is a measurement, never a claim of scientific alignment."
                      : "Validated against the registered pair(s) — raw integrity, metadata checks and M2 PREPARE readiness pass."
              : modalStage?.id === "preprocess"
                ? "M2 PREPARE ran but stopped transparently — a registered real pair still lacks documented ground geometry for overlap."
                : modalStage?.id === "match"
                  ? "M3 matching is ready to run in the Analysis workspace — it will record candidate correspondences as observations and stop honestly at the M4 Trust Gate."
                  : "The data architecture exists and official source (ISSDC PRADAN) is documented. Ingestion needs approved real products on disk."}
        </p>
      </Modal>

      <Modal
        open={lockModal}
        onClose={() => setLockModal(false)}
        title="Analysis workspace — PREPARE + MATCH + TRUST + SPATIAL + REGISTER"
        footer={
          <>
            <button className="btn-ghost" onClick={() => setLockModal(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={() => { setLockModal(false); onNavigate("analysis"); }}>
              Open Analysis
            </button>
          </>
        }
      >
        <p>M2 PREPARE registers, validates and transforms a pair to the matcher boundary; M3 runs the adaptive matcher and records candidate correspondences as observations; M4 then independently verifies them geometrically through the Trust Gate; M5 represents the overlap scene as a reliability grid and selects a supported region; M6 fits and validates a transform on that M5-selected evidence and warps the source into the target sensor frame.</p>
        <p className="mt-2">
          {spatialCompletePairs > 0
            ? "A pair has M5-selected evidence here, so the REGISTER run can execute now — trusted evidence in, diagnostics + registered product out, never a claim of scientific alignment."
            : readyInM2 > 0
              ? "A pair is matcher-ready here, so the full M3 MATCH + M4 TRUST + M5 SPATIAL (+ M6 REGISTER) flow can run now — explainable strategy routing, explicit candidate filters, an evidence-based Trust Gate and spatial selection."
              : "Register a validated pair first. M2 PREPARE to the match boundary will then run truthfully — BLOCKED is a first-class outcome."}
        </p>
      </Modal>
    </div>
  );
}

function MetaRow({ k, v, mono = false }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
      <dt className="shrink-0 text-muted">{k}</dt>
      <dd className={`min-w-0 truncate text-right text-slate-200 ${mono ? "font-mono text-xs" : "font-medium"}`}>
        {v === "" ? "—" : v}
      </dd>
    </div>
  );
}