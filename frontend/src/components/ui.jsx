import { createContext, useContext, useEffect, useState } from "react";

/* ------------------------------------------------------------------ icons */

export const Icon = {
  Grid: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  ),
  Database: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </svg>
  ),
  Activity: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M3 12h4l3-8 4 16 3-8h4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Chart: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" strokeLinecap="round" />
    </svg>
  ),
  Spark: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" strokeLinejoin="round" />
      <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z" strokeLinejoin="round" />
    </svg>
  ),
  Gear: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.5-2-3.4-2.4 1a7.6 7.6 0 0 0-2.6-1.5L14 2.6h-4l-.4 2.5a7.6 7.6 0 0 0-2.6 1.5l-2.4-1-2 3.4 2 1.5a7.6 7.6 0 0 0 0 3l-2 1.5 2 3.4 2.4-1a7.6 7.6 0 0 0 2.6 1.5l.4 2.5h4l.4-2.5a7.6 7.6 0 0 0 2.6-1.5l2.4 1 2-3.4-2-1.5z" />
    </svg>
  ),
  Info: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8h.01M12 11v5" strokeLinecap="round" />
    </svg>
  ),
  Chevron: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Lock: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  ),
  Check: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Refresh: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M20 11a8 8 0 1 0-2.3 6.3M20 4v7h-7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Alert: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M12 3L2.5 20h19L12 3z" strokeLinejoin="round" />
      <path d="M12 10v4M12 17h.01" strokeLinecap="round" />
    </svg>
  ),
  File: ({ className = "h-4 w-4" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M6 2.5h8l4 4V21a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1z" />
      <path d="M14 2.5V7h4" />
      <path d="M9 12h6M9 16h6" strokeLinecap="round" />
    </svg>
  ),
};

/* ------------------------------------------------------------- status glyph */

const STATE_COLORS = {
  ok: "bg-ok text-emerald-950",
  warn: "bg-warn text-amber-950",
  danger: "bg-danger text-red-950",
  info: "bg-orbit-400 text-blue-950",
  neutral: "bg-muted text-space-950",
};

export function StatusDot({ state = "neutral", pulse = false, className = "" }) {
  return (
    <span className={`relative inline-flex h-2 w-2 ${className}`} aria-hidden>
      {pulse && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${STATE_COLORS[state]}`}
        />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${STATE_COLORS[state]}`} />
    </span>
  );
}

export function Badge({ tone = "neutral", children, className = "" }) {
  const tones = {
    neutral: "border-white/10 bg-white/[0.04] text-muted",
    gold: "border-lunar-500/40 bg-lunar-500/10 text-lunar-300",
    blue: "border-orbit-500/40 bg-orbit-500/10 text-orbit-300",
    ok: "border-ok/40 bg-ok/10 text-ok",
    warn: "border-warn/40 bg-warn/10 text-warn",
    danger: "border-danger/40 bg-danger/10 text-danger",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ toast */

const ToastCtx = createContext(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  function push({ title, message, tone = "neutral" }) {
    const id = Date.now() + Math.random().toString(36).slice(2, 7);
    setToasts((t) => [...t, { id, title, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200);
  }

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className="card animate-fade-up pointer-events-auto border-white/10 p-3.5 shadow-glow"
          >
            <div className="flex items-start gap-2.5">
              <span
                className={
                  t.tone === "danger"
                    ? "mt-0.5 text-danger"
                    : t.tone === "ok"
                      ? "mt-0.5 text-ok"
                      : "mt-0.5 text-lunar-400"
                }
              >
                {t.tone === "danger" ? <Icon.Alert /> : <Icon.Check />}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-100">{t.title}</p>
                {t.message && <p className="mt-0.5 text-xs leading-relaxed text-muted">{t.message}</p>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ------------------------------------------------------------------ modal */

export function Modal({ open, onClose, title, children, footer }) {
  useEffect(() => {
    if (!open) return undefined;
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" role="dialog" aria-modal>
      <button
        aria-label="Close dialog"
        className="absolute inset-0 bg-space-950/80 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="card animate-fade-up relative w-full max-w-lg border-white/10 p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-base font-bold text-slate-100">{title}</h3>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-muted transition hover:bg-white/5 hover:text-slate-100"
          >
            ✕
          </button>
        </div>
        <div className="text-sm leading-relaxed text-muted">{children}</div>
        {footer && <div className="mt-4 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- empty state */

export function EmptyState({ icon, title, message, action }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-white/10 px-6 py-14 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-muted">
        {icon}
      </div>
      <p className="text-sm font-semibold text-slate-200">{title}</p>
      {message && <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-muted">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* --------------------------------------------------------- page skeleton */

export function PageSkeleton({ rows = 4 }) {
  return (
    <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="card space-y-3 p-4">
          <div className="skeleton h-3 w-1/2" />
          <div className="skeleton h-8 w-3/4" />
          <div className="skeleton h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}