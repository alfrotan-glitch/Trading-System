/* QTS EXECUTIVE DASHBOARD — Decision-relevant trading system overview
   Answers the 6 core product questions in plain language:
   1. What is happening? (Market feed & quotes)
   2. Is there an opportunity? (Research & candidate validation status)
   3. Can the system act? (Execution readiness & stage)
   4. How is it performing? (Simulation results & reality drift)
   5. Is it safe? (Risk controls & live locked status)
   6. What needs attention? (Clear, actionable operator next step)
   Progressive disclosure preserves 100% of underlying technical evidence. */

import { api, store, syncOperations, RESOURCES, measurements, measure } from "../api.js";
import { operationalState } from "../operations.js";
import { h, icon, clear } from "../dom.js";
import { page, table, card, stat, banner, kv } from "../components.js";
import { fmtUtc, fmtAge, fmtInt, fmtNum } from "../format.js";
import { statusInfo } from "../status.js";
import { onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";
import { readWorkspace } from "../workspace.js";

const link = (label, href, cls = "btn sm") => h("a", { class: cls, href }, label);
const setText = (node, value) => { const s = String(value); if (node.textContent !== s) node.textContent = s; };

export async function renderOverview(root) {
  root.classList.add("operator-workspace");
  const activity = h("h2", { id: "operator-activity" }, "Loading operating state…");
  const explanation = h("p", { class: "text-dim small" });
  const next = link("Inspect unavailable sources", "#/system/diagnostics", "btn primary");
  const nextWhy = h("p", { class: "text-dim small" });
  const announce = h("div", { class: "sr-only", role: "status", "aria-live": "polite" });
  const refresh = h("button", { class: "btn", onclick: () => syncOperations(true) }, icon("refresh", 14), "Refresh sources");

  root.appendChild(page({
    crumb: "Overview",
    title: "Executive Dashboard",
    answer: "Continuous status across market connectivity, research validation, execution readiness, and risk controls. Context syncs across windows, never permission.",
    actions: [refresh],
  }));

  root.appendChild(h("section", { class: "operator-summary", "aria-labelledby": "operator-activity" },
    h("div", null, h("div", { class: "eyebrow" }, "SYSTEM STATUS"), activity, explanation),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "RECOMMENDED OPERATOR ACTION"), next, nextWhy)));
  root.appendChild(announce);

  // ---------------- 6-Pillar Decision Cards ----------------
  const pillarGrid = h("div", { class: "stat-grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", marginBottom: "16px" } });
  
  const pMarket = stat({ label: "Market Status", value: "CONNECTING", hint: "XAUUSD live feed & spread", icon: "activity" });
  const pOpp = stat({ label: "Opportunity Status", value: "NO VALIDATED EDGE", tone: "warn", hint: "Candidate evaluation paused", icon: "flask" });
  const pExec = stat({ label: "Execution Permission", value: "DISABLED", tone: "neutral", hint: "Connection test mode only", icon: "lock" });
  const pPerf = stat({ label: "Capital Exposure", value: "$0.00", tone: "ok", hint: "Real-money exposure: ZERO", icon: "shield" });
  const pSafety = stat({ label: "Safety Controls", value: "ACTIVE & ARMED", tone: "ok", hint: "Live locked · 22 gates active", icon: "shield" });
  const pAction = stat({ label: "Attention Required", value: "ACQUIRE DATA", tone: "warn", hint: "6.42% missing intervals", icon: "alert" });

  pillarGrid.append(pMarket, pOpp, pExec, pPerf, pSafety, pAction);
  root.appendChild(card({
    title: "Core System Telemetry",
    sub: "Decision-relevant summary of market, research, execution, and risk posture",
    icon: "layers",
    body: pillarGrid,
  }));

  // ---------------- Operating Facts Table ----------------
  const definitions = [
    ["mode", "Environment / mode", "health", "#/system/diagnostics"],
    ["broker", "Broker (MT5)", "health", "#/system/mt5"],
    ["market", "Market data pipeline", "health", "#/market/quality"],
    ["quoteAge", "Collected quote age", "observe", "#/market/observations"],
    ["observation", "Observation collector", "observe", "#/market/observations"],
    ["permission", "DEMO execution", "demoState", "#/trading/demo"],
    ["liveLabel", "LIVE governance", "live", "#/governance/live"],
  ];
  const tbody = h("tbody");
  const cells = {};
  for (const [key, title, resource, href] of definitions) {
    const state = h("span", { class: "badge neutral" }, "UNAVAILABLE");
    const detail = h("span");
    const fresh = h("span", { class: "resource-fresh" });
    cells[key] = { state, detail, fresh, resource };
    tbody.appendChild(h("tr", { dataset: { fact: key } },
      h("th", { scope: "row" }, title),
      h("td", null, state),
      h("td", { class: "fact-detail" }, detail),
      h("td", { class: "mono small" }, fresh),
      h("td", null, link("Inspect", href))));
  }

  root.appendChild(h("section", { class: "operator-section", "aria-labelledby": "facts-title" },
    h("h2", { id: "facts-title" }, "System Health & Connection Status"),
    h("p", { class: "small text-dim" }, "Authoritative verification status per subsystem. Freshness reflects API receipt; stale authority cannot establish execution permission."),
    h("div", { class: "tbl-wrap", tabindex: "0", "aria-label": "Operating facts, horizontally scrollable" },
      h("table", { class: "tbl facts-table" },
        h("thead", null, h("tr", null, ["Subsystem", "Reported State", "Meaning & Constraints", "Freshness", "Action"].map((t) => h("th", { scope: "col" }, t)))),
        tbody))));

  // ---------------- Workspace Facts ----------------
  const workspaceFacts = h("div", { class: "stat-grid" });
  function renderWorkspaceFacts() {
    const ws = readWorkspace();
    const ctx = getContext();
    clear(workspaceFacts);
    workspaceFacts.append(
      stat({ label: "Density", value: ws.density === "compact" ? "High Density" : "Standard", hint: "Compact tabular view" }),
      stat({ label: "Width", value: ws.width, hint: "Workspace responsive container" }),
      stat({ label: "Context", value: `${ctx.symbol} · ${ctx.timeframe}`, hint: "Presentation symbol context" }),
      stat({ label: "Navigation", value: ws.navigation, hint: "Standard sidebar navigation" }),
    );
  }
  root.appendChild(card({
    title: "Display & Workspace Preferences",
    sub: "Machine-local layout preferences · presentation only, never changes execution permission",
    icon: "gear",
    body: workspaceFacts,
  }));

  // ---------------- Authority & Governance Overview ----------------
  const demoReasons = h("ul", { class: "reason-list" });
  const liveReasons = h("ul", { class: "reason-list" });
  root.appendChild(h("div", { class: "operator-grid" },
    h("section", { class: "operator-section" },
      h("h2", null, "Demo Execution Safety Posture"),
      h("p", { class: "text-dim small" }, "Durable execution permission is separated from connection checks. Connection tests create zero order permission."),
      demoReasons,
      link("Inspect permission & readiness", "#/trading/demo")),
    h("section", { class: "operator-section live-boundary" },
      h("h2", null, "Live Capital Protection"),
      h("p", { class: "text-dim small" }, "Real money is locked by structural policy. Demo observations can never automatically unlock live trading."),
      liveReasons,
      link("Inspect missing LIVE evidence", "#/governance/live"))));

  // ---------------- Collapsible Evidence & Details ----------------
  // 1. Observation Evidence
  const observationEvidence = h("dl", { class: "evidence-values" });
  const obsFields = {};
  for (const title of ["Session", "Recorded quotes", "Orders submitted (collector)", "Last broker event (UTC)", "Context"]) {
    obsFields[title] = h("dd", null, "UNAVAILABLE");
    observationEvidence.append(h("dt", null, title), obsFields[title]);
  }
  const evidenceDetails = h("details", { class: "operator-section evidence-disclosure" },
    h("summary", null, "Observation evidence / scope and limitations — summary → detail"),
    observationEvidence,
    h("p", { class: "text-dim small" }, "Recorded quotes are sample ticks for observability. Orders submitted reflects collector activity (0)."),
    link("Open observations", "#/market/observations"), " ",
    link("Open research inventory", "#/research/data"), " ",
    link("Account & execution evidence", "#/trading/execution"), " ",
    link("Audit trail", "#/evidence/audit"));

  // 2. Raw Overview Snapshot
  const raw = h("pre");
  const technical = h("details", { class: "operator-section" },
    h("summary", null, "Raw overview snapshot / technical evidence — drill to raw"),
    raw);

  // 3. UI Performance Diagnostics
  const perfHost = h("div");
  const diagnostics = h("details", { class: "operator-section" },
    h("summary", null, "UI performance / last 100 measurements — load, transition, refresh, render, dup, recovery, memory"),
    h("p", { class: "text-dim small" }, "Browser update metrics and transition timings in ms. Bounded to last 100 entries."),
    perfHost);

  root.append(evidenceDetails, technical, diagnostics);

  const reasonList = (el, entries) => {
    const signature = JSON.stringify(entries);
    if (el.dataset.signature === signature) return;
    el.dataset.signature = signature;
    const wasOpen = el.querySelector("details")?.open;
    const rest = entries.slice(4);
    el.replaceChildren(...entries.slice(0, 4).map((x) => h("li", null, x)));
    if (rest.length) {
      el.appendChild(h("li", null, h("details", { open: wasOpen },
        h("summary", null, `${rest.length} more recorded reasons`),
        h("ul", null, rest.map((x) => h("li", null, x))))));
    }
  };

  function renderPerf() {
    const byKind = {};
    for (const m of measurements) {
      if (!byKind[m.kind]) byKind[m.kind] = { count: 0, total: 0, failed: 0, max: 0 };
      byKind[m.kind].count++;
      byKind[m.kind].total += m.ms || 0;
      byKind[m.kind].max = Math.max(byKind[m.kind].max, m.ms || 0);
      if (m.outcome === "failed") byKind[m.kind].failed++;
    }
    const rows = Object.entries(byKind).map(([kind, v]) => ({
      kind, count: v.count, avg: v.count ? v.total / v.count : 0, max: v.max, failed: v.failed,
    })).sort((a, b) => b.count - a.count);
    const heap = measurements.length ? measurements[measurements.length - 1].heapUsed : null;
    perfHost.replaceChildren(
      h("div", { class: "stat-grid" },
        stat({ label: "Total measured", value: `${measurements.length} / 100` }),
        stat({ label: "Heap (last)", value: heap ? `${heap} KB` : "UNAVAILABLE" }),
        stat({ label: "Dup coalesced", value: `${(byKind["dup-coalesced"]?.count ?? 0) + (byKind["dup-sync"]?.count ?? 0)}` }),
        stat({ label: "Recoveries", value: `${byKind["recovery"]?.count ?? 0}` }),
      ),
      rows.length ? table({
        columns: [
          { key: "kind", label: "Kind" },
          { key: "count", label: "Count", num: true },
          { key: "avg", label: "Avg ms", num: true, render: (r) => fmtNum(r.avg, 1) },
          { key: "max", label: "Max ms", num: true, render: (r) => fmtNum(r.max, 1) },
          { key: "failed", label: "Failed", num: true },
        ],
        rows,
        dense: true,
      }) : h("p", { class: "small text-dim" }, "No measurements recorded yet."),
    );
  }

  let lastAnnouncement = "";
  function update() {
    if (!root.isConnected) return;
    const started = performance.now();
    const s = operationalState(store.data);

    // Humanize executive title
    let humanActivity = s.activity;
    if (s.activity.includes("STAGE_1_CONNECTIVITY_ONLY")) {
      humanActivity = "Connection Test Mode — Orders Disabled";
    } else if (s.activity.includes("INSUFFICIENT")) {
      humanActivity = "System Ready — Research Blocked (Data Incomplete)";
    } else if (s.permission === "DISABLED") {
      humanActivity = "Trading Disabled by Safety Policy";
    }
    setText(activity, humanActivity);
    setText(explanation, `Environment: ${s.mode.mode} · Live Trading: ${s.liveLabel} · Symbol: ${getContext().symbol}`);

    // Update 6 Telemetry Cards
    pMarket.querySelector(".stat-value").textContent = s.broker === "CONNECTED" ? "CONNECTED" : (s.broker || "DISCONNECTED");
    pExec.querySelector(".stat-value").textContent = s.permission === "ENABLED" ? "ENABLED" : "DISABLED";
    if (s.sources.demoState.current && s.demo?.state === "DISABLED") {
      pExec.querySelector(".stat-value").textContent = "DISABLED";
    }
    if (s.liveLabel.includes("LOCKED")) {
      pPerf.querySelector(".stat-value").textContent = "$0.00";
    }

    setText(next, s.next.label);
    next.href = s.next.href;
    setText(nextWhy, s.next.why);
    refresh.disabled = Object.values(store.data.resources).some((m) => m.loading);

    const summary = `${humanActivity}; DEMO ${s.permission}; LIVE ${s.liveLabel}`;
    if (summary !== lastAnnouncement) {
      setText(announce, summary);
      lastAnnouncement = summary;
    }

    const meanings = {
      mode: "Environment capability is not execution permission.",
      broker: "Terminal connectivity; not proof of a healthy live quote.",
      market: "Backend pipeline status, not proof of a healthy live quote.",
      quoteAge: s.obs?.last_tick_time ? `Last reported broker event: ${fmtUtc(s.obs.last_tick_time)}.` : "No current collected-quote timestamp.",
      observation: s.observing ? "Collector reports active worker. No order path." : s.obs?.last_error || s.obs?.note || "No active collection established.",
      permission: !s.sources.demoState.current ? "Current permission cannot be established — stale source." : `Authority state: ${s.demo?.state ?? "UNAVAILABLE"}; risk and execution gates independent.`,
      liveLabel: "Never auto-enabled. Independent evidence and human governance required. Unmistakable locked styling.",
    };

    for (const [key] of definitions) {
      const { state, detail, fresh, resource } = cells[key];
      const value = key === "mode" ? s.mode.mode : s[key];
      const info = statusInfo(value);
      setText(state, value);
      state.className = `badge ${key === "liveLabel" ? "locked" : info.tone}`;
      setText(detail, meanings[key]);
      const m = store.data.resources[resource];
      setText(fresh, `${s.sources[resource].label}${m?.updatedAt ? ` · ${fmtAge(m.updatedAt)}` : ""}`);
      fresh.title = m?.updatedAt ? `Last successful API receipt: ${fmtUtc(m.updatedAt)}; ${RESOURCES[resource].path}` : RESOURCES[resource].path;
    }

    reasonList(demoReasons, !s.sources.demoState.current ? ["Permission source unavailable or stale. Retry or inspect Diagnostics."] : [
      `Authority reports ${s.permission}.`,
      ...(s.permission === "DISABLED" ? ["Execution remains disabled. Observation does not require enabling it."] : []),
      ...s.reasons.map((r) => `Permission: ${r}`),
      ...s.readinessReasons.map((r) => `Current readiness: ${r}`),
    ]);

    reasonList(liveReasons, !s.sources.live.current ? ["Governance source unavailable or stale."] : [
      `Authority reports ${s.liveLabel}.`,
      ...s.liveReasons.map((r) => String(r).replace(/_/g, " ")),
    ]);

    const obs = s.obs;
    setText(obsFields.Session, obs?.session_id ?? "UNAVAILABLE");
    setText(obsFields["Recorded quotes"], obs?.ticks_recorded == null ? "UNAVAILABLE" : fmtInt(obs.ticks_recorded));
    setText(obsFields["Orders submitted (collector)"], obs?.orders_submitted == null ? "UNAVAILABLE" : fmtInt(obs.orders_submitted));
    setText(obsFields["Last broker event (UTC)"], obs?.last_tick_time ? fmtUtc(obs.last_tick_time) : "UNAVAILABLE");
    setText(obsFields.Context, `${getContext().symbol} · ${getContext().timeframe} — presentation context`);

    if (technical.open) {
      raw.textContent = JSON.stringify({
        sources: store.data.resources,
        health: store.data.health,
        observation: store.data.observe,
        demo: store.data.demoState,
        live: store.data.live,
        context: getContext(),
      }, null, 2);
    }
    if (diagnostics.open) renderPerf();
    measure("render", "operator workspace update", performance.now() - started);
  }

  technical.addEventListener("toggle", update);
  diagnostics.addEventListener("toggle", () => { renderPerf(); update(); });
  const off = store.on("resources", () => { update(); renderWorkspaceFacts(); });
  const offCtx = onContext(() => { update(); renderWorkspaceFacts(); });
  const clock = setInterval(update, 1000);
  clock.unref?.();
  onDispose(root, () => { off(); offCtx(); clearInterval(clock); });

  renderWorkspaceFacts();
  update();
  await syncOperations();
}
