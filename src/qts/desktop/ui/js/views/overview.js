/* ============================================================
   VIEW: OVERVIEW — the command center
   Answers, in order: what is QTS doing · what market · what mode ·
   is trading permitted · what needs attention · what should I do
   next. Every answer is derived from canonical endpoints only.
   ============================================================ */
import { api, store, poll } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, stat, metricStat, badge, banner, page, rail, journey, checkGrid, tech,
  emptyState, skeletonInto, freshStamp, kv, timeline, toast, provStrip, errorBox, table,
} from "../components.js";
import { fmtMetric, fmtAge, fmtUtc, fmtInt, fmtDuration } from "../format.js";
import { modeInfo, lifecycleStages, statusInfo } from "../status.js";
import { navigate } from "../router.js";

export async function renderOverview(root) {
  skeletonInto(root, "stats");
  let health, risk, observe, demoState, live, manifest, notes, campaigns, audit, dash;
  try {
    [health, risk, observe, demoState, live, manifest, notes, campaigns, audit, dash] = await Promise.all([
      api.get("/api/health"),
      api.get("/api/risk"),
      api.get("/api/observe/status"),
      api.get("/api/demo/state"),
      api.get("/api/live/status"),
      api.get("/api/research/forward-manifest"),
      api.get("/api/notifications"),
      api.get("/api/research/campaigns"),
      api.get("/api/audit?limit=8"),
      api.get("/api/dashboard"),
    ]);
  } catch (e) {
    clear(root);
    root.appendChild(errorBox({
      what: "the system overview could not be loaded",
      known: e.status ? `API responded with status ${e.status}.` : "The API server did not respond.",
      next: "use Retry; if it persists, restart QTS from the desktop launcher.",
      raw: e.message,
    }));
    root.appendChild(h("div", { class: "mt-4" },
      h("button", { class: "btn primary", onclick: () => renderOverview(root) }, icon("refresh", 14), "Retry")));
    return;
  }

  const mode = modeInfo(health.effective_mode?.effective_mode);
  const brokerUp = String(health.mt5 || "").toLowerCase() === "connected";
  const dataUp = String(health.market_data || "").toLowerCase().includes("healthy");
  const canTrade = !risk.blocked;
  const clearRoot = clear(root);

  /* ---------- page head ---------- */
  const head = page({
    crumb: "Overview",
    title: "Command Center",
    answer: [
      h("b", null, mode.mode), ` — ${mode.blurb} `,
      h("span", { class: "text-dim" }, "All numbers below come from the canonical backend; nothing on this page is simulated presentation data."),
    ],
    actions: [
      h("button", { class: "btn", onclick: () => renderOverview(root) }, icon("refresh", 14), "Refresh"),
      h("button", { class: "btn", onclick: () => navigate("#/system/setup") }, icon("gear", 14), "Setup"),
    ],
    body: null,
  });
  root.appendChild(head);

  /* ---------- operator questions strip ---------- */
  root.appendChild(h("div", { class: "stat-grid", style: { marginTop: "var(--sp-5)" } },
    stat({
      label: "Effective mode", value: mode.mode, tone: mode.tone === "neutral" ? "neutral" : mode.tone,
      hint: mode.canSubmit === true ? "broker submission possible in this mode" : mode.canSubmit === "gated" ? "submission gated by demo authority" : "no broker submission in this mode",
      icon: "layers",
    }),
    stat({
      label: "Broker (MT5)", value: brokerUp ? "CONNECTED" : String(health.mt5 || "UNAVAILABLE").toUpperCase(),
      tone: brokerUp ? "ok" : "warn",
      hint: brokerUp ? "terminal reachable — account state on MT5 page" : "no live terminal context — observation/demo need it",
      icon: "bank",
    }),
    stat({
      label: "Market data", value: String(health.market_data || "UNAVAILABLE").toUpperCase(),
      tone: dataUp ? "ok" : "warn",
      hint: manifest.ticks_recorded ? `${fmtInt(manifest.ticks_recorded)} recorded ticks` : "no forward observations recorded yet",
      icon: "activity",
    }),
    stat({
      label: "Trading permission", value: canTrade ? "PERMITTED (within limits)" : "BLOCKED",
      tone: canTrade ? "ok" : "err",
      hint: canTrade ? "risk limits satisfied — see Risk for why" : `${risk.blocked_reasons.length} active reason(s) — see Risk`,
      icon: "shield",
    }),
  ));

  /* ---------- lifecycle rail ---------- */
  const stages = lifecycleStages({
    mode: mode.mode,
    observeState: observe.state,
    ticksRecorded: manifest.ticks_recorded,
    demoState: demoState.state,
    demoPermitted: demoState.execution_permitted,
    liveEligible: live.eligible,
    liveStatus: live.live_trading,
  });
  root.appendChild(card({
    title: "Strategy lifecycle", sub: "where QTS is on the path to live — every stage transition is gated by evidence",
    icon: "branch",
    body: h("div", null,
      rail(stages),
      h("div", { class: "mt-3" }, banner(
        live.eligible ? "warn" : "info",
        ("LIVE — " + String(live.live_trading || "LOCKED")).toUpperCase(),
        live.eligible ? "Eligible — human approval still required." : live.message,
        "lock",
      )),
    ),
  }));

  /* ---------- attention + journey ---------- */
  const attention = buildAttention({ health, risk, demoState, live, manifest, notes });
  const journeySteps = await buildJourney({ health, observe, demoState, live, campaigns });

  root.appendChild(h("div", { class: "grid-2 section" },
    card({
      title: "Requires attention", sub: "highest-severity first — nothing here is decorative", icon: "alert",
      actions: [h("button", { class: "btn ghost sm", onclick: () => navigate("#/evidence/audit") }, "Full audit trail")],
      body: attention.length
        ? h("div", { class: "stack" }, attention.map((a) =>
            h("div", { class: "row spread", style: { padding: "6px 0", borderBottom: "1px solid var(--line-soft)" } },
              h("div", { class: "row", style: { gap: "8px" } }, badge(a.level), h("span", { class: "small text-dim" }, a.text)),
              a.href ? h("button", { class: "btn ghost sm", onclick: () => navigate(a.href) }, "Open") : null,
            )))
        : emptyState({ icon: "check", title: "Nothing requires attention", desc: "All monitored subsystems are reporting healthy or are intentionally idle." }),
    }),
    card({
      title: "Setup journey", sub: "guided path from install to controlled demo — each step is checked against the live system", icon: "sliders",
      body: h("div", { class: "journey" }, journeySteps),
    }),
  ));

  /* ---------- sessions + activity ---------- */
  const obsActive = observe.state === "running";
  root.appendChild(h("div", { class: "grid-2 section" },
    card({
      title: "Observation session", sub: "real-market forward observation — zero orders", icon: "eye",
      actions: [h("button", { class: "btn ghost sm", onclick: () => navigate("#/market/observations") }, "Open observatory")],
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Session state", value: obsActive ? "OBSERVING" : String(observe.state || "IDLE").toUpperCase(), tone: obsActive ? "run" : "neutral", icon: "eye" }),
          stat({ label: "Ticks recorded", value: fmtInt(manifest.ticks_recorded), hint: `${fmtInt(manifest.real_market_ticks)} real-market`, icon: "database" }),
          stat({ label: "Orders submitted", value: fmtInt(observe.orders_submitted), tone: Number(observe.orders_submitted) === 0 ? "ok" : "warn", hint: "observation never submits orders", icon: "zap" }),
        ),
        manifest.ticks_recorded
          ? kv([["Canonical store", manifest.canonical_store], ["Capital exposure", manifest.no_capital_exposure ? "none (observation only)" : "review required"]])
          : emptyState({
              icon: "eye", title: "No real observations recorded yet",
              desc: "Start an observation session to record real broker ticks (bid/ask/spread/regime). No orders are ever submitted during observation.",
              actions: [h("button", { class: "btn", onclick: () => navigate("#/market/observations") }, icon("play", 14), "Start Observation")],
            }),
      ),
    }),
    card({
      title: "Recent activity", sub: "audit events — append-only, redacted", icon: "clock",
      actions: [h("button", { class: "btn ghost sm", onclick: () => navigate("#/evidence/audit") }, "Evidence")],
      body: audit.length
        ? timeline(audit.slice(0, 8).map((a) => ({
            when: fmtUtc(a.time),
            what: `${String(a.type || "event").toUpperCase()}${a.payload?.event ? ` — ${String(a.payload.event).replace(/_/g, " ")}` : ""}`,
            detail: a.payload?.reason ? truncReason(a.payload.reason) : null,
            tone: String(a.type).includes("block") || String(a.type).includes("veto") ? "err" : String(a.type).includes("enable") || String(a.type).includes("start") ? "ok" : "",
          })))
        : emptyState({ icon: "clock", title: "No activity yet", desc: "Audit events appear here as soon as QTS does anything: campaigns, checks, enables, blocks." }),
    }),
  ));

  /* ---------- account / positions / latest decision ---------- */
  root.appendChild(card({
    title: "Account & positions", sub: "as reported by the canonical account authority — unmeasured values show UNAVAILABLE", icon: "bank",
    actions: [h("button", { class: "btn ghost sm", onclick: () => navigate("#/trading/execution") }, "Execution center")],
    body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        metricStat({ label: "Equity", metric: dash.equity, icon: "pulse" }),
        metricStat({ label: "Balance", metric: dash.balance, icon: "bank" }),
        metricStat({ label: "Exposure", metric: dash.exposure, icon: "layers" }),
        metricStat({ label: "Spread", metric: dash.spread, digits: 1, icon: "activity" }),
      ),
      h("div", { class: "grid-2" },
        (dash.open_positions ?? []).length
          ? table({
              columns: [
                { key: "symbol", label: "Symbol" },
                { key: "side", label: "Side" },
                { key: "volume", label: "Volume", num: true },
                { key: "profit", label: "P&L", num: true },
              ],
              rows: dash.open_positions,
              empty: "No positions.",
            })
          : h("div", { class: "empty", style: { padding: "var(--sp-4)" } },
              h("div", { class: "empty-title" }, "No open positions"),
              h("div", { class: "empty-desc" }, "Positions appear only after real (demo or live) execution — simulated paper positions stay on the Paper/Shadow page, clearly labeled.")),
        h("div", null,
          h("div", { class: "eyebrow", style: { marginBottom: "6px" } }, "Reconciliation"),
          banner(String(dash.reconciliation_status).toLowerCase() === "healthy" ? "ok" : "err",
            String(dash.reconciliation_status ?? "UNAVAILABLE").toUpperCase(),
            "internal state vs broker, checked continuously",
            String(dash.reconciliation_status).toLowerCase() === "healthy" ? "check" : "alert"),
          dash.latest_decision
            ? [h("div", { class: "eyebrow mt-3", style: { marginBottom: "6px" } }, "Latest decision"),
               h("div", { class: "gate-note" }, truncReason(JSON.stringify(dash.latest_decision)))]
            : null,
        ),
      ),
    ),
  }));

  /* ---------- research pulse ---------- */
  root.appendChild(card({
    title: "Research pulse", sub: "what the laboratory is doing", icon: "flask",
    actions: [h("button", { class: "btn ghost sm", onclick: () => navigate("#/research/campaigns") }, "Open Research")],
    body: campaigns.length
      ? h("div", null,
          table({
            columns: [
              { key: "id", label: "Campaign", render: (c) => h("span", { class: "primary-cell mono" }, c.id?.slice(0, 18) ?? "—") },
              { key: "status", label: "Status", render: (c) => badge(c.status) },
              { key: "family", label: "Family", render: (c) => c.config?.family ?? "—" },
              { key: "symbol", label: "Symbol", render: (c) => `${c.config?.symbol ?? "—"} ${c.config?.timeframe ?? ""}` },
              { key: "trials", label: "Max trials", num: true, render: (c) => String(c.config?.max_trials ?? "—") },
            ],
            rows: campaigns.slice(0, 5),
            empty: "No campaigns.",
            onRowClick: () => navigate("#/research/campaigns"),
          }),
        )
      : emptyState({
          icon: "flask", title: "Research has not started yet",
          desc: "QTS researches like a scientist: it proposes falsifiable hypotheses, runs bounded experiments, attacks survivors, and records every failure as knowledge.",
          actions: [h("button", { class: "btn primary", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Research")],
        }),
  }));

  root.appendChild(h("div", { class: "mt-4" }, tech({ health, risk_summary: { blocked: risk.blocked, reasons: risk.blocked_reasons }, observe, demo_state: demoState, live_status: live }, "Raw overview snapshot")));
}

function truncReason(r) {
  const s = String(r);
  return s.length > 120 ? s.slice(0, 119) + "…" : s;
}

/* ---------- attention builder (canonical sources only) ---------- */
function buildAttention({ health, risk, demoState, live, manifest, notes }) {
  const items = [];
  for (const n of notes || []) {
    items.push({ level: n.level, text: `${n.title}${n.detail ? ` — ${n.detail}` : ""}`, href: "#/overview" });
  }
  if (String(health.mt5).toLowerCase() !== "connected") {
    items.push({ level: "warning", text: "MT5 terminal not connected — observation and demo cannot run. This is normal in development environments.", href: "#/system/mt5" });
  }
  if (String(health.market_data).toLowerCase() !== "healthy") {
    items.push({ level: "warning", text: `Market data: ${health.market_data}. Signals requiring fresh data are not trustworthy right now.`, href: "#/market/monitor" });
  }
  if (risk.blocked) {
    items.push({ level: "error", text: `Trading blocked by risk: ${risk.blocked_reasons.slice(0, 2).join("; ")}${risk.blocked_reasons.length > 2 ? ` (+${risk.blocked_reasons.length - 2} more)` : ""}`, href: "#/risk" });
  }
  if (demoState.state === "ENABLED" && demoState.readiness_expired) {
    items.push({ level: "critical", text: "Demo execution enabled but readiness has expired — re-verify before any submission.", href: "#/trading/demo" });
  }
  return items.slice(0, 8);
}

/* ---------- setup journey (each step verified against live state) ---------- */
async function buildJourney({ health, observe, demoState, live, campaigns }) {
  let readiness = null;
  try { readiness = await api.get("/api/demo/readiness"); } catch { readiness = null; }
  const brokerUp = String(health.mt5).toLowerCase() === "connected";
  const dataOk = String(health.market_data).toLowerCase() === "healthy";
  const researchDone = (campaigns?.length ?? 0) > 0;
  const readinessPassed = Boolean(readiness?.passed);

  const steps = [
    {
      state: brokerUp ? "done" : "active",
      title: "1 · Connect the MT5 environment",
      desc: brokerUp ? `Terminal connected (${health.mt5}).` : "Install MetaTrader 5 with a DEMO account, then set the terminal path in Setup. Development without a terminal is fine — research works on historical data.",
      action: brokerUp ? null : btn("Open Setup", "#/system/setup"),
    },
    {
      state: dataOk ? "done" : brokerUp ? "active" : "blocked",
      title: "2 · Verify market data freshness",
      desc: dataOk ? "Market data pipeline healthy." : "Start a short observation session so QTS can record real ticks and verify freshness, spread and regime.",
      action: !dataOk && brokerUp ? btn("Observation", "#/market/observations") : null,
    },
    {
      state: researchDone ? "done" : "active",
      title: "3 · Run research",
      desc: researchDone ? `${campaigns.length} campaign(s) recorded — every trial is preserved.` : "Create a bounded research campaign. QTS proposes hypotheses, executes experiments and attacks survivors — failures are recorded as knowledge.",
      action: researchDone ? btn("View research", "#/research/campaigns") : btn("Start research", "#/research/campaigns"),
    },
    {
      state: readinessPassed ? "done" : researchDone ? "active" : "blocked",
      title: "4 · Verify broker readiness (14 checks)",
      desc: readinessPassed ? `All readiness checks passed ${readiness.timestamp ? fmtAge(readiness.timestamp) : ""}.` : "Run the 14-check readiness gate against the DEMO terminal: connection, account type, symbol, spread, freshness, account state.",
      action: !readinessPassed ? btn("Run readiness", "#/trading/demo") : null,
    },
    {
      state: demoState.enabled ? "done" : readinessPassed ? "active" : "blocked",
      title: "5 · Enable controlled demo execution (optional)",
      desc: demoState.enabled ? `Demo execution ENABLED — capped limits active${demoState.readiness_expired ? " (readiness expired — re-verify)" : ""}.` : "Demo execution stays disabled until readiness passes and you acknowledge the hard demo limits. Observation alone is always safe.",
      action: !demoState.enabled && readinessPassed ? btn("Demo control", "#/trading/demo") : null,
    },
    {
      state: live.eligible ? "active" : "locked",
      title: "6 · Live governance",
      desc: live.eligible
        ? "All gates pass — explicit human confirmation is still required in Governance."
        : "LIVE is structurally locked. Demo results never unlock it; see Governance for the exact missing requirements.",
      action: h("button", { class: "btn ghost sm", onclick: () => navigate("#/governance/live") }, "Why is LIVE locked?"),
    },
  ];
  return steps.map((s) => h("div", { class: `journey-step ${s.state}` },
    h("div", { class: "j-step-mark", "aria-hidden": "true" }, s.state === "done" ? "✓" : ""),
    h("div", null, h("div", { class: "j-title" }, s.title), h("div", { class: "j-desc" }, s.desc)),
    s.action ? h("div", { class: "j-action" }, s.action) : null,
  ));

  function btn(label, href) {
    return h("button", { class: "btn sm", onclick: () => navigate(href) }, label);
  }
}
