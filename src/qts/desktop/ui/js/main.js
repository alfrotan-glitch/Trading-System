/* ============================================================
   QTS MAIN — application shell bootstrap
   Header (global operating facts) · Sidebar (grouped IA) ·
   Router · Palette · Global polling (pauses when hidden).
   ============================================================ */
import { h, icon, clear } from "./dom.js";
import { api, store, syncHealth, syncNotifications, syncObservations, poll } from "./api.js";
import { registerRoutes, startRouter, navigate, dispatch } from "./router.js";
import { initPalette } from "./palette.js";
import { fmtAge } from "./format.js";
import { modeInfo, statusInfo } from "./status.js";
import { toast } from "./components.js";

import * as overview from "./views/overview.js";
import * as research from "./views/research.js";
import * as market from "./views/market.js";
import * as trading from "./views/trading.js";
import * as risk from "./views/risk.js";
import * as evidence from "./views/evidence.js";
import * as system from "./views/system.js";
import * as governance from "./views/governance.js";

/* ============================================================
   INFORMATION ARCHITECTURE — 8 primary areas, contextual depth.
   Every legacy page maps into exactly one home; nothing is lost.
   ============================================================ */
const IA = [
  { id: "overview", label: "Overview", icon: "grid", render: overview.renderOverview },
  {
    id: "research", label: "Research", icon: "flask", defaultChild: "campaigns",
    children: [
      { id: "campaigns", label: "Campaigns", render: research.renderCampaigns },
      { id: "hypotheses", label: "Hypotheses", render: research.renderHypotheses },
      { id: "experiments", label: "Experiment ledger", render: research.renderExperiments },
      { id: "strategies", label: "Strategy library", render: research.renderStrategies },
      { id: "validation", label: "Validation", render: research.renderValidation },
      { id: "memory", label: "Research memory", render: research.renderMemory },
      { id: "data", label: "Data observatory", render: research.renderData },
    ],
  },
  {
    id: "market", label: "Market", icon: "candle", defaultChild: "monitor",
    children: [
      { id: "monitor", label: "Market monitor", render: market.renderMonitor },
      { id: "observations", label: "Observations", render: market.renderObservations },
      { id: "quality", label: "Data quality", render: market.renderQuality },
      { id: "lineage", label: "Lineage", render: market.renderLineage },
    ],
  },
  {
    id: "trading", label: "Trading", icon: "layers", defaultChild: "demo",
    children: [
      { id: "demo", label: "Demo forward", render: trading.renderDemo },
      { id: "paper", label: "Paper / shadow", render: trading.renderPaper },
      { id: "execution", label: "Execution", render: trading.renderExecution },
      { id: "comparison", label: "Comparison", render: trading.renderComparison },
    ],
  },
  { id: "risk", label: "Risk", icon: "shield", render: risk.renderRisk },
  {
    id: "evidence", label: "Evidence", icon: "fileCheck", defaultChild: "explorer",
    children: [
      { id: "explorer", label: "Evidence explorer", render: evidence.renderExplorer },
      { id: "audit", label: "Audit trail", render: evidence.renderAudit },
    ],
  },
  {
    id: "system", label: "System", icon: "gear", defaultChild: "setup",
    children: [
      { id: "setup", label: "Setup", render: system.renderSetup },
      { id: "mt5", label: "MT5 connection", render: system.renderMT5 },
      { id: "diagnostics", label: "Diagnostics", render: system.renderDiagnostics },
    ],
  },
  { id: "governance", label: "Governance", path: "#/governance/live", icon: "lock", render: governance.renderGovernance, restricted: true },
];

/* ============================================================
   SHELL CONSTRUCTION
   ============================================================ */
function buildHeader() {
  const facts = h("div", { class: "header-facts", id: "header-facts" });
  const conn = h("span", { class: "conn-dot", title: "API connection" });
  const updated = h("span", { class: "meta", id: "header-updated" }, "connecting…");

  const header = h("header", { class: "header" },
    h("button", { class: "btn ghost nav-toggle", "aria-label": "Toggle navigation", onclick: () => document.getElementById("app").classList.toggle("nav-open") }, icon("menu", 18)),
    h("div", { class: "brand" },
      h("span", { class: "logo", "aria-hidden": "true" }, "QTS"),
      h("span", { class: "word" }, "QTS"),
      h("span", { class: "sub" }, "Trading System"),
    ),
    facts,
    h("div", { class: "header-actions" },
      conn, updated,
      h("button", { class: "btn ghost sm", onclick: () => document.querySelector(".palette-scrim") && document.body.classList.add("palette-open"), "aria-label": "Open command palette (Ctrl+K)", title: "Ctrl+K" }, icon("search", 15)),
    ),
  );
  return { header, facts, conn, updated };
}

function factChip({ icon: ic, label, value, cls = "", title, optional = false }) {
  return h("span", { class: `fact ${cls}${optional ? " optional" : ""}`, title: title ?? "" },
    ic ? icon(ic, 12) : null,
    label ? h("span", null, label, " ") : null,
    h("b", null, value),
  );
}

function renderFacts(factsEl) {
  const d = store.data;
  const health = d.health;
  clear(factsEl);
  if (!health) {
    factsEl.appendChild(factChip({ icon: "clock", label: "status", value: "connecting…" }));
    return;
  }
  const mode = modeInfo(health.effective_mode?.effective_mode);
  const broker = statusInfo(String(health.mt5).toLowerCase() === "connected" ? "connected" : "unavailable");
  const data = statusInfo(String(health.market_data).toLowerCase().includes("healthy") ? "healthy" : "degraded");
  factsEl.append(
    factChip({ icon: "layers", label: "mode", value: mode.mode, cls: mode.tone === "locked" ? "live-locked" : "mode", title: `${mode.blurb}${mode.canSubmit === true ? " — CAN submit broker orders" : mode.canSubmit === "gated" ? " — submission gated by demo authority" : " — cannot submit broker orders"}` }),
    factChip({ icon: "bank", value: broker.label, cls: broker.tone === "ok" ? "" : "optional", title: "MT5 terminal connection", optional: true }),
    factChip({ icon: "candle", value: health.strategy?.symbol ?? "XAUUSD", cls: "optional", title: "Instrument", optional: true }),
    factChip({ icon: "activity", value: data.label, cls: data.tone === "ok" ? "optional" : "", title: "Market data pipeline freshness" }),
    factChip({ icon: "shield", value: String(health.risk ?? "—").toUpperCase(), cls: "optional", title: "Risk subsystem state", optional: true }),
    factChip({ icon: "lock", value: "LIVE LOCKED", cls: "live-locked", title: "Live trading is structurally locked — see Governance" }),
  );
}

function buildSidebar() {
  const aside = h("nav", { class: "sidebar", "aria-label": "Primary" });
  for (const g of IA) {
    const grp = h("div", { class: "sidebar-group" });
    grp.appendChild(h("div", { class: "sidebar-group-label" }, icon(g.icon, 14), h("span", null, g.label)));
    const add = (label, href, restricted) => {
      grp.appendChild(h("button", {
        class: `nav-item${restricted ? " restricted" : ""}`,
        dataset: { href },
        onclick: () => navigate(href),
      }, icon(restricted ? "lock" : g.icon, 15), h("span", null, label)));
    };
    if (g.children) {
      for (const c of g.children) add(c.label, `#/${g.id}/${c.id}`, false);
    } else {
      add(g.label, g.path ?? `#/${g.id}`, g.restricted);
    }
    aside.appendChild(grp);
  }
  aside.appendChild(h("div", { class: "sidebar-footer" },
    h("span", null, [h("span", { class: "kbd" }, "Ctrl"), " + ", h("span", { class: "kbd" }, "K"), " command palette"]),
    h("span", null, "Backend is the only authority — the UI requests and displays, it never decides."),
  ));
  return aside;
}

function markActiveNav() {
  const hash = (location.hash || "#/overview").split("?")[0];
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.href === hash);
  });
}

/* ============================================================
   BOOTSTRAP
   ============================================================ */
function main() {
  const { header, facts, conn, updated } = buildHeader();
  const app = h("div", { id: "app" },
    header,
    buildSidebar(),
    h("div", { class: "scrim", onclick: () => app.classList.remove("nav-open") }),
    h("main", { id: "main", class: "main", tabindex: "-1" }),
  );
  document.body.appendChild(app);

  registerRoutes(IA);
  initPalette(IA, [
    { label: "Start observation (no orders)", group: "Actions", icon: "eye", run: async () => {
      try { await api.post("/api/observe/start"); toast("ok", "Observation started", "Zero orders will be submitted."); dispatch(); }
      catch (e) { toast("err", "Could not start observation", String(e.message).slice(0, 120)); }
    } },
    { label: "Stop observation", group: "Actions", icon: "stop", run: async () => {
      try { await api.post("/api/observe/stop"); toast("warn", "Observation stopped"); dispatch(); }
      catch (e) { toast("err", "Could not stop", String(e.message).slice(0, 120)); }
    } },
    { label: "Run readiness checks", group: "Actions", icon: "shield", run: () => { navigate("#/trading/demo"); } },
    { label: "Refresh system status", group: "Actions", icon: "refresh", run: async () => { await syncHealth(); toast("ok", "Status refreshed"); dispatch(); } },
  ]);

  window.addEventListener("hashchange", () => { markActiveNav(); });
  store.on("health", () => { renderFacts(facts); markConn(); });
  store.on("conn", () => { markConn(); });

  function markConn() {
    conn.className = `conn-dot${store.data.conn === "down" ? " down" : ""}`;
    updated.textContent = store.data.conn === "down"
      ? "API unreachable — values may be stale"
      : `synced ${fmtAge(store.data.lastSync)}`;
  }

  /* global polling — only while visible */
  poll(syncHealth, 15000);
  poll(syncNotifications, 20000);
  poll(syncObservations, 8000);
  const clock = setInterval(() => markConn(), 2000);
  if (typeof clock.unref === "function") clock.unref();

  syncHealth().then(syncNotifications);
  startRouter();
  markActiveNav();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
else main();
