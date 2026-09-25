import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M6 ADAPTIVE MATCHER ROUTER — deterministic, evidence-based routing
   decision layer between the M5 condition profile and matcher execution.

   Routing is a what-to-try decision, never a quality/accuracy verdict and
   never a matcher selection. Capability gates are resolved honestly and
   fallback is predeclared. ``decision`` never contains forbidden vocabulary
   such as ``selected_matcher`` / ``confidence``. */

const MODES = ["ADAPTIVE", "FIXED_BASELINE"];

function stateTone(state) {
  if (state === "SUCCESS" || state === "ROUTING_SUCCESS" || state === "EXECUTION_STARTED") return "ok";
  if (state === "ROUTED") return "ok";
  if (state === "BLOCKED" || state === "ABSTAIN") return "warn";
  if (state === "FAILED") return "danger";
  return "neutral";
}

function matcherTone(matcherId) {
  if (matcherId === "superpoint_superglue") return "blue";
  if (matcherId === "sift") return "ok";
  return "gold";
}

export default function AdaptiveRoutingCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [caps, setCaps] = useState(null);
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [mode, setMode] = useState("ADAPTIVE");
  const [busy, setBusy] = useState(false);
  const [execBusy, setExecBusy] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const latest = runs[0] ?? status?.latest ?? null;
  const decision = latest?.decision ?? null;

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        setCaps((await apiGet("/matching/routing/capabilities")) ?? null);
      } catch (e) {
        setError(e);
      }
      try {
        const st = (await apiGet(`/pairs/${pairId}/routing/status`)) ?? null;
        setStatus(st);
      } catch (e) {
        setError(e);
      }
      try {
        const rr = (await apiGet(`/pairs/${pairId}/routing/runs`)) ?? null;
        setRuns(rr?.runs ?? []);
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

  async function runRouting() {
    setBusy(true);
    setError(null);
    try {
      const payload = await apiPost(`/pairs/${pairId}/routing/run`, { mode });
      if (payload.task_handle) {
        notify({ title: `Routing run queued · ${payload.routing_run_id ?? "?"}`, message: "Routing task dispatched.", tone: "ok" });
      } else {
        const dec = payload.decision ?? {};
        if (dec.state === "ROUTED") {
          notify({
            title: `Route · ${dec.matched_rule_id ?? "?"} → ${dec.primary_matcher ?? "?"}`,
            message: `Fallback ${dec.fallback_matcher ?? "—"}${dec.fallback_used ? " (used)" : ""}. Routing is a what-to-try decision, never a verdict.`,
            tone: "ok",
          });
        } else if (payload.decision_status === "BLOCKED") {
          notify({
            title: `Routing BLOCKED · ${dec.error_code ?? "?"}`,
            message: dec.error_detail ?? "Blocked honestly at a routing gate.",
            tone: "warn",
          });
        } else {
          notify({ title: "Routing ABSTAIN", message: dec.route_explanation ?? "No rule matched.", tone: "warn" });
        }
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Routing run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function executeRouting() {
    if (!latest?.run_id) return;
    setExecBusy(true);
    setError(null);
    try {
      const payload = await apiPost(`/pairs/${pairId}/routing/execute`, { run_id: latest.run_id });
      const ex = payload.execution ?? {};
      if (ex.final_route) {
        notify({
          title: `Executed · ${ex.final_route}`,
          message: `${ex.executed_routes?.length ?? 0} route(s) tried${ex.fallback_used ? ` · fallback: ${ex.fallback_reason ?? "?"}` : ""}. Results remain candidate observations.`,
          tone: ex.fallback_used ? "warn" : "ok",
        });
      } else {
        notify({ title: "Execution recorded", message: payload.decision_status ?? "Started.", tone: "ok" });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Execute failed", message: e.message, tone: "danger" });
    } finally {
      setExecBusy(false);
    }
  }

  const configId = latest?.configuration_id ?? "AR-M6-001";
  const capClassical = caps?.capabilities?.classical ?? {};
  const capDeep = caps?.capabilities?.deep ?? {};

  return (
    <section className="space-y-4">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Adaptive matcher router · M6 — <span className="font-mono text-lunar-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(latest?.decision_status ?? "NOT_RUN")}>
                {latest?.decision_status ?? "NOT_RUN"}
              </Badge>
            </div>
            <p className="mt-1 max-w-2xl text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{configId}</code> · deterministic routing policy
              over the M5 condition and M8 capability probes. Routing is a <strong className="text-slate-200">what-to-try
              decision</strong> — never a matcher selection verdict and never a confidence or accuracy claim.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select className="input w-44" value={mode} onChange={(e) => setMode(e.target.value)} disabled={busy}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m === "ADAPTIVE" ? "ADAPTIVE (condition-driven)" : "FIXED_BASELINE (ablation)"}
                </option>
              ))}
            </select>
            <button
              className="btn-primary"
              disabled={busy || !canMutate}
              title={
                canMutate
                  ? "Run deterministic routing over the current condition + capability gates"
                  : `Viewer access — ${user?.username ?? "you"} can read decisions but cannot run routing`
              }
              onClick={runRouting}
            >
              <Icon.Activity className="h-4 w-4" /> {busy ? "Routing…" : "Run routing"}
            </button>
            <button
              className="btn-ghost"
              disabled={execBusy || !canMutate || !decision || decision.state !== "ROUTED"}
              title={canMutate ? "Dispatch the routed primary matcher (fallback predeclared)" : "Analyst or admin required"}
              onClick={executeRouting}
            >
              <Icon.Activity className="h-4 w-4" /> {execBusy ? "Executing…" : "Execute routed matcher"}
            </button>
          </div>
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}

        {caps && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted">
            <Badge tone="neutral">{caps.configuration_id ?? "AR-M6-001"}</Badge>
            {Object.entries(capClassical).map(([matcher, ok]) => (
              <span key={matcher} className={`font-mono ${ok ? "text-ok" : "text-muted"}`}>
                {matcher}:{ok ? "on" : "off"}
              </span>
            ))}
            {Object.entries(capDeep).map(([matcher, ok]) => (
              <span key={matcher} className={`font-mono ${ok ? "text-lunar-300" : "text-muted"}`}>
                {matcher}:{ok ? "on" : "off"}
              </span>
            ))}
          </div>
        )}

        {decision?.state === "BLOCKED" && (
          <div className="mt-3 rounded-lg border border-warn/30 bg-warn/[0.06] p-3">
            <p className="flex items-center gap-2 text-xs font-bold text-warn">
              <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {decision.error_code}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{decision.error_detail ?? decision.route_explanation}</p>
          </div>
        )}

        {decision?.state === "ABSTAIN" && (
          <div className="mt-3 rounded-lg border border-warn/30 bg-warn/[0.06] p-3">
            <p className="text-xs font-bold text-warn">ABSTAIN — no configured rule matched.</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{decision.route_explanation}</p>
          </div>
        )}
      </div>

      {latest && (
        <DecisionSummary latest={latest} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
      )}

      {runs.length > 0 && (
        <div className="card p-4">
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-wider text-muted">Routing runs</p>
          <ul className="space-y-1.5">
            {runs.map((r) => (
              <li key={r.run_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.06] bg-space-900/40 px-3 py-2 text-[11px]">
                <span className="font-mono text-slate-200">{r.run_id}</span>
                <Badge tone={r.decision === "BLOCKED" ? "warn" : r.decision?.state === "ROUTED" ? "ok" : "neutral"}>
                  {r.decision?.state ?? r.decision_status ?? "?"}
                </Badge>
                <span className="text-muted">{r.mode}</span>
                <span className="text-muted/60">{r.created_at_utc}</span>
                <span className="ml-auto font-mono text-slate-300">
                  {r.decision?.primary_matcher ?? "—"} → {r.decision?.fallback_matcher ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="gold">Decision</Badge>
        <span>— deterministic policy output; identical inputs produce identical hashes.</span>
        <Badge tone="blue">Capability gate</Badge>
        <span>— honest probe results; deep matchers are off unless provisioned.</span>
        <Badge tone="warn">Fallback</Badge>
        <span>— predeclared, never silent; wired to matcher execution.</span>
      </div>
    </section>
  );
}

function DecisionSummary({ latest, onToggle, expanded }) {
  const decision = latest?.decision ?? {};
  const input = latest?.input ?? {};
  const ex = latest?.execution ?? {};
  const rule = decision.matched_rule ?? {};
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={stateTone(decision.state)}>{decision.state ?? "—"}</Badge>
          {decision.matched_rule_id && <Badge tone="neutral">rule {decision.matched_rule_id}</Badge>}
          {decision.primary_matcher && (
            <Badge tone={matcherTone(decision.primary_matcher)}>primary {decision.primary_matcher}</Badge>
          )}
          {decision.fallback_matcher && (
            <Badge tone="neutral">fallback {decision.fallback_matcher}</Badge>
          )}
          <Badge tone={ex.fallback_used ? "warn" : "neutral"}>
            {ex.fallback_used ? `fallback used · ${ex.fallback_reason ?? "?"}` : "no fallback used"}
          </Badge>
          {ex.final_route && <Badge tone="blue">final {ex.final_route}</Badge>}
        </div>
        <button className="btn-ghost" onClick={onToggle}>
          {expanded ? "Hide details" : "Details"}
        </button>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        run <code className="font-mono text-slate-300">{latest.run_id}</code> · {latest.created_at_utc} ·{" "}
        {latest.mode}
        {rule.description ? <> · {rule.description}</> : null}
      </p>

      {decision.state === "ROUTED" && (
        <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Route decision</p>
            <dl className="space-y-1">
              <Readout k="Primary" v={decision.primary_matcher ?? "—"} />
              <Readout k="Fallback" v={decision.fallback_matcher ?? "—"} />
              <Readout k="Rule" v={`${decision.matched_rule_id ?? "—"} · priority ${decision.rule_priority ?? "—"}`} />
              <Readout k="Requested primary" v={decision.requested_primary_matcher ?? "—"} />
              <Readout k="Decision hash" v={hashShort(decision.decision_hash)} />
            </dl>
            <p className="pt-2 text-[10.5px] leading-snug text-muted">{decision.route_explanation}</p>
          </div>
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Evidence inputs</p>
            <dl className="space-y-1">
              <Readout k="Ready for matching" v={boolText(input.ready_for_matching)} />
              <Readout k="Condition profile" v={boolText(input.condition_profile_success)} />
              <Readout k="Processing state" v={input.processing_state ?? "—"} />
              <Readout k="M5 condition run" v={input.condition_run_id ?? "—"} />
              <Readout k="Source gate" v={input.source_gate ?? "—"} />
              <Readout k="Synthetic" v={boolText(input.synthetically_derived)} />
            </dl>
          </div>
        </div>
      )}

      {ex.executed_routes?.length > 0 && (
        <div className="mt-3 rounded-lg border border-white/[0.06] bg-space-900/40 p-3">
          <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Execution dispatch</p>
          <p className="text-[11px] text-muted">
            executed <code className="font-mono text-slate-300">{ex.executed_routes?.join(" → ") ?? "—"}</code> · final{" "}
            <code className="font-mono text-slate-200">{ex.final_route ?? "—"}</code> ·{" "}
            {ex.fallback_used ? `fallback reason: ${ex.fallback_reason ?? "?"}` : "executed primary only"} ·{" "}
            {latest.created_at_utc}
          </p>
          <ul className="mt-2 space-y-1">
            {Object.entries(ex.runs ?? {}).map(([matcher, meta]) => (
              <li key={matcher} className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
                <span className="font-mono text-slate-300">{matcher}</span>
                <Badge tone={meta.status === "SUCCESS" ? "ok" : "warn"}>{meta.status ?? "?"}</Badge>
                <span className="font-mono">{fmt(meta.candidate_match_count)} candidates</span>
                <span className="ml-auto font-mono">{meta.run_id}</span>
              </li>
            ))}
          </ul>
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

function hashShort(h) {
  if (!h) return "—";
  return `${h.slice(0, 10)}…${h.slice(-6)}`;
}

function boolText(v) {
  if (v == null) return "—";
  return v ? "yes" : "no";
}

function fmt(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  return String(v);
}

function Readout({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}