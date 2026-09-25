import { useEffect, useState } from "react";

import { Badge, EmptyState, Icon, Modal, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet, apiPost } from "../api.js";

const TONE = {
  VERIFIED: "ok", REPRODUCIBLE: "ok", IDENTICAL: "ok", COMPLETE: "ok", PASS: "ok",
  CLEAR: "ok", CLEAN: "ok", READY: "ok", RESET: "ok",
  DRIFTED: "danger", INTEGRITY_DEGRADED: "danger", FAIL: "danger", INVALID: "danger",
  NOT_MEASURED: "warn", BLOCKED: "warn", HOLD: "warn", INCOMPLETE: "warn", PARTIAL: "warn",
  UNRECORDED: "warn",
  NOT_RUN: "neutral", NOT_CONFIGURED: "neutral", NOT_AVAILABLE: "neutral",
};

function tone(status) {
  return TONE[String(status ?? "").toUpperCase()] ?? "neutral";
}

function useFetch(path) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    if (!path) return undefined;
    setError(null);
    apiGet(path)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [path]);
  return { data, error, setData };
}

function Stat({ label, value, tone = "neutral", sub }) {
  const colors = { ok: "text-ok", warn: "text-warn", danger: "text-danger", neutral: "text-slate-100" };
  return (
    <div className="card card-hover p-4">
      <div className="mb-2 flex items-center gap-2">
        <StatusDot state={tone === "neutral" ? "info" : tone} />
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</p>
      </div>
      <p className={`truncate text-lg font-extrabold tracking-tight ${colors[tone]}`}>{value}</p>
      {sub && <p className="mt-1 text-xs leading-relaxed text-muted">{sub}</p>}
    </div>
  );
}

function Row({ k, v, mono = false }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
      <dt className="shrink-0 text-muted">{k}</dt>
      <dd className={`min-w-0 truncate text-right text-slate-200 ${mono ? "font-mono text-xs" : "font-medium"}`}>
        {v == null || v === "" ? "—" : v}
      </dd>
    </div>
  );
}

function Funnel({ runs }) {
  const cols = [
    ["Run", (r) => <span key="r" className="font-semibold text-lunar-300">RUN {String(r.key)}</span>],
    ["Candidates M3", (r) => <span key="c" className="font-mono">{r.v?.funnel?.candidates ?? "—"}</span>],
    ["Trusted M4", (r) => <span key="t" className="font-mono">{r.v?.funnel?.trusted ?? "—"}</span>],
    ["Selected M5", (r) => <span key="s" className="font-mono">{r.v?.funnel?.selected ?? "—"}</span>],
    ["Registered M6", (r) => <span key="g" className="font-mono">{r.v?.funnel?.registered ?? "—"}</span>],
  ];
  const runEntries = Object.entries(runs ?? {}).map(([key, v]) => ({ key, v }));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-muted">
            {cols.map(([h]) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {runEntries.map((r) => (
            <tr key={r.key} className="border-b border-white/[0.05]">
              {cols.map(([, render]) => <td key={String(r.key)} className="px-3 py-2 text-slate-200">{render(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Provenance({ chain }) {
  if (!Array.isArray(chain) || !chain.length) return <p className="text-xs text-muted">No provenance chain recorded.</p>;
  return (
    <ol className="space-y-2">
      {chain.map((s) => (
        <li key={s.milestone} className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.06] bg-space-900/50 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <Badge tone={tone(s.status)}>{s.milestone}</Badge>
            <span className="truncate text-xs text-slate-300">
              {s.artifact_count} artifact{s.artifact_count === 1 ? "" : "s"}
              {s.configuration_id ? ` · ${s.configuration_id}` : ""}
            </span>
          </div>
          <Badge tone={tone(s.status)}>{s.status}</Badge>
        </li>
      ))}
    </ol>
  );
}

function inline(text) {
  return String(text).replace(/\*\*(.+?)\*\*/g, (_, m) => `[${m}]`).replace(/`([^`]+)`/g, (_, m) => m);
}

function Markdown({ text }) {
  const rows = [];
  let buf = [];
  const flush = () => {
    if (buf.length) {
      rows.push(<p key={rows.length} className="mb-2 text-sm leading-relaxed text-muted">{inline(buf.join(" "))}</p>);
      buf = [];
    }
  };
  for (const line of (text ?? "").split("\n")) {
    const h2 = line.match(/^##\s+(.+)/);
    const h3 = line.match(/^###\s+(.+)/);
    const h1 = line.match(/^#\s+(.+)/) && !line.startsWith("##");
    const li = line.match(/^\s*[-*]\s+(.+)/);
    if (h1) rows.push(<h1 key={rows.length} className="mb-2 mt-3 text-base font-bold text-slate-100">{inline(h1[1])}</h1>);
    else if (h2) { flush(); rows.push(<h2 key={rows.length} className="mb-1 mt-3 text-sm font-bold text-slate-100">{inline(h2[1])}</h2>); }
    else if (h3) { flush(); rows.push(<h3 key={rows.length} className="mb-1 mt-2 text-[13px] font-bold text-lunar-300">{inline(h3[1])}</h3>); }
    else if (li) { flush(); rows.push(<div key={rows.length} className="mb-1 flex gap-2 text-sm leading-relaxed text-muted"><span className="text-lunar-400">•</span><span>{inline(li[1])}</span></div>); }
    else if (!line.trim()) flush();
    else buf.push(line.trim());
  }
  flush();
  return <div className="space-y-1">{rows}</div>;
}

export default function Evidence({ notify }) {
  const { data: status, error: statusError, setData: setStatus } = useFetch("/m13/status");
  const { data: list, error: listError } = useFetch("/m13/evidence");
  const { data: reports, error: reportsError } = useFetch("/m13/reports");
  const [detail, setDetail] = useState(null);
  const [report, setReport] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  if (!status || !list) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <Badge tone="gold">CHANDRASUTRA · SIH26166 · Final Release</Badge>
          <h2 className="text-2xl font-extrabold tracking-tight text-slate-100">Final evidence &amp; reports</h2>
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            Frozen scientific evidence, reproducibility record, provenance chain and milestone reports.
          </p>
        </div>
        {(statusError || listError) ? (
          <div className="card p-4">
            <p className="flex items-center gap-2 text-sm text-danger">
              <Icon.Alert /> {String(statusError?.message ?? listError?.message ?? "Evidence API unavailable")}
            </p>
          </div>
        ) : <PageSkeleton rows={4} />}
      </div>
    );
  }

  const ev = status.evidence || {};
  const prov = status.provenance || {};
  const repro = status.reproducibility || {};
  const meas = status.measurements || {};

  const openDetail = async (expId) => {
    setActionError(null);
    try { setDetail(await apiGet(`/m13/evidence/${encodeURIComponent(expId)}`)); }
    catch (e) { setActionError(e); }
  };
  const openReport = async (name) => {
    setActionError(null);
    try { const b = await apiGet(`/m13/report/${encodeURIComponent(name)}`); setReport({ name: b.name, text: b.markdown }); }
    catch (e) { console.error(e); }
  };
  const runReset = async () => {
    setResetting(true);
    setActionError(null);
    try {
      const ok = await apiPost("/m13/demo/reset", {});
      setConfirmReset(false);
      notify({
        title: "Demonstration reset",
        message: ok.evidence_preserved
          ? "Transient demo state cleared; frozen evidence re-verified untouched."
          : "Transient demo state cleared with warnings — see evidence list.",
        tone: ok.evidence_preserved ? "ok" : "danger",
      });
      setStatus(await apiGet("/m13/status"));
    } catch (e) { setActionError(e); }
    finally { setResetting(false); }
  };

  const verdicts = repro.subject_verdicts || {};

  return (
    <div className="space-y-6">
      <section className="panel relative overflow-hidden p-5">
        <div className="pointer-events-none absolute inset-0 grid-texture opacity-40" aria-hidden />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl space-y-2.5">
            <p className="eyebrow">Frozen Evidence Vault · M13</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="gold">CHANDRASUTRA v{status.app?.release_version ?? "1.0.0"}</Badge>
              <Badge tone="gold">M13 Final Release</Badge>
              <Badge tone="neutral">{status.app?.project_identifier ?? "SIH26166"}</Badge>
              {status.real_data?.status === "BLOCKED" && (
                <Badge tone="warn">Synthetic demonstration — not a real lunar observation</Badge>
              )}
            </div>
            <h2 className="text-xl font-extrabold tracking-tight text-slate-100">Frozen evidence · verified end-to-end</h2>
            <p className="text-sm leading-relaxed text-muted">
              Experiment <span className="font-mono text-lunar-300">{ev.experiment_id ?? "—"}</span> (pair{" "}
              <span className="font-mono text-lunar-300">{ev.pair_id ?? "—"}</span>) is frozen under digest{" "}
              <code className="rounded bg-white/[0.06] px-1 py-0.5 font-mono text-[11px] text-lunar-300">
                {(ev.final_evidence_sha256 ?? "").slice(0, 20)}…
              </code>{" "}
              Provenance M1–M7 recorded with configuration IDs; M8/M9 open (no per-pair deep-matcher run, no AI
              provider in this offline environment) — reported as PARTIAL / HOLD, never fabricated. Physical accuracy
              is NOT_CLAIMED without a reference dataset.
            </p>
          </div>
          <button onClick={() => setConfirmReset(true)} className="btn-ghost !px-3 !py-1.5 text-xs" disabled={resetting}>
            <Icon.Refresh className="h-3.5 w-3.5" /> {resetting ? "Resetting…" : "Reset demonstration"}
          </button>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Stat label="Evidence integrity" value={ev.verify_status ?? "PENDING"} tone={tone(ev.verify_status)}
          sub={`${ev.experiment_id?.slice(0, 16) ?? "—"}… · ${ev.artifact_count ?? 0} artifacts`} />
        <Stat label="Reproducibility" value={repro.status ?? "NOT_RECORDED"} tone={tone(repro.status)}
          sub={Object.keys(verdicts).length
            ? `${Object.values(verdicts).filter((v) => v === "IDENTICAL").length}/${Object.keys(verdicts).length} subjects identical · runs A/B/C`
            : "No reproducibility record in data root"} />
        <Stat label="Scientific gate" value={ev.gate_condition ?? "—"} tone={tone(ev.gate_condition)}
          sub={ev.gate_reason ?? ""} />
        <Stat label="Provenance" value={prov.status ? `PARTIAL · HOLD (${prov.status})` : "UNRECORDED"} tone="warn"
          sub={prov.missing_stages?.length ? `Open stages: ${prov.missing_stages.join(", ")}` : "Full chain complete"} />
        <Stat label="Audits" value={ev.audit_status ?? "—"} tone={tone(ev.audit_status)}
          sub="Independent raw-integrity recompute was performed" />
        <Stat label="AI cross-check" value={ev.crosscheck_status ?? "—"} tone={tone(ev.crosscheck_status)}
          sub={ev.crosscheck_violations?.length ? `${ev.crosscheck_violations.length} violation(s)` : "No confirmed violations"} />
        <Stat label="Security scan" value={ev.security_status ?? "—"} tone={tone(ev.security_status)}
          sub="Frozen package scanned for secrets" />
        <Stat label="Real data" value={status.real_data?.status ?? "—"} tone={tone(status.real_data?.status)}
          sub={status.real_data?.detail ?? ""} />
      </section>

      <section className="grid gap-5 lg:grid-cols-5">
        <div className="card space-y-4 p-5 lg:col-span-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-100">Reproducibility record</h3>
            <Badge tone={tone(repro.status)}><StatusDot state={tone(repro.status) === "neutral" ? "info" : tone(repro.status)} /> {repro.status ?? "NOT_RECORDED"}</Badge>
          </div>
          {Object.keys(repro.runs ?? {}).length ? <Funnel runs={repro.runs} /> : <p className="text-xs text-muted">No reproducibility record present.</p>}
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <Row k="Configuration fingerprint" v={ev.configuration_fingerprint ?? "—"} mono />
            <Row k="Transform hash (A/B/C)" v={`${repro.runs?.A?.transform_matrix_hash?.slice(0, 12) ?? "—"} / ${repro.runs?.B?.transform_matrix_hash?.slice(0, 12) ?? "—"} / ${repro.runs?.C?.transform_matrix_hash?.slice(0, 12) ?? "—"}`} mono />
            <Row k="Report hash (M7 report.md)" v={repro.runs?.A?.report_md_sha256 ?? "—"} mono />
          </dl>
        </div>
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h3 className="mb-3 text-sm font-bold text-slate-100">Measurements</h3>
            {meas.status === "NOT_MEASURED" ? (
              <p className="text-xs leading-relaxed text-muted">
                Hosted latency is <strong className="text-warn">NOT_MEASURED</strong> — no public deployment was
                provisioned from this offline environment. Local API timings are in{" "}
                <code className="rounded bg-white/[0.06] px-1 py-0.5 font-mono text-[11px]">reports/m13_performance.json</code>{" "}
                when present.
              </p>
            ) : (
              <dl className="space-y-2 text-sm">
                {Object.entries(meas).filter(([k]) => k !== "status").map(([k, v]) => (
                  <Row key={k} k={k.replaceAll("_", " ")} v={String(v)} mono />
                ))}
              </dl>
            )}
          </div>
          <div className="card p-5">
            <h3 className="mb-3 text-sm font-bold text-slate-100">Reference dataset</h3>
            <div className="flex items-center gap-2">
              <StatusDot state={status.reference?.status === "AVAILABLE" ? "ok" : "info"} />
              <span className="text-sm font-semibold text-slate-200">{status.reference?.status ?? "NOT_AVAILABLE"}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-muted">
              Physical accuracy is NOT_CLAIMED without an independent reference dataset. This release demonstrates
              engineering repeatability on the frozen TEST_FIXTURE corpus.
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="card space-y-3 p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-100">Provenance chain</h3>
            <Badge tone={prov.missing_stages?.length ? "warn" : "ok"}>{prov.missing_stages?.length ? "PARTIAL · HOLD" : "COMPLETE"}</Badge>
          </div>
          <Provenance chain={prov.chain} />
          {!!prov.missing_stages?.length && (
            <p className="rounded-lg border border-warn/30 bg-warn/5 p-3 text-xs leading-relaxed text-warn">
              Provenance is partially recorded and held open. No hashes were fabricated for the missing stages
              (M8 per-pair deep-matcher run, M9 AI evidence packet). Repair needs real artifacts with verifiable hashes.
            </p>
          )}
        </div>
        <div className="card space-y-3 p-5">
          <h3 className="text-sm font-bold text-slate-100">Frozen evidence packages</h3>
          {list?.packages?.length ? list.packages.map((p) => (
            <button key={p.experiment_id} onClick={() => openDetail(p.experiment_id)}
              className="card card-hover w-full p-3 text-left">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm font-bold text-lunar-300">{p.experiment_id}</p>
                  <p className="mt-0.5 text-[11px] text-muted">pair {p.pair_id ?? "—"} · {p.artifact_count ?? 0} artifacts</p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="font-mono text-[10px] leading-tight text-muted">{(p.final_evidence_sha256 ?? "").slice(0, 12)}…</p>
                  <Badge tone="ok">FROZEN</Badge>
                </div>
              </div>
            </button>
          )) : (
            <EmptyState icon={<Icon.File className="h-5 w-5" />} title="No frozen evidence packages"
              message="Run the M12 evidence freeze and seed the data root with scripts/m13_release_prep.py." />
          )}
          {actionError && (
            <p className="flex items-center gap-2 text-xs text-danger"><Icon.Alert /> {String(actionError.message)}</p>
          )}
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="card space-y-3 p-5">
          <h3 className="text-sm font-bold text-slate-100">Report centre</h3>
          {reports?.reports?.length ? (
            <ul className="space-y-1.5">
              {reports.reports.map((r) => (
                <li key={r.name}>
                  <button onClick={() => openReport(r.name)}
                    className="flex w-full items-center justify-between gap-3 rounded-lg border border-white/[0.06] bg-space-900/50 px-3 py-2 text-left transition hover:border-white/[0.16] hover:bg-white/[0.03]">
                    <span className="truncate text-sm text-slate-200">{r.name}</span>
                    <Badge tone={r.kind === "scientific" ? "blue" : "neutral"}>{r.kind}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">{reportsError ? `Reports unavailable: ${reportsError.message}` : "No reports in data root."}</p>
          )}
        </div>
        <div className="card space-y-3 p-5">
          <h3 className="text-sm font-bold text-slate-100">Release stance</h3>
          <ul className="space-y-2.5 text-sm">
            <li className="flex items-center justify-between gap-3"><span className="text-muted">Scientific gate</span><Badge tone="warn">{ev.gate_path ?? "—"} · {ev.gate_condition ?? "—"}</Badge></li>
            <li className="flex items-center justify-between gap-3"><span className="text-muted">Reproducibility</span><Badge tone="ok">{repro.status ?? "—"}</Badge></li>
            <li className="flex items-center justify-between gap-3"><span className="text-muted">Real mission data</span><Badge tone={status.real_data?.status === "BLOCKED" ? "warn" : "ok"}>{status.real_data?.status ?? "—"}</Badge></li>
            <li className="flex items-center justify-between gap-3"><span className="text-muted">Reference dataset</span><Badge tone="neutral">{status.reference?.status ?? "NOT_AVAILABLE"}</Badge></li>
            <li className="flex items-center justify-between gap-3"><span className="text-muted">AI capability</span><Badge tone="neutral">{status.ai?.state ?? "NOT_CONFIGURED"}</Badge></li>
            <li className="flex items-center justify-between gap-3"><span className="text-muted">Deep matcher</span><Badge tone="neutral">{status.deep_matcher?.state ?? "NOT_AVAILABLE"}</Badge></li>
            <li className="flex items-center justify-between gap-3"><span className="text-muted">Provenance</span><Badge tone="warn">PARTIAL · HOLD</Badge></li>
          </ul>
        </div>
      </section>

      <Modal open={!!detail} onClose={() => setDetail(null)}
        title={`Evidence package — ${detail?.experiment_id ?? ""}`}
        footer={<button className="btn-ghost" onClick={() => setDetail(null)}>Close</button>}>
        {detail.error ? <p className="text-danger">{detail.error}</p> : (
          <div className="space-y-3">
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <Row k="Experiment" v={detail?.experiment_id} mono />
              <Row k="Pair" v={detail?.pair_id} mono />
              <Row k="Schema" v={detail?.manifest?.schema_version} mono />
              <Row k="Artifacts" v={detail?.manifest?.artifact_count} mono />
              <Row k="Verify" v={detail?.verify?.status} mono />
              <Row k="Digest" v={(detail?.final_evidence_sha256 ?? "").slice(0, 20)} mono />
            </dl>
            <div className="flex flex-wrap gap-2">
              <Badge tone="ok">SECURITY {detail?.security?.status ?? "—"}</Badge>
              <Badge tone="ok">CROSSCHECK {detail?.crosscheck?.status ?? "—"}</Badge>
              <Badge tone="neutral">PROVENANCE {detail?.provenance?.status ?? "—"}</Badge>
            </div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted">Artifact index</h4>
            <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {(detail?.manifest?.artifacts ?? []).map((a) => (
                <div key={a.path} className="flex items-center justify-between gap-3 rounded bg-white/[0.03] px-2 py-1.5">
                  <span className="truncate font-mono text-[11px] text-slate-300">{a.path}</span>
                  <span className="shrink-0 font-mono text-[10px] text-muted">{a.sha256.slice(0, 10)}…</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!report} onClose={() => setReport(null)}
        title={`Report — ${report?.name ?? ""}`}
        footer={<button className="btn-ghost" onClick={() => setReport(null)}>Close</button>}>
        <div className="max-h-[70vh] overflow-y-auto pr-1">
          <Markdown text={report?.text ?? ""} />
        </div>
      </Modal>

      <Modal open={confirmReset} onClose={() => setConfirmReset(false)}
        title="Reset the demonstration?"
        footer={
          <>
            <button className="btn-ghost" onClick={() => setConfirmReset(false)} disabled={resetting}>Cancel</button>
            <button className="btn-primary" onClick={runReset} disabled={resetting}>{resetting ? "Verifying…" : "Reset"}</button>
          </>
        }>
        <p>Clears transient demonstration state and re-verifies every frozen evidence package. No scientific artifact,
          raw image or report is written, renamed or deleted.</p>
        {actionError && <p className="mt-2 flex items-center gap-2 text-xs text-danger"><Icon.Alert /> {String(actionError.message)}</p>}
      </Modal>
    </div>
  );
}