import { useEffect, useMemo, useState } from "react";

import Pipeline, { STAGE_STYLE } from "./Pipeline.jsx";
import { Badge, Icon, Modal } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

const MATCH_STAGES = [
  { id: "building_match_tiles", label: "Align", desc: "IoU-aligned tile pairs" },
  { id: "routing_strategy", label: "Strategy", desc: "Explainable routing" },
  { id: "running_matchers", label: "Matchers", desc: "Detect & match" },
  { id: "writing_candidates", label: "Candidates", desc: "Explicit filters" },
  { id: "run", label: "Run", desc: "MATCH lifecycle" },
];

const OUTCOME_TONES = {
  SUCCESS: "ok",
  NO_FEATURES: "warn",
  NO_CANDIDATES: "warn",
  INSUFFICIENT_CANDIDATES: "warn",
  MATCHER_FAILED: "danger",
  MATCHER_UNAVAILABLE: "neutral",
  INPUT_INVALID: "neutral",
  BLOCKED: "warn",
  TIMEOUT: "danger",
};

function matchStateTone(state) {
  if (state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED") return "danger";
  return "neutral";
}

export default function MatchingPanel({ pairId, notify }) {
  const { canMutate, user } = useAuth();
  const [status, setStatus] = useState(null);
  const [index, setIndex] = useState(null);
  const [decisions, setDecisions] = useState(null);
  const [tileSel, setTileSel] = useState("");
  const [tileCandidates, setTileCandidates] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const st = await apiGet(`/matching/${pairId}/status`);
        setStatus(st);
      } catch (e) {
        setError(e);
        return;
      }
      let idx = null;
      let dec = null;
      try {
        idx = (await apiGet(`/matching/${pairId}/candidates`)).tiles ?? null;
      } catch {
        /* no candidates yet */
      }
      try {
        dec = (await apiGet(`/matching/${pairId}/decisions`)).decisions ?? null;
      } catch {
        /* no decisions yet */
      }
      setIndex(idx ? { tiles: idx } : null);
      setDecisions(dec);
      setTileSel("");
      setTileCandidates(null);
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function loadTile(mid) {
    if (!mid) {
      setTileSel("");
      setTileCandidates(null);
      return;
    }
    setTileSel(mid);
    setTileCandidates(null);
    try {
      const payload = (await apiGet(`/matching/${pairId}/tiles/${mid}/candidates`)).candidates;
      setTileCandidates(payload);
    } catch (e) {
      notify({ title: "No candidate data", message: e.message, tone: "danger" });
    }
  }

  async function runMatch() {
    setBusy(true);
    setError(null);
    try {
      const st = await apiPost(`/matching/${pairId}/run`, {});
      setStatus(st);
      if (st.state === "BLOCKED") {
        notify({
          title: `MATCH blocked · ${st.blocked?.code ?? "?"}`,
          message: st.blocked?.reason ?? "Blocked honestly at a matching gate.",
          tone: "warn",
        });
      } else if (st.state === "COMPLETE") {
        notify({
          title: `${pairId} matched · ${st.summary?.total_candidates ?? 0} candidate(s)`,
          message: st.note ?? "Candidate correspondences are observations, not verified truth.",
          tone: "ok",
        });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "MATCH run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function resetMatch() {
    setBusy(true);
    try {
      const r = await apiPost(`/matching/${pairId}/reset`);
      setStatus(r.status);
      setIndex(null);
      setDecisions(null);
      setTileSel("");
      setTileCandidates(null);
      notify({
        title: `${pairId} matching reset`,
        message: "Only derived matching artifacts were removed. M2 products and raw/ are untouched.",
        tone: "ok",
      });
    } catch (e) {
      notify({ title: "Reset failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function openManifest() {
    try {
      const m = (await apiGet(`/matching/${pairId}/manifest`)).manifest;
      setManifest(m);
    } catch (e) {
      notify({ title: "No matching manifest", message: e.message, tone: "danger" });
    }
  }

  const stages = useMemo(() => {
    const stagesById = Object.fromEntries((status?.stages ?? []).map((s) => [s.id, s]));
    return MATCH_STAGES.map((s) => {
      const raw = stagesById[s.id];
      if (!raw) {
        if (status?.state === "COMPLETE") return { ...s, state: "complete" };
        if (status?.state === "FAILED") return s.id === "run" ? { ...s, state: "failed" } : { ...s, state: "locked" };
        return { ...s, state: "locked" };
      }
      const state = raw.state === "pending" ? "locked" : raw.state === "running" ? "running" : raw.state;
      return { ...s, state, detail: raw.detail };
    });
  }, [status]);

  const strategySummary = useMemo(() => {
    if (!status?.summary && !index) return null;
    const s = status?.summary ?? null;
    if (s) return { used: s.strategies_used ?? {}, proposed: s.strategies_proposed ?? {} };
    return null;
  }, [status, index]);

  return (
    <section className="space-y-4">
      {/* header + controls */}
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Adaptive matcher — <span className="font-mono text-lunar-300">{pairId}</span>
              </h3>
              <Badge tone={matchStateTone(status?.state ?? "NOT_STARTED")}>
                {status?.state ?? "NOT_STARTED"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{status?.configuration_id ?? "MC-M3-001"}</code> ·
              one explainable routing decision per match tile · BLOCKED is a first-class outcome.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run adaptive matching" : `Viewer access — ${user?.username ?? "you"} can read evidence but cannot run pipeline mutations`} onClick={runMatch}>
              <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "Run MATCH"}
            </button>
            <button className="btn-ghost" disabled={busy || !canMutate} title={canMutate ? "Reset pair state" : "Analyst or admin required"} onClick={resetMatch}>
              <Icon.Refresh className="h-4 w-4" /> Reset
            </button>
            <button className="btn-ghost" disabled={busy} onClick={openManifest} title="Matching provenance manifest">
              <Icon.Database className="h-4 w-4" /> Manifest
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

      <Pipeline stages={stages} />

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

      {status?.state === "COMPLETE" && status?.summary && (
        <SummaryBlock summary={status.summary} strategySummary={strategySummary} />
      )}

      {decisions?.decisions && <DecisionsBlock decisions={decisions.decisions} />}

      {index?.tiles && (
        <CandidateExplorer
          tiles={index.tiles}
          tileSel={tileSel}
          onSelect={loadTile}
          tileCandidates={tileCandidates}
          pairId={pairId}
        />
      )}

      <Modal open={!!manifest} onClose={() => setManifest(null)} title={`Matching manifest · ${pairId}`}>
        {manifest && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(manifest, null, 2)}
          </pre>
        )}
      </Modal>
    </section>
  );
}

function SummaryBlock({ summary, strategySummary }) {
  const outcomes = Object.entries(summary.outcomes ?? {});
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ok">{summary.tiles} tile pair(s)</Badge>
        <Badge tone="blue">{summary.total_candidates} candidate(s)</Badge>
        {strategySummary?.used &&
          Object.entries(strategySummary.used).map(([s, n]) => (
            <Badge key={s} tone="gold">
              {s} × {n}
            </Badge>
          ))}
        <Badge tone="neutral">proposed {JSON.stringify(strategySummary?.proposed ?? {})}</Badge>
      </div>

      {outcomes.length > 0 && (
        <div className="card p-4">
          <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-muted">Outcomes per tile</p>
          <div className="flex flex-wrap gap-2">
            {outcomes.map(([k, v]) => (
              <Badge key={k} tone={OUTCOME_TONES[k] ?? "neutral"}>
                {k} · {v}
              </Badge>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-muted">{summary.note}</p>
    </div>
  );
}

function DecisionsBlock({ decisions }) {
  return (
    <div className="card p-4">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-muted">
        Explainable routing decisions · {decisions.length}
      </p>
      <div className="grid max-h-[420px] gap-3 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3">
        {decisions.map((d) => (
          <div key={d.decision_id} className="rounded-lg border border-white/[0.07] bg-space-900/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate font-mono text-[11px] font-semibold text-slate-200">{d.match_tile_id}</p>
              <Badge tone="gold">{d.selected_strategy}</Badge>
            </div>
            <p className="mt-1.5 text-[10.5px] leading-snug text-slate-300">
              texture <span className="font-mono">{d.inputs?.condition_view?.texture_signature}</span>
              {" · "}contrast <span className="font-mono">{d.inputs?.condition_view?.contrast_signature}</span>
              {" · "}gap <span className="font-mono">{d.inputs?.scale_gap?.class}</span>
              {" · "}vf <span className="font-mono">{d.inputs?.condition_view?.valid_fraction_effective}</span>
            </p>
            <div className="mt-2 space-y-1 text-[10px]">
              {Object.entries(d.scoring ?? {})
                .filter(([, v]) => v.status !== "UNAVAILABLE")
                .map(([strategy, v]) => (
                  <div key={strategy} className="flex items-center justify-between gap-2">
                    <span className="font-mono text-muted">{strategy}</span>
                    <span className="flex items-center gap-1.5">
                      <span className="font-mono text-slate-300">{v.score ?? "—"}</span>
                      <Badge tone={v.status === "SCORED" ? "ok" : v.status === "CONSTRAINT_REJECTED" ? "warn" : "neutral"}>
                        {v.status}
                      </Badge>
                    </span>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CandidateExplorer({ tiles, tileSel, onSelect, tileCandidates, pairId }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Candidate explorer</p>
        <select className="input w-full max-w-md" value={tileSel} onChange={(e) => onSelect(e.target.value)}>
          <option value="">Select a match tile…</option>
          {tiles.map((t) => (
            <option key={t.match_tile_id} value={t.match_tile_id}>
              {t.match_tile_id} · {t.outcome} · {t.candidates} candidates · {t.strategy_used}
            </option>
          ))}
        </select>
      </div>

      {tileSel && !tileCandidates && (
        <div className="card p-4 text-xs text-muted">Loading candidate correspondences…</div>
      )}

      {tileCandidates && <TileCandidatesView payload={tileCandidates} pairId={pairId} />}
    </div>
  );
}

function TileCandidatesView({ payload }) {
  const summary = payload.summary ?? {};
  const points = payload.points;
  const thresholds = summary.threshold_counts ?? {};
  const attempts = summary.attempts ?? [];
  const n = points?.x_a?.length ?? 0;
  const dist = payload.descriptor_distance ?? [];
  const score = payload.matcher_score ?? [];

  const med = (arr) => {
    if (!arr?.length) return "—";
    const sorted = [...arr].sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)].toFixed(2);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {Object.entries(thresholds).map(([k, v]) => (
          <Badge key={k} tone={k === "candidate_set" ? "ok" : "neutral"}>
            {k} · {v}
          </Badge>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="card p-4 lg:col-span-2">
          <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-muted">
            Correspondence planes · {n} points (≤600 drawn)
          </p>
          <div className="grid grid-cols-2 gap-3">
            <PointPlane title="Sensor A" points={points} side="a" />
            <PointPlane title="Sensor B" points={points} side="b" />
          </div>
          <p className="mt-2 text-[10.5px] text-muted">
            Each panel plots keypoint columns (x) × rows (y) of the sensor-native tile windows,
            normalised to the point cloud extent. Locations are observations — not verified ground truth.
          </p>
        </div>

        <div className="space-y-3">
          <div className="card p-4">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-muted">Matching readout</p>
            <dl className="space-y-1.5 text-xs">
              <Readout k="Candidates" v={summary.count ?? n} />
              <Readout k="Strategy" v={payload.decision?.selected_strategy ?? summary.strategy} />
              <Readout k="Median matcher score" v={med(score)} />
              <Readout k="Median distance" v={med(dist)} />
              <Readout k="Outcome" v={summary.outcome ?? "—"} />
            </dl>
            <p className="mt-2 text-[10.5px] leading-relaxed text-muted">
              {summary.license ?? payload.note ?? "Candidate correspondences carry no accuracy or trust verdict."}
            </p>
          </div>

          {attempts.length > 0 && (
            <div className="card p-4">
              <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-muted">Attempt trail</p>
              <ul className="space-y-1.5 text-[11px]">
                {attempts.map((a, i) => (
                  <li key={i} className="flex items-start justify-between gap-2">
                    <span className="font-mono text-slate-300">{a.strategy}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="text-muted">
                        {a.status === "OK" ? `${a.candidates} candidates` : a.status === "FAILED" ? (a.note ?? "failed") : a.status}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="card border-warn/30 bg-warn/[0.06] p-4">
        <p className="flex items-start gap-2 text-[11px] leading-relaxed text-warn">
          <Icon.Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Trust Gate (M4): these are raw observations from one matcher run per tile — they are{" "}
            <strong>not yet verified</strong>. Run TRUST below to apply deterministic geometric
            verification and convert qualified tiles into verified spatial evidence.
          </span>
        </p>
      </div>
    </div>
  );
}

function PointPlane({ title, points, side }) {
  const xs = points?.[`x_${side}`] ?? [];
  const ys = points?.[`y_${side}`] ?? [];
  const sample = Math.min(600, xs.length);
  if (sample === 0) {
    return (
      <div className="rounded-lg border border-white/[0.06] bg-space-900/40 p-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-muted">{title}</p>
        <p className="mt-2 text-[10px] text-muted">No points.</p>
      </div>
    );
  }
  const max = Math.max(Math.max(...xs.slice(0, sample)), Math.max(...ys.slice(0, sample)), 1);
  const dot =
    xs.length <= 200 ? 4 : xs.length <= 1000 ? 3 : 2;
  return (
    <div className="rounded-lg border border-white/[0.06] bg-space-900/40 p-2">
      <p className="text-[10px] font-bold uppercase tracking-wider text-muted">{title}</p>
      <svg viewBox="0 0 100 100" className="mt-1 w-full" preserveAspectRatio="none" role="img" aria-label={`${title} keypoint plane`}>
        {Array.from({ length: sample }).map((_, i) => (
          <circle
            key={i}
            cx={(xs[i] / max) * 100}
            cy={(ys[i] / max) * 100}
            r={dot}
            fill="currentColor"
            className="text-lunar-300"
            opacity="0.75"
          />
        ))}
      </svg>
    </div>
  );
}

function Readout({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}