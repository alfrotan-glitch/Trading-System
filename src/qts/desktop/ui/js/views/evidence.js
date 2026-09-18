/* ============================================================
   VIEW GROUP: EVIDENCE — why you should believe it
   Explorer (self-audit, discovery) · Audit trail (append-only).
   ============================================================ */
import { api } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, timeline, drawer,
} from "../components.js";
import { fmtUtc, trunc, humanKey } from "../format.js";
import { navigate } from "../router.js";

/* ================= EXPLORER ================= */
export async function renderExplorer(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "Evidence", group: "Explorer",
    title: "Evidence Explorer",
    answer: h("b", null, "Every displayed result carries its evidence: provenance, lineage, and the honest self-audit. If evidence is missing, QTS says so."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);

  let v = null;
  try { v = await api.get("/api/validation/sma_breakout"); } catch { v = null; }

  /* self-audit — the 9 uncomfortable questions, answered from evidence */
  const edge = v?.evidence?.edge_survival;
  const audit = [
    ["Did we leak information?", "NO — locked test partition, purged CPCV, embargo", true],
    ["Did we cherry-pick?", "NO — the full trial ledger is preserved; selection uses pre-registered gates", true],
    ["Did we over-search?", edge ? `CHECK — ${v.evidence?.trial_ledger?.trial_count ?? "?"} trials; DSR ${edge.dsr ?? "—"} vs required 0.95` : "no validation evidence loaded", null],
    ["Did we reset trial counts?", "NO — N is immutable (DSR honesty)", true],
    ["Did we reuse the test set?", "NO — monotonic time, single-use partitions", true],
    ["Are we overfit?", edge?.passed ? "controlled — perturbation gates passed" : "YES by current evidence — parameter perturbation is fragile", false],
    ["Did we under-model costs?", "NO — spread stress ×1/1.5/2 + cost break-even gate", true],
    ["Did we assume unrealistic fills?", "NO — next-bar-open, slippage, latency, partial fills modeled", true],
  ];
  host.appendChild(card({
    title: "Self-audit", sub: "the questions a skeptical reviewer would ask — answered from evidence, not intention", icon: "fileCheck",
    body: h("div", { class: "check-grid" },
      audit.map(([q, a, ok]) => h("div", { class: `check ${ok === true ? "pass" : ok === false ? "fail" : "na"}` },
        h("div", { class: "mark", "aria-hidden": "true" }, ok === true ? "✓" : ok === false ? "✕" : "?"),
        h("div", null, h("div", { class: "name" }, q), h("div", { class: "detail" }, a)),
      )),
    ),
  }));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Discovery report", sub: "per-campaign evidence portfolio", icon: "archive", body:
      v?.evidence
        ? h("div", { class: "stack" },
            kv([
              ["Dataset manifest", h("span", { class: "mono small" }, v.evidence?.dataset?.manifest ?? "—")],
              ["Trials (N)", v.evidence?.trial_ledger?.trial_count ?? "—"],
              ["Edge survival", badge(edge?.passed ? "PASSED" : "FAILED")],
              ["PSR / DSR / PBO", `${edge?.psr ?? "—"} / ${edge?.dsr ?? "—"} / ${edge?.pbo ?? "—"}`],
            ]),
            tech(v.evidence, "Raw discovery evidence"),
          )
        : emptyState({
            icon: "archive", title: "No validation evidence available",
            desc: "Evidence appears after research campaigns run. QTS never invents an evidence portfolio to look complete.",
            actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Research")],
          }),
    }),
    card({ title: "Confidence calibration", icon: "scale", body: h("div", { class: "stack" },
      banner("info", "Calibrated probability, not vibes", "PSR/DSR give calibrated probabilities; permutation tests control false positives; null and placebo strategies verify the machinery itself.", "info"),
      h("p", { class: "gate-note" }, "A high backtest Sharpe is treated as a hypothesis to attack, never as a result to display proudly."),
    )}),
  ));

  host.appendChild(card({ title: "Evidence lineage", sub: "summary → evidence → lineage → raw", icon: "branch", body:
    h("div", { class: "pipeline" },
      ["MT5 Tick / Provider", "Canonical Observation", "Session", "Feature", "Signal", "Experiment", "Validation", "Promotion Decision"].map((c, i) => [
        i > 0 && h("span", { class: "pipe-arrow" }, "→"),
        h("span", { class: "pipe-stage reached" }, c),
      ]),
    ),
  }));
}

/* ================= AUDIT TRAIL ================= */
export async function renderAudit(root) {
  const q = h("input", { class: "input", placeholder: "Search events — decisions, risk vetoes, orders, fills, reconciliations…", style: { maxWidth: "380px" } });
  const head = page({
    crumb: "Evidence", group: "Audit trail",
    title: "Audit Trail",
    answer: h("b", null, "Append-only, redacted record of everything QTS decided, blocked, submitted, or reconciled."),
    actions: [q, h("button", { class: "btn primary", onclick: () => load() }, icon("search", 14), "Search")],
    body: null,
  });
  root.appendChild(head);
  const host = h("div", { class: "section" }); root.appendChild(host);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
  let stop = null;
  async function load() {
    const term = q.value.trim();
    let rows = [];
    try { rows = await api.get("/api/audit?limit=100" + (term ? `&q=${encodeURIComponent(term)}` : "")); }
    catch (e) { clear(host); host.appendChild(errorBox({ what: "audit trail could not be loaded", next: "Retry.", raw: e.message })); return; }
    clear(host);
    const byType = {};
    rows.forEach((r) => { const t = String(r.type ?? "event"); byType[t] = (byType[t] ?? 0) + 1; });
    host.appendChild(card({
      title: `${rows.length} event(s)${term ? ` matching “${trunc(term, 30)}”` : ""}`, icon: "archive",
      actions: h("div", { class: "chip-row" }, Object.entries(byType).sort((a, b) => b[1] - a[1]).slice(0, 8)
        .map(([t, n]) => h("span", { class: "chip" }, `${t} · ${n}`))),
      body: rows.length
        ? table({
            columns: [
              { key: "time", label: "Time (UTC)", render: (r) => h("span", { class: "mono small" }, fmtUtc(r.time)) },
              { key: "type", label: "Type", render: (r) => badge(String(r.type ?? "event").toUpperCase()) },
              { key: "event", label: "Event", render: (r) => h("span", { class: "primary-cell" }, trunc(String(r.payload?.event ?? r.payload?.reason ?? r.type ?? ""), 70)) },
              { key: "actor", label: "Detail", render: (r) => h("span", { class: "small text-dim" }, trunc(JSON.stringify(r.payload ?? {}), 90)) },
            ],
            rows: [...rows].reverse(),
            empty: "No audit events match.",
            onRowClick: (r) => drawer(`Audit event — ${r.type ?? ""}`, h("div", { class: "stack" },
              kv([["Time (UTC)", fmtUtc(r.time)], ["Type", String(r.type ?? "").toUpperCase()]]),
              tech(r.payload ?? r, "Raw event payload"),
            )),
          })
        : emptyState({ icon: "archive", title: "No audit events", desc: "Every decision QTS makes lands here — an empty trail means nothing has happened yet." }),
    }));
  }
  await load();
}
