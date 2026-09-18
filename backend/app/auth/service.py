"""M10 authentication service: persistent users + sessions + authorization.

Persistence is SQLite at ``<data_root>/auth/auth.db`` (survives restarts;
never a global dict). Refresh tokens are stored as SHA-256 hashes only.
In-memory state is limited to login rate-limit counters (allowed by the
spec) and a lock guarding MySQLite ops.

The service decides *who may do what*. Endpoints only translate results.
Authentication never alters scientific truth: user identity is contextual
provenance metadata, never part of scientific digests.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import Settings, rfc3339_now
from ..errors import (
    AccountDisabledError,
    AuthNotConfiguredError,
    AuthRateLimitedError,
    AuthRequiredError,
    ForbiddenError,
    InvalidCredentialsError,
    NotFoundError,
    SessionRevokedError,
    TokenExpiredError,
    TokenInvalidError,
    ValidationError,
)
from ..security import Role
from .audit import SecurityAudit
from .config import AAuthConfig, load_auth_config
from .models import (
    RefreshSession,
    SafeUser,
    UserInDB,
    new_user_id,
)
from .password import assert_password_policy, hash_user_password, verify_user_password
from .tokens import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_jti,
)

_SCHEMA_VERSION = 1

_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_login_at TEXT
);
"""
_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS refresh_sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    token_hash  TEXT UNIQUE NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT,
    last_used_at TEXT NOT NULL
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    """The authoritative authentication/authorization service."""

    def __init__(self, settings: Settings, audit: SecurityAudit | None = None):
        self._settings = settings
        self._cfg: AAuthConfig = load_auth_config(settings)
        self._audit = audit or SecurityAudit(settings)
        self._lock = threading.RLock()
        self._failures: dict[str, list[float]] = {}
        self._lockouts: dict[str, float] = {}
        if settings.auth_configured:
            self._init_db()
            self._cleanup_sessions()
            self._bootstrap_admin()

    # ------------------------------------------------------------------
    # configuration / status
    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self._settings.auth_configured

    @property
    def config(self) -> AAuthConfig:
        return self._cfg

    def require_configured(self) -> None:
        if not self.configured:
            raise AuthNotConfiguredError(
                "Authentication is not configured (AUTH_SECRET_KEY is empty).",
                details={"configuration_id": self._cfg.configuration_id},
            )

    def status_dict(self, current_user: SafeUser | None = None) -> dict[str, Any]:
        return {
            "authentication_enabled": self.configured,
            "configured": self.configured,
            "milestone": "M10",
            "configuration_id": self._cfg.configuration_id,
            "configuration_version": self._cfg.configuration_version,
            "registration_enabled": bool(self._cfg.registration_enabled),
            "authenticated_user": current_user.as_dict() if current_user else None,
            "session_state": "AUTHENTICATED" if current_user else "UNAUTHENTICATED",
            "roles": [r.value for r in Role],
            "policy": dict(self._cfg.policy or {}),
            "access_token_ttl_seconds": self._cfg.access_token_ttl_seconds,
            "refresh_token_ttl_seconds": self._cfg.refresh_token_ttl_seconds,
        }

    # ------------------------------------------------------------------
    # database access (per-operation connections; lock for consistency)
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def _db_path(self) -> Path:
        return self._settings.auth_db_file

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_USERS_SQL)
                conn.executescript(_SESSIONS_SQL)
                # PRAGMA does not accept bound parameters in sqlite3.
                conn.execute("PRAGMA user_version = %d" % int(_SCHEMA_VERSION))
                conn.commit()
            finally:
                conn.close()

    def _row_to_user(self, row: sqlite3.Row | None) -> UserInDB | None:
        if row is None:
            return None
        return UserInDB(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            password_hash=row["password_hash"],
            role=Role(row["role"]),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
        )

    def _row_to_session(self, row: sqlite3.Row | None) -> RefreshSession | None:
        if row is None:
            return None
        return RefreshSession(
            id=row["id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
            last_used_at=row["last_used_at"],
        )

    def _fetch_user_by_username(self, username: str) -> UserInDB | None:
        norm = self._normalize(username)
        conn = self._connect()
        try:
            return self._row_to_user(
                conn.execute("SELECT * FROM users WHERE username = ?", (norm,)).fetchone()
            )
        finally:
            conn.close()

    def _fetch_user_by_id(self, user_id: str) -> UserInDB | None:
        conn = self._connect()
        try:
            return self._row_to_user(
                conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            )
        finally:
            conn.close()

    @staticmethod
    def _normalize(username: str) -> str:
        return username.strip().lower()

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------
    def register(self, username: str, password: str, display_name: str = "") -> SafeUser:
        self.require_configured()
        if not self._cfg.registration_enabled:
            raise ValidationError("Registration is disabled for this deployment.")
        self._throttle_register(username)
        norm = self._normalize(username)
        if not norm:
            raise ValidationError("A username is required.")
        assert_password_policy(password, policy=self._cfg.password_policy, username=norm)
        if self._fetch_user_by_username(norm) is not None:
            # duplicate identity: stable, safe message (identity already exists)
            raise InvalidCredentialsError("An account with this username already exists.", details={"code": "USERNAME_TAKEN"})
        user = UserInDB(
            id=new_user_id(),
            username=norm,
            display_name=display_name.strip()[:128],
            password_hash=hash_user_password(password),
            role=Role.VIEWER,  # default registration role is always viewer
            is_active=True,
            created_at=rfc3339_now(),
            updated_at=rfc3339_now(),
            last_login_at=None,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO users (id, username, display_name, password_hash, role, is_active, created_at, updated_at, last_login_at) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?, ?, NULL)",
                    (user.id, user.username, user.display_name, user.password_hash, user.role.value,
                     user.created_at, user.updated_at),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise InvalidCredentialsError(
                    "An account with this username already exists.", details={"code": "USERNAME_TAKEN"}
                ) from exc
            finally:
                conn.close()
        self._audit.record(
            event_type="REGISTER",
            success=True,
            endpoint="/api/auth/register",
            user_id=user.id,
            username=user.username,
        )
        return user.safe()

    # ------------------------------------------------------------------
    # login
    # ------------------------------------------------------------------
    def _throttle_login(self, username: str, now: float) -> None:
        low = username.strip().lower()
        with self._lock:
            lockout_until = self._lockouts.get(low, 0.0)
            if lockout_until > now:
                raise AuthRateLimitedError("Too many failed attempts. Please wait before trying again.")

    def _record_login_failure(self, username: str, now: float) -> None:
        low = username.strip().lower()
        limit = self._cfg.login_rate_limit
        with self._lock:
            bucket = [t for t in self._failures.get(low, []) if now - t < limit.window_seconds]
            bucket.append(now)
            self._failures[low] = bucket
            if len(bucket) >= limit.max_attempts:
                self._lockouts[low] = now + limit.lockout_seconds
                self._failures.pop(low, None)

    def _clear_login_failures(self, username: str) -> None:
        low = username.strip().lower()
        with self._lock:
            self._failures.pop(low, None)
            self._lockouts.pop(low, None)

    def _throttle_register(self, username: str) -> None:
        # light global guard so registration cannot be spammed
        with self._lock:
            now = time.time()
            seen = [t for t in self._failures.get(f"@{username.strip().lower()}", []) if now - t < 60]
            if len(seen) >= 10:
                raise AuthRateLimitedError("Too many registration attempts. Please wait.")
            seen.append(now)
            self._failures[f"@{username.strip().lower()}"] = seen

    def login(self, username: str, password: str) -> dict[str, Any]:
        self.require_configured()
        now_time = time.time()
        self._throttle_login(username, now_time)
        user = self._fetch_user_by_username(username)
        ok = user is not None and verify_user_password(password, user.password_hash)
        if not ok:
            # generic invalid-credential response for unknown user AND wrong password
            self._record_login_failure(username, now_time)
            reason = "account_disabled" if (user is not None and not user.is_active) else "invalid_credentials"
            self._audit.record(
                event_type="LOGIN_FAILURE",
                success=False,
                endpoint="/api/auth/login",
                user_id=user.id if user else None,
                username=user.username if user else None,
                metadata={"reason": reason},
            )
            raise InvalidCredentialsError("Invalid username or password.")
        if not user.is_active:
            self._record_login_failure(username, now_time)
            self._audit.record(
                event_type="LOGIN_FAILURE",
                success=False,
                endpoint="/api/auth/login",
                user_id=user.id,
                username=user.username,
                metadata={"reason": "account_disabled"},
            )
            raise InvalidCredentialsError("Invalid username or password.")
        self._record_login_success(user)
        access = create_access_token(settings=self._settings, subject=user.id, role=user.role, auth_config=self._cfg)
        refresh_raw, refresh_hash, session = self._issue_refresh_session(user)
        self._audit.record(
            event_type="LOGIN_SUCCESS",
            success=True,
            endpoint="/api/auth/login",
            user_id=user.id,
            username=user.username,
        )
        return {
            "access_token": access,
            "token_type": "bearer",
            "expires_in": self._cfg.access_token_ttl_seconds,
            "user": user.safe().as_dict(),
            "refresh_token": refresh_raw,
            "refresh_token_expires_in": self._cfg.refresh_token_ttl_seconds,
            "session_id": session.id,
        }

    def _record_login_success(self, user: UserInDB) -> None:
        now = rfc3339_now()
        conn = self._connect()
        try:
            conn.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                         (now, now, user.id))
            conn.commit()
        finally:
            conn.close()
        self._clear_login_failures(user.username)

    def _issue_refresh_session(self, user: UserInDB) -> tuple[str, str, RefreshSession]:
        raw, digest = generate_refresh_token()
        now = _utcnow()
        refresh_ttl = self._cfg.refresh_token_ttl_seconds
        idle_ttl = self._cfg.session_idle_ttl_seconds
        expires = min(now + timedelta(seconds=refresh_ttl), now + timedelta(seconds=idle_ttl))
        session = RefreshSession(
            id=refresh_jti(),
            user_id=user.id,
            token_hash=digest,
            created_at=rfc3339_now(),
            expires_at=expires.isoformat(timespec="seconds"),
            revoked_at=None,
            last_used_at=rfc3339_now(),
        )
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO refresh_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (session.id, session.user_id, session.token_hash, session.created_at,
                 session.expires_at, session.last_used_at),
            )
            conn.commit()
        finally:
            conn.close()
        return raw, digest, session

    # ------------------------------------------------------------------
    # refresh + rotation
    # ------------------------------------------------------------------
    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Rotate a refresh token: issue a new access token + new refresh token,
        and revoke the presented one (replay-safe)."""
        self.require_configured()
        if not refresh_token:
            raise AuthRequiredError("A refresh token is required.")
        digest = hash_refresh_token(refresh_token)
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM refresh_sessions WHERE token_hash = ?", (digest,)).fetchone()
            session = self._row_to_session(row)
            if session is None:
                self._audit.record(event_type="TOKEN_REFRESH", success=False, endpoint="/api/auth/refresh",
                                   metadata={"reason": "unknown_session"})
                raise SessionRevokedError("The session does not exist or was revoked.")
            now = _utcnow()
            if session.revoked_at:
                self._audit.record(event_type="TOKEN_REFRESH", success=False, endpoint="/api/auth/refresh",
                                   metadata={"reason": "revoked_replay"})
                raise SessionRevokedError("The session has been revoked.")
            if datetime.fromisoformat(session.expires_at) < now:
                self._revoke_sessions_by_hash(conn, digest)
                conn.commit()
                self._audit.record(event_type="TOKEN_REFRESH", success=False, endpoint="/api/auth/refresh",
                                   metadata={"reason": "expired"})
                raise TokenExpiredError("The session has expired; please sign in again.")
            user = self._fetch_user_by_id(session.user_id)
            if user is None or not user.is_active:
                self._revoke_sessions_by_hash(conn, digest)
                conn.commit()
                self._audit.record(event_type="TOKEN_REFRESH", success=False, endpoint="/api/auth/refresh",
                                   user_id=session.user_id, metadata={"reason": "account_disabled"})
                raise AccountDisabledError("This account is disabled.")
            # rotate: revoke presented session
            self._revoke_sessions_by_hash(conn, digest)
            conn.commit()
        finally:
            conn.close()

        access = create_access_token(settings=self._settings, subject=user.id, role=user.role, auth_config=self._cfg)
        refresh_raw, refresh_hash, new_session = self._issue_refresh_session(user)
        self._audit.record(
            event_type="TOKEN_REFRESH",
            success=True,
            endpoint="/api/auth/refresh",
            user_id=user.id,
            username=user.username,
        )
        return {
            "access_token": access,
            "token_type": "bearer",
            "expires_in": self._cfg.access_token_ttl_seconds,
            "user": user.safe().as_dict(),
            "refresh_token": refresh_raw,
            "refresh_token_expires_in": self._cfg.refresh_token_ttl_seconds,
            "session_id": new_session.id,
        }

    @staticmethod
    def _revoke_sessions_by_hash(conn: sqlite3.Connection, digest: str) -> None:
        conn.execute(
            "UPDATE refresh_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (rfc3339_now(), digest),
        )

    # ------------------------------------------------------------------
    # logout / revocation
    # ------------------------------------------------------------------
    def logout(self, refresh_token: str, user_id: str | None = None) -> dict[str, Any]:
        self.require_configured()
        revoked = 0
        if refresh_token:
            digest = hash_refresh_token(refresh_token)
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE refresh_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                    (rfc3339_now(), digest),
                )
                conn.commit()
                revoked = cur.rowcount or 0
            finally:
                conn.close()
        elif user_id:
            # sign-out-everywhere fallback: revoke all sessions for the user
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE refresh_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (rfc3339_now(), user_id),
                )
                conn.commit()
                revoked = cur.rowcount or 0
            finally:
                conn.close()
        self._audit.record(
            event_type="LOGOUT",
            success=True,
            endpoint="/api/auth/logout",
            user_id=user_id,
            metadata={"sessions_revoked": revoked},
        )
        return {"logged_out": True, "sessions_revoked": revoked}

    # ------------------------------------------------------------------
    # current user + authorization
    # ------------------------------------------------------------------
    def get_current_user_from_authorization(self, authorization: str | None) -> SafeUser:
        self.require_configured()
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthRequiredError("Authentication is required (provide a bearer token).")
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = decode_access_token(self._settings, token)
        except TokenExpiredError:
            raise
        except TokenInvalidError:
            raise
        user = self._fetch_user_by_id(str(claims.get("sub", "")))
        if user is None:
            raise TokenInvalidError("The access token references an unknown user.")
        if not user.is_active:
            raise AccountDisabledError("This account is disabled. Contact an administrator.")
        return user.safe()

    def require_role(self, user: SafeUser, *roles: Role) -> SafeUser:
        allowed = {r.value for r in roles}
        if user.role not in allowed:
            self._audit.record(
                event_type="PROTECTED_ACCESS_DENIED",
                success=False,
                endpoint="protected-route",
                user_id=user.id,
                username=user.username,
                metadata={"granted_role": user.role, "required_roles": sorted(allowed)},
            )
            raise ForbiddenError("Insufficient privileges for this operation.", details={"required_roles": sorted(allowed)})
        return user

    # ------------------------------------------------------------------
    # session revocation (single session, admin-initiated)
    # ------------------------------------------------------------------
    def revoke_session(self, admin: SafeUser, session_id: str) -> dict[str, Any]:
        """Revoke exactly one refresh session by its id. Returns the revoked
        session's owner id and the number of rows changed (0 + error otherwise)."""
        self.require_configured()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, user_id FROM refresh_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("No such session.")
            revoked_user_id = row["user_id"]
            cur = conn.execute(
                "UPDATE refresh_sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (rfc3339_now(), session_id),
            )
            conn.commit()
            revoked = cur.rowcount or 0
        finally:
            conn.close()
        self._audit.record(
            event_type="TOKEN_REVOKED",
            success=True,
            endpoint="/api/auth/sessions/{id}",
            user_id=admin.id,
            username=admin.username,
            metadata={"session_id": session_id, "owner_user_id": revoked_user_id, "revoked": revoked},
        )
        return {"revoked": bool(revoked), "session_id": session_id, "owner_user_id": revoked_user_id}

    # ------------------------------------------------------------------
    # password change
    # ------------------------------------------------------------------
    def change_password(self, user: SafeUser, current: str, new_password: str) -> None:
        self.require_configured()
        stored = self._fetch_user_by_id(user.id)
        if stored is None or not verify_user_password(current, stored.password_hash):
            raise InvalidCredentialsError("The current password is incorrect.")
        assert_password_policy(new_password, policy=self._cfg.password_policy, username=stored.username)
        new_hash = hash_user_password(new_password)
        now = rfc3339_now()
        conn = self._connect()
        try:
            conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                         (new_hash, now, user.id))
            conn.execute("UPDATE refresh_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                         (now, user.id))
            conn.commit()
        finally:
            conn.close()
        self._audit.record(event_type="PASSWORD_CHANGE", success=True, endpoint="/api/auth/me/password",
                           user_id=user.id, username=user.username)

    # ------------------------------------------------------------------
    # admin: users
    # ------------------------------------------------------------------
    def list_users(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        finally:
            conn.close()
        users = [self._row_to_user(r).safe().as_dict() for r in rows if r is not None]
        active_ids = {u["id"] for u in users if u["is_active"]}
        return _attach_session_counts(users, active_ids, self._count_sessions)

    def _count_sessions(self, user_id: str) -> int:
        conn = self._connect()
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM refresh_sessions WHERE user_id = ? AND revoked_at IS NULL",
                    (user_id,),
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def get_user(self, user_id: str) -> dict[str, Any]:
        user = self._fetch_user_by_id(user_id)
        if user is None:
            raise ForbiddenError("No such user.")
        public = user.safe().as_dict()
        public["active_sessions"] = self._count_sessions(user.id)
        return public

    def patch_user(self, actor: SafeUser, user_id: str, *, new_role: Role | None = None, is_active: bool | None = None) -> dict[str, Any]:
        if new_role is None and is_active is None:
            return self.get_user(user_id)
        target = self._fetch_user_by_id(user_id)
        if target is None:
            raise ForbiddenError("No such user.")

        actor_role = Role(actor.role)
        active_admin_count = self._active_admin_count()

        # safety rules: no self-elevation, no disabling yourself, and the last
        # active administrator can never be demoted or disabled (self included).
        if new_role is not None:
            if target.id == actor.id and new_role.rank > actor_role.rank:
                raise ForbiddenError("An administrator cannot elevate their own role.")
            if target.role == Role.ADMIN and new_role != Role.ADMIN and active_admin_count <= 1:
                raise ForbiddenError("Cannot change the role of the last active administrator.")
        if is_active is False:
            if active_admin_count <= 1 and target.role == Role.ADMIN:
                raise ForbiddenError("Cannot disable the last active administrator.")
            if target.id == actor.id:
                raise ForbiddenError("Cannot disable your own account.")

        changes: list[str] = []
        final_role = target.role if new_role is None else new_role
        final_active = target.is_active if is_active is None else is_active
        if new_role is not None and new_role != target.role:
            changes.append("role")
        if is_active is not None and is_active != target.is_active:
            changes.append("active")

        now = rfc3339_now()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE users SET role = ?, is_active = ?, updated_at = ? WHERE id = ?",
                (final_role.value, 1 if final_active else 0, now, target.id),
            )
            conn.commit()
        finally:
            conn.close()
        if "role" in changes:
            self._audit.record(event_type="ROLE_CHANGE", success=True, endpoint="/api/auth/users/{id}",
                               user_id=target.id, username=target.username,
                               metadata={"from": target.role.value, "to": final_role.value, "actor": actor.id})
        if "active" in changes:
            event = "ACCOUNT_ENABLED" if final_active else "ACCOUNT_DISABLED"
            self._audit.record(event_type=event, success=True, endpoint="/api/auth/users/{id}",
                               user_id=target.id, username=target.username,
                               metadata={"is_active": final_active, "actor": actor.id})
        return self.get_user(target.id)

    def _active_admin_count(self) -> int:
        conn = self._connect()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM users WHERE role = ? AND is_active = 1", (Role.ADMIN.value,)).fetchone()[0])
        finally:
            conn.close()

    def security_summary(self) -> dict[str, Any]:
        self.require_configured()
        conn = self._connect()
        try:
            total_users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            active_users = int(conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0])
            active_sessions = int(conn.execute("SELECT COUNT(*) FROM refresh_sessions WHERE revoked_at IS NULL").fetchone()[0])
            role_rows = conn.execute("SELECT role, COUNT(*) AS n FROM users GROUP BY role ORDER BY role").fetchall()
        finally:
            conn.close()
        role_distribution = {r["role"]: int(r["n"]) for r in role_rows}
        recent = self._audit.read_recent(limit=100)
        failed = [e for e in recent if e.get("event_type") == "LOGIN_FAILURE"]
        return {
            "active_users": active_users,
            "active_sessions": active_sessions,
            "role_distribution": role_distribution,
            "recent_security_events": recent[:20],
            "recent_failed_logins": failed[:10],
            "total_users": total_users,
            "authentication_enabled": self.configured,
            "configuration_id": self._cfg.configuration_id,
        }

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------
    def _cleanup_sessions(self) -> None:
        """Lazy cleanup: delete revoked/expired sessions older than 30 days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM refresh_sessions WHERE (revoked_at IS NOT NULL AND revoked_at < ?) OR (revoked_at IS NULL AND expires_at < ?)",
                (cutoff, cutoff),
            )
            conn.commit()
        finally:
            conn.close()

    def _bootstrap_admin(self) -> None:
        username = self._settings.auth_bootstrap_admin_username.strip()
        password = self._settings.auth_bootstrap_admin_password.strip()
        if not username or not password:
            return
        conn = self._connect()
        try:
            count = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        finally:
            conn.close()
        if count:
            return
        user = UserInDB(
            id=new_user_id(),
            username=self._normalize(username),
            display_name="Initial administrator",
            password_hash=hash_user_password(password),
            role=Role.ADMIN,
            is_active=True,
            created_at=rfc3339_now(),
            updated_at=rfc3339_now(),
        )
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO users (id, username, display_name, password_hash, role, is_active, created_at, updated_at, last_login_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, NULL)",
                (user.id, user.username, user.display_name, user.password_hash, user.role.value,
                 user.created_at, user.updated_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()
        self._audit.record(event_type="BOOTSTRAP_ADMIN", success=True, endpoint="startup",
                           user_id=user.id, username=user.username)


def _attach_session_counts(users: list[dict[str, Any]], active_ids: set[str], counter) -> list[dict[str, Any]]:
    for u in users:
        u["active_sessions"] = counter(u["id"]) if u["id"] in active_ids else 0
    return users


def build_auth_service(settings: Settings) -> AuthService:
    return AuthService(settings)


__all__ = ["AuthService", "build_auth_service"]