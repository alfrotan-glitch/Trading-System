/* ============================================================
   VIEW GROUP: TRADING — what actually happened
   Paper/Shadow · Demo Forward (readiness, authority, control) ·
   Execution lifecycle · Comparison. UNAVAILABLE is never 0.
   ============================================================ */
import { api, poll, store } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, confirmModal, toast, checkGrid, provStrip, pipeline, metricStat, drawer,
} from "../components.js";
import { fmtInt, fmtNum, fmtUtc, fmtAge, fmtDuration, fmtMetric, humanKey, trunc, metricTone } from "../format.js";
import { statusInfo } from "../status.js";
import { navigate } from "../router.js";

/* ================= PAPER / SHADOW ================= */
export async function renderPaper(root) {
  skeletonInto(root, "stats");
  root.appendChild(page({
    crumb: "Trading", group: "Paper / Shadow",
    title: "Paper & Shadow",
    answer: h("b", null, "Simulated execution (PAPER) and would-be intents on real data (SHADOW). No order ever reaches a broker from these modes."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let paper = null, shadow = null;
  try { [paper, shadow] = await Promise.all([api.get("/api/paper"), api.get("/api/shadow")]); }
  catch (e) { host.appendChild(errorBox({ what: "paper/shadow state could not be loaded", next: "Retry.", raw: e.message })); return; }

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "PAPER", sub: "simulated fills — labeled simulation", icon: "layers",
      actions: [h("span", { class: "prov synthetic" }, "SIMULATED")],
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Fills", value: fmtInt(paper?.execution_statistics?.total_fills ?? paper?.fills?.length), icon: "zap" }),
          metricStat({ label: "Avg slippage", metric: paper?.execution_statistics?.avg_slippage_bps, icon: "scale", hint: "unmeasured slippage is UNAVAILABLE — never zero" }),
          stat({ label: "PnL (simulated)", value: fmtMetric(paper?.pnl), hint: "hypothetical — not real money", icon: "pulse" }),
        ),
        (paper?.fills ?? []).length
          ? table({
              columns: [
                { key: "time", label: "Time (UTC)", render: (f) => h("span", { class: "mono small" }, fmtUtc(f.time)) },
                { key: "price", label: "Price", num: true, render: (f) => fmtNum(f.price) },
                { key: "qty", label: "Qty", num: true, render: (f) => fmtNum(f.qty) },
              ],
              rows: paper.fills, empty: "No fills.",
            })
          : emptyState({ icon: "zap", title: "No simulated fills yet", desc: "Paper fills appear when a strategy runs in paper mode." }),
      ),
    }),
    card({ title: "SHADOW", sub: "would-be intents — risk/spread evaluated, nothing submitted", icon: "eye",
      actions: [h("span", { class: "prov" }, "WOULD-BE")],
      body: shadow
        ? h("div", { class: "stack" },
            h("div", { class: "stat-grid" },
              stat({ label: "Intents recorded", value: fmtInt(shadow.intents_count ?? (shadow.shadow_intents ?? []).length), icon: "eye" }),
              stat({ label: "Submitted orders", value: "0 — always", tone: "ok", icon: "shield" }),
            ),
            tech(shadow, "Raw shadow state"),
          )
        : emptyState({ icon: "eye", title: "No shadow intents yet", desc: "Shadow records what WOULD have been submitted, with risk and spread checks applied — nothing is sent to any broker." }),
    }),
  ));

  const diff = shadow?.shadow_vs_paper_discrepancy ?? shadow?.discrepancy ?? null;
  if (diff) {
    host.appendChild(card({ title: "Shadow vs paper discrepancy", sub: "systematic differences between simulation and reality proxies", icon: "scale", body: tech(diff, "Show discrepancy detail") }));
  }
}

/* ================= DEMO FORWARD ================= */
export async function renderDemo(root) {
  skeletonInto(root, "stats");
  const head = page({
    crumb: "Trading", group: "Demo forward",
    title: "Demo Forward Control",
    answer: h("b", null, "MT5 demo-account readiness and execution authority are separate. DEMO_FORWARD is observation-only; broker orders require DEMO_EXECUTION plus explicit authority and every safety gate."),
    actions: [
      h("button", { class: "btn", onclick: () => renderDemo(root) }, icon("refresh", 14), "Refresh"),
    ],
    body: null,
  });
  root.appendChild(head);
  const host = h("div", { class: "section" }); root.appendChild(host);
  let demoRetried = false;
  await refresh();

  async function refresh() {
    let readiness, state, safety, obs, config;
    try {
      [readiness, state, safety, obs, config] = await Promise.all([
        api.get("/api/demo/readiness"),
        api.get("/api/demo/state"),
        api.get("/api/demo/safety"),
        api.get("/api/demo/observations?limit=20"),
        api.get("/api/demo/config"),
      ]);
    } catch (e) {
      clear(host);
      host.appendChild(errorBox({ what: "demo state could not be loaded", next: "Use Retry. If readiness probing itself fails (no terminal), that is reported honestly below.", raw: e.message }));
      host.appendChild(h("div", { class: "mt-3" },
        h("button", { class: "btn primary", onclick: () => refresh() }, icon("refresh", 14), "Retry")));
      if (!demoRetried) {
        demoRetried = true;
        setTimeout(() => { if (document.contains(host)) refresh(); }, 4000);
      }
      return;
    }
    store.set("demoState", state);
    clear(host);

    /* --- authority banner: THE primary answer --- */
    const enabled = Boolean(state.enabled);
    const permitted = Boolean(state.execution_permitted);
    host.appendChild(banner(
      permitted ? "warn" : enabled ? "warn" : "info",
      `DEMO EXECUTION: ${String(state.state ?? (enabled ? "ENABLED" : "DISABLED")).toUpperCase()}`,
      permitted
        ? `Orders permitted within demo limits — readiness ${state.readiness_expired ? "EXPIRED — re-verify now" : `verified ${fmtDuration(state.readiness_age_s)} ago, re-verify every ${fmtDuration(state.reverify_ttl_s)}`}`
        : enabled
          ? "Enabled but not permitted — see blockers."
          : "Execution stays disabled until readiness passes and you explicitly acknowledge the demo limits. Observation alone is always safe.",
      permitted || enabled ? "alert" : "lock",
    ));

    /* --- readiness --- */
    const checks = readiness.checks ?? {};
    const allPass = Boolean(readiness.passed);
    host.appendChild(card({
      title: "Readiness — the 14-check gate", icon: "shield",
      sub: allPass ? `passed ${fmtAge(readiness.timestamp)}` : `${Object.values(checks).filter((v) => v === false).length} check(s) failing`,
      actions: [
        h("button", { class: "btn sm", onclick: runReadiness }, icon("refresh", 13), "Run readiness now"),
      ],
      body: h("div", { class: "stack" },
        allPass
          ? banner("ok", "ALL CHECKS PASSED", "Demo execution can be requested — enabling still requires your explicit confirmation and risk acknowledgment.", "check")
          : banner("warn", "READINESS NOT PASSED", (readiness.blocked_reasons ?? []).join(" · ") || "Failed checks listed below.", "alert"),
        checkGrid(checks, readiness.details ?? {}),
        tech(readiness, "Raw readiness report"),
      ),
    }));

    /* --- control: observe vs enable --- */
    host.appendChild(h("div", { class: "grid-2" },
      card({ title: "Observe only — always safe", sub: "records real ticks, submits zero orders", icon: "eye", body:
        h("div", { class: "stack" },
          kv([["Observation mode", String(config.observation_mode ?? "observe_only").toUpperCase()], ["Orders possible", "no — structurally"]]),
          h("div", { class: "row" },
            h("button", { class: "btn", onclick: async () => {
              try { await api.post("/api/observe/start"); toast("ok", "Observation started", "Zero orders will be submitted."); refresh(); }
              catch (e) { toast("err", "Could not start", explain(e)); }
            } }, icon("play", 14), "Start observation"),
            h("button", { class: "btn", onclick: async () => {
              try { await api.post("/api/observe/stop"); toast("warn", "Observation stopped"); refresh(); }
              catch (e) { toast("err", "Could not stop", explain(e)); }
            } }, icon("stop", 14), "Stop"),
          ),
          h("div", { class: "meta" }, "A DEMO terminal must be configured; without one this honestly reports failure instead of pretending."),
        ),
      }),
      card({ title: "Demo execution — gated", sub: "requires readiness + explicit acknowledgment", icon: "lock", body:
        h("div", { class: "stack" },
          enabled
            ? h("div", { class: "row" },
                h("button", { class: "btn danger", onclick: disableDemo }, icon("stop", 14), "Disable demo execution"),
                h("span", { class: "meta" }, `decided ${fmtAge(state.decided_at)}`),
              )
            : h("button", { class: "btn primary", onclick: enableDemo }, icon("lock", 14) , "Request demo execution enable"),
          h("div", { class: "meta" }, "Enable is refused (409) with the full blocker list unless a FRESH readiness report passes in the same request. The state is durable — a restart never silently changes it."),
        ),
      }),
    ));

    /* --- demo limits --- */
    const lim = safety?.demo_limits ?? {};
    host.appendChild(card({
      title: "Demo hard limits", sub: `independent conservative caps · config ${lim.config_hash ?? "—"}`, icon: "shield",
      actions: [h("span", { class: "prov demo" }, "DEMO LIMITS")],
      body: h("div", { class: "stat-grid" },
        stat({ label: "Max volume / order", value: `${fmtNum(lim.max_volume_per_order)} lots`, icon: "layers" }),
        stat({ label: "Max exposure", value: `${fmtNum(lim.max_simultaneous_exposure)} lots`, icon: "layers" }),
        stat({ label: "Order rate", value: `${fmtInt(lim.max_orders_per_minute)}/min`, icon: "clock" }),
        stat({ label: "Daily loss cap", value: `$${fmtNum(lim.max_daily_loss_usd, 0)}`, tone: "warn", icon: "alert" }),
        stat({ label: "Max spread", value: `${fmtNum(lim.max_spread_bps, 0)} bps`, icon: "activity" }),
        stat({ label: "Kill switch", value: lim.kill_switch_enabled ? "ARMED" : "UNAVAILABLE", tone: lim.kill_switch_enabled ? "ok" : "err", icon: "shield" }),
      ),
    }));

    /* --- observations table --- */
    host.appendChild(card({ title: "Recent demo observations", sub: "canonical store — provenance explicit", icon: "database", body:
      (obs ?? []).length
        ? table({
            columns: [
              { key: "timestamp", label: "Time (UTC)", render: (o) => h("span", { class: "mono small" }, fmtUtc(o.timestamp)) },
              { key: "bid", label: "Bid", num: true, render: (o) => fmtNum(o.bid) },
              { key: "ask", label: "Ask", num: true, render: (o) => fmtNum(o.ask) },
              { key: "prov", label: "Provenance", render: (o) => provStrip(o.provenance ?? o.data_class ?? "") },
              { key: "signal", label: "Signal", render: (o) => o.signal ? badge(String(o.signal).toUpperCase() === "NO_TRADE" ? "NO_TRADE" : "SIGNAL") : h("span", { class: "text-faint small" }, "—") },
            ],
            rows: obs, empty: "No demo observations yet.",
          })
        : emptyState({ icon: "database", title: "No real demo observations recorded yet", desc: "Start an observation session with the DEMO terminal connected. Every tick persists with full provenance." }),
    }));

    /* --- safety boundary --- */
    if (safety?.boundary) {
      host.appendChild(card({ title: "Environment boundary", sub: "what each mode may do — demo never grants live", icon: "shield", body:
        kv(Object.entries(safety.boundary).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
      }));
    }
  }

  async function runReadiness() {
    toast("info", "Running readiness", "Probing terminal, account, symbol, spec, data…");
    await refresh();
  }

  async function enableDemo() {
    const ok = await confirmModal({
      title: "Enable demo execution",
      danger: false,
      body: h("div", { class: "stack" },
        h("p", { class: "text-dim" }, "This asks the authoritative gate to permit REAL demo orders on the connected DEMO account. The gate re-verifies all readiness checks in this same request and refuses with the full blocker list if anything fails."),
        h("p", { class: "meta" }, "Demo execution is capped by independent conservative limits and labeled DEMO. It never makes the strategy live-eligible."),
      ),
      acks: [
        "confirmed — I explicitly request demo execution enablement now.",
        "risk_ack — I acknowledge the hard demo limits (volume, exposure, rate, daily loss, spread, kill switch) and that I will not bypass gates.",
      ],
      confirmLabel: "Request enable",
    });
    if (!ok) return;
    try {
      const r = await api.post("/api/demo/enable", { confirmed: true, risk_ack: true });
      toast("ok", "Demo execution ENABLED", `Authority state: ${r.state}`);
      refresh();
    } catch (e) {
      if (e.status === 409 && e.body) {
        toast("err", "Enable refused by the gate", `${(e.body.reasons ?? []).slice(0, 3).join(" · ") || "readiness not passed"}`);
        drawer("Enable refused — full blocker list", h("div", { class: "stack" },
          banner("err", "The gate refused — state remains DISABLED", "This is the safety architecture working. Fix the blockers and request again.", "shield"),
          h("ul", { class: "gate-list" }, (e.body.reasons ?? []).map((r) => h("li", null, r))),
          e.body.readiness ? tech(e.body.readiness, "Raw readiness report") : null,
        ));
        refresh();
      } else if (e.status === 400) {
        toast("err", "Missing acknowledgment", "The request requires confirmed=true and risk_ack=true.");
      } else {
        toast("err", "Enable request failed", explain(e));
      }
    }
  }

  async function disableDemo() {
    const ok = await confirmModal({
      title: "Disable demo execution",
      danger: true,
      body: "The demo execution permission is revoked immediately and durably. Observation can continue safely.",
      confirmLabel: "Disable",
    });
    if (!ok) return;
    try { await api.post("/api/demo/disable"); toast("ok", "Demo execution disabled"); refresh(); }
    catch (e) { toast("err", "Disable failed", explain(e)); }
  }
}

/* ================= EXECUTION ================= */
const ORDER_STAGES = ["INTENT", "RISK", "PREFLIGHT", "SUBMIT", "BROKER ACK", "FILL", "RECONCILE"];

export async function renderExecution(root) {
  skeletonInto(root, "stats");
  root.appendChild(page({
    crumb: "Trading", group: "Execution",
    title: "Execution Center",
    answer: h("b", null, "The complete order lifecycle: intent → risk → preflight → submit → broker ACK → fill → reconcile. Unmeasured values display as UNAVAILABLE, never zero."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let orders = [];
  try { orders = await api.get("/api/execution/orders?limit=50"); }
  catch (e) { host.appendChild(errorBox({ what: "orders could not be loaded", next: "Retry.", raw: e.message })); return; }

  try {
    const account = await api.get("/api/dashboard");
    host.appendChild(card({ title: "Account snapshot", sub: "Canonical dashboard metrics; UNAVAILABLE is not zero. Refresh this page to retrieve a new snapshot.", icon: "bank",
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          metricStat({ label: "Equity", metric: account.equity }),
          metricStat({ label: "Balance", metric: account.balance }),
          metricStat({ label: "Exposure", metric: account.exposure }),
          metricStat({ label: "Spread", metric: account.spread })),
        Array.isArray(account.open_positions) && account.open_positions.length
          ? table({ columns: [{key: "symbol", label: "Symbol"}, {key: "side", label: "Side"}, {key: "volume", label: "Volume", num: true}, {key: "profit", label: "P&L", num: true}], rows: account.open_positions })
          : h("p", {class: "text-dim"}, account.balance?.status === "MEASURED" ? "No positions reported in this snapshot." : "Position state UNAVAILABLE — account measurements are not established."),
        tech(account, "Raw account snapshot")) }));
  } catch (e) { host.appendChild(errorBox({ what: "account snapshot unavailable", next: "Retry this page; order-event evidence below is independent.", raw: e.message })); }

  host.appendChild(card({ title: "Lifecycle reference", sub: "each stage is audited with its own timestamp", icon: "branch", body:
    pipeline(ORDER_STAGES, ORDER_STAGES.length, -1),
  }));

  host.appendChild(card({
    title: "Orders", sub: `${orders.length} recent event(s)`, icon: "zap",
    body: orders.length
      ? table({
          columns: [
            { key: "time", label: "Time (UTC)", render: (o) => h("span", { class: "mono small" }, fmtUtc(o.time)) },
            { key: "type", label: "Event", render: (o) => badge(String(o.type ?? "event").toUpperCase()) },
            { key: "lifecycle", label: "Lifecycle", render: (o) => o.lifecycle ? h("span", { class: "mono small" }, String(o.lifecycle).toUpperCase()) : h("span", { class: "text-faint small" }, "—") },
            { key: "reason", label: "Detail", render: (o) => h("span", { class: "small text-dim" }, trunc(o.payload?.reason ?? o.payload?.event ?? "", 80)) },
          ],
          rows: [...orders].reverse(),
          empty: "No orders.",
          onRowClick: (o) => drawer(`Order event — ${o.type ?? ""}`, h("div", { class: "stack" },
            kv([["Time (UTC)", fmtUtc(o.time)], ["Type", String(o.type ?? "").toUpperCase()], ["Lifecycle", String(o.lifecycle ?? "—").toUpperCase()]]),
            o.payload && (o.payload.requested_price || o.payload.executed_price)
              ? h("div", { class: "stat-grid" },
                  stat({ label: "Requested", value: fmtNum(o.payload.requested_price) }),
                  stat({ label: "Executed", value: fmtNum(o.payload.executed_price) }),
                  stat({ label: "Slippage", value: o.payload.slippage_bps ?? "UNAVAILABLE" }),
                  stat({ label: "Latency", value: o.payload.latency_ms ? `${o.payload.latency_ms}ms` : "UNAVAILABLE" }),
                )
              : null,
            tech(o, "Raw order event"),
          )),
        })
      : emptyState({
          icon: "zap", title: "No real executions recorded yet",
          desc: "Demo execution requires: the 14-check readiness gate passed, demo execution explicitly enabled with risk acknowledgment, and mode-correct configuration. Nothing here is simulated to look busy.",
          actions: [h("button", { class: "btn", onclick: () => navigate("#/trading/demo") }, icon("shield", 14), "Open Demo Control")],
        }),
  }));
}

/* ================= COMPARISON ================= */
export async function renderComparison(root) {
  skeletonInto(root, "stats");
  root.appendChild(page({
    crumb: "Trading", group: "Comparison",
    title: "Paper · Shadow · Demo Comparison",
    answer: h("b", null, "How simulated expectations compare with real demo outcomes — computed fresh on request, never cached optimism."),
    actions: [h("button", { class: "btn", onclick: async () => {
      try { await api.post("/api/demo/comparison/refresh"); toast("ok", "Comparison refreshed"); renderComparison(root); }
      catch (e) { toast("err", "Refresh failed", explain(e)); }
    } }, icon("refresh", 14), "Refresh comparison")],
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let comp = null;
  try { comp = await api.get("/api/demo/comparison"); }
  catch (e) { host.appendChild(errorBox({ what: "comparison could not be loaded", next: "Retry.", raw: e.message })); return; }

  const metrics = Object.entries(comp?.metrics ?? comp ?? {})
    .filter(([, v]) => typeof v === "object" && v !== null && ("status" in v || "value" in v));
  if (metrics.length) {
    host.appendChild(card({ title: "Measured comparison", icon: "scale", body:
      h("div", { class: "stat-grid" },
        metrics.map(([k, m]) => metricStat({ label: humanKey(k), metric: m })),
      ),
    }));
  } else {
    host.appendChild(card({ title: "Measured comparison", icon: "scale", body:
      emptyState({
        icon: "scale", title: "No comparable demo executions yet",
        desc: "Comparison metrics (signal agreement, expected vs actual entry, slippage, latency) require real demo executions. Until then every field reports UNAVAILABLE — comparison is never fabricated from simulation alone.",
        actions: [h("button", { class: "btn", onclick: () => navigate("#/trading/demo") }, icon("shield", 14), "Demo control")],
      }),
    }));
  }
  host.appendChild(tech(comp, "Raw comparison evidence"));
}

/* ---------- helpers ---------- */
function explain(e) {
  if (e.status === 0) return "API unreachable — is the QTS backend running?";
  const d = e.body;
  if (d && typeof d === "object") return String(d.detail?.detail ?? d.detail ?? d.reasons?.[0] ?? e.message).slice(0, 160);
  return String(e.message).slice(0, 160);
}
