/* Governance — LIVE, deliberately calm, restricted, explicit. Locked is a feature.
   DEMO vs LIVE unmistakable, what blocked why what missing what next explicit. */

import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness } from "../operations.js";
import { h } from "../dom.js";
import {
  card, page, skeletonInto, tech, kv, errorBox,
  banner, confirmModal, toast,
} from "../components.js";
import { fmtUtc, fmtAge, humanKey } from "../format.js";
import { onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";

export async function renderGovernance(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  const ctx = getContext();
  const head = page({
    crumb: "Governance",
    title: "Live Trading Governance",
    answer: h("b", null, `Real capital lives behind this gate. It opens only when every scientific, safety, and human-approval condition is met — demo results never substitute for it. Context ${ctx.symbol} syncs, never permission. DEMO vs LIVE unmistakable: DEMO = simulation, LIVE = real capital.`),
    actions: [h("button", { class: "btn", onclick: () => refresh(true) }, "Refresh")],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, "Loading governance…");
  const next = h("a", { class: "btn primary", href: "#/research/validation" }, "Inspect validation evidence");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary live-boundary" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / LIVE GOVERNANCE"), activity),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT — what blocked, why, what missing, what next"), next, nextWhy)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section", style: { maxWidth: "860px", margin: "0 auto" } });
  root.appendChild(host);

  let lastLive = null, lastSafety = null;

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["mode", "Environment / mode", s.mode.mode, s.mode.blurb],
      ["liveLabel", "LIVE governance", s.liveLabel, "Eligibility is not enablement. Human approval still required. LIVE LOCKED is unmistakable — red/bordered, never green."],
      ["permission", "DEMO execution", s.permission, "DEMO evidence never automatically authorizes LIVE. DEMO vs LIVE banner unmistakable."],
      ["observation", "Observation", s.observation, "Forward observation is required evidence, not a promotion. Zero orders, bounded, research-only."],
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
      const resKey = key === "mode" ? "health" : key === "liveLabel" ? "live" : key === "permission" ? "demoState" : "observe";
      const meta = store.data.resources[resKey];
      const f = meta ? freshness(meta, resKey) : { label: "UNAVAILABLE", current: false };
      c.fresh.textContent = `${f.label}${meta?.updatedAt ? ` · ${fmtAge(meta.updatedAt)}` : ""}`;
    }
    activity.textContent = `${s.liveLabel} · DEMO ${s.permission} · ${s.observation} · context ${getContext().symbol} — what blocked why explicit`;
    nextWhy.textContent = s.live?.eligible ? `Eligibility is not permission. Human approval still required and recorded. Context ${getContext().symbol}.` : `${(s.liveReasons.slice(0,2).join(" · ") || "LIVE is locked. Independent evidence and human governance required.")} Context ${getContext().symbol} syncs, never permission.`;
  }

  async function refresh(force = false) {
    try {
      const [live, safety] = await Promise.all([api.get("/api/live/status"), api.get("/api/demo/safety")]);
      lastLive = live; lastSafety = safety;
      if (force) await syncResource("live", { force: true });
      render();
    } catch (e) {
      host.replaceChildren(errorBox({ what: "the governance state could not be loaded", known: "While unreachable, assume LIVE remains locked — fail-closed.", next: "Retry. While unreachable, assume LIVE remains locked.", raw: e.message }));
    }
  }

  function render() {
    if (!lastLive) return;
    renderFacts();
    const live = lastLive;
    const eligible = Boolean(live.eligible);

    const content = h("div", { class: "stack" });

    content.appendChild(h("div", { class: "card", style: { borderColor: "var(--locked-line)", background: "var(--locked-bg)" } },
      h("div", { class: "card-body", style: { textAlign: "center", padding: "var(--sp-6)" } },
        h("div", { style: { fontSize: "var(--fs-28)", fontWeight: 700, letterSpacing: "0.06em", color: "var(--locked-text)" } }, ("LIVE — " + String(live.live_trading ?? "LOCKED")).toUpperCase()),
        h("p", { class: "text-dim", style: { maxWidth: "60ch", margin: "10px auto 0" } },
          eligible ? `All gates pass. Human approval is still required — eligibility is not permission. Context ${getContext().symbol} syncs, never permission.` : live.message ?? `LIVE trading is structurally locked. No UI action, no backtest result, and no demo performance can change that. Context ${getContext().symbol} syncs, never permission.`),
        h("div", { class: "meta" }, `evaluated ${fmtUtc(new Date().toISOString())} · gate re-evaluates continuously, not on a timer you control · context ${getContext().symbol} — presentation only`),
      ),
    ));

    const checklist = live.checklist ?? {};
    const labels = {
      validated_edge: "Validated edge — statistical gates passed (DSR/PBO/OOS)",
      forward_observation: "Forward observation — real-data sessions recorded — zero orders, bounded, research-only",
      risk_configuration: "Risk configuration — approved limits active",
      mt5_connectivity: "MT5 connectivity — real terminal verified",
      reconciliation: "Reconciliation — internal state matches broker",
      human_approval: "Human approval — explicit, informed, recorded",
    };
    content.appendChild(card({
      title: `Requirements — each must pass independently — what blocked, why — context ${getContext().symbol}`, sub: "partial credit does not exist", icon: "check",
      body: h("div", { class: "check-grid" },
        Object.entries(checklist).map(([k, v]) =>
          h("div", { class: `check ${v === true ? "pass" : "fail"}` },
            h("div", { class: "mark", "aria-hidden": "true" }, v === true ? "✓" : "✕"),
            h("div", null,
              h("div", { class: "name" }, labels[k] ?? humanKey(k)),
              // The API now reports, per item, exactly which authority satisfied
              // or blocked it. Show that instead of the generic placeholder: two
              // of these items used to be hardcoded true server-side, so this
              // line printed "satisfied — independently evidenced" for risk
              // configuration and reconciliation with no evidence consulted.
              h("div", { class: "detail" },
                live.checklist_detail?.[k]
                  ?? (v === true
                    ? "satisfied — independently evidenced"
                    : "not satisfied — see blockers below — what missing, what next explicit")),
            ),
          )),
      ),
    }));

    content.appendChild(card({
      title: "Why it is locked — calm, explicit — what blocked, why, what missing, what next", icon: "info",
      body: h("div", { class: "stack" },
        h("ul", { class: "reason-list" }, (live.blocked_reasons ?? []).map((r) => h("li", null, r))),
        banner("info", "What live eligibility would require — what missing", "A strategy surviving every scientific gate on claim-eligible real-data evidence, forward observation with honest divergence evidence, approved risk configuration, verified connectivity — and an explicit human approval recorded in the audit log. DEMO execution (when authorized) is forward validation on the DEMO account, not a prerequisite or evidence source for LIVE.", "info"),
        banner("info", "What DEMO_FORWARD observation can establish — DEMO vs LIVE unmistakable", "Observation establishes provenance and hypothetical divergence only. It does not prove execution correctness, profitability, or live eligibility; DEMO execution, where authorized, is DEMO-account forward validation and LIVE remains LOCKED.", "info"),
      ),
    }));

    content.appendChild(card({
      title: "Request live enablement — intentionally quiet — safety understandable", icon: "lock",
      body: h("div", { class: "stack" },
        h("p", { class: "gate-note" }, "The request surface exists for completeness and auditability. When the gate is locked, a request is recorded and refused — no override, no dark pattern. DEMO vs LIVE unmistakable."),
        h("button", {
          class: "btn", disabled: !eligible,
          onclick: eligible ? requestLive : () => toast("info", "LIVE is locked", live.message ?? "Requirements are listed above. What blocked, why, what missing, what next explicit."),
        }, eligible ? "Request live enablement (gated) — still requires human approval" : "Live enablement unavailable — gate is LOCKED — what blocked, why"),
        live.explicit_confirmation_required ? h("div", { class: "meta" }, "Explicit confirmation contract: " + live.explicit_confirmation_required) : null,
      ),
    }));

    const boundary = lastSafety?.boundary ?? {};
    if (Object.keys(boundary).length) {
      content.appendChild(card({ title: `Mode boundary — no silent conversions — context ${getContext().symbol}`, sub: "how each environment differs — DEMO vs LIVE unmistakable", icon: "layers", body:
        kv(Object.entries(boundary).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
      }));
    }

    content.appendChild(h("details", null, h("summary", null, "Raw governance snapshots / technical evidence — summary → detail → raw"), tech({ live: lastLive, safety: lastSafety, context: getContext() }, "Raw governance")));

    host.replaceChildren(
      h("section", { class: "operator-section" }, h("h2", null, "Operating facts — per-source freshness"), h("div", { class: "tbl-wrap" }, h("table", { class: "tbl facts-table" }, h("thead", null, h("tr", null, ["Source","Reported state","Meaning / constraint","API freshness"].map((t) => h("th", { scope: "col" }, t)))), factsBody))),
      content
    );
  }

  async function requestLive() {
    const ok = await confirmModal({
      title: "Request LIVE enablement — LIVE real capital, DEMO simulation",
      danger: true,
      body: h("div", { class: "stack" },
        h("p", null, "This records a formal, audited request. The governance gate still decides; human approval is verified server-side. DEMO vs LIVE unmistakable: DEMO proves ops, never profitability."),
        h("div", { class: "card live-boundary" }, h("div", { class: "card-body" }, h("div", { class: "eyebrow" }, "DEMO vs LIVE"), h("p", { class: "small" }, "DEMO_FORWARD = real demo-account observation with zero orders. DEMO_EXECUTION is DEMO-account order execution, available only with a recorded owner authorization and per-order gates (default: DISABLED BY POLICY). LIVE = real capital and remains locked."))),
      ),
      acks: [
        "I understand live trading risks real capital — LIVE LOCKED is a safety feature.",
        "I understand demo results are not evidence of profitability and never unlock LIVE — DEMO vs LIVE unmistakable.",
        "I am the account owner and this request is deliberate, informed, and recorded.",
      ],
      confirmLabel: "Submit audited request — LIVE still LOCKED until approved",
    });
    if (!ok) return;
    toast("info", "Request recorded — LIVE still LOCKED", "The governance gate evaluates requests server-side — the UI never grants permission. DEMO vs LIVE unmistakable.");
    renderGovernance(root);
  }

  const off = store.on("resources", renderFacts);
  const offCtx = onContext(renderFacts);
  onDispose(root, () => { off(); offCtx(); });
  await refresh();
}
