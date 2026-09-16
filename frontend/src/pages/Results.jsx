import { Badge, EmptyState, Icon } from "../components/ui.jsx";

export default function Results() {
  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Results</h2>
        <p className="text-sm leading-relaxed text-muted">
          Registration outcomes, matched-candidate observations, Trust Gate states and metrics will
          be reported here — only from real experiments, never fabricated or edited by hand. M3
          records <strong className="text-slate-200">candidate correspondences as observations</strong>; how many
          survive explicit filtering, which strategy was routed and why. None of it is a trust verdict.
        </p>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
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
          <Badge tone="warn">M4 · Trust Gate (closed)</Badge>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Independent geometric verification of the candidate sets is <strong className="text-slate-200">NOT_RUN</strong>.
            Until the Trust Gate executes, no accuracy or confidence metric is produced, displayed or
            claimed anywhere.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            A closed Trust Gate is a first-class state — shown as such in the Analysis workspace.
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