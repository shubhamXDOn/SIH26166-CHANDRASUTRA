const API_BASE = "/api";

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
    throw err;
  }
  return body;
}

async function refreshSession() {
  const res = await fetch(API_BASE + "/auth/refresh", {
    method: "POST",
    headers: { Accept: "application/json" },
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

async function authFetch(path, { method = "GET", payload, auth = true } = {}) {
  const attempt = () => {
    const headers = { Accept: "application/json" };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const init = { method, headers };
    if (payload !== undefined) init.body = JSON.stringify(payload);
    return fetch(API_BASE + path, init);
  };

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

export { API_BASE, refreshSession };