import { useEffect, useState } from "react";

import { Badge, Icon, ToastProvider, useToast } from "../components/ui.jsx";
import { MissionStamp, OrbitalRings, StarField } from "../components/space.jsx";
import { useAuth } from "../auth.jsx";

function Field({ label, type = "text", value, onChange, placeholder, autoComplete, children }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className="input w-full"
      />
      {children}
    </label>
  );
}

function AuthRequiredGate() {
  const { auth, signIn, signUp, refreshAuthStatus } = useAuth();
  const notify = useToast();
  const [mode, setMode] = useState("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    refreshAuthStatus();
  }, [refreshAuthStatus]);

  const configured = auth?.authentication_enabled === true;

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (!configured) {
      setError("Authentication is not configured — set AUTH_SECRET_KEY and restart the backend.");
      return;
    }
    if (mode === "signin") {
      setBusy(true);
      try {
        const u = await signIn(username.trim(), password);
        notify({ title: "Signed in", message: `Welcome, ${u.display_name || u.username}.`, tone: "ok" });
      } catch (err) {
        setError(err.message);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const res = await signUp(username.trim(), password, displayName.trim());
      notify({
        title: "Account created",
        message: res.registration_enabled
          ? "Your account is active — sign in to continue."
          : "Account created and pending administrator approval.",
        tone: "ok",
      });
      setMode("signin");
      setPassword("");
      setConfirm("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const regEnabled = auth?.registration_enabled === true;

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-space-950 px-4">
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <StarField className="absolute inset-0 h-full w-full opacity-60" />
        <OrbitalRings className="absolute -left-40 -top-40 h-[34rem] w-[34rem] max-w-none opacity-50" />
        <OrbitalRings className="absolute -bottom-44 -right-44 h-[38rem] w-[38rem] max-w-none opacity-40" accent="#33b7dc" />
      </div>
      <div className="relative w-full max-w-md space-y-5">
        <div className="text-center">
          <MissionStamp className="mb-3" />
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-slate-100">
            Sign in to the lunar intelligence workspace
          </h1>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            Real Chandrayaan-2 OHRC × TMC-2 pairs, verifiable pipeline evidence and role-based
            access — viewer, analyst or administrator.
          </p>
        </div>

        {!configured && (
          <div className="card flex items-start gap-3 border-warn/30 p-4">
            <Icon.Alert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            <div className="text-xs leading-relaxed">
              <p className="font-semibold text-warn">Authentication is not configured</p>
              <p className="mt-1 text-muted">
                Set <code className="font-mono text-slate-300">AUTH_SECRET_KEY</code> in{" "}
                <code className="font-mono text-slate-300">.env</code> (optionally{" "}
                <code className="font-mono text-slate-300">AUTH_BOOTSTRAP_ADMIN_USERNAME</code> /
                <code className="font-mono text-slate-300">_PASSWORD</code>) and restart the backend.
                Until then sign-in is disabled fail-closed.
              </p>
            </div>
          </div>
        )}

        <form onSubmit={submit} className="card space-y-4 p-5">
          <div className="flex items-center gap-1 rounded-lg border border-white/[0.06] bg-white/[0.02] p-1">
            <button
              type="button"
              onClick={() => { setMode("signin"); setError(null); }}
              className={`flex-1 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                mode === "signin" ? "bg-teal-500/15 text-teal-200" : "text-muted hover:text-slate-200"
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => { setMode("register"); setError(null); }}
              disabled={!regEnabled}
              title={regEnabled ? "Create an account" : "Self-registration is disabled by the administrator"}
              className={`flex-1 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                mode === "register" ? "bg-teal-500/15 text-teal-200" : "text-muted hover:text-slate-200"
              } disabled:cursor-not-allowed disabled:opacity-40`}
            >
              Register
            </button>
          </div>

          {mode === "register" && (
            <Field label="Display name (optional)" value={displayName} onChange={setDisplayName} placeholder="Analyst" />
          )}
          <Field
            label="Username"
            value={username}
            onChange={setUsername}
            placeholder="alice"
            autoComplete="username"
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder="••••••••••••"
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
          />
          {mode === "register" && (
            <Field
              label="Confirm password"
              type="password"
              value={confirm}
              onChange={setConfirm}
              placeholder="••••••••••••"
              autoComplete="new-password"
            />
          )}

          {error && (
            <p className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
              <Icon.Alert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
            </p>
          )}

          <button type="submit" className="btn-primary w-full justify-center" disabled={busy || !configured}>
            {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
          </button>

          <div className="flex items-center justify-between text-[10.5px] text-muted">
            <span>
              Roles:{" "}
              {auth?.roles?.length
                ? auth.roles.map((r) => <Badge key={r} tone="neutral" className="ml-1 !text-[9.5px]">{r}</Badge>)
                : <Badge tone="neutral" className="ml-1 !text-[9.5px]">viewer · analyst · admin</Badge>}
            </span>
            <span>{auth?.registration_enabled === true ? "open registration" : "registration gated"}</span>
          </div>
        </form>

        <p className="text-center text-[10.5px] leading-relaxed text-muted/70">
          Access tokens are short-lived and kept in memory only; the refresh token rides an
          HttpOnly cookie. Authorization is enforced server-side for every request.
        </p>
      </div>
    </div>
  );
}

export default function AuthGate({ children }) {
  const { status, user } = useAuth();
  if (status === "booting") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-space-950">
        <span className="h-2 w-2 animate-ping rounded-full bg-lunar-400" />
      </div>
    );
  }
  return (
    <ToastProvider>
      {status === "authed" && user ? children : <AuthRequiredGate />}
    </ToastProvider>
  );
}