/* QTS REPORTS — outcomes, not implementation.
   System: what QTS is doing now · Demo trading: real recorded counts ·
   Results: honest — no result is manufactured from missing or demo data. */

import { api } from "../api.js";
import { h, icon } from "../dom.js";
import { page, card, stat, emptyState, tech, banner, kv, toast } from "../components.js";
import { fmtInt, fmtNum, fmtUtc } from "../format.js";

export async function renderReports(root) {
  root.classList.add("operator-workspace", "reports");
  root.appendChild(page({
    crumb: "Reports",
    title: "Reports",
    answer: "What QTS is doing and what it has recorded. Missing data is reported as missing — never as zero.",
  }));

  const host = h("div", { class: "section stack" });
  root.appendChild(host);

  const [guide, journal, measuredCosts, lhSummary] = await Promise.all([
    api.get("/api/demo/guide").catch(() => null),
    api.get("/api/demo/journal").catch(() => null),
    api.get("/api/demo/measured-costs").catch(() => null),
    api.get("/api/research/longhistory-summary").catch(() => null),
  ]);

  // ---- System -----------------------------------------------------------
  host.appendChild(card({
    title: "System", icon: "info",
    sub: "The current state of QTS, in plain language",
    body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({ label: "Status", value: guide?.headline || "Unavailable", tone: guide?.status === "ready" ? "ok" : guide?.status === "stopped" ? "err" : "neutral", icon: "activity" }),
        stat({ label: "Demo account", value: guide?.connection?.connected ? "Connected" : "Not connected", tone: guide?.connection?.connected ? "ok" : "neutral", icon: "shield" }),
        stat({ label: "Trading", value: guide?.can_trade ? "Ready" : "Not ready", tone: guide?.can_trade ? "ok" : "neutral", icon: "layers" }),
        stat({ label: "Live trading", value: "Locked", tone: "ok", icon: "lock", hint: "Real money can never be used." }),
      ),
      guide?.reason ? h("p", { class: "small text-dim" }, guide.reason) : null),
  }));

  // ---- Demo trading -------------------------------------------------------
  const sum = journal?.summary;
  host.appendChild(card({
    title: "Demo trading", icon: "layers",
    sub: "Recorded demo activity — real counts only",
    body: sum
      ? h("div", { class: "stat-grid" },
          stat({ label: "Demo orders recorded", value: fmtInt(sum.orders), icon: "fileCheck" }),
          stat({ label: "Open demo positions", value: fmtInt(sum.open_orders), icon: "activity" }),
          stat({ label: "Unreconciled", value: fmtInt(sum.unreconciled), tone: sum.unreconciled > 0 ? "warn" : "ok", icon: "scale", hint: "Orders QTS and the broker have not yet agreed on." }),
        )
      : emptyState({ icon: "fileCheck", title: "No demo activity recorded", desc: "QTS has not recorded a demo order yet. Counts appear here only after real recorded activity." }),
  }));

  // ---- Execution costs & financing (Measured vs Assumed) ------------------
  const avm = measuredCosts?.assumed_vs_measured?.components || {};
  const spLive = avm.spread?.live_terminal || {};
  const cmLive = avm.commission?.live_terminal || {};
  const slLive = avm.slippage?.live_terminal || {};
  const fnLive = avm.financing?.live_terminal || {};
  const claimOk = Boolean(measuredCosts?.measured_cost_model?.claim_eligible);

  const probeBtn = h("button", {
    class: "btn sm",
    onclick: async () => {
      probeBtn.disabled = true;
      try {
        await api.post("/api/demo/measure-symbol-terms", {});
        toast("ok", "Broker symbol terms recorded", "Read-only probe completed — zero orders submitted.");
        host.parentElement.replaceChildren();
        await renderReports(root);
      } catch (e) {
        const d = e?.body?.detail;
        const msg = (typeof d === "object" && d !== null) ? (d.detail || d.headline) : (d || e.message);
        toast("warn", "Could not read live broker terms", String(msg || "Open MetaTrader 5 on Windows and sign in to your Demo account."));
      } finally {
        probeBtn.disabled = false;
      }
    },
  }, icon("refresh", 13), "Check broker symbol terms (read-only)");

  host.appendChild(card({
    title: "Execution costs & financing — measured vs assumed", icon: "scale",
    sub: claimOk
      ? "All 4 cost components are measured from broker evidence."
      : "Unmeasured broker costs stay explicitly UNMEASURED — never assumed zero.",
    actions: [probeBtn],
    body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({
          label: "Spread (live terminal)",
          value: spLive.status === "MEASURED" ? `$${fmtNum(spLive.value, 2)}/oz` : "UNMEASURED",
          tone: spLive.status === "MEASURED" ? "ok" : "warn",
          hint: "Research assumption: 3.0 bps ($0.30/oz on 15m). Historical quote archives are not this account’s fill costs.",
        }),
        stat({
          label: "Commission",
          value: cmLive.status === "MEASURED" ? `$${fmtNum(cmLive.value, 2)}/lot` : "UNMEASURED",
          tone: cmLive.status === "MEASURED" ? "ok" : "warn",
          hint: "Research assumption: $7.00/lot/side. Published broker specifications are references, not account measurements.",
        }),
        stat({
          label: "Slippage",
          value: slLive.status === "MEASURED" ? `${fmtNum(slLive.avg_abs_slippage_bps, 2)} bps` : "UNMEASURED",
          tone: slLive.status === "MEASURED" ? "ok" : "warn",
          hint: "Assumed in research: 1.0 bps/side. Measured only from realized demo fills.",
        }),
        stat({
          label: "Overnight swap (long)",
          value: fnLive.status === "MEASURED" ? `${fnLive.swap_long_usd_per_lot_night} USD/lot/night` : "UNMEASURED",
          tone: fnLive.status === "MEASURED" ? "ok" : "warn",
          hint: "Assumed in research G9: 0.25 bps/day. Break-even: ~3.35 bps/day (ts9_lo) / ~2.38 bps/day (veto9).",
        }),
      ),
      h("p", { class: "small text-dim" },
        measuredCosts?.champion_reevaluation?.decision_summary
          || "Connect your MetaTrader 5 Demo terminal and press “Check broker symbol terms” to measure directional swap and current spread without placing any order."),
    ),
  }));

  // ---- Results --------------------------------------------------------------
  host.appendChild(card({
    title: "Results", icon: "scale",
    sub: "Performance is reported only when it is real",
    body: h("div", { class: "stack" },
      banner("info", "Not enough data to report a result.",
        "There is no validated trading opportunity, and demo activity is practice — it is never reported as a real result. QTS will not show a number it does not have.", "info"),
      h("p", { class: "small text-dim" }, "Research conclusion: no validated edge. Live trading stays locked. Real-capital exposure is $0."),
      h("a", { class: "btn sm", href: "#/advanced/evidence" }, "See the evidence"),
    ),
  }));

  // ---- Current research status ---------------------------------------------
  const recentScreens = lhSummary?.recent_screens || [];
  const champions = lhSummary?.frozen_champions || {};
  const sahmScreen = recentScreens.find((item) => item.hypothesis_id === "LH-XAUUSD-SAHM-U3-GATE-2026-10-20");
  const screenNames = {
    "LH-XAUUSD-YC-INVERSION-GATE-2026-10-19": "Yield-curve inversion",
    "LH-XAUUSD-GOLD-CALENDAR-SEASONALITY-2026-10-19": "Gold calendar seasonality",
    "LH-XAUUSD-SAHM-U3-GATE-2026-10-20": "Sahm/U-3 labor-stress gate",
  };
  const recentScreenText = recentScreens.map((item) => {
    const name = screenNames[item.hypothesis_id] || item.hypothesis_id;
    const count = item.cumulative_trials == null ? "" : ` (N=${fmtInt(item.cumulative_trials)})`;
    return `${name}: ${item.status}${count}`;
  }).join("; ");
  const sahmDataLimit = sahmScreen
    ? [
        sahmScreen.source_vintage_status ? "U-3 is a revised historical snapshot without point-in-time vintages." : null,
        sahmScreen.post_1999_gold_prices_accessed === false ? "No post-1999 Gold price values were accessed." : null,
        sahmScreen.post_1999_u3_values_accessed === false ? "No post-1999 U-3 values were accessed." : null,
        sahmScreen.holdout_accessed === false ? "The locked holdout remains untouched." : null,
      ].filter(Boolean).join(" ")
    : null;
  host.appendChild(card({
    title: "Research status — frozen candidates", icon: "eye",
    sub: `Paper-only · ${fmtInt(lhSummary?.n_trials_cumulative ?? 362)} cumulative trials · verdict: NO_VALIDATED_EDGE`,
    body: h("div", { class: "stack" },
      kv([
        ["ts9_lo", `${champions.ts9_lo?.rule || "9-month Gold trend, long-or-flat"} · research-only; not validated`],
        ["veto9", `${champions.veto9?.rule || "9-month Gold trend with USD-conditioned shorts"} · research-only; not validated`],
        ["Promotion / LIVE", "No candidate is promoted. LIVE remains locked; passing a readiness check does not grant permission."],
        ["Historical performance", "Archived figures are not recalculated or shown as current performance in this status view."],
        ["Independent calculation audit", `${lhSummary?.independent_verification?.verdict || "UNAVAILABLE"} · arithmetic reproduction only; not evidence of profitability.`],
        ["Recent preregistered screens", recentScreenText || "—"],
        ["Sahm/U-3 data limitation", sahmDataLimit || "No current Sahm/U-3 evidence available."],
      ]),
    ),
  }));

  host.appendChild(h("details", null,
    h("summary", null, "Technical details"),
    tech({ guide, journal, measuredCosts, lhSummary }, "Raw reports state")));
}
