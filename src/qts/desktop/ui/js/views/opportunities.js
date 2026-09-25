/* Opportunities — user-facing research status.
   A hypothesis, a candidate, and an authorized trade are different things.
   Nothing here is a BUY/SELL recommendation unless governance has authorized it.
   Current certified conclusion remains NO_VALIDATED_EDGE. */

import { api } from "../api.js";
import { h, icon } from "../dom.js";
import { page, card, stat, emptyState, errorBox } from "../components.js";

const EDGE = "NO_VALIDATED_EDGE";

function humanState(row) {
  const decision = String(row?.decision || row?.lifecycle_state || "").toUpperCase();
  if (decision === "VALIDATED" || decision === "LIVE_ELIGIBLE") {
    return { label: "Blocked", detail: "A passing research record is not permission to trade. Live trading is locked.", tone: "warn" };
  }
  if (decision.includes("DEMO")) {
    return { label: "Demo observation", detail: "Forward observation only. Demo results are not a validated edge.", tone: "neutral" };
  }
  if (decision.includes("CANDIDATE")) {
    return { label: "Candidate", detail: "Under research. Not a trading opportunity.", tone: "warn" };
  }
  if (decision.includes("RESEARCH") || decision.includes("DISCOVERY")) {
    return { label: "Researching", detail: "Still being tested. Not a trading opportunity.", tone: "neutral" };
  }
  if (!decision || decision === "NONE" || decision === "BLOCKED" || decision.includes("NO_TRADE") || decision.includes("REJECT")) {
    return { label: "Blocked", detail: "Research did not authorize this record.", tone: "err" };
  }
  return { label: "No opportunity", detail: "This record is research evidence, not a trade.", tone: "neutral" };
}

export async function renderOpportunities(root) {
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Opportunities",
    title: "Opportunities",
    answer: "QTS shows a trading opportunity only when research and governance both authorize it. They do not.",
  }));

  const host = h("div", { class: "section" });
  root.appendChild(host);
  host.appendChild(h("div", { class: "stat-grid product-questions" },
    stat({ label: "Research conclusion", value: "No validated opportunity", hint: EDGE, tone: "warn", icon: "scale" }),
    stat({ label: "Authorized trades", value: "None", hint: "Live trading is locked", tone: "ok", icon: "lock" }),
    stat({ label: "What this means", value: "Keep observing", hint: "Do not treat a hypothesis as a signal", icon: "info" }),
  ));

  let strategies = [];
  try {
    strategies = await api.get("/api/strategies");
  } catch (e) {
    host.appendChild(errorBox({ what: "strategy records could not be loaded", next: "Retry. Missing records are not a hidden opportunity.", raw: e.message }));
    return;
  }
  if (!Array.isArray(strategies) || strategies.length === 0) {
    host.appendChild(emptyState({
      icon: "scale",
      title: "No opportunity",
      desc: "There is no validated trading opportunity. Research can continue. It cannot authorize a trade from this screen.",
    }));
    return;
  }

  const list = h("div", { class: "stack" });
  for (const row of strategies) {
    const state = humanState(row);
    list.appendChild(card({
      title: row.name || row.strategy_id || "Research record",
      sub: state.detail,
      icon: "flask",
      actions: [h("span", { class: `badge ${state.tone}` }, state.label)],
      body: h("p", { class: "small text-dim" },
        "This is a research record. It is not a buy or sell instruction. ",
        row.strategy_id ? `Reference ${row.strategy_id}.` : "",
      ),
    }));
  }
  host.appendChild(h("section", { class: "operator-section" },
    h("h2", null, "Research records"),
    h("p", { class: "small text-dim" }, "Shown so you can see what has been studied. None of these cards is a trading recommendation."),
    list,
  ));
  host.appendChild(h("p", { class: "small text-dim" }, icon("lock", 12), " Live trading remains locked. Demo observation is not evidence of an edge."));
}
