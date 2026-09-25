import { useState } from "react";

import { Badge, Icon } from "../components/ui.jsx";
import { apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

function fmtTs(iso) {
  if (!iso) return "—";
  return String(iso).replace("T", " ").replace("+00:00", " UTC").slice(0, 19) + " UTC";
}

export default function Account({ notify }) {
  const { user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const canSave = currentPassword && newPassword && newPassword === confirm;

  async function change(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await apiPost("/auth/me/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      notify({
        title: "Password changed",
        message: r.sessions_revoked ? "All other sessions were revoked." : "Password updated.",
        tone: "ok",
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirm("");
    } catch (err) {
      notify({ title: "Password change failed", message: err.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  const roleTone = user?.role === "admin" ? "gold" : user?.role === "analyst" ? "ok" : "blue";

  return (
    <div className="space-y-6">
      <section className="panel max-w-3xl space-y-2 p-5">
        <p className="eyebrow">Crew Account · Session</p>
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Account</h2>
        <p className="text-sm leading-relaxed text-muted">
          Your identity, session role and sign-in details. Passwords are verified against the
          stored hash on the server; changing one revokes every other session.
        </p>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-100">Identity</h3>
          <dl className="space-y-2.5 text-sm">
            <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
              <dt className="text-muted">Username</dt>
              <dd className="font-mono text-xs font-semibold text-slate-100">{user.username}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
              <dt className="text-muted">Display name</dt>
              <dd className="text-xs text-slate-200">{user.display_name || "—"}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
              <dt className="text-muted">Role</dt>
              <dd>
                <Badge tone={roleTone}>{user.role}</Badge>
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
              <dt className="text-muted">Account ID</dt>
              <dd className="font-mono text-[11px] text-slate-300">{user.id}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.04] pb-2">
              <dt className="text-muted">Account status</dt>
              <dd>
                {user.is_active ? <Badge tone="ok">active</Badge> : <Badge tone="danger">disabled</Badge>}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Created</dt>
              <dd className="font-mono text-[11px] text-slate-300">{fmtTs(user.created_at)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Last login</dt>
              <dd className="font-mono text-[11px] text-slate-300">{fmtTs(user.last_login_at)}</dd>
            </div>
          </dl>
        </div>

        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-100">Change password</h3>
          <form onSubmit={change} className="space-y-3.5">
            <label className="block space-y-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Current password</span>
              <input
                type="password"
                className="input w-full"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">New password</span>
              <input
                type="password"
                className="input w-full"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
              <span className="block text-[10.5px] text-muted">
                Minimum 8 characters, must include a letter and a digit.
              </span>
            </label>
            <label className="block space-y-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Confirm new password</span>
              <input
                type="password"
                className="input w-full"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </label>
            {newPassword && confirm && newPassword !== confirm && (
              <p className="flex items-center gap-1.5 text-[11px] text-danger">
                <Icon.Alert className="h-3 w-3" /> Passwords do not match.
              </p>
            )}
            <button type="submit" className="btn-primary" disabled={busy || !canSave}>
              {busy ? "Saving…" : "Change password"}
            </button>
            <p className="text-[10.5px] leading-relaxed text-muted">
              On success every other session you left open is revoked.
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}