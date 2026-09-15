const API_BASE = "/api";

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

export async function apiGet(path) {
  const res = await fetch(API_BASE + path, { headers: { Accept: "application/json" } });
  return handle(res);
}

export async function apiPost(path, payload) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  return handle(res);
}

export { API_BASE };