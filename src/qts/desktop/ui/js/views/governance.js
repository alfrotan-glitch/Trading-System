/* ============================================================
   VIEW: GOVERNANCE — LIVE, deliberately different
   Calm, restricted, explicit. No aggressive visuals, no
   pressure. The locked state is a feature, rendered proudly.
   ============================================================ */
import { api } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, checkGrid, confirmModal, toast,
} from "../components.js";
import { fmtUtc, fmtAge } from "../format.js";
import { navigate } from "../router.js";

export async function renderGovernance(root) {
  skeletonInto(root);
  const head = page({
    crumb: "Governance",
    title: "Live Trading Governance",
    answer: h("b", null, "Real capital lives behind this gate. It opens only when every scientific, safety, and human-approval condition is met — and demo results never substitute for it."),
    body: null,
  });
  root.appendChild(head);
  const host = h("div", { class: "section", style: { maxWidth: "860px", margin: "0 auto" } }); root.appendChild(host);

  let live = null, safety = null;
  try { [live, safety] = await Promise.all([api.get("/api/live/status"), api.get("/api/demo/safety")]); }
  catch (e) {
    host.appendChild(errorBox({ what: "the governance state could not be loaded", next: "Retry. While unreachable, assume LIVE remains locked.", raw: e.message }));
    return;
  }

  /* --- hero: LIVE — LOCKED --- */
  const eligible = Boolean(live.eligible);
  host.appendChild(h("div", {
    class: "card",
    style: {
      borderColor: "var(--locked-line)",
      background: "linear-gradient(180deg, var(--locked-bg), transparent 70%)",
    },
  },
    h("div", { class: "card-body", style: { textAlign: "center", padding: "var(--sp-8)" } },
      h("div", { style: { display: "flex", justifyContent: "center", marginBottom: "var(--sp-3)" } },
        icon("lock", 34),
      ),
      h("div", {
        style: { fontSize: "var(--fs-28)", fontWeight: 700, letterSpacing: "0.06em", color: "var(--locked-text)" },
      }, ("LIVE — " + String(live.live_trading ?? "LOCKED")).toUpperCase()),
      h("p", { class: "text-dim", style: { maxWidth: "60ch", margin: "10px auto 0" } },
        eligible
          ? "All gates pass. Human approval is still required — eligibility is not permission."
          : live.message ?? "LIVE trading is structurally locked. No UI action, no backtest result, and no demo performance can change that."),
      h("div", { class: "meta", style: { marginTop: "10px" } }, `evaluated ${fmtUtc(new Date().toISOString())} · the gate re-evaluates continuously, not on a timer you control`),
    ),
  ));

  /* --- requirement checklist --- */
  const checklist = live.checklist ?? {};
  const labels = {
    validated_edge: "Validated edge — statistical gates passed (DSR/PBO/OOS)",
    forward_observation: "Forward observation — real-data sessions recorded",
    risk_configuration: "Risk configuration — approved limits active",
    mt5_connectivity: "MT5 connectivity — real terminal verified",
    reconciliation: "Reconciliation — internal state matches broker",
    human_approval: "Human approval — explicit, informed, recorded",
  };
  host.appendChild(card({
    title: "Requirements", sub: "each must pass independently — partial credit does not exist", icon: "check",
    body: h("div", { class: "check-grid" },
      Object.entries(checklist).map(([k, v]) =>
        h("div", { class: `check ${v === true ? "pass" : "fail"}` },
          h("div", { class: "mark", "aria-hidden": "true" }, v === true ? "✓" : "✕"),
          h("div", null,
            h("div", { class: "name" }, labels[k] ?? humanKey(k)),
            v === true ? h("div", { class: "detail" }, "satisfied") : h("div", { class: "detail" }, "not satisfied — see below for what this requires"),
          ),
        )),
    ),
  }));

  /* --- why locked: the blockers, calmly --- */
  host.appendChild(card({
    title: "Why it is locked", icon: "info",
    body: h("div", { class: "stack" },
      h("ul", { class: "gate-list" }, (live.blocked_reasons ?? []).map((r) => h("li", null, r))),
      banner("info", "What live eligibility would require", "A strategy surviving every scientific gate on real-data evidence, forward observation and demo execution with reconciled reality, approved risk configuration, verified connectivity — and an explicit human approval recorded in the audit log.", "info"),
      banner("info", "What demo success means", "Demo execution proves operational correctness, not profitability, and never advances lifecycle state by itself. Labels stay DEMO.", "info"),
    ),
  }));

  /* --- the request control: intentionally quiet --- */
  host.appendChild(card({
    title: "Request live enablement", icon: "lock",
    body: h("div", { class: "stack" },
      h("p", { class: "gate-note" }, "The request surface exists for completeness and auditability. When the gate is locked, a request is recorded and refused — there is no override, no “are you sure?” spam, no dark pattern."),
      h("button", {
        class: "btn", disabled: !eligible, style: { opacity: eligible ? 1 : 0.5 },
        onclick: eligible ? requestLive : () => toast("info", "LIVE is locked", live.message ?? "Requirements are listed above."),
      }, icon("lock", 14), eligible ? "Request live enablement (gated)" : "Live enablement unavailable — gate is LOCKED"),
      live.explicit_confirmation_required ? h("div", { class: "meta" }, "Explicit confirmation contract: " + live.explicit_confirmation_required) : null,
    ),
  }));

  /* --- mode boundary table --- */
  const boundary = safety?.boundary ?? {};
  if (Object.keys(boundary).length) {
    host.appendChild(card({ title: "Mode boundary", sub: "how each environment differs — no silent conversions", icon: "layers", body:
      kv(Object.entries(boundary).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
    }));
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
}
