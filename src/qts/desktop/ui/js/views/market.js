/* Market — Monitor (quotes/regime/quality) · Observations · Data quality · Lineage
   Flat, dense, honest empties. Context synchronized across windows via context.js */

import { api, store, RESOURCES, syncResource, poll } from "../api.js";
import { operationalState, freshness } from "../operations.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  spark, barList, banner, toast, checkGrid, provStrip, freshStamp, timeline,
} from "../components.js";
import { fmtInt, fmtNum, fmtUtc, fmtAge, humanKey, trunc, fmtMetric } from "../format.js";
import { navigate, onDispose } from "../router.js";
import { getContext, setContext, onContext } from "../context.js";

/* Monitor */
export async function renderMonitor(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");

  const ctx = getContext();
  const ctxBadge = h("span", { class: "badge neutral" }, `${ctx.symbol} · ${ctx.timeframe}`);
  const symInput = h("input", { class: "input", style: { maxWidth: "120px" }, value: ctx.symbol, "aria-label": "Symbol context" });
  const tfInput = h("select", { class: "input", style: { maxWidth: "90px" }, "aria-label": "Timeframe context" },
    ["1M","5M","15M","1H","4H","1D"].map((tf) => h("option", { value: tf, selected: tf === ctx.timeframe }, tf)));
  const applyCtx = h("button", { class: "btn sm", onclick: () => { setContext({ symbol: symInput.value.trim().toUpperCase(), timeframe: tfInput.value }); toast("ok","Context updated",`${symInput.value} · ${tfInput.value} — syncs across windows`); } }, "Set context");

  root.appendChild(page({
    crumb: "Market", group: "Monitor",
    title: "Market Monitor",
    answer: h("b", null, "What the market looks like through QTS's data pipeline — quotes, regime, freshness — with provenance and honest empty states. Pipeline health is not quote freshness. Context syncs across windows via BroadcastChannel."),
    actions: [ctxBadge, symInput, tfInput, applyCtx, h("button", { class: "btn", onclick: () => refresh(true) }, icon("refresh", 14), "Refresh sources")],
    body: null,
  }));

  const activity = h("h2", null, "Loading market evidence…");
  const next = h("a", { class: "btn primary", href: "#/market/observations" }, "Open observations");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / MARKET"), activity),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT"), next, nextWhy)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section" }); root.appendChild(host);
  let lastManifest = null, lastRegime = null, lastAdv = null;

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["market", "Market data pipeline", s.market, "Backend pipeline status, not proof of live quote."],
      ["quoteAge", "Collected quote age", s.quoteAge, "Age of last broker event, not API freshness."],
      ["observation", "Observation collector", s.observation, s.obs?.note || "Collector state"],
      ["mode", "Environment / mode", s.mode.mode, s.mode.blurb],
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
      const resKey = key === "market" || key === "mode" ? "health" : "observe";
      const meta = store.data.resources[resKey];
      const f = meta ? freshness(meta, resKey) : { label: "UNAVAILABLE", current: false };
      c.fresh.textContent = `${f.label}${meta?.updatedAt ? ` · ${fmtAge(meta.updatedAt)}` : ""}`;
    }
    activity.textContent = `${s.market} · ${s.observation} · ${s.quoteAge} · context ${getContext().symbol}`;
    nextWhy.textContent = s.obs?.state === "OBSERVING" ? "Collector reports OBSERVING. Inspect quote timestamps and provenance." : "No active collection. Start observation if terminal connected.";
  }

  async function refresh(force = false) {
    try {
      const [manifest, regime, adv] = await Promise.all([
        api.get("/api/research/forward-manifest"),
        api.get("/api/research/regime-observations"),
        api.get("/api/research/data-quality-adversarial"),
      ]);
      lastManifest = manifest; lastRegime = regime; lastAdv = adv;
      if (force) await Promise.all(Object.keys(RESOURCES).map((k) => syncResource(k, { force: true })));
      render();
    } catch (e) {
      host.replaceChildren(errorBox({ what: "market data could not be loaded", next: "Retry; if API down, restart QTS.", raw: e.message }));
    }
  }

  function render() {
    if (!lastManifest) return;
    renderFacts();
    const manifest = lastManifest, regime = lastRegime, adv = lastAdv;
    const ticks = manifest.sample_ticks ?? [];
    const last = ticks[ticks.length - 1];
    const currentCtx = getContext();
    ctxBadge.textContent = `${currentCtx.symbol} · ${currentCtx.timeframe} — synced`;

    const content = h("div", { class: "stack" });
    content.appendChild(h("section", { class: "operator-section" },
      h("h2", null, "Operating facts — pipeline health vs quote freshness"),
      h("div", { class: "tbl-wrap" },
        h("table", { class: "tbl facts-table" },
          h("thead", null, h("tr", null, ["Source","Reported state","Meaning / constraint","API freshness"].map((t) => h("th", { scope: "col" }, t)))),
          factsBody))));

    content.appendChild(h("div", { class: "grid-2" },
      card({
        title: "Current quote — last recorded tick, not live market", sub: last ? `latest recorded · ${last.symbol ?? ""} — context ${currentCtx.symbol}` : "no tick recorded", icon: "activity",
        actions: [last ? provStrip(last.provenance ?? last.data_class ?? "SYNTHETIC") : null],
        body: last
          ? h("div", { class: "stack" },
              h("div", { class: "quote" },
                h("div", { class: "q-side" }, h("span", { class: "q-label" }, "BID"), h("span", { class: "q-value bid" }, fmtNum(last.bid))),
                h("div", { class: "q-side" }, h("span", { class: "q-label" }, "ASK"), h("span", { class: "q-value ask" }, fmtNum(last.ask))),
                h("div", { class: "q-side" }, h("span", { class: "q-label" }, "SPREAD"), h("span", { class: "q-value" }, `${fmtNum(last.spread_bps, 1)} bps`)),
              ),
              h("div", { class: "meta" }, `broker time ${last.broker_time ?? "—"} · canonical UTC ${fmtUtc(last.timestamp ?? last.canonical_ts)} · basis ${last.timestamp_basis ?? "canonical-UTC"}`),
              h("div", { class: "meta" }, `API freshness ${freshness(store.data.resources.observe, "observe").label} — quote age is separate from API receipt`),
              ticks.length >= 2
                ? [h("div", { class: "chart-block" }, spark(ticks.map((t) => (Number(t.bid) + Number(t.ask)) / 2), { height: 70 })),
                   h("div", { class: "chart-caption" }, h("span", { class: "cap-item" }, `${ticks.length} real recorded ticks`), h("span", { class: "cap-item" }, "source: forward observation"), h("span", { class: "cap-item" }, "mid = (bid+ask)/2, no interpolation"), h("span", { class: "cap-item" }, `context ${currentCtx.symbol} — chart is explanatory, not predictive`))]
                : banner("info", "Not enough observations yet", "Chart appears after ≥2 recorded ticks — QTS never fabricates history.", "info"),
            )
          : emptyState({
              icon: "activity", title: "No real observations recorded yet",
              desc: "Quotes appear once observation records real broker ticks. Observation is order-free. Pipeline HEALTHY does not mean a fresh quote exists.",
              actions: [h("button", { class: "btn primary", onclick: () => navigate("#/market/observations") }, icon("play", 14), "Start Observation")],
            }),
      }),
      card({
        title: "Regime picture", sub: regime?.count != null ? `${fmtInt(regime.count)} observations — not a strategy signal` : null, icon: "pulse",
        body: regime?.volatility_distribution
          ? h("div", { class: "stack" },
              barList([
                { label: "Low volatility", value: regime.volatility_distribution.low ?? 0, max: regime.count ?? 1, tone: "" },
                { label: "Normal", value: regime.volatility_distribution.normal ?? 0, max: regime.count ?? 1, tone: "ok" },
                { label: "High volatility", value: regime.volatility_distribution.high ?? 0, max: regime.count ?? 1, tone: "warn" },
              ]),
              regime.trend_strength_avg != null ? h("div", { class: "meta" }, `avg trend strength ${fmtNum(regime.trend_strength_avg, 3)} — descriptive, not predictive`) : null,
              (regime.transitions ?? []).length
                ? [h("div", { class: "eyebrow mt-3" }, "Recent transitions"), timeline((regime.transitions ?? []).slice(0, 6).map((t) => ({ when: fmtUtc(t.time), what: `${t.symbol ?? ""} ${t.from ?? "?"} → ${t.to ?? "?"}`, tone: "" })))]
                : null,
            )
          : emptyState({ icon: "pulse", title: "No regime observations", desc: "Regime classification starts once observation records real ticks." }),
      }),
    ));

    content.appendChild(card({
      title: "Data quality — adversarial stress must fail closed", sub: "corrupted input never passes silently", icon: "shield",
      body: adv ? h("div", { class: "check-grid" },
        h("div", { class: `check ${adv.duplicate_corrupted_passed ? "pass" : "fail"}` }, h("div", { class: "mark" }, adv.duplicate_corrupted_passed ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Duplicate & corrupted rows"), h("div", { class: "detail" }, "faults injected on purpose are caught"))),
        h("div", { class: `check ${adv.missing_corrupted_gap_check ? "pass" : "fail"}` }, h("div", { class: "mark" }, adv.missing_corrupted_gap_check ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Gap detection"), h("div", { class: "detail" }, "missing ranges block rather than interpolate"))),
        adv.zero_price_error ? h("div", { class: "check fail" }, h("div", { class: "mark" }, "■"), h("div", null, h("div", { class: "name" }, "Zero-price guard"), h("div", { class: "detail" }, adv.zero_price_error))) : null,
      ) : emptyState({ icon: "shield", title: "Quality stress results unavailable" }),
    }));

    if (manifest.canonical_store) content.appendChild(h("details", null, h("summary", null, "Raw forward-observation manifest / technical"), tech(manifest, "Raw manifest")));
    host.replaceChildren(content);
  }

  const off = store.on("resources", renderFacts);
  const offCtx = onContext(() => { ctxBadge.textContent = `${getContext().symbol} · ${getContext().timeframe} — synced`; renderFacts(); });
  onDispose(root, () => { off(); offCtx(); });
  await refresh();
}

/* Observations */
export async function renderObservations(root) {
  skeletonInto(root, "stats");
  let refreshing = false, acting = false;
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Market", group: "Observations",
    title: "Forward Observatory",
    answer: h("b", null, "Real broker ticks recorded with zero capital exposure. Observation never submits orders — it builds evidence research requires. Recorded count is not complete tick history."),
    actions: [
      h("button", { id: "obs-start", class: "btn primary", onclick: () => act("start") }, icon("play", 14), "Start Observation"),
      h("button", { id: "obs-stop", class: "btn danger", onclick: () => act("stop") }, icon("stop", 14), "Stop"),
      h("button", { class: "btn", onclick: refresh }, icon("refresh", 14), "Refresh"),
    ],
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let lastManifest = null;
  const stamp = freshStamp(() => lastManifest?.generated_at, 1000);
  host.appendChild(stamp);
  const sourceStatus = h("p", { class: "text-dim small", role: "status" }, "Loading observation sources…");
  host.before(sourceStatus);

  async function refresh() {
    if (refreshing || !root.isConnected) return;
    refreshing = true;
    let obs, manifest, execReality;
    try {
      [obs, manifest, execReality] = await Promise.all([
        api.get("/api/observe/status"),
        api.get("/api/research/forward-manifest"),
        api.get("/api/research/execution-reality"),
      ]);
    } catch (e) {
      sourceStatus.textContent = "STALE / UNAVAILABLE — refresh failed. Last-known evidence may remain below; collector activity not established. Retrying while visible.";
      if (!lastManifest) {
        clear(host); host.appendChild(stamp);
        host.appendChild(errorBox({ what: "observation status could not be loaded", next: "Retry; collector activity cannot be established while source unavailable.", raw: e.message }));
      }
      return;
    } finally { refreshing = false; }
    if (!root.isConnected) return;
    sourceStatus.textContent = "CURRENT API snapshot — quote timestamps and manifest generation time are separate. Updated " + fmtUtc(Date.now());
    lastManifest = manifest;
    const running = obs.state === "OBSERVING" && obs.thread_alive === true;
    store.set("observe", obs);
    root.querySelector("#obs-start").disabled = acting || running;
    root.querySelector("#obs-stop").disabled = acting || !running;

    const body = h("div", { class: "stack" });
    body.appendChild(h("div", { class: "stat-grid" },
      stat({ label: "Session state", value: running ? "OBSERVING" : String(obs.state ?? "IDLE").toUpperCase(), tone: running ? "run" : "neutral", icon: "eye", hint: obs.note ?? null }),
      stat({ label: "Ticks recorded", value: fmtInt(manifest.ticks_recorded), icon: "database", hint: `${fmtInt(manifest.real_market_ticks)} real-market — not complete tick history` }),
      stat({ label: "Signals recorded", value: fmtInt(manifest.signals_recorded), icon: "zap", hint: "store-wide count; FO-R1 requires zero session signals" }),
      stat({ label: "Orders submitted", value: fmtInt(obs.orders_submitted), tone: Number(obs.orders_submitted) === 0 ? "ok" : "err", hint: "must always be 0 during observation — collector scope, not terminal-wide proof" }),
    ));

    const byProv = manifest.ticks_by_provenance ?? {};
    if (Object.keys(byProv).length) {
      body.appendChild(h("div", { class: "row" },
        h("span", { class: "eyebrow" }, "Ticks by provenance"),
        Object.entries(byProv).map(([p, n]) => [provStrip(p), h("span", { class: "badge-mini" }, fmtInt(n))]),
      ));
    }

    const ticks = manifest.sample_ticks ?? [];
    body.appendChild(card({
      title: "Recorded ticks — dense, sortable, keyboard navigable", sub: `${ticks.length} shown of ${fmtInt(manifest.ticks_recorded)}`, icon: "activity",
      actions: [h("span", { class: "meta" }, "live view — updates every 5s while visible, context synced")],
      body: ticks.length
        ? table({
            columns: [
              { key: "timestamp", label: "Time (UTC)", render: (t) => h("span", { class: "mono small" }, fmtUtc(t.timestamp)) },
              { key: "bid", label: "Bid", num: true, render: (t) => fmtNum(t.bid) },
              { key: "ask", label: "Ask", num: true, render: (t) => fmtNum(t.ask) },
              { key: "spread", label: "Spread", num: true, render: (t) => `${fmtNum(t.spread_bps, 1)} bps` },
              { key: "session", label: "Session", render: (t) => t.session ?? "—" },
              { key: "regime", label: "Regime", render: (t) => t.regime ?? "—" },
              { key: "prov", label: "Provenance", render: (t) => provStrip(t.provenance ?? t.data_class ?? "") },
              { key: "anom", label: "Anomaly", render: (t) => t.anomaly && t.anomaly !== "none" ? badge("WARNING") : h("span", { class: "text-faint small" }, "none") },
            ],
            rows: [...ticks].reverse(),
            empty: "No ticks yet.",
            dense: true,
          })
        : emptyState({
            icon: "activity", title: "No real observations recorded yet",
            desc: running ? "Session is starting — ticks appear here as broker streams them." : "Start an observation session. QTS records bid/ask/spread/regime with zero orders. A DEMO terminal is required; in development this honestly stays empty.",
            actions: running ? null : [h("button", { class: "btn primary", onclick: () => act("start") }, icon("play", 14), "Start Observation")],
          }),
    }));

    body.appendChild(h("div", { class: "grid-2" },
      card({ title: "Execution reality — honesty ledger", sub: "real fills vs expectations", icon: "scale", body:
        execReality && execReality.count > 0
          ? kv([["Real executions", fmtInt(execReality.count)], ["Avg slippage", fmtMetric(execReality.measured_metrics?.avg_slippage_bps)]])
          : emptyState({
              icon: "scale", title: "No real executions recorded",
              desc: "Slippage, latency and fill quality become measurable only with real (demo) executions. Until then UNAVAILABLE — never zero, never estimate.",
            }),
      }),
      card({ title: "Recorded signals — FO-R1 requires zero", icon: "zap", body:
        (manifest.sample_signals ?? []).length
          ? table({
              columns: [
                { key: "timestamp", label: "Time (UTC)", render: (s) => h("span", { class: "mono small" }, fmtUtc(s.timestamp)) },
                { key: "signal", label: "Signal", render: (s) => badge(String(s.signal ?? s.state ?? "").toUpperCase() === "NO_TRADE" ? "NO_TRADE" : "SIGNAL") },
                { key: "strategy", label: "Strategy", render: (s) => s.strategy_id ?? "—" },
                { key: "why", label: "Detail", render: (s) => h("span", { class: "small text-dim" }, trunc(s.reason ?? s.detail ?? "", 60)) },
              ],
              rows: manifest.sample_signals, empty: "No signals yet.", dense: true,
            })
          : emptyState({ icon: "zap", title: "No signals recorded yet", desc: "Research-grade observation requires zero session signals. Legacy strategy records, if any, are separate evidence." }),
      }),
    ));

    clear(host);
    host.appendChild(stamp);
    host.appendChild(body);
  }

  async function act(kind) {
    if (acting) return;
    acting = true;
    root.querySelectorAll("#obs-start, #obs-stop").forEach((b) => { b.disabled = true; });
    sourceStatus.textContent = kind === "start" ? "REQUESTING observation — waiting for backend readiness and collector state…" : "STOPPING observation — waiting for terminal state…";
    try {
      if (kind === "start") {
        const result = await api.post("/api/observe/start");
        if (result.status?.state !== "OBSERVING") throw new Error(result.note || result.status?.blocked_reasons?.join("; ") || "Backend did not confirm observation started");
        toast("ok", "Observation confirmed", "Collector reports OBSERVING — zero orders.");
      } else {
        await api.post("/api/observe/stop");
        toast("warn", "Observation stopped", "Session state preserved.");
      }
      await refresh();
    } catch (e) {
      const msg = typeof e.body === "object" && e.body?.detail ? (e.body.detail.detail ?? e.body.detail) : e.message;
      toast("err", `Could not ${kind} observation`, String(msg).slice(0, 140));
    } finally { acting = false; await refresh(); }
  }

  const stop = poll(refresh, 5000);
  onDispose(root, stop);
}

/* Quality */
export async function renderQuality(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  root.appendChild(page({ crumb: "Market", group: "Data quality", title: "Data Quality", answer: h("b", null, "Fail-closed validation of every dataset before it can feed research. Missing is blocked, not interpolated."), body: null }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let audit = null, adv = null;
  try { [audit, adv] = await Promise.all([api.get("/api/research/data-audit"), api.get("/api/research/data-quality-adversarial")]); }
  catch (e) { host.appendChild(errorBox({ what: "data quality could not be loaded", next: "Retry.", raw: e.message })); return; }

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Source audit — dense, provenance explicit", sub: `${audit?.count ?? 0} source(s) — fail-closed, 12 checks`, icon: "database", body:
      table({
        columns: [
          { key: "instrument", label: "Source", render: (s) => `${s.instrument} ${s.timeframe}` },
          { key: "rows", label: "Rows", num: true, render: (s) => fmtInt(s.rows) },
          { key: "bidask", label: "Bid/Ask", render: (s) => badge(s.bid_ask_available ? "available" : "SYNTHETIC proxy") },
          { key: "spread", label: "Spread", render: (s) => badge(String(s.spread_available ?? "UNAVAILABLE")) },
          { key: "ts", label: "Timestamps", render: (s) => badge(s.timestamp_quality ?? "—") },
        ],
        rows: audit?.available_sources ?? [], empty: "No sources.", dense: true,
      }),
    }),
    card({ title: "Adversarial stress — must fail closed", icon: "shield", body: adv ? checkGrid({
      "duplicate & corrupted caught": adv.duplicate_corrupted_passed,
      "gap detection": adv.missing_corrupted_gap_check,
    }, { "duplicate & corrupted caught": "faults injected; must be caught", "gap detection": "missing ranges must block, not interpolate" }) : null }),
  ));
  if (audit?.limitation) host.appendChild(banner("warn", "Known limitation", audit.limitation, "alert"));
  if (audit?.recommendation) host.appendChild(banner("info", "Recommended next acquisition", audit.recommendation, "info"));
  host.appendChild(h("details", null, h("summary", null, "Raw source audit / technical"), tech(audit, "Raw source audit")));
}

/* Lineage */
export async function renderLineage(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Market", group: "Lineage",
    title: "Data Lineage",
    answer: h("b", null, "Where did this number come from? Provider → raw → canonical → manifest → experiment → evidence. Any preprocessing change creates a NEW version."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let inv = [];
  try { inv = await api.get("/api/research/data-inventory"); }
  catch (e) { host.appendChild(errorBox({ what: "lineage could not be loaded", next: "Retry.", raw: e.message })); return; }

  const chain = ["Provider", "Raw storage (immutable)", "Validation", "Canonical dataset", "Manifest (checksum)", "Features", "Experiment", "Evidence"];
  host.appendChild(card({ title: "Lineage chain", sub: "old versions never mutated", icon: "branch", body:
    h("div", { class: "pipeline" }, chain.map((c, i) => [i > 0 && h("span", { class: "pipe-arrow", "aria-hidden": "true" }, "→"), h("span", { class: "pipe-stage reached" }, c)])),
  }));

  host.appendChild(card({ title: "Datasets — immutable, checksummed, version-locked", sub: "dense table, sortable, keyboard navigable", icon: "database", body:
    table({
      columns: [
        { key: "id", label: "Dataset", render: (d) => h("span", { class: "primary-cell mono small" }, `${d.instrument} ${d.timeframe}`) },
        { key: "provider", label: "Provider", render: (d) => d.provider ?? "—" },
        { key: "rows", label: "Rows", num: true, render: (d) => fmtInt(d.row_count) },
        { key: "range", label: "Range", render: (d) => h("span", { class: "mono small text-dim" }, `${d.date_range?.start} → ${d.date_range?.end}`) },
        { key: "tz", label: "Timestamps", render: (d) => `${d.timezone} · ${d.timestamp_resolution}` },
      ],
      rows: inv,
      empty: "No datasets ingested yet.",
      dense: true,
    }),
  }));

  host.appendChild(card({ title: "Research quality gate — insufficient BLOCKs, never quietly passes", sub: "dense list, not decoration", icon: "shield", body:
    h("ul", { class: "reason-list" },
      h("li", null, "DATA QUALITY — ingestion checks must all pass"),
      h("li", null, "DATA DEPTH — minimum history depth per timeframe"),
      h("li", null, "DIVERSITY — symbols/timeframes/regimes"),
      h("li", null, "EXECUTION REALISM — real execution observations required"),
      h("li", null, "OOS COVERAGE + TRIAL COUNT + STATISTICAL EVIDENCE"),
    ),
  }));
  host.appendChild(banner("info", "Locked test partitions", "Test data is partitioned and locked before discovery begins; experiments physically cannot touch it during search (purged CPCV, embargo, monotonic time).", "lock"));
}
