import Pipeline, { PIPELINE, STAGE_STYLE } from "../components/Pipeline.jsx";
import { Badge, EmptyState, Icon } from "../components/ui.jsx";

const MODULE_PLAN = [
  {
    id: "condition",
    label: "Condition estimator",
    desc: "Estimates illumination, coverage, radiometry, texture and resolution conditions of each product.",
    milestone: "M2",
    state: "locked",
  },
  {
    id: "matcher",
    label: "Matcher adapters",
    desc: "Uniform adapters over existing baselines (SIFT, AKAZE, and deep matchers in later milestones).",
    milestone: "M2",
    state: "locked",
  },
  {
    id: "routing",
    label: "Adaptive routing",
    desc: "Condition-informed choice of matcher strategy instead of a single blind default.",
    milestone: "M3",
    state: "locked",
  },
  {
    id: "trust",
    label: "Trust Gate",
    desc: "Independent verification layer — matcher confidence is never the final truth signal.",
    milestone: "M4",
    state: "locked",
  },
  {
    id: "spatial",
    label: "Spatial selection",
    desc: "Temporal & spatial reliability of accepted correspondences before model fitting.",
    milestone: "M5",
    state: "locked",
  },
  {
    id: "registration",
    label: "Registration",
    desc: "Homography / affine fitting with diagnostics — low residual ≠ physically exact lunar registration.",
    milestone: "M6",
    state: "locked",
  },
  {
    id: "metrics",
    label: "Metrics & reporting",
    desc: "Measurable diagnostics and SUCCESS / FAILURE / ABSTAIN outcomes.",
    milestone: "M7",
    state: "locked",
  },
];

export default function Analysis() {
  const pipeline = PIPELINE.map((s) => ({ ...s, state: s.id === "data" ? "ready" : "locked" }));

  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">
          Analysis workspace
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          The scientific pipeline is <strong className="text-slate-200">dormant</strong> in M0. It
          becomes executable only on real, validated OHRC–TMC-2 pairs. No output below is produced
          or simulated.
        </p>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-100">Execution flow</h3>
          <Badge tone="warn">Locked until M1 data</Badge>
        </div>
        <Pipeline stages={pipeline} />
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-bold text-slate-100">Component roadmap</h3>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {MODULE_PLAN.map((mod) => {
            const style = STAGE_STYLE[mod.state];
            return (
              <div key={mod.id} className={`card card-hover p-4 ${style.ring}`}>
                <div className="mb-2 flex items-center justify-between">
                  <span className={`flex h-2 w-2 rounded-full ${style.dot}`} />
                  <Badge tone="neutral">planned · {mod.milestone}</Badge>
                </div>
                <p className={`text-sm font-bold ${style.label}`}>{mod.label}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted">{mod.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="card p-5">
        <EmptyState
          icon={<Icon.Activity className="h-5 w-5" />}
          title="No analysis run yet"
          message="Run history will list every experiment with its Pair ID, Configuration ID, matcher, runtime, status and failure reason — all reproducible."
          action={
            <Badge tone="gold">
              Awaiting first documented pair (M1)
            </Badge>
          }
        />
      </section>
    </div>
  );
}