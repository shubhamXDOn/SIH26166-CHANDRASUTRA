import { EmptyState, Icon } from "../components/ui.jsx";

export default function Results() {
  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Results</h2>
        <p className="text-sm leading-relaxed text-muted">
          Registration outcomes, correspondence statistics, Trust Gate states and metrics will be
          reported here — only from real experiments, never fabricated or edited by hand.
        </p>
      </section>

      <div className="card p-6">
        <EmptyState
          icon={<Icon.Chart className="h-5 w-5" />}
          title="No experiment run yet"
          message="No correspondence or registration metrics exist in M0. First results will appear after the M1 real-data pipeline produces them."
          action={
            <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-warn animate-pulse-soft" />
              Scientific integrity: no fabricated metrics will ever be shown here
            </span>
          }
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <p className="mb-2 text-xs font-bold uppercase tracking-wider text-lunar-400">Outcome model</p>
          <p className="text-sm leading-relaxed text-muted">
            Every experiment ends in one of three states depending on evidence:
            <span className="mx-1 font-mono text-xs text-ok">SUCCESS</span>
            <span className="mx-1 font-mono text-xs text-danger">FAILURE</span>
            <span className="mx-1 font-mono text-xs text-orbit-300">ABSTAIN</span>.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            Abstention is a first-class outcome: low confidence or insufficient spatial reliability
            means we decline to claim registration.
          </p>
        </div>
        <div className="card p-5">
          <p className="mb-2 text-xs font-bold uppercase tracking-wider text-orbit-400">Visualization catalog</p>
          <p className="text-sm leading-relaxed text-muted">
            Image A / Image B, candidate correspondences, accepted/rejected points, spatial
            distribution, registration overlay, condition features, confidence and Trust Gate state.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            None are rendered until real output exists.
          </p>
        </div>
      </div>
    </div>
  );
}