/* QTS REPORTS — outcomes, not implementation.
   System: what QTS is doing now · Demo trading: real recorded counts ·
   Results: honest — no result is manufactured from missing or demo data. */

import { api } from "../api.js";
import { h, icon } from "../dom.js";
import { page, card, stat, emptyState, tech, banner } from "../components.js";
import { fmtInt, fmtUtc } from "../format.js";

export async function renderReports(root) {
  root.classList.add("operator-workspace", "reports");
  root.appendChild(page({
    crumb: "Reports",
    title: "Reports",
    answer: "What QTS is doing and what it has recorded. Missing data is reported as missing — never as zero.",
  }));

  const host = h("div", { class: "section stack" });
  root.appendChild(host);

  const [guide, journal] = await Promise.all([
    api.get("/api/demo/guide").catch(() => null),
    api.get("/api/demo/journal").catch(() => null),
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

  host.appendChild(h("details", null,
    h("summary", null, "Technical details"),
    tech({ guide, journal }, "Raw reports state")));
}
