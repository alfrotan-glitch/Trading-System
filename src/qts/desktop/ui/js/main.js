/* QTS MAIN — product shell for a normal (non-technical) user.
   Primary navigation: Home · Market · Trading · Reports.
   Everything engineering lives behind one quiet "Advanced" area.
   The header says only what matters: the demo account and overall status.
   The backend remains the only authority; this shell renders and requests. */

import { h, icon, clear } from "./dom.js";
import { api, store, RESOURCES, syncResource, syncOperations, poll, measure } from "./api.js";
import { operationalState, freshness } from "./operations.js";
import { initWorkspace, readWorkspace, saveWorkspace } from "./workspace.js";
import { registerRoutes, registerRedirects, startRouter, navigate, HOME } from "./router.js";
import { initPalette } from "./palette.js";
import { fmtAge } from "./format.js";
import { attentionRank } from "./status.js";
import { toast, badge, drawer, confirmModal } from "./components.js";
import { getContext, onContext } from "./context.js";

import * as home from "./views/overview.js";
import * as market from "./views/market.js";
import * as trading from "./views/trading.js";
import * as reports from "./views/reports.js";
import * as research from "./views/research.js";
import * as risk from "./views/risk.js";
import * as evidence from "./views/evidence.js";
import * as system from "./views/system.js";
import * as governance from "./views/governance.js";

/* ---------------- information architecture ----------------
   Four primary pages for a normal user. Every engineering
   surface keeps working — under Advanced, out of the way. */
const IA = [
  { id: "home", label: "Home", section: "Product", icon: "home", render: home.renderHome },
  { id: "market", label: "Market", section: "Product", icon: "activity", render: market.renderMarket },
  { id: "trading", label: "Trading", section: "Product", icon: "layers", render: trading.renderDemo },
  { id: "reports", label: "Reports", section: "Product", icon: "fileCheck", render: reports.renderReports },
  {
    id: "advanced", label: "Advanced", section: "Advanced", icon: "sliders", quiet: true, defaultChild: "research-campaigns",
    children: [
      { id: "research-campaigns", label: "Research campaigns", sub: "Research", render: research.renderCampaigns },
      { id: "research-hypotheses", label: "Hypotheses", sub: "Research", render: research.renderHypotheses },
      { id: "research-experiments", label: "Experiment ledger", sub: "Research", render: research.renderExperiments },
      { id: "research-strategies", label: "Strategy library", sub: "Research", render: research.renderStrategies },
      { id: "research-validation", label: "Validation", sub: "Research", render: research.renderValidation },
      { id: "research-memory", label: "Research memory", sub: "Research", render: research.renderMemory },
      { id: "research-data", label: "Data observatory", sub: "Research", render: research.renderData },
      { id: "data-observations", label: "Recorded observations", sub: "Data", render: market.renderObservations },
      { id: "data-quality", label: "Data quality", sub: "Data", render: market.renderQuality },
      { id: "data-lineage", label: "Data lineage", sub: "Data", render: market.renderLineage },
      { id: "trading-practice", label: "Practice (paper)", sub: "Trading tools", render: trading.renderPaper },
      { id: "trading-history", label: "Order history", sub: "Trading tools", render: trading.renderExecution },
      { id: "trading-comparison", label: "Comparison", sub: "Trading tools", render: trading.renderComparison },
      { id: "risk", label: "Risk controls", sub: "Trading tools", render: risk.renderRisk },
      { id: "evidence", label: "Evidence explorer", sub: "Evidence & audit", render: evidence.renderExplorer },
      { id: "audit", label: "Audit trail", sub: "Evidence & audit", render: evidence.renderAudit },
      { id: "governance", label: "Live trading rules", sub: "Governance", render: governance.renderGovernance },
      { id: "system-setup", label: "Setup", sub: "System", render: system.renderSetup },
      { id: "system-mt5", label: "Terminal connection", sub: "System", render: system.renderMT5 },
      { id: "system-diagnostics", label: "Diagnostics", sub: "System", render: system.renderDiagnostics },
    ],
  },
];

/* Deep links and bookmarks from the previous IA keep working. */
const REDIRECTS = {
  "#/overview": "#/home",
  "#/market/monitor": "#/market",
  "#/market/observations": "#/advanced/data-observations",
  "#/market/quality": "#/advanced/data-quality",
  "#/market/lineage": "#/advanced/data-lineage",
  "#/opportunities": "#/reports",
  "#/trading/demo": "#/trading",
  "#/trading/paper": "#/advanced/trading-practice",
  "#/trading/execution": "#/advanced/trading-history",
  "#/trading/comparison": "#/advanced/trading-comparison",
  "#/risk": "#/advanced/risk",
  "#/evidence/explorer": "#/advanced/evidence",
  "#/evidence/audit": "#/advanced/audit",
  "#/research/campaigns": "#/advanced/research-campaigns",
  "#/research/hypotheses": "#/advanced/research-hypotheses",
  "#/research/experiments": "#/advanced/research-experiments",
  "#/research/strategies": "#/advanced/research-strategies",
  "#/research/validation": "#/advanced/research-validation",
  "#/research/memory": "#/advanced/research-memory",
  "#/research/data": "#/advanced/research-data",
  "#/system/setup": "#/advanced/system-setup",
  "#/system/mt5": "#/advanced/system-mt5",
  "#/system/diagnostics": "#/advanced/system-diagnostics",
  "#/governance/live": "#/advanced/governance",
};

const LEVEL_TONE = {
  critical: { tone: "err", label: "CRITICAL", mark: "■" },
  error: { tone: "err", label: "ERROR", mark: "■" },
  warning: { tone: "warn", label: "WARNING", mark: "▲" },
  info: { tone: "info", label: "INFO", mark: "●" },
};

function buildNotifBell() {
  const wrapper = h("span", { class: "notification-anchor" });
  const count = h("span", { class: "notif-count", hidden: true, "aria-hidden": "true" });
  const btn = h("button", { class: "btn ghost sm notif-btn", "aria-label": "Notifications", title: "Notifications", "aria-expanded": "false" }, icon("alert", 15), count);
  let pop = null;
  const onDoc = (e) => { if (pop && !pop.contains(e.target) && !btn.contains(e.target)) close(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() {
    if (!pop) return;
    pop.remove(); pop = null;
    btn.setAttribute("aria-expanded", "false"); btn.focus();
    document.removeEventListener("click", onDoc, true);
    document.removeEventListener("keydown", onKey);
  }
  function renderList(listEl) {
    clear(listEl);
    const notes = attentionRank(store.data.notifications || []);
    if (!notes.length) {
      listEl.appendChild(h("div", { class: "notif-empty" }, "Nothing needs your attention."));
      return;
    }
    for (const n of notes) {
      const info = LEVEL_TONE[String(n.level).toLowerCase()] ?? { tone: "neutral", label: String(n.level || "NOTICE").toUpperCase(), mark: "○" };
      listEl.appendChild(h("div", {
        class: "notif-item", role: "button", tabindex: "0",
        onclick: () => { close(); navigate(HOME); },
        onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); close(); navigate(HOME); } },
      },
        badge(info),
        h("div", { class: "n-body" },
          h("div", { class: "n-title" }, n.title ?? "—"),
          n.detail ? h("div", { class: "n-detail" }, n.detail) : null),
      ));
    }
  }
  btn.addEventListener("click", () => {
    if (pop) { close(); return; }
    pop = h("div", { class: "notif-pop", role: "region", "aria-label": "Notifications" },
      h("div", { class: "notif-head" },
        "Attention",
        h("button", { class: "btn ghost sm", "aria-label": "Close notifications", onclick: close }, icon("x", 13))),
      h("div", { class: "notif-list" }));
    renderList(pop.querySelector(".notif-list"));
    wrapper.appendChild(pop);
    btn.setAttribute("aria-expanded", "true");
    pop.querySelector("button").focus();
    document.addEventListener("click", onDoc, true);
    document.addEventListener("keydown", onKey);
  });
  store.on("notifications", (notes) => {
    const list = notes || [];
    count.hidden = list.length === 0;
    count.textContent = list.length > 99 ? "99+" : String(list.length);
    count.classList.toggle("critical", list.some((x) => ["critical", "error"].includes(String(x.level).toLowerCase())));
    if (pop) renderList(pop.querySelector(".notif-list"));
  });
  wrapper.appendChild(btn);
  return wrapper;
}

async function stopTrading() {
  const ok = await confirmModal({
    title: "Stop trading",
    danger: true,
    body: "This stops demo orders until you review and resume. It does not close an open position. Cancel if you only wanted to look.",
    acks: ["I want orders stopped until I review and resume."],
    confirmLabel: "Stop orders",
  });
  if (!ok) return;
  try {
    const out = await api.post("/api/demo/kill", { reason: "operator stop from the header" });
    if (!out || out.killed !== true) {
      toast("err", "Stop was not confirmed", "QTS could not confirm that orders are stopped. Check Trading before assuming anything.");
      return;
    }
    toast("warn", "Orders stopped", "Trading is temporarily stopped. You can review and resume from Trading. Live trading was already locked.");
    syncOperations(true);
  } catch (e) {
    toast("err", "Stop was not confirmed", e.message || "The request failed. Do not assume orders are stopped.");
  }
}

/* ---------------- header: only what matters ---------------- */
function buildHeader() {
  const account = h("span", { class: "header-account", id: "header-account", role: "status" },
    h("span", { class: "account-dot", "aria-hidden": "true" }),
    h("span", { class: "account-text" }, "Demo account: checking…"));
  const status = h("span", { class: "header-status", id: "header-status" }, "");
  const conn = h("span", { class: "conn-dot", title: "QTS service connection", role: "status", "aria-label": "QTS service connecting" });
  const updated = h("span", { class: "meta header-updated", id: "header-updated", "aria-live": "polite" }, "connecting…");

  const header = h("header", { class: "header" },
    h("button", { class: "btn ghost nav-toggle", "aria-label": "Toggle navigation", "aria-expanded": "false", onclick: (e) => { const open = document.getElementById("app").classList.toggle("nav-open"); e.currentTarget.setAttribute("aria-expanded", String(open)); } }, icon("menu", 18)),
    h("a", { class: "brand", href: HOME, "aria-label": "QTS home" },
      h("span", { class: "logo", "aria-hidden": "true" }, "Q"),
      h("span", { class: "word" }, "QTS"),
      h("span", { class: "sub" }, "Gold · Demo")),
    h("div", { class: "header-center" }, account, status),
    h("div", { class: "header-actions" },
      conn, updated,
      h("span", { class: "header-lock", title: "Live trading cannot be opened from QTS. Real money is never at risk." }, icon("lock", 12), "Demo only · Live locked"),
      h("button", { class: "btn danger sm", onclick: stopTrading, "aria-label": "Stop trading" }, "Stop trading"),
      buildNotifBell()),
  );
  return { header, account, status, conn, updated };
}

function renderHeaderStatus({ account, status }) {
  const s = operationalState(store.data);
  const connected = s.sources.health.current && String(s.health?.mt5).toLowerCase() === "connected";
  const dot = account.querySelector(".account-dot");
  const text = account.querySelector(".account-text");
  account.classList.toggle("connected", connected);
  dot.className = `account-dot ${connected ? "ok" : "off"}`;
  text.textContent = connected ? "Demo account: Connected" : "Demo account: Not connected";

  let label = "";
  if (!s.sources.health.current) label = "Status unavailable";
  else if (s.killActive) label = "Trading is temporarily stopped";
  else if (s.permission === "PERMITTED · DEMO ONLY") label = "Ready for demo trading";
  else if (connected) label = "Connected — setup continues on Trading";
  else label = "Getting started";
  status.textContent = label;
  status.dataset.tone = s.killActive ? "err" : s.permission === "PERMITTED · DEMO ONLY" ? "ok" : "neutral";
}

/* ---------------- sidebar: few choices, quiet Advanced ---------------- */
function buildSidebar() {
  const aside = h("nav", { class: "sidebar", "aria-label": "Primary" });

  const primary = h("div", { class: "nav-primary" });
  for (const g of IA.filter((x) => !x.quiet)) {
    primary.appendChild(h("button", {
      class: "nav-item primary",
      dataset: { href: `#/${g.id}` },
      onclick: () => navigate(`#/${g.id}`),
    }, icon(g.icon, 16), h("span", null, g.label)));
  }
  aside.appendChild(primary);

  const adv = IA.find((x) => x.quiet);
  const advBody = h("div", { class: "adv-body" });
  let lastSub = "";
  for (const c of adv.children) {
    if (c.sub !== lastSub) {
      advBody.appendChild(h("div", { class: "adv-sub" }, c.sub));
      lastSub = c.sub;
    }
    advBody.appendChild(h("button", {
      class: "nav-item adv",
      dataset: { href: `#/advanced/${c.id}` },
      onclick: () => navigate(`#/advanced/${c.id}`),
    }, h("span", null, c.label)));
  }
  aside.appendChild(h("details", { class: "nav-advanced" },
    h("summary", null, icon("sliders", 14), h("span", null, "Advanced"), h("span", { class: "adv-hint" }, "technical")),
    advBody));

  aside.appendChild(h("div", { class: "sidebar-footer" },
    h("span", null, icon("lock", 12), " Demo only — live trading stays locked."),
    h("span", { class: "text-faint" }, "QTS decides nothing on its own. Every order still passes the safety checks.")));
  return aside;
}

function markActiveNav() {
  const hash = (location.hash || HOME).split("?")[0];
  document.querySelectorAll(".nav-item").forEach((el) => {
    const active = el.dataset.href === hash || (hash.startsWith("#/advanced/") && el.dataset.href === hash);
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  // Opening Advanced automatically when one of its pages is shown.
  const advDetails = document.querySelector(".nav-advanced");
  if (advDetails) advDetails.open = advDetails.open || hash.startsWith("#/advanced/");
}

/* ---------------- workspace drawer (kept for power users via palette) ---------------- */
function openWorkspace() {
  const p = readWorkspace();
  const ctx = getContext();
  const form = h("div", { class: "stack" },
    h("p", { class: "small text-dim" }, `Presentation preferences only. Modes, permissions and risk acknowledgements are never stored here. Context ${ctx.symbol} · ${ctx.timeframe} is presentation only.`));
  for (const [key, label, options, hint] of [
    ["density", "Density", ["compact", "comfortable"], "Compact rows vs more whitespace."],
    ["width", "Workspace width", ["focused", "wide"], "Focused 1440px, wide 1600px."],
    ["navigation", "Navigation width", ["narrow", "standard", "wide"], "Sidebar width."],
  ]) {
    const select = h("select", { class: "input", "aria-label": label }, options.map((v) => h("option", { value: v }, v)));
    select.value = p[key];
    select.addEventListener("change", () => { if (!saveWorkspace({ [key]: select.value })) toast("warn", "Preferences could not be saved", "Browser storage unavailable."); });
    form.appendChild(h("div", { class: "field" }, h("label", null, label), select, h("div", { class: "hint" }, hint)));
  }
  const remember = h("input", { type: "checkbox", checked: p.rememberRoute });
  remember.addEventListener("change", () => { if (!saveWorkspace({ rememberRoute: remember.checked, route: location.hash })) toast("warn", "Preferences could not be saved"); });
  form.appendChild(h("label", { class: "field-inline", style: { marginTop: "8px" } }, remember, h("span", { class: "small" }, "Restore the last page on launch. This never repeats an action.")));
  form.appendChild(h("div", { class: "small text-dim", style: { marginTop: "12px" } }, "A missing number stays missing — it is never shown as zero. Watching the market never sends an order. Live trading stays locked."));
  drawer("Display preferences", form);
}

function main() {
  const loadStart = performance.now();
  initWorkspace();
  const { header, account, status, conn, updated } = buildHeader();
  const app = h("div", { id: "app" },
    header,
    buildSidebar(),
    h("div", { class: "scrim", onclick: () => app.classList.remove("nav-open") }),
    h("main", { id: "main", class: "main", tabindex: "-1" }),
  );
  document.body.appendChild(app);

  registerRoutes(IA);
  registerRedirects(REDIRECTS);
  initPalette(IA, [
    { label: "Check the demo connection", group: "Actions", icon: "activity", run: () => navigate("#/trading") },
    { label: "Start a demo trade", group: "Actions", icon: "zap", run: () => navigate("#/trading") },
    { label: "See reports", group: "Actions", icon: "fileCheck", run: () => navigate("#/reports") },
    { label: "Display preferences", group: "Workspace", icon: "sliders", run: openWorkspace },
    { label: "Refresh status", group: "Actions", icon: "refresh", run: () => syncOperations(true) },
  ]);

  window.addEventListener("hashchange", () => { markActiveNav(); });
  const update = () => {
    renderHeaderStatus({ account, status });
    const f = freshness(store.data.resources.health, "health");
    const stateClass = f.current ? "" : f.label.includes("STALE") ? " stale" : " down";
    conn.className = `conn-dot${stateClass}`;
    conn.title = `QTS service: ${f.label}`;
    conn.setAttribute("aria-label", `QTS service ${f.label.toLowerCase()}`);
    updated.textContent = f.current ? (store.data.resources.health?.updatedAt ? `Updated ${fmtAge(store.data.resources.health.updatedAt)}` : "Up to date") : f.label;
  };
  store.on("resources", update);
  onContext(update);
  for (const key of Object.keys(RESOURCES)) poll(() => syncResource(key), RESOURCES[key].interval);
  const clock = setInterval(update, 2000); clock.unref?.();

  startRouter();
  markActiveNav();
  measure("load", "shell", performance.now() - loadStart, "ok");
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
else main();
