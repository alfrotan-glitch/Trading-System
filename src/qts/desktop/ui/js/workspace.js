/* Workspace — presentation only. Never stores permission, mode, risk ack.
   Persistent layout: density, width, navigation, last route (never actions).
   Syncs across tabs via storage event. Multi-monitor: new window opens current context. */

const KEY = "qts.workspace.v1";
const defaults = { density: "compact", width: "focused", navigation: "standard", rememberRoute: false, route: "#/overview" };

export function sanitizeWorkspace(raw = {}) {
  const d = raw?.density, w = raw?.width, n = raw?.navigation, r = raw?.route;
  return {
    density: ["compact", "comfortable"].includes(d) ? d : defaults.density,
    width: ["focused", "wide"].includes(w) ? w : defaults.width,
    navigation: ["narrow", "standard", "wide"].includes(n) ? n : defaults.navigation,
    rememberRoute: raw?.rememberRoute === true,
    route: typeof r === "string" && /^#\/[a-z]+(?:\/[a-z]+)?$/.test(r) ? r : defaults.route,
  };
}

export function readWorkspace() {
  try { return sanitizeWorkspace(JSON.parse(window.localStorage.getItem(KEY))); }
  catch { return { ...defaults }; }
}

export function applyWorkspace() {
  const p = readWorkspace();
  document.body.dataset.density = p.density;
  document.body.dataset.width = p.width;
  document.documentElement.style.setProperty("--sidebar-w", { narrow: "184px", standard: "216px", wide: "264px" }[p.navigation]);
  document.documentElement.style.setProperty("--content-max", p.width === "wide" ? "1600px" : "1440px");
}

export function saveWorkspace(changes) {
  const p = sanitizeWorkspace({ ...readWorkspace(), ...changes });
  try { window.localStorage.setItem(KEY, JSON.stringify(p)); } catch { return false; }
  applyWorkspace();
  return true;
}

export function initWorkspace() {
  applyWorkspace();
  window.addEventListener("storage", (e) => { if (e.key === KEY) applyWorkspace(); });
}
