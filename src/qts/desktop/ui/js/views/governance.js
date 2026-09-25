/* Governance — LIVE, deliberately calm, restricted, explicit. Locked is a feature.
   DEMO vs LIVE unmistakable, what blocked why what missing what next explicit. */

import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness, demoSentence } from "../operations.js";
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
  const head = page({
    crumb: "Governance",
    title: "Live trading",
    answer: h("b", null, "Live trading stays locked. This page cannot open it, and demo results cannot open it. Demo is a practice account. Live would be real money."),
    actions: [h("button", { class: "btn", onclick: () => refresh(true) }, "Refresh")],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, "Loading live status…");
  const next = h("a", { class: "btn primary", href: "#/risk" }, "See the limits");
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
    activity.textContent = `${demoSentence(s.permission)} Live trading stays locked.`;
    nextWhy.textContent = "This page cannot open live trading. A passed check is still not permission.";
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
          eligible ? "A readiness report can pass its structural checks. That is not permission, and this page still cannot open live trading." : live.message ?? "Live trading is locked. No button, backtest, or demo result on this page can change that."),
        h("div", { class: "meta" }, `evaluated ${fmtUtc(new Date().toISOString())} · gate re-evaluates continuously, not on a timer you control · context ${getContext().symbol} — presentation only`),
      ),
    ));

    const checklist = live.checklist ?? {};
    const labels = {
      validated_edge: "Validated edge — not found. A backtest is not enough.",
      forward_observation: "Recorded quotes — watching the market is not a trade.",
      risk_configuration: "Risk limits — a limit is not permission to trade.",
      mt5_connectivity: "Broker connection — a connection is not an order.",
      reconciliation: "Books match the broker — a match is not permission.",
      human_approval: "A recorded human decision — this screen cannot record one.",
    };
    content.appendChild(card({
      title: "What the readiness report lists", sub: "A listed pass does not open live trading.", icon: "check",
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
      title: "Why it is locked", icon: "info",
      body: h("div", { class: "stack" },
        h("ul", { class: "reason-list" }, (live.blocked_reasons ?? []).map((r) => h("li", null, r))),
        banner("info", "None of these open live trading", "A research result, a recorded quote, a risk limit, or a broker connection does not open live trading. This page cannot record an approval.", "info"),
        banner("info", "Watching is not trading", "Saving quotes does not prove a profit and does not permit an order. Demo trading, if it is ever turned on, is still not live trading.", "info"),
      ),
    }));

    content.appendChild(card({
      title: "Live enablement is not available from this screen", icon: "lock",
      body: h("div", { class: "stack" },
        h("p", { class: "gate-note" }, "This button does not write a request and does not unlock live trading. Locked means locked."),
        h("button", {
          class: "btn", disabled: !eligible,
          onclick: eligible ? requestLive : () => toast("info", "LIVE is locked", live.message ?? "Requirements are listed above. What blocked, why, what missing, what next explicit."),
        }, "Live trading cannot be opened here"),
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
      title: "Live trading stays locked",
      danger: true,
      body: h("div", { class: "stack" },
        h("p", null, "This screen cannot record a live request and cannot unlock live trading. There is no approval endpoint behind this button."),
        h("div", { class: "card live-boundary" }, h("div", { class: "card-body" }, h("div", { class: "eyebrow" }, "DEMO vs LIVE"), h("p", { class: "small" }, "Watching a demo account does not use real money. A demo order, if one is ever allowed, is still not live trading. Live trading stays locked."))),
      ),
      acks: [
        "I understand this screen cannot unlock live trading.",
        "I understand demo results are not evidence of profitability and never unlock live trading.",
        "I understand nothing I confirm here is written as an approval.",
      ],
      confirmLabel: "Close — nothing is recorded",
    });
    if (!ok) return;
    toast("info", "Nothing was recorded", "This screen cannot unlock live trading and it does not write an approval.");
    renderGovernance(root);
  }

  const off = store.on("resources", renderFacts);
  const offCtx = onContext(renderFacts);
  onDispose(root, () => { off(); offCtx(); });
  await refresh();
}
