/* QTS MAIN — professional operator shell
   Header facts (instant awareness) · Sidebar (grouped IA, searchable, keyboard) ·
   Router (shallow, predictable) · Palette (Ctrl+K) · Polling (pauses when hidden).
   No decorative motion. Borders carry structure. Backend is only authority. */

import { h, icon, clear } from "./dom.js";
import { store, RESOURCES, syncResource, syncOperations, poll, measure } from "./api.js";
import { operationalState, freshness } from "./operations.js";
import { initWorkspace, readWorkspace, saveWorkspace } from "./workspace.js";
import { registerRoutes, startRouter, navigate } from "./router.js";
import { initPalette } from "./palette.js";
import { fmtAge } from "./format.js";
import { attentionRank } from "./status.js";
import { toast, badge, drawer } from "./components.js";
import { getContext, onContext } from "./context.js";

import * as overview from "./views/overview.js";
import * as research from "./views/research.js";
import * as market from "./views/market.js";
import * as trading from "./views/trading.js";
import * as risk from "./views/risk.js";
import * as evidence from "./views/evidence.js";
import * as system from "./views/system.js";
import * as governance from "./views/governance.js";

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
      listEl.appendChild(h("div", { class: "notif-empty" }, freshness(store.data.resources.notifications, "notifications").current ? "No notifications reported. See operating facts for permission and health." : "Notifications unavailable or stale. No all-clear can be established."));
      return;
    }
    for (const n of notes) {
      const info = LEVEL_TONE[String(n.level).toLowerCase()] ?? { tone: "neutral", label: String(n.level || "NOTICE").toUpperCase(), mark: "○" };
      listEl.appendChild(h("div", {
        class: "notif-item", role: "button", tabindex: "0",
        onclick: () => { close(); navigate("#/overview"); },
        onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); close(); navigate("#/overview"); } },
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

function buildHeader() {
  const facts = h("div", { class: "header-facts", id: "header-facts", role: "status", "aria-label": "Operating facts" });
  const conn = h("span", { class: "conn-dot", title: "API connection" });
  const updated = h("span", { class: "meta", id: "header-updated" }, "connecting…");

  const header = h("header", { class: "header" },
    h("button", { class: "btn ghost nav-toggle", "aria-label": "Toggle navigation", "aria-expanded": "false", onclick: (e) => { const open = document.getElementById("app").classList.toggle("nav-open"); e.currentTarget.setAttribute("aria-expanded", String(open)); } }, icon("menu", 18)),
    h("div", { class: "brand" },
      h("span", { class: "logo", "aria-hidden": "true" }, "QTS"),
      h("span", { class: "word" }, "QTS"),
      h("span", { class: "sub" }, "Research workstation"),
    ),
    facts,
    h("div", { class: "header-actions" },
      conn, updated,
      buildNotifBell(),
      h("button", { class: "btn ghost sm", onclick: openWorkspace, "aria-label": "Workspace preferences" }, icon("layers", 15), "Workspace"),
      h("a", { class: "btn ghost sm", href: location.hash || "#/overview", target: "_blank", rel: "noopener", "aria-label": "Open current context in another window", onclick: (e) => { e.currentTarget.href = location.hash || "#/overview"; } }, "New window"),
      h("button", { class: "btn ghost sm", onclick: () => palette?.open(), "aria-label": "Open command palette (Ctrl+K)", title: "Ctrl+K" }, icon("search", 15)),
    ),
  );
  return { header, facts, conn, updated };
}

function factChip({ label, value, cls = "", title }) {
  return h("span", { class: `fact ${cls}`, title: title ?? "" },
    label ? h("span", null, label, " ") : null,
    h("b", null, value),
  );
}

let palette;
function openWorkspace() {
  const p = readWorkspace();
  const ctx = getContext();
  const form = h("div", { class: "stack" },
    h("p", { class: "small text-dim" }, `Presentation preferences only. Modes, permissions and risk acknowledgements are never restored from browser storage. Context ${ctx.symbol} · ${ctx.timeframe} syncs across windows via BroadcastChannel, never permission. Multi-monitor: New window opens current context for second monitor. Native monitor placement and linked crosshairs benchmark — not claimed implemented if not.`),
    h("div", { class: "stat-grid" },
      stat({ label: "Density", value: p.density, hint: "compact = 5px rows, 10px cards — high density without chaos" }),
      stat({ label: "Width", value: p.width, hint: "focused 1440px, wide 1600px" }),
      stat({ label: "Context", value: `${ctx.symbol} · ${ctx.timeframe}`, hint: "presentation only, syncs, never permission" }),
    ),
  );
  for (const [key, label, options, hint] of [
    ["density", "Density", ["compact", "comfortable"], "Compact: 5px table rows, 10px cards — high density without chaos. Comfortable: more whitespace — professional instrument, not decorative."],
    ["width", "Workspace width", ["focused", "wide"], "Focused: 1440px max — readable, oriented. Wide: 1600px — more columns visible, controlled complexity."],
    ["navigation", "Navigation width", ["narrow", "standard", "wide"], "Sidebar width — persists per browser, never permission. Shallow, predictable, searchable."],
  ]) {
    const select = h("select", { class: "input", "aria-label": label }, options.map((v) => h("option", { value: v }, v)));
    select.value = p[key];
    select.addEventListener("change", () => { if (!saveWorkspace({ [key]: select.value })) toast("warn", "Preferences could not be saved", "Browser storage unavailable."); });
    form.appendChild(h("div", { class: "field" }, h("label", null, label), select, h("div", { class: "hint" }, hint)));
  }
  const remember = h("input", { type: "checkbox", checked: p.rememberRoute });
  remember.addEventListener("change", () => { if (!saveWorkspace({ rememberRoute: remember.checked, route: location.hash })) toast("warn", "Preferences could not be saved"); });
  form.appendChild(h("label", { class: "field-inline", style: { marginTop: "8px" } }, remember, h("span", { class: "small" }, "Restore last page on launch (never replay actions, never permission)")));
  form.appendChild(h("div", { class: "stack", style: { marginTop: "12px" } },
    h("div", { class: "eyebrow" }, "Keyboard — minimal cognitive cost, keyboard-first"),
    h("div", { class: "small text-dim" }, h("span", { class: "kbd" }, "Ctrl"), " + ", h("span", { class: "kbd" }, "K"), " palette · ", h("span", { class: "kbd" }, "/"), " filter nav · ", h("span", { class: "kbd" }, "Esc"), " close drawer/modal · ", h("span", { class: "kbd" }, "↑"), h("span", { class: "kbd" }, "↓"), " navigate rows · ", h("span", { class: "kbd" }, "Home"), "/", h("span", { class: "kbd" }, "End"), " first/last · ", h("span", { class: "kbd" }, "Enter"), " sort/open drawer"),
    h("div", { class: "eyebrow" }, "Workspace-oriented — persistent layouts, synchronized context"),
    h("div", { class: "small text-dim" }, "BroadcastChannel qts-context syncs symbol/timeframe across windows/tabs. localStorage qts.context.v1 persists per browser. Never permission/mode/risk. New window button opens current context for multi-monitor. TradingView benchmark for UX, not visual copy."),
    h("div", { class: "eyebrow" }, "Performance is UX — principle 13"),
    h("div", { class: "small text-dim" }, "Diagnostics shows last 100 measurements: load (page), route (transition), refresh (forced/periodic), render (workspace update), request (API), dup-coalesced (GET dedup), dup-sync (sync dedup), recovery (error→ok), poll (periodic), poll-skipped (hidden tab), heap (performance.memory). No payloads. Bounded 100. Measures load/transition/refresh/rendering/memory/dup/recovery."),
    h("div", { class: "eyebrow" }, "Safety — DEMO vs LIVE unmistakable"),
    h("div", { class: "small text-dim" }, "DEMO_FORWARD = real MT5 demo-account observation with zero orders, yellow/warn. DEMO_EXECUTION is disabled by product policy. LIVE = real capital, red/locked, structurally locked. What blocked, why, what missing, what next explicit everywhere."),
    h("div", { class: "eyebrow" }, "Truth visible — never 0 when missing"),
    h("div", { class: "small text-dim" }, "MEASURED/UNAVAILABLE/INSUFFICIENT/BLOCKED/DEGRADED/READY/OBSERVING/LOCKED — never 0. Provenance badges REAL/SYNTHETIC/SIMULATED/ESTIMATED/IMPUTED/BROKER-DERIVED/MODEL-DERIVED explicit on every field."),
  ));
  drawer("Workspace preferences — presentation only, never permission", form);
}

function stat({ label, value, hint }) {
  return h("div", { class: "stat" },
    h("div", { class: "stat-label" }, label),
    h("div", { class: "stat-value" }, value),
    hint ? h("div", { class: "stat-hint" }, hint) : null,
  );
}

function renderFacts(factsEl) {
  const s = operationalState(store.data);
  const ctx = getContext();
  const values = [
    ["mode", s.mode.mode, "mode"],
    ["Observation", s.observation, s.observing ? "observing" : ""],
    ["DEMO", s.permission, ""],
    ["LIVE", s.liveLabel, "live-locked"],
    ["ctx", `${ctx.symbol}`, "optional"],
  ];
  if (!factsEl.children.length) {
    for (const [label, value, cls] of values) factsEl.appendChild(factChip({ label, value, cls }));
  }
  [...factsEl.children].forEach((node, i) => {
    const [label, value, cls] = values[i];
    const v = node.querySelector("b");
    const cur = label === "ctx" ? `${getContext().symbol}` : value;
    if (v.textContent !== cur) v.textContent = cur;
    node.className = `fact ${cls}`;
    const src = label === "mode" ? s.sources.health : label === "Observation" ? s.sources.observe : label === "DEMO" ? s.sources.demoState : label === "LIVE" ? s.sources.live : null;
    if (label === "ctx") node.title = `Context: ${getContext().symbol} · ${getContext().timeframe} — presentation only, syncs across windows via BroadcastChannel, never permission.`;
    else node.title = `${label}: ${value}. ${src?.label ?? "UNAVAILABLE"} — ${label === "mode" ? "environment capability is not permission" : label === "DEMO" ? "readiness and permission are separate" : label === "LIVE" ? "never auto-enabled" : "collector state, zero orders"}.`;
  });
}

function buildSidebar() {
  const aside = h("nav", { class: "sidebar", "aria-label": "Primary" });
  const search = h("input", { class: "input nav-search", type: "search", "aria-label": "Find a workspace page", placeholder: "Find a page… ( / )" });
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    aside.querySelectorAll(".sidebar-group").forEach((group) => {
      group.querySelectorAll(".nav-item").forEach((item) => { item.hidden = !`${group.querySelector(".sidebar-group-label").textContent} ${item.textContent}`.toLowerCase().includes(q); });
      group.hidden = [...group.querySelectorAll(".nav-item")].every((x) => x.hidden);
    });
  });
  search.addEventListener("keydown", (e) => { if (e.key === "Escape") { search.value = ""; search.dispatchEvent(new window.Event("input")); } });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
      e.preventDefault(); search.focus();
    }
  });
  aside.appendChild(search);
  for (const g of IA) {
    const grp = h("div", { class: "sidebar-group" });
    grp.appendChild(h("div", { class: "sidebar-group-label" }, icon(g.icon, 14), h("span", null, g.label)));
    const add = (label, href, restricted) => {
      grp.appendChild(h("button", {
        class: `nav-item${restricted ? " restricted" : ""}`,
        dataset: { href },
        onclick: () => navigate(href),
      }, icon(restricted ? "lock" : g.icon, 14), h("span", null, label)));
    };
    if (g.children) {
      for (const c of g.children) add(c.label, `#/${g.id}/${c.id}`, false);
    } else {
      add(g.label, g.path ?? `#/${g.id}`, g.restricted);
    }
    aside.appendChild(grp);
  }
  aside.appendChild(h("div", { class: "sidebar-footer" },
    h("span", null, [h("span", { class: "kbd" }, "Ctrl"), " + ", h("span", { class: "kbd" }, "K"), " palette · ", h("span", { class: "kbd" }, "/"), " filter"]),
    h("span", null, "Backend is the only authority — UI requests and displays, never decides."),
  ));
  return aside;
}

function markActiveNav() {
  const hash = (location.hash || "#/overview").split("?")[0];
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.href === hash);
    if (el.dataset.href === hash) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
}

function main() {
  const loadStart = performance.now();
  initWorkspace();
  const { header, facts, conn, updated } = buildHeader();
  const app = h("div", { id: "app" },
    header,
    buildSidebar(),
    h("div", { class: "scrim", onclick: () => app.classList.remove("nav-open") }),
    h("main", { id: "main", class: "main", tabindex: "-1" }),
  );
  document.body.appendChild(app);

  registerRoutes(IA);
  palette = initPalette(IA, [
    { label: "Inspect observation (no orders)", group: "Actions", icon: "eye", run: () => navigate("#/market/observations") },
    { label: "Inspect readiness and permission", group: "Actions", icon: "shield", run: () => navigate("#/trading/demo") },
    { label: "Inspect timestamp normalization — FS-c42bbd fix", group: "Diagnostics", icon: "clock", run: () => navigate("#/system/diagnostics") },
    { label: "Market monitor — timestamp bases & offsets", group: "Market", icon: "activity", run: () => navigate("#/market/monitor") },
    { label: "Workspace preferences", group: "Workspace", icon: "layers", run: openWorkspace },
    { label: "Refresh operating sources", group: "Actions", icon: "refresh", run: () => syncOperations(true) },
    { label: "Toggle density compact/comfortable", group: "Workspace", icon: "layers", run: () => {
      const ws = readWorkspace();
      const next = ws.density === "compact" ? "comfortable" : "compact";
      saveWorkspace({ density: next });
      toast("ok", `Density ${next}`, "High density without chaos — professional instrument");
    }},
  ]);

  window.addEventListener("hashchange", () => { markActiveNav(); });
  const update = () => {
    renderFacts(facts);
    const f = freshness(store.data.resources.health, "health");
    conn.className = `conn-dot${f.current ? "" : f.label.includes("STALE") ? " stale" : " down"}`;
    updated.textContent = `Health API: ${f.label}${store.data.resources.health?.updatedAt ? ` · ${fmtAge(store.data.resources.health.updatedAt)}` : ""}`;
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
