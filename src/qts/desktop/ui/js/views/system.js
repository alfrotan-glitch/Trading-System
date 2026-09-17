/* ============================================================
   VIEW GROUP: SYSTEM — setup, MT5, diagnostics
   The unglamorous but critical plumbing, made calm and clear.
   ============================================================ */
import { api } from "../api.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, checkGrid, toast, confirmModal,
} from "../components.js";
import { fmtUtc, humanKey, trunc } from "../format.js";
import { modeInfo } from "../status.js";
import { navigate } from "../router.js";

/* ================= SETUP WIZARD ================= */
export async function renderSetup(root) {
  const head = page({
    crumb: "System", group: "Setup",
    title: "Setup",
    answer: h("b", null, "Guided configuration — no code editing. Progress is verified against the live system at each step."),
    body: null,
  });
  root.appendChild(head);
  const host = h("div", { class: "section" }); root.appendChild(host);

  /* load current setup (credential-free) */
  let saved = null, safety = null, env = null;
  try {
    [saved, safety, env] = await Promise.all([
      api.get("/api/setup/mt5"),
      api.get("/api/demo/safety"),
      api.get("/api/env/boundary"),
    ]);
  } catch { /* first run: defaults below */ }
  const setup = saved?.setup ?? {};

  /* ---- step 1: environment ---- */
  const envOpts = [
    ["development", "Development", "Backtest and research only — mock or historical data, zero broker contact."],
    ["paper", "Paper", "Simulated fills on recorded data, next-bar-open execution. No real orders."],
    ["shadow", "Shadow", "Real market data; would-be intents with risk/spread checks. Nothing is submitted."],
    ["demo_forward", "Demo Forward", "REAL MT5 DEMO terminal + REAL market data + REAL demo order lifecycle — labeled DEMO, never LIVE."],
  ];
  const currentEnv = env?.resolution?.effective_mode ?? "development";
  host.appendChild(card({
    title: "Step 1 · Choose the environment", icon: "layers",
    sub: `currently effective: ${modeInfo(currentEnv).mode}`,
    body: h("div", { class: "stack" },
      envOpts.map(([val, label, desc]) => h("label", { class: "check", style: { cursor: "pointer", display: "flex" } },
        h("input", { type: "radio", name: "setup-env", value: val, checked: val === currentEnv || (currentEnv === "dev" && val === "development") }),
        h("div", null,
          h("div", { class: "name" }, label),
          h("div", { class: "detail" }, desc),
        ),
      )),
      banner("warn", "LIVE is separately gated", "No environment choice here can unlock live trading. Governance decides — with human approval, after every scientific and safety gate.", "lock"),
    ),
  }));

  /* ---- step 2: MT5 ---- */
  const path = h("input", { class: "input", value: setup.terminal_path ?? "", placeholder: "C:\\Program Files\\MetaTrader 5\\terminal64.exe" });
  const symbol = h("input", { class: "input", value: setup.symbol ?? "XAUUSD" });
  host.appendChild(card({
    title: "Step 2 · MT5 terminal & instrument", icon: "bank",
    sub: "credentials stay out of QTS — set QTS_MT5_LOGIN / QTS_MT5_PASSWORD / QTS_MT5_SERVER in your OS credential store or environment",
    body: h("div", { class: "stack" },
      h("div", { class: "field" }, h("label", null, "Terminal path"), path,
        h("div", { class: "hint" }, "Full path to terminal64.exe. Broker symbol names may differ (e.g. XAUUSD@) — use the broker's exact name or QTS_MT5_SYMBOL_MAP.")),
      h("div", { class: "field" }, h("label", null, "Symbol (canonical QTS name)"), symbol),
      h("div", { class: "row" },
        h("button", { class: "btn primary", onclick: saveSetup }, icon("check", 14), "Save setup"),
        h("button", { class: "btn", onclick: testConnection }, icon("shield", 14), "Test connection (14 checks)"),
      ),
      h("div", { id: "setup-test-result" }),
    ),
  }));

  /* ---- step 3: risk acknowledgment ---- */
  const lim = safety?.demo_limits ?? {};
  host.appendChild(card({
    title: "Step 3 · Acknowledge hard limits", icon: "shield",
    body: h("div", { class: "stack" },
      h("div", { class: "stat-grid" },
        stat({ label: "Max volume / order", value: `${lim.max_volume_per_order ?? "—"} lots` }),
        stat({ label: "Max exposure", value: `${lim.max_simultaneous_exposure ?? "—"} lots` }),
        stat({ label: "Daily loss cap", value: `$${lim.max_daily_loss_usd ?? "—"}` }),
        stat({ label: "Kill switch", value: lim.kill_switch_enabled ? "ARMED" : "—", tone: "ok" }),
      ),
      banner("danger", "Acknowledgement is stored durably", "Enabling demo execution requires a separate, explicit acknowledgment in Demo Control. Nothing is enabled from this page.", "alert"),
    ),
  }));

  /* ---- step 4: where things live ---- */
  host.appendChild(card({
    title: "Step 4 · Where logs & evidence live", icon: "database",
    body: kv([
      ["Audit log", h("span", { class: "mono small" }, "logs/audit.jsonl (redacted) + SQLite audit_events")],
      ["Evidence", h("span", { class: "mono small" }, "data/evidence/*.json — written by the system, readable in Evidence Explorer")],
      ["Canonical observations", h("span", { class: "mono small" }, "data/sqlite/forward_observatory.db")],
      ["Rule", "Never edit these by hand — the UI and CLI read them for you."],
    ]),
  }));

  async function saveSetup() {
    try {
      await api.post("/api/setup/mt5", { terminal_path: path.value, symbol: symbol.value });
      toast("ok", "Setup saved", "Terminal path and symbol persisted (credential-free).");
      renderSetup(root);
    } catch (e) {
      toast("err", "Could not save setup", String(e.message).slice(0, 140));
    }
  }

  async function testConnection() {
    const out = document.getElementById("setup-test-result");
    out.replaceChildren(banner("info", "Running readiness checks…", "Probing terminal, account, symbol, spec, data freshness.", "info"));
    try {
      const r = await api.get(`/api/demo/readiness?terminal_path=${encodeURIComponent(path.value)}&symbol=${encodeURIComponent(symbol.value)}`);
      out.replaceChildren(
        banner(r.passed ? "ok" : "warn", r.passed ? "ALL READINESS CHECKS PASSED" : "READINESS NOT PASSED", (r.blocked_reasons ?? []).join(" · ") || "Review the failing checks below.", r.passed ? "check" : "alert"),
        checkGrid(r.checks ?? {}, r.details ?? {}),
      );
    } catch (e) {
      out.replaceChildren(errorBox({ what: "the readiness probe failed", known: "No terminal answered or the path is wrong. In development without MT5 this is expected.", next: "Verify the path, or continue in development mode — research does not need a terminal.", raw: e.message }));
    }
  }
}

/* ================= MT5 ================= */
export async function renderMT5(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "System", group: "MT5",
    title: "MT5 Connection",
    answer: h("b", null, "Terminal, account and instrument state — mock and real are always explicitly distinguished."),
    actions: [h("button", { class: "btn", onclick: () => renderMT5(root) }, icon("refresh", 14), "Refresh")],
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let m = null;
  try { m = await api.get("/api/mt5"); }
  catch (e) { host.appendChild(errorBox({ what: "MT5 state could not be loaded", next: "Retry.", raw: e.message })); return; }

  const connected = Boolean(m.connected);
  host.appendChild(h("div", { class: "stat-grid" },
    stat({ label: "Module mode", value: String(m.mode ?? "UNAVAILABLE").toUpperCase(), tone: String(m.mode).toUpperCase().includes("REAL") ? "ok" : "warn", hint: "REAL = real terminal in use; MOCK = simulated module", icon: "bank" }),
    stat({ label: "Connection", value: connected ? "CONNECTED" : String(m.terminal_status ?? "DISCONNECTED").toUpperCase(), tone: connected ? "ok" : "neutral", icon: "activity" }),
  ));

  if (m.warning) host.appendChild(banner("warn", "Connection advisory", m.warning, "alert"));

  host.appendChild(h("div", { class: "grid-2" },
    card({ title: "Account", icon: "bank", body: m.account
      ? h("div", { class: "stack" },
          metricStatCard(m.account, "Account state"),
          tech(m.account, "Raw account metric"),
        )
      : emptyState({ icon: "bank", title: "Account state unavailable", desc: "No terminal context in this process. Attach a terminal in Setup and verify with readiness." }),
    }),
    card({ title: "Symbol spec", icon: "fileCheck", body: m.spec
      ? h("div", { class: "stack" },
          metricStatCard(m.spec, "Symbol spec"),
          tech(m.spec, "Raw spec metric"),
        )
      : emptyState({ icon: "fileCheck", title: "Symbol spec unavailable", desc: "The authoritative contract (volume steps, stops, filling mode) requires a connected terminal. Missing metadata is never guessed in safety-critical paths." }),
    }),
  ));

  host.appendChild(banner("info", "Mock ≠ real, always labeled", "When no terminal is attached QTS uses an explicitly labeled mock module. Mock data is rendered as SYNTHETIC everywhere in this UI and is never eligible as evidence of broker behavior.", "info"));
}

function metricStatCard(metric, label) {
  const ok = metric?.status === "MEASURED" || metric?.status === "OK";
  return h("div", { class: "stat-grid" },
    stat({ label, value: ok ? String(metric.value) : String(metric?.status ?? "UNAVAILABLE").toUpperCase(), tone: ok ? "ok" : "neutral", hint: metric?.reason ?? null }),
  );
}

/* ================= DIAGNOSTICS ================= */
export async function renderDiagnostics(root) {
  skeletonInto(root);
  root.appendChild(page({
    crumb: "System", group: "Diagnostics",
    title: "System Diagnostics",
    answer: h("b", null, "Startup checks, durable-state restoration, and the environment boundary matrix — the honest plumbing view."),
    actions: [h("button", { class: "btn", onclick: () => renderDiagnostics(root) }, icon("refresh", 14), "Refresh")],
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);

  let health = null, env = null;
  try { [health, env] = await Promise.all([api.get("/api/health"), api.get("/api/env/boundary")]); }
  catch (e) { host.appendChild(errorBox({ what: "diagnostics could not be loaded", next: "Retry; if the API is down, restart QTS from the launcher.", raw: e.message })); return; }

  host.appendChild(card({ title: "Environment boundary matrix", sub: "what each mode may and may not do", icon: "shield", body:
    kv(Object.entries(env?.boundary ?? {}).map(([k, v]) => [k, h("span", { class: "small text-dim" }, v)])),
  }));

  const res = env?.resolution ?? {};
  host.appendChild(card({ title: "Mode resolution", icon: "layers", body: h("div", { class: "stack" },
    h("div", { class: "stat-grid" },
      stat({ label: "Effective mode", value: modeInfo(res.effective_mode).mode }),
      stat({ label: "Broker submission", value: res.can_submit_broker_orders ? "possible" : "impossible", tone: res.can_submit_broker_orders ? "warn" : "ok" }),
      stat({ label: "Real broker data", value: res.uses_real_broker_data ? "yes" : "no" }),
      stat({ label: "Money at risk", value: res.money_at_risk ? "YES" : "no", tone: res.money_at_risk ? "err" : "ok" }),
    ),
    res.restart_semantics ? banner("info", "Restart semantics", res.restart_semantics, "info") : null,
    res.resolution_error ? banner("err", "Resolution error", res.resolution_error, "alert") : null,
    tech(env, "Raw environment boundary"),
  )}));

  host.appendChild(card({ title: "Health detail", sub: `reported ${fmtUtc(health?.timestamp)}`, icon: "activity", body:
    h("div", { class: "stack" },
      h("div", { class: "check-grid" },
        ["mt5", "market_data", "risk", "reconciliation"].map((k) => {
          const v = health?.[k];
          const ok = String(v).toLowerCase().includes("healthy") || String(v).toLowerCase() === "connected";
          return h("div", { class: `check ${ok ? "pass" : "na"}` },
            h("div", { class: "mark" }, ok ? "✓" : "!"),
            h("div", null, h("div", { class: "name" }, humanKey(k)), h("div", { class: "detail" }, String(v ?? "UNAVAILABLE"))),
          );
        }),
      ),
      health?.reconciliation_detail ? banner("info", "Reconciliation", health.reconciliation_detail, "info") : null,
      tech(health, "Raw health report"),
    ),
  }));
}
