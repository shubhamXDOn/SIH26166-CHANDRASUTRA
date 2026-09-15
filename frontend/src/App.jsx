import { useCallback, useEffect, useState } from "react";

import { Icon, ToastProvider, useToast } from "./components/ui.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { apiGet } from "./api.js";

import Overview from "./pages/Overview.jsx";
import Data from "./pages/Data.jsx";
import Analysis from "./pages/Analysis.jsx";
import Results from "./pages/Results.jsx";
import AIInsights from "./pages/AIInsights.jsx";
import Settings from "./pages/Settings.jsx";

const PAGES = {
  overview: { title: "Overview", Component: Overview },
  data: { title: "Data", Component: Data },
  analysis: { title: "Analysis", Component: Analysis },
  results: { title: "Results", Component: Results },
  ai: { title: "AI Insights", Component: AIInsights },
  settings: { title: "Settings", Component: Settings },
};

function Shell() {
  const [page, setPage] = useState("overview");
  const [backend, setBackend] = useState({ online: false, retrying: false });
  const notify = useToast();

  const refreshHealth = useCallback(async () => {
    try {
      const health = await apiGet("/health");
      setBackend({ ...health, online: true });
    } catch {
      setBackend((prev) => ({ ...prev, online: false }));
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const id = setInterval(refreshHealth, 20_000);
    return () => clearInterval(id);
  }, [refreshHealth]);

  const navigate = useCallback(
    (id) => {
      setPage(id);
      const timeout = window.setTimeout(() => (document.activeElement?.blur?.(null)), 0);
      window.clearTimeout(timeout);
    },
    []
  );

  const { title, Component } = PAGES[page];

  return (
    <div className="min-h-screen">
      <Sidebar page={page} onNavigate={navigate} backend={backend} />

      <main className="pl-16 lg:pl-64">
        <div className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-white/[0.06] bg-space-950/60 px-5 backdrop-blur-xl sm:px-8">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-bold tracking-tight text-slate-100">{title}</h1>
            {page !== "overview" && (
              <span className="hidden text-xs text-muted sm:inline">/ {title.toLowerCase()}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-[11px] font-medium text-muted md:flex">
              <span className="h-1.5 w-1.5 rounded-full bg-lunar-400" />
              Milestone M0 · Foundation
            </span>
            <button
              onClick={() => {
                refreshHealth();
                notify({ title: "Status refreshed", message: "Backend health re-checked.", tone: "ok" });
              }}
              className="btn-ghost !px-3 !py-1.5 text-xs"
            >
              <Icon.Refresh className="h-3.5 w-3.5" />
              Refresh
            </button>
          </div>
        </div>

        <div key={page} className="animate-fade-up px-5 py-6 sm:px-8">
          <Component notify={notify} backend={backend} onNavigate={navigate} />
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}