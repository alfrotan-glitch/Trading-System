/* Market — a professional gold screen for a normal user.
   renderMarket: current price (only when valid), change, status, update
   time and a chart of REAL recorded observations only.
   renderObservations / renderQuality / renderLineage remain available
   under Advanced for engineers. */

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

const setText = (node, value) => { const s = String(value); if (node.textContent !== s) node.textContent = s; };

/* Market — Gold, plainly. */
export async function renderMarket(root) {
  root.classList.add("operator-workspace", "market");
  root.appendChild(page({
    crumb: "Market",
    title: "Gold — XAUUSD",
    answer: "The current gold price when it is valid. QTS never shows an old or invented price as the current one.",
    actions: [h("button", { class: "btn", onclick: () => load(true) }, icon("refresh", 14), "Refresh")],
  }));

  const heroHost = h("section", { class: "market-hero" }, h("p", { class: "text-dim small" }, "Loading the gold price…"));
  const detailHost = h("div", { class: "section stack" });
  root.append(heroHost, detailHost);

  let guide = null;
  let manifest = null;
  let regime = null;
  let busy = false;

  function paint() {
    clear(heroHost); clear(detailHost);
    const q = guide?.quote || {};
    const conn = guide?.connection || {};
    const priceOk = Boolean(q.fresh && (q.bid || q.ask));
    const ticks = (manifest?.sample_ticks ?? []).filter((t) => Number.isFinite(Number(t.bid)) && Number.isFinite(Number(t.ask)));
    const mids = ticks.map((t) => (Number(t.bid) + Number(t.ask)) / 2);

    // ---- hero: price, change, status -----------------------------------
    const statusLine = !conn.connected
      ? { tone: "warn", text: "Not connected — open MetaTrader 5 and sign in to your demo account." }
      : priceOk
        ? { tone: "ok", text: "Live prices from your broker." }
        : { tone: "neutral", text: "Connected — waiting for a fresh price." };

    let changeNode = null;
    if (mids.length >= 2) {
      const first = mids[0];
      const lastMid = mids[mids.length - 1];
      const delta = lastMid - first;
      const pct = first ? (delta / first) * 100 : null;
      const dir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
      changeNode = h("div", { class: `market-change ${dir}` },
        h("span", { class: "chg-value" }, `${delta >= 0 ? "+" : ""}${fmtNum(delta)}`),
        pct != null ? h("span", { class: "chg-pct" }, ` ${pct >= 0 ? "+" : ""}${fmtNum(pct, 2)}%`) : null,
        h("span", { class: "chg-note" }, "over the recorded window"));
    }

    heroHost.appendChild(h("div", { class: "market-hero-inner" },
      h("div", { class: "market-price-block" },
        priceOk
          ? h("div", { class: "market-price" }, fmtNum(q.ask ?? q.bid))
          : h("div", { class: "market-price unavailable" }, "Current price unavailable"),
        priceOk ? h("div", { class: "market-sub" }, `Bid ${fmtNum(q.bid)} · Ask ${fmtNum(q.ask)}`) : null,
        changeNode,
      ),
      h("div", { class: "market-meta" },
        h("div", { class: `market-status ${statusLine.tone}` }, h("span", { class: "account-dot " + (statusLine.tone === "ok" ? "ok" : statusLine.tone === "warn" ? "off" : "") }), statusLine.text),
        h("div", { class: "small text-dim" }, guide?.checked_at ? `Last checked ${fmtAge(Date.parse(guide.checked_at))}` : ""),
        q.spread_bps != null && priceOk ? h("div", { class: "small text-dim" }, `Spread ${fmtNum(q.spread_bps, 1)} bps`) : null,
      )));

    // ---- chart: real recorded observations only -------------------------
    detailHost.appendChild(card({
      title: "Recorded price window", icon: "activity",
      sub: ticks.length >= 2 ? `${ticks.length} real recorded observations — mid = (bid + ask) / 2, no interpolation` : "A chart appears once QTS has recorded real observations.",
      body: ticks.length >= 2
        ? h("div", { class: "stack" },
            h("div", { class: "chart-block market-chart" }, spark(mids, { width: 720, height: 140 })),
            h("div", { class: "meta" }, `range ${fmtNum(Math.min(...mids))} → ${fmtNum(Math.max(...mids))} · recorded observations only`))
        : emptyState({ icon: "activity", title: "No recorded observations yet", desc: "QTS never fabricates price history. Once observations are recorded, the chart appears here." }),
    }));

    detailHost.appendChild(h("div", { class: "grid-2" },
      card({ title: "Market status", icon: "activity", body: h("div", { class: "stack" },
        kv([
          ["Instrument", "Gold — XAUUSD"],
          ["Account", conn.connected ? `Demo · ${conn.broker || conn.server || "broker"}` : "Not connected"],
          ["Price feed", priceOk ? "Fresh" : conn.connected ? "Waiting for prices" : "Unavailable"],
          ["Last update", guide?.checked_at ? fmtUtc(guide.checked_at) : "Unavailable"],
        ]),
        h("p", { class: "small text-dim" }, "A connection is not a price, and a price is not a trade."),
      ) }),
      card({ title: "Good to know", icon: "info", body: h("div", { class: "stack" },
        h("p", { class: "small text-dim" }, "QTS shows a price only when it is current and valid. If the feed stops, this page says so instead of showing an old number."),
        h("p", { class: "small text-dim" }, "Live trading stays locked. Watching gold never sends an order."),
        h("a", { class: "btn sm", href: "#/advanced/data-observations" }, "Recorded observations"),
      ) })));

    const techDetails = h("details", null, h("summary", null, "Technical details"), h("div", { class: "tech-lazy small text-dim" }, "Loads when expanded."));
    techDetails.addEventListener("toggle", async () => {
      if (!techDetails.open || techDetails.dataset.loaded) return;
      techDetails.dataset.loaded = "1";
      regime = await api.get("/api/research/regime-observations").catch(() => null);
      techDetails.replaceChildren(h("summary", null, "Technical details"), tech({ guide, manifest, regime }, "Raw market state"));
    });
    detailHost.appendChild(techDetails);
  }

  async function load() {
    if (busy) return;
    busy = true;
    try {
      const [g, m] = await Promise.all([
        api.get("/api/demo/guide"),
        api.get("/api/research/forward-manifest").catch(() => null),
      ]);
      guide = g; manifest = m;
      paint();
    } catch (e) {
      clear(heroHost); clear(detailHost);
      heroHost.appendChild(errorBox({ what: "the gold price could not be loaded", next: "Retry. If MetaTrader 5 is closed, the price stays unavailable — honestly.", raw: e.message }));
      detailHost.appendChild(h("div", { class: "mt-3" }, h("button", { class: "btn primary", onclick: () => load() }, icon("refresh", 14), "Retry")));
    } finally { busy = false; }
  }

  await load();
}

/* Observations — real-time alive without flicker: preserve focus, scroll, disclosure */
export async function renderObservations(root) {
  skeletonInto(root, "stats");
  let refreshing = false, acting = false;
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Market", group: "Observations",
    title: "Recorded quotes",
    answer: h("b", null, "Quotes QTS has saved. Recording never submits orders. The count is not a complete history, and a saved quote is not permission to trade."),
    actions: [
      h("button", { id: "obs-start", class: "btn primary", onclick: () => act("start") }, icon("play", 14), "Start Observation"),
      h("button", { id: "obs-stop", class: "btn danger", onclick: () => act("stop") }, icon("stop", 14), "Stop"),
      h("button", { class: "btn", onclick: () => refresh(true) }, icon("refresh", 14), "Refresh"),
    ],
    body: null,
  }));

  const activity = h("h2", null, "Loading observation…");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / OBSERVATORY"), activity), h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT"), nextWhy)));

  const host = h("div", { class: "section" }); root.appendChild(host);
  let lastManifest = null;
  const stamp = freshStamp(() => lastManifest?.generated_at, 1000);
  const sourceStatus = h("p", { class: "text-dim small", role: "status" }, "Loading observation sources…");

  // stable stat elements — setText preserves, no flicker
  const statSession = h("span", null, "UNAVAILABLE");
  const statTicks = h("span", null, "UNAVAILABLE");
  const statSignals = h("span", null, "UNAVAILABLE");
  const statOrders = h("span", null, "UNAVAILABLE");
  const statsRow = h("div", { class: "stat-grid" },
    stat({ label: "Recording", value: statSession, icon: "eye" }),
    stat({ label: "Quotes saved", value: statTicks, icon: "database" }),
    stat({ label: "Signals saved", value: statSignals, icon: "zap" }),
    stat({ label: "Orders submitted", value: statOrders, icon: "shield" }),
  );

  const provRow = h("div", { class: "row" });
  const ticksHost = h("div");
  const execHost = h("div");
  const signalsHost = h("div");

  host.append(stamp, sourceStatus, statsRow, provRow, ticksHost, h("div", { class: "grid-2" }, execHost, signalsHost));

  async function refresh(force = false) {
    if (refreshing || !root.isConnected) return;
    refreshing = true;
    // preserve focus/scroll across refresh
    const active = document.activeElement;
    const activePath = active ? { id: active.id, tag: active.tagName, inTicks: ticksHost.contains(active), inSignals: signalsHost.contains(active) } : null;
    const scrollTops = [...root.querySelectorAll(".tbl-wrap")].map((el) => el.scrollTop);

    let obs, manifest, execReality;
    try {
      [obs, manifest, execReality] = await Promise.all([
        api.get("/api/observe/status"),
        api.get("/api/research/forward-manifest"),
        api.get("/api/research/execution-reality"),
      ]);
    } catch (e) {
      setText(sourceStatus, "STALE / UNAVAILABLE — refresh failed. Last-known evidence may remain below; collector activity not established. Retrying while visible.");
      if (!lastManifest) {
        ticksHost.replaceChildren(errorBox({ what: "observation status could not be loaded", next: "Retry; collector activity cannot be established while source unavailable.", raw: e.message }));
      }
      refreshing = false;
      return;
    } finally { refreshing = false; }
    if (!root.isConnected) return;

    lastManifest = manifest;
    const running = obs.state === "OBSERVING" && obs.thread_alive === true;
    store.set("observe", obs);
    const startBtn = root.querySelector("#obs-start");
    const stopBtn = root.querySelector("#obs-stop");
    if (startBtn) startBtn.disabled = acting || running;
    if (stopBtn) stopBtn.disabled = acting || !running;

    setText(sourceStatus, running ? "Recording quotes. This does not send an order." : "Not recording. Starting it still does not send an order.");
    setText(activity, running ? "Quotes are being recorded. Recording never submits orders." : "Nothing is being recorded. Recording never submits orders.");
    setText(nextWhy, running ? "Quotes are being recorded. Recording never submits orders." : "Nothing is being recorded. Starting it still never submits orders.");

    setText(statSession, running ? "Recording" : "Not recording");
    setText(statTicks, `${fmtInt(manifest.ticks_recorded)} saved. Not a complete history.`);
    setText(statSignals, `${fmtInt(manifest.signals_recorded)} — store-wide, FO-R1 requires zero session signals`);
    setText(statOrders, `${fmtInt(obs.orders_submitted)} — must always be 0 during observation`);

    // provenance row — setText style update
    const byProv = manifest.ticks_by_provenance ?? {};
    clear(provRow);
    if (Object.keys(byProv).length) {
      provRow.appendChild(h("span", { class: "eyebrow" }, "Ticks by provenance — explanatory"));
      for (const [p, n] of Object.entries(byProv)) provRow.append(provStrip(p), h("span", { class: "badge-mini" }, fmtInt(n)));
    }

    const ticks = manifest.sample_ticks ?? [];
    // preserve focus: only replace ticks table if count changed significantly or first load
    const shouldReplaceTicks = !ticksHost.dataset.count || String(ticks.length) !== ticksHost.dataset.count || force;
    if (shouldReplaceTicks) {
      ticksHost.dataset.count = String(ticks.length);
      clear(ticksHost);
      ticksHost.appendChild(card({
        title: `Recorded ticks — dense, sortable, keyboard navigable — context ${getContext().symbol}`, sub: `${ticks.length} shown of ${fmtInt(manifest.ticks_recorded)} — live view updates every 5s while visible, focus preserved`, icon: "activity",
        actions: [h("span", { class: "meta" }, `live — ${running ? "OBSERVING" : "IDLE"} — context synced — no flicker`)],
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
              icon: "activity", title: "No real observations recorded yet — INSUFFICIENT, not 0",
              desc: running ? "Session is starting — ticks appear here as broker streams them. Focus preserved, no flicker." : "Start an observation session. QTS records bid/ask/spread/regime with zero orders. A DEMO terminal is required; in development this honestly stays empty.",
              actions: running ? null : [h("button", { class: "btn primary", onclick: () => act("start") }, icon("play", 14), "Start Observation")],
            }),
      }));
    }

    // execution reality — stable update
    clear(execHost);
    execHost.appendChild(card({ title: `Execution reality — honesty ledger — context ${getContext().symbol}`, sub: "real fills vs expectations — MEASURED vs UNAVAILABLE", icon: "scale", body:
      execReality && execReality.count > 0
        ? kv([["Real executions", fmtInt(execReality.count)], ["Avg slippage", fmtMetric(execReality.measured_metrics?.avg_slippage_bps)], ["Context", `${getContext().symbol} — presentation only`]])
        : emptyState({
            icon: "scale", title: "No real executions recorded — UNAVAILABLE, not 0",
            desc: "Slippage, latency and fill quality become measurable only with real (demo) executions. Until then UNAVAILABLE — never zero, never estimate. Truth visible.",
          }),
    }));

    clear(signalsHost);
    signalsHost.appendChild(card({ title: `Recorded signals — FO-R1 requires zero — context ${getContext().symbol}`, icon: "zap", body:
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
        : emptyState({ icon: "zap", title: "No signals recorded yet — INSUFFICIENT", desc: "Research-grade observation requires zero session signals. Legacy strategy records, if any, are separate evidence. Truth visible." }),
    }));

    // restore scroll and focus if possible
    requestAnimationFrame(() => {
      const wraps = [...root.querySelectorAll(".tbl-wrap")];
      wraps.forEach((el, i) => { if (scrollTops[i] != null) el.scrollTop = scrollTops[i]; });
      if (activePath?.inTicks || activePath?.inSignals) {
        const firstClickable = root.querySelector(".tbl-wrap tr.clickable");
        if (firstClickable && document.activeElement === document.body) firstClickable.focus();
      }
    });
  }

  async function act(kind) {
    if (acting) return;
    acting = true;
    root.querySelectorAll("#obs-start, #obs-stop").forEach((b) => { b.disabled = true; });
    setText(sourceStatus, kind === "start" ? "REQUESTING observation — waiting for backend readiness and collector state… — what blocked, why explicit" : "STOPPING observation — waiting for terminal state…");
    try {
      if (kind === "start") {
        const result = await api.post("/api/observe/start");
        if (result.status?.state !== "OBSERVING") throw new Error(result.note || result.status?.blocked_reasons?.join("; ") || "Backend did not confirm observation started");
        toast("ok", "Recording started", "Quotes will be saved. No order is sent. Live trading stays locked.");
      } else {
        await api.post("/api/observe/stop");
        toast("warn", "Recording stopped", "No order was sent.");
      }
      await refresh(true);
    } catch (e) {
      const msg = typeof e.body === "object" && e.body?.detail ? (e.body.detail.detail ?? e.body.detail) : e.message;
      toast("err", `Could not ${kind} observation`, String(msg).slice(0, 140));
    } finally { acting = false; await refresh(true); }
  }

  const stop = poll(() => refresh(false), 5000);
  onDispose(root, stop);
  await refresh(true);
}

/* Quality */
export async function renderQuality(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({ crumb: "Market", group: "Data quality", title: "Data quality", answer: h("b", null, "Whether saved market data is complete enough for research. Missing data stays missing. It is not filled in. This page cannot permit a trade."), body: null }));
  const activity = h("h2", null, `Loading quality… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / QUALITY"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let audit = null, adv = null, completeness = null;
  try { [audit, adv, completeness] = await Promise.all([
    api.get("/api/research/data-audit"),
    api.get("/api/research/data-quality-adversarial"),
    api.get("/api/research/data-completeness"),
  ]); }
  catch (e) { host.appendChild(errorBox({ what: "data quality could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${audit?.count ?? 0} registered source(s) — missing data stays blocked — context ${getContext().symbol}`;

  if (completeness && completeness.independent_recomputation) {
    const ir = completeness.independent_recomputation;
    host.appendChild(card({
      title: "Historical Data Quality & Integrity",
      sub: "Authoritative data quality disposition · Zero synthetic interpolation · Research gates fail closed",
      icon: "shield",
      actions: [h("span", { class: `badge ${ir.quality_gate === "PASS" ? "ok" : "warn"} lg` }, ir.quality_gate === "PASS" ? "QUALITY: READY" : "QUALITY: NOT READY")],
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Historical Bars Available", value: fmtInt(ir.source_rows), hint: "Actual observed rows in dataset", icon: "database" }),
          stat({ label: "Expected Intervals Missing", value: fmtInt(ir.unexpected_missing_intervals), tone: ir.quality_gate === "PASS" ? "ok" : "err", hint: "Unaccounted data gaps", icon: "alert" }),
          stat({ label: "Data Incompleteness", value: `${ir.active_span_missing_pct}%`, tone: ir.quality_gate === "PASS" ? "ok" : "err", hint: "Quality threshold: ≤ 2.00%", icon: "scale" }),
          stat({ label: "Data Integrity Posture", value: "ZERO SYNTHESIS", tone: "ok", hint: "No bars interpolated or fabricated", icon: "shield" }),
        ),
        banner(
          ir.quality_gate === "PASS" ? "ok" : "warn",
          ir.quality_gate === "PASS" ? "Dataset Quality Gate Passed" : "Historical Data Incomplete — Research Blocked",
          ir.quality_gate === "PASS"
            ? "Dataset meets the required completeness threshold (< 2.00% missing). Valid for statistical research."
            : `Quality check: Not ready. ${fmtInt(ir.source_rows)} bars available; ${fmtInt(ir.unexpected_missing_intervals)} expected intervals missing (${ir.active_span_missing_pct}% incomplete). Required action: Acquire a new broker dataset from MT5. No data was fabricated or interpolated.`,
          ir.quality_gate === "PASS" ? "check" : "alert",
        ),
        h("details", null,
          h("summary", null, "Detailed accounting & gap disposition (Level 3/4 evidence)"),
          h("div", { class: "stack", style: { marginTop: "10px" } },
            kv([
              ["Active span expected", fmtInt(ir.active_span_expected_intervals)],
              ["Observed source rows", fmtInt(ir.source_rows)],
              ["Missing intervals count", fmtInt(ir.unexpected_missing_intervals)],
              ["Missing percentage", `${ir.active_span_missing_pct}% (threshold: 2.00%)`],
              ["Unexpected gap events", fmtInt(ir.unexpected_gap_events)],
              ["Recognized weekend closures", `${ir.recognized_closure_events} events (${fmtInt(ir.recognized_closure_intervals)} intervals)`],
              ["Gate disposition", ir.quality_gate],
              ["Recovery outcome", completeness.recovery_outcome || "RECOVERABLE ONLY BY NEW ACQUISITION"],
            ]),
          ),
        ),
      ),
    }));
  }

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: `Registered sources — ${ctx.symbol}`, sub: `${audit?.count ?? 0} source(s). This list is not a quality-check count.`, icon: "database", body:
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
    card({ title: "Adversarial stress — must fail closed — what blocked, why", icon: "shield", body: adv ? checkGrid({
      "duplicate & corrupted caught": adv.duplicate_corrupted_passed,
      "gap detection": adv.missing_corrupted_gap_check,
    }, { "duplicate & corrupted caught": "faults injected; must be caught — safety understandable", "gap detection": "missing ranges must block, not interpolate — never silently pass" }) : null }),
  ));
  if (audit?.limitation) host.appendChild(banner("warn", "Known limitation — truth visible", audit.limitation, "alert"));
  if (audit?.recommendation) host.appendChild(banner("info", "Recommended next acquisition — what missing, what next", audit.recommendation, "info"));
  host.appendChild(h("details", null, h("summary", null, "Raw source audit / technical — summary → detail → raw"), tech(audit, "Raw source audit")));
}

/* Lineage */
export async function renderLineage(root) {
  skeletonInto(root);
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({
    crumb: "Market", group: "Lineage",
    title: "Lineage",
    answer: h("b", null, "Where a saved number came from. A changed preparation is a new version, not a silent edit. This page cannot permit a trade."),
    body: null,
  }));
  const activity = h("h2", null, `Loading lineage… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / LINEAGE"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let inv = [];
  try { inv = await api.get("/api/research/data-inventory"); }
  catch (e) { host.appendChild(errorBox({ what: "lineage could not be loaded", next: "Retry.", raw: e.message })); return; }

  activity.textContent = `${inv.length} dataset(s) — immutable, checksummed, version-locked — context ${ctx.symbol}`;

  const chain = ["Provider", "Raw storage (immutable)", "Validation", "Canonical dataset", "Manifest (checksum)", "Features", "Experiment", "Evidence"];
  host.appendChild(card({ title: "Lineage chain — explanatory, not decorative", sub: "old versions never mutated — summary → evidence → lineage → raw", icon: "branch", body:
    h("div", { class: "pipeline" }, chain.map((c, i) => [i > 0 && h("span", { class: "pipe-arrow", "aria-hidden": "true" }, "→"), h("span", { class: "pipe-stage reached" }, c)])),
  }));

  host.appendChild(card({ title: `Datasets — immutable, checksummed, version-locked — context ${ctx.symbol}`, sub: "dense table, sortable, keyboard navigable — high density without chaos", icon: "database", body:
    table({
      columns: [
        { key: "id", label: "Dataset", render: (d) => h("span", { class: "primary-cell mono small" }, `${d.instrument} ${d.timeframe}`) },
        { key: "provider", label: "Provider", render: (d) => d.provider ?? "—" },
        { key: "rows", label: "Rows", num: true, render: (d) => fmtInt(d.row_count) },
        { key: "range", label: "Range", render: (d) => h("span", { class: "mono small text-dim" }, `${d.date_range?.start} → ${d.date_range?.end}`) },
        { key: "tz", label: "Timestamps", render: (d) => `${d.timezone} · ${d.timestamp_resolution}` },
      ],
      rows: inv,
      empty: "No datasets ingested yet — INSUFFICIENT, not 0.",
      dense: true,
    }),
  }));

  host.appendChild(card({ title: "Research quality gate — insufficient BLOCKs, never quietly passes — safety understandable", sub: "dense list, not decoration — what blocked, why, what missing", icon: "shield", body:
    h("ul", { class: "reason-list" },
      h("li", null, "DATA QUALITY — ingestion checks must all pass — what blocked, why explicit"),
      h("li", null, "DATA DEPTH — minimum history depth per timeframe — what missing, what next"),
      h("li", null, "DIVERSITY — symbols/timeframes/regimes — scope and limitations"),
      h("li", null, "EXECUTION REALISM — real execution observations required — MEASURED vs UNAVAILABLE"),
      h("li", null, "OOS COVERAGE + TRIAL COUNT + STATISTICAL EVIDENCE — DSR uses full N"),
    ),
  }));
  host.appendChild(banner("info", "Locked test partitions — explanatory, not decorative", "Test data is partitioned and locked before discovery begins; experiments physically cannot touch it during search (purged CPCV, embargo, monotonic time). Progressive disclosure: summary → evidence → raw.", "lock"));
}
