import { useCallback, useEffect, useState } from "react";

import { Badge, Icon, PageSkeleton } from "../components/ui.jsx";
import { apiGet, apiPatch } from "../api.js";
import { useAuth } from "../auth.jsx";

function fmtTs(iso) {
  if (!iso) return "—";
  return String(iso).replace("T", " ").replace("+00:00", " UTC").slice(0, 16) + " UTC";
}

const EVENT_TONE = {
  LOGIN_SUCCESS: "ok",
  LOGIN_FAILURE: "danger",
  REGISTER: "blue",
  PASSWORD_CHANGE: "warn",
  ROLE_CHANGE: "gold",
  ACCOUNT_DISABLE: "danger",
  ACCOUNT_ENABLE: "ok",
  SESSION_REVOKED: "warn",
  SESSION_REVOKED_BY_ADMIN: "warn",
};

function RoleCell({ user, onPatch }) {
  const { user: me } = useAuth();
  const [role, setRole] = useState(user.role);
  const self = me?.id === user.id;
  useEffect(() => setRole(user.role), [user.role]);

  async function apply(next) {
    if (next === role) return;
    try {
      await onPatch(user.id, { role: next }, "Role updated");
      setRole(next);
    } catch {
      setRole(user.role); // server rejected (e.g. last active admin)
    }
  }

  return (
    <select
      className="input !w-auto !py-1 text-xs"
      value={role}
      onChange={(e) => apply(e.target.value)}
      disabled={self}
      title={self ? "You cannot change your own role" : "Change role"}
    >
      <option value="viewer">viewer</option>
      <option value="analyst">analyst</option>
      <option value="admin">admin</option>
    </select>
  );
}

export default function Security({ notify }) {
  const { user: me } = useAuth();
  const [summary, setSummary] = useState(null);
  const [users, setUsers] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(async (showOk) => {
    try {
      const [s, u] = await Promise.all([
        apiGet("/auth/security-summary"),
        apiGet("/auth/users"),
      ]);
      setSummary(s);
      setUsers(u.users ?? []);
      setError(null);
      if (showOk) notify({ title: "Security data refreshed", tone: "ok" });
    } catch (e) {
      setError(e);
    }
  }, [notify]);

  useEffect(() => {
    reload(false);
  }, [reload]);

  async function patchUser(userId, payload, okTitle) {
    try {
      await apiPatch(`/auth/users/${userId}`, payload);
      notify({ title: okTitle, message: "", tone: "ok" });
      await reload(false);
    } catch (e) {
      notify({ title: "Update rejected", message: e.message, tone: "danger" });
    }
  }

  if (!me) return null;

  if (error && !users && !summary) {
    return (
      <div className="card p-6">
        <p className="flex items-center gap-2 text-sm font-semibold text-danger">
          <Icon.Alert className="h-4 w-4" /> Unable to load security data.
        </p>
        <p className="mt-1 text-xs text-muted">{error.message}</p>
      </div>
    );
  }

  if (!summary || !users) return <PageSkeleton rows={3} />;

  const dist = summary.role_distribution || {};

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl space-y-2">
          <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Security</h2>
          <p className="text-sm leading-relaxed text-muted">
            Administrator view of the persistent account database: users, roles, session activity
            and the audit trail. Every change is written server-side and recorded.
          </p>
        </div>
        <button className="btn-ghost !px-3 !py-2 text-xs" onClick={() => reload(true)}>
          <Icon.Refresh className="h-3.5 w-3.5" /> Refresh
        </button>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="card p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Users</p>
          <p className="mt-1 text-2xl font-extrabold text-slate-100">{summary.total_users}</p>
          <p className="text-xs text-muted">{summary.active_users} active</p>
        </div>
        <div className="card p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Active sessions</p>
          <p className="mt-1 text-2xl font-extrabold text-slate-100">{summary.active_sessions}</p>
          <p className="text-xs text-muted">rotating refresh sessions</p>
        </div>
        <div className="card p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Role distribution</p>
          <p className="mt-2 flex flex-wrap gap-1.5 text-xs">
            {(["admin", "analyst", "viewer"]).map((r) => (
              <Badge key={r} tone={r === "admin" ? "gold" : r === "analyst" ? "ok" : "blue"}>
                {r}: {dist[r] ?? 0}
              </Badge>
            ))}
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Recent failures</p>
          <p className="mt-1 text-2xl font-extrabold text-slate-100">
            {(summary.recent_failed_logins || []).length}
          </p>
          <p className="text-xs text-muted">failed logins in audit window</p>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="card overflow-hidden lg:col-span-3">
          <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3">
            <h3 className="text-sm font-bold text-slate-100">Accounts</h3>
            <p className="text-[10.5px] text-muted">you cannot demote or disable yourself</p>
          </div>
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th className="w-28">Action</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const self = me?.id === u.id;
                  return (
                    <tr key={u.id}>
                      <td>
                        <div className="min-w-0">
                          <p className="truncate font-mono text-xs font-semibold text-slate-100">
                            {u.username}
                            {self && <span className="ml-2 text-lunar-400">(you)</span>}
                          </p>
                          <p className="truncate font-mono text-[10px] text-muted">
                            {u.id} · created {fmtTs(u.created_at)}
                          </p>
                        </div>
                      </td>
                      <td>
                        <RoleCell user={u} onPatch={patchUser} />
                      </td>
                      <td>
                        {u.is_active ? <Badge tone="ok">active</Badge> : <Badge tone="danger">disabled</Badge>}
                      </td>
                      <td>
                        <button
                          className="btn-ghost !px-2.5 !py-1 text-[11px]"
                          disabled={self}
                          title={self ? "You cannot disable your own account" : u.is_active ? "Disable account — revokes access until re-enabled" : "Re-enable account"}
                          onClick={() =>
                            patchUser(u.id, { is_active: !u.is_active }, u.is_active ? "Account disabled" : "Account enabled")
                          }
                        >
                          {u.is_active ? "Disable" : "Enable"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-xs text-muted">No accounts.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-5 lg:col-span-2">
          <div className="card p-5">
            <h3 className="mb-2 text-sm font-bold text-slate-100">Recent security events</h3>
            <ul className="space-y-2">
              {(summary.recent_security_events || []).map((ev, i) => (
                <li key={i} className="flex items-start justify-between gap-3 border-b border-white/[0.04] pb-2 text-[11px]">
                  <span className="flex items-center gap-2">
                    <Badge tone={EVENT_TONE[ev.event_type] || "neutral"} className="!text-[9.5px]">
                      {ev.event_type}
                    </Badge>
                    <code className="font-mono text-slate-300">{ev.username || ev.user_id || "—"}</code>
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-muted">{fmtTs(ev.occurred_at)}</span>
                </li>
              ))}
              {!summary.recent_security_events?.length && (
                <li className="text-xs text-muted">No security events recorded yet.</li>
              )}
            </ul>
          </div>
          <div className="card p-5">
            <h3 className="mb-2 text-sm font-bold text-slate-100">Failed logins</h3>
            <ul className="space-y-2">
              {(summary.recent_failed_logins || []).map((ev, i) => (
                <li key={i} className="flex items-center justify-between gap-3 border-b border-white/[0.04] pb-2 font-mono text-[11px]">
                  <span className="text-warn">{ev.username || ev.user_id || "unknown"}</span>
                  <span className="text-[10px] text-muted">{fmtTs(ev.occurred_at)}</span>
                </li>
              ))}
              {!summary.recent_failed_logins?.length && (
                <li className="text-xs text-muted">No failed logins in the audit window.</li>
              )}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}