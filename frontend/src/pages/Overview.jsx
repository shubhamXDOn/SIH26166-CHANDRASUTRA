import { useEffect, useState } from "react";

import Pipeline, { PIPELINE } from "../components/Pipeline.jsx";
import { Badge, EmptyState, Icon, Modal, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet } from "../api.js";

const M0_PIPELINE_STATES = {
  data: "ready",
  validate: "locked",
  preprocess: "locked",
  match: "locked",
  trust: "locked",
  register: "locked",
  report: "locked",
};

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
  const [modalStage, setModalStage] = useState(null);
  const [lockModal, setLockModal] = useState(false);

  const pipeline = PIPELINE.map((s) => ({ ...s, state: M0_PIPELINE_STATES[s.id] }));

  if (!meta) {
    const offline = backend?.online === false;
    return (
      <div className="space-y-6">
        <div className="space-y-4">
          <Badge tone="gold">M0 · Foundation build</Badge>
          <h2 className="text-2xl font-extrabold tracking-tight text-slate-100">
            Trustworthy adaptive lunar image correspondence & registration
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            A reliability-first platform over heterogeneous Chandrayaan-2 imagery: validated data,
            condition-aware strategy selection, independent verification and principled abstention.
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
  const dirs = meta.data_directories || [];
  const expectedNonRaw = dirs.filter((d) => !d.is_raw).length;
  const nonRawPresent = dirs.filter((d) => !d.is_raw && d.exists).length;
  const dirsPresent = dirs.filter((d) => d.exists).length;
  const foundationReady = nonRawPresent === expectedNonRaw;
  const readyLabel = foundationReady ? "Foundation layout ready" : "Foundation layout staged";

  return (
    <div className="space-y-6">
      {/* Hero */}
      <section className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-2xl space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="gold">Milestone M0 — Foundation</Badge>
            <Badge tone="blue">Real data: M1</Badge>
          </div>
          <h2 className="text-2xl font-extrabold leading-tight tracking-tight text-slate-100 sm:text-[1.7rem]">
            Trustworthy adaptive <span className="text-lunar-400 text-glow">lunar image</span>{" "}
            correspondence & registration
          </h2>
          <p className="text-sm leading-relaxed text-muted">
            A reliability-first scientific platform over heterogeneous Chandrayaan-2 imagery
            (OHRC · TMC-2): validated data, condition-aware matcher strategy, independent
            verification, measurable diagnostics and principled abstention.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-3">
          <button onClick={() => onNavigate("data")} className="btn-primary">
            <Icon.Database className="h-4 w-4" /> Explore data readiness
          </button>
          <button
            onClick={() => setLockModal(true)}
            className="btn-ghost"
            disabled={!meta}
            title="Requires a registered pair (M1)"
          >
            <Icon.Activity className="h-4 w-4" /> Begin analysis
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
          sub={`${settings.app_env ?? "development"} · v${meta.version ?? "—"}`}
        />
        <StatCard
          label="Data readiness"
          value={readyLabel}
          tone={foundationReady ? "ok" : "warn"}
          sub={`${dirsPresent}/${dirs.length} logical directories present · raw awaiting M1`}
        />
        <StatCard
          label="Registered pairs"
          value="0"
          sub="First OHRC–TMC-2 pair arrives in M1"
        />
        <StatCard
          label="AI insights"
          value={settings.ai?.configured ? "Ready" : "Not configured"}
          tone={settings.ai?.configured ? "ok" : "warn"}
          sub={`${settings.ai?.service ?? "Gemini"} · explanatory layer only`}
        />
      </section>

      {/* Pipeline */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-slate-100">Scientific pipeline</h3>
            <p className="text-xs text-muted">
              Stages unlock as real data and processing arrive. Nothing below is simulated.
            </p>
          </div>
          <Badge tone={backend?.online ? "ok" : "danger"}>
            <StatusDot state={backend?.online ? "ok" : "danger"} pulse={backend?.online} />
            {backend?.online ? "Pipeline dormant" : "Backend offline"}
          </Badge>
        </div>
        <Pipeline stages={pipeline} onStageClick={(s) => setModalStage(s)} />
      </section>

      {/* Two-column lower */}
      <section className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <div className="card p-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-100">System status</h3>
              <span className="h-1.5 w-1.5 rounded-full bg-ok shadow-[0_0_8px_rgba(61,220,151,0.9)]" />
            </div>
            <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <MetaRow k="Application" v={meta.application} />
              <MetaRow k="Version" v={meta.version} />
              <MetaRow k="Environment" v={settings.app_env} mono />
              <MetaRow k="Debug mode" v={String(Boolean(settings.app_debug))} />
              <MetaRow k="Auth foundation" v={settings.auth?.configured ? "configured" : "not configured"} />
              <MetaRow k="AI service" v={settings.ai?.configured ? "configured" : "not configured"} />
              <MetaRow k="Data root" v={settings.data_root} mono />
              <MetaRow k="CORS origins" v={(settings.cors_origins || []).join("  ·  ")} mono />
            </dl>
            {metaError && (
              <p className="mt-3 flex items-center gap-2 text-xs text-danger">
                <Icon.Alert /> {String(metaError?.message ?? metaError)}
              </p>
            )}
          </div>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h3 className="mb-3 text-sm font-bold text-slate-100">Recent activity</h3>
            <EmptyState
              icon={<Icon.Chart className="h-5 w-5" />}
              title="No experiment run yet"
              message="No correspondence or registration result exists in M0 — the pipeline is intentionally dormant until real data integration (M1)."
            />
          </div>
          <div className="card p-5">
            <h3 className="mb-3 text-sm font-bold text-slate-100">Integration status</h3>
            <ul className="space-y-2.5 text-sm">
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Chandrayaan-2 data source (ISSDC PRADAN)</span>
                <Badge tone="warn">Documented</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">OHRC–TMC-2 pair registered</span>
                <Badge tone="neutral">0 pairs</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Condition-aware strategy</span>
                <Badge tone="neutral">M2+</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Trust Gate reliability</span>
                <Badge tone="neutral">M3+</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Gemini explanatory layer</span>
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
          {modalStage?.state === "ready" ? "ready at the foundation level" : "locked"}.
        </p>
        <p className="mt-2">
          {modalStage?.state === "ready"
            ? "The data architecture exists and the official source is documented. Actual ingestion begins in M1."
            : "This stage executes only on real, validated pairs. It will be enabled by its milestone — no processing is simulated in M0."}
        </p>
      </Modal>

      <Modal
        open={lockModal}
        onClose={() => setLockModal(false)}
        title="Begin analysis — unavailable"
        footer={
          <>
            <button className="btn-ghost" onClick={() => setLockModal(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={() => { setLockModal(false); onNavigate("data"); }}>
              Go to data readiness
            </button>
          </>
        }
      >
        <p>An analysis requires at least one registered, overlap-confirmed OHRC–TMC-2 pair.</p>
        <p className="mt-2">
          M0 registers no pairs on purpose. The first documented pair is acquired from ISSDC PRADAN
          in M1 — this is not faked today.
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