import { useEffect, useMemo, useState } from "react";

import { Badge, Icon, Modal } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

const M8_STAGES = [
  { id: "checking_prerequisites", label: "Gates", desc: "M2/M3 prerequisites" },
  { id: "resolving_capabilities", label: "Capabilities", desc: "Live runtime probe" },
  { id: "routing", label: "Routing", desc: "Categorical strategy order" },
  { id: "running_matchers", label: "Matchers", desc: "Classical + deep" },
  { id: "writing_candidates", label: "Candidates", desc: "Unified contract" },
  { id: "benchmark", label: "Benchmark", desc: "Measurement rows" },
];

const MODES = ["AUTO", "CLASSICAL_ONLY", "DEEP_ONLY"];

const TONE_BY_STATE = {
  COMPLETE: "ok",
  RUNNING: "blue",
  BLOCKED: "warn",
  FAILED: "danger",
  INSUFFICIENT: "warn",
};

const OUTCOME_TONE = {
  CANDIDATES: "ok",
  NO_CANDIDATES: "warn",
  MATCHER_UNAVAILABLE: "neutral",
  MATCHER_FAILED: "danger",
  TIMEOUT: "danger",
  INPUT_INVALID: "neutral",
};

function capTone(available) {
  return available ? "ok" : "warn";
}

export default function M8Workspace({ pairId, notify }) {
  const { canMutate } = useAuth();
  const [capabilities, setCapabilities] = useState(null);
  const [status, setStatus] = useState(null);
  const [routing, setRouting] = useState(null);
  const [index, setIndex] = useState(null);
  const [benchmark, setBenchmark] = useState(null);
  const [mode, setMode] = useState("AUTO");
  const [doBenchmark, setDoBenchmark] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [jsonModal, setJsonModal] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const cap = await apiGet("/matching/capabilities");
        setCapabilities(cap);
      } catch (e) {
        setError(e);
        return;
      }
      try {
        const st = await apiGet(`/matching/${pairId}/m8/status`);
        setStatus(st);
      } catch (e) {
        setError(e);
      }
      let rt = null;
      let ix = null;
      let bm = null;
      try {
        rt = (await apiGet(`/matching/${pairId}/m8/routing`)).routing;
      } catch {
        /* none yet */
      }
      try {
        ix = (await apiGet(`/matching/${pairId}/m8/candidates`)).index;
      } catch {
        /* none yet */
      }
      try {
        bm = (await apiGet(`/matching/${pairId}/m8/benchmark`)).benchmark;
      } catch {
        /* none yet */
      }
      setRouting(rt);
      setIndex(ix);
      setBenchmark(bm);
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runExpand() {
    setBusy(true);
    setError(null);
    try {
      const st = await apiPost(`/matching/${pairId}/m8/run`, { mode, benchmark: doBenchmark });
      setStatus(st);
      if (st.state === "BLOCKED") {
        notify({
          title: `EXPAND blocked · ${st.blocked?.code ?? "?"}`,
          message: st.blocked?.reason ?? "Blocked honestly at an M8 gate.",
          tone: "warn",
        });
      } else {
        notify({
          title: `${pairId} EXPAND ${st.state === "INSUFFICIENT" ? "insufficient candidates" : "complete"}`,
          message: st.note ?? "M8 candidate sets are matcher observations, not verified truth.",
          tone: st.state === "INSUFFICIENT" ? "warn" : "ok",
        });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "EXPAND run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function resetExpand() {
    setBusy(true);
    try {
      const r = await apiPost(`/matching/${pairId}/m8/reset`);
      setStatus(r.status);
      setRouting(null);
      setIndex(null);
      setBenchmark(null);
      notify({
        title: `${pairId} EXPAND reset`,
        message: "Only derived M8 expansion artifacts were removed.",
        tone: "ok",
      });
    } catch (e) {
      notify({ title: "EXPAND reset failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function openJson(what) {
    try {
      const path = what === "manifest"
        ? `/matching/${pairId}/m8/manifest`
        : what === "provenance"
          ? `/matching/${pairId}/m8/provenance`
          : `/matching/${pairId}/m8/experiment`;
      const payload = (await apiGet(path))[what];
      setJsonModal({ what, payload });
    } catch (e) {
      notify({ title: `No M8 ${what}`, message: e.message, tone: "danger" });
    }
  }

  const stageState = useMemo(() => {
    if (!status) return M8_STAGES.map((s) => ({ ...s, state: "locked" }));
    if (status.state === "RUNNING") {
      return M8_STAGES.map((s, i) => ({ ...s, state: i < 3 ? "complete" : i === 3 ? "running" : "locked" }));
    }
    const complete = status.state === "COMPLETE" || status.state === "INSUFFICIENT";
    const failed = status.state === "FAILED";
    return M8_STAGES.map((s, i) => ({
      ...s,
      state: complete ? "complete" : failed ? (i === M8_STAGES.length - 1 ? "failed" : "locked") : "locked",
    }));
  }, [status]);

  return (
    <section className="space-y-4">
      {/* header + controls */}
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Deep matcher expansion · <span className="font-mono text-lunar-300">{pairId}</span>
              </h3>
              <Badge tone={TONE_BY_STATE[status?.state ?? "NOT_STARTED"] ?? "neutral"}>
                {status?.state ?? "NOT_STARTED"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{status?.configuration_id ?? "DM-M8-001"}</code> ·
              benchmark reference dataset <code className="font-mono text-slate-300">NOT_AVAILABLE</code> ·
              no winner, no accuracy claim — ever.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Run mode</label>
              <select className="input" value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <label className="flex items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-lunar-400"
                checked={doBenchmark}
                onChange={(e) => setDoBenchmark(e.target.checked)}
              />
              Benchmark
            </label>
            <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run deep-matcher expansion" : "Analyst or admin required"} onClick={runExpand}>
              <Icon.Activity className="h-4 w-4" /> {busy ? "Expanding…" : "Run EXPAND"}
            </button>
            <button className="btn-ghost" disabled={busy || !canMutate} title={canMutate ? "Reset pair state" : "Analyst or admin required"} onClick={resetExpand}>
              <Icon.Refresh className="h-4 w-4" /> Reset
            </button>
          </div>
        </div>
        {status?.progress != null && status?.state === "RUNNING" && (
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
            <div className="h-full rounded-full bg-lunar-400 transition-all" style={{ width: `${status.progress}%` }} />
          </div>
        )}
        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}
      </div>

      {/* stage trail */}
      <div className="flex flex-wrap gap-2">
        {stageState.map((s) => (
          <div key={s.id} className="flex items-center gap-1.5 rounded-lg border border-white/[0.07] bg-space-900/40 px-2.5 py-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                s.state === "complete" ? "bg-ok" : s.state === "running" ? "bg-lunar-300" : s.state === "failed" ? "bg-danger" : "bg-muted"
              }`}
            />
            <span className="text-[10.5px] font-medium text-muted">{s.label}</span>
          </div>
        ))}
      </div>

      {status?.state === "BLOCKED" && status?.blocked && (
        <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-warn">
            <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {status.blocked.code}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{status.blocked.reason}</p>
        </div>
      )}
      {status?.state === "FAILED" && status?.error && (
        <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> FAILED · {status.error.code}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{status.error.message}</p>
        </div>
      )}

      {/* capability matrix */}
      <CapabilityMatrix capabilities={capabilities} />

      {/* routing table */}
      {routing?.rows?.length > 0 && <RoutingTable rows={routing.rows} />}

      {/* summary */}
      {status?.summary && status.state !== "BLOCKED" && (
        <SummaryRow summary={status.summary} index={index} />
      )}

      {/* benchmark table */}
      {benchmark?.rows?.length > 0 && <BenchmarkTable benchmark={benchmark} />}

      {/* JSON drawers */}
      <div className="flex flex-wrap gap-2">
        <button className="btn-ghost !px-3 !py-1.5 text-xs" disabled={busy} onClick={() => openJson("manifest")} title="M8 provenance manifest">
          <Icon.Database className="h-3.5 w-3.5" /> Manifest
        </button>
        <button className="btn-ghost !px-3 !py-1.5 text-xs" disabled={busy} onClick={() => openJson("provenance")} title="M8 provenance chain">
          <Icon.Info className="h-3.5 w-3.5" /> Provenance
        </button>
        <button className="btn-ghost !px-3 !py-1.5 text-xs" disabled={busy} onClick={() => openJson("experiment")} title="Deterministic experiment identity">
          <Icon.Spark className="h-3.5 w-3.5" /> Experiment
        </button>
      </div>

      <Modal open={!!jsonModal} onClose={() => setJsonModal(null)} title={`M8 ${jsonModal?.what} · ${pairId}`}>
        {jsonModal && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(jsonModal.payload, null, 2)}
          </pre>
        )}
      </Modal>
    </section>
  );
}

function CapabilityMatrix({ capabilities }) {
  const matchers = capabilities?.matchers ?? [];
  const device = capabilities?.device;
  if (!matchers.length) return null;
  return (
    <div className="card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Honest matcher capabilities</p>
        {device && (
          <Badge tone="blue">
            device {device.effective_device}{device.cuda.available ? " · cuda" : ""} · torch {device.deep_runtime.torch ? "✓" : "✗"} ·
            torchvision {device.deep_runtime.torchvision ? "✓" : "✗"} · kornia {device.deep_runtime.kornia ? "✓" : "✗"}
          </Badge>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {matchers.map((m) => (
          <div key={m.matcher_id} className="rounded-lg border border-white/[0.07] bg-space-900/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-[11px] font-semibold text-slate-200">{m.matcher_id}</p>
              <Badge tone={capTone(m.available)}>{m.available ? "available" : "unavailable"}</Badge>
            </div>
            <p className="mt-1 text-[10.5px] text-muted">
              <span className="font-mono">{m.family}</span>
              {m.reason_if_unavailable ? ` · ${m.reason_if_unavailable}` : ""}
            </p>
            <p className="mt-1 text-[10px] text-muted/70">
              weights {m.weights_available ? "✓" : "✗"} · runtime {m.runtime_available ? "✓" : "✗"}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10.5px] text-muted">
        {capabilities?.note ?? "Availability is probe-checked at request time; deep matchers are only available when provisioned."}
      </p>
    </div>
  );
}

function RoutingTable({ rows }) {
  return (
    <div className="card p-4">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-muted">
        Adaptive expansion routing · {rows.length} tile(s)
      </p>
      <div className="grid max-h-[360px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map((r, i) => (
          <div key={`${r.tile_id}-${i}`} className="rounded-lg border border-white/[0.07] bg-space-900/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate font-mono text-[11px] font-semibold text-slate-200">{r.tile_id}</p>
              <Badge tone="gold">{r.requested_strategy}</Badge>
            </div>
            <p className="mt-1 text-[10.5px] font-medium text-slate-300">
              {r.reason} · mode {r.mode}
            </p>
            <p className="mt-1 text-[10px] text-muted">order: {(r.strategy_order ?? []).join(" → ")}</p>
            <p className="mt-1.5 text-[9.5px] leading-snug text-muted/70">{r.note}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SummaryRow({ summary, index }) {
  const total = summary.total_candidates ?? index?.total_candidates ?? 0;
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ok">{summary.tiles} tile pair(s)</Badge>
        <Badge tone="blue">{total} candidates</Badge>
        {Object.entries(summary.matchers_used ?? {}).map(([mid, n]) => (
          <Badge key={mid} tone="gold">
            {mid} × {n}
          </Badge>
        ))}
        {Object.entries(summary.outcomes ?? {}).map(([k, v]) => (
          <Badge key={k} tone={OUTCOME_TONE[k] ?? "neutral"}>
            {k} · {v}
          </Badge>
        ))}
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted">{summary.note}</p>
      <p className="mt-1 text-[10.5px] text-muted">
        downstream: {summary.downstream?.m4_trust ?? "?"} · {summary.downstream?.m5_spatial_reliability ?? "?"} ·{" "}
        {summary.downstream?.m6_registration ?? "?"} (categorical, never fabricated)
      </p>
    </div>
  );
}

function BenchmarkTable({ benchmark }) {
  const cols = ["matcher_id", "tile_id", "matcher_family", "runtime", "usable_count", "duplicate_count", "outcome", "m4_trusted", "m5_supported", "m6_registration_reachable"];
  return (
    <div className="card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-bold uppercase tracking-wider text-muted">
          Benchmark rows · reference dataset {benchmark.reference_dataset}
        </p>
        <Badge tone="warn">measurements — no winner/accuracy</Badge>
      </div>
      <div className="max-h-[420px] overflow-auto rounded-lg border border-white/[0.06]">
        <table className="w-full text-left text-[10.5px]">
          <thead className="sticky top-0 bg-space-900 text-muted">
            <tr>
              {cols.map((c) => (
                <th key={c} className="whitespace-nowrap border-b border-white/[0.06] px-2.5 py-1.5 font-semibold">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {benchmark.rows.map((r, i) => (
              <tr key={i} className="border-b border-white/[0.04]">
                <td className="px-2.5 py-1.5 font-mono text-slate-200">{r.matcher_id}</td>
                <td className="px-2.5 py-1.5 font-mono text-muted">{r.tile_id}</td>
                <td className="px-2.5 py-1.5 capitalize">{r.matcher_family}</td>
                <td className="px-2.5 py-1.5 font-mono text-muted">{r.runtime}</td>
                <td className="px-2.5 py-1.5 font-mono">{r.usable_count}</td>
                <td className="px-2.5 py-1.5 font-mono">{r.duplicate_count}</td>
                <td className="px-2.5 py-1.5">
                  <Badge tone={OUTCOME_TONE[r.outcome?.toUpperCase?.()] ?? "neutral"}>{r.outcome}</Badge>
                </td>
                <td className="px-2.5 py-1.5 font-mono text-muted">{r.m4_trusted}</td>
                <td className="px-2.5 py-1.5 font-mono text-muted">{r.m5_supported}</td>
                <td className="px-2.5 py-1.5 font-mono text-muted">{r.m6_registration_reachable}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}