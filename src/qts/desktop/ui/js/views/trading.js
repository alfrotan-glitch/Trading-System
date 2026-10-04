/* Trading — Paper/Shadow · Demo Forward · Execution · Comparison
   Safety is primary: DEMO vs LIVE unmistakable, what blocked why what next explicit. */

import { api, store, RESOURCES, syncResource } from "../api.js";
import { operationalState, freshness, demoSentence } from "../operations.js";
import { h, icon, clear } from "../dom.js";
import {
  card, badge, page, table, emptyState, skeletonInto, tech, kv, stat, errorBox,
  banner, confirmModal, toast, checkGrid, provStrip, pipeline, metricStat, drawer,
} from "../components.js";
import { fmtInt, fmtNum, fmtUtc, fmtAge, fmtDuration, fmtMetric, humanKey, trunc } from "../format.js";
import { navigate, onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";

function explain(e) {
  if (e.status === 0) return "API unreachable — is QTS backend running?";
  const d = e.body;
  if (d && typeof d === "object") return String(d.detail?.detail ?? d.detail ?? d.reasons?.[0] ?? e.message).slice(0, 160);
  return String(e.message).slice(0, 160);
}

/* Paper / Shadow */
export async function renderPaper(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Trading", group: "Paper / Shadow",
    title: "Practice",
    answer: h("b", null, "Practice fills and would-be trades. Nothing here is sent to a broker. This is not a real account, and it is not live trading."),
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
              rows: paper.fills, empty: "No fills.", dense: true,
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

/* Demo account — guided product workflow.
   A normal user connects, reviews, prepares and trades WITHOUT a terminal,
   PowerShell, stage names, gate names, journal ids or symbol aliases.
   Every action drives the same lifecycle the CLI uses; nothing is bypassed.
   Engineering internals live under "Technical details" at the bottom. */
/* Render the refusal the SERVER built. The plain sentence, the condition to
   retry on and the technical detail all come from qts.execution.demo_refusal,
   which sits next to the gate that produced the verdict — so the wording can
   never drift from the predicate, and every one of the gate's checks is
   covered.

   This used to be a hand-written dictionary here in the browser: eleven
   entries for twenty-eight predicates (four of them keys the gate never
   emits), matched by splitting reasons[0] on ":". Everything unmatched fell
   back to a generic "a safety check refused the order" line — the system knew
   the exact predicate and told the operator nothing actionable. */
function refusalOf(body) {
  const r = body && typeof body === "object" ? body.refusal : null;
  if (r && r.primary) return r;
  // No structured refusal (an older server, or a transport-level error):
  // say exactly that rather than inventing a cause.
  const reasons = Array.isArray(body?.reasons) ? body.reasons
    : (body?.detail ? [String(body.detail)] : []);
  return {
    headline: "Order blocked",
    summary: "Trading is not ready yet.",
    explanation_available: false,
    primary: {
      id: "unidentified",
      plain: "The order was refused by a safety check, but QTS could not identify which one. It has NOT been sent.",
      retry_when: "The exact reason is unavailable — see the technical details below.",
      technical: reasons.join("; ") || "no refusal detail was recorded",
    },
    blockers: [],
  };
}

/* The refusal block for the normal (non-technical) Trading view. */
function refusalBody(r) {
  const p = r.primary || {};
  const rows = [h("div", { class: "stack" },
    h("div", null, h("b", null, "Reason: "), String(p.plain || "")),
    p.retry_when ? h("div", null, h("b", null, "Retry when: "), String(p.retry_when)) : null,
  )];
  const others = (r.blockers || []).slice(1).filter((b) => b && b.plain);
  if (others.length) {
    rows.push(h("div", { class: "hint" },
      `Also blocking: ${others.map((b) => b.plain).join(" ")}`));
  }
  if (r.explanation_available === false) {
    rows.push(h("div", { class: "hint" },
      "QTS could not identify the exact failed check — the order was still refused."));
  }
  return h("div", { class: "stack" }, ...rows);
}

export async function renderDemo(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Trading", group: "Demo",
    title: "Demo account",
    answer: h("b", null, "Connect your practice account, let QTS run the safety checks, and place demo orders. Live trading stays locked. No real money is at risk."),
    actions: [h("button", { class: "btn", onclick: () => load(true) }, icon("refresh", 14), "Refresh")],
    body: null,
  }));

  const host = h("div", { class: "section" });
  root.appendChild(host);
  let guide = null;
  let acting = false;

  // ---- plain-language helpers ------------------------------------------------
  const toneFor = (g) => (g.status === "ready" ? "ok" : g.status === "stopped" ? "err" : "warn");
  const headlineIcon = (g) => (g.status === "ready" ? "check" : g.status === "stopped" ? "stop" : "alert");

  function connectionCard(g) {
    const c = g.connection || {};
    const connected = Boolean(c.connected);
    const demo = c.account_type === "Demo";
    return card({
      title: "Connection", icon: "activity",
      sub: "Is the practice account connected?",
      actions: [h("button", { class: "btn sm", disabled: acting, onclick: () => load(true) }, icon("refresh", 13), "Check connection")],
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          stat({ label: "Status", value: connected ? "Connected" : "Not connected", tone: connected ? "ok" : "warn", icon: connected ? "check" : "alert", hint: connected ? "MetaTrader 5 answered." : "Open MetaTrader 5 and sign in to your demo account, then press Check connection." }),
          stat({ label: "Account", value: connected ? (c.account_type || "Unknown") : "—", tone: demo ? "ok" : "neutral", icon: "shield", hint: demo ? "This is a practice account. No real money." : "QTS only trades demo accounts." }),
          stat({ label: "Broker", value: connected ? (c.broker || c.server || "—") : "—", icon: "bank" }),
          stat({ label: "Instrument", value: g.instrument || "Gold", icon: "activity", hint: "The product trades gold." }),
        ),
        connected
          ? h("p", { class: "small text-dim" }, `Signed in as ${c.login ?? "unknown account"} · ${c.server ?? "unknown server"}.`)
          : banner("warn", "MetaTrader 5 is not connected", "Open MetaTrader 5 on this computer and sign in to your demo account. Then press “Check connection”. No command line is needed.", "alert"),
      ),
    });
  }

  function stepRow(s, i) {
    const done = s.state === "done";
    return h("div", { class: "guide-step", style: { display: "flex", gap: "12px", alignItems: "flex-start", padding: "10px 0", borderBottom: "1px solid var(--border)" } },
      h("div", { class: "badge", style: { minWidth: "26px", justifyContent: "center" } }, done ? "✓" : String(i + 1)),
      h("div", { style: { flex: 1 } },
        h("div", { class: "small", style: { fontWeight: 600 } }, s.title),
        h("div", { class: "small text-dim" }, s.detail || ""),
      ),
    );
  }

  async function runNextAction(g) {
    const next = g.next;
    if (!next || next.action === "none") return;
    if (acting) return;
    acting = true;
    try {
      if (next.action === "check_connection") { await load(true); return; }
      if (next.action === "open_setup") { navigate("#/advanced/system-setup"); return; }
      if (next.action === "review_authorization") { navigate("#/advanced/governance"); return; }

      if (next.action === "record_identity") {
        const out = await api.post("/api/demo/guide/record-identity", {});
        return afterAction(out);
      }
      if (next.action === "confirm_identity") {
        const ok = await confirmModal({
          title: "Confirm this is your demo account",
          body: h("div", { class: "stack" },
            h("p", null, "QTS recorded the connected account. Please review it before any order can be prepared."),
            kv([
              ["Account", String(guide?.connection?.login ?? "—")],
              ["Broker", String(guide?.connection?.broker ?? guide?.connection?.server ?? "—")],
              ["Server", String(guide?.connection?.server ?? "—")],
              ["Type", String(guide?.connection?.account_type ?? "—")],
            ])),
          acks: ["This is my demo account, and I reviewed the account number and broker above."],
          confirmLabel: "Confirm identity",
        });
        if (!ok) return;
        const out = await api.post("/api/demo/guide/confirm-identity", { confirmed: true });
        return afterAction(out);
      }
      if (next.action === "prepare") {
        const ok = await confirmModal({
          title: "Prepare demo trading",
          body: h("div", { class: "stack" },
            h("p", null, "QTS will run the full safety checks against the terminal, confirm your risk acknowledgement, and prepare the demo account. This never touches real money and never opens live trading."),
            banner("info", "No real money is at risk", "This is a practice account only. Live trading stays locked.", "lock")),
          acks: [
            "I understand this prepares DEMO trading only — live trading stays locked.",
            "I acknowledge the demo risk limits and that any order can still be refused.",
          ],
          confirmLabel: "Prepare demo trading",
        });
        if (!ok) return;
        const out = await api.post("/api/demo/guide/prepare", { confirmed: true, risk_ack: true });
        return afterAction(out);
      }
      if (next.action === "refresh") {
        const ok = await confirmModal({
          title: "Refresh connection",
          body: h("p", null, "The proof that the terminal is healthy has expired. QTS will re-check the connection. This is routine."),
          acks: ["Re-check the connection so demo trading stays prepared."],
          confirmLabel: "Refresh connection",
        });
        if (!ok) return;
        const out = await api.post("/api/demo/guide/refresh", { confirmed: true, risk_ack: true });
        return afterAction(out);
      }
      if (next.action === "resume") {
        let reasonText = "";
        const reasonBox = h("textarea", {
          class: "input", rows: 2, placeholder: "Why are you clearing the stop? This is recorded in the audit log.",
          oninput: (e) => { reasonText = e.target.value; },
        });
        const ok = await confirmModal({
          danger: true,
          title: "Review and resume after the stop",
          body: h("div", { class: "stack" },
            // Say what actually stopped trading. "Resume" now also clears a
            // reconciliation stop, so hard-coding "the kill switch" would
            // describe the wrong fault half the time — the guide already
            // carries the honest reason.
            h("p", null, g.reason || "Trading is stopped."),
            h("p", null, "QTS re-checks the stop against the broker before clearing it. If the problem is still there, nothing is cleared. Clearing is recorded with your reason, and trading does NOT resume by itself — the demo account is prepared again from the start."),
            reasonBox),
          acks: ["I reviewed why trading was stopped, and I want to clear the stop."],
          confirmLabel: "Clear the stop",
        });
        if (!ok) return;
        const reason = reasonText.trim();
        if (!reason) { toast("err", "A reason is required", "Clearing the stop is recorded in the audit log — say why."); return; }
        const out = await api.post("/api/demo/guide/resume", { confirmed: true, reason });
        return afterAction(out);
      }
    } catch (e) {
      const b = e.body || {};
      const res = b.result || {};
      toast("err", res.headline || "Action failed", res.detail || explain(e));
      await load();
    } finally {
      acting = false;
    }
  }

  function afterAction(out) {
    const res = out?.result || {};
    guide = out?.guide ?? guide;
    if (res.ok) toast("ok", res.headline || "Done", res.detail || "");
    else toast("err", res.headline || "Not completed", res.detail || "See the reason above.");
    render();
  }

  function nextActionButton(g) {
    const next = g.next;
    if (!next || next.action === "none") {
      return h("p", { class: "small text-dim" }, next?.description || "Nothing to do right now.");
    }
    const btn = h("button", { class: "btn primary", disabled: acting, onclick: () => runNextAction(g) }, icon("play", 14), next.label || "Continue");
    return h("div", { class: "stack" },
      h("div", { class: "row" }, btn),
      next.description ? h("p", { class: "small text-dim" }, next.description) : null,
    );
  }

  function orderTicket(g) {
    if (!g.can_trade) {
      return card({
        title: "Place a demo order", icon: "zap",
        sub: "Available once the steps above are complete",
        body: emptyState({ icon: "lock", title: "Not ready to trade yet", desc: g.reason || "Finish the steps above. QTS will tell you when an order is possible. No real money is at risk either way." }),
      });
    }
    let side = "BUY";
    const size = h("input", { class: "input", type: "number", step: "0.01", min: "0.01", value: g.order_defaults?.size ?? "0.01", style: { maxWidth: "140px" } });
    const stop = h("input", { class: "input", type: "number", step: "0.01", placeholder: "e.g. 3280.00", style: { maxWidth: "160px" } });
    const result = h("div");
    const sideBtn = (label) => h("button", {
      class: `btn sm ${side === label ? "primary" : ""}`,
      onclick: (e) => { side = label; [...e.currentTarget.parentNode.children].forEach((b) => b.className = "btn sm"); e.currentTarget.className = "btn sm primary"; },
    }, label === "BUY" ? "Buy" : "Sell");

    async function submit(dry) {
      const payload = { side, lots: size.value || undefined, stop_loss: stop.value || undefined, confirmed: true, risk_ack: true };
      if (dry) payload.dry_run = true;
      if (!dry) {
        // One simple review before anything is sent — exactly what will happen.
        const ok = await confirmModal({
          title: "Confirm demo trade",
          body: h("div", { class: "stack" },
            kv([
              ["Direction", side === "BUY" ? "Buy" : "Sell"],
              ["Instrument", g.instrument || "Gold (XAUUSD)"],
              ["Amount", `${size.value || "—"} lot`],
              ["Stop loss", stop.value || "—"],
              ["Account", "Demo — no real money"],
            ]),
            banner("info", "This trade is placed on a Demo account.", "No real money is at risk. Live trading stays locked.", "lock")),
          acks: ["I want to place this demo trade."],
          confirmLabel: "Place demo trade",
        });
        if (!ok) return;
      }
      try {
        const out = await api.post("/api/demo/order", payload);
        if (dry) {
          // A 200 preview can still be a refusal: the dry run reports the
          // verdict rather than raising. Never call that "passed".
          if (out && out.allowed === false) {
            const r = refusalOf(out);
            result.replaceChildren(
              banner("warn", "Preview: this order would be blocked", r.summary || "Trading is not ready yet.", "alert"),
              refusalBody(r),
              h("details", null, h("summary", null, "Technical details"),
                h("div", { class: "hint" }, `Failed check: ${r.primary?.id ?? "unidentified"} — ${r.primary?.technical ?? ""}`),
                tech(out, "Preview detail")),
            );
          } else {
            result.replaceChildren(banner("ok", "Preview passed the safety checks", "No order was sent. Press “Place demo trade” to submit on the demo account.", "check"), tech(out, "Preview detail"));
          }
        } else {
          result.replaceChildren(banner("ok", "Demo trade placed", `Broker reference ${out.broker_order_id ?? "recorded"}. This is a practice account — no real money.`, "check"), tech(out, "Order detail"));
          toast("ok", "Demo trade placed", "No real money is at risk.");
        }
      } catch (e) {
        const b = e.body || {};
        const r = refusalOf(b);
        result.replaceChildren(
          banner("warn", r.headline || "Order blocked", r.summary || "Trading is not ready yet.", "alert"),
          refusalBody(r),
          h("details", null, h("summary", null, "Technical details"),
            h("div", { class: "hint" }, `Failed check: ${r.primary?.id ?? "unidentified"} — ${r.primary?.technical ?? ""}`),
            tech(b, "Raw refusal")),
        );
      }
    }

    return card({
      title: "New demo trade", icon: "zap",
      sub: `${g.instrument} · practice account · no real money at risk`,
      actions: [h("span", { class: "prov demo" }, "DEMO ONLY")],
      body: h("div", { class: "stack" },
        banner("info", "No real money is at risk", "This order goes to your demo (practice) account only. Live trading stays locked.", "lock"),
        h("div", { class: "row", style: { flexWrap: "wrap", gap: "10px", alignItems: "flex-end" } },
          h("div", { class: "field" }, h("label", { class: "small" }, "Direction"), h("div", { class: "row" }, sideBtn("BUY"), sideBtn("SELL"))),
          h("div", { class: "field" }, h("label", { class: "small" }, "Amount (lots)"), size),
          h("div", { class: "field" }, h("label", { class: "small" }, `Stop loss ${g.order_defaults?.stop_required === false ? "(optional)" : "(required)"}`), stop, h("div", { class: "hint" }, g.order_defaults?.stop_required === false ? "A protective stop is optional for this plan." : "The demo plan requires a protective stop on every order. Set the price where this trade must close if it moves against you.")),
        ),
        h("div", { class: "row" },
          h("button", { class: "btn", disabled: acting, onclick: () => submit(true) }, icon("eye", 14), "Preview (no order)"),
          h("button", { class: "btn primary", disabled: acting, onclick: () => submit(false) }, icon("zap", 14), "Place demo trade"),
        ),
        result,
      ),
    });
  }

  function observationControls() {
    const status = h("span", { class: "small text-dim" }, "Checking…");
    const startBtn = h("button", { class: "btn sm", onclick: async () => {
      try { const r = await api.post("/api/observe/start"); toast("ok", "Observation started", "Recording quotes only — zero orders."); status.textContent = String(r?.status?.state ?? "OBSERVING"); }
      catch (e) { toast("err", "Could not start observation", explain(e)); }
    } }, icon("play", 13), "Start watching");
    const stopBtn = h("button", { class: "btn sm", onclick: async () => {
      try { await api.post("/api/observe/stop"); toast("warn", "Observation stopped"); status.textContent = "STOPPED"; }
      catch (e) { toast("err", "Could not stop observation", explain(e)); }
    } }, icon("stop", 13), "Stop");
    api.get("/api/observe/status").then((s) => { status.textContent = String(s?.state ?? s?.status?.state ?? "IDLE"); }).catch(() => { status.textContent = "UNAVAILABLE"; });
    return h("div", { class: "row", style: { alignItems: "center", gap: "10px" } }, startBtn, stopBtn, status);
  }

  async function advancedSection(g) {
    const box = h("div", { class: "stack", style: { paddingTop: "10px" } },
      h("p", { class: "small text-dim" }, "Engineering detail and secondary controls. None of this changes what the guided workflow enforces. Stage names, readiness checks, the identity pin and raw reports are shown verbatim."),
      card({ title: "Watch the market", sub: "Records quotes only — never an order", icon: "eye", body: h("div", { class: "stack" },
        observationControls(),
        h("p", { class: "small text-dim" }, "Watching does not trade and does not grant permission. Context syncs; permission does not."),
      ) }),
    );
    const [readiness, config, state, safety, obs] = await Promise.all([
      api.get("/api/demo/readiness").catch(() => null),
      api.get("/api/demo/config").catch(() => null),
      api.get("/api/demo/state").catch(() => null),
      api.get("/api/demo/safety").catch(() => null),
      api.get("/api/demo/observations?limit=20").catch(() => []),
    ]);

    const cfg = config ?? {};
    const demoEnabled = cfg.demo_execution_disabled === false;

    // Execution cockpit facts — derived from the resolved backend state, never
    // hard-coded into the guided workflow above.
    box.appendChild(card({
      title: "Trading status",
      sub: "Demo only. Real money stays locked. A connection is not permission to trade.",
      icon: "layers",
      body: h("div", { class: "stat-grid" },
        stat({ label: "Account", value: g.connection?.account_type ?? "Unknown", tone: g.connection?.account_type === "Demo" ? "info" : "neutral", hint: g.connection?.login ? `Login ${g.connection.login} at ${g.connection.server ?? "broker"}` : "Account not confirmed yet.", icon: "shield" }),
        stat({ label: "Gold", value: "XAUUSD", hint: cfg.symbol_mapping?.venue_symbol ? `Broker symbol ${cfg.symbol_mapping.venue_symbol}` : "Broker symbol not confirmed yet.", icon: "activity" }),
        stat({ label: "Trading", value: demoEnabled ? "Demo only" : "Not allowed", tone: demoEnabled ? "ok" : "neutral", hint: demoEnabled ? "Still needs a fresh check before any order." : "Protected by the safety policy.", icon: "lock" }),
        stat({ label: "Safety checks", value: "Safety checks are on", tone: "ok", hint: "Every order is refused unless the full pre-trade gate passes.", icon: "shield" }),
        stat({ label: "Your money", value: "Not at risk", tone: "ok", hint: "Live trading is locked. Real money cannot be used.", icon: "lock" }),
      ),
    }));

    box.appendChild(banner(
      demoEnabled ? "info" : "warn",
      demoEnabled ? "Demo may be considered. Live trading is locked." : "Trading is off. Live trading is locked.",
      `${demoEnabled
        ? `DEMO EXECUTION: ${String(cfg.demo_execution?.state ?? "ENABLED_AUTHORIZED")} — LIVE LOCKED. This backend process resolved a DEMO-capable mode and a recorded owner authorization. Order permission is still per-order: staged arming, a confirmed identity pin, fresh readiness, a registered policy and the full pre-trade gate.`
        : "DEMO EXECUTION: DISABLED BY POLICY — LIVE LOCKED. No readiness result or UI action creates demo order permission. Watching the market does not turn trading on."} Mode ${String(cfg.mode ?? "UNAVAILABLE").toUpperCase()} — decided by: ${String(cfg.mode_source ?? "unresolved")}.`,
      "lock",
    ));

    box.appendChild(card({
      title: "What this process decided", icon: "shield",
      sub: "The mode, where state is stored, and the gold symbol. This page does not grant permission.",
      body: h("div", { class: "stack" },
        kv([
          ["Effective mode", String(cfg.mode ?? "UNAVAILABLE").toUpperCase()],
          ["Decided by", String(cfg.mode_source ?? "unresolved")],
          ["Persisted declaration", String(cfg.mode_declaration ?? "none")],
          ["State root", String(cfg.state?.state_root ?? "UNAVAILABLE")],
          ["Authority state", `${String(state?.state ?? "UNAVAILABLE")} · permitted: ${String(state?.execution_permitted ?? false)}`],
          ["Orders possible from this page", "no — nothing here grants permission"],
        ]),
        h("details", null, h("summary", null, "Raw runtime state / technical evidence"), tech({ config: cfg, state }, "Raw /api/demo/config + /api/demo/state")),
      ),
    }));

    const checks = readiness?.checks ?? {};
    const allPass = Boolean(readiness?.passed);
    const failing = Object.entries(checks).filter(([, v]) => v === false).map(([k]) => k);
    box.appendChild(card({
      title: "Safety checks", icon: "shield",
      sub: readiness
        ? (allPass ? `passed ${fmtAge(readiness.timestamp)}` : `${failing.length} failing — ${failing.slice(0, 3).join(", ")}${failing.length > 3 ? ` +${failing.length - 3} more` : ""}`)
        : "readiness report unavailable",
      body: h("div", { class: "stack" },
        allPass
          ? banner("ok", "Checks passed for watching only", "A pass lets QTS record quotes. It does not allow an order. Live trading stays locked.", "check")
          : banner("warn", "Checks did not pass", (readiness?.blocked_reasons ?? []).join(" · ") || "The failed checks are listed below. Watching stays unable to send an order.", "alert"),
        checkGrid(checks, readiness?.details ?? {}),
        h("details", null, h("summary", null, "Raw readiness report / technical evidence"), tech(readiness ?? {}, "Raw /api/demo/readiness")),
      ),
    }));

    const lim = safety?.demo_limits ?? {};
    box.appendChild(card({ title: "Demo safety limits — non-authorizing", sub: `config ${lim.config_hash ?? "—"} · descriptive only`, icon: "shield", body: h("div", { class: "stat-grid" },
      stat({ label: "Max volume / order", value: `${fmtNum(lim.max_volume_per_order)} lots`, icon: "layers" }),
      stat({ label: "Max exposure", value: `${fmtNum(lim.max_simultaneous_exposure)} lots`, icon: "layers" }),
      stat({ label: "Order rate", value: `${fmtInt(lim.max_orders_per_minute)}/min`, icon: "clock" }),
      stat({ label: "Daily loss cap", value: `$${fmtNum(lim.max_daily_loss_usd, 0)}`, tone: "warn", icon: "alert" }),
      stat({ label: "Max spread", value: `${fmtNum(lim.max_spread_bps, 0)} bps`, icon: "activity" }),
    ) }));
    box.appendChild(Array.isArray(obs) && obs.length && !obs[0]?.error
      ? card({ title: "Recent demo observations", sub: "recorded quotes with provenance", icon: "database", body: table({
          columns: [
            { key: "timestamp", label: "Time (UTC)", render: (o) => h("span", { class: "mono small" }, fmtUtc(o.timestamp)) },
            { key: "bid", label: "Bid", num: true, render: (o) => fmtNum(o.bid) },
            { key: "ask", label: "Ask", num: true, render: (o) => fmtNum(o.ask) },
            { key: "prov", label: "Provenance", render: (o) => provStrip(o.provenance ?? o.data_class ?? "") },
          ],
          rows: obs, dense: true,
        }) })
      : card({ title: "Recent demo observations", icon: "database", body: emptyState({ icon: "database", title: "No demo observations yet", desc: "Start watching above. Every tick persists with full provenance." }) }));
    box.appendChild(h("details", null, h("summary", null, "Raw guided-workflow state / technical evidence"), tech(g.technical || {}, "Raw guided-workflow state")));
    return h("details", { class: "mt-3" },
      h("summary", null, "Advanced — technical details, limits, observations"),
      box,
    );
  }


  // ---- Open positions (§9): broker-authoritative, never faked ----------------
  async function fetchPositions() {
    try { return await api.get("/api/demo/positions"); } catch { return null; }
  }
  function positionRow(p, onClose) {
    const profit = Number(p.profit);
    const profitOk = Number.isFinite(profit);
    const current = Number(p.price_current);
    const opened = p.time ? new Date(Number(p.time) * 1000).toISOString() : null;
    return h("tr", null,
      h("td", null, h("b", null, p.canonical_symbol || p.symbol || "Gold"), h("div", { class: "small text-dim" }, p.broker_symbol ? `broker: ${p.broker_symbol}` : "")),
      h("td", null, h("span", { class: `badge ${p.side === "BUY" ? "ok" : "err"}` }, p.side === "BUY" ? "Buy" : "Sell")),
      h("td", null, p.volume ? `${p.volume}` : "—"),
      h("td", { class: "mono" }, p.price_open && Number(p.price_open) ? fmtNum(Number(p.price_open)) : "—"),
      h("td", { class: "mono" }, Number.isFinite(current) && current > 0 ? fmtNum(current) : "—"),
      h("td", { class: "mono" }, profitOk ? `${profit >= 0 ? "+" : ""}${fmtNum(profit)}` : "—"),
      h("td", { class: "mono" }, p.sl && Number(p.sl) > 0 ? fmtNum(Number(p.sl)) : "—"),
      h("td", null, opened ? fmtUtc(opened) : "—"),
      h("td", null, h("button", { class: "btn sm", disabled: acting, onclick: () => onClose(p) }, "Close")),
    );
  }
  async function closePosition(p) {
    const ok = await confirmModal({
      title: "Close this demo position?",
      body: h("div", { class: "stack" },
        banner("info", "Demo account only", "No real money is at risk. Closing sends the close to the broker and then checks the result.", "shield"),
        kv([
          ["Instrument", p.canonical_symbol || p.symbol || "Gold"],
          ["Direction", p.side === "BUY" ? "Buy" : "Sell"],
          ["Size", p.volume || "—"],
          ["Ticket", String(p.ticket ?? "—")],
        ])),
      acks: ["I understand this closes the position on the Demo account."],
      confirmLabel: "Close position",
    });
    if (!ok) return;
    acting = true;
    try {
      const out = await api.post("/api/demo/close", { ticket: p.ticket, confirmed: true, risk_ack: true, reason: "operator close from the Trading page" });
      toast(out?.success ? "ok" : "warn",
        out?.success ? "Position closed" : "Close reported — check the result",
        out?.success ? `Realized P/L ${out.realized_pnl ?? "—"} · reconciled with the broker and recorded in the journal.` : (out?.detail || "The broker result is recorded in the journal."));
    } catch (e) {
      toast("err", "Position was not closed", e.message || "The close request failed. The position stays open until the broker confirms a close.");
    } finally {
      acting = false;
      refreshPositions(host.querySelector("[data-positions]"));
    }
  }
  async function refreshPositions(into) {
    if (!into) return;
    const g = guide;
    if (!g?.connection?.connected) {
      into.replaceChildren(emptyState({ icon: "layers", title: "Positions unknown — not connected", desc: "QTS cannot read positions until the Demo account is connected. It never claims a flat book it has not verified." }));
      return;
    }
    into.replaceChildren(h("div", { class: "skeleton skl-line", style: { width: "50%" } }));
    const data = await fetchPositions();
    if (!data) {
      into.replaceChildren(banner("warn", "Positions unavailable", "The Demo account is connected but QTS could not read positions from the terminal. Nothing was changed. Retry, or check the terminal.", "alert"));
      return;
    }
    const list = data.positions || [];
    if (!list.length) {
      into.replaceChildren(emptyState({ icon: "layers", title: "No open positions", desc: "The broker reports no open demo positions right now." }));
      return;
    }
    into.replaceChildren(h("div", { class: "table-wrap" },
      h("table", { class: "table" },
        h("thead", null, h("tr", null, ...["Instrument", "Direction", "Size", "Entry", "Current", "Profit", "Stop loss", "Opened", ""].map((t) => h("th", null, t)))),
        h("tbody", null, ...list.map((pos) => positionRow(pos, closePosition))),
      ),
      h("p", { class: "small text-dim" }, "Profit is the broker\u2019s unrealized figure. Closing reconciles with the broker and records the outcome \u2014 QTS never fakes a closed position.")));
  }
  function positionsSection() {
    const into = h("div", { dataset: { positions: "1" }, class: "stack" });
    refreshPositions(into);
    return card({
      title: "Open positions", icon: "layers",
      sub: "Broker-authoritative \u2014 read from the Demo account, closed through the broker",
      actions: [h("button", { class: "btn sm", onclick: () => refreshPositions(into) }, icon("refresh", 13), "Refresh positions")],
      body: into,
    });
  }

  function render() {
    if (!guide) return;
    clear(host);
    const g = guide;

    // Unmistakable status headline.
    host.appendChild(h("section", { class: "operator-summary" },
      h("div", null,
        h("div", { class: "eyebrow" }, "STATUS"),
        h("h2", null, g.headline || "Loading…"),
        g.reason ? h("p", { class: "text-dim small" }, g.reason) : null,
      ),
      h("div", { class: "next-action" },
        h("div", { class: "eyebrow" }, g.can_trade ? "TRADE" : "NEXT"),
        g.can_trade ? h("span", { class: "badge ok" }, "Ready — place a demo order below") : nextActionButton(g),
      )));

    host.appendChild(banner(toneFor(g), g.status === "ready" ? "Ready for demo trading" : g.status === "stopped" ? "Trading is stopped" : "Not ready yet",
      `Live trading is locked. Real-capital exposure is $0. ${g.reason ? g.reason : (g.status === "ready" ? "Every order still passes the full pre-trade safety gate." : "Follow the next step — QTS runs the checks for you.")}`,
      headlineIcon(g)));

    host.appendChild(h("div", { class: "grid-2" },
      connectionCard(g),
      card({
        title: "Setup steps", icon: "shield",
        sub: "QTS runs the safety checks for you",
        body: h("div", { class: "stack" },
          ...(g.steps || []).map(stepRow),
          h("div", { class: "mt-3" }, nextActionButton(g)),
        ),
      }),
    ));

    host.appendChild(orderTicket(g));
    host.appendChild(positionsSection());
    advancedSection(g).then((node) => host.appendChild(node)).catch(() => {
      host.appendChild(h("details", { class: "mt-3" },
        h("summary", null, "Advanced — technical details"),
        tech(g.technical || {}, "Raw guided-workflow state"),
      ));
    });
  }

  async function load(force = false) {
    if (acting && !force) return;
    try {
      const g = await api.get("/api/demo/guide");
      guide = g;
      render();
    } catch (e) {
      clear(host);
      host.appendChild(errorBox({ what: "the guided demo state could not be loaded", next: "Retry. If MetaTrader 5 is not installed, connection steps report that honestly.", raw: e.message }));
      host.appendChild(h("div", { class: "mt-3" }, h("button", { class: "btn primary", onclick: () => load(true) }, icon("refresh", 14), "Retry")));
    }
  }

  await load();
}

/* Execution Center */
const ORDER_STAGES = ["INTENT", "RISK", "PREFLIGHT", "SUBMIT", "BROKER ACK", "FILL", "RECONCILE"];
export async function renderExecution(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Trading", group: "Execution",
    title: "Order history",
    answer: h("b", null, "Orders the broker accepted, rejected, or left unfinished. This page does not place an order. Live trading stays locked."),
    body: null,
  }));
  const host = h("div", { class: "section" }); root.appendChild(host);
  let orders = [];
  try { orders = await api.get("/api/execution/orders?limit=50"); }
  catch (e) { host.appendChild(errorBox({ what: "orders could not be loaded", next: "Retry.", raw: e.message })); return; }

  let demoPositions = [];
  try {
    const posRes = await api.get("/api/demo/positions");
    demoPositions = Array.isArray(posRes?.positions) ? posRes.positions : [];
  } catch (_) { /* fail-closed / optional when broker offline */ }

  async function handleClosePosition(pos) {
    const ok = await confirmModal({
      title: `Close Position #${pos.ticket} — ${pos.side} ${pos.volume} ${pos.symbol || pos.broker_symbol}`,
      danger: true,
      body: h("div", { class: "stack" },
        h("p", null, `Close ticket #${pos.ticket} at current market price. This executes an offsetting MT5 order on the DEMO venue, reconciles local vs broker positions, and logs the outcome in the order journal.`),
        kv([
          ["Ticket", String(pos.ticket)],
          ["Symbol", `${pos.canonical_symbol || "XAUUSD"} (broker: ${pos.broker_symbol || pos.symbol || "XAUUSD@"})`],
          ["Side / Volume", `${pos.side} · ${pos.volume} lots`],
          ["Open Price", String(pos.price_open ?? "—")],
          ["Current Price", String(pos.price_current ?? "—")],
          ["Current P&L", String(pos.profit ?? "—")],
        ]),
      ),
      acks: [
        "I confirm submitting a closing order on the configured MT5 DEMO account.",
        "I acknowledge this executes an offsetting market order and reconciles venue state.",
      ],
      confirmLabel: `Close position #${pos.ticket}`,
    });
    if (!ok) return;
    try {
      const res = await api.post("/api/demo/close", {
        ticket: pos.ticket,
        confirmed: true,
        risk_ack: true,
        reason: "operator closed position via Execution Center UI",
      });
      const realized = res.realized_pnl ?? res.profit;
      const drift = res.reconciliation?.drift;
      toast("ok", `Position #${pos.ticket} closed`, `Realized P&L: ${realized === undefined || realized === null || realized === "" ? "UNAVAILABLE" : realized}. Reconciliation: ${drift || "UNAVAILABLE"}`);
      renderExecution(root);
    } catch (e) {
      toast("err", "Failed to close position", explain(e));
    }
  }

  if (demoPositions.length > 0) {
    host.appendChild(card({
      title: "Open Broker Positions — Authoritative MT5 Venue Truth",
      sub: `${demoPositions.length} active position(s) on configured DEMO account · Explicit close lifecycle`,
      icon: "layers",
      body: table({
        columns: [
          { key: "ticket", label: "Ticket", render: (p) => h("span", { class: "mono small" }, String(p.ticket)) },
          { key: "symbol", label: "Symbol", render: (p) => h("span", null, `${p.canonical_symbol || p.symbol} `, h("span", { class: "text-dim small" }, `(${p.broker_symbol || p.symbol})`)) },
          { key: "side", label: "Side", render: (p) => badge(p.side, p.side === "BUY" ? "ok" : "err") },
          { key: "volume", label: "Lots", num: true, render: (p) => fmtNum(p.volume) },
          { key: "price_open", label: "Open Price", num: true, render: (p) => fmtNum(p.price_open) },
          { key: "price_current", label: "Current Price", num: true, render: (p) => fmtNum(p.price_current) },
          { key: "profit", label: "P&L", num: true, render: (p) => fmtNum(p.profit) },
          {
            key: "action", label: "Action",
            render: (p) => h("button", { class: "btn danger sm", onclick: () => handleClosePosition(p) }, "Close"),
          },
        ],
        rows: demoPositions,
        dense: true,
      }),
    }));
  }

  try {
    const account = await api.get("/api/dashboard");
    host.appendChild(card({ title: "Account snapshot", sub: `Canonical dashboard metrics; UNAVAILABLE is not zero. Context ${getContext().symbol}. Refresh to retrieve new snapshot.`, icon: "bank",
      body: h("div", { class: "stack" },
        h("div", { class: "stat-grid" },
          metricStat({ label: "Equity", metric: account.equity }),
          metricStat({ label: "Balance", metric: account.balance }),
          metricStat({ label: "Exposure", metric: account.exposure }),
          metricStat({ label: "Spread", metric: account.spread })),
        Array.isArray(account.open_positions) && account.open_positions.length
          ? table({ columns: [{key: "symbol", label: "Symbol"}, {key: "side", label: "Side"}, {key: "volume", label: "Volume", num: true}, {key: "profit", label: "P&L", num: true}], rows: account.open_positions, dense: true })
          : h("p", {class: "text-dim small"}, account.balance?.status === "MEASURED" ? "No positions reported in this snapshot." : "Position state UNAVAILABLE — account measurements are not established."),
        h("details", null, h("summary", null, "Raw account snapshot / technical evidence"), tech(account, "Raw account snapshot")))}));
  } catch (e) { host.appendChild(errorBox({ what: "account snapshot unavailable", next: "Retry this page; order-event evidence below is independent.", raw: e.message })); }

  host.appendChild(card({ title: "Lifecycle reference", sub: "each stage is audited with its own timestamp", icon: "branch", body:
    pipeline(ORDER_STAGES, ORDER_STAGES.length, -1),
  }));

  host.appendChild(card({
    title: "Orders — dense, sortable, keyboard navigable, drawer for detail", sub: `${orders.length} recent event(s) — context ${getContext().symbol}`, icon: "zap",
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
            kv([["Time (UTC)", fmtUtc(o.time)], ["Type", String(o.type ?? "").toUpperCase()], ["Lifecycle", String(o.lifecycle ?? "—").toUpperCase()], ["Context", `${getContext().symbol} — presentation only`]]),
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
          desc: "No order has been recorded. An empty list is not zero profit, and this page does not place an order. Live trading stays locked.",
          actions: [h("button", { class: "btn", onclick: () => navigate("#/trading") }, icon("shield", 14), "Open the demo account")],
        }),
  }));
}

/* Comparison */
export async function renderComparison(root) {
  skeletonInto(root, "stats");
  root.classList.add("operator-workspace");
  root.appendChild(page({
    crumb: "Trading", group: "Comparison",
    title: "Comparison",
    answer: h("b", null, "Practice results beside recorded demo quotes. A missing fill stays missing. It is not shown as zero. Live trading stays locked."),
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
    host.appendChild(card({ title: `Measured / unavailable comparison — context ${getContext().symbol}`, icon: "scale", body:
      h("div", { class: "stat-grid" },
        metrics.map(([k, m]) => metricStat({ label: humanKey(k), metric: m })),
      ),
    }));
  } else {
    host.appendChild(card({ title: "Measured comparison", icon: "scale", body:
      emptyState({
        icon: "scale", title: "No DEMO_FORWARD observations to compare yet",
        desc: "Signal alignment can be measured only when paper/shadow events share a decision event with recorded observations. Fill, slippage, latency, and realized execution metrics remain UNAVAILABLE until DEMO orders are recorded — never fabricated as zero.",
        actions: [h("button", { class: "btn", onclick: () => navigate("#/trading") }, icon("shield", 14), "Demo control")],
      }),
    }));
  }
  host.appendChild(h("details", null, h("summary", null, "Raw comparison evidence / technical — summary → detail → raw"), tech(comp, "Raw comparison evidence")));
}
