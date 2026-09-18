import { measure } from "./api.js";
import { readWorkspace, saveWorkspace } from "./workspace.js";
/* ============================================================
   QTS ROUTER — hash router over the information architecture.
   Routes are declared in the IA tree (main.js); this module
   resolves, dispatches, and keeps history/scroll sane.
   ============================================================ */

let routes = new Map(); // "#/market/observations" → {render, group, label}
let current = null;
let currentHost = null;
const cleanups = new WeakMap();
export function onDispose(host, fn) {
  if (!host.isConnected) { fn(); return; }
  if (!cleanups.has(host)) cleanups.set(host, []);
  cleanups.get(host).push(fn);
}
function dispose(host) { (cleanups.get(host) || []).forEach((fn) => fn()); cleanups.delete(host); }


export function registerRoutes(IA) {
  routes = new Map();
  for (const g of IA) {
    if (g.children) {
      for (const c of g.children) {
        routes.set(`#/${g.id}/${c.id}`, { render: c.render, group: g, page: c });
      }
      if (g.defaultChild) {
        routes.set(`#/${g.id}`, routes.get(`#/${g.id}/${g.defaultChild}`) ?? null);
      }
    } else {
      const path = g.path ?? `#/${g.id}`;
      routes.set(path, { render: g.render, group: g, page: { label: g.label, render: g.render } });
      if (g.path) routes.set(`#/${g.id}`, routes.get(path)); // short alias
    }
  }
}

export function resolve(hash) {
  const clean = (hash || location.hash || "#/overview").split("?")[0];
  return routes.get(clean) || routes.get("#/overview") || null;
}

export function currentRoute() { return current; }

export async function navigate(hash) {
  if (location.hash === hash) dispatch();
  else location.hash = hash;
}

export async function dispatch() {
  const route = resolve(location.hash);
  if (!route) return;
  current = route;
  const main = document.getElementById("main");
  if (!main) return;
  if (currentHost) dispose(currentHost);
  const start = performance.now();
  main.scrollTop = 0; // new page — scroll to top
  document.getElementById("app")?.classList.remove("nav-open");
  if (route.page?.label) document.title = `${route.page.label} · QTS Trading System`;
  // Render into a per-dispatch host: if a newer navigation supersedes this
  // one, the old view's late async appends land in a detached node — never
  // interleaved with the new page (prevents duplicated/raced content).
  const host = document.createElement("div");
  host.className = "view-enter"; // per-route transition (respects reduced motion)
  currentHost = host;
  main.replaceChildren(host);
  if (readWorkspace().rememberRoute && routes.has(location.hash)) saveWorkspace({ route: location.hash });
  main.focus({ preventScroll: true }); // SPA a11y: announce the new page to AT
  try {
    await route.render(host);
    if (currentHost === host) measure("route", route.page.label, performance.now() - start);
  } catch (e) {
    console.error("view render failed", e);
    if (currentHost !== host) return;
    const { errorBox } = await import("./components.js");
    if (currentHost !== host) return;
    host.replaceChildren(errorBox({
      what: "this view failed to render",
      known: "The backend may still be healthy — other views can work.",
      next: "Refresh this view or pick another section from the sidebar.",
      raw: e.stack || e.message,
    }));
  }
}

export function startRouter() {
  window.addEventListener("hashchange", dispatch);
  // Normalize the initial hash WITHOUT firing a second hashchange dispatch —
  // history.replaceState is silent, so exactly one initial render happens.
  if (!location.hash || location.hash === "#" || location.hash === "#/") {
    if (window.history?.replaceState) {
      const p = readWorkspace();
      window.history.replaceState(null, "", p.rememberRoute && routes.has(p.route) ? p.route : "#/overview"); // silent — one initial dispatch below
    } else {
      location.hash = "#/overview"; // hashchange will dispatch; skip the manual call
      return;
    }
  }
  dispatch();
}
