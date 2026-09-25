# FRONTEND BLANK SCREEN — FIX REPORT (CHANDRASUTRA · SIH26166)

Status: **FIXED** — root cause found and repaired; verified in a real
Chromium runtime (dev splash → authed shell with live backend data), the TSX
production build, SSR render smoke, and a backend auth/security regression.

---

## 1. Reproduction

- URL: `http://localhost:5173/`
- Symptom: fully blank, dark viewport. `#root` ended up **empty**
  (`root.children.length === 0`). No sidebar, no signage, no bootsplash text.
- Verified in a real browser (headless Chromium via CDP) **and** by SSR:
  `App`+`AuthProvider` server-render → note below.

## 2. Root cause

`AuthProvider` (the auth context provider + gate in `frontend/src/auth.jsx`)
computes its context `value` from a **bounded dependency list**, and that list
**omitted one member of the context API that consumers rely on**:

```
refreshAuthStatus:  defineAuthCallback  →  <AuthProvider value={...}>
```

`AuthRequiredGate` (the gate that wraps the protected banter/shell) calls
`const { refreshAuthStatus } = useAuth()` and invokes it in a `useEffect` on
every status transition (booting→anon→retrying→anon→sign-in etc.).

Because the provider value did **not** contain a `refreshAuthStatus` member,
React mounted the gate, ran its effect, and threw:

```
TypeError: refreshAuthStatus is not a function
```

React 18 treated the failure in `<AuthRequiredGate>` as render-time and —
with no error boundary — **unmounted the entire root**, leaving a chrome-dark,
completely empty page. This is the *first* fatal error (the actual TypeError),
not a downstream effect of a network/API issue: even the very first render
crashed, before any API call could matter.

## 3. Exact error observed

```
Uncaught TypeError: refreshAuthStatus is not a function
The above error occurred in the <AuthRequiredGate> component:
Consider adding an error boundary to your tree…
TypeError: refreshAuthStatus is not a function
    at … (node_modules/.vite/deps/chunk-*.js)
```

Console confirmed two identical rethrows (React StrictMode double-invokes the
effect), consistent with the effect-crash theory. Zero independent API/network
errors preceded it — the project was otherwise healthy.

## 4. Files changed

| File | Change |
| --- | --- |
| `frontend/src/auth.jsx` | (1) Expose `refreshAuthStatus` in the provider's context value + dependency list. (2) Harden the bootsplash bootstrap against unhandled promise rejections so a flaky `/auth/refresh` or `/auth/me` can **never** blank the shell. |

No other frontend file touched. No backend file touched.

## 5. Fix implemented (minimal)

- Added `refreshAuthStatus` to the `useMemo` value object and its dependency
  array in `AuthProvider`, closing the contract gap that made
  `AuthRequiredGate` crash on mount.
- Wrapped the bootstrap async body in `try/catch` so any network/auth hiccup
  degrades to the existing anonymous sign-in state instead of an unhandled
  rejection that unmounts React.

## 6. Build result

```
npm run build  →  vite v7.3.6
✓ 55 modules transformed.
✓ built in 4.56s   (dist/assets/*.js 448.71 kB, *.css 35.40 kB)
exit 0
```

## 7. Backend test result

Focus regression — auth/security plus the shell's first-render endpoints:

- `pytest` (security + auth-required + auth_helpers): **7 passed** ✔
- Live API surface exercised from the browser after the fix:
  - `/api/health` → 200 `{"status":"ok",…}`
  - `/api/auth/refresh`, `/api/auth/me` → 200 (fresh login), tokens issued
  - `/api/metrics/overview`, `/api/matching/overview`, `/api/trust/overview`,
    `/api/spatial/overview`, `/api/registration/overview`, `/api/meta`,
    `/api/processing/overview` → **all 200** with real data payloads
    (`demo_mode: false`, milestone M11).
- Backend **left running and untouched** (health endpoint already OK → didn't
  restart/rebuild per directives).

## 8. Browser smoke-test result

Headless real browser (fresh profile, fresh user `blankfix_6039`):

1. First load → **sign-in screen renders** (not blank). No `refreshAuthStatus`
   exception, no render-time exception, no unhandled rejection.
2. Sign in via the real page network call → backend returns 200 + `access_token`.
3. Hard reload → **authed Overview shell renders** — Overview page HTTP 200,
   `/api/auth/me` 200 with `role: viewer`, Overview SSR string present, backend
   meta visible. Root children > 0.
4. Console: clean — no exceptions, no network errors (favicon 404 only,
   cosmetic).

## 9. Console status

After fix: **No console errors.** `vite connected` (dev-server websocket) and a
React DevTools info message only.

## 10. Network status

- Backend alive on `http://127.0.0.1:8000` (health `ok`).
- Vite dev proxy `/api` → `http://127.0.0.1:8000` (default `VITE_PROXY_TARGET`)
  confirmed by hitting `http://localhost:5173/api/health` through the browser.
- Auth refresh rides an HttpOnly cookie; `/api/auth/refresh` returns 200 with a
  new access token on the corrected path (`/api/auth/refresh`, not
  `/api/auth/refreshtoken`).

## 11. Regression status

Backend auth/security regression: **PASS (7 tests)**. Frontend full SSR smoke
(Overview, Evidence, Data, Analysis, Results, AI Insights, Account, Security +
M8/M9/M10 panels): **PASS**. `npm run build`: **PASS**. Existing M0–M13 modules
left intact — no milestone functionality removed.

## 12. Secondary bugs found/fixed

- **Primary:** `refreshAuthStatus` missing from `AuthProvider` context value —
  the direct blank-screen cause (fixed).
- **Secondary:** bootstrap `useEffect` could raise an unhandled rejection to an
  effect that had no error boundary — now caught so any refresh/`/me` failure
  falls back to the sign-in state (blank-proofing).

No hidden overlay/CSS/route issues found during the audit — the root container
was empty because React had unmounted, not because of a dark overlay.

## 13. Remaining warnings

- `#root` blank-recovery now relies on the sign-in state for
  unauthenticated/expired sessions, as designed (nothing fabricated; real
  Chandrayaan-2 OHRC×TMC-2 verification remains gated on actual PRADAN
  operator data; AI copilot uses Gemini when configured).
- The one favicon 404 is cosmetic and pre-existing.

## 14. Final status

- FRONTEND: **FIXED** — renders sign-in and the authed Overview shell in a real
  browser; no `refreshAuthStatus` TypeError; build + SSR + security regression
  green.
- BACKEND: healthy (`127.0.0.1:8000/api/health` → ok), untouched.
- REAL PRADAN DATA: **BLOCKED** (REAL_DATA_UNAVAILABLE — no genuine PRADAN
  pair provisioned yet; honest BLOCKED outcome by design, not simulated).
- GEMINI: configured/available per `/api/auth/status` (`ai: Gemini,
  configured: true`).
- SERVERS: **RUNNING** (backend + Vite dev server both detached/background).
