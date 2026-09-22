/* Evidence — self-audit and append-only audit trail
   Progressive disclosure: summary → evidence → raw. Dense, keyboard navigable. */

import { api, store } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, errorBox,
  banner, drawer,
} from "../components.js";
import { fmtUtc, trunc, humanKey } from "../format.js";
import { navigate, onDispose } from "../router.js";
import { getContext } from "../context.js";

export async function renderExplorer(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({
    crumb: "Evidence", group: "Explorer",
    title: "Evidence Explorer",
    answer: h("b", null, `Every displayed result carries its evidence: provenance, lineage, and honest self-audit. If evidence missing, QTS says so. Context ${ctx.symbol}. Progressive disclosure: summary → evidence → raw.`),
    body: null,
  }));
  const activity = h("h2", null, `Loading evidence… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / EVIDENCE"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let v = null;
  try { v = await api.get("/api/validation/sma_breakout"); } catch { v = null; }

  const attr = v?.attribution;
  const unattributed = attr && attr.attributed === false;
  activity.textContent = !v
    ? `No validation evidence — context ${ctx.symbol} — honest empty`
    : unattributed
      ? `Validation file on disk is not attributed to sma_breakout — ${attr.reason}`
      : `Validation evidence loaded for ${attr?.evidence_strategy_id ?? "the requested strategy"} — context ${ctx.symbol}`;

  const edge = unattributed ? null : v?.evidence?.edge_survival;
  const notEstablished = "not established by the loaded evidence — absence is not a pass";
  const audit = [
    ["Did we leak information?", notEstablished, null],
    ["Did we cherry-pick?", notEstablished, null],
    ["Did we over-search?", edge ? `recorded trials=${v.evidence?.trial_ledger?.trial_count ?? "not recorded"}; DSR ${edge.dsr ?? "not recorded"} — a number is not a pass` : notEstablished, null],
    ["Did we reset trial counts?", notEstablished, null],
    ["Did we reuse test set?", v?.evidence?.dataset?.locked_partition?.is_frozen === true && !unattributed ? "locked_partition.is_frozen=true is recorded; that is not proof the test set was unused" : notEstablished, null],
    ["Are we overfit?", edge ? `edge_survival.passed=${edge.passed} — a gate result is not a diagnosis` : notEstablished, null],
    ["Did we under-model costs?", v?.evidence?.cost_robustness?.status && !unattributed ? `cost_robustness.status=${v.evidence.cost_robustness.status} — status is not proof costs were adequate` : notEstablished, null],
    ["Did we assume unrealistic fills?", notEstablished, null],
  ];
  host.appendChild(card({
    title: `Self-audit — 8 uncomfortable questions, answered from evidence — context ${ctx.symbol}`, sub: "not intention, but evidence", icon: "fileCheck",
    body: h("div", { class: "check-grid" },
      audit.map(([q, a, ok]) => h("div", { class: `check ${ok === true ? "pass" : ok === false ? "fail" : "na"}` },
        h("div", { class: "mark", "aria-hidden": "true" }, ok === true ? "✓" : ok === false ? "✕" : "?"),
        h("div", null, h("div", { class: "name" }, q), h("div", { class: "detail" }, a)),
      )),
    ),
  }));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: `Discovery report — per-campaign evidence portfolio — context ${ctx.symbol}`, sub: "dense, with raw disclosure", icon: "archive", body:
      v?.evidence
        ? h("div", { class: "stack" },
            kv([["Dataset manifest", h("span", { class: "mono small" }, v.evidence?.dataset?.manifest ?? "—")], ["Trials (N)", v.evidence?.trial_ledger?.trial_count ?? "—"], ["Edge survival", badge(edge?.passed ? "PASSED" : "FAILED")], ["PSR / DSR / PBO", `${edge?.psr ?? "—"} / ${edge?.dsr ?? "—"} / ${edge?.pbo ?? "—"}`], ["Context", `${getContext().symbol} — presentation only`]]),
            h("details", null, h("summary", null, "Raw discovery evidence / technical — summary → detail → raw"), tech(v.evidence, "Raw discovery evidence")),
          )
        : emptyState({ icon: "archive", title: "No validation evidence available", desc: "Evidence appears after research campaigns run. QTS never invents portfolio to look complete.", actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Research")] }),
    }),
    card({ title: "Confidence calibration — explanatory, not decorative", icon: "scale", body: h("div", { class: "stack" }, banner("info", "Calibrated probability, not vibes", "PSR/DSR give calibrated probabilities; permutation tests control false positives; null and placebo verify machinery itself.", "info"), h("p", { class: "gate-note" }, "High backtest Sharpe is treated as hypothesis to attack, never as result to display proudly."))}),
  ));

  host.appendChild(card({ title: "Evidence lineage — summary → evidence → lineage → raw", sub: "any preprocessing change creates NEW version", icon: "branch", body:
    h("div", { class: "pipeline" }, ["MT5 Tick / Provider","Canonical Observation","Session","Feature","Signal","Experiment","Validation","Promotion Decision"].map((c, i) => [i > 0 && h("span", { class: "pipe-arrow" }, "→"), h("span", { class: "pipe-stage reached" }, c)])),
  }));
}

export async function renderAudit(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  const q = h("input", { class: "input", placeholder: "Search events — decisions, risk vetoes, orders, fills, reconciliations…", style: { maxWidth: "380px" }, "aria-label": "Search audit trail" });
  const head = page({
    crumb: "Evidence", group: "Audit trail",
    title: "Audit Trail",
    answer: h("b", null, `Append-only, redacted record of everything QTS decided, blocked, submitted, or reconciled. Context ${ctx.symbol}. Dense table, drawer for payload, per-source freshness, keyboard navigable.`),
    actions: [q, h("button", { class: "btn primary", onclick: () => load() }, icon("search", 14), "Search")],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, `Loading audit… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / AUDIT"), activity)));

  const host = h("div", { class: "section" }); root.appendChild(host);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });

  async function load() {
    const term = q.value.trim();
    let rows = [];
    try { rows = await api.get("/api/audit?limit=100" + (term ? `&q=${encodeURIComponent(term)}` : "")); } catch (e) { clear(host); host.appendChild(errorBox({ what: "audit trail could not be loaded", next: "Retry.", raw: e.message })); return; }
    clear(host);
    activity.textContent = `${rows.length} audit events${term ? ` matching “${trunc(term,30)}”` : ""} — context ${getContext().symbol} — dense, keyboard sortable`;
    const byType = {};
    rows.forEach((r) => { const t = String(r.type ?? "event"); byType[t] = (byType[t] ?? 0) + 1; });
    host.appendChild(card({
      title: `${rows.length} event(s)${term ? ` matching “${trunc(term,30)}”` : ""} — dense, keyboard sortable, drawer for payload — context ${getContext().symbol}`, icon: "archive",
      actions: h("div", { class: "chip-row" }, Object.entries(byType).sort((a, b) => b[1]-a[1]).slice(0,8).map(([t, n]) => h("span", { class: "chip" }, `${t} · ${n}`))),
      body: rows.length
        ? table({
            columns: [
              { key: "time", label: "Time (UTC)", render: (r) => h("span", { class: "mono small" }, fmtUtc(r.time)) },
              { key: "type", label: "Type", render: (r) => badge(String(r.type ?? "event").toUpperCase()) },
              { key: "event", label: "Event", render: (r) => h("span", { class: "primary-cell small" }, trunc(String(r.payload?.event ?? r.payload?.reason ?? r.type ?? ""), 70)) },
              { key: "actor", label: "Detail", render: (r) => h("span", { class: "small text-dim" }, trunc(JSON.stringify(r.payload ?? {}), 90)) },
            ],
            rows: [...rows].reverse(),
            empty: "No audit events match.",
            dense: true,
            onRowClick: (r) => drawer(`Audit event — ${r.type ?? ""}`, h("div", { class: "stack" }, kv([["Time (UTC)", fmtUtc(r.time)], ["Type", String(r.type ?? "").toUpperCase()], ["Context", `${getContext().symbol} — presentation only`]]), tech(r.payload ?? r, "Raw event payload — summary → detail → raw"))),
          })
        : emptyState({ icon: "archive", title: "No audit events", desc: "Every decision QTS makes lands here — empty trail means nothing happened yet." }),
    }));
  }

  const off = store.on("resources", () => { activity.textContent = `${getContext().symbol} — audit source — dense, honest`; });
  onDispose(root, off);
  await load();
}
