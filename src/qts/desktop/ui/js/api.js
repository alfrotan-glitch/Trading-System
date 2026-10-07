/* Transport + shared operational resources. No permission decisions or persisted authority.
   Performance is UX: every request, coalesce, recovery, render, route is measured.
   Bounded to 100 entries, no payloads stored. */

export class ApiError extends Error {
  constructor(path, status, body) {
    super(`API ${status} on ${path}: ${typeof body === "string" ? body.slice(0, 200) : JSON.stringify(body).slice(0, 200)}`);
    Object.assign(this, { path, status, body });
  }
}

const inflight = new Map();
export const measurements = [];
export function measure(kind, name, ms, outcome = "ok") {
  const entry = { kind, name, ms: Math.round(ms * 10) / 10, outcome, at: Date.now() };
  if (typeof performance !== "undefined" && performance.memory) {
    entry.heapUsed = Math.round(performance.memory.usedJSHeapSize / 1024);
  }
  measurements.push(entry);
  if (measurements.length > 100) measurements.shift();
}

async function request(path, opts) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  timer.unref?.();
  const start = performance.now();
  let outcome = "ok";
  try {
    const headers = {
      "Content-Type": "application/json",
      "X-QTS-Operator": "local-ui",
      ...(opts?.headers || {}),
    };
    const resp = await fetch(path, { ...opts, headers, signal: ctrl.signal });
    const text = await resp.text();
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
    if (inflight.has(path)) { measure("dup-coalesced", path, 0, "coalesced"); return inflight.get(path); }
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
    const prev = RESOURCES[key] ? this.data.resources[key] : null;
    const hadError = Boolean(prev?.error);
    this.data[key] = value;
    if (RESOURCES[key]) {
      this.data.resources[key] = { updatedAt: Date.now(), loading: false, error: null };
      if (hadError) measure("recovery", RESOURCES[key].path, 0, "recovered");
      if (key === "health") this.data.lastSync = this.data.resources[key].updatedAt;
      this.emit("resources");
    }
    this.emit(key);
  },
  emit(key) { listeners.get(key)?.forEach((fn) => { try { fn(this.data[key]); } catch (e) { console.error(e); } }); },
};

const syncing = new Map();
export function syncResource(key, { force = false } = {}) {
  if (syncing.has(key)) { measure("dup-sync", key, 0, "coalesced"); return syncing.get(key); }
  const meta = store.data.resources[key];
  if (!force && meta?.updatedAt && !meta.error && Date.now() - meta.updatedAt < RESOURCES[key].interval) return Promise.resolve();
  store.data.resources[key] = { ...meta, loading: true };
  store.emit("resources");
  const start = performance.now();
  const p = (async () => {
    try {
      const value = await api.get(RESOURCES[key].path);
      if (key === "notifications" ? !Array.isArray(value) : !value || typeof value !== "object" || Array.isArray(value)) {
        throw new Error("Unexpected response shape; state unavailable");
      }
      store.set(key, value);
      if (key === "health") store.set("conn", "up");
      measure(force ? "refresh-forced" : "refresh", key, performance.now() - start, "ok");
    } catch (e) {
      store.data.resources[key] = { ...store.data.resources[key], loading: false, error: e.message };
      store.emit("resources");
      if (key === "health") store.set("conn", "down");
      measure("refresh", key, performance.now() - start, "failed");
    } finally { syncing.delete(key); }
  })();
  syncing.set(key, p);
  return p;
}

export const syncHealth = () => syncResource("health");
export const syncObservations = () => syncResource("observe");
export const syncNotifications = () => syncResource("notifications");
export const syncOperations = (force = false) => {
  const start = performance.now();
  return Promise.all(Object.keys(RESOURCES).map((k) => syncResource(k, { force }))).then(() => {
    measure(force ? "refresh-all-forced" : "refresh-all", "operations", performance.now() - start, "ok");
  });
};

/** Poller — one in-flight iteration, pause when hidden, resume on visibility. */
export function poll(fn, ms) {
  let alive = true, busy = false, timer;
  let skipped = 0;
  const loop = async () => {
    clearTimeout(timer);
    if (!alive || busy) return;
    if (document.hidden) { skipped++; timer = setTimeout(loop, ms); timer.unref?.(); return; }
    if (skipped) { measure("poll-skipped", fn.name || "poll", 0, `${skipped} skipped while hidden`); skipped = 0; }
    busy = true;
    const s = performance.now();
    try { await fn(); measure("poll", fn.name || "poll", performance.now() - s, "ok"); }
    catch { measure("poll", fn.name || "poll", performance.now() - s, "failed"); }
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

/* initial load measurement */
if (typeof performance !== "undefined" && performance.timing) {
  const t = performance.timing;
  if (t.loadEventEnd && t.navigationStart) {
    measure("load", "page", t.loadEventEnd - t.navigationStart, "ok");
  }
}
