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

function statusTone(status) {
  if (status === "AVAILABLE") return "ok";
  if (status === "BLOCKED" || status === "NOT_RUN") return "warn";
  if (status === "REFERENCE_UNAVAILABLE") return "neutral";
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

function fmtValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(+v.toFixed?.(4));
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export default function MetricsPanel({ pairId, notify }) {
  const { canMutate } = useAuth();
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [experiment, setExperiment] = useState(null);
  const [markdown, setMarkdown] = useState(null);
  const [provenance, setProvenance] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [modal, setModal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      let st = null;
      try {
        st = await apiGet(`/metrics/${pairId}/status`);
        setStatus(st);
      } catch (e) {
        setError(e);
        return;
      }
      const get = async (ep, key) => {
        try {
          const r = await apiGet(`/metrics/${pairId}/${ep}`);
          return key ? r[key] : r;
        } catch {
          return null;
        }
      };
      if (st.state === "COMPLETE") {
        setSummary(await get("summary", "summary"));
        setMetrics((await get("metrics", "metrics")) ?? []);
        setExperiment(await get("experiment", "experiment"));
        try {
          const md = await apiGet(`/metrics/${pairId}/report/markdown`);
          setMarkdown(md ?? null);
        } catch {
          setMarkdown(null);
        }
      } else {
        setSummary(null);
        setMetrics([]);
        setExperiment(null);
        setMarkdown(null);
        setProvenance(null);
        setManifest(null);
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
  }, [pairId]);

  async function runMetrics() {
    setBusy(true);
    setError(null);
    try {
      const st = await apiPost(`/metrics/${pairId}/run`, {
        metrics_configuration_id: "MT-M7-001",
      });
      setStatus(st);
      if (st.state === "BLOCKED") {
        notify({
          title: `METRICS blocked · ${st.block_code ?? "?"}`,
          message: st.reasons?.join(", ") ?? "Blocked honestly at the metrics gate.",
          tone: "warn",
        });
      } else if (st.state === "COMPLETE") {
        notify({
          title: `Metrics complete · ${pairId}`,
          message: "Quantitative metrics and reproducible experiment report produced.",
          tone: "ok",
        });
      } else if (st.state === "FAILED") {
        notify({
          title: `METRICS failed · ${pairId}`,
          message: st.reasons?.join(", ") ?? "No trustworthy metrics artifact could be produced.",
          tone: "warn",
        });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "METRICS run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function resetMetrics() {
    setBusy(true);
    try {
      const r = await apiPost(`/metrics/${pairId}/reset`);
      setStatus(r.status);
      setSummary(null);
      setMetrics([]);
      setExperiment(null);
      setMarkdown(null);
      setProvenance(null);
      setManifest(null);
      notify({
        title: `${pairId} metrics reset`,
        message: "Only derived metrics artifacts were removed. M6/M5/M4/M3/M2/raw untouched.",
        tone: "ok",
      });
    } catch (e) {
      notify({ title: "METRICS reset failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function openModal(kind) {
    try {
      if (kind === "provenance") {
        setProvenance((await apiGet(`/metrics/${pairId}/provenance`)).provenance);
      } else if (kind === "manifest") {
        setManifest((await apiGet(`/metrics/${pairId}/manifest`)).manifest);
      }
      setModal(kind);
    } catch (e) {
      notify({ title: "No artifact", message: e.message, tone: "danger" });
    }
  }

  const available = metrics.filter((m) => m.status === "AVAILABLE").length;
  const blocked = metrics.filter((m) => m.status === "BLOCKED" || m.status === "NOT_RUN").length;
  const referenceUnavailable = metrics.filter((m) => m.status === "REFERENCE_UNAVAILABLE").length;
  const physicalAccuracy = metrics.find((m) => m.metric_id === "PHYSICAL_ACCURACY");
  const recomputeConsistent = summary?.recomputation_consistent;

  return (
    <div className="space-y-4">
      {/* controls */}
      <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="space-y-1">
          <p className="text-xs font-semibold text-slate-200">
            State · <span className="font-mono text-lunar-300">{status?.state ?? "NOT_STARTED"}</span>
          </p>
          <p className="text-[11px] text-muted">
            Metrics are measurements of pipeline evidence, never proof of physical accuracy.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run reproducible metrics" : "Analyst or admin required"} onClick={runMetrics}>
            <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "Run metrics"}
          </button>
          <button className="btn-ghost" disabled={busy || !canMutate} title={canMutate ? "Reset pair state" : "Analyst or admin required"} onClick={resetMetrics}>
            <Icon.Refresh className="h-4 w-4" /> Reset
          </button>
        </div>
      </div>

      {error && (
        <p className="card flex items-center gap-2 p-3 text-xs text-danger">
          <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
        </p>
      )}

      {status?.block_code && (
        <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-warn">
            <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {status.block_code}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{status.reasons?.join(", ") ?? ""}</p>
        </div>
      )}

      {status?.state === "COMPLETE" && summary && (
        <>
          {/* summary cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="card p-3.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted">Metrics</p>
              <p className="mt-1 text-xl font-extrabold text-slate-100">{summary.metrics_total}</p>
              <p className="text-[10.5px] text-muted">{available} available · {blocked} blocked</p>
            </div>
            <div className="card p-3.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted">Recomputation</p>
              <p className="mt-1 flex items-center gap-2 text-xl font-extrabold text-slate-100">
                {recomputeConsistent === true ? "consistent" : recomputeConsistent === false ? "mismatch" : "—"}
                {recomputeConsistent === true ? <span className="h-2 w-2 rounded-full bg-ok" /> : recomputeConsistent === false ? <span className="h-2 w-2 rounded-full bg-warn" /> : null}
              </p>
              <p className="text-[10.5px] text-muted">independent re-derivation vs recorded</p>
            </div>
            <div className="card p-3.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted">Reference</p>
              <p className="mt-1 text-xl font-extrabold text-slate-100">{summary.reference_dataset ?? "NOT_AVAILABLE"}</p>
              <p className="text-[10.5px] text-muted">{referenceUnavailable} reference metrics</p>
            </div>
            <div className="card p-3.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted">Experiment</p>
              <p className="mt-1 font-mono text-sm font-extrabold text-lunar-300">{experiment?.experiment_id ?? "—"}</p>
              <p className="text-[10.5px] text-muted">deterministic identity</p>
            </div>
          </div>

          {/* toolstrip */}
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-ghost !px-3 !py-1.5 text-xs" onClick={() => setModal("markdown")}>
              <Icon.Chevron className="h-3.5 w-3.5" /> Report (.md)
            </button>
            <button className="btn-ghost !px-3 !py-1.5 text-xs" onClick={() => openModal("provenance")}>
              <Icon.Database className="h-3.5 w-3.5" /> Provenance
            </button>
            <button className="btn-ghost !px-3 !py-1.5 text-xs" onClick={() => openModal("manifest")}>
              <Icon.Grid className="h-3.5 w-3.5" /> Manifest
            </button>
            <Badge tone={physicalAccuracy?.status === "REFERENCE_UNAVAILABLE" ? "neutral" : "warn"}>
              physical_accuracy: NOT_AVAILABLE
            </Badge>
          </div>

          {/* metric table */}
          <div className="card p-4">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-xs font-bold text-slate-100">Metric records</h4>
              <Badge tone="blue">{metrics.length} metrics</Badge>
            </div>
            <div className="max-h-[380px] overflow-auto">
              <table className="w-full text-left text-[11px]">
                <thead className="sticky top-0 bg-space-900/90 text-[10px] uppercase tracking-wider text-muted">
                  <tr>
                    <th className="px-2 py-1.5">metric_id</th>
                    <th className="px-2 py-1.5">value</th>
                    <th className="px-2 py-1.5">unit</th>
                    <th className="px-2 py-1.5">scientific status</th>
                    <th className="px-2 py-1.5">status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {metrics.map((m) => (
                    <tr key={m.metric_id}>
                      <td className="px-2 py-1.5 font-mono text-[10.5px] text-slate-200">{m.metric_id}</td>
                      <td className="px-2 py-1.5 font-mono text-slate-300">{fmtValue(m.value)}</td>
                      <td className="px-2 py-1.5 text-muted">{m.unit ?? "—"}</td>
                      <td className="px-2 py-1.5 text-muted">{m.scientific_status}</td>
                      <td className="px-2 py-1.5">
                        <Badge tone={statusTone(m.status)}>{m.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {status?.state === "NOT_STARTED" && (
        <div className="card p-4 text-center text-xs text-muted">
          No metrics run yet for <span className="font-mono text-slate-200">{pairId}</span>. Registration must be
          COMPLETE first — then run Metrics to produce quantitative diagnostics and a reproducible report.
        </div>
      )}

      {/* modals */}
      <Modal open={modal === "markdown"} onClose={() => setModal(null)} title={`Reproducible report · ${pairId}`}>
        {markdown && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {markdown}
          </pre>
        )}
      </Modal>
      <Modal open={modal === "provenance"} onClose={() => setModal(null)} title={`Provenance (M2→M7) · ${pairId}`}>
        {provenance && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(provenance, null, 2)}
          </pre>
        )}
      </Modal>
      <Modal open={modal === "manifest"} onClose={() => setModal(null)} title={`Metrics manifest · ${pairId}`}>
        {manifest && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(manifest, null, 2)}
          </pre>
        )}
      </Modal>
    </div>
  );
}