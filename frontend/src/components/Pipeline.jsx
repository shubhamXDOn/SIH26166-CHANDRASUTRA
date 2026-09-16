import { Icon } from "./ui.jsx";

export const PIPELINE = [
  { id: "data", label: "Data", desc: "Ingest & provenance" },
  { id: "validate", label: "Validate", desc: "Metadata checks" },
  { id: "preprocess", label: "Preprocess", desc: "Safe radiometric & geometric" },
  { id: "match", label: "Match", desc: "Correspondence search" },
  { id: "trust", label: "Trust", desc: "Adaptive reliability gate" },
  { id: "reliability", label: "Reliability", desc: "Spatial selection" },
  { id: "register", label: "Register", desc: "Spatial model" },
  { id: "report", label: "Report", desc: "Metrics & visualization" },
];

export const STAGE_STYLE = {
  locked: {
    ring: "border-white/[0.08]",
    dot: "bg-space-600",
    label: "text-muted",
    badge: "text-muted",
    note: "Locked",
  },
  ready: {
    ring: "border-orbit-500/40 bg-orbit-500/[0.06]",
    dot: "bg-orbit-400",
    label: "text-slate-100",
    badge: "text-orbit-300",
    note: "Ready",
  },
  running: {
    ring: "border-lunar-500/50 bg-lunar-500/[0.08]",
    dot: "bg-lunar-400",
    label: "text-slate-100",
    badge: "text-lunar-300",
    note: "Running",
  },
  complete: {
    ring: "border-ok/40 bg-ok/[0.06]",
    dot: "bg-ok",
    label: "text-slate-100",
    badge: "text-ok",
    note: "Complete",
  },
  warning: {
    ring: "border-warn/50 bg-warn/[0.07]",
    dot: "bg-warn",
    label: "text-slate-100",
    badge: "text-warn",
    note: "Warning",
  },
  failed: {
    ring: "border-danger/50 bg-danger/[0.07]",
    dot: "bg-danger",
    label: "text-slate-100",
    badge: "text-danger",
    note: "Failed",
  },
};

export default function Pipeline({ stages, onStageClick }) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
        {stages.map((stage, i) => {
          const style = STAGE_STYLE[stage.state] ?? STAGE_STYLE.locked;
          const running = stage.state === "running";
          return (
            <div key={stage.id} className="relative flex items-stretch">
              {i > 0 && (
                <span className="absolute left-0 top-1/2 z-0 hidden -translate-x-1/2 -translate-y-1/2 text-muted/40 lg:block">
                  <Icon.Chevron className="h-4 w-4" />
                </span>
              )}
              <button
                onClick={onStageClick ? () => onStageClick(stage) : undefined}
                disabled={!onStageClick}
                aria-label={`${stage.label}: ${style.note}`}
                className={`card card-hover group relative z-10 w-full flex-1 p-3 text-left transition duration-200 ${style.ring} ${
                  !onStageClick ? "cursor-default" : ""
                }`}
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className={`flex h-2.5 w-2.5 rounded-full ${style.dot} ${running ? "animate-pulse-soft" : ""}`} />
                  <span className={`text-[10px] font-semibold uppercase tracking-wider ${style.badge}`}>
                    {style.note}
                  </span>
                </div>
                <p className={`text-sm font-bold ${style.label}`}>{stage.label}</p>
                <p className="mt-0.5 text-[10.5px] leading-snug text-muted">{stage.desc}</p>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}