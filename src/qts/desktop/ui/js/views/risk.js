/* Risk — safety cockpit: what can QTS do now and why, what blocked why what next explicit */

import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness, demoSentence } from "../operations.js";
import { h } from "../dom.js";
import {
  card, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner,
} from "../components.js";
import { fmtInt, humanKey, trunc, fmtAge } from "../format.js";
import { onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";

export async function renderRisk(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  const head = page({
    crumb: "Risk",
    title: "Risk",
    answer: h("b", null, "These are the limits. A clear risk reading is not permission to trade. Live trading stays locked."),
    actions: [h("button", { class: "btn", onclick: () => refresh(true) }, "Refresh")],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, "Loading risk authority…");
  const next = h("a", { class: "btn primary", href: "#/trading/demo" }, "Inspect DEMO authority");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / RISK"), activity),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT — what blocked, why, what next"), next, nextWhy)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section" });
  root.appendChild(host);

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["mode", "Environment / mode", s.mode.mode, s.mode.blurb],
      ["risk", "Risk authority", s.health?.risk ?? "UNAVAILABLE", "Independent numeric limits; mode restrictions compose on top. No mode relaxes a limit silently."],
      ["permission", "DEMO execution", s.permission, "Risk permission is separate from numeric limits; both must allow. DEMO vs LIVE unmistakable."],
      ["liveLabel", "LIVE governance", s.liveLabel, "Risk alone never unlocks LIVE. Locked styling unmistakable."],
    ];
    if (!factsBody.children.length) {
      for (const [key, title] of rows) {
        const st = h("span", { class: "badge neutral" }, "UNAVAILABLE");
        const det = h("span", null, "");
        const fresh = h("span", { class: "mono small" }, "");
        factCells[key] = { st, det, fresh };
        factsBody.appendChild(h("tr", null, h("th", { scope: "row" }, title), h("td", null, st), h("td", { class: "fact-detail" }, det), h("td", null, fresh)));
      }
    }
    for (const [key, , value, meaning] of rows) {
      const c = factCells[key];
      c.st.textContent = value;
      c.det.textContent = meaning;
      const resKey = key === "mode" || key === "risk" ? "health" : key === "permission" ? "demoState" : "live";
      const meta = store.data.resources[resKey];
      const f = meta ? freshness(meta, resKey) : { label: "UNAVAILABLE", current: false };
      c.fresh.textContent = `${f.label}${meta?.updatedAt ? ` · ${fmtAge(meta.updatedAt)}` : ""}`;
    }
    activity.textContent = store.data.health
      ? `${demoSentence(s.permission)} Live trading stays locked.`
      : "Risk status was not reported. Do not treat a blank reading as permission.";
    nextWhy.textContent = s.next.why;
  }

  let lastRisk = null;
  async function refresh(force = false) {
    try {
      const [risk] = await Promise.all([api.get("/api/risk")]);
      lastRisk = risk;
      if (force) await Promise.all(Object.keys(RESOURCES).map((k) => syncResource(k, { force: true })));
      render();
    } catch (e) {
      host.replaceChildren(errorBox({ what: "the risk authority could not be reached", known: "Until it answers, assume trading is blocked — fail-closed.", next: "Retry. Check backend logs. Risk authority is independent.", raw: e.message }));
    }
  }

  function render() {
    if (!lastRisk) return;
    renderFacts();
    const risk = lastRisk;
    const loss = risk.limits?.daily_loss_limit_usd;
    const lossLabel = loss == null || loss === "" ? "Not reported" : `$${loss}`;
    const kill = String(risk.limits?.kill_switch ?? "").toUpperCase();
    const killStopped = kill === "ACTIVE";
    const hostContent = h("div", { class: "stack" });

    hostContent.appendChild(card({
      title: "System Safety & Capital Protection",
      sub: "Structural protection · Zero real-capital exposure · Fail-closed risk controls",
      icon: "shield",
      actions: [h("span", { class: "badge locked lg" }, "REAL CAPITAL: OFF")],
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Live Trading Gate", value: "PERMANENTLY LOCKED", tone: "err", hint: "Zero real capital exposure", icon: "lock" }),
          stat({ label: "Kill switch", value: killStopped ? "On — orders stopped" : kill === "ARMED" ? "Ready" : "Not reported", tone: killStopped ? "err" : kill === "ARMED" ? "ok" : "neutral", hint: killStopped ? "The durable kill switch is stopping orders." : "Ready is not the same as an order being allowed.", icon: "shield" }),
          stat({ label: "Pre-trade checks", value: "Safety checks are on", tone: "ok", hint: "Every order is refused unless the full pre-trade gate passes. This card does not count the checks.", icon: "shield" }),
          stat({ label: "Max daily loss", value: lossLabel, hint: "From the risk authority. A missing limit is not a default dollar amount.", icon: "alert" }),
        ),
        h("p", { class: "text-dim small", style: { marginTop: "6px" } },
          "This page cannot place an order. Live trading stays locked. A clear risk reading is not permission to trade, and it is not a validated opportunity.",
        ),
      ),
    }));

    hostContent.appendChild(banner(
      risk.blocked ? "err" : "warn",
      risk.blocked ? `TRADING IS CURRENTLY BLOCKED — ${risk.blocked_reasons.length} reason(s)` : "TRADING IS NOT AUTHORIZED",
      risk.blocked
        ? `${risk.blocked_reasons.join(" · ")} — ${getContext().symbol}. Fix the listed reason, then check again. Live trading stays locked.`
        : `Risk limits are not blocking. That is not permission to trade. Live trading stays locked. There is no validated opportunity. Context ${getContext().symbol}.`,
      "shield",
    ));

    hostContent.appendChild(h("div", { class: "stat-grid" },
      stat({ label: "Mode", value: risk.mode ?? "UNAVAILABLE", hint: "no mode relaxes a limit silently" }),
      stat({ label: "Config hash", value: h("span", { class: "mono small" }, risk.config_hash ?? "—"), hint: "limits pinned to this hash — changes audited" }),
      stat({ label: "Open orders cap", value: fmtInt(risk.limits?.max_open_orders) }),
      stat({ label: "Order rate cap", value: `${fmtInt(risk.limits?.max_orders_per_minute)}/min` }),
      stat({ label: "Context", value: `${getContext().symbol} · ${getContext().timeframe}`, hint: "presentation only, never relaxes limits" }),
    ));

    const overrides = risk.overrides_applied ?? {};
    hostContent.appendChild(card({
      title: "Effective limits — dense, sortable, override source explicit — what limits, why", sub: "base authority values; deviated fields flagged", icon: "shield",
      body: table({
        columns: [
          { key: "limit", label: "Limit" },
          { key: "value", label: "Effective value", render: (r) => h("span", { class: "mono small" }, String(r.value)) },
          { key: "source", label: "Source", render: (r) => overrides[r.key] ? h("span", { class: "badge warn" }, `OVERRIDE · ${String(overrides[r.key]).toUpperCase().slice(0,24)}`) : h("span", { class: "meta" }, "BASE AUTHORITY") },
        ],
        rows: Object.entries(risk.limits ?? {}).map(([k, v]) => ({ limit: humanKey(k), key: k, value: String(v) })),
        empty: "No limits configured — trading stays blocked.",
        sortable: false,
        dense: true,
      }),
    }));

    hostContent.appendChild(h("div", { class: "grid-2" },
      card({ title: "Active vetoes — what blocked, why, what missing", sub: "why submission would be refused now", icon: "alert", body:
        risk.blocked_reasons.length
          ? h("ul", { class: "reason-list" }, risk.blocked_reasons.map((r) => h("li", null, r)))
          : emptyState({ icon: "check", title: "No active vetoes", desc: "No risk veto is active. That does not permit an order. Demo permission and the pre-trade gate still apply. Live trading stays locked." }),
      }),
      card({ title: "Known conditions — informational, not violations", sub: "scope and limitations", icon: "info", body:
        Object.keys(risk.explanations ?? {}).length
          ? kv(Object.entries(risk.explanations).map(([k, v]) => [k, h("span", { class: "small text-dim" }, trunc(String(v),130))]))
          : (risk.warnings ?? []).length
            ? h("ul", { class: "reason-list" }, risk.warnings.map((w) => h("li", null, w)))
            : emptyState({ icon: "info", title: "No advisory conditions" }),
      }),
    ));

    if ((risk.warnings ?? []).length) {
      hostContent.appendChild(card({ title: "Authority warnings — what to watch", icon: "alert", body:
        h("div", { class: "stack" }, risk.warnings.map((w) => banner("warn", "Warning", w, "alert"))),
      }));
    }

    hostContent.appendChild(h("details", null, h("summary", null, "Raw risk authority snapshot / technical evidence — summary → detail → raw"), tech(risk, "Raw risk authority")));
    host.replaceChildren(
      h("section", { class: "operator-section" }, h("h2", null, "Operating facts — per-source freshness"), h("div", { class: "tbl-wrap" }, h("table", { class: "tbl facts-table" }, h("thead", null, h("tr", null, ["Source","Reported state","Meaning / constraint","API freshness"].map((t) => h("th", { scope: "col" }, t)))), factsBody))),
      hostContent
    );
  }

  const off = store.on("resources", renderFacts);
  const offCtx = onContext(renderFacts);
  onDispose(root, () => { off(); offCtx(); });
  await refresh();
}
