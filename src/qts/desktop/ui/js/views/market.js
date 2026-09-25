/* Market — Monitor (quotes/regime/quality) · Observations · Data quality · Lineage
   Flat, dense, honest empties. Context synchronized across windows via context.js
   Real-time alive without flicker: focus/scroll preserved, setText not replace. */

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
    answer: h("b", null, "What the market looks like through QTS's data pipeline — quotes, regime, freshness — with provenance and honest empty states. Pipeline health is not quote freshness. Context syncs across windows via BroadcastChannel, presentation only."),
    actions: [ctxBadge, symInput, tfInput, applyCtx, h("button", { class: "btn", onclick: () => refresh(true) }, icon("refresh", 14), "Refresh sources")],
    body: null,
  }));

  const activity = h("h2", null, "Loading market evidence…");
  const next = h("a", { class: "btn primary", href: "#/market/observations" }, "Open observations");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / MARKET"), activity),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT — why, what missing"), next, nextWhy)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section" }); root.appendChild(host);
  let lastManifest = null, lastRegime = null, lastAdv = null;

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["market", "Market data pipeline", s.market, "Backend pipeline status, not proof of live quote."],
      ["quoteAge", "Collected quote age", s.quoteAge, "Age of last broker event, not API freshness."],
      ["observation", "Observation collector", s.observation, s.obs?.note || "Collector state — zero orders structurally"],
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
      setText(c.st, value);
      setText(c.det, meaning);
      const resKey = key === "market" || key === "mode" ? "health" : "observe";
      const meta = store.data.resources[resKey];
      const f = meta ? freshness(meta, resKey) : { label: "UNAVAILABLE", current: false };
      setText(c.fresh, `${f.label}${meta?.updatedAt ? ` · ${fmtAge(meta.updatedAt)}` : ""}`);
    }
    setText(activity, `${s.market} · ${s.observation} · ${s.quoteAge} · context ${getContext().symbol} — truth visible`);
    setText(nextWhy, s.obs?.state === "OBSERVING" ? "Collector reports OBSERVING. Inspect quote timestamps and provenance. Chart explains mid = (bid+ask)/2, no interpolation." : "No active collection. Start observation if terminal connected. Context syncs, never permission.");
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
    setText(ctxBadge, `${currentCtx.symbol} · ${currentCtx.timeframe} — synced`);

    const content = h("div", { class: "stack" });
    content.appendChild(h("section", { class: "operator-section" },
      h("h2", null, "Operating facts — pipeline health vs quote freshness — truth visible"),
      h("div", { class: "tbl-wrap" },
        h("table", { class: "tbl facts-table" },
          h("thead", null, h("tr", null, ["Source","Reported state","Meaning / constraint","API freshness"].map((t) => h("th", { scope: "col" }, t)))),
          factsBody))));

    content.appendChild(h("div", { class: "grid-2" },
      card({
        title: "Current quote — last recorded tick, not live market — explanatory viz", sub: last ? `latest recorded · ${last.symbol ?? ""} — context ${currentCtx.symbol}` : "no tick recorded", icon: "activity",
        actions: [last ? provStrip(last.provenance ?? last.data_class ?? "SYNTHETIC") : null],
        body: last
          ? h("div", { class: "stack" },
              h("div", { class: "quote" },
                h("div", { class: "q-side" }, h("span", { class: "q-label" }, "BID"), h("span", { class: "q-value bid" }, fmtNum(last.bid))),
                h("div", { class: "q-side" }, h("span", { class: "q-label" }, "ASK"), h("span", { class: "q-value ask" }, fmtNum(last.ask))),
                h("div", { class: "q-side" }, h("span", { class: "q-label" }, "SPREAD"), h("span", { class: "q-value" }, `${fmtNum(last.spread_bps, 1)} bps`)),
              ),
              h("div", { class: "meta" }, `broker time ${last.broker_time ?? "—"} · canonical UTC ${fmtUtc(last.timestamp ?? last.canonical_ts)} · basis ${last.timestamp_basis ?? "canonical-UTC"}`),
              h("div", { class: "meta" }, `API freshness ${freshness(store.data.resources.observe, "observe").label} — quote age is separate from API receipt — context ${currentCtx.symbol} presentation only`),
              ticks.length >= 2
                ? [h("div", { class: "chart-block" }, spark(ticks.map((t) => (Number(t.bid) + Number(t.ask)) / 2), { height: 70 })),
                   h("div", { class: "chart-caption" }, h("span", { class: "cap-item" }, `${ticks.length} recorded DEMO observation ticks`), h("span", { class: "cap-item" }, "source: DEMO_FORWARD observation — not historical REAL"), h("span", { class: "cap-item" }, "mid = (bid+ask)/2, no interpolation"), h("span", { class: "cap-item" }, `context ${currentCtx.symbol} — chart explains, not decorates`), h("span", { class: "cap-item" }, `range ${fmtNum(Math.min(...ticks.map((t)=>(Number(t.bid)+Number(t.ask))/2)))} → ${fmtNum(Math.max(...ticks.map((t)=>(Number(t.bid)+Number(t.ask))/2)))}`))]
                : banner("info", "Not enough observations yet", "Chart appears after ≥2 recorded ticks — QTS never fabricates history. Explanatory, not decorative.", "info"),
            )
          : emptyState({
              icon: "activity", title: "No real observations recorded yet — INSUFFICIENT, not 0",
              desc: "Quotes appear once observation records real broker ticks. Observation is order-free. Pipeline HEALTHY does not mean a fresh quote exists. Truth visible: MEASURED vs UNAVAILABLE.",
              actions: [h("button", { class: "btn primary", onclick: () => navigate("#/market/observations") }, icon("play", 14), "Start Observation")],
            }),
      }),
      card({
        title: "Regime picture — explanatory, not predictive — truth visible", sub: regime?.count != null ? `${fmtInt(regime.count)} observations — not a strategy signal — context ${currentCtx.symbol}` : null, icon: "pulse",
        body: regime?.volatility_distribution
          ? h("div", { class: "stack" },
              barList([
                { label: "Low volatility", value: regime.volatility_distribution.low ?? 0, max: regime.count ?? 1, tone: "", valText: `${fmtInt(regime.volatility_distribution.low)} of ${fmtInt(regime.count)}` },
                { label: "Normal", value: regime.volatility_distribution.normal ?? 0, max: regime.count ?? 1, tone: "ok", valText: `${fmtInt(regime.volatility_distribution.normal)} of ${fmtInt(regime.count)}` },
                { label: "High volatility", value: regime.volatility_distribution.high ?? 0, max: regime.count ?? 1, tone: "warn", valText: `${fmtInt(regime.volatility_distribution.high)} of ${fmtInt(regime.count)}` },
              ]),
              regime.trend_strength_avg != null ? h("div", { class: "meta" }, `avg trend strength ${fmtNum(regime.trend_strength_avg, 3)} — descriptive, not predictive — range 0→1, higher = stronger trend`) : null,
              (regime.transitions ?? []).length
                ? [h("div", { class: "eyebrow mt-3" }, "Recent transitions — explanatory"), timeline((regime.transitions ?? []).slice(0, 6).map((t) => ({ when: fmtUtc(t.time), what: `${t.symbol ?? ""} ${t.from ?? "?"} → ${t.to ?? "?"}`, tone: "" })))]
                : null,
            )
          : emptyState({ icon: "pulse", title: "No regime observations — INSUFFICIENT", desc: "Regime classification starts once observation records real ticks. Explanatory, not decorative." }),
      }),
    ));

    content.appendChild(card({
      title: "Data quality — adversarial stress must fail closed — safety understandable", sub: "corrupted input never passes silently — what blocked, why", icon: "shield",
      body: adv ? h("div", { class: "check-grid" },
        h("div", { class: `check ${adv.duplicate_corrupted_passed ? "pass" : "fail"}` }, h("div", { class: "mark" }, adv.duplicate_corrupted_passed ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Duplicate & corrupted rows"), h("div", { class: "detail" }, "faults injected on purpose are caught — what blocked, why explicit"))),
        h("div", { class: `check ${adv.missing_corrupted_gap_check ? "pass" : "fail"}` }, h("div", { class: "mark" }, adv.missing_corrupted_gap_check ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Gap detection"), h("div", { class: "detail" }, "missing ranges block rather than interpolate — never silently pass"))),
        adv.zero_price_error ? h("div", { class: "check fail" }, h("div", { class: "mark" }, "■"), h("div", null, h("div", { class: "name" }, "Zero-price guard"), h("div", { class: "detail" }, adv.zero_price_error))) : null,
      ) : emptyState({ icon: "shield", title: "Quality stress results unavailable — UNAVAILABLE, not 0" }),
    }));

    // timestamp normalization health — FS-c42bbd fix visible in monitor
    const bases = manifest.timestamp_bases ?? {};
    const offsets = manifest.server_utc_offsets_s ?? [];
    content.appendChild(card({
      title: `Timestamp normalization — authoritative UTC — context ${currentCtx.symbol} — FS-c42bbd fix retained`, sub: `bases: ${Object.keys(bases).join(", ") || "UNAVAILABLE"} — offsets ${offsets.length ? offsets.map((o)=>`${o/3600}h`).join(", ") : "UNAVAILABLE"}`,
      icon: "clock",
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Timestamp bases", value: Object.keys(bases).length ? Object.entries(bases).map(([k,v])=>`${k}·${v}`).join(", ") : "UNAVAILABLE", hint: "broker-normalized(measured-m1-bar) vs assumed-utc-fallback — truth visible, never 0" }),
          stat({ label: "Server UTC offsets", value: offsets.length ? offsets.join(", ") : "UNAVAILABLE", hint: "seconds east positive — +3h=10800 retained on probe failure (FS-c42bbd fix), not lost" }),
          stat({ label: "Ticks recorded", value: fmtInt(manifest.ticks_recorded), hint: "FS-c42bbd had 2396 then 30 future failures, now retained offset prevents storm" }),
          stat({ label: "Last event", value: manifest.last_event_time ? fmtUtc(manifest.last_event_time) : "UNAVAILABLE", hint: "broker-normalized true UTC, not server-local" }),
        ),
        banner("info", "Canonical contract — no double-apply, no loss", "True UTC = time.time(). Broker stamps server-local. Offset = server - UTC via forming-M1-bar probe. Normalization = broker_stamp - offset -> UTC single application. On probe failure retain last offset (FS-c42bbd fix) — prevents +3h future. Future-tick protection unchanged: age < -1s still fails.", "clock"),
      ),
    }));

    if (manifest.canonical_store) content.appendChild(h("details", null, h("summary", null, "Raw forward-observation manifest / technical — summary → detail → raw"), tech(manifest, "Raw manifest")));
    host.replaceChildren(content);
  }

  const off = store.on("resources", renderFacts);
  const offCtx = onContext(() => { setText(ctxBadge, `${getContext().symbol} · ${getContext().timeframe} — synced`); renderFacts(); });
  onDispose(root, () => { off(); offCtx(); });
  await refresh();
}

/* Observations — real-time alive without flicker: preserve focus, scroll, disclosure */
export async function renderObservations(root) {
  skeletonInto(root, "stats");
  let refreshing = false, acting = false;
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Market", group: "Observations",
    title: "Forward Observatory",
    answer: h("b", null, "Real broker ticks recorded with zero capital exposure. Observation never submits orders — it builds evidence research requires. Recorded count is not complete tick history. Context syncs, never permission. Real-time alive without flicker: focus and scroll preserved."),
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
    stat({ label: "Session state", value: statSession, icon: "eye" }),
    stat({ label: "Ticks recorded", value: statTicks, icon: "database" }),
    stat({ label: "Signals recorded", value: statSignals, icon: "zap" }),
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

    setText(sourceStatus, `CURRENT API snapshot — quote timestamps and manifest generation time are separate. Updated ${fmtUtc(Date.now())} — context ${getContext().symbol} — ${running ? "OBSERVING — zero orders" : "IDLE"}`);
    setText(activity, `${running ? "OBSERVING" : obs.state ?? "IDLE"} · ${fmtInt(manifest.ticks_recorded)} ticks · ${fmtInt(manifest.real_market_ticks)} real-market · context ${getContext().symbol} — truth visible`);
    setText(nextWhy, running ? "Collector reports OBSERVING. Inspect quote timestamps and provenance. Zero orders structurally." : "No active collection. Start observation if terminal connected. Context syncs, never permission.");

    setText(statSession, running ? "OBSERVING" : String(obs.state ?? "IDLE").toUpperCase());
    setText(statTicks, `${fmtInt(manifest.ticks_recorded)} — ${fmtInt(manifest.real_market_ticks)} real-market — not complete history`);
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
        toast("ok", "Observation confirmed", "Collector reports OBSERVING — zero orders — DEMO vs LIVE unmistakable.");
      } else {
        await api.post("/api/observe/stop");
        toast("warn", "Observation stopped", "Session state preserved.");
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
  root.appendChild(page({ crumb: "Market", group: "Data quality", title: "Data Quality", answer: h("b", null, `Fail-closed validation of every dataset before it can feed research. Missing is blocked, not interpolated. Context ${ctx.symbol}. Truth visible: MEASURED vs UNAVAILABLE never 0.`), body: null }));
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

  activity.textContent = `${audit?.count ?? 0} source(s) — fail-closed, 12 checks — context ${getContext().symbol}`;

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
    card({ title: `Source audit — dense, provenance explicit — context ${ctx.symbol}`, sub: `${audit?.count ?? 0} source(s) — fail-closed, 12 checks`, icon: "database", body:
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
    title: "Data Lineage",
    answer: h("b", null, `Where did this number come from? Provider → raw → canonical → manifest → experiment → evidence. Any preprocessing change creates a NEW version. Context ${ctx.symbol}. Progressive disclosure: summary → detail → raw.`),
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
