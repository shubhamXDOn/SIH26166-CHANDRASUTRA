/* API root resolution.
   - Default: same-origin "/api" (dev Vite proxy, docker-compose nginx gateway).
   - Deployed split hosting (Netlify UI + Render API): set VITE_API_BASE_URL to
     the backend origin at build time, e.g. https://<service>.onrender.com
     Both "https://host" and "https://host/api" are accepted.
   `import.meta.env` is read as a whole object (not via optional chaining on the
   member) so Vite statically substitutes the VITE_* values into the bundle. */
const viteEnv = import.meta.env ?? {};

function resolveApiBase() {
  const configured = (viteEnv.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");
  if (!configured) return "/api";
  return /\/api$/.test(configured) ? configured : `${configured}/api`;
}

const API_BASE = resolveApiBase();

/* Cross-origin deployments must send/store the HttpOnly refresh cookie, which
   requires credentials on every call (the backend answers with
   Access-Control-Allow-Credentials). Same-origin requests are unaffected. */
const API_CREDENTIALS = API_BASE.startsWith("/") ? "same-origin" : "include";

/* M11 resilience: a stable per-session request id correlates every call with
   backend envelopes/logs, and a fetch timeout guarantees the UI never hangs
   on a stalled backend connection. */
const DEFAULT_TIMEOUT_MS = 60000;
const sessionRequestId =
  (typeof crypto !== "undefined" && crypto.randomUUID && crypto.randomUUID()) ||
  `cs-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

let accessToken = null;
let refreshPromise = null;
const authLostListeners = new Set();

/* ------------------------------------------------------------ token store */

export function setAccessToken(token) {
  accessToken = token || null;
}

export function getAccessToken() {
  return accessToken;
}

/* Silent expiry handler: attached by the auth provider so that the whole app
   can flip back to the sign-in screen when a refresh attempt fails. */
export function onAuthLost(listener) {
  authLostListeners.add(listener);
  return () => authLostListeners.delete(listener);
}

function emitAuthLost() {
  for (const fn of authLostListeners) fn();
}

/* ------------------------------------------------------------- transport */

function withTimeout(init, timeoutMs) {
  if (!timeoutMs || typeof AbortController === "undefined") return init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return { ...init, signal: controller.signal, _done: () => clearTimeout(timer) };
}

async function handle(res) {
  let body = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON upstream — fall through to generic error */
  }
  if (!res.ok) {
    const err = new Error(
      body?.error?.user_message || body?.error?.message || `Request failed (${res.status})`
    );
    err.code = body?.error?.code || "HTTP_ERROR";
    err.status = res.status;
    err.requestId = body?.error?.request_id || res.headers?.get("x-request-id") || "";
    err.details = body?.error?.details || {};
    throw err;
  }
  return body;
}

async function refreshSession() {
  const res = await fetch(API_BASE + "/auth/refresh", {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: API_CREDENTIALS,
  });
  if (!res.ok) {
    setAccessToken(null);
    return null;
  }
  const body = await handle(res);
  if (body?.access_token) {
    setAccessToken(body.access_token);
    return body.access_token;
  }
  setAccessToken(null);
  return null;
}

async function rawFetch(path, init, timeoutMs) {
  const prepared = withTimeout(init, timeoutMs ?? DEFAULT_TIMEOUT_MS);
  try {
    return await fetch(API_BASE + path, prepared);
  } catch (err) {
    if (err?.name === "AbortError") {
      const aborted = new Error("The request timed out; the backend did not respond in time.");
      aborted.code = "REQUEST_TIMEOUT";
      aborted.status = 0;
      aborted.retryable = true;
      throw aborted;
    }
    throw err;
  } finally {
    if (prepared?._done) prepared._done();
  }
}

function authFetch(path, { method = "GET", payload, auth = true, timeoutMs } = {}) {
  const attempt = () => {
    const headers = {
      Accept: "application/json",
      "X-Request-ID": sessionRequestId,
    };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const init = { method, headers, credentials: API_CREDENTIALS };
    if (payload !== undefined) init.body = JSON.stringify(payload);
    return rawFetch(path, init, timeoutMs);
  };

  return (async () => {
    let res = await attempt();
    if (auth && res.status === 401 && accessToken) {
      // single refresh + single replay — never loops
      refreshPromise = refreshPromise || refreshSession().finally(() => {
        refreshPromise = null;
      });
      await refreshPromise;
      if (accessToken) {
        res = await attempt();
      } else {
        emitAuthLost();
      }
    }
    return handle(res);
  })();
}

export async function apiGet(path) {
  return authFetch(path, { method: "GET" });
}

export async function apiPost(path, payload) {
  return authFetch(path, { method: "POST", payload });
}

export async function apiPatch(path, payload) {
  return authFetch(path, { method: "PATCH", payload });
}

export async function apiDelete(path) {
  return authFetch(path, { method: "DELETE" });
}

export { API_BASE, sessionRequestId, refreshSession };