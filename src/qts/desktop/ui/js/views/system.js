/* System — setup, MT5, diagnostics: plumbing made calm and explicit
   Operator workspace, context synced, DEMO vs LIVE unmistakable, perf honest.
   Includes timestamp normalization health (FS-c42bbd fix visible). */

import { api, store, RESOURCES, syncResource, measurements } from "../api.js";
import { operationalState, freshness } from "../operations.js";
import { h } from "../dom.js";
import {
  card, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, checkGrid, toast,
} from "../components.js";
import { fmtUtc, fmtAge, humanKey, fmtNum, fmtInt } from "../format.js";
import { modeInfo } from "../status.js";
import { onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";

/* Setup wizard */
export async function renderSetup(root) {
  const ctx = getContext();
  const head = page({
    crumb: "System", group: "Setup",
    title: "Setup",
    answer: h("b", null, `Guided configuration — no code editing. Progress verified against live system. Credentials never stored in QTS. Context ${ctx.symbol} syncs, never permission. DEMO vs LIVE unmistakable.`),
    body: null,
  });
  root.appendChild(head);
  const activity = h("h2", null, `Loading setup… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / SETUP"), activity)));
  const host = h("div", { class: "section" }); root.appendChild(host);

  let saved = null, safety = null, env = null;
  try { [saved, safety, env] = await Promise.all([api.get("/api/setup/mt5"), api.get("/api/demo/safety"), api.get("/api/env/boundary")]); } catch {}
  activity.textContent = `Setup wizard — context ${ctx.symbol} — credentials stay out of QTS`;

  const setup = saved?.setup ?? {};
  const envOpts = [
    ["development", "Development", "Backtest and research only — mock or historical data, zero broker contact."],
    ["paper", "Paper", "Simulated fills on recorded data, next-bar-open. No real orders."],
    ["shadow", "Shadow", "Real market data; would-be intents with risk/spread checks. Nothing submitted."],
    ["demo_forward", "Demo Forward", "DEMO observation only — real MT5 demo terminal, real market data, zero orders structurally."],
    ["demo_execution", "Demo Execution", "DEMO_EXECUTION = ENABLED_AUTHORIZED only with a recorded owner authorization (default: DISABLED BY POLICY); orders additionally require staged arming, a pinned identity, an eligible registered strategy and 22 pre-trade checks. DEMO vs LIVE unmistakable."],
  ];
  const currentEnv = env?.resolution?.effective_mode ?? "development";
  host.appendChild(card({
    title: `Step 1 · Choose environment — presentation only, restart re-resolves — context ${ctx.symbol}`, icon: "layers",
    sub: `effective: ${modeInfo(currentEnv).mode}`,
    body: h("div", { class: "stack" },
      envOpts.map(([val, label, desc]) => h("label", { class: "check", style: { cursor: "pointer", display: "flex" } },
        h("input", { type: "radio", name: "setup-env", value: val, checked: val.toLowerCase() === String(currentEnv).toLowerCase() || (String(currentEnv).toLowerCase() === "dev" && val === "development") }),
        h("div", null, h("div", { class: "name" }, label), h("div", { class: "detail" }, desc)),
      )),
      banner("warn", "LIVE is separately gated — DEMO vs LIVE unmistakable", "No environment choice here unlocks live trading. Governance decides with human approval after every scientific and safety gate. DEMO = simulation, LIVE = real capital, locked by design.", "lock"),
    ),
  }));

  const path = h("input", { class: "input", value: setup.terminal_path ?? "", placeholder: "C:\\Program Files\\MetaTrader 5\\terminal64.exe" });
  const symbol = h("input", { class: "input", value: setup.symbol ?? getContext().symbol });
  host.appendChild(card({
    title: `Step 2 · MT5 terminal & instrument — context ${ctx.symbol} syncs`, icon: "bank",
    sub: "credentials stay out of QTS — set QTS_MT5_LOGIN / PASSWORD / SERVER in OS store",
    body: h("div", { class: "stack" },
      h("div", { class: "field" }, h("label", null, "Terminal path"), path, h("div", { class: "hint" }, "Full path to terminal64.exe. Broker symbol may differ (e.g. XAUUSD@) — use exact broker name.")),
      h("div", { class: "field" }, h("label", null, "Symbol — canonical QTS name, context synced"), symbol, h("div", { class: "hint" }, `Uses current context ${getContext().symbol}, presentation only.`)),
      h("div", { class: "row" },
        h("button", { class: "btn primary", onclick: saveSetup }, "Save setup"),
        h("button", { class: "btn", onclick: testConnection }, "Test connection (14 checks) — what blocked, why"),
      ),
      h("div", { id: "setup-test-result" }),
    ),
  }));

  const lim = safety?.demo_limits ?? {};
  host.appendChild(card({
    title: "Step 3 · Acknowledge hard limits (informational, does not enable) — safety understandable", icon: "shield",
    body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({ label: "Max volume / order", value: `${lim.max_volume_per_order ?? "—"} lots` }),
        stat({ label: "Max exposure", value: `${lim.max_simultaneous_exposure ?? "—"} lots` }),
        stat({ label: "Daily loss cap", value: `$${lim.max_daily_loss_usd ?? "—"}` }),
        stat({ label: "Kill switch", value: lim.kill_switch_enabled ? "ARMED" : "—", tone: "ok" }),
      ),
      banner("info", "Safety metadata is informational and non-authorizing — what blocked, why, what next", "DEMO_EXECUTION is authorized for the DEMO account only by a recorded owner authorization; the shipped default is DISABLED BY POLICY. No acknowledgement or setup-page action creates order permission. Nothing is enabled from this page. DEMO_FORWARD observation remains order-free. DEMO vs LIVE unmistakable.", "alert"),
    ),
  }));

  host.appendChild(card({
    title: "Step 4 · Where logs & evidence live", icon: "database",
    body: kv([
      ["Audit log", h("span", { class: "mono small" }, "logs/audit.jsonl (redacted) + SQLite audit_events")],
      ["Evidence", h("span", { class: "mono small" }, "data/evidence/*.json — Evidence Explorer")],
      ["Canonical observations", h("span", { class: "mono small" }, "data/sqlite/forward_observatory.db")],
      ["Timestamp contract", h("span", { class: "mono small" }, "broker stamp - measured offset -> UTC, retained on probe failure (FS-c42bbd fix)")],
      ["Context", `${getContext().symbol} — presentation only, never permission`],
      ["Rule", "Never edit by hand — UI and CLI read them for you."],
    ]),
  }));

  async function saveSetup() {
    try {
      await api.post("/api/setup/mt5", { terminal_path: path.value, symbol: symbol.value });
      toast("ok", "Setup saved", "Credential-free metadata persisted.");
      renderSetup(root);
    } catch (e) { toast("err", "Could not save setup", String(e.message).slice(0,140)); }
  }
  async function testConnection() {
    const out = document.getElementById("setup-test-result");
    out.replaceChildren(banner("info", "Running readiness checks… — what blocked, why", "Probing terminal, account, symbol, spec, data freshness.", "info"));
    try {
      const r = await api.get(`/api/demo/readiness?terminal_path=${encodeURIComponent(path.value)}&symbol=${encodeURIComponent(symbol.value)}`);
      out.replaceChildren(
        banner(r.passed ? "ok" : "warn", r.passed ? "OBSERVATION READINESS PASSED — DEMO execution disabled" : "READINESS NOT PASSED — what blocked, why, what missing, what next", (r.blocked_reasons ?? []).join(" · ") || "Review failing checks.", r.passed ? "check" : "alert"),
        checkGrid(r.checks ?? {}, r.details ?? {}),
      );
    } catch (e) {
      out.replaceChildren(errorBox({ what: "the readiness probe failed", known: "No terminal answered or path wrong. In dev without MT5 this is expected.", next: "Verify path, or continue in development — research does not need terminal.", raw: e.message }));
    }
  }
}

/* MT5 connection */
export async function renderMT5(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  const ctx = getContext();
  root.appendChild(page({
    crumb: "System", group: "MT5",
    title: "MT5 Connection",
    answer: h("b", null, `Terminal, account and instrument state — mock and real explicitly distinguished. Mock is never eligible as broker evidence. Context ${ctx.symbol} syncs, never permission. Timestamp normalization: broker stamp - measured offset -> UTC.`),
    actions: [h("button", { class: "btn", onclick: () => renderMT5(root) }, "Refresh")],
    body: null,
  }));

  const activity = h("h2", null, `Loading MT5 state… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / MT5"), activity)));

  const host = h("div", { class: "section" }); root.appendChild(host);
  let m = null;
  try { m = await api.get("/api/mt5"); } catch (e) { host.appendChild(errorBox({ what: "MT5 state could not be loaded", next: "Retry.", raw: e.message })); return; }

  const connected = Boolean(m.connected);
  activity.textContent = connected ? `CONNECTED — real terminal in use — context ${getContext().symbol}` : `DISCONNECTED — mock or no terminal — context ${getContext().symbol}`;
  host.appendChild(h("div", { class: "stat-grid" },
    stat({ label: "Module mode", value: String(m.mode ?? "UNAVAILABLE").toUpperCase(), tone: String(m.mode).toUpperCase().includes("REAL") ? "ok" : "warn", hint: "REAL = real terminal; MOCK = simulated", icon: "bank" }),
    stat({ label: "Connection", value: connected ? "CONNECTED" : String(m.terminal_status ?? "DISCONNECTED").toUpperCase(), tone: connected ? "ok" : "neutral", icon: "activity" }),
    stat({ label: "Context", value: `${getContext().symbol} · ${getContext().timeframe}`, hint: "presentation only, never permission" }),
  ));

  if (m.warning) host.appendChild(banner("warn", "Connection advisory — what blocked, why", m.warning, "alert"));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: `Account — context ${getContext().symbol}`, icon: "bank", body: m.account
      ? h("div", { class: "stack" }, h("div", { class: "stat-grid" }, stat({ label: "Account state", value: m.account?.status === "MEASURED" ? String(m.account.value) : String(m.account?.status ?? "UNAVAILABLE").toUpperCase(), tone: m.account?.status === "MEASURED" ? "ok" : "neutral", hint: m.account?.reason ?? null })), tech(m.account, "Raw account metric — summary → detail → raw"))
      : emptyState({ icon: "bank", title: "Account state unavailable — INSUFFICIENT, not 0", desc: "No terminal context. Attach terminal in Setup and verify with readiness." }),
    }),
    card({ title: `Symbol spec — context ${getContext().symbol}`, icon: "fileCheck", body: m.spec
      ? h("div", { class: "stack" }, h("div", { class: "stat-grid" }, stat({ label: "Symbol spec", value: m.spec?.status === "MEASURED" ? String(m.spec.value) : String(m.spec?.status ?? "UNAVAILABLE").toUpperCase(), tone: m.spec?.status === "MEASURED" ? "ok" : "neutral", hint: m.spec?.reason ?? null })), tech(m.spec, "Raw spec — summary → detail → raw"))
      : emptyState({ icon: "fileCheck", title: "Symbol spec unavailable — INSUFFICIENT, not 0", desc: "Authoritative contract requires connected terminal. Missing metadata never guessed in safety-critical paths." }),
    }),
  ));

  host.appendChild(banner("info", "Mock ≠ real, always labeled — truth visible — timestamp contract retained", "When no terminal attached QTS uses explicitly labeled mock module. Mock data is SYNTHETIC everywhere and never eligible as broker behavior evidence. Timestamp normalization: broker stamp - measured offset -> UTC, retained on probe failure (FS-c42bbd fix). Context syncs, never permission.", "info"));
}

/* Diagnostics — per-resource freshness + performance + timestamp normalization */
export async function renderDiagnostics(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  const ctx = getContext();
  const head = page({
    crumb: "System", group: "Diagnostics",
    title: "System Diagnostics",
    answer: h("b", null, `Per-source freshness, environment boundary, mode resolution — honest plumbing. One failed source does not erase other current facts. Context ${ctx.symbol} syncs. Performance is UX: load/transition/refresh/rendering/memory/dup/recovery measured. Timestamp normalization: broker - measured offset -> UTC, retained on failure (FS-c42bbd).`),
    actions: [h("button", { class: "btn", onclick: () => refresh(true) }, "Refresh sources")],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", null, `Loading diagnostics… — context ${ctx.symbol}`);
  root.appendChild(h("section", { class: "operator-summary" }, h("div", null, h("div", { class: "eyebrow" }, "NOW / DIAGNOSTICS"), activity)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section" }); root.appendChild(host);
  let lastHealth = null, lastEnv = null, lastManifest = null, lastObserve = null;

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["health", "Health API", s.sources.health.label, "Backend health endpoint freshness, not quote freshness."],
      ["observe", "Observation collector", s.observation, s.obs?.last_error || s.obs?.note || "Collector state from /api/observe/status — FS-c42bbd: 2396 ticks then 30 future failures, offset retained fix"],
      ["demoState", "DEMO authority", s.permission, "Current execution permission from authority. DEMO vs LIVE unmistakable."],
      ["live", "LIVE governance", s.liveLabel, "Governance eligibility from /api/live/status — LOCKED is safety."],
      ["notifications", "Notifications", s.sources.notifications.label, "Attention list freshness."],
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
      const meta = store.data.resources[key];
      const f = meta ? freshness(meta, key) : { label: "UNAVAILABLE", current: false };
      c.fresh.textContent = `${f.label}${meta?.updatedAt ? ` · ${fmtAge(meta.updatedAt)}` : ""} · ${RESOURCES[key]?.path ?? ""}`;
      c.fresh.title = meta?.error ? `Last error: ${meta.error}` : RESOURCES[key]?.path ?? "";
    }
    activity.textContent = `Health ${s.sources.health.label} · Observation ${s.observation} · DEMO ${s.permission} · LIVE ${s.liveLabel} · context ${getContext().symbol} · timestamp bases ${Object.keys(lastManifest?.timestamp_bases ?? {}).join(", ") || "UNAVAILABLE"}`;
  }

  async function refresh(force = false) {
    try {
      const [health, env, manifest, observe] = await Promise.all([
        api.get("/api/health"),
        api.get("/api/env/boundary"),
        api.get("/api/research/forward-manifest").catch(() => null),
        api.get("/api/observe/status").catch(() => null),
      ]);
      lastHealth = health; lastEnv = env; lastManifest = manifest; lastObserve = observe;
      if (force) await Promise.all(Object.keys(RESOURCES).map((k) => syncResource(k, { force: true })));
      render();
    } catch (e) {
      host.replaceChildren(errorBox({ what: "diagnostics could not be loaded", next: "Retry; if API down, restart QTS.", raw: e.message }));
    }
  }

  function perfSummary() {
    const byKind = {};
    for (const m of measurements) {
      if (!byKind[m.kind]) byKind[m.kind] = { count: 0, total: 0, failed: 0, max: 0 };
      byKind[m.kind].count++;
      byKind[m.kind].total += m.ms || 0;
      byKind[m.kind].max = Math.max(byKind[m.kind].max, m.ms || 0);
      if (m.outcome === "failed") byKind[m.kind].failed++;
    }
    const rows = Object.entries(byKind).map(([kind, v]) => ({
      kind, count: v.count, avg: v.count ? v.total / v.count : 0, max: v.max, failed: v.failed,
    })).sort((a, b) => b.count - a.count);

    const heap = measurements.length ? measurements[measurements.length - 1].heapUsed : null;

    return h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({ label: "Total measured", value: `${measurements.length} / 100`, hint: "bounded — no payloads" }),
        stat({ label: "Heap (last)", value: heap ? `${heap} KB` : "UNAVAILABLE", hint: "JS heap if browser exposes performance.memory — MEASURED vs UNAVAILABLE, never 0" }),
        stat({ label: "Dup coalesced", value: `${(byKind["dup-coalesced"]?.count ?? 0) + (byKind["dup-sync"]?.count ?? 0)}`, hint: "GET coalesce + sync dedup — performance win, no extra network" }),
        stat({ label: "Recoveries", value: `${byKind["recovery"]?.count ?? 0}`, hint: "error → success transitions — alive without flicker" }),
      ),
      rows.length ? table({
        columns: [
          { key: "kind", label: "Kind" },
          { key: "count", label: "Count", num: true },
          { key: "avg", label: "Avg ms", num: true, render: (r) => fmtNum(r.avg, 1) },
          { key: "max", label: "Max ms", num: true, render: (r) => fmtNum(r.max, 1) },
          { key: "failed", label: "Failed", num: true },
        ],
        rows,
        dense: true,
      }) : emptyState({ icon: "activity", title: "No measurements yet", desc: "Interact with UI — route, refresh, poll — to generate performance evidence. Performance is UX." }),
      h("details", null, h("summary", null, "Show raw measurements / technical (last 100) — summary → detail → raw"),
        h("p", { class: "small text-dim" }, "Kinds: load (page), route (transition), refresh (forced or periodic), render (workspace update), request (API), dup-coalesced (GET dedup), dup-sync (sync dedup), recovery (error→ok), poll (periodic), poll-skipped (hidden tab). No response payloads stored. Heap requires performance.memory. Measures: load/transition/refresh/rendering/memory/dup/recovery per principle 13."),
        tech(measurements.slice(-100), "Measurements")),
    );
  }

  function timestampNormalizationCard() {
    const manifest = lastManifest;
    const obs = lastObserve;
    if (!manifest && !obs) {
      return card({ title: "Timestamp normalization — FS-c42bbd fix — authoritative clock basis", sub: "broker stamp - measured offset -> UTC, retained on probe failure", icon: "clock", body: emptyState({ icon: "clock", title: "No observation manifest yet — INSUFFICIENT", desc: "Manifest appears after observation records ticks. Shows timestamp bases, server_utc_offsets, last error. Truth visible." }) });
    }
    const bases = manifest?.timestamp_bases ?? {};
    const offsets = manifest?.server_utc_offsets_s ?? obs?.server_utc_offsets_s ?? [];
    const lastError = obs?.last_error ?? manifest?.last_error ?? null;
    const ticksRecorded = manifest?.ticks_recorded ?? obs?.ticks_recorded ?? 0;
    const dupSkipped = manifest?.duplicates_skipped ?? obs?.duplicates_skipped ?? 0;
    const state = obs?.state ?? manifest?.state ?? "UNAVAILABLE";

    return card({
      title: `Timestamp normalization — FS-c42bbd fix — ${state} — authoritative clock basis UTC`, sub: `bases: ${Object.keys(bases).join(", ") || "UNAVAILABLE"} — offsets retained on probe failure, not lost`, icon: "clock",
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Ticks recorded", value: fmtInt(ticksRecorded), hint: "canonical store count — FS-c42bbd had 2396 then 30 future failures" }),
          stat({ label: "Duplicates skipped", value: fmtInt(dupSkipped), hint: "identical raw broker stamps skipped — FS-c42bbd had 233" }),
          stat({ label: "Offsets observed", value: offsets.length ? offsets.map((o) => `${o/3600}h`).join(", ") : "UNAVAILABLE", hint: "server_utc_offset_s — +3h = 10800, retained on failure not lost" }),
          stat({ label: "Bases", value: Object.keys(bases).length ? Object.entries(bases).map(([k,v])=>`${k}·${v}`).join(", ") : "UNAVAILABLE", hint: "broker-normalized(measured-m1-bar) vs assumed-utc-fallback" }),
          stat({ label: "Last tick time", value: manifest?.last_event_time ?? obs?.last_tick_time ?? "UNAVAILABLE", hint: "broker-normalized true UTC, not server-local" }),
          stat({ label: "Collector state", value: state, hint: "OBSERVING vs STOPPED_ON_ERRORS — FS-c42bbd stopped after 30 future" }),
        ),
        lastError ? banner("warn", "Last collector error — what blocked, why", String(lastError).slice(0, 300), "alert") : null,
        banner("info", "Canonical contract — authoritative clock basis", "True UTC = time.time(). Broker stamps are server-local (e.g. UTC+3). Offset = server - UTC measured via forming-M1-bar probe (bar_time ∈ [server_now-60, server_now]). Normalization = broker_stamp - offset -> UTC, single application, never double-applied. On probe failure (copy_rates None/stale), retain last measured offset instead of falling back to 0.0 — fix for FS-c42bbd +3h future storm. Future-tick protection unchanged: age < -1s still fails.", "clock"),
        h("details", null, h("summary", null, "Raw timestamp normalization evidence / technical — summary → detail → raw"), tech({ manifest: { timestamp_bases: bases, server_utc_offsets_s: offsets, ticks_recorded: ticksRecorded, last_event_time: manifest?.last_event_time, state }, observe: obs }, "Raw timestamp evidence")),
      ),
    });
  }

  function render() {
    if (!lastHealth || !lastEnv) return;
    renderFacts();
    const content = h("div", { class: "stack" });

    content.appendChild(h("section", { class: "operator-section" },
      h("h2", null, "Operating facts — per-source freshness — truth visible"),
      h("div", { class: "tbl-wrap" },
        h("table", { class: "tbl facts-table" },
          h("thead", null, h("tr", null, ["Source","Reported state","Meaning / constraint","API freshness / path"].map((t) => h("th", { scope: "col" }, t)))),
          factsBody))));

    content.appendChild(timestampNormalizationCard());

    content.appendChild(card({ title: `Environment boundary matrix — context ${getContext().symbol}`, sub: "what each mode may and may not do — DEMO vs LIVE unmistakable", icon: "shield", body:
      kv(Object.entries(lastEnv?.boundary ?? {}).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
    }));

    const res = lastEnv?.resolution ?? {};
    content.appendChild(card({ title: `Mode resolution — context ${getContext().symbol}`, icon: "layers", body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({ label: "Effective mode", value: modeInfo(res.effective_mode).mode }),
        stat({ label: "Broker submission", value: res.can_submit_broker_orders ? "possible" : "impossible", tone: res.can_submit_broker_orders ? "warn" : "ok" }),
        stat({ label: "Real broker data", value: res.uses_real_broker_data ? "yes" : "no" }),
        stat({ label: "Money at risk", value: res.money_at_risk ? "YES" : "no", tone: res.money_at_risk ? "err" : "ok" }),
      ),
      res.restart_semantics ? banner("info", "Restart semantics", res.restart_semantics, "info") : null,
      res.resolution_error ? banner("err", "Resolution error", res.resolution_error, "alert") : null,
      h("details", null, h("summary", null, "Raw environment boundary / technical — summary → detail → raw"), tech(lastEnv, "Raw environment boundary")),
    )}));

    content.appendChild(card({ title: "Health detail — explanatory, not decorative", sub: `reported ${fmtUtc(lastHealth?.timestamp)} — receipt time separate`, icon: "activity", body:
      h("div", { class: "stack" },
        h("div", { class: "check-grid" },
          ["mt5","market_data","risk","reconciliation"].map((k) => {
            const v = lastHealth?.[k];
            const ok = String(v).toLowerCase() === "healthy" || String(v).toLowerCase() === "connected";
            return h("div", { class: `check ${ok ? "pass" : "na"}` },
              h("div", { class: "mark" }, ok ? "✓" : "!"),
              h("div", null, h("div", { class: "name" }, humanKey(k)), h("div", { class: "detail" }, String(v ?? "UNAVAILABLE"))),
            );
          }),
        ),
        lastHealth?.reconciliation_detail ? banner("info", "Reconciliation — truth visible", lastHealth.reconciliation_detail, "info") : null,
        h("details", null, h("summary", null, "Raw health report / technical — summary → detail → raw"), tech(lastHealth, "Raw health report")),
      ),
    }));

    content.appendChild(card({ title: "UI performance — last 100 local measurements — performance is UX (principle 13)", sub: "load / transition / refresh / rendering / memory / dup / recovery — MEASURED vs UNAVAILABLE, never 0", icon: "activity", body: perfSummary() }));
    host.replaceChildren(content);
  }

  const off = store.on("resources", renderFacts);
  const offCtx = onContext(renderFacts);
  onDispose(root, () => { off(); offCtx(); });
  await refresh();
}
