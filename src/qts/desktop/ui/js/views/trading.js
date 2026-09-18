/* Trading — Paper/Shadow (simulation) · Demo Forward (readiness + authority) · Execution · Comparison */
import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness } from "../operations.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, confirmModal, toast, checkGrid, provStrip, pipeline, metricStat, drawer,
} from "../components.js";
import { fmtInt, fmtNum, fmtUtc, fmtAge, fmtDuration, fmtMetric, humanKey, trunc } from "../format.js";
import { navigate, onDispose } from "../router.js";

function explain(e) {
  if (e.status === 0) return "API unreachable — is the QTS backend running?";
  const d = e.body;
  if (d && typeof d === "object") return String(d.detail?.detail ?? d.detail ?? d.reasons?.[0] ?? e.message).slice(0, 160);
  return String(e.message).slice(0, 160);
}

/* Paper / Shadow — simulation only, never broker */
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
  if (diff) host.appendChild(card({ title: "Shadow vs paper discrepancy", sub: "systematic differences between simulation and reality proxies", icon: "scale", body: tech(diff, "Show discrepancy detail") }));
}

/* Demo Forward — authority + readiness are separate */
export async function renderDemo(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  const head = page({
    crumb: "Trading", group: "Demo forward",
    title: "Demo Forward Control",
    answer: h("b", null, "Readiness and execution permission are separate. A passing connection check never enables execution. DEMO_FORWARD is observation-only; orders require DEMO_EXECUTION plus explicit authority."),
    actions: [
      h("button", { class: "btn", onclick: () => refresh(true) }, icon("refresh", 14), "Refresh sources"),
    ],
    body: null,
  });
  root.appendChild(head);

  const activity = h("h2", { id: "demo-activity" }, "Loading authority…");
  const next = h("a", { class: "btn primary", href: "#/system/setup" }, "Inspect setup");
  const nextWhy = h("p", { class: "text-dim small" });
  root.appendChild(h("section", { class: "operator-summary", "aria-labelledby": "demo-activity" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / AUTHORITY"), activity),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT MEANINGFUL ACTION"), next, nextWhy)));

  const factsBody = h("tbody");
  const factCells = {};
  const host = h("div", { class: "section" });
  root.appendChild(host);

  let lastReadiness = null, lastState = null, lastSafety = null, lastObs = null, lastConfig = null;
  let acting = false;

  function renderFacts() {
    const s = operationalState(store.data);
    const rows = [
      ["mode", "Environment / mode", s.mode.mode, "Environment capability is not execution permission."],
      ["broker", "Broker (MT5)", s.broker, "Terminal connectivity; not proof of healthy quote."],
      ["observation", "Observation collector", s.observation, s.obs?.last_error ? `Last error: ${s.obs.last_error}` : s.obs?.note || "No active collection established."],
      ["permission", "DEMO execution", s.permission, s.sources.demoState.current ? `Authority state ${s.demo?.state ?? "UNAVAILABLE"}; readiness and permission are separate.` : "Permission source unavailable or stale."],
      ["liveLabel", "LIVE governance", s.liveLabel, "Never auto-enabled from DEMO evidence."],
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
      const meta = store.data.resources[key === "mode" || key === "broker" ? "health" : key === "observation" ? "observe" : key === "permission" ? "demoState" : "live"];
      const f = meta ? freshness(meta, key === "mode" || key === "broker" ? "health" : key === "observation" ? "observe" : key === "permission" ? "demoState" : "live") : { label: "UNAVAILABLE", current: false };
      c.fresh.textContent = `${f.label}${meta?.updatedAt ? ` · ${fmtAge(meta.updatedAt)}` : ""}`;
    }
    activity.textContent = `${s.observation} · DEMO ${s.permission} · LIVE ${s.liveLabel}`;
    if (s.permission === "DISABLED") {
      next.textContent = "Review readiness blockers"; next.href = "#/trading/demo"; nextWhy.textContent = "Execution disabled. Observation does not require enabling it. Fix blockers only if you intend to request DEMO execution.";
    } else if (s.permission === "CONFLICT · INSPECT") {
      next.textContent = "Inspect permission conflict"; next.href = "#/system/diagnostics"; nextWhy.textContent = "Mode and authority disagree. Current permission cannot be established.";
    } else if (s.sources.health.current && String(s.health?.mt5).toLowerCase() !== "connected") {
      next.textContent = "Review MT5 connection"; next.href = "#/system/mt5"; nextWhy.textContent = "Terminal not connected. No permission can be established.";
    } else {
      next.textContent = "Inspect observation evidence"; next.href = "#/market/observations"; nextWhy.textContent = s.next.why;
    }
  }

  async function refresh(force = false) {
    if (acting) return;
    try {
      const [readiness, state, safety, obs, config] = await Promise.all([
        api.get("/api/demo/readiness"),
        api.get("/api/demo/state"),
        api.get("/api/demo/safety"),
        api.get("/api/demo/observations?limit=20"),
        api.get("/api/demo/config"),
      ]);
      lastReadiness = readiness; lastState = state; lastSafety = safety; lastObs = obs; lastConfig = config;
      store.set("demoState", state);
      // keep health/observe/live from shell resources if available
      if (force) await Promise.all(Object.keys(RESOURCES).map((k) => syncResource(k, { force: true })));
      render();
    } catch (e) {
      clear(host);
      host.appendChild(errorBox({ what: "demo authority could not be loaded", next: "Retry. If readiness probing fails, terminal is not installed — that is honest, not a silent pass.", raw: e.message }));
      host.appendChild(h("div", { class: "mt-3" }, h("button", { class: "btn primary", onclick: () => refresh(true) }, icon("refresh", 14), "Retry")));
    }
  }

  function render() {
    if (!lastReadiness || !lastState) return;
    clear(host);
    renderFacts();

    const s = operationalState(store.data);
    const enabled = Boolean(lastState.enabled);
    const permitted = Boolean(lastState.execution_permitted) && lastState.state === "ENABLED" && s.mode.mode === "DEMO_EXECUTION";

    host.appendChild(h("section", { class: "operator-section" },
      h("h2", null, "Operating facts"),
      h("div", { class: "tbl-wrap", tabindex: "0" },
        h("table", { class: "tbl facts-table" },
          h("thead", null, h("tr", null, ["Source", "Reported state", "Meaning / constraint", "API freshness"].map((t) => h("th", { scope: "col" }, t)))),
          factsBody))));

    host.appendChild(banner(
      permitted ? "warn" : enabled ? "warn" : "info",
      `DEMO EXECUTION: ${String(lastState.state ?? (enabled ? "ENABLED" : "DISABLED")).toUpperCase()}${permitted ? "" : s.permission === "CONFLICT · INSPECT" ? " — CONFLICT" : ""}`,
      permitted
        ? `Orders permitted within demo limits — readiness ${lastState.readiness_expired ? "EXPIRED — re-verify now" : `verified ${fmtDuration(lastState.readiness_age_s)} ago, re-verify every ${fmtDuration(lastState.reverify_ttl_s)}`}`
        : enabled
          ? `Enabled but not permitted — mode ${s.mode.mode} or additional gate blocks. ${lastState.reasons?.join("; ") || ""}`
          : "Execution disabled until readiness passes and you explicitly acknowledge demo limits. Observation alone is always safe.",
      permitted || enabled ? "alert" : "lock",
    ));

    const checks = lastReadiness.checks ?? {};
    const allPass = Boolean(lastReadiness.passed);
    host.appendChild(card({
      title: "Readiness — 14-check gate (fresh probe)", icon: "shield",
      sub: allPass ? `passed ${fmtAge(lastReadiness.timestamp)}` : `${Object.values(checks).filter((v) => v === false).length} failing`,
      actions: [h("button", { class: "btn sm", onclick: () => refresh(true) }, icon("refresh", 13), "Run readiness now")],
      body: h("div", { class: "stack" },
        allPass
          ? banner("ok", "ALL CHECKS PASSED", "Passing readiness does not enable execution. Enabling still requires explicit confirmation and risk acknowledgment.", "check")
          : banner("warn", "READINESS NOT PASSED", (lastReadiness.blocked_reasons ?? []).join(" · ") || "Failed checks listed below.", "alert"),
        checkGrid(checks, lastReadiness.details ?? {}),
        h("details", null, h("summary", null, "Raw readiness report / technical evidence"), tech(lastReadiness, "Raw readiness")),
      ),
    }));

    host.appendChild(h("div", { class: "grid-2" },
      card({ title: "Observe only — always safe", sub: "records real ticks, submits zero orders", icon: "eye", body:
        h("div", { class: "stack" },
          kv([[ "Observation mode", String(lastConfig?.observation_mode ?? "observe_only").toUpperCase()], ["Orders possible", "no — structurally"], ["Collector", s.observation]]),
          h("div", { class: "row" },
            h("button", { class: "btn", disabled: acting || s.observing, onclick: async () => {
              acting = true; try { const r = await api.post("/api/observe/start"); if (r.status?.state !== "OBSERVING") throw new Error(r.note || "Backend did not confirm OBSERVING"); toast("ok","Observation confirmed","Zero orders."); await refresh(); } catch (e){ toast("err","Could not start",explain(e)); } finally { acting=false; }
            } }, icon("play", 14), "Start observation"),
            h("button", { class: "btn", disabled: acting || !s.observing, onclick: async () => {
              acting = true; try { await api.post("/api/observe/stop"); toast("warn","Observation stopped"); await refresh(); } catch (e){ toast("err","Could not stop",explain(e)); } finally { acting=false; }
            } }, icon("stop", 14), "Stop"),
          ),
          h("div", { class: "meta" }, "A DEMO terminal must be configured; without one this honestly reports failure instead of pretending."),
        ),
      }),
      card({ title: "Demo execution — gated", sub: "requires readiness + explicit acknowledgment + DEMO_EXECUTION mode", icon: "lock", body:
        h("div", { class: "stack" },
          h("p", { class: "text-dim small" }, `Authority reports ${s.permission}. Mode ${s.mode.mode} — ${s.mode.blurb}`),
          enabled
            ? h("div", { class: "row" },
                h("button", { class: "btn danger", disabled: acting, onclick: disableDemo }, icon("stop", 14), "Disable demo execution"),
                h("span", { class: "meta" }, `decided ${fmtAge(lastState.decided_at)}`),
              )
            : h("button", { class: "btn primary", disabled: acting || !allPass, onclick: enableDemo }, icon("lock", 14), "Request demo execution enable"),
          !allPass && !enabled ? h("p", { class: "text-dim small" }, "Enable is disabled while readiness fails. Fix blockers and re-run readiness.") : null,
          h("div", { class: "meta" }, "Enable is refused (409) with full blocker list unless a FRESH readiness report passes in the same request. State is durable — restart never silently changes it."),
          h("details", null, h("summary", null, "Why DEMO is not an ordinary switch / evidence"), 
            h("ul", { class: "reason-list" },
              [ `Authority state: ${lastState.state}`, `Execution permitted: ${String(lastState.execution_permitted)}`, `Mode: ${s.mode.mode}`, ...(lastState.reasons || []).map((r) => `Permission: ${r}`), ...(lastReadiness.blocked_reasons || []).map((r) => `Readiness: ${r}`)].map((x) => h("li", null, x))
            )
          ),
        ),
      }),
    ));

    const lim = lastSafety?.demo_limits ?? {};
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

    host.appendChild(card({ title: "Recent demo observations", sub: "canonical store — provenance explicit, not a completeness proof", icon: "database", body:
      (lastObs ?? []).length
        ? table({
            columns: [
              { key: "timestamp", label: "Time (UTC)", render: (o) => h("span", { class: "mono small" }, fmtUtc(o.timestamp)) },
              { key: "bid", label: "Bid", num: true, render: (o) => fmtNum(o.bid) },
              { key: "ask", label: "Ask", num: true, render: (o) => fmtNum(o.ask) },
              { key: "prov", label: "Provenance", render: (o) => provStrip(o.provenance ?? o.data_class ?? "") },
              { key: "signal", label: "Signal", render: (o) => o.signal ? badge(String(o.signal).toUpperCase() === "NO_TRADE" ? "NO_TRADE" : "SIGNAL") : h("span", { class: "text-faint small" }, "—") },
            ],
            rows: lastObs, empty: "No demo observations yet.",
          })
        : emptyState({ icon: "database", title: "No real demo observations recorded yet", desc: "Start an observation session with the DEMO terminal connected. Every tick persists with full provenance." }),
    }));

    if (lastSafety?.boundary) {
      host.appendChild(card({ title: "Environment boundary", sub: "what each mode may do — demo never grants live", icon: "shield", body:
        kv(Object.entries(lastSafety.boundary).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
      }));
    }
    host.appendChild(h("details", null, h("summary", null, "Raw authority snapshots / technical evidence"), tech({ readiness: lastReadiness, state: lastState, safety: lastSafety, config: lastConfig }, "Raw authority")));
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
    acting = true;
    try {
      const r = await api.post("/api/demo/enable", { confirmed: true, risk_ack: true });
      toast("ok", "Demo execution ENABLED", `Authority state: ${r.state}`);
      await refresh(true);
    } catch (e) {
      if (e.status === 409 && e.body) {
        toast("err", "Enable refused by the gate", `${(e.body.reasons ?? []).slice(0, 3).join(" · ") || "readiness not passed"}`);
        drawer("Enable refused — full blocker list", h("div", { class: "stack" },
          banner("err", "The gate refused — state remains DISABLED", "This is the safety architecture working. Fix the blockers and request again.", "shield"),
          h("ul", { class: "gate-list" }, (e.body.reasons ?? []).map((r) => h("li", null, r))),
          e.body.readiness ? tech(e.body.readiness, "Raw readiness report") : null,
        ));
        await refresh(true);
      } else if (e.status === 400) {
        toast("err", "Missing acknowledgment", "The request requires confirmed=true and risk_ack=true.");
      } else {
        toast("err", "Enable request failed", explain(e));
      }
    } finally { acting = false; }
  }

  async function disableDemo() {
    const ok = await confirmModal({
      title: "Disable demo execution",
      danger: true,
      body: "The demo execution permission is revoked immediately and durably. Observation can continue safely.",
      confirmLabel: "Disable",
    });
    if (!ok) return;
    acting = true;
    try { await api.post("/api/demo/disable"); toast("ok", "Demo execution disabled"); await refresh(true); }
    catch (e) { toast("err", "Disable failed", explain(e)); }
    finally { acting = false; }
  }

  const off = store.on("resources", renderFacts);
  onDispose(root, off);
  await refresh();
}

/* Execution Center */
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
          ? table({ columns: [{key: "symbol", label: "Symbol"}, {key: "side", label: "Side"}, {key: "volume", label: "Volume", num: true}, {key: "profit", label: "P&L", num: true}], rows: account.open_positions, dense: true })
          : h("p", {class: "text-dim"}, account.balance?.status === "MEASURED" ? "No positions reported in this snapshot." : "Position state UNAVAILABLE — account measurements are not established."),
        h("details", null, h("summary", null, "Raw account snapshot / technical evidence"), tech(account, "Raw account snapshot")))}));
  } catch (e) { host.appendChild(errorBox({ what: "account snapshot unavailable", next: "Retry this page; order-event evidence below is independent.", raw: e.message })); }

  host.appendChild(card({ title: "Lifecycle reference", sub: "each stage is audited with its own timestamp", icon: "branch", body:
    pipeline(ORDER_STAGES, ORDER_STAGES.length, -1),
  }));

  host.appendChild(card({
    title: "Orders", sub: `${orders.length} recent event(s) — dense, sortable, drawer for detail`, icon: "zap",
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
          dense: true,
          onRowClick: (o) => drawer(`Order event — ${o.type ?? ""}`, h("div", { class: "stack" },
            kv([[ "Time (UTC)", fmtUtc(o.time)], ["Type", String(o.type ?? "").toUpperCase()], ["Lifecycle", String(o.lifecycle ?? "—").toUpperCase()]]),
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

/* Comparison */
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
  host.appendChild(h("details", null, h("summary", null, "Raw comparison evidence / technical"), tech(comp, "Raw comparison evidence")));
}
