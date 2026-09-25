/* Research — scientific laboratory: campaigns, hypotheses, experiments, strategies, validation, memory, data
   Flat, dense, progressive disclosure, context-synced. */

import { api } from "../api.js";
import { h, icon } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, chipRow, drawer, closeDrawer, confirmModal, toast,
} from "../components.js";
import { fmtInt, fmtMetric, fmtUtc, fmtAge, humanKey, trunc, fmtDuration } from "../format.js";
import { navigate } from "../router.js";
import { getContext, onContext } from "../context.js";

function denseTable(opts) { return table({ ...opts, dense: true }); }

/* Campaigns */
export async function renderCampaigns(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  const head = page({
    crumb: "Research", group: "Campaigns",
    title: "Research Campaigns",
    answer: h("b", null, `Bounded, auditable experiment runs. Every trial — kept or discarded — permanently recorded. Trial counts never reset. Context ${ctx.symbol} syncs across windows. High density, drawer for detail, keyboard sortable.`),
    actions: [
      h("button", { class: "btn primary", onclick: () => openCreateCampaign(root) }, icon("plus", 14), "New campaign"),
      h("button", { class: "btn", onclick: () => renderCampaigns(root) }, icon("refresh", 14), "Refresh"),
    ],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, "Loading campaigns…");
  const activityWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / RESEARCH"), activity, activityWhy),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT"), h("p", { class: "small text-dim" }, "Campaigns generate falsifiable hypotheses with explicit mechanisms. Human directs; gates decide. Context syncs, never permission."))));

  const host = h("div"); root.appendChild(host);
  let campaigns = [];
  try { campaigns = await api.get("/api/research/campaigns"); } catch (e) { host.appendChild(errorBox({ what: "campaigns could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${campaigns.length} campaign(s) — ${campaigns.filter((c) => String(c.status).toLowerCase().includes("running")).length} running — context ${getContext().symbol}`;
  activityWhy.textContent = "Bounded by trial budget and runtime cap. Every trial preserved with reason. High density without chaos via compact tables and drawer drill-down.";

  const shape = (c) => ({
    id: c.id, status: c.status, family: c.config?.family, symbol: c.config?.symbol,
    timeframe: c.config?.timeframe, version: c.config?.data_version, trials: c.config?.max_trials,
    runtime: c.config?.max_runtime_s, seed: c.config?.seed, space: c.config?.param_space,
  });

  host.appendChild(card({
    title: `${campaigns.length} campaigns — dense, sortable, keyboard navigable, drawer for config`, icon: "flask",
    body: denseTable({
      columns: [
        { key: "id", label: "Campaign", render: (c) => h("span", { class: "primary-cell mono small" }, String(c.id).slice(0,24)) },
        { key: "status", label: "Status", render: (c) => badge(c.status) },
        { key: "family", label: "Family", render: (c) => humanKey(c.config?.family ?? "—") },
        { key: "symbol", label: "Instrument", render: (c) => `${c.config?.symbol ?? "—"} · ${c.config?.timeframe ?? "—"}` },
        { key: "version", label: "Data version", render: (c) => h("span", { class: "mono small text-dim" }, trunc(c.config?.data_version ?? "auto", 26)) },
        { key: "trials", label: "Trial budget", num: true, sortVal: (c) => c.config?.max_trials ?? 0, render: (c) => fmtInt(c.config?.max_trials) },
      ],
      rows: campaigns,
      empty: "No campaigns yet. Research starts by creating one — QTS then generates falsifiable hypotheses.",
      onRowClick: (c) => {
        const s = shape(c);
        drawer(`Campaign ${String(c.id).slice(0,18)}`, h("div", { class: "stack" },
          kv([["Status", badge(c.status)], ["Family", humanKey(s.family ?? "")], ["Instrument", `${s.symbol ?? "—"} ${s.timeframe ?? ""}`], ["Data version", s.version ?? "auto (latest)"], ["Trial budget", s.trials], ["Runtime cap", s.runtime ? fmtDuration(s.runtime) : "—"], ["Seed", s.seed], ["Context", `${getContext().symbol} — presentation only`]]),
          h("details", null, h("summary", null, "Parameter space / technical — summary → detail → raw"), tech(s.space, "Show parameter space")),
          h("p", { class: "text-dim small" }, "Campaigns never modify code and never promote strategies. Human directs; gates decide."),
        ));
      },
    }),
  }));

  host.appendChild(card({
    title: "How a campaign works — progressive disclosure", icon: "book",
    body: h("div", { class: "stack" },
      h("ol", { class: "reason-list" }, ["Review available data — insufficient blocks campaign","Review recorded failures — dead ideas not retried blindly","Generate bounded plan (trial budget, runtime cap, seed)","Create falsifiable hypotheses with explicit mechanisms","Execute experiments inside budget","Store every result — winners and losers","Attack survivors (costs, perturbation, regimes, null, placebo)","Eliminate weak candidates — elimination is success","Refine survivors under same budget","Produce evidence portfolio — never a promotion"].map((s, i) => h("li", null, `${i+1}. ${s}`))),
      h("details", null, h("summary", null, "Why high density matters here"), h("p", { class: "text-dim small" }, "Research is data-intensive. Compact tables, aligned numerics, drawer drill-down and keyboard sorting keep useful information visible without visual chaos.")),
    ),
  }));
}

async function openCreateCampaign(root) {
  const families = ["trend","breakout","mean_reversion","momentum","volatility"];
  const fam = h("select", { class: "input" }, families.map((f) => h("option", { value: f }, humanKey(f))));
  const sym = h("input", { class: "input", value: getContext().symbol });
  const tf = h("input", { class: "input", value: getContext().timeframe });
  const ver = h("input", { class: "input", placeholder: "auto — latest ingested version" });
  const trials = h("input", { class: "input", type: "number", value: "12", min: "1", max: "100" });
  const ok = await confirmModal({
    title: "Create research campaign",
    body: h("div", null,
      h("div", { class: "field" }, h("label", null, "Strategy family"), fam),
      h("div", { class: "field" }, h("label", null, "Symbol — context synced"), sym, h("div", { class: "hint" }, "Uses current context, presentation only.")),
      h("div", { class: "field" }, h("label", null, "Timeframe"), tf),
      h("div", { class: "field" }, h("label", null, "Data version"), ver, h("div", { class: "hint" }, "Blank = latest ingested manifest version.")),
      h("div", { class: "field" }, h("label", null, "Trial budget (hard cap)"), trials),
      h("div", { class: "meta" }, "Campaign runs inside bounds and records everything to immutable ledger."),
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
    toast("ok", "Campaign created", "It appears in ledger immediately.");
    renderCampaigns(root);
  } catch (e) { toast("err", "Campaign creation failed", e.message); }
}

/* Hypotheses */
export async function renderHypotheses(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({ crumb: "Research", group: "Hypotheses", title: "Hypothesis Explorer", answer: h("b", null, `Every idea is a falsifiable claim with named mechanism — never vague strategy name. Context ${ctx.symbol}. Dense table, drawer for full claim, keyboard navigable.`), body: null }));
  const activity = h("h2", null, `Loading hypotheses… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / HYPOTHESES"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let hyps = [];
  try { hyps = await api.get("/api/research/hypotheses?limit=50"); } catch (e) { host.appendChild(errorBox({ what: "hypotheses could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${hyps.length} hypotheses — context ${getContext().symbol} — dense, mechanism explicit`;

  if (!hyps.length) {
    host.appendChild(card({ title: "Hypotheses", icon: "brain", body: emptyState({ icon: "brain", title: "No hypotheses recorded yet", desc: "Hypotheses generated inside campaigns: each states claim, mechanism, how it can be refuted.", actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Campaigns")] }) }));
  } else {
    host.appendChild(card({ title: `${hyps.length} hypotheses — dense, keyboard navigable`, icon: "brain", body: denseTable({
      columns: [
        { key: "id", label: "Hypothesis", render: (hp) => h("span", { class: "mono small primary-cell" }, trunc(hp.hypothesis_id ?? hp.id ?? "hypothesis", 28)) },
        { key: "status", label: "Status", render: (hp) => badge(hp.status ?? hp.state ?? "UNTESTED") },
        { key: "claim", label: "Claim", render: (hp) => h("span", { class: "small text-dim" }, trunc(hp.claim ?? hp.statement ?? hp.description ?? "—", 70)) },
        { key: "mechanism", label: "Mechanism", render: (hp) => h("span", { class: "small" }, humanKey(Array.isArray(hp.mechanism) ? hp.mechanism[0] : hp.mechanism ?? "—")) },
        { key: "tests", label: "Experiments", num: true, render: (hp) => fmtInt(hp.experiments_count) },
      ],
      rows: hyps,
      onRowClick: (hp) => drawer(`Hypothesis ${hp.hypothesis_id ?? hp.id ?? ""}`, h("div", { class: "stack" },
        kv([["ID", hp.hypothesis_id ?? hp.id ?? "—"], ["Status", badge(hp.status ?? hp.state ?? "UNTESTED")], ["Claim", hp.claim ?? hp.statement ?? "—"], ["Context", `${getContext().symbol} — presentation only`]]),
        hp.mechanism ? chipRow([hp.mechanism].flat().map((m) => h("span", { class: "chip mech" }, humanKey(m)))) : null,
        h("details", null, h("summary", null, "Raw hypothesis record / technical — summary → detail → raw"), tech(hp, "Raw hypothesis")),
      )),
    }) }));
  }

  host.appendChild(card({
    title: "Mechanism pool — falsifiable market mechanisms", sub: "explicit, not vague", icon: "branch",
    body: chipRow("trend persistence, momentum persistence, mean reversion, breakout continuation, breakout failure, volatility clustering, volatility expansion, regime transitions, liquidity, spread, time-of-day, session, range compression, range expansion, directional imbalance, acceleration, exhaustion, overextension, pullback continuation, failed breakouts, multi-timeframe confirmation, volatility-adjusted positioning, persistence after large moves, asymmetric shock response".split(", ").map((m) => h("span", { class: "chip mech" }, m))),
  }));
}

/* Experiments */
export async function renderExperiments(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({
    crumb: "Research", group: "Experiments",
    title: "Experiment Ledger",
    answer: h("b", null, `No hidden trials. Winners, losers, discarded variants — all preserved with reasons. DSR uses full N. Context ${ctx.symbol}. High density, keyboard sortable.`),
    body: null,
  }));
  const activity = h("h2", null, `Loading experiments… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / EXPERIMENTS"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let camps = [], novelty = [];
  try { [camps, novelty] = await Promise.all([api.get("/api/research/campaigns"), api.get("/api/research/novelty")]); } catch (e) { host.appendChild(errorBox({ what: "experiment ledger could not be loaded", next: "Retry.", raw: e.message })); return; }

  const allTrials = camps.flatMap((c) => (c.trials ?? c.experiments ?? []).map((t) => ({ ...t, campaign_id: c.id })));
  activity.textContent = `${allTrials.length} trials — context ${getContext().symbol} — immutable ledger`;

  host.appendChild(card({
    title: `${allTrials.length} trials — dense, sortable, drawer for detail, keyboard navigable`, icon: "flask",
    body: allTrials.length ? denseTable({
      columns: [
        { key: "id", label: "Trial", render: (t) => h("span", { class: "mono small" }, trunc(t.id ?? t.trial_id ?? "", 18)) },
        { key: "campaign", label: "Campaign", render: (t) => h("span", { class: "mono small" }, String(t.campaign_id).slice(0,12)) },
        { key: "status", label: "Outcome", render: (t) => badge(t.status ?? t.outcome ?? "RECORDED") },
        { key: "metric", label: "Metric", num: true, render: (t) => t.sharpe != null ? String(Number(t.sharpe).toFixed(2)) : t.metric != null ? String(t.metric) : "—" },
        { key: "reason", label: "Why", render: (t) => h("span", { class: "small text-dim" }, trunc(t.reason ?? t.lesson ?? "", 60)) },
      ],
      rows: allTrials,
      onRowClick: (t) => drawer(`Trial ${t.id ?? ""}`, h("div", { class: "stack" }, kv([["Campaign", String(t.campaign_id)], ["Outcome", badge(t.status ?? "RECORDED")], ["Reason", t.reason ?? "—"], ["Context", `${getContext().symbol} — presentation only`]]), tech(t, "Raw trial"))),
    }) : emptyState({ icon: "archive", title: "No trials recorded yet", desc: "Failed experiments are knowledge: each eliminates search space. They appear here with same prominence as successes.", actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Run a campaign")] }),
  }));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Novelty & diversity — prevents rediscovering same idea", sub: "prevents double-counting", icon: "branch", body: novelty && novelty.total_trials != null ? h("div", { class: "stack" },
      h("div", { class: "stat-grid" }, stat({ label: "Total trials", value: fmtInt(novelty.total_trials) }), stat({ label: "Distinct hypotheses", value: fmtInt(novelty.distinct_hypotheses) }), stat({ label: "Largest cluster", value: fmtInt(novelty.largest_cluster_size), tone: novelty.largest_cluster_size > 3 ? "warn" : "ok", hint: "clusters >3 suggest duplicated idea" })),
      novelty.honest_note ? banner("info", "Honest note", novelty.honest_note, "info") : null,
    ) : emptyState({ icon: "branch", title: "No novelty analysis yet", desc: "Appears once experiments exist — QTS clusters hypotheses so one idea cannot be counted twice." }) }),
    card({ title: "Experiment governance", icon: "shield", body: h("ul", { class: "reason-list" }, h("li", null, "No hidden retries — every execution is one ledger row"), h("li", null, "Trial count N never reset (DSR honesty)"), h("li", null, "No deletion — failures persist with reasons"), h("li", null, "Budgets are hard caps, not suggestions")) }),
  ));
}

/* Strategies */
export async function renderStrategies(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({ crumb: "Research", group: "Strategies", title: "Strategy Library", answer: h("b", null, `Strategies are scientific objects: identity, thesis, mechanism, evidence grade. Context ${ctx.symbol}. High historical return alone never promotes.`), body: null }));
  const activity = h("h2", null, `Loading strategies… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / STRATEGIES"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let list = [];
  try { list = await api.get("/api/strategies"); } catch (e) { host.appendChild(errorBox({ what: "strategies could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${list.length} strategies — context ${getContext().symbol} — evidence graded`;

  if (!list.length) {
    host.appendChild(card({ body: emptyState({ icon: "flask", title: "No strategies registered", desc: "Strategies appear after campaigns surface surviving candidates. Empty library is honest starting state.", actions: [h("button", { class: "btn", onclick: () => navigate("#/research/campaigns") }, icon("play", 14), "Open Research")] }) }));
    return;
  }

  host.appendChild(card({
    title: `${list.length} registered — dense, drawer for thesis, keyboard navigable`, icon: "flask",
    body: denseTable({
      columns: [
        { key: "strategy_id", label: "Strategy", render: (s) => h("span", { class: "primary-cell mono small" }, s.strategy_id) },
        { key: "family", label: "Family", render: (s) => humanKey(s.feature_definition?.family ?? s.family ?? "—") },
        { key: "instrument", label: "Instrument", render: (s) => `${s.symbol ?? "—"} · ${s.timeframe ?? "—"}` },
        { key: "params", label: "Parameters", render: (s) => h("span", { class: "mono small text-dim" }, trunc(JSON.stringify(s.parameter_definition ?? {}), 40)) },
        { key: "hypothesis", label: "Thesis", render: (s) => h("span", { class: "small text-dim" }, trunc(s.hypothesis ?? "", 50)) },
        { key: "score", label: "Validation", render: (s) => h("button", { class: "btn ghost sm", onclick: (e) => { e.stopPropagation(); navigate("#/research/validation"); } }, "Scorecard") },
      ],
      rows: list,
      onRowClick: (s) => drawer(s.strategy_id, h("div", { class: "stack" },
        kv([["Name", s.name ?? "—"], ["Version", s.version ?? "—"], ["Market", `${s.market ?? "—"} ${s.symbol ?? ""} ${s.timeframe ?? ""}`], ["Data manifest", h("span", { class: "mono small" }, s.data_manifest ?? "—")], ["Context", `${getContext().symbol} — presentation only`]]),
        h("div", null, h("div", { class: "eyebrow" }, "Thesis"), h("p", { class: "text-dim small" }, s.hypothesis ?? "—")),
        h("details", null, h("summary", null, "Feature definition / technical — summary → detail → raw"), tech(s.feature_definition, "Show features")),
        h("button", { class: "btn primary", onclick: () => { closeDrawer(); navigate("#/research/validation"); } }, icon("pulse", 14), "Open validation scorecard"),
      )),
    }),
  }));
}

/* Validation */
export async function renderValidation(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  const head = page({ crumb: "Research", group: "Validation", title: "Validation Scorecard", answer: h("b", null, `Does evidence support hypothesis? Every gate must pass on its own merits — fail-closed. Context ${ctx.symbol}.`), body: null });
  root.appendChild(head);
  const pick = h("select", { class: "input", style: { maxWidth: "260px" } });
  const host = h("div", { class: "section" }); root.appendChild(host);
  let ids = [];
  try { ids = (await api.get("/api/strategies")).map((s) => s.strategy_id); } catch { ids = []; }
  if (!ids.length) ids = ["sma_breakout"];
  ids.forEach((s) => pick.appendChild(h("option", { value: s }, s)));
  head.querySelector(".page-actions").append(pick, h("button", { class: "btn primary", onclick: () => load(pick.value) }, icon("pulse", 14), "Load scorecard"));

  async function load(strategyId) {
    host.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-body" }, h("div", { class: "skeleton skl-line", style: { width: "60%" } }), h("div", { class: "skeleton skl-line", style: { width: "80%" } }))));
    let v;
    try { v = await api.get(`/api/validation/${encodeURIComponent(strategyId)}`); } catch (e) { host.replaceChildren(errorBox({ what: `validation for ${strategyId} could not be loaded`, next: "Pick another strategy or retry.", raw: e.message })); return; }
    host.replaceChildren(scorecard(strategyId, v));
  }
  await load(ids[0]);
}

function scorecard(strategyId, v) {
  const attr = v.attribution;
  if (attr && attr.attributed === false) {
    // The file on disk is disclosed, not hidden, and is not this strategy's result.
    return h("div", { class: "stack" },
      banner("err", "UNATTRIBUTED — this file is not this strategy's validation", attr.reason ?? "evidence does not name this strategy", "shield"),
      card({
        title: "On-disk validation file — not a scorecard",
        sub: `requested ${strategyId} · evidence strategy_id ${attr.evidence_strategy_id ?? "none"}`,
        icon: "fileCheck",
        body: h("div", { class: "stack" },
          h("p", { class: "gate-note" }, "Gates below are not rendered. A file that does not name this strategy is not its pass or its block."),
          h("details", null, h("summary", null, "Raw file — disclosed, not attributed"), tech(v.evidence ?? {}, "Raw validation file")),
        ),
      }),
    );
  }
  const ev = v.evidence ?? {};
  const edge = ev.edge_survival ?? {};
  const verdict = v.decision ?? v.verdict ?? (edge.passed ? "PASS" : "BLOCK");
  const chips = h("div", { class: "chip-row" },
    h("span", { class: "chip" }, `trials N=${ev.trial_ledger?.trial_count ?? "?"}`),
    h("span", { class: "chip" }, `PSR ${fmtNum3(edge.psr)}`),
    h("span", { class: "chip" }, `DSR ${fmtNum3(edge.dsr)}`),
    h("span", { class: "chip" }, `PBO ${fmtNum3(edge.pbo)}`),
    h("span", { class: "chip" }, `context ${getContext().symbol}`),
  );

  const gate = (name, ok, detail) => h("div", { class: `check ${ok === true ? "pass" : ok === false ? "fail" : "na"}` },
    h("div", { class: "mark", "aria-hidden": "true" }, ok === true ? "✓" : ok === false ? "✕" : "○"),
    h("div", null, h("div", { class: "name" }, name), detail ? h("div", { class: "detail" }, detail) : null));

  const ds = ev.dataset ?? {};

  // Executive Opportunity Classification (Section 10)
  const isPass = verdict === "PASS";
  const oppClassification = isPass ? "CANDIDATE_READY" : "BLOCKED_OR_REJECTED";
  const oppBadge = isPass
    ? h("span", { class: "badge ok lg" }, "VALIDATED CANDIDATE")
    : h("span", { class: "badge err lg" }, "BLOCKED / REJECTED");

  const oppSummary = card({
    title: "Opportunity Evaluation — Plain Language Disposition",
    sub: `Strategy: ${strategyId} · Scientific status: ${isPass ? "SURVIVED GATES" : "CONTAINED IN RESEARCH"}`,
    icon: "shield",
    actions: [oppBadge],
    body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({ label: "Opportunity Status", value: isPass ? "VALIDATED CANDIDATE" : "NO VALIDATED EDGE", tone: isPass ? "ok" : "err", hint: isPass ? "Passed research gates" : "Contained in research", icon: "flask" }),
        stat({ label: "Evaluation Phase", value: isPass ? "READY FOR DEMO" : "RESEARCH BLOCKED", tone: isPass ? "ok" : "warn", hint: "Fail-closed threshold enforced", icon: "branch" }),
        stat({ label: "Evidence Survival", value: edge.passed ? "PASSED" : "FAILED", tone: edge.passed ? "ok" : "err", hint: "Multi-testing corrected", icon: "activity" }),
        stat({ label: "Data Quality Gate", value: ds.quality_passed ? "PASSED" : "NOT READY", tone: ds.quality_passed ? "ok" : "warn", hint: "Requires complete data", icon: "database" }),
      ),
      h("p", { class: "text-dim small", style: { marginTop: "6px" } },
        isPass
          ? "This candidate strategy survived out-of-sample stress testing, Deflated Sharpe Ratio (DSR), and Probability of Backtest Overfitting (PBO). It is scientifically eligible to be registered for forward demo observation. Real-money live trading remains structurally locked."
          : "This strategy does not have certified edge survival. In trading research, rejecting weak or overfitted candidates is success — it prevents real capital risk. The strategy is safely contained in research.",
      ),
    ),
  });

  return h("div", { class: "stack" },
    oppSummary,
    banner(verdict === "PASS" ? "ok" : "err", `VERDICT: ${verdict === "PASS" ? "EVIDENCE SUPPORTS — next gates apply" : "BLOCK — evidence does not support promotion"}`, verdict === "PASS" ? `One gate; forward observation, demo and governance still apply. Context ${getContext().symbol}.` : "Strategy stays in research. Weak evidence discarded before it can cost money.", verdict === "PASS" ? "check" : "shield"),
    card({ title: `Multiple-testing corrected edge — strategy: ${strategyId} — context ${getContext().symbol}`, sub: `trials N=${ev.trial_ledger?.trial_count ?? "?"}`, icon: "pulse", actions: [chips], body:
      h("div", { class: "check-grid" },
        gate("Edge survival (all checks)", edge.passed, "OOS + PSR + DSR + PBO + WFE + cost break-even"),
        gate("Null control rejected", ev.null_control?.rejected, `${(ev.null_control?.control_sharpes ?? []).length} null strategies`),
        gate("Placebo rejected", ev.placebo?.rejected, `${(ev.placebo?.placebo_sharpes ?? []).length} placebo tests`),
        // Presence of an object is not a pass. cost_robustness exists on files
        // whose own edge_survival.checks.cost is false.
        gate("Cost robustness", edge.checks?.cost === true ? true : edge.checks?.cost === false ? false : null, ev.cost_robustness?.stress ? `stress: ${trunc(JSON.stringify(ev.cost_robustness.stress),80)}` : "no explicit cost check"),
        gate("Locked test partition", ds.locked_partition?.is_frozen === true ? true : ds.locked_partition?.is_frozen === false ? false : null, `is_frozen=${ds.locked_partition?.is_frozen ?? "not recorded"} — a partition object is not proof the test set was unused`),
        gate("Dataset quality", ds.quality_passed, `${(ds.quality_checks ?? []).length} ingestion checks`),
      ),
    }),
    h("div", { class: "grid-2" },
      card({ title: "Regime robustness — explanatory, not decorative", icon: "activity", body:
        (ev.regime ?? []).length
          ? denseTable({ columns: [{ key: "regime", label: "Regime" }, { key: "sharpe", label: "Sharpe", num: true, render: (r) => fmtNum3(r.sharpe) }, { key: "trades", label: "Trades", num: true }, { key: "passed", label: "State", render: (r) => badge(r.passed ? "PASS" : "FAIL") }], rows: ev.regime, empty: "No regime breakdown." })
          : emptyState({ icon: "activity", title: "No regime evidence yet", desc: "Regime splits appear after campaigns run across varied market states." }),
      }),
      card({ title: "Forward evidence — honesty ledger", icon: "eye", body: emptyState({ icon: "eye", title: "No forward evidence yet", desc: "Forward observation and demo results appear only after real sessions run. Backtests never substitute." }) }),
    ),
    card({ title: "Discovery provenance", icon: "fileCheck", body: h("div", { class: "stack" }, kv([["Dataset manifest", h("span", { class: "mono small" }, ds.manifest ?? "—")], ["Quality checks", `${(ds.quality_checks ?? []).length} recorded`], ["Context", `${getContext().symbol} — presentation only`]]), h("details", null, h("summary", null, "Raw validation evidence / technical — summary → detail → raw"), tech(ev, "Raw validation evidence")))}),
  );
}
const fmtNum3 = (x) => (x == null) ? "—" : Number(x).toFixed(3);

/* Memory */
export async function renderMemory(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({ crumb: "Research", group: "Memory", title: "Research Memory", answer: h("b", null, `Durable knowledge of what was tested, why it failed, and what was unstable — so QTS never pays twice for same lesson. Context ${ctx.symbol}. Dense table, keyboard navigable.`), body: null }));
  const activity = h("h2", null, `Loading memory… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / MEMORY"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let mem = [], statStack = null;
  try { [mem, statStack] = await Promise.all([api.get("/api/research/memory?limit=30"), api.get("/api/research/statistical")]); } catch (e) { host.appendChild(errorBox({ what: "research memory could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${mem.length} findings — context ${getContext().symbol} — failures are permanent knowledge`;

  host.appendChild(card({
    title: "Findings — failed hypotheses kept with reasons — negative results are permanent knowledge", sub: `context ${getContext().symbol}`, icon: "brain",
    body: (mem ?? []).length ? denseTable({
      columns: [
        { key: "id", label: "Finding", render: (m) => h("span", { class: "primary-cell small" }, trunc(m.hypothesis_id ?? m.id ?? m.summary ?? "—", 40)) },
        { key: "outcome", label: "Outcome", render: (m) => badge(m.status ?? m.outcome ?? "RECORDED") },
        { key: "reason", label: "Why", render: (m) => h("span", { class: "small text-dim" }, trunc(m.reason ?? m.lesson ?? "", 100)) },
        { key: "when", label: "Recorded", render: (m) => h("span", { class: "small mono text-dim" }, m.timestamp ? fmtUtc(m.timestamp) : "—") },
      ],
      rows: mem, empty: "Memory empty.",
    }) : emptyState({ icon: "brain", title: "No findings recorded yet", desc: "As experiments run, disproven assumptions accumulate here." }),
  }));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Statistical stack — multiple-testing defenses — used by every gate", sub: "explanatory, not decorative", icon: "scale", body: statStack ? h("div", { class: "stack" },
      Object.entries(statStack).filter(([, v]) => typeof v === "object").map(([k, v]) =>
        h("div", { class: "check pass", style: { borderColor: "var(--line)" } },
          h("div", { class: "mark", style: { background: "var(--research-bg)", color: "var(--research-text)", borderColor: "var(--research-line)" } }, "∑"),
          h("div", null, h("div", { class: "name" }, humanKey(k)), h("div", { class: "detail" }, v.purpose ?? ""), v.p_value != null ? h("div", { class: "detail" }, `p=${v.p_value}`) : null),
        ),
      ),
      h("details", null, h("summary", null, "Raw statistical stack / technical — summary → detail → raw"), tech(statStack, "Raw statistical stack")),
    ) : emptyState({ icon: "scale", title: "Statistical stack unavailable" }) }),
    card({ title: "Why failures matter", icon: "info", body: h("div", { class: "stack" }, banner("info", "No-exploitable-edge is valid outcome", "If research proves no durable edge under honest costs, that is success of method — not failure of QTS.", "info"), h("p", { class: "gate-note" }, "Every disproven hypothesis narrows search space. Memory makes next campaign cheaper."))}),
  ));
}

/* Data observatory */
export async function renderData(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({ crumb: "Research", group: "Data", title: "Data Observatory", answer: h("b", null, `What data QTS has, how good it is, and what is missing — explicit REAL vs SYNTHETIC labeling on every field. Context ${ctx.symbol}. High density, no interpolation.`), body: null }));
  const activity = h("h2", null, `Loading data inventory… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / DATA"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let audit = null, inv = [], quality = null;
  try { [audit, inv, quality] = await Promise.all([api.get("/api/research/data-audit"), api.get("/api/research/data-inventory"), api.get("/api/research/data-quality-adversarial")]); } catch (e) { host.appendChild(errorBox({ what: "data observatory could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${audit?.count ?? 0} source(s) — ${inv.length} dataset(s) — context ${getContext().symbol} — provenance explicit`;

  const need = audit?.minimum_expansion_needed ?? {};
  host.appendChild(h("div", { class: "grid-2" },
    card({ title: `Available data — dense, provenance explicit — context ${ctx.symbol}`, sub: audit?.count != null ? `${audit.count} source(s)` : null, icon: "database", body:
      denseTable({
        columns: [
          { key: "instrument", label: "Instrument" },
          { key: "timeframe", label: "TF" },
          { key: "rows", label: "Rows", num: true, render: (d) => fmtInt(d.rows) },
          { key: "range", label: "Range", render: (d) => h("span", { class: "small mono text-dim" }, `${d.start} → ${d.end}`) },
          { key: "bid_ask", label: "Bid/Ask", render: (d) => badge(d.bid_ask_available ? "REAL" : "SYNTHETIC") },
          { key: "ts", label: "Timestamps", render: (d) => badge(d.timestamp_quality ?? "UNAVAILABLE") },
        ],
        rows: audit?.available_sources ?? [], empty: "No data sources ingested.",
      }),
    }),
    card({ title: "Minimum expansion needed — what must be acquired before claims strengthen", sub: "what missing, why", icon: "alert", body:
      Object.keys(need).length ? kv(Object.entries(need).map(([k, v]) => [k, h("span", { class: "small" }, v)])) : emptyState({ icon: "check", title: "No gaps recorded", desc: "Audit did not report expansion requirements." }),
    }),
  ));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Dataset inventory & lineage inputs — immutable, checksummed", icon: "branch", body:
      denseTable({
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
    card({ title: "Fail-closed quality stress — must fail closed, never silently pass", icon: "shield", body: quality ? h("div", { class: "stack" },
      h("div", { class: "check-grid" },
        h("div", { class: `check ${quality.duplicate_corrupted_passed ? "pass" : "fail"}` }, h("div", { class: "mark" }, quality.duplicate_corrupted_passed ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Duplicate / corrupted rows"), h("div", { class: "detail" }, "injected faults must be caught"))),
        h("div", { class: `check ${quality.missing_corrupted_gap_check ? "pass" : "fail"}` }, h("div", { class: "mark" }, quality.missing_corrupted_gap_check ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Missing-data gap detection"), h("div", { class: "detail" }, "gaps must fail closed, never interpolate silently"))),
      ),
      quality.fail_closed_principle ? banner("info", "Principle", quality.fail_closed_principle, "info") : null,
    ) : emptyState({ icon: "shield", title: "Quality stress unavailable" }) }),
  ));

  host.appendChild(card({ title: "Labeling contract — truth is visual design", icon: "fileCheck", body: h("div", { class: "stack" },
    h("div", { class: "chip-row" }, h("span", { class: "prov real" }, "REAL"), h("span", { class: "prov synthetic" }, "SYNTHETIC"), h("span", { class: "prov synthetic" }, "SIMULATED"), h("span", { class: "prov synthetic" }, "ESTIMATED"), h("span", { class: "prov" }, "IMPUTED"), h("span", { class: "prov demo" }, "BROKER-DERIVED"), h("span", { class: "prov" }, "MODEL-DERIVED")),
    h("p", { class: "gate-note" }, "CSV imports remain provenance-bound; the registered Dukascopy dataset is REAL historical mid-price OHLC, not MT5 broker history. Bid/ask and spread are UNAVAILABLE in those bars; high-low is never a measured spread. DEMO_FORWARD observations remain DEMO, not historical REAL. Every badge carries source prefix. Context syncs, never permission."),
    audit?.never_substitute ? banner("warn", "Never substitute", audit.never_substitute, "alert") : null,
  )}));

  host.appendChild(card({ title: "External source catalog — researched providers for closing gaps", sub: "depth, granularity, licensing, cost, suitability", icon: "book", body: (async () => {
    try { const cat = await api.get("/api/research/data-source-catalog"); return tech(cat, "Show provider catalog — summary → detail → raw"); } catch { return emptyState({ icon: "book", title: "Catalog unavailable" }); }
  })() }));
}
