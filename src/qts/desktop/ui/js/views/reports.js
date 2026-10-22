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

  const [guide, journal, measuredCosts, lhSummary, forwardEvidence] = await Promise.all([
    api.get("/api/demo/guide").catch(() => null),
    api.get("/api/demo/journal").catch(() => null),
    api.get("/api/demo/measured-costs").catch(() => null),
    api.get("/api/research/longhistory-summary").catch(() => null),
    api.get("/api/research/edgelab-forward").catch(() => null),
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
          hint: "A real broker quote is necessary. Research assumptions and archived spreads are not current execution costs.",
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
          hint: "Measured only from actual DEMO fills with reliable requested and executed prices.",
        }),
        stat({
          label: "Overnight swap (long)",
          value: fnLive.status === "MEASURED" ? `${fnLive.swap_long_usd_per_lot_night} USD/lot/night` : "UNMEASURED",
          tone: fnLive.status === "MEASURED" ? "ok" : "warn",
          hint: "Symbol swap specifications are indicative; actual charged financing requires broker deal evidence.",
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

  // ---- Research evidence, without synthetic current positions ----------------
  const historical = lhSummary?.forward_champions_state?.champions || {};
  const positions = Object.entries(historical)
    .filter(([, entry]) => entry && entry.as_of && entry.position_label)
    .map(([name, entry]) => `${name}: ${entry.position_label} on ${entry.as_of} (historical only)`);
  const active = forwardEvidence?.active_candidates || [];
  const observations = forwardEvidence?.observations;
  const validated = forwardEvidence?.validated_any === true;
  host.appendChild(card({
    title: "Strategy evidence — research only", icon: "eye",
    sub: "Historical backtests are not today's broker trade signals.",
    body: h("div", { class: "stack" },
      kv([
        ["Validated executable edge", validated ? "See independent validation evidence before using" : "NONE — no authorized trading strategy"],
        ["Forward-research candidates", forwardEvidence ? String(active.length) : "UNAVAILABLE"],
        ["Recorded candidate observations", Number.isFinite(Number(observations)) ? String(observations) : "UNAVAILABLE"],
        ["Old research snapshots", positions.length ? positions.join("; ") : "No attributable dated snapshots"],
        ["Current XAUUSD@ trade signal", "NOT VALIDATED — historical LONG/SHORT states are not live instructions"],
        ["Proof required", "Genuinely new timestamped evidence, independent tests and measured broker spread, commission, slippage and swap"],
      ]),
      h("p", { class: "small text-dim" },
        "The research engine may display historical hypotheses. QTS does not infer today's position, profit or approval from an old saved report."),
    ),
  }));


  host.appendChild(h("details", null,
    h("summary", null, "Technical details"),
    tech({ guide, journal, measuredCosts, lhSummary, forwardEvidence }, "Raw reports state")));
}
