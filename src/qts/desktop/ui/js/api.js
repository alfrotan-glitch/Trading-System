/* Transport + shared operational resources. No permission decisions or persisted authority. */
export class ApiError extends Error {
  constructor(path, status, body) {
    super(`API ${status} on ${path}: ${typeof body === "string" ? body.slice(0, 200) : JSON.stringify(body).slice(0, 200)}`);
    Object.assign(this, { path, status, body });
  }
}
const inflight = new Map();
export const measurements = [];
export function measure(kind, name, ms, outcome = "ok") {
  measurements.push({ kind, name, ms: Math.round(ms * 10) / 10, outcome, at: Date.now() });
  if (measurements.length > 100) measurements.shift(); // bounded; no response payloads
}
async function request(path, opts) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  timer.unref?.();
  const start = performance.now();
  let outcome = "ok";
  try {
    const resp = await fetch(path, { headers: { "Content-Type": "application/json" }, signal: ctrl.signal, ...opts });
    const text = await resp.text(); // body read is also protected by timeout
    let data;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!resp.ok) throw new ApiError(path, resp.status, data);
    return data;
  } catch (e) {
    outcome = "failed";
    if (e instanceof ApiError) throw e;
    throw new ApiError(path, 0, e.name === "AbortError" ? "request timed out after 20s" : `network error: ${e.message}`);
  } finally {
    clearTimeout(timer);
    measure("request", path, performance.now() - start, outcome);
  }
}
export const api = {
  get(path) {
    if (inflight.has(path)) { measure("coalesced", path, 0); return inflight.get(path); }
    const p = request(path).finally(() => inflight.delete(path));
    inflight.set(path, p);
    return p;
  },
  post: (path, body) => request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};
export const RESOURCES = {
  health: { path: "/api/health", interval: 15000, stale: 30000 },
  observe: { path: "/api/observe/status", interval: 8000, stale: 20000 },
  demoState: { path: "/api/demo/state", interval: 30000, stale: 45000 },
  live: { path: "/api/live/status", interval: 60000, stale: 90000 },
  notifications: { path: "/api/notifications", interval: 20000, stale: 45000 },
};
const listeners = new Map();
export const store = {
  data: { health: null, notifications: null, observe: null, live: null, demoState: null, resources: {}, lastSync: 0, conn: "init" },
  on(key, fn) {
    if (!listeners.has(key)) listeners.set(key, new Set());
    listeners.get(key).add(fn);
    if (this.data[key] !== null && this.data[key] !== undefined) fn(this.data[key]);
    return () => listeners.get(key)?.delete(fn);
  },
  set(key, value) {
    this.data[key] = value;
    // A notification, failure or connection update must not refresh health's timestamp.
    if (RESOURCES[key]) {
      this.data.resources[key] = { updatedAt: Date.now(), loading: false, error: null };
      if (key === "health") this.data.lastSync = this.data.resources[key].updatedAt;
      this.emit("resources");
    }
    this.emit(key);
  },
  emit(key) { listeners.get(key)?.forEach((fn) => { try { fn(this.data[key]); } catch (e) { console.error(e); } }); },
};
const syncing = new Map();
export function syncResource(key, { force = false } = {}) {
  if (syncing.has(key)) return syncing.get(key);
  const meta = store.data.resources[key];
  if (!force && meta?.updatedAt && !meta.error && Date.now() - meta.updatedAt < RESOURCES[key].interval) return Promise.resolve();
  store.data.resources[key] = { ...meta, loading: true };
  store.emit("resources");
  const p = (async () => {
    try {
      const value = await api.get(RESOURCES[key].path);
      if (key === "notifications" ? !Array.isArray(value) : !value || typeof value !== "object" || Array.isArray(value)) {
        throw new Error("Unexpected response shape; state unavailable");
      }
      store.set(key, value);
      if (key === "health") store.set("conn", "up");
    } catch (e) {
      store.data.resources[key] = { ...store.data.resources[key], loading: false, error: e.message };
      store.emit("resources");
      if (key === "health") store.set("conn", "down");
    } finally { syncing.delete(key); }
  })();
  syncing.set(key, p);
  return p;
}
export const syncHealth = () => syncResource("health");
export const syncObservations = () => syncResource("observe");
export const syncNotifications = () => syncResource("notifications");
export const syncOperations = (force = false) => Promise.all(Object.keys(RESOURCES).map((k) => syncResource(k, { force })));

/** One in-flight iteration per poller; stop during await cannot resurrect it. Resume on visibility. */
export function poll(fn, ms) {
  let alive = true, busy = false, timer;
  const loop = async () => {
    clearTimeout(timer);
    if (!alive || busy) return;
    busy = true;
    try { if (!document.hidden) await fn(); } catch { /* resource/view owns failure presentation */ }
    finally {
      busy = false;
      if (alive) { timer = setTimeout(loop, ms); timer.unref?.(); }
    }
  };
  const resume = () => { if (!document.hidden) loop(); };
  document.addEventListener("visibilitychange", resume);
  loop();
  return () => { alive = false; clearTimeout(timer); document.removeEventListener("visibilitychange", resume); };
}
