/* ============================================================
   QTS API — thin fetch layer with honest failure semantics
   The backend is the only authority; this layer never alters
   payloads, only normalizes transport errors.
   ============================================================ */

export class ApiError extends Error {
  constructor(path, status, body) {
    super(`API ${status} on ${path}: ${typeof body === "string" ? body.slice(0, 200) : JSON.stringify(body).slice(0, 200)}`);
    this.path = path;
    this.status = status;
    this.body = body;
  }
}

const REQUEST_TIMEOUT_MS = 20000; // a hung API call must surface as a failure, never freeze the view

async function request(path, opts) {
  const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS) : null;
  if (timer && typeof timer.unref === "function") timer.unref();
  let resp;
  try {
    resp = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      signal: ctrl?.signal,
      ...opts,
    });
  } catch (e) {
    const aborted = e && (e.name === "AbortError" || String(e.message).includes("abort"));
    const err = new ApiError(path, 0, aborted ? `request timed out after ${REQUEST_TIMEOUT_MS / 1000}s` : `network error: ${e.message}`);
    err.network = true;
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }
  let data = null;
  const text = await resp.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!resp.ok) throw new ApiError(path, resp.status, data);
  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};

/* ---------------- global store (tiny pub-sub) ---------------- */
const listeners = new Map();

export const store = {
  data: { health: null, notifications: [], observe: null, live: null, demoState: null, lastSync: 0, conn: "init" },
  on(key, fn) {
    if (!listeners.has(key)) listeners.set(key, new Set());
    listeners.get(key).add(fn);
    if (this.data[key] !== null && this.data[key] !== undefined) fn(this.data[key]);
    return () => listeners.get(key)?.delete(fn);
  },
  set(key, value) {
    this.data[key] = value;
    this.data.lastSync = Date.now();
    listeners.get(key)?.forEach((fn) => { try { fn(value); } catch (e) { console.error(e); } });
  },
};

/** Fetch + store health; sets conn health for the header. */
export async function syncHealth() {
  try {
    const health = await api.get("/api/health");
    store.set("health", health);
    store.set("conn", "up");
  } catch {
    store.set("conn", "down");
  }
}

export async function syncObservations() {
  try { store.set("observe", await api.get("/api/observe/status")); } catch { /* header degrades honestly */ }
}

export async function syncNotifications() {
  try { store.set("notifications", await api.get("/api/notifications")); } catch { /* keep last known */ }
}

/** Poll fn every ms while the document is visible; returns stop(). */
export function poll(fn, ms) {
  let alive = true;
  let timer = null;
  const loop = async () => {
    if (!alive) return;
    if (!document.hidden) { try { await fn(); } catch { /* handled by fn */ } }
    timer = setTimeout(loop, ms);
    if (typeof timer.unref === "function") timer.unref(); // Node/test hygiene; no-op in browsers
  };
  loop();
  return () => { alive = false; clearTimeout(timer); };
}
