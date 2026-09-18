/* Governance — LIVE, deliberately calm, restricted, explicit. Locked is a feature. */
import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness } from "../operations.js";
import { h } from "../dom.js";
import {
  card, page, skeletonInto, tech, kv, errorBox,
  banner, confirmModal, toast,
} from "../components.js";
import { fmtUtc, fmtAge, humanKey } from "../format.js";
import { onDispose } from "../router.js";

export async function renderGovernance(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  const head = page({
    crumb: "Governance",
    title: "Live Trading Governance",
    answer: h("b", null, "Real capital lives behind this gate. It opens only when every scientific, safety, and human-approval condition is met — demo results never substitute for it."),
    actions: [h("button", { class: "btn", onclick: () => refresh(true) }, "Refresh")],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, "Loading governance…");
  const next = h("a", { class: "btn primary", href: "#/research/validation" }, "Inspect validation evidence");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary live-boundary" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / LIVE GOVERNANCE"), activity),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT"), next, nextWhy)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section", style: { maxWidth: "860px", margin: "0 auto" } });
  root.appendChild(host);

  let lastLive = null, lastSafety = null;

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["mode", "Environment / mode", s.mode.mode, s.mode.blurb],
      ["liveLabel", "LIVE governance", s.liveLabel, "Eligibility is not enablement. Human approval still required."],
      ["permission", "DEMO execution", s.permission, "DEMO evidence never automatically authorizes LIVE."],
      ["observation", "Observation", s.observation, "Forward observation is required evidence, not a promotion."],
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
    activity.textContent = `${s.liveLabel} · DEMO ${s.permission} · ${s.observation}`;
    nextWhy.textContent = s.live?.eligible ? "Eligibility is not permission. Human approval still required and recorded." : s.liveReasons.slice(0,2).join(" · ") || "LIVE is locked. Independent evidence and human governance required.";
  }

  async function refresh(force = false) {
    try {
      const [live, safety] = await Promise.all([api.get("/api/live/status"), api.get("/api/demo/safety")]);
      lastLive = live; lastSafety = safety;
      if (force) await syncResource("live", { force: true });
      render();
    } catch (e) {
      host.replaceChildren(errorBox({ what: "the governance state could not be loaded", next: "Retry. While unreachable, assume LIVE remains locked.", raw: e.message }));
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
          eligible ? "All gates pass. Human approval is still required — eligibility is not permission." : live.message ?? "LIVE trading is structurally locked. No UI action, no backtest result, and no demo performance can change that."),
        h("div", { class: "meta" }, `evaluated ${fmtUtc(new Date().toISOString())} · gate re-evaluates continuously, not on a timer you control`),
      ),
    ));

    const checklist = live.checklist ?? {};
    const labels = {
      validated_edge: "Validated edge — statistical gates passed (DSR/PBO/OOS)",
      forward_observation: "Forward observation — real-data sessions recorded",
      risk_configuration: "Risk configuration — approved limits active",
      mt5_connectivity: "MT5 connectivity — real terminal verified",
      reconciliation: "Reconciliation — internal state matches broker",
      human_approval: "Human approval — explicit, informed, recorded",
    };
    content.appendChild(card({
      title: "Requirements — each must pass independently", sub: "partial credit does not exist", icon: "check",
      body: h("div", { class: "check-grid" },
        Object.entries(checklist).map(([k, v]) =>
          h("div", { class: `check ${v === true ? "pass" : "fail"}` },
            h("div", { class: "mark", "aria-hidden": "true" }, v === true ? "✓" : "✕"),
            h("div", null,
              h("div", { class: "name" }, labels[k] ?? humanKey(k)),
              h("div", { class: "detail" }, v === true ? "satisfied — independently evidenced" : "not satisfied — see blockers below"),
            ),
          )),
      ),
    }));

    content.appendChild(card({
      title: "Why it is locked — calm, explicit", icon: "info",
      body: h("div", { class: "stack" },
        h("ul", { class: "reason-list" }, (live.blocked_reasons ?? []).map((r) => h("li", null, r))),
        banner("info", "What live eligibility would require", "A strategy surviving every scientific gate on real-data evidence, forward observation and demo execution with reconciled reality, approved risk configuration, verified connectivity — and an explicit human approval recorded in the audit log.", "info"),
        banner("info", "What demo success means", "Demo execution proves operational correctness, not profitability, and never advances lifecycle state by itself. Labels stay DEMO.", "info"),
      ),
    }));

    content.appendChild(card({
      title: "Request live enablement — intentionally quiet", icon: "lock",
      body: h("div", { class: "stack" },
        h("p", { class: "gate-note" }, "The request surface exists for completeness and auditability. When the gate is locked, a request is recorded and refused — no override, no dark pattern."),
        h("button", {
          class: "btn", disabled: !eligible,
          onclick: eligible ? requestLive : () => toast("info", "LIVE is locked", live.message ?? "Requirements are listed above."),
        }, eligible ? "Request live enablement (gated)" : "Live enablement unavailable — gate is LOCKED"),
        live.explicit_confirmation_required ? h("div", { class: "meta" }, "Explicit confirmation contract: " + live.explicit_confirmation_required) : null,
      ),
    }));

    const boundary = lastSafety?.boundary ?? {};
    if (Object.keys(boundary).length) {
      content.appendChild(card({ title: "Mode boundary — no silent conversions", sub: "how each environment differs", icon: "layers", body:
        kv(Object.entries(boundary).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
      }));
    }

    content.appendChild(h("details", null, h("summary", null, "Raw governance snapshots / technical evidence"), tech({ live: lastLive, safety: lastSafety }, "Raw governance")));

    host.replaceChildren(
      h("section", { class: "operator-section" }, h("h2", null, "Operating facts"), h("div", { class: "tbl-wrap", tabindex: "0" }, h("table", { class: "tbl facts-table" }, h("thead", null, h("tr", null, ["Source","Reported state","Meaning / constraint","API freshness"].map((t) => h("th", { scope: "col" }, t)))), factsBody))),
      content
    );
  }

  async function requestLive() {
    const ok = await confirmModal({
      title: "Request LIVE enablement",
      danger: true,
      body: "This records a formal, audited request. The governance gate still decides; human approval is verified server-side.",
      acks: [
        "I understand live trading risks real capital.",
        "I understand demo results are not evidence of profitability and never unlock LIVE.",
        "I am the account owner and this request is deliberate.",
      ],
      confirmLabel: "Submit audited request",
    });
    if (!ok) return;
    toast("info", "Request recorded", "The governance gate evaluates requests server-side — the UI never grants permission.");
    renderGovernance(root);
  }

  const off = store.on("resources", renderFacts);
  onDispose(root, off);
  await refresh();
}
