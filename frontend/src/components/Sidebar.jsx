import { Icon, StatusDot } from "./ui.jsx";
import { useAuth } from "../auth.jsx";

const NAV = [
  { id: "overview", label: "Overview", icon: Icon.Grid },
  { id: "evidence", label: "Evidence", icon: Icon.File },
  { id: "data", label: "Data", icon: Icon.Database },
  { id: "analysis", label: "Analysis", icon: Icon.Activity },
  { id: "results", label: "Results", icon: Icon.Chart },
  { id: "ai", label: "AI Copilot", icon: Icon.Spark },
  { id: "account", label: "Account", icon: Icon.Info },
  { id: "security", label: "Security", icon: Icon.Lock, admin: true },
];

export function Logo({ compact = false }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-teal-400/30 bg-gradient-to-br from-space-600 to-space-900 shadow-glow">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-teal-300" fill="none" stroke="currentColor" strokeWidth="1.5">
          {/* mission emblem: orbit + crosshair */}
          <circle cx="12" cy="12" r="7.5" opacity="0.5" strokeDasharray="2.5 3" />
          <circle cx="12" cy="12" r="3.4" />
          <path d="M12 4.5v-2M12 21.5v-2M4.5 12h-2M21.5 12h-2" strokeLinecap="round" />
          <path d="M17 4l1.5-1.5M17 20l1.5 1.5M7 4L5.5 2.5M7 20L5.5 21.5" strokeLinecap="round" opacity="0.6" />
        </svg>
      </div>
      {!compact && (
        <div className="leading-tight">
          <p className="text-sm font-extrabold tracking-tight text-slate-100">
            CHANDRA<span className="text-teal-300">SUTRA</span>
          </p>
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
            Orbital Research Interface
          </p>
        </div>
      )}
    </div>
  );
}

export function Sidebar({ page, onNavigate, backend }) {
  const online = backend?.online === true;
  const { user, isAdmin, signOut } = useAuth();
  const items = NAV.filter((item) => !item.admin || isAdmin);

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
          Mission Modules
        </p>
        {items.map((item) => {
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
                transition duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/60
                lg:justify-start lg:px-3
                ${
                  active
                    ? "bg-teal-500/10 text-teal-200"
                    : "text-muted hover:bg-white/[0.04] hover:text-slate-100"
                }`}
            >
              <IconCmp
                className={`h-4 w-4 shrink-0 ${active ? "text-teal-300" : "text-muted group-hover:text-slate-300"}`}
              />
              <span className="hidden flex-1 lg:block">{item.label}</span>
              {active && (
                <span className="hidden h-1.5 w-1.5 rounded-full bg-teal-300 shadow-[0_0_8px_rgba(67,205,181,0.9)] lg:block" />
              )}
            </button>
          );
        })}
      </nav>

      <div className="space-y-2 border-t border-white/[0.06] p-2 lg:p-3">
        {user && (
          <div className="card flex items-center gap-2.5 !rounded-lg p-2 lg:p-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-teal-500/15">
              <Icon.Info className="h-4 w-4 text-teal-300" />
            </div>
            <div className="hidden min-w-0 flex-1 leading-tight lg:block">
              <p className="truncate text-xs font-semibold text-slate-100">{user.username}</p>
              <p className="capitalize text-[10px] text-teal-300">{user.role}</p>
            </div>
          </div>
        )}
        <div className="flex items-center gap-2 px-1 lg:px-0.5">
          <StatusDot state={online ? "ok" : "danger"} pulse={online} />
          <span className="hidden flex-1 min-w-0 text-xs font-semibold text-slate-100 lg:block">
            {online ? `${backend?.environment} · v${backend?.version}` : "Backend offline"}
          </span>
          <button
            onClick={() => signOut()}
            title="Sign out"
            className="btn-ghost hidden !px-2 !py-1 text-[10px] lg:inline-flex"
          >
            Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}