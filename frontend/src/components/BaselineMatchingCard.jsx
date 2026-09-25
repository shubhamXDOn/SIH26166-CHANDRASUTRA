import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M3 classical baseline matching — SIFT · AKAZE · ORB, candidate
   correspondences only. Candidates are observations, never verified;
   the M4 Trust Gate (M4) and the M6 Registration engine own the
   TRUSTED / REGISTERED states that this card must never imply. */

const MATCHER_ORDER = ["sift", "akaze", "orb"];

function stateTone(state) {
  if (state === "SUCCESS" || state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED") return "danger";
  return "neutral";
}

export default function BaselineMatchingCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [caps, setCaps] = useState(null);
  const [status, setStatus] = useState(null);
  const [latest, setLatest] = useState(null);
  const [matcher, setMatcher] = useState("sift");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const c = (await apiGet("/matching/baseline/capabilities")) ?? null;
        setCaps(c);
      } catch (e) {
        setError(e);
      }
      try {
        const st = (await apiGet(`/matching/${pairId}/baseline/status`)) ?? null;
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

  const matchers = useMemo(() => {
    const list = (caps?.matchers ?? []).slice();
    list.sort((a, b) => MATCHER_ORDER.indexOf(a.matcher_id) - MATCHER_ORDER.indexOf(b.matcher_id));
    return list;
  }, [caps]);

  async function runBaseline() {
    if (!matcher) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await apiPost(`/matching/${pairId}/baseline/run`, { matcher });
      setLatest(payload);
      setStatus((prev) => ({ ...(prev ?? {}), latest_run: payload }));
      if (payload.status === "SUCCESS") {
        notify({
          title: `${payload.matcher_id} baseline · ${payload.matcher?.candidate_match_count ?? 0} candidate(s)`,
          message: "Candidates are observations; verification happens only at the M4 Trust Gate.",
          tone: "ok",
        });
      } else if (payload.status === "BLOCKED") {
        notify({
          title: `${payload.matcher_id} baseline BLOCKED · ${payload.error_code ?? "?"}`,
          message: payload.error_detail ?? "Blocked honestly at a baseline gate.",
          tone: "warn",
        });
      } else {
        notify({ title: `${payload.matcher_id} baseline failed`, message: payload.error_detail ?? "Run failed.", tone: "danger" });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Baseline run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  function countsOf(item) {
    if (!item) return { keypoints_a: 0, keypoints_b: 0, candidates: 0 };
    if (item.counts) return item.counts;
    return {
      keypoints_a: item.matcher?.keypoint_count_a ?? 0,
      keypoints_b: item.matcher?.keypoint_count_b ?? 0,
      candidates: item.matcher?.candidate_match_count ?? 0,
    };
  }

  const counts = countsOf(latest);

  const activeMatcher = matchers.find((m) => m.matcher_id === (latest?.matcher_id ?? matcher));

  return (
    <section className="space-y-4">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Classical baseline matching — <span className="font-mono text-lunar-300">{pairId}</span>
              </h3>
              <Badge tone={stateTone(latest?.status ?? "NOT_RUN")}>{latest?.status ?? "NOT_RUN"}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{latest?.configuration_id ?? "MB-M3-001"}</code> ·
              SIFT × AKAZE × ORB share one explicit contract. Candidate correspondences — never verified.
            </p>
          </div>
          <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run the selected baseline matcher" : `Viewer access — ${user?.username ?? "you"} can read evidence but cannot run pipeline mutations`} onClick={runBaseline}>
            <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "Run baseline"}
          </button>
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}

        {/* matcher selector with honest availability */}
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          {matchers.map((m) => {
            const selected = m.matcher_id === matcher;
            return (
              <button
                key={m.matcher_id}
                disabled={!m.available}
                onClick={() => setMatcher(m.matcher_id)}
                className={`rounded-lg border p-3 text-left transition ${
                  selected
                    ? "border-lunar-400/50 bg-lunar-400/10"
                    : "border-white/[0.08] bg-space-900/40 hover:border-white/[0.16]"
                } ${!m.available ? "cursor-not-allowed opacity-60" : ""}`}
                title={m.available ? `${m.matcher_name} — availability verified at runtime.` : m.not_available_detail}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-[11px] font-semibold text-slate-200">{m.matcher_id.toUpperCase()}</p>
                  <Badge tone={m.available ? "ok" : "neutral"}>{m.available ? "available" : "NOT_AVAILABLE"}</Badge>
                </div>
                <p className="mt-1 text-[10.5px] leading-snug text-muted">{m.matcher_name}</p>
              </button>
            );
          })}
        </div>
        {activeMatcher && !activeMatcher.available && (
          <div className="mt-2 rounded-lg border border-warn/30 bg-warn/[0.06] p-3">
            <p className="flex items-start gap-2 text-[11px] leading-relaxed text-warn">
              <Icon.Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                AKAZE is registered as a baseline matcher but this OpenCV build does not include{" "}
                <code className="font-mono">AKAZE_create</code>. A requested run records a truthful{" "}
                <code className="font-mono">MATCHER_NOT_AVAILABLE</code> block — nothing is simulated.
              </span>
            </p>
          </div>
        )}
      </div>

      {latest && (
        <RunSummary latest={latest} counts={counts} onToggle={() => setExpanded((v) => !v)} expanded={expanded} />
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="neutral">Candidate</Badge>
        <span>— raw correspondence observed by a baseline matcher, unverified.</span>
        <Badge tone="gold">Trusted</Badge>
        <span>— claimed only after the M4 Trust Gate (not this card).</span>
        <Badge tone="blue">Registered</Badge>
        <span>— claimed only after the M6 registration engine (not this card).</span>
      </div>
    </section>
  );
}

function RunSummary({ latest, counts, onToggle, expanded }) {
  const matcher = latest?.matcher ?? {};
  const scores = matcher.scores ?? latest.scores ?? {};
  const funnel = matcher.filters?.funnel ?? latest.filters?.funnel ?? {};
  const matcherVersion = latest?.matcher?.matcher_version ?? "opencv";
  const source = latest.synthetically_derived
    ? "SYNTHETIC / fixture — structural software validation only"
    : "REAL-shaped / operator-data path";
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="ok">{counts.candidates} candidate(s)</Badge>
          <Badge tone="neutral">KP A {counts.keypoints_a}</Badge>
          <Badge tone="neutral">KP B {counts.keypoints_b}</Badge>
          <Badge tone="gold">{matcherVersion}</Badge>
          <Badge tone={latest.synthetically_derived ? "warn" : "blue"}>{source}</Badge>
        </div>
        <button className="btn-ghost" onClick={onToggle}>
          {expanded ? "Hide details" : "Details"}
        </button>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        run <code className="font-mono text-slate-300">{latest.run_id}</code> · {latest.created_at_utc} ·{" "}
        {latest.status === "SUCCESS"
          ? `funnel ${funnel.raw_matches ?? "—"} raw → ${counts.candidates} candidates`
          : latest.status === "BLOCKED"
            ? `BLOCKED · ${latest.error_code ?? "?"}`
            : `FAILED · ${latest.error_detail ?? "?"}`}
      </p>

      {latest.status === "SUCCESS" && (
        <div className="grid gap-3 text-xs sm:grid-cols-2">
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Distance (descriptor)</p>
            <dl className="space-y-1">
              <Readout k="median" v={scores.descriptor_distance?.median ?? "—"} />
              <Readout k="p95" v={scores.descriptor_distance?.p95 ?? "—"} />
              <Readout k="min / max" v={join(scores.descriptor_distance)} />
            </dl>
          </div>
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Score (normalised complement)</p>
            <dl className="space-y-1">
              <Readout k="median" v={scores.score?.median ?? "—"} />
              <Readout k="p95" v={scores.score?.p95 ?? "—"} />
              <p className="pt-1 text-[10px] leading-snug text-muted">
                An observation, never a confidence or a trust verdict.
              </p>
            </dl>
          </div>
          {latest.visualization_rel && (
            <div className="sm:col-span-2">
              <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Candidate line preview</p>
              <img
                src={`/api/matching/runs/${latest.run_id}/visualization`}
                alt={`${latest.matcher_id} candidate correspondence lines preview`}
                className="max-h-72 w-full rounded-lg border border-white/[0.08] object-contain"
              />
              <p className="mt-1 text-[10px] text-muted">
                Candidate lines only — observations, not verified alignment. No trust is implied by colour or count.
              </p>
            </div>
          )}
        </div>
      )}

      {latest.status === "BLOCKED" && (
        <div className="mt-2 rounded-lg border border-warn/30 bg-warn/[0.06] p-3">
          <p className="flex items-center gap-2 text-xs font-bold text-warn">
            <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {latest.error_code}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{latest.error_detail}</p>
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

function join(s) {
  if (!s) return "—";
  if (s.min == null || s.max == null) return "—";
  return `${s.min} · ${s.max}`;
}

function Readout({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}