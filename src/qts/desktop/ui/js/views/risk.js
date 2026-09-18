/* Risk — safety cockpit: what can QTS do now and why, what blocked why what next explicit */

import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness } from "../operations.js";
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
  const ctx = getContext();
  const head = page({
    crumb: "Risk",
    title: "Risk Center",
    answer: h("b", null, `Primary question: what can QTS do right now — and why? Risk authority is independent from mode and execution permission. Context ${ctx.symbol} syncs, never relaxes limits. DEMO vs LIVE unmistakable.`),
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
    activity.textContent = `${s.mode.mode} · DEMO ${s.permission} · LIVE ${s.liveLabel} · context ${getContext().symbol} — ${store.data.health ? "risk evaluated" : "UNAVAILABLE"}`;
    nextWhy.textContent = `${s.next.why} Context ${getContext().symbol} syncs, never relaxes limits.`;
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
    const hostContent = h("div", { class: "stack" });

    hostContent.appendChild(banner(
      risk.blocked ? "err" : "ok",
      risk.blocked ? `TRADING IS CURRENTLY BLOCKED — ${risk.blocked_reasons.length} reason(s) — what blocked, why` : "TRADING IS PERMITTED — WITHIN THE LIMITS BELOW — what allowed, why",
      risk.blocked ? `${risk.blocked_reasons.join(" · ")} — context ${getContext().symbol} — fix what missing, then re-verify.` : `Every check evaluated continuously; any violation blocks instantly and is audited. Context ${getContext().symbol} syncs, never relaxes limits. DEMO vs LIVE unmistakable.`,
      risk.blocked ? "shield" : "check",
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
          : emptyState({ icon: "check", title: "No active vetoes", desc: "No blocking condition currently triggered. Trading permitted within limits, but DEMO permission and mode still apply. LIVE remains LOCKED." }),
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
