/* ============================================================
   VIEW: RISK — the safety cockpit
   Primary question: WHAT CAN QTS DO RIGHT NOW — and WHY?
   ============================================================ */
import { api } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, checkGrid,
} from "../components.js";
import { fmtNum, fmtInt, humanKey, trunc } from "../format.js";
import { modeInfo } from "../status.js";

export async function renderRisk(root) {
  skeletonInto(root, "stats");
  const head = page({
    crumb: "Risk",
    title: "Risk Center",
    actions: [h("button", { class: "btn", onclick: () => renderRisk(root) }, icon("refresh", 14), "Refresh")],
    body: null,
  });
  root.appendChild(head);
  const host = h("div", { class: "section" }); root.appendChild(host);

  let risk = null;
  try { risk = await api.get("/api/risk"); }
  catch (e) {
    clear(host);
    host.appendChild(errorBox({ what: "the risk authority could not be reached", next: "Retry. Until it answers, assume trading is blocked.", raw: e.message }));
    return;
  }

  const mode = modeInfo(risk.mode);

  /* --- the primary answer --- */
  host.appendChild(banner(
    risk.blocked ? "err" : "ok",
    risk.blocked ? "TRADING IS CURRENTLY BLOCKED" : "TRADING IS PERMITTED — WITHIN THE LIMITS BELOW",
    risk.blocked
      ? `${risk.blocked_reasons.length} active reason(s): ${risk.blocked_reasons.join(" · ")}`
      : "Every check below is evaluated continuously; any violation blocks instantly and is audited.",
    risk.blocked ? "shield" : "check",
  ));

  host.appendChild(h("div", { class: "stat-grid", style: { marginTop: "var(--sp-4)" } },
    stat({ label: "Mode", value: mode.mode, tone: mode.tone === "neutral" ? "neutral" : mode.tone, hint: mode.canSubmit === true ? "may submit broker orders" : "no broker submission in this mode", icon: "layers" }),
    stat({ label: "Config hash", value: h("span", { class: "mono" }, risk.config_hash ?? "—"), hint: "limits are pinned to this configuration — changes are audited", icon: "fileCheck" }),
    stat({ label: "Open orders cap", value: fmtInt(risk.limits?.max_open_orders), icon: "clock" }),
    stat({ label: "Order rate cap", value: `${fmtInt(risk.limits?.max_orders_per_minute)}/min`, icon: "activity" }),
  ));

  /* --- limits table with provenance --- */
  const overrides = risk.overrides_applied ?? {};
  host.appendChild(card({
    title: "Effective limits", sub: "base authority values; deviated fields are flagged with their override source", icon: "sliders",
    actions: [h("span", { class: "meta" }, "loosening any limit requires explicit risk-approval or acknowledgment — never a UI toggle")],
    body: table({
      columns: [
        { key: "limit", label: "Limit" },
        { key: "value", label: "Effective value", render: (r) => h("span", { class: "num primary-cell mono" }, String(r.value)) },
        { key: "source", label: "Source", render: (r) => overrides[r.key]
          ? badge({ tone: "warn", label: `OVERRIDE · ${String(overrides[r.key]).toUpperCase().slice(0, 24)}`, mark: "▲" })
          : h("span", { class: "meta" }, "BASE AUTHORITY") },
      ],
      rows: Object.entries(risk.limits ?? {}).map(([k, v]) => ({ limit: humanKey(k), key: k, value: String(v) })),
      empty: "No limits configured — trading stays blocked.",
      sortable: false,
    }),
  }));

  /* --- vetoes / explanations --- */
  const expl = risk.explanations ?? {};
  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Active vetoes", sub: "why a specific submission would be refused right now", icon: "alert", body:
      risk.blocked_reasons.length
        ? h("ul", { class: "gate-list" }, risk.blocked_reasons.map((r) => h("li", null, r)))
        : emptyState({ icon: "check", title: "No active vetoes", desc: "No blocking condition is currently triggered." }),
    }),
    card({ title: "Known conditions", sub: "informational states that are not violations", icon: "info", body:
      Object.keys(expl).length
        ? kv(Object.entries(expl).map(([k, v]) => [k, h("span", { class: "small text-dim" }, trunc(String(v), 130))]))
        : (risk.warnings ?? []).length
          ? h("ul", { class: "gate-list" }, risk.warnings.map((w) => h("li", null, w)))
          : emptyState({ icon: "info", title: "No advisory conditions" }),
    }),
  ));

  if ((risk.warnings ?? []).length) {
    host.appendChild(card({ title: "Authority warnings", icon: "alert", body:
      h("div", { class: "stack" }, risk.warnings.map((w) => banner("warn", "Warning", w, "alert"))),
    }));
  }

  host.appendChild(card({ title: "Mode restrictions", icon: "lock", body:
    h("div", { class: "stack" },
      banner("info", mode.mode, mode.blurb, "info"),
      h("p", { class: "gate-note" }, "Mode restrictions compose with the numeric limits: DEMO caps are tighter than base authority, and LIVE requires the governance gate — no mode or UI action relaxes a limit silently."),
    ),
  }));

  host.appendChild(h("div", { class: "mt-4" }, tech(risk, "Raw risk authority snapshot")));
}
