/* ============================================================
   VIEW GROUP: MARKET — what QTS sees
   Monitor (quotes/regime/quality) · Observation sessions ·
   Data quality · Lineage (where every number came from).
   ============================================================ */
import { api, poll, store } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  spark, barList, banner, confirmModal, toast, checkGrid, provStrip, freshStamp, timeline,
} from "../components.js";
import { fmtInt, fmtNum, fmtUtc, fmtAge, humanKey, trunc, fmtMetric } from "../format.js";
import { statusInfo, freshnessTone } from "../status.js";
import { navigate, onDispose } from "../router.js";

/* ================= MONITOR ================= */
export async function renderMonitor(root) {
  skeletonInto(root, "stats");
  root.appendChild(page({
    crumb: "Market", group: "Monitor",
    title: "Market Monitor",
    answer: h("b", null, "What the market looks like through QTS's data pipeline right now — quotes, regime, freshness — with provenance on every number."),
    actions: [h("button", { class: "btn", onclick: () => renderMonitor(root) }, icon("refresh", 14), "Refresh")],
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);

  let manifest = null, regime = null, adv = null;
  try {
    [manifest, regime, adv] = await Promise.all([
      api.get("/api/research/forward-manifest"),
      api.get("/api/research/regime-observations"),
      api.get("/api/research/data-quality-adversarial"),
    ]);
  } catch (e) {
    clear(host);
    host.appendChild(errorBox({ what: "market data could not be loaded", next: "Retry; if the API is down, restart QTS.", raw: e.message }));
    return;
  }

  const ticks = manifest.sample_ticks ?? [];
  const last = ticks[ticks.length - 1];
  const quotesCard = card({
    title: "Current quote", sub: last ? `latest recorded tick · ${last.symbol ?? ""}` : null, icon: "activity",
    actions: [last ? provStrip(last.provenance ?? last.data_class ?? "SYNTHETIC") : null],
    body: last
      ? h("div", { class: "stack" },
          h("div", { class: "quote" },
            h("div", { class: "q-side" }, h("span", { class: "q-label" }, "BID"), h("span", { class: "q-value bid" }, fmtNum(last.bid))),
            h("div", { class: "q-side" }, h("span", { class: "q-label" }, "ASK"), h("span", { class: "q-value ask" }, fmtNum(last.ask))),
            h("div", { class: "q-side" }, h("span", { class: "q-label" }, "SPREAD"), h("span", { class: "q-value" }, `${fmtNum(last.spread_bps, 1)} bps`)),
          ),
          h("div", { class: "meta" }, `broker time ${last.broker_time ?? "—"} · canonical UTC ${fmtUtc(last.timestamp ?? last.canonical_ts)} · basis ${last.timestamp_basis ?? "canonical-UTC"}`),
          ticks.length >= 2
            ? [h("div", { class: "chart-block" }, spark(ticks.map((t) => (Number(t.bid) + Number(t.ask)) / 2), { height: 70 })),
               h("div", { class: "chart-caption" },
                 h("span", { class: "cap-item" }, `${ticks.length} real recorded ticks`),
                 h("span", { class: "cap-item" }, "source: forward observation session"),
                 h("span", { class: "cap-item" }, "mid = (bid+ask)/2, no interpolation"))]
            : banner("info", "Not enough observations yet", "A line chart appears after at least 2 recorded ticks — QTS never fabricates history to fill a chart.", "info"),
        )
      : emptyState({
          icon: "activity", title: "No real observations recorded yet",
          desc: "Quotes, spreads and regime appear here once an observation session records real broker ticks. Observation is always order-free.",
          actions: [h("button", { class: "btn primary", onclick: () => navigate("#/market/observations") }, icon("play", 14), "Start Observation")],
        }),
  });

  const regimeDist = regime?.volatility_distribution ?? null;
  const regimeCard = card({
    title: "Regime picture", sub: regime?.count != null ? `${fmtInt(regime.count)} regime observations` : null, icon: "pulse",
    body: regimeDist
      ? h("div", { class: "stack" },
          barList([
            { label: "Low volatility", value: regimeDist.low ?? 0, max: regime.count ?? 1, tone: "" },
            { label: "Normal", value: regimeDist.normal ?? 0, max: regime.count ?? 1, tone: "ok" },
            { label: "High volatility", value: regimeDist.high ?? 0, max: regime.count ?? 1, tone: "warn" },
          ]),
          regime.trend_strength_avg != null ? h("div", { class: "meta" }, `avg trend strength ${fmtNum(regime.trend_strength_avg, 3)}`) : null,
          (regime.transitions ?? []).length
            ? [h("div", { class: "eyebrow mt-3" }, "Recent transitions"),
               timeline((regime.transitions ?? []).slice(0, 6).map((t) => ({
                 when: fmtUtc(t.time), what: `${t.symbol ?? ""} ${t.from ?? "?"} → ${t.to ?? "?"}`, tone: "",
               })))]
            : null,
        )
      : emptyState({ icon: "pulse", title: "No regime observations", desc: "Regime classification starts once observation sessions record real ticks." }),
  });

  const qualityCard = card({
    title: "Data quality — adversarial stress", sub: "corrupted input must fail closed, never pass silently", icon: "shield",
    body: adv ? h("div", { class: "check-grid" },
      h("div", { class: `check ${adv.duplicate_corrupted_passed ? "pass" : "fail"}` }, h("div", { class: "mark" }, adv.duplicate_corrupted_passed ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Duplicate & corrupted rows"), h("div", { class: "detail" }, "faults injected on purpose are caught"))),
      h("div", { class: `check ${adv.missing_corrupted_gap_check ? "pass" : "fail"}` }, h("div", { class: "mark" }, adv.missing_corrupted_gap_check ? "✓" : "✕"), h("div", null, h("div", { class: "name" }, "Gap detection"), h("div", { class: "detail" }, "missing ranges block rather than interpolate"))),
      adv.zero_price_error ? h("div", { class: "check fail" }, h("div", { class: "mark" }, "■"), h("div", null, h("div", { class: "name" }, "Zero-price guard"), h("div", { class: "detail" }, adv.zero_price_error))) : null,
    ) : emptyState({ icon: "shield", title: "Quality stress results unavailable" }),
  });

  host.appendChild(h("div", { class: "grid-2" }, quotesCard, regimeCard));
  host.appendChild(qualityCard);
  if (manifest.canonical_store) {
    host.appendChild(h("div", { class: "mt-4" }, tech(manifest, "Raw forward-observation manifest")));
  }
}

/* ================= OBSERVATIONS ================= */
export async function renderObservations(root) {
  skeletonInto(root, "stats");
  let refreshing = false;
  let acting = false;
  root.appendChild(page({
    crumb: "Market", group: "Observations",
    title: "Forward Observatory",
    answer: h("b", null, "Real broker ticks recorded with zero capital exposure. Observation never submits orders — it builds the real-data evidence research requires."),
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
      sourceStatus.textContent = "STALE / UNAVAILABLE — refresh failed. Last-known evidence may remain below; collector activity is not established. Retrying while visible.";
      if (!lastManifest) {
        clear(host); host.appendChild(stamp);
        host.appendChild(errorBox({ what: "observation status could not be loaded", next: "Retry; collector activity cannot be established while its source is unavailable.", raw: e.message }));
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
      stat({ label: "Ticks recorded", value: fmtInt(manifest.ticks_recorded), icon: "database", hint: `${fmtInt(manifest.real_market_ticks)} real-market` }),
      stat({ label: "Signals recorded", value: fmtInt(manifest.signals_recorded), icon: "zap", hint: "store-wide count; FO-R1 observation requires zero session signals" }),
      stat({ label: "Orders submitted", value: fmtInt(obs.orders_submitted), tone: Number(obs.orders_submitted) === 0 ? "ok" : "err", hint: "must always be 0 during observation" }),
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
      title: "Recorded ticks", sub: `${ticks.length} shown of ${fmtInt(manifest.ticks_recorded)}`, icon: "activity",
      actions: [h("span", { class: "meta" }, "live view — updates every 5s while the tab is visible")],
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
          })
        : emptyState({
            icon: "activity", title: "No real observations recorded yet",
            desc: running ? "Session is starting — ticks appear here as the broker streams them." : "Start an observation session. QTS records bid/ask/spread/regime with zero orders. A DEMO terminal is required; in development this honestly stays empty.",
            actions: running ? null : [h("button", { class: "btn primary", onclick: () => act("start") }, icon("play", 14), "Start Observation")],
          }),
    }));

    body.appendChild(h("div", { class: "grid-2" },
      card({ title: "Execution reality", sub: "real fills vs expectations — the honesty ledger", icon: "scale", body:
        execReality && execReality.count > 0
          ? kv([["Real executions", fmtInt(execReality.count)], ["Avg slippage", fmtMetric(execReality.measured_metrics?.avg_slippage_bps)]])
          : emptyState({
              icon: "scale", title: "No real executions recorded",
              desc: "Slippage, latency and fill quality become measurable only with real (demo) executions. Until then QTS shows UNAVAILABLE — never zero, never an estimate.",
            }),
      }),
      card({ title: "Recorded signals", icon: "zap", body:
        (manifest.sample_signals ?? []).length
          ? table({
              columns: [
                { key: "timestamp", label: "Time (UTC)", render: (s) => h("span", { class: "mono small" }, fmtUtc(s.timestamp)) },
                { key: "signal", label: "Signal", render: (s) => badge(String(s.signal ?? s.state ?? "").toUpperCase() === "NO_TRADE" ? "NO_TRADE" : "SIGNAL") },
                { key: "strategy", label: "Strategy", render: (s) => s.strategy_id ?? "—" },
                { key: "why", label: "Detail", render: (s) => h("span", { class: "small text-dim" }, trunc(s.reason ?? s.detail ?? "", 60)) },
              ],
              rows: manifest.sample_signals, empty: "No signals yet.",
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

/* ================= QUALITY ================= */
export async function renderQuality(root) {
  skeletonInto(root);
  root.appendChild(page({ crumb: "Market", group: "Data quality", title: "Data Quality", answer: h("b", null, "Fail-closed validation of every dataset before it can feed research."), body: null }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let audit = null, adv = null;
  try { [audit, adv] = await Promise.all([api.get("/api/research/data-audit"), api.get("/api/research/data-quality-adversarial")]); }
  catch (e) { host.appendChild(errorBox({ what: "data quality could not be loaded", next: "Retry.", raw: e.message })); return; }

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Source audit", sub: `${audit?.count ?? 0} source(s) — fail-closed, 12 checks`, icon: "database", body:
      table({
        columns: [
          { key: "instrument", label: "Source", render: (s) => `${s.instrument} ${s.timeframe}` },
          { key: "rows", label: "Rows", num: true, render: (s) => fmtInt(s.rows) },
          { key: "bidask", label: "Bid/Ask", render: (s) => badge(s.bid_ask_available ? "available" : "SYNTHETIC proxy") },
          { key: "spread", label: "Spread", render: (s) => badge(String(s.spread_available ?? "UNAVAILABLE")) },
          { key: "ts", label: "Timestamps", render: (s) => badge(s.timestamp_quality ?? "—") },
        ],
        rows: audit?.available_sources ?? [], empty: "No sources.",
      }),
    }),
    card({ title: "Adversarial stress", icon: "shield", body: adv ? checkGrid({
      "duplicate & corrupted caught": adv.duplicate_corrupted_passed,
      "gap detection": adv.missing_corrupted_gap_check,
    }, { "duplicate & corrupted caught": "faults injected; must be caught", "gap detection": "missing ranges must block, not interpolate" }) : null }),
  ));
  if (audit?.limitation) host.appendChild(banner("warn", "Known limitation", audit.limitation, "alert"));
  if (audit?.recommendation) host.appendChild(banner("info", "Recommended next acquisition", audit.recommendation, "info"));
  host.appendChild(tech(audit, "Raw source audit"));
}

/* ================= LINEAGE ================= */
export async function renderLineage(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "Market", group: "Lineage",
    title: "Data Lineage",
    answer: h("b", null, "Where did this number come from? Every value traces back: provider → raw → canonical → manifest → experiment → evidence."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let inv = [];
  try { inv = await api.get("/api/research/data-inventory"); }
  catch (e) { host.appendChild(errorBox({ what: "lineage could not be loaded", next: "Retry.", raw: e.message })); return; }

  const chain = ["Provider", "Raw storage (immutable)", "Validation", "Canonical dataset", "Manifest (checksum)", "Features", "Experiment", "Evidence"];
  host.appendChild(card({ title: "Lineage chain", sub: "any preprocessing change creates a NEW version — old versions are never mutated", icon: "branch", body:
    h("div", { class: "pipeline" },
      chain.map((c, i) => [
        i > 0 && h("span", { class: "pipe-arrow", "aria-hidden": "true" }, "→"),
        h("span", { class: "pipe-stage reached" }, c),
      ]),
    ),
  }));

  host.appendChild(card({ title: "Datasets", sub: "immutable, checksummed, version-locked", icon: "database", body:
    table({
      columns: [
        { key: "id", label: "Dataset", render: (d) => h("span", { class: "primary-cell" }, `${d.instrument} ${d.timeframe}`) },
        { key: "provider", label: "Provider", render: (d) => d.provider ?? "—" },
        { key: "rows", label: "Rows", num: true, render: (d) => fmtInt(d.row_count) },
        { key: "range", label: "Range", render: (d) => h("span", { class: "mono small text-dim" }, `${d.date_range?.start} → ${d.date_range?.end}`) },
        { key: "tz", label: "Timestamps", render: (d) => `${d.timezone} · ${d.timestamp_resolution}` },
      ],
      rows: inv,
      empty: "No datasets ingested yet.",
    }),
  }));

  host.appendChild(card({ title: "Research quality gate", sub: "insufficient data BLOCKs — it never quietly passes", icon: "shield", body:
    h("ul", { class: "gate-list", style: { fontSize: "var(--fs-13)" } },
      h("li", null, "DATA QUALITY — ingestion checks must all pass"),
      h("li", null, "DATA DEPTH — minimum history depth required per timeframe"),
      h("li", null, "DIVERSITY — symbols/timeframes/regimes"),
      h("li", null, "EXECUTION REALISM — real execution observations required"),
      h("li", null, "OOS COVERAGE + TRIAL COUNT + STATISTICAL EVIDENCE"),
    ),
  }));
  host.appendChild(banner("info", "Locked test partitions", "Test data is partitioned and locked before discovery begins; experiments physically cannot touch it during search (purged CPCV, embargo, monotonic time).", "lock"));
}
