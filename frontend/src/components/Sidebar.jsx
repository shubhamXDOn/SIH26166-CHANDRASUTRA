import { Icon, StatusDot } from "./ui.jsx";

const NAV = [
  { id: "overview", label: "Overview", icon: Icon.Grid },
  { id: "data", label: "Data", icon: Icon.Database },
  { id: "analysis", label: "Analysis", icon: Icon.Activity },
  { id: "results", label: "Results", icon: Icon.Chart },
  { id: "ai", label: "AI Insights", icon: Icon.Spark },
  { id: "settings", label: "Settings", icon: Icon.Gear },
];

export function Logo({ compact = false }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-lunar-500/30 bg-gradient-to-br from-space-700 to-space-900 shadow-glow">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-lunar-400" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="7.5" opacity="0.5" />
          <circle cx="12" cy="12" r="3.2" />
          <circle cx="17.5" cy="6.5" r="0.9" fill="currentColor" stroke="none" opacity="0.9" />
          <circle cx="6.5" cy="9" r="0.7" fill="currentColor" stroke="none" opacity="0.7" />
          <circle cx="8.5" cy="17.5" r="0.65" fill="currentColor" stroke="none" opacity="0.6" />
        </svg>
      </div>
      {!compact && (
        <div className="leading-tight">
          <p className="text-sm font-extrabold tracking-tight text-slate-100">
            CHANDRA<span className="text-lunar-400">SUTRA</span>
          </p>
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
            Lunar Image Intelligence
          </p>
        </div>
      )}
    </div>
  );
}

export function Sidebar({ page, onNavigate, backend }) {
  const online = backend?.online === true;

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-16 flex-col border-r border-white/[0.06] bg-space-900/70 backdrop-blur-xl lg:w-64">
      <div className="flex h-16 items-center justify-center border-b border-white/[0.06] px-1 lg:justify-start lg:px-5">
        <div className="lg:hidden">
          <Logo compact />
        </div>
        <div className="hidden lg:block">
          <Logo />
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-4 lg:px-3">
        <p className="hidden px-2 pb-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted/70 lg:block">
          Workspace
        </p>
        {NAV.map((item) => {
          const active = page === item.id;
          const IconCmp = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              aria-current={active ? "page" : undefined}
              aria-label={item.label}
              title={item.label}
              className={`group flex w-full items-center justify-center gap-3 rounded-lg px-2 py-2.5 text-left text-sm font-medium
                transition duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-lunar-400/60
                lg:justify-start lg:px-3
                ${
                  active
                    ? "bg-lunar-500/10 text-lunar-300"
                    : "text-muted hover:bg-white/[0.04] hover:text-slate-100"
                }`}
            >
              <IconCmp
                className={`h-4 w-4 shrink-0 ${active ? "text-lunar-400" : "text-muted group-hover:text-slate-300"}`}
              />
              <span className="hidden flex-1 lg:block">{item.label}</span>
              {active && (
                <span className="hidden h-1.5 w-1.5 rounded-full bg-lunar-400 shadow-[0_0_8px_rgba(230,177,87,0.9)] lg:block" />
              )}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-white/[0.06] p-2 lg:p-4">
        <div className="card flex items-center justify-center gap-3 !rounded-lg p-2 lg:justify-start lg:p-3">
          <StatusDot state={online ? "ok" : "danger"} pulse={online} />
          <div className="hidden min-w-0 flex-1 leading-tight lg:block">
            <p className="text-xs font-semibold text-slate-100">
              {online ? "Backend online" : "Backend offline"}
            </p>
            <p className="truncate text-[10px] text-muted">
              {online ? `${backend?.environment} · v${backend?.version}` : "Retrying…"}
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}