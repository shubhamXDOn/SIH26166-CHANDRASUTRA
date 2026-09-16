import { Badge, EmptyState, Icon } from "../components/ui.jsx";

export default function Results() {
  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Results</h2>
        <p className="text-sm leading-relaxed text-muted">
          Registration outcomes, matched-candidate observations, Trust Gate states, spatial
          reliability results and metrics will be reported here — only from real experiments, never
          fabricated or edited by hand. M3 records{" "}
          <strong className="text-slate-200">candidate correspondences as observations</strong>; how many
          survive explicit filtering, which strategy was routed and why. M4 then applies the{" "}
          <strong className="text-slate-200">Trust Gate</strong> — deterministic geometric verification — and
          either accepts a tile as verified spatial evidence or rejects it with structured reasons.
          M5 represents the overlap scene as a{" "}
          <strong className="text-slate-200">spatial reliability grid</strong> and selects a supported
          reliability region for the future registration.
        </p>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="card p-5">
          <Badge tone="blue">M3 · Matching observations</Badge>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            <span className="font-mono text-xs text-lunar-300">Candidate sets</span> are per-tile, per-run
            outputs of the selected matcher: keypoint columns/rows in the sensor-native tile windows,
            descriptor distances and normalised matcher scores, with explicit filter counts
            (mask / border / duplicate rejection).
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            The routing decision is recorded with the measured scene conditions that drove it — a
            <em> what-to-try</em> decision, never a quality or accuracy verdict.
          </p>
        </div>
        <div className="card p-5">
          <Badge tone="ok">M4 · Trust Gate (open)</Badge>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Candidate sets are independently verified with deterministic RANSAC geometry, spatial
            support and a symmetric cross-check. Every tile ends in a first-class state:{" "}
            <span className="mx-1 font-mono text-[11px] text-ok">TRUSTED</span>
            <span className="mx-1 font-mono text-[11px] text-danger">REJECTED</span>
            <span className="mx-1 font-mono text-[11px] text-warn">INSUFFICIENT</span> or{" "}
            <span className="mx-1 font-mono text-[11px] text-orbit-300">NOT_RUN</span>.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            TRUSTED means verified spatial evidence for model fitting — it is still not final registration
            geometry. Registration (M6) remains locked until implemented.
          </p>
        </div>
        <div className="card p-5">
          <Badge tone="blue">M5 · Spatial reliability (open)</Badge>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Trusted correspondences are re-projected into an overlap-normalised scene grid. Each cell
            records verified inliers, usable correspondences, trusted-tile coverage and neighbourhood
            support; reliable cells join into connected components; a{" "}
            <span className="font-mono text-[11px] text-lunar-300">supported region</span> is selected and
            written as <span className="font-mono text-[11px] text-slate-300">selected_correspondences.npz</span>.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            M5 reports measurable spatial evidence — it is not an absolute accuracy or physical-registration
            claim. Blocked and insufficient outcomes are first-class.
          </p>
        </div>
        <div className="card p-5">
          <Badge tone="gold">Outcome model</Badge>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Every experiment ends in one of three states depending on evidence:
            <span className="mx-1 font-mono text-xs text-ok">SUCCESS</span>
            <span className="mx-1 font-mono text-xs text-danger">FAILURE</span>
            <span className="mx-1 font-mono text-xs text-orbit-300">ABSTAIN</span>.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            Abstention is first-class: insufficient or unreliable evidence means we decline to claim
            a result.
          </p>
        </div>
      </div>

      <div className="card p-6">
        <EmptyState
          icon={<Icon.Chart className="h-5 w-5" />}
          title="No real experiment run yet"
          message="Candidate correspondences and metrics appear only after the real-data pipeline (PRADAN-approved products + M1/M2/M3 runs) produces them. Synthetic TEST_FIXTURE runs validate the engine but are clearly labelled and never reported as lunar results."
          action={
            <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-warn animate-pulse-soft" />
              Scientific integrity: no fabricated metrics will ever be shown here
            </span>
          }
        />
      </div>
    </div>
  );
}