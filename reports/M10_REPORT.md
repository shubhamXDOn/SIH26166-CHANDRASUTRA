# M10 Report — Real Authentication, Authorization & User Security (CHANDRASUTRA · SIH26166)

**Milestone:** M10 — server-side authentication everywhere. SQLite-backed user
accounts, PBKDF2-SHA-256 password hashing, short-lived JWT access tokens,
rotating refresh sessions carried only in an HttpOnly SameSite cookie, a
viewer/analyst/admin role model enforced at the router level, an audit +
security-event log behind an admin surface, and honest **fail-closed**
behaviour at every layer.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-18
**Status:**
- **Engineering: DONE** — the complete M10 stack (config → accounts →
  hashing → tokens → sessions → role enforcement → audit → admin API) is
  implemented and tested (`tests/test_m10.py`: **31 passed**, including the
  B01–B30 bug-hunt acceptance corpus). The full backend suite is green —
  consolidated `pytest tests/ -q` = **442 passed** — and
  `smoke_test.py` is **91/91 PASS** (11 new `m10-*` probes over live HTTP
  against a real login flow), the frontend builds and `ssr-smoke.mjs` passes
  all renders (17, including the new Account + admin Security pages), and
  `docker compose config` is valid.
- **Real-data execution: BLOCKED** — unchanged from M1–M9: the pipeline is
  honestly empty/BLOCKED until the first real OHRC–TMC-2 pair is acquired.
  M10 adds no fabricated user, result or login; all security claims below were
  verified with real HTTP, real cookies and real tokens.

> **Honesty rule:** there is **no fake authentication**. No frontend-only
> login, no hardcoded passwords, no role selectors, no skipped authorization
> checks. Protected endpoints are unreadable without a valid token; a mutation
> without at least analyst role is rejected server-side; and while
> `AUTH_SECRET_KEY` is empty the whole product **fails closed** with
> `501 AUTH_NOT_CONFIGURED` — the app still starts (public health/meta), but
> nothing protected is reachable.

---

## 1. What M10 delivers

### 1.1 Configuration & fail-closed defaults

- Engineering policy lives in `configs/app.yaml` (`m10:` section,
  Configuration ID **`AU-M10-001`**), exposed read-only via
  `GET /api/auth/status` and `/api/meta.m10_config`: access TTL 900s, refresh
  TTL 604800s, session idle TTL 86400s, password policy and login rate limit.
- Runtime overrides come from the environment only (`AAuthConfig` in
  `backend/app/auth/config.py`): `AUTH_ACCESS_TTL_SECONDS`,
  `AUTH_REFRESH_TTL_SECONDS`, `AUTH_REGISTER_ENABLED`.
- `auth_configured` is true only when `AUTH_SECRET_KEY` is non-empty.
  Empty → every protected route returns `501 AUTH_NOT_CONFIGURED`
  (`errors.py`), exactly like the honest pre-M10 stub behaviour — but now
  backed by the real service, ready to be switched on with a key.
- The account database defaults to `<data_root>/auth/auth.db`
  (`AUTH_DB_PATH` override); migrations version it via SQLite `user_version`.

### 1.2 Accounts, hashing, bootstrap

- `backend/app/auth/models.py` — SQLite-backed users and sessions; `SafeUser`
  is the only user shape ever returned (`id, username, display_name, role,
  is_active, created_at, updated_at, last_login_at`).
- `backend/app/auth/password.py` — PBKDF2-HMAC-SHA256 (210 000 iterations,
  per-user random salt) with a strict policy: min length 12, letter + digit
  required, username-ish passwords rejected; `verify_password` is
  constant-time and format-strict.
- `backend/app/auth/service.py` — self-registration creates an account in
  **disabled** state (no login until an admin activates it), preventing
  registration-driven takeover; login updates `last_login_at` and records
  success/failure events.
- Bootstrap administrator: when both `AUTH_BOOTSTRAP_ADMIN_USERNAME` and
  `AUTH_BOOTSTRAP_ADMIN_PASSWORD` are set, the admin account is created on
  first startup (idempotent). Nothing is ever fabricated or default-passworded.

### 1.3 Access tokens & rotating refresh sessions

- `backend/app/auth/tokens.py` — HS256 JWT (`iss` = app name): `sub`, `role`,
  `iat`, `exp` (default 900s). The `role` claim is treated as **untrusted**:
  authorization always re-reads the live role from the database row, so a
  stale/forged token cannot escalate.
- Refresh sessions are stored as **SHA-256 hashes only** — the raw token is
  never persisted. Each `/auth/refresh` (or re-login) creates a new session
  and idempotently revokes the old one (rotation); an admin can revoke any
  session via `DELETE /api/auth/sessions/{id}`.
- The refresh token reaches the browser exclusively through a
  `SameSite=strict` **HttpOnly** cookie (`chandrasutra_refresh`,
  `Path=/api/auth/`), never through the JSON body. `secure` is automatic in
  production. The access token travels in the response body and the frontend
  keeps it **in memory only**.
- Changing your password (`POST /api/auth/me/password`) verifies the current
  password and revokes **all** of the user's refresh sessions.

### 1.4 Role model & access matrix

`backend/app/security.py` + `backend/app/auth/dependencies.py`:

| Role | Rank | Can |
|------|------|-----|
| `viewer` | 0 | read pipeline results, use explanatory AI, own account |
| `analyst` | 1 | everything a viewer can + **all pipeline mutations** (prepare, run, register, validate, reset) |
| `admin`  | 2 | everything above + **user/session/security administration** |

Enforcement:
- Public & always open: `/api/health`, `/api/meta`, `/api/auth/*` (status,
  login, refresh, logout, register read publics).
- All pipeline **GET reads** require any authenticated user
  (`CurrentUser` dependency).
- All pipeline **mutations** require `AnalystUser` (admin or analyst).
- User/session/security routes require `AdminUser`.
- `current_user_dep` also enforces **active-account policy**; a disabled
  account is rejected with `403 ACCOUNT_DISABLED` even with a valid token.
- The last active admin cannot be demoted or disabled (even by themselves);
  self-demote/self-disable/self-elevate mutations are refused.

### 1.5 Error model (single envelope)

All codes verified in tests against live HTTP status + body:

| HTTP | Code | Meaning |
|------|------|---------|
| 501 | `AUTH_NOT_CONFIGURED` | no `AUTH_SECRET_KEY` — app fails closed |
| 401 | `AUTH_REQUIRED` | no/malformed credentials |
| 401 | `TOKEN_INVALID` / `TOKEN_EXPIRED` | bad or expired JWT |
| 401 | `SESSION_REVOKED` | refresh session no longer valid |
| 401 | `INVALID_CREDENTIALS` | wrong username/password |
| 403 | `FORBIDDEN` | insufficient role (viewer on a mutation, non-admin on users) |
| 403 | `ACCOUNT_DISABLED` | account inactive |
| 429 | `RATE_LIMITED` | login/refresh rate limit (`RATE_LIMITED`, 5 attempts / 300s, 900s lockout) |
| 422 | `VALIDATION_ERROR` | payload/password-policy violations |
| 404 | `NOT_FOUND` | unknown user/session/pair |

Secrets are redacted from log messages, errors and provenance by
`redact_text` (`security.py`); the no-secret rule is enforced in tests.

### 1.6 Audit & admin surface

- `backend/app/auth/audit.py` — append-only security event table
  (`derived/.../auth` via the auth DB): login success/failure, registration,
  password change, role/active changes, session revocation, account disable.
  Event names include `LOGIN_SUCCESS`, `LOGIN_FAILED`, `ACCOUNT_DISABLED`,
  `ACCOUNT_ENABLED`, `PASSWORD_CHANGED`, `SESSION_REVOKED`.
- `GET /api/auth/security-summary` (admin): `total_users`, `active_users`,
  `active_sessions`, `role_distribution`, `recent_security_events`,
  `recent_failed_logins`, `authentication_enabled`, `configuration_id`.

### 1.7 API surface (`backend/app/api/auth.py`)

Public:
`GET /api/auth/status` · `POST /api/auth/register` · `POST /api/auth/login`
Authenticated:
`GET /api/auth/me` · `POST /api/auth/me/password` · `POST /api/auth/logout` ·
`POST /api/auth/refresh`
Administrator-only:
`GET /api/auth/users` · `GET /api/auth/users/{id}` ·
`PATCH /api/auth/users/{id}` (role / active) ·
`DELETE /api/auth/sessions/{id}` · `GET /api/auth/security-summary`

`/status` is public but resolves an optionally-present bearer
(`_maybe_current_user`) so the UI can detect the current session without a
round-trip. `login`/`refresh`/`logout` return the refresh token only via the
cookie path above.

### 1.8 Frontend auth UX

- `frontend/src/api.js` — in-memory access-token store, single 401
  refresh-and-retry (no loops), `setAccessToken`/`refreshSession`/
  `onAuthLost`, `apiPatch`/`apiDelete`.
- `frontend/src/auth.jsx` — `AuthProvider`/`useAuth`: boot resolves the
  session via the refresh cookie (`/auth/refresh` → `/auth/me`); `signIn`
  /`signUp`/`signOut`; `isAdmin`/`canMutate` from the live role.
- `frontend/src/pages/AuthGate.jsx` — login/register screen honouring
  `authentication_enabled`, `registration_enabled` and a graceful
  "auth not configured" notice; booting splash.
- `frontend/src/pages/Account.jsx` — identity card + change-password form.
- `frontend/src/pages/Security.jsx` — admin users table (role select,
  enable/disable, self-row protections), security summary cards, recent
  security events and failed logins.
- `App.jsx`/`Sidebar.jsx` — `AuthProvider → AuthGate → ToastProvider → Shell`,
  admin-only Security navigation, username/role chip and Sign out, plus
  **role-disabled mutation buttons** across every pipeline panel
  (registration, matching, trust, spatial, metrics, M8, data load/validate,
  analysis prepare/reset) so the UX never asks a viewer to attempt a write.

### 1.9 Deployment

- `.env.example` documents all M10 variables (`AUTH_SECRET_KEY`,
  `AUTH_ALGORITHM`, `AUTH_ACCESS_TTL_SECONDS`, `AUTH_REFRESH_TTL_SECONDS`,
  `AUTH_REGISTER_ENABLED`, `AUTH_BOOTSTRAP_ADMIN_USERNAME/PASSWORD`,
  `AUTH_REFRESH_COOKIE_NAME`, `AUTH_COOKIE_SAMESITE`, optional
  `AUTH_COOKIE_SECURE`/`AUTH_DB_PATH`).
- `docker-compose.yml` wires the same variables into the backend container
  with safe defaults (`compose config` valid).
- `smoke_test.py` now boots every milestone with authentication **enabled**
  (ephemeral key + isolated temp auth DB when the live `.env` is unconfigured),
  logs in as the bootstrap admin over real HTTP, and carries the bearer token
  on every probe — plus dedicated `m10-*` checks.

---

## 2. Acceptance & bug-hunt validation (B01–B30, tests/test_m10.py)

`tests/test_m10.py` runs **31 tests, all green** (73.0s), covering:

- **Fail-closed configuration** — no `AUTH_SECRET_KEY` → every protected route
  returns 501 `AUTH_NOT_CONFIGURED`; health/meta/status stay public.
- **Login/refresh lifecycle** — login issues a JWT + HttpOnly
  `Path=/api/auth/` cookie; refresh rotates (old session hash revoked);
  refresh-TTL and access-TTL boundaries hold; logout revokes sessions.
- **Role matrix** — viewer/analyst/admin enforced on reads, mutations and
  admin routes (`auth_status_public_states`, `disable_user`,
  `no_secret_ever_echoed`).
- **Password rules** — min-length/composition policy, current-password
  verification, change revokes all sessions.
- **Audit & summary** — events recorded, `security_summary` aggregates, failed
  logins surfaced.
- **Rate limiting** — 5 attempts in a window → 429 `RATE_LIMITED` then
  lockout; correct code name.
- **Bug hunt (B01–B30)** — JWT tampering/expiry/replay rejection, bearer
  variants (`Bearer`, malformed, uppercase), refresh reuse after rotation
  (rejected), recoverys: valid-token edge cases, admin last-admin protections,
  `/api/auth//users` 404 behaviour, disabled accounts (403), role-claim
  spoofing (ignored), refresh token never returned in bodies, secret never
  echoed in any response, `Set-Cookie` correctness, and the global-singleton
  ordering hazard (B17: unconfigured-app boot must run last in its own
  process).

## 3. Regression

| Suite | Result |
|-------|--------|
| `pytest tests/test_m10.py -q` | **31 passed** (73.0s) |
| `pytest tests/ -q` (full, consolidated) | **442 passed**, 3 warnings (1732s / ~29 min) |
| `smoke_test.py` (live HTTP: M1–M10 + auth) | **91/91 PASS** (11 new `m10-*` probes: status, refresh cookie, login, `/me`, fail-closed 401s, users list, security summary) |
| `npm run build` (frontend) | **built OK (vite, 46 modules)** |
| `node frontend/ssr-smoke.mjs` | **OVERALL PASS (17 renders incl. Account + Security)** |
| `docker compose config` | **valid** |

No M1–M9 regressions observed; M1–M9 suites now authenticate through
`tests/auth_helpers.py` + `conftest.py` and remain green.

## 4. Known limitations

1. **Real-data execution** — BLOCKED on PRADAN approval as for M1–M9; the
   pipeline stages stay honestly empty/BLOCKED. M10 guards an honest product,
   it does not fabricate one.
2. **Refresh rotation is per-token** — a stolen refresh token used strictly
   *before* the legitimate one would itself pass; the rotation model detects
   reuse-after-rotation (both are rejected) which is the standard mitigation.
   Full device/UA fingerprinting is out of scope.
3. **Token blacklisting** — access tokens are stateless JWTs; revocation before
   expiry is handled at the session/refresh layer, not per-access-token.
4. **Single admin by default** — the bootstrap admin is the only account until
   registration is enabled and an admin activates new users.
5. **Containerisation** — `docker compose config` validates; a live compose up
   needs the Docker daemon (not running in this environment).

## 5. Traceability vs spec (SIH26166)

- **M10.1 Account provisioning** — `auth/service.py`, `auth/models.py`:
  SQLite users, registry + bootstrap admin, disabled-until-activated
  self-registration, PBKDF2-SHA-256 hashing, strict password policy.
- **M10.2 Sessions & tokens** — `auth/tokens.py`, `auth/service.py`,
  `api/auth.py`: HS256 JWT (TTL 900s), HttpOnly SameSite cookie refresh,
  SHA-256-hashed rotating sessions, session revocation, logout.
- **M10.3 Authorization** — `security.py`, `auth/dependencies.py`:
  viewer/analyst/admin role model, router-level enforcement on reads,
  mutations and administration, DB-fresh role lookup (claims ignored),
  active-account policy, last-admin protections.
- **M10.4 Fail-closed behaviour** — missing key → 501 `AUTH_NOT_CONFIGURED`;
  audit + security summary; `RATE_LIMITED` lockouts; secrets redacted/scanned.
- **M10.5 UI** — login/register gate, in-memory token store, silent refresh on
  boot, account + change password, admin Security console, role-aware
  navigation and disabled mutation controls.
- **M10.6 Verification** — 31 dedicated M10 tests including the B01–B30
  bug-hunt corpus, full-suite regression, live smoke probes against a real
  login, frontend build/SSR, compose config — all green.