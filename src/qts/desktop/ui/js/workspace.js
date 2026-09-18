/* Persist presentation only. Never store account details, modes, permission or acknowledgements. */
const KEY = "qts.workspace.v1";
const defaults = { density: "compact", width: "focused", navigation: "standard", rememberRoute: false, route: "#/overview" };
export function sanitizeWorkspace(raw = {}) {
  return {
    density: ["compact", "comfortable"].includes(raw?.density) ? raw.density : defaults.density,
    width: ["focused", "wide"].includes(raw?.width) ? raw.width : defaults.width,
    navigation: ["narrow", "standard", "wide"].includes(raw?.navigation) ? raw.navigation : defaults.navigation,
    rememberRoute: raw?.rememberRoute === true,
    route: typeof raw?.route === "string" && /^#\/[a-z]+(?:\/[a-z]+)?$/.test(raw.route) ? raw.route : defaults.route,
  };
}
export function readWorkspace() {
  try { return sanitizeWorkspace(JSON.parse(window.localStorage.getItem(KEY))); } catch { return { ...defaults }; }
}
export function applyWorkspace() {
  const p = readWorkspace();
  document.body.dataset.density = p.density;
  document.body.dataset.width = p.width;
  document.documentElement.style.setProperty("--sidebar-w", { narrow: "184px", standard: "216px", wide: "264px" }[p.navigation]);
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
