import { useEffect, useMemo, useState } from "react";

import { Badge, Icon } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

/* M4 deep matching — SuperPoint + SuperGlue through the SAME candidate
   correspondence contract as the M3 classical baseline. Deep candidates
   are observations: model-native scores (matching_score / log_assignment
   _score / model_probability) are assignment probabilities only — NEVER
   confidence, NEVER a trust verdict, NEVER a "best model" badge. The M4
   Trust Gate and M6 registration engine own TRUSTED / REGISTERED. */

const DEEP_ORDER = ["superpoint_superglue", "loftr", "rift2"];
const CLASSICAL_ORDER = ["sift", "akaze", "orb"];

function stateTone(state) {
  if (state === "SUCCESS" || state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED") return "danger";
  return "neutral";
}

function statusLabel(m) {
  if (!m) return "UNKNOWN";
  if (m.available) return "AVAILABLE";
  return m.status ?? "NOT_AVAILABLE";
}

export default function DeepMatchingCard({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [caps, setCaps] = useState(null);
  const [status, setStatus] = useState(null);
  const [latest, setLatest] = useState(null);
  const [baselineRuns, setBaselineRuns] = useState([]);
  const [matcher, setMatcher] = useState("superpoint_superglue");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const c = (await apiGet("/matching/deep/capabilities")) ?? null;
        setCaps(c);
      } catch (e) {
        setError(e);
      }
      try {
        const st = (await apiGet(`/matching/${pairId}/deep/status`)) ?? null;
        setStatus(st);
        setLatest(st?.latest_run ?? null);
      } catch (e) {
        setError(e);
      }
      try {
        const b = (await apiGet(`/matching/${pairId}/baseline/runs`)) ?? null;
        setBaselineRuns(b?.runs ?? []);
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
    list.sort((a, b) => DEEP_ORDER.indexOf(a.matcher_id) - DEEP_ORDER.indexOf(b.matcher_id));
    return list;
  }, [caps]);

  const activeMatcher = matchers.find((m) => m.matcher_id === (latest?.matcher_id ?? matcher));

  async function runDeep() {
    if (!matcher) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await apiPost(`/matching/${pairId}/deep/run`, { matcher });
      setLatest(payload);
      setStatus((prev) => ({ ...(prev ?? {}), latest_run: payload }));
      if (payload.status === "SUCCESS") {
        notify({
          title: `Deep ${payload.matcher?.model_family ?? payload.matcher_id} · ${payload.matcher?.candidate_match_count ?? 0} candidate(s)`,
          message: "Candidates are observations; model scores are assignment probabilities, never a trust verdict.",
          tone: "ok",
        });
      } else if (payload.status === "BLOCKED") {
        notify({
          title: `Deep matcher BLOCKED · ${payload.error_code ?? "?"}`,
          message: payload.error_detail ?? "Blocked honestly at an M4 gate.",
          tone: "warn",
        });
      } else {
        notify({ title: `Deep matcher failed`, message: payload.error_detail ?? "Run failed.", tone: "danger" });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "Deep run failed", message: e.message, tone: "danger" });
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
  const matcherData = latest?.matcher ?? {};
  const modelEvidence = matcherData.model_evidence ?? {};
  const scores = matcherData.scores ?? {};

  return (
    <section className="space-y-4">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Deep matching — <span className="font-mono text-orbit-300">{pairId}</span>
              </h3>
              <Badge tone="gold">M4</Badge>
              <Badge tone={stateTone(latest?.status ?? "NOT_RUN")}>{latest?.status ?? "NOT_RUN"}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Config <code className="font-mono text-slate-300">{latest?.configuration_id ?? "DM-M4-001"}</code> ·
              SuperPoint + SuperGlue share the M3 candidate-correspondence contract. Candidates — never verified.
            </p>
          </div>
          <button
            className="btn-primary"
            disabled={busy || !canMutate || !activeMatcher?.available}
            title={canMutate
              ? (activeMatcher?.available ? "Run the selected deep matcher" : "This deep matcher is not available in this environment.")
              : `Viewer access — ${user?.username ?? "you"} can read evidence but cannot run pipeline mutations`}
            onClick={runDeep}
          >
            <Icon.Spark className="h-4 w-4" /> {busy ? "Running…" : "Run deep matcher"}
          </button>
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}

        {/* deep matcher selector with honest availability + DEEP visual language */}
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          {matchers.map((m) => {
            const selected = m.matcher_id === matcher;
            const available = m.available;
            return (
              <button
                key={m.matcher_id}
                disabled={!available}
                onClick={() => setMatcher(m.matcher_id)}
                className={`rounded-lg border p-3 text-left transition ${
                  selected
                    ? "border-orbit-400/50 bg-orbit-400/10"
                    : "border-white/[0.08] bg-space-900/40 hover:border-white/[0.16]"
                } ${!available ? "cursor-not-allowed opacity-60" : ""}`}
                title={available ? `${m.matcher_name} — availability verified at runtime.` : m.reason ?? m.not_available_detail}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-[11px] font-semibold text-slate-200">
                    {m.matcher_id === "superpoint_superglue" ? "SP+SG" : m.matcher_id.toUpperCase()}
                  </p>
                  <span className="inline-flex items-center gap-1">
                    <Badge tone="blue">DEEP</Badge>
                    <Badge tone={available ? "ok" : "neutral"}>{statusLabel(m)}</Badge>
                  </span>
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
                {activeMatcher.matcher_id === "superpoint_superglue"
                  ? "SuperPoint + SuperGlue requires torch/torchvision and official provisioned checkpoints. This environment reports it honestly unavailable — nothing is simulated."
                  : activeMatcher.reason ?? activeMatcher.not_available_detail}
              </span>
            </p>
          </div>
        )}
      </div>

      {latest && (
        <DeepRunSummary
          latest={latest}
          counts={counts}
          modelEvidence={modelEvidence}
          scores={scores}
          onToggle={() => setExpanded((v) => !v)}
          expanded={expanded}
        />
      )}

      {/* descriptive comparison — observations only, no winner/best badges */}
      <DescriptiveComparison
        pairId={pairId}
        baselineRuns={baselineRuns}
        capMap={matchers}
        deepLatest={latest}
      />

      <div className="flex flex-wrap gap-2 text-[11px] text-muted">
        <Badge tone="blue">Deep</Badge>
        <span>— strong learned correspondence (SuperPoint + SuperGlue).</span>
        <Badge tone="neutral">Classical</Badge>
        <span>— SIFT / AKAZE / ORB baseline.</span>
        <Badge tone="gold">Candidate</Badge>
        <span>— raw model observation, unverified.</span>
        <Badge tone="warn">Trusted</Badge>
        <span>— claimed only after the M4 Trust Gate (not this card).</span>
        <Badge tone="ok">Registered</Badge>
        <span>— claimed only after M6 registration (not this card).</span>
      </div>
    </section>
  );
}

function DeepRunSummary({ latest, counts, modelEvidence, scores, onToggle, expanded }) {
  const matcher = latest?.matcher ?? {};
  const env = matcher.environment ?? {};
  const provenance = matcher.provenance ?? {};
  const weights = provenance.checkpoints ?? [];
  const transform = modelEvidence.coordinate_transform ?? {};
  const exec = latest.configuration?.execution ?? {};
  const effA = latest.input?.image_a?.effective_dimensions;
  const effB = latest.input?.image_b?.effective_dimensions;
  const nativeA = latest.input?.image_a?.native_dimensions;
  const nativeB = latest.input?.image_b?.native_dimensions;
  const funnel = matcher.filters?.funnel ?? {};
  const source = latest.synthetically_derived
    ? "SYNTHETIC / fixture — structural software validation only"
    : "REAL-shaped / operator-data path";

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="blue">DEEP</Badge>
          <Badge tone="ok">{counts.candidates} candidate(s)</Badge>
          <Badge tone="neutral">KP A {counts.keypoints_a}</Badge>
          <Badge tone="neutral">KP B {counts.keypoints_b}</Badge>
          <Badge tone="neutral">{env.torch_version ?? "torch ?"}</Badge>
          <Badge tone={latest.synthetically_derived ? "warn" : "blue"}>{source}</Badge>
        </div>
        <button className="btn-ghost" onClick={onToggle}>
          {expanded ? "Hide details" : "Details"}
        </button>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        run <code className="font-mono text-slate-300">{latest.run_id}</code> · {latest.created_at_utc} ·{" "}
        {latest.status === "SUCCESS"
          ? `Selected ${matcher.candidate_match_count ?? 0} candidates from ${funnel.raw_matches ?? matcher.raw_match_count ?? "—"} SuperGlue matches`
          : latest.status === "BLOCKED"
            ? `BLOCKED · ${latest.error_code ?? "?"} · ${latest.error_detail ?? ""}`
            : `FAILED · ${latest.error_detail ?? "?"}`}
      </p>

      {latest.status === "SUCCESS" && (
        <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">
              Matching score (model-native)
            </p>
            <dl className="space-y-1">
              <Readout k="count" v={scores.matching_score?.count ?? "—"} />
              <Readout k="median" v={scores.matching_score?.median ?? "—"} />
              <Readout k="p95" v={scores.matching_score?.p95 ?? "—"} />
              <Readout k="min / max" v={join(scores.matching_score)} />
            </dl>
            <p className="pt-1 text-[10px] leading-snug text-muted">
              {modelEvidence.note ?? "Assignment probability — an observation, never confidence or a verdict."}
            </p>
          </div>
          <div className="card bg-space-900/40 p-3">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">SuperPoint + SuperGlue</p>
            <dl className="space-y-1">
              <Readout k="device" v={latest.matcher?.device ?? "cpu"} />
              <Readout k="model input" v={dims(effA)} />
              <Readout k="native product" v={dims(nativeA)} />
              <Readout
                k="runtime"
                v={matcher.runtime_ms != null ? `${(matcher.runtime_ms / 1000).toFixed(1)}s` : "—"}
              />
              <Readout k="match threshold" v={modelEvidence.superglue?.match_threshold ?? "—"} />
              <Readout k="sinkhorn iters" v={modelEvidence.superglue?.sinkhorn_iterations ?? "—"} />
            </dl>
          </div>
          <div className="card bg-space-900/40 p-3 sm:col-span-2">
            <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Coordinate transform (recorded)</p>
            <pre className="max-h-44 overflow-auto rounded bg-space-900/70 p-2 font-mono text-[9.5px] leading-snug text-slate-300">
              {JSON.stringify(transform, null, 2)}
            </pre>
            <p className="mt-1 text-[10px] text-muted">
              Output correspondences are mapped back to the effective (model input) frame; the grid → effective →
              native transforms recorded above are verified by independent round-trip tests.
            </p>
          </div>
          {latest.visualization_rel && (
            <div className="sm:col-span-2">
              <p className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-muted">Deep candidate line preview</p>
              <img
                src={`/api/matching/runs/${latest.run_id}/visualization`}
                alt="SuperPoint + SuperGlue candidate correspondence lines preview"
                className="max-h-72 w-full rounded-lg border border-white/[0.08] object-contain"
              />
              <p className="mt-1 text-[10px] text-muted">
                Candidate lines only — observations, never verified alignment. No trust or accuracy is implied.
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

      {/* provenance / checkpoint evidence */}
      {weights.length > 0 && (
        <div className="mt-3 grid gap-2">
          <p className="text-[10.5px] font-bold uppercase tracking-wider text-muted">Checkpoint evidence (provenance)</p>
          {weights.map((w) => (
            <div key={w.name} className="rounded-lg border border-white/[0.06] bg-space-900/40 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={w.provisioned && w.sha256_match ? "ok" : "danger"}>{w.provisioned ? "PROVISIONED" : "MISSING"}</Badge>
                <span className="font-mono text-[10.5px] text-slate-200">{w.filename}</span>
                {w.sha256_match !== undefined && (
                  <Badge tone={w.sha256_match ? "ok" : "danger"}>{w.sha256_match ? "SHA-256 ✓" : "SHA-256 ✗"}</Badge>
                )}
              </div>
              {w.sha256 && <p className="mt-1 font-mono text-[9.5px] text-muted">sha256 {w.sha256}</p>}
              {w.detail && <p className="mt-0.5 text-[10px] text-muted">{w.detail}</p>}
            </div>
          ))}
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

/* Descriptive comparison — same pair/input, neutral wording. No WINNER /
   BEST / ACCURACY / RECOMMENDED labels are ever produced. */
function DescriptiveComparison({ pairId, baselineRuns, capMap, deepLatest }) {
  const baselineByName = useMemo(() => {
    const m = {};
    for (const r of baselineRuns ?? []) {
      if (r.matcher_id && !m[r.matcher_id]) m[r.matcher_id] = r;
    }
    return m;
  }, [baselineRuns]);

  const rows = [
    ...CLASSICAL_ORDER.map((id) => {
      const run = baselineByName[id];
      return {
        kind: "CLASSICAL",
        id,
        name: id.toUpperCase(),
        available: run ? (run.status === "SUCCESS" ? "Available" : run.status) : "Unavailable",
        candidates: run?.counts?.candidates ?? "—",
        runtime: run?.runtime_ms != null ? `${(run.runtime_ms / 1000).toFixed(1)}s` : "—",
        source: run?.synthetically_derived ? "Test fixture" : run ? "—" : "—",
        identity: run?.matcher?.matcher_version ?? "opencv",
      };
    }),
    ...DEEP_ORDER.map((id) => {
      const cap = capMap?.find((m) => m.matcher_id === id);
      const run = deepLatest?.matcher_id === id ? deepLatest : null;
      return {
        kind: "DEEP",
        id,
        name: id === "superpoint_superglue" ? "SuperPoint + SuperGlue" : cap?.matcher_name ?? id,
        available: cap?.available ? "Available" : cap?.status ?? "Unavailable",
        candidates: run ? run.matcher?.candidate_match_count ?? "—" : "—",
        runtime: run ? (run.matcher.runtime_ms != null ? `${(run.matcher.runtime_ms / 1000).toFixed(1)}s` : "—") : "—",
        source: run ? (run.synthetically_derived ? "Test fixture" : "Real-shaped") : "—",
        identity: cap?.checkpoint?.join(" + ") ?? "—",
      };
    }),
  ];

  return (
    <div className="card p-4">
      <p className="mb-2 text-[10.5px] font-bold uppercase tracking-wider text-muted">
        Descriptive comparison · {pairId} (observations only)
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[11px]">
          <thead>
            <tr className="border-b border-white/[0.08] text-[10px] uppercase tracking-wider text-muted">
              <th className="py-1.5 pr-2">Matcher</th>
              <th className="py-1.5 pr-2">Kind</th>
              <th className="py-1.5 pr-2">Availability</th>
              <th className="py-1.5 pr-2">Candidates</th>
              <th className="py-1.5 pr-2">Runtime</th>
              <th className="py-1.5 pr-2">Data source</th>
              <th className="py-1.5">Model identity</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-white/[0.04]">
                <td className="py-1.5 pr-2 font-mono text-slate-200">{r.name}</td>
                <td className="py-1.5 pr-2">
                  <Badge tone={r.kind === "DEEP" ? "blue" : "neutral"}>{r.kind}</Badge>
                </td>
                <td className="py-1.5 pr-2">{r.available}</td>
                <td className="py-1.5 pr-2 font-mono">{r.candidates}</td>
                <td className="py-1.5 pr-2 font-mono">{r.runtime}</td>
                <td className="py-1.5 pr-2">{r.source}</td>
                <td className="py-1.5 text-muted">{r.identity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[10px] leading-snug text-muted">
        This table is descriptive (“Observed / Available / Unavailable / Candidate output / Runtime”). No
        winner, best, accuracy or recommended ranking is produced or implied.
      </p>
    </div>
  );
}

function join(s) {
  if (!s) return "—";
  if (s.min == null || s.max == null) return "—";
  return `${s.min} · ${s.max}`;
}

function dims(d) {
  if (!d) return "—";
  return `${d.width}×${d.height}`;
}

function Readout({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}