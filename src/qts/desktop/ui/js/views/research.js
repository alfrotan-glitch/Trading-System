/* ============================================================
   VIEW GROUP: RESEARCH — the scientific laboratory
   Question → Hypotheses → Experiments → Attacks → Results →
   Survivors → Validation. Failures are first-class knowledge.
   ============================================================ */
import { api } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  barList, confirmModal, toast, banner, chipRow, drawer, closeDrawer,
} from "../components.js";
import { fmtInt, fmtMetric, fmtUtc, fmtAge, humanKey, trunc } from "../format.js";
import { navigate } from "../router.js";

/* ================= CAMPAIGNS ================= */
export async function renderCampaigns(root) {
  skeletonInto(root);
  const el = page({
    crumb: "Research", group: "Campaigns",
    title: "Research Campaigns",
    answer: h("b", null, "Bounded, auditable experiment runs. Every trial — kept or discarded, winning or failing — is permanently recorded. Trial counts are never reset."),
    actions: [
      h("button", { class: "btn primary", onclick: () => openCreateCampaign(root) }, icon("plus", 14), "New campaign"),
    ],
    body: null,
  });
  root.appendChild(el);
  const host = h("div");
  el.appendChild(host);

  let campaigns = [];
  try {
    campaigns = await api.get("/api/research/campaigns");
  } catch (e) {
    host.appendChild(errorBox({ what: "campaigns could not be loaded", next: "Retry.", raw: e.message }));
    return;
  }

  const shape = (c) => ({
    id: c.id, status: c.status, family: c.config?.family, symbol: c.config?.symbol,
    timeframe: c.config?.timeframe, version: c.config?.data_version, trials: c.config?.max_trials,
    runtime: c.config?.max_runtime_s, seed: c.config?.seed, space: c.config?.param_space,
  });

  host.appendChild(card({
    title: `${campaigns.length} campaign${campaigns.length === 1 ? "" : "s"}`,
    sub: "click a row for configuration details", icon: "flask",
    body: table({
      columns: [
        { key: "id", label: "Campaign", render: (c) => h("span", { class: "primary-cell mono" }, String(c.id).slice(0, 24)) },
        { key: "status", label: "Status", render: (c) => badge(c.status) },
        { key: "family", label: "Family", render: (c) => humanKey(c.config?.family ?? "—") },
        { key: "symbol", label: "Instrument", render: (c) => `${c.config?.symbol ?? "—"} · ${c.config?.timeframe ?? "—"}` },
        { key: "version", label: "Data version", render: (c) => h("span", { class: "mono small text-dim" }, trunc(c.config?.data_version ?? "auto", 26)) },
        { key: "trials", label: "Trial budget", num: true, sortVal: (c) => c.config?.max_trials ?? 0, render: (c) => fmtInt(c.config?.max_trials) },
      ],
      rows: campaigns,
      empty: "No campaigns yet. Research starts by creating one — QTS then generates falsifiable hypotheses from the family's mechanism pool.",
      onRowClick: (c) => {
        const s = shape(c);
        import("../components.js").then(({ drawer }) => {
          drawer(`Campaign ${String(c.id).slice(0, 18)}`, h("div", { class: "stack" },
            kv([
              ["Status", badge(c.status)],
              ["Family", humanKey(s.family ?? "")],
              ["Instrument", `${s.symbol ?? "—"} ${s.timeframe ?? ""}`],
              ["Data version", s.version ?? "auto (latest ingested)"],
              ["Trial budget", s.trials],
              ["Runtime cap (s)", s.runtime],
              ["Seed", s.seed],
            ]),
            h("div", null, h("div", { class: "eyebrow", style: { marginBottom: "6px" } }, "Parameter space"), tech(s.space, "Show parameter space")),
            h("div", { class: "meta" }, "Campaigns never modify code and never promote strategies. Human directs; gates decide."),
          ));
        });
      },
    }),
  }));

  host.appendChild(card({
    title: "How a campaign works", icon: "book",
    body: h("ol", { class: "gate-list", style: { fontSize: "var(--fs-13)", lineHeight: "1.9" } },
      ["Review available data — insufficient data blocks the campaign",
        "Review recorded failures — known-dead ideas are not retried blindly",
        "Generate a bounded plan (trial budget, runtime cap, seed)",
        "Create falsifiable hypotheses with explicit mechanisms",
        "Execute experiments inside the budget",
        "Store every result — winners and losers",
        "Attack surviving candidates (costs, perturbation, regimes, null, placebo)",
        "Eliminate weak candidates — elimination is success, not failure",
        "Refine survivors under the same budget",
        "Re-test refinements",
        "Produce an evidence portfolio — never a promotion"].map((s, i) => h("li", null, `${i + 1}. ${s}`))),
  }));
}

async function openCreateCampaign(root) {
  const families = ["trend", "breakout", "mean_reversion", "momentum", "volatility"];
  const fam = h("select", { class: "select" }, families.map((f) => h("option", { value: f }, humanKey(f))));
  const sym = h("input", { class: "input", value: "XAUUSD" });
  const tf = h("input", { class: "input", value: "1H" });
  const ver = h("input", { class: "input", placeholder: "auto — latest ingested version" });
  const trials = h("input", { class: "input", type: "number", value: "12", min: "1", max: "100" });
  const ok = await confirmModal({
    title: "Create research campaign",
    body: h("div", null,
      h("div", { class: "field" }, h("label", null, "Strategy family"), fam),
      h("div", { class: "field" }, h("label", null, "Symbol"), sym),
      h("div", { class: "field" }, h("label", null, "Timeframe"), tf),
      h("div", { class: "field" }, h("label", null, "Data version"), ver, h("div", { class: "hint" }, "Blank = latest ingested manifest version.")),
      h("div", { class: "field" }, h("label", null, "Trial budget (hard cap)"), trials),
      h("div", { class: "meta" }, "The campaign runs inside these bounds and records everything to the immutable ledger."),
    ),
    confirmLabel: "Start campaign",
  });
  if (!ok) return;
  try {
    await api.post("/api/research/campaigns", {
      name: `campaign-${Date.now()}`,
      symbol: sym.value || "XAUUSD",
      timeframe: tf.value || "1H",
      family: fam.value,
      max_trials: Number(trials.value) || 12,
      ...(ver.value ? { data_version: ver.value } : {}),
    });
    toast("ok", "Campaign created", "It appears in the ledger immediately.");
    renderCampaigns(root);
  } catch (e) {
    toast("err", "Campaign creation failed", e.message);
  }
}

/* ================= HYPOTHESES ================= */
export async function renderHypotheses(root) {
  skeletonInto(root);
  root.appendChild(page({ crumb: "Research", group: "Hypotheses", title: "Hypothesis Explorer", answer: h("b", null, "Every idea QTS tests is a falsifiable claim with a named mechanism — never a vague strategy name."), body: null }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let hyps = [];
  try { hyps = await api.get("/api/research/hypotheses?limit=50"); } catch (e) { host.appendChild(errorBox({ what: "hypotheses could not be loaded", next: "Retry.", raw: e.message })); return; }

  if (!hyps.length) {
    host.appendChild(card({ title: "Hypotheses", icon: "brain", body: emptyState({
      icon: "brain", title: "No hypotheses recorded yet",
      desc: "Hypotheses are generated inside research campaigns: each one states a claim, a mechanism, and how it can be refuted. Run a campaign to populate the explorer.",
      actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Campaigns")],
    }) }));
  } else {
    host.appendChild(h("div", { class: "grid-2" }, hyps.map((hp) => h("div", { class: "hyp-card" },
      h("div", { class: "hyp-head" },
        h("div", { class: "hyp-title" }, hp.hypothesis_id ?? hp.id ?? "hypothesis"),
        badge(hp.status ?? hp.state ?? "UNTESTED"),
      ),
      h("div", { class: "hyp-claim" }, hp.claim ?? hp.statement ?? hp.description ?? "—"),
      hp.mechanism ? chipRow([hp.mechanism].flat().map((m) => h("span", { class: "chip mech" }, humanKey(m)))) : null,
      h("div", { class: "hyp-meta" },
        hp.experiments_count != null ? h("span", { class: "badge-mini" }, `${hp.experiments_count} experiments`) : null,
        hp.failed_attacks != null ? h("span", { class: "badge-mini" }, `${hp.failed_attacks} failed attacks`) : null,
        hp.last_tested ? h("span", { class: "badge-mini" }, `tested ${fmtAge(hp.last_tested)}`) : null,
      ),
      tech(hp, "Raw hypothesis record"),
    ))));
  }

  host.appendChild(card({
    title: "Mechanism pool", sub: "falsifiable market mechanisms hypotheses are drawn from", icon: "branch",
    body: chipRow("trend persistence, momentum persistence, mean reversion, breakout continuation, breakout failure, volatility clustering, volatility expansion, regime transitions, liquidity, spread, time-of-day, session, range compression, range expansion, directional imbalance, acceleration, exhaustion, overextension, pullback continuation, failed breakouts, multi-timeframe confirmation, volatility-adjusted positioning, persistence after large moves, asymmetric shock response"
      .split(", ").map((m) => h("span", { class: "chip mech" }, m))),
  }));
}

/* ================= EXPERIMENTS (ledger) ================= */
export async function renderExperiments(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "Research", group: "Experiments",
    title: "Experiment Ledger",
    answer: h("b", null, "No hidden trials. Winners, losers, discarded variants, parameter and feature variants, failed runs — all preserved with their reasons. DSR uses the full N."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let camps = [], novelty = [];
  try {
    [camps, novelty] = await Promise.all([api.get("/api/research/campaigns"), api.get("/api/research/novelty")]);
  } catch (e) { host.appendChild(errorBox({ what: "the experiment ledger could not be loaded", next: "Retry.", raw: e.message })); return; }

  const allTrials = camps.flatMap((c) => (c.trials ?? []).map((t) => ({ ...t, campaign: c.id })));
  host.appendChild(card({
    title: "Trial ledger", sub: `${fmtInt(allTrials.length || camps.length)} recorded entr${allTrials.length === 1 ? "y" : "ies"} across ${camps.length} campaigns`, icon: "archive",
    body: allTrials.length
      ? table({
          columns: [
            { key: "trial_id", label: "Trial", render: (t) => h("span", { class: "mono primary-cell" }, trunc(t.trial_id ?? t.id ?? "—", 20)) },
            { key: "campaign", label: "Campaign", render: (t) => trunc(t.campaign, 18) },
            { key: "status", label: "Outcome", render: (t) => badge(t.status ?? t.outcome ?? "RECORDED") },
            { key: "reason", label: "Why", render: (t) => h("span", { class: "small text-dim" }, trunc(t.reason ?? t.rejection_reason ?? "", 90)) },
          ],
          rows: allTrials,
          empty: "No trials recorded yet.",
        })
      : emptyState({
          icon: "archive", title: "No trials recorded yet",
          desc: "Failed experiments are scientific knowledge: each one eliminates a region of the search space. They appear here with the same prominence as successes.",
          actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Run a campaign")],
        }),
  }));

  host.appendChild(h("div", { class: "grid-2" },
    card({
      title: "Novelty & diversity", sub: "prevents rediscovering the same idea in disguise", icon: "branch",
      body: novelty && novelty.total_trials != null ? h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Total trials", value: fmtInt(novelty.total_trials) }),
          stat({ label: "Distinct hypotheses", value: fmtInt(novelty.distinct_hypotheses) }),
          stat({ label: "Largest cluster", value: fmtInt(novelty.largest_cluster_size), tone: novelty.largest_cluster_size > 3 ? "warn" : "ok", hint: "clusters >3 suggest a duplicated idea" }),
        ),
        novelty.honest_note ? banner("info", "Honest note", novelty.honest_note, "info") : null,
      ) : emptyState({ icon: "branch", title: "No novelty analysis yet", desc: "Appears once experiments exist — QTS clusters hypotheses so one idea cannot be counted twice." }),
    }),
    card({
      title: "Experiment governance", icon: "shield",
      body: h("ul", { class: "gate-list", style: { fontSize: "var(--fs-13)" } },
        h("li", null, "No hidden retries — every execution is one ledger row"),
        h("li", null, "Trial count N is never reset (DSR honesty)"),
        h("li", null, "No deletion — failures persist with their reasons"),
        h("li", null, "Budgets are hard caps, not suggestions"),
      ),
    }),
  ));
}

/* ================= STRATEGIES ================= */
export async function renderStrategies(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "Research", group: "Strategies",
    title: "Strategy Library",
    answer: h("b", null, "Strategies are scientific objects: identity, thesis, mechanism, evidence grade. High historical return alone never promotes a strategy."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let list = [];
  try { list = await api.get("/api/strategies"); } catch (e) { host.appendChild(errorBox({ what: "strategies could not be loaded", next: "Retry.", raw: e.message })); return; }

  if (!list.length) {
    host.appendChild(card({ body: emptyState({
      icon: "flask", title: "No strategies registered",
      desc: "Strategies appear here after research campaigns surface surviving candidates. Nothing is registered by default — an empty library is the honest starting state.",
      actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Research")],
    }) }));
    return;
  }

  host.appendChild(card({
    title: `${list.length} registered`, icon: "flask",
    body: table({
      columns: [
        { key: "strategy_id", label: "Strategy", render: (s) => h("span", { class: "primary-cell mono" }, s.strategy_id) },
        { key: "family", label: "Family", render: (s) => humanKey(s.feature_definition?.family ?? s.family ?? "—") },
        { key: "instrument", label: "Instrument", render: (s) => `${s.symbol ?? "—"} · ${s.timeframe ?? "—"}` },
        { key: "params", label: "Parameters", render: (s) => h("span", { class: "mono small" }, JSON.stringify(s.parameter_definition ?? {})) },
        { key: "hypothesis", label: "Thesis", render: (s) => h("span", { class: "small text-dim" }, trunc(s.hypothesis ?? "", 70)) },
        { key: "exec", label: "Execution assumptions", render: (s) => h("span", { class: "small text-dim" }, `${s.execution_assumptions?.spread_bps ?? "?"} bps spread · ${s.execution_assumptions?.slippage ?? "?"}`) },
        { key: "score", label: "Validation", render: (s) => h("button", { class: "btn ghost sm", onclick: (e) => { e.stopPropagation(); navigate(`#/research/validation`); } }, "Scorecard") },
      ],
      rows: list,
      empty: "No strategies.",
      onRowClick: (s) => {
        drawer(s.strategy_id, h("div", { class: "stack" },
          kv([
            ["Name", s.name ?? "—"],
            ["Version", s.version ?? "—"],
            ["Market", `${s.market ?? "—"} ${s.symbol ?? ""} ${s.timeframe ?? ""}`],
            ["Data manifest", h("span", { class: "mono small" }, s.data_manifest ?? "—")],
            ["Risk assumptions", JSON.stringify(s.risk_assumptions ?? {})],
          ]),
          h("div", null, h("div", { class: "eyebrow", style: { marginBottom: "6px" } }, "Thesis"), h("p", { class: "text-dim" }, s.hypothesis ?? "—")),
          h("div", null, h("div", { class: "eyebrow", style: { marginBottom: "6px" } }, "Feature definition"), tech(s.feature_definition, "Show features")),
          h("button", { class: "btn primary", onclick: () => { closeDrawer(); navigate("#/research/validation"); } }, icon("pulse", 14), "Open validation scorecard"),
        ));
      },
    }),
  }));
}

/* ================= VALIDATION ================= */
export async function renderValidation(root) {
  skeletonInto(root);
  const head = page({
    crumb: "Research", group: "Validation",
    title: "Validation Scorecard",
    answer: h("b", null, "Does the evidence support the hypothesis? Every gate below must pass on its own merits — the verdict is fail-closed."),
    actions: [],
    body: null,
  });
  root.appendChild(head);
  const pick = h("select", { class: "select", style: { maxWidth: "260px" } });
  const host = h("div", { class: "section" }); root.appendChild(host);

  let ids = [];
  try { ids = (await api.get("/api/strategies")).map((s) => s.strategy_id); } catch { ids = []; }
  if (!ids.length) ids = ["sma_breakout"];
  ids.forEach((s) => pick.appendChild(h("option", { value: s }, s)));

  head.querySelector(".page-actions").appendChild(pick);
  const loadBtn = h("button", { class: "btn primary", onclick: () => load(pick.value) }, icon("pulse", 14), "Load scorecard");
  head.querySelector(".page-actions").appendChild(loadBtn);

  async function load(strategyId) {
    clear(host);
    host.appendChild(h("div", { class: "card" }, h("div", { class: "card-body" }, h("div", { class: "skeleton skl-line", style: { width: "60%" } }), h("div", { class: "skeleton skl-line", style: { width: "80%" } }), h("div", { class: "skeleton skl-line", style: { width: "40%" } }))));
    let v;
    try { v = await api.get(`/api/validation/${encodeURIComponent(strategyId)}`); }
    catch (e) { clear(host); host.appendChild(errorBox({ what: `validation for ${strategyId} could not be loaded`, next: "Pick another strategy or retry.", raw: e.message })); return; }
    clear(host);
    host.appendChild(scorecard(strategyId, v));
  }
  await load(ids[0]);
}

function scorecard(strategyId, v) {
  const ev = v.evidence ?? {};
  const edge = ev.edge_survival ?? {};
  const verdict = v.decision ?? v.verdict ?? edge.passed ? "PASS" : "BLOCK";
  const chips = h("div", { class: "chip-row" },
    h("span", { class: "chip" }, `trials N=${ev.trial_ledger?.trial_count ?? "?"} (disk ${ev.trial_ledger?.disk_trial_count ?? "?"})`),
    h("span", { class: "chip" }, `PSR ${fmtNum3(edge.psr)}`),
    h("span", { class: "chip" }, `DSR ${fmtNum3(edge.dsr)}`),
    h("span", { class: "chip" }, `PBO ${fmtNum3(edge.pbo)}`),
    h("span", { class: "chip" }, `WFE ${fmtNum3(edge.wfe)}`),
    h("span", { class: "chip" }, `cost break-even ${fmtNum3(edge.cost_be)}`),
  );

  const gate = (name, ok, detail) => h("div", { class: `check ${ok === true ? "pass" : ok === false ? "fail" : "na"}` },
    h("div", { class: "mark", "aria-hidden": "true" }, ok === true ? "✓" : ok === false ? "✕" : "○"),
    h("div", null, h("div", { class: "name" }, name), detail ? h("div", { class: "detail" }, detail) : null));

  const ds = ev.dataset ?? {};
  return h("div", { class: "stack" },
    banner(
      verdict === "PASS" ? "ok" : "err",
      `VERDICT: ${verdict === "PASS" ? "EVIDENCE SUPPORTS — next gates apply" : "BLOCK — evidence does not support promotion"}`,
      verdict === "PASS" ? "This scorecard is one gate; forward observation, demo and governance still apply." : "The strategy stays in research. This is the system working as designed: weak evidence is discarded before it can cost money.",
      verdict === "PASS" ? "check" : "shield",
    ),
    card({ title: "Multiple-testing corrected edge", sub: `strategy: ${strategyId}`, icon: "pulse", actions: [chips], body:
      h("div", { class: "check-grid" },
        gate("Edge survival (all checks)", edge.passed, "OOS + PSR + DSR + PBO + WFE + cost break-even"),
        gate("Null control rejected", ev.null_control?.rejected, `${(ev.null_control?.control_sharpes ?? []).length} null strategies tested`),
        gate("Placebo rejected", ev.placebo?.rejected, `${(ev.placebo?.placebo_sharpes ?? []).length} placebo tests`),
        gate("Cost robustness", ev.cost_robustness ? true : null, ev.cost_robustness?.stress ? `stress: ${trunc(JSON.stringify(ev.cost_robustness.stress), 80)}` : null),
        gate("Locked test partition", ds.locked_partition ? true : null, "test set untouched during discovery"),
        gate("Dataset quality", ds.quality_passed, `${(ds.quality_checks ?? []).length} ingestion checks`),
      ),
    }),
    h("div", { class: "grid-2" },
      card({ title: "Regime robustness", icon: "activity", body:
        (ev.regime ?? []).length
          ? table({
              columns: [
                { key: "regime", label: "Regime" },
                { key: "sharpe", label: "Sharpe", num: true, render: (r) => fmtNum3(r.sharpe) },
                { key: "trades", label: "Trades", num: true },
                { key: "passed", label: "State", render: (r) => badge(r.passed ? "PASS" : "FAIL") },
              ],
              rows: ev.regime, empty: "No regime breakdown.",
            })
          : emptyState({ icon: "activity", title: "No regime evidence yet", desc: "Regime splits appear after campaigns run across varied market states." }),
      }),
      card({ title: "Forward evidence", icon: "eye", body:
        emptyState({ icon: "eye", title: "No forward evidence yet", desc: "Forward observation and demo results appear here only after real sessions run. Backtests never substitute for them." }),
      }),
    ),
    card({ title: "Discovery provenance", icon: "fileCheck", body:
      h("div", { class: "stack" },
        kv([
          ["Dataset manifest", h("span", { class: "mono small" }, ds.manifest ?? "—")],
          ["Quality checks", `${(ds.quality_checks ?? []).length} recorded`],
          ["Missing stats", JSON.stringify(ds.missing_stats ?? {})],
        ]),
        tech(ev, "Raw validation evidence"),
      ),
    }),
  );
}

const fmtNum3 = (x) => (x === null || x === undefined) ? "—" : Number(x).toFixed(3);

/* ================= MEMORY (findings) ================= */
export async function renderMemory(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "Research", group: "Memory",
    title: "Research Memory",
    answer: h("b", null, "Durable knowledge of what was tested, why it failed, and what was unstable — so QTS never pays twice for the same lesson."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let mem = [], novelty = [], statStack = null;
  try {
    [mem, novelty, statStack] = await Promise.all([
      api.get("/api/research/memory?limit=30"),
      api.get("/api/research/novelty"),
      api.get("/api/research/statistical"),
    ]);
  } catch (e) { host.appendChild(errorBox({ what: "research memory could not be loaded", next: "Retry.", raw: e.message })); return; }

  host.appendChild(card({
    title: "Findings", sub: "failed hypotheses are kept with their reasons", icon: "brain",
    body: (mem ?? []).length
      ? table({
          columns: [
            { key: "id", label: "Finding", render: (m) => h("span", { class: "primary-cell" }, trunc(m.hypothesis_id ?? m.id ?? m.summary ?? "—", 40)) },
            { key: "outcome", label: "Outcome", render: (m) => badge(m.status ?? m.outcome ?? "RECORDED") },
            { key: "reason", label: "Why", render: (m) => h("span", { class: "small text-dim" }, trunc(m.reason ?? m.lesson ?? "", 100)) },
            { key: "when", label: "Recorded", render: (m) => h("span", { class: "small text-dim mono" }, m.timestamp ? fmtUtc(m.timestamp) : "—") },
          ],
          rows: mem,
          empty: "Memory is empty — nothing has been learned and recorded yet.",
        })
      : emptyState({ icon: "brain", title: "No findings recorded yet", desc: "As experiments run, disproven assumptions and unstable parameters accumulate here — negative results are permanent knowledge." }),
  }));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Statistical stack", sub: "multiple-testing defenses used by every gate", icon: "scale", body: statStack ? h("div", { class: "stack" },
      Object.entries(statStack).filter(([, v]) => typeof v === "object").map(([k, v]) =>
        h("div", { class: "check pass", style: { borderColor: "var(--line)" } },
          h("div", { class: "mark", style: { background: "var(--research-bg)", color: "var(--research-text)", borderColor: "var(--research-line)" } }, "∑"),
          h("div", null,
            h("div", { class: "name" }, humanKey(k)),
            h("div", { class: "detail" }, v.purpose ?? ""),
            v.p_value != null ? h("div", { class: "detail" }, `p = ${v.p_value}${v.n_bootstrap ? ` · ${fmtInt(v.n_bootstrap)} bootstraps` : ""}${v.n_perm ? ` · ${fmtInt(v.n_perm)} permutations` : ""}`) : null,
            v.limitations ? h("div", { class: "detail" }, `Limitations: ${trunc(v.limitations, 110)}`) : null,
          ),
        ),
      ),
      tech(statStack, "Raw statistical stack"),
    ) : emptyState({ icon: "scale", title: "Statistical stack unavailable" }) }),
    card({ title: "Why failures matter", icon: "info", body: h("div", { class: "stack" },
      banner("info", "No-exploitable-edge is a valid outcome", "If research proves there is no durable edge under honest costs, that is a success of the method — not a failure of QTS.", "info"),
      h("p", { class: "gate-note" }, "Every disproven hypothesis narrows the search space. Memory makes the next campaign cheaper and prevents re-testing dead ideas with cosmetic variations."),
    )}),
  ));
}

/* ================= DATA (observatory + source lab) ================= */
export async function renderData(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "Research", group: "Data",
    title: "Data Observatory",
    answer: h("b", null, "What data QTS has, how good it is, and what is missing — with explicit REAL vs SYNTHETIC labeling on every field."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let audit = null, inv = [], quality = null;
  try {
    [audit, inv, quality] = await Promise.all([
      api.get("/api/research/data-audit"),
      api.get("/api/research/data-inventory"),
      api.get("/api/research/data-quality-adversarial"),
    ]);
  } catch (e) { host.appendChild(errorBox({ what: "data observatory could not be loaded", next: "Retry.", raw: e.message })); return; }

  const need = audit?.minimum_expansion_needed ?? {};
  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Available data", sub: audit?.count != null ? `${audit.count} source(s)` : null, icon: "database", body:
      table({
        columns: [
          { key: "instrument", label: "Instrument" },
          { key: "timeframe", label: "TF" },
          { key: "rows", label: "Rows", num: true, render: (d) => fmtInt(d.rows) },
          { key: "range", label: "Range", render: (d) => h("span", { class: "small mono text-dim" }, `${d.start} → ${d.end}`) },
          { key: "bid_ask", label: "Bid/Ask", render: (d) => badge(d.bid_ask_available ? "REAL" : "SYNTHETIC") },
          { key: "ts", label: "Timestamps", render: (d) => badge(d.timestamp_quality ?? "UNAVAILABLE") },
        ],
        rows: audit?.available_sources ?? [],
        empty: "No data sources ingested.",
      }),
    }),
    card({ title: "Minimum expansion needed", sub: "what must be acquired before claims strengthen", icon: "alert", body:
      Object.keys(need).length
        ? kv(Object.entries(need).map(([k, v]) => [k, h("span", { class: "small" }, v)]))
        : emptyState({ icon: "check", title: "No gaps recorded", desc: "The audit did not report expansion requirements." }),
    }),
  ));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Dataset inventory & lineage inputs", icon: "branch", body:
      table({
        columns: [
          { key: "instrument", label: "Dataset", render: (d) => `${d.instrument} ${d.timeframe}` },
          { key: "rows", label: "Rows", num: true, render: (d) => fmtInt(d.row_count) },
          { key: "range", label: "Range", render: (d) => h("span", { class: "small mono text-dim" }, `${d.date_range?.start} → ${d.date_range?.end}`) },
          { key: "tz", label: "Timezone", render: (d) => d.timezone },
          { key: "fields", label: "Fields", render: (d) => h("span", { class: "small" }, ["OHLC", d.ohlc_availability, d.bid_availability && "bid", d.ask_availability && "ask"].filter(Boolean).join(" · ")) },
        ],
        rows: inv, empty: "No datasets.",
      }),
    }),
    card({ title: "Fail-closed quality stress", icon: "shield", body: quality ? h("div", { class: "stack" },
      h("div", { class: "check-grid" },
        h("div", { class: `check ${quality.duplicate_corrupted_passed ? "pass" : "fail"}` }, h("div", { class: "mark" }, quality.duplicate_corrupted_passed ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Duplicate / corrupted rows"), h("div", { class: "detail" }, "injected faults must be caught"))),
        h("div", { class: `check ${quality.missing_corrupted_gap_check ? "pass" : "fail"}` }, h("div", { class: "mark" }, quality.missing_corrupted_gap_check ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Missing-data gap detection"), h("div", { class: "detail" }, "gaps must fail closed, never interpolate silently"))),
      ),
      quality.fail_closed_principle ? banner("info", "Principle", quality.fail_closed_principle, "info") : null,
    ) : emptyState({ icon: "shield", title: "Quality stress unavailable" }) }),
  ));

  host.appendChild(card({ title: "Labeling contract", icon: "fileCheck", body: h("div", { class: "stack" },
    h("div", { class: "chip-row" },
      h("span", { class: "prov real" }, "REAL"), h("span", { class: "prov synthetic" }, "SYNTHETIC"), h("span", { class: "prov synthetic" }, "SIMULATED"), h("span", { class: "prov synthetic" }, "ESTIMATED"), h("span", { class: "prov" }, "IMPUTED"), h("span", { class: "prov demo" }, "BROKER-DERIVED"), h("span", { class: "prov" }, "MODEL-DERIVED"),
    ),
    h("p", { class: "gate-note" }, "OHLC from CSV import is a REAL-price proxy with limited depth; bid/ask and spread derived from highs/lows are SYNTHETIC until real ticks are observed. Every UI badge carries its source prefix."),
    audit?.never_substitute ? banner("warn", "Never substitute", audit.never_substitute, "alert") : null,
  )}));

  host.appendChild(card({ title: "External source catalog", sub: "researched providers for closing the data gaps", icon: "book", body: (async () => {
    try {
      const cat = await api.get("/api/research/data-source-catalog");
      return tech(cat, "Show provider catalog (depth, granularity, licensing, cost, suitability)");
    } catch { return emptyState({ icon: "book", title: "Catalog unavailable" }); }
  })() }));
}
