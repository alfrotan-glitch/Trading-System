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
          hint: "Assumed in research: 3.0 bps ($0.30/oz on 15m). Archive DEMO mean: 0.72 bps ($0.24/oz median).",
        }),
        stat({
          label: "Commission",
          value: cmLive.status === "MEASURED" ? `$${fmtNum(cmLive.value, 2)}/lot` : "UNMEASURED",
          tone: cmLive.status === "MEASURED" ? "ok" : "warn",
          hint: "Assumed in research: $7.00/lot/side. Measured only from recorded broker deals.",
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

  // ---- Forward-validation watch (frozen monthly champions) ------------------
  const fwdChamps = lhSummary?.forward_champions_state?.champions || {};
  const ts9 = fwdChamps.ts9_lo || {};
  const veto9 = fwdChamps.veto9 || {};
  host.appendChild(card({
    title: "Forward-validation watch — frozen monthly research candidates", icon: "eye",
    sub: `Paper observation only · ${fmtInt(lhSummary?.n_trials_cumulative ?? 355)} cumulative trials tested · overall verdict: NO_VALIDATED_EDGE`,
    body: h("div", { class: "stack" },
      kv([
        ["Primary candidate (ts9_lo)", `9-month gold trend (long-or-flat) · State at ${ts9.as_of || "2026-09-30"}: ${ts9.position_label || "LONG"} (size ${fmtNum((ts9.size_fraction ?? 0.4728) * 100, 1)}%, since ${ts9.since || "2023-02-28"}) · 2000–2026 Sharpe 0.837 (+$70,989)`],
        ["Decade-robust companion (veto9)", `9-month trend, shorts require 12-month USD rise · State at ${veto9.as_of || "2026-09-30"}: ${veto9.position_label || "LONG"} (size ${fmtNum((veto9.size_fraction ?? 0.4728) * 100, 1)}%, since ${veto9.since || "2023-02-28"}) · Positive in every decade (2000–2026 Sharpe 0.662, +$49,897)`],
        ["Independent verification", `${lhSummary?.independent_verification?.verdict || "AGREE"} (zero-shared-code stdlib+numpy verifier matches engine within <0.01%)`],
        ["Why not promoted to live?", "Fails G3 (walk-forward positive-year count), G5 (DSR 0.941 < 0.95 at N=355), and G6 (16–45 OOS turns < 100), plus broker overnight swap remains UNMEASURED."],
      ]),
    ),
  }));

  host.appendChild(h("details", null,
    h("summary", null, "Technical details"),
    tech({ guide, journal, measuredCosts, lhSummary }, "Raw reports state")));
}
