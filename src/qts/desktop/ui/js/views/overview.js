/* QTS EXECUTIVE DASHBOARD — Decision-relevant trading system overview
   Answers the 6 core product questions in plain language:
   1. What is happening? (Market feed & quotes)
   2. Is there an opportunity? (Research & candidate validation status)
   3. Can the system act? (Execution readiness & stage)
   4. How is it performing? (Simulation results & reality drift)
   5. Is it safe? (Risk controls & live locked status)
   6. What needs attention? (Clear, actionable operator next step)
   Progressive disclosure preserves 100% of underlying technical evidence. */

import { store, syncOperations, RESOURCES, measurements, measure } from "../api.js";
import { operationalState } from "../operations.js";
import { h, icon } from "../dom.js";
import { page, table, stat } from "../components.js";
import { fmtUtc, fmtAge, fmtInt, fmtNum, explainStatus } from "../format.js";
import { statusInfo } from "../status.js";
import { onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";

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
    crumb: "Home",
    title: "Home",
    answer: "Six answers, then one next step. Connection details, codes, and raw readings stay closed until you open them.",
    actions: [refresh],
  }));

  root.appendChild(h("section", { class: "operator-summary", "aria-labelledby": "operator-activity" },
    h("div", null, h("div", { class: "eyebrow" }, "Right now"), activity, explanation),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "What to do next"), next, nextWhy)));
  root.appendChild(announce);

  // ---------------- 6-Pillar Decision Cards ----------------
  const pillarGrid = h("div", { class: "home-answers" });

  const pMarket = stat({ label: "Gold", value: "No live price yet", hint: "XAUUSD. A connection is not a price.", icon: "activity" });
  const pOpp = stat({ label: "Opportunity", value: "No validated opportunity", tone: "warn", hint: "Research has not authorized a trade.", icon: "scale" });
  const pExec = stat({ label: "Trading", value: "Not allowed", tone: "neutral", hint: "Demo safety is on. Live trading is locked.", icon: "lock" });
  const pPerf = stat({ label: "Your money", value: "Not at risk", tone: "ok", hint: "Real money cannot be used.", icon: "shield" });
  const pSafety = stat({ label: "Safety", value: "Live trading locked", tone: "ok", hint: "The kill switch stays armed. Demo cannot unlock live.", icon: "shield" });
  const pAction = stat({ label: "Next", value: "See the step above", tone: "warn", hint: "One step. Not a trade.", icon: "alert" });

  pillarGrid.append(pMarket, pOpp, pExec, pPerf, pSafety, pAction);
  root.appendChild(pillarGrid);

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

  const demoReasons = h("ul", { class: "reason-list" });
  const liveReasons = h("ul", { class: "reason-list" });
  const connectionDetails = h("details", { class: "operator-section" },
    h("summary", null, "Connection and safety details"),
    h("p", { class: "small text-dim" }, "Codes stay here. A missing or old reading is not permission to trade."),
    h("div", { class: "tbl-wrap", tabindex: "0", "aria-label": "Connection details" },
      h("table", { class: "tbl facts-table" },
        h("thead", null, h("tr", null, ["Item", "Status", "What it means", "How fresh", ""].map((t) => h("th", { scope: "col" }, t)))),
        tbody)),
    h("h3", { class: "small" }, "Why demo trading is or is not allowed"),
    demoReasons,
    link("Open demo account", "#/trading/demo"),
    h("h3", { class: "small" }, "Why live trading stays locked"),
    liveReasons,
    link("Open live trading rules", "#/governance/live"));

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
  const perfHost = h("div");
  const technical = h("details", { class: "operator-section" },
    h("summary", null, "Raw overview snapshot"),
    h("p", { class: "text-dim small" }, "Machine readings and browser timings. They do not change whether trading is allowed."),
    raw,
    perfHost);

  root.append(connectionDetails, evidenceDetails, technical);

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
    if (s.observing || /observing/i.test(s.activity)) {
      humanActivity = s.activity;
    } else if (s.activity.includes("STAGE_1_CONNECTIVITY_ONLY")) {
      humanActivity = "Connection Test Mode — Orders Disabled";
    } else if (s.activity.includes("INSUFFICIENT")) {
      humanActivity = "System Ready — Research Blocked (Data Incomplete)";
    } else if (s.permission === "DISABLED") {
      humanActivity = "Trading Disabled by Safety Policy";
    }
    setText(activity, humanActivity);
    const running = s.sources.health.current ? "QTS is running." : "QTS status is not available yet.";
    const money = s.liveLabel.includes("LOCKED") || !s.sources.live.current
      ? "Your money is not at risk."
      : "Live trading is still gated. Real money is not in use.";
    const stopped = s.killActive ? "Orders are stopped by the kill switch." : "";
    setText(explanation, `${running} ${money} ${stopped} There is no validated trading opportunity.`.replace(/\s+/g, " ").trim());

    const quoteRecorded = Boolean(s.obs?.last_tick_time);
    pMarket.querySelector(".stat-value").textContent = quoteRecorded ? "Quote recorded" : "No live price yet";
    pMarket.querySelector(".stat-hint").textContent = quoteRecorded
      ? `Last gold quote ${s.quoteAge}. A quote is not a trade.`
      : "XAUUSD. A connection is not a price.";
    const tradingAllowed = s.permission === "PERMITTED · DEMO ONLY" && !s.killActive;
    pExec.querySelector(".stat-value").textContent = s.killActive ? "Orders stopped" : tradingAllowed ? "Demo only" : "Not allowed";
    pExec.querySelector(".stat-hint").textContent = s.killActive
      ? "The kill switch is on. That does not close an open position. Live trading stays locked."
      : tradingAllowed
      ? "Demo orders can be considered. Live trading stays locked."
      : explainStatus(s.permission === "DISABLED BY POLICY" ? "DISABLED_BY_POLICY" : s.permission);
    pPerf.querySelector(".stat-value").textContent = "Not at risk";
    pSafety.querySelector(".stat-value").textContent = s.liveLabel.includes("LOCKED") ? "Live trading locked" : "Live still gated";
    pAction.querySelector(".stat-value").textContent = s.next.label;

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
      mode: "The environment name is not permission to trade.",
      broker: "Whether the terminal is connected. Not a gold price.",
      market: "Whether stored market data is usable. Not a live quote.",
      quoteAge: s.obs?.last_tick_time ? `Last recorded quote: ${fmtUtc(s.obs.last_tick_time)}.` : "No gold quote has been recorded.",
      observation: s.observing ? "Quotes are being recorded. No order is sent." : s.obs?.last_error || s.obs?.note || "Quote recording is not running.",
      permission: !s.sources.demoState.current ? "Trading permission is unknown because the status is missing or old." : explainStatus(s.permission),
      liveLabel: "Live trading cannot turn on by itself. Real money stays unavailable.",
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

    reasonList(demoReasons, !s.sources.demoState.current ? ["Trading permission is unknown because that status is missing or old."] : [
      explainStatus(s.permission),
      ...(s.permission === "DISABLED" || s.permission === "DISABLED BY POLICY" ? ["Watching the market does not turn trading on."] : []),
      ...s.reasons.map((r) => explainStatus(r)),
      ...s.readinessReasons.map((r) => explainStatus(r)),
    ]);

    reasonList(liveReasons, !s.sources.live.current ? ["Live-trading status is missing or old. Treat it as locked."] : [
      s.liveLabel.includes("LOCKED") ? "Live trading is locked. Real money cannot be used." : explainStatus(s.liveLabel),
      ...s.liveReasons.map((r) => explainStatus(r)),
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
      renderPerf();
    }
    measure("render", "operator workspace update", performance.now() - started);
  }

  technical.addEventListener("toggle", () => { if (technical.open) renderPerf(); update(); });
  const off = store.on("resources", update);
  const offCtx = onContext(update);
  const clock = setInterval(update, 1000);
  clock.unref?.();
  onDispose(root, () => { off(); offCtx(); clearInterval(clock); });

  update();
  await syncOperations();
}
