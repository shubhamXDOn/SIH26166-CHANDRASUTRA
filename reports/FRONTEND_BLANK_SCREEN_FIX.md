# FRONTEND BLANK-SCREEN FIX — CHANDRASUTRA (SIH26166)

## Status: FIXED

## 1. Reproduction
- URL: `http://localhost:5173/` (Vite dev), backend `http://127.0.0.1:8000` (FastAPI).
- Symptom reported by operator: page rendered as a **completely dark, blank
  viewport** (no CHANDRASUTRA UI, no sidebar, no sign-in page). The dark tone
  came from `body` CSS background only; React `#root` was **empty**.
- Independent reproduction (headless Chrome via CDP, real Vite dev server +
  live backend): `#root` empty, and the only hard error on first load was a
  **render-time TypeError** (below). No network/API errors on the original
  code path — a genuine runtime crash, not an upstream failure.

## 2. Root cause
`AuthProvider` in `frontend/src/auth.jsx` returned a context value that did
**not** include `refreshAuthStatus`, yet the app's `AuthRequiredGate`
(`frontend/src/AuthGate.jsx`) destructures it and calls it unconditionally
from a `useEffect`. On first mount:

```
TypeError: refreshAuthStatus is not a function
```
thrown inside `<AuthRequiredGate>` → React unmounted the whole tree → `#root`
ended up empty → blank dark page (no error boundary existed, so the error was
not surfaced to the user; only an unhandled console error).

SSR smoke (`frontend/ssr-smoke.mjs`) passed for every page/component, which
confirms the failure was specifically in the authenticated gate bootstrap and
not in any page component or import graph.

## 3. Exact error observed (browser console)
```
Uncaught TypeError: refreshAuthStatus is not a function
The above error occurred in the <AuthRequiredGate> component:
Consider adding an error boundary…
```
(also surfaced during SSR when the authed gate ran its effect in a browser).

Additionally the auth bootstrap's async IIFE had no local rejection guard, so
an unhandled refresh/auth failure could have left the shell stuck on its
boot splash instead of degrading cleanly.

## 4. Files changed
- `frontend/src/auth.jsx` — MISSING `refreshAuthStatus` added to the
  `AuthProvider` context value **and** to its `useMemo` dependency array;
  bootstrap wrapped in `try/catch` so a backend/auth failure degrades to the
  anonymous sign-in view instead of an uncaught rejection.

## 5. Fix implemented (minimal)
1. Added `refreshAuthStatus` to the context value object returned by
   `AuthProvider` and to the `useMemo` deps (`[status, user, auth, signIn,
   signUp, signOut, refreshAuthStatus]`).
2. Wrapped the auth-bootstrap async IIFE body in `try/catch` and added a
   guard so any unhandled bootstrap rejection transitions to `becomeAnon()`
   rather than leaving a blank/boot-locked shell.

No other files changed. No scientific logic, milestone modules, router
definitions, or protected-route gating were touched.

## 6. Build result
- `npm run build` in `frontend/` → **PASS**; `✓ 55 modules transformed,
  ✓ built in 4.56s` (Vite 7.3.6, CJS deps pre-bundled). No import/export
  errors, no duplicate-export or missing-export failures.
- `frontend/ssr-smoke.mjs` (real Vite SSR transform + React SSR of App + all
  pages and Shell/Sidebar/panels) → **PASS, OVERALL: PASS** (no SSR exception,
  all routes render ≥200 chars).

## 7. Backend test result
- Focused regression (not the full battery, per directive): `test_security.py`
  → **7 passed** (auth-enforced, token policies, refresh cookie, onboarding
  gate). Config + directories smoke + SSR + live health/overview endpoints all
  `200 OK`. Full backend running via `.venv` uvicorn, `demo_mode=false`
  (REAL PRADAN gated: no genuine pair registered ⇒ `REAL_DATA_UNVAILABLE`).

## 8. Browser smoke-test
- Real browser (headless Chrome + CDP) against the running dev server:
  after login/bootstrap the **authed CHANDRASUTRA shell renders** with
  backend online and Overview/metadata content; before login the sign-in
  page renders. Zero hard console errors on load.
- `npm run build` output (`dist/`) loads standalone.

## 9. Console status
- No runtime exceptions in dev console after fix (only expected
  React-DevTools / Vite-info messages).
- No unhandled rejection from refresh/bootstrap.

## 10. Network status
- Backend alive at `http://127.0.0.1:8000` (health `ok`, M10 milestone).
- Frontend proxy `/api` → `http://127.0.0.1:8000` (Vite `vite.config.js`);
  all Overview endpoints return 200 and the shell loads with live data.

## 11. Regression status
- Frontend: SSR smoke all pages PASS; Vite prod build PASS.
- Backend: focused security/auth regression PASS (7/7), live overview
  endpoints PASS (9/9 over the authed surface).
- Servers running (dev + backend), left detached/background.

REAL PRADAN DATA: BLOCKED (no genuine PRADAN/CH2 pair registered; only
operator-supplied real data triggers real-data path — per existing
`REAL_DATA_UNAVAILABLE` design).
GEMINI: DEV-READY (configured, gemini_configured=true), AI milestones gate
on real data as designed.

## 12. Secondary bugs found/fixed
- Hardened auth bootstrap against unhandled rejections (secondary safety,
  part of the same file; prevents a boot-lock/blank from a failed first
  refresh — API-failure-must-not-blank-the-UI requirement).
- Confirmed no full-screen overlay, no `display:none`/`opacity:0` on a page
  wrapper, no z-index/pointer-events mask hiding the app — the shell renders.

## 13. Remaining warnings
- Favicon missing → 404 in dev (cosmetic, pre-existing, not a cause).
- React DevTools standalone download notice (informational).
- `deep_matcher` state UNAVAILABLE without device/weights; `scientific_data`
  BLOCKED until real PRADAN pair registered — both by design.

## 14. Final status
FIXED — frontend blank-screen resolved; both servers running; backend
regression passes; SSR+browser smoke tests render the actual CHANDRASUTRA UI.
