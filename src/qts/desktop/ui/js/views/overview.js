/* Operator workspace: primary answer → facts → why blocked → evidence → technical.
   No separate polling loop. Stable controls, focus preserved, no fake zero. */

import { api, store, syncOperations, RESOURCES, measurements, measure } from "../api.js";
import { operationalState } from "../operations.js";
import { h, icon, clear } from "../dom.js";
import { page, table, card, stat, banner, kv } from "../components.js";
import { fmtUtc, fmtAge, fmtInt, fmtNum } from "../format.js";
import { statusInfo } from "../status.js";
import { onDispose } from "../router.js";
import { getContext, onContext } from "../context.js";
import { readWorkspace } from "../workspace.js";

const link = (label, href, cls = "btn sm") => h("a", { class: cls, href }, label);
const setText = (node, value) => { const s = String(value); if (node.textContent !== s) node.textContent = s; };

export async function renderOverview(root) {
  root.classList.add("operator-workspace");
  const activity = h("h2", { id: "operator-activity" }, "Loading operating state…");
  const explanation = h("p", { class: "text-dim small" });
  const next = link("Inspect unavailable sources", "#/system/diagnostics", "btn primary");
  const nextWhy = h("p", { class: "text-dim small" });
  const announce = h("div", { class: "sr-only", role: "status", "aria-live": "polite" });
  const refresh = h("button", { class: "btn", onclick: () => syncOperations(true) }, icon("refresh", 14), "Refresh sources");
  root.appendChild(page({ crumb: "Overview", title: "Operator workspace", answer: "Current operation, authority and evidence — one source per fact. Context syncs across windows, never permission.", actions: [refresh] }));
  root.appendChild(h("section", { class: "operator-summary", "aria-labelledby": "operator-activity" },
    h("div", null, h("div", { class: "eyebrow" }, "NOW / OBSERVATION"), activity, explanation),
    h("div", { class: "next-action" }, h("div", { class: "eyebrow" }, "NEXT MEANINGFUL ACTION"), next, nextWhy)));
  root.appendChild(announce);

  const definitions = [
    ["mode", "Environment / mode", "health", "#/system/diagnostics"],
    ["broker", "Broker (MT5)", "health", "#/system/mt5"],
    ["market", "Market data pipeline", "health", "#/market/quality"],
    ["quoteAge", "Collected quote age", "observe", "#/market/observations"],
    ["observation", "Observation collector", "observe", "#/market/observations"],
    ["permission", "DEMO execution", "demoState", "#/trading/demo"],
    ["liveLabel", "LIVE governance", "live", "#/governance/live"],
  ];
  const tbody = h("tbody");
  const cells = {};
  for (const [key, title, resource, href] of definitions) {
    const state = h("span", { class: "badge neutral" }, "UNAVAILABLE");
    const detail = h("span");
    const fresh = h("span", { class: "resource-fresh" });
    cells[key] = { state, detail, fresh, resource };
    tbody.appendChild(h("tr", { dataset: { fact: key } }, h("th", { scope: "row" }, title), h("td", null, state),
      h("td", { class: "fact-detail" }, detail), h("td", { class: "mono small" }, fresh),
      h("td", null, link("Inspect", href))));
  }
  root.appendChild(h("section", { class: "operator-section", "aria-labelledby": "facts-title" },
    h("h2", { id: "facts-title" }, "Operating facts — per-source freshness, not quote freshness — truth visible"),
    h("p", { class: "small text-dim" }, "Freshness below means last successful API receipt, not age of market quote. Stale authority cannot establish current permission. Context syncs separately via BroadcastChannel and never stores permission. Workspace density/width/navigation persist per browser, never permission."),
    h("div", { class: "tbl-wrap", tabindex: "0", "aria-label": "Operating facts, horizontally scrollable" },
      h("table", { class: "tbl facts-table" },
        h("thead", null, h("tr", null, ["Source", "Reported state", "Meaning / constraint", "API freshness", "Evidence"].map((t) => h("th", { scope: "col" }, t)))), tbody))));

  const workspaceFacts = h("div", { class: "stat-grid" });
  function renderWorkspaceFacts() {
    const ws = readWorkspace();
    const ctx = getContext();
    clear(workspaceFacts);
    workspaceFacts.append(
      stat({ label: "Density", value: ws.density, hint: "compact = high density without chaos" }),
      stat({ label: "Width", value: ws.width, hint: "focused 1440px, wide 1600px" }),
      stat({ label: "Context", value: `${ctx.symbol} · ${ctx.timeframe}`, hint: "presentation only, syncs across windows" }),
      stat({ label: "Navigation", value: ws.navigation, hint: "sidebar width — persists per browser" }),
    );
  }
  root.appendChild(card({ title: "Workspace — persistent layout, synchronized context, keyboard-first", sub: "presentation only, never permission — TradingView benchmark for UX, not visual copy", icon: "layers", body: workspaceFacts }));

  // timestamp normalization health — FS-c42bbd fix visible at top level
  const tsCard = h("div");
  root.appendChild(card({ title: "Timestamp normalization — authoritative UTC — FS-c42bbd fix", sub: "broker stamp - measured offset -> UTC, retained on probe failure, not lost — no double-apply", icon: "clock", body: tsCard }));
  async function refreshTimestampCard() {
    try {
      const [manifest, obs] = await Promise.all([
        api.get("/api/research/forward-manifest").catch(()=>null),
        api.get("/api/observe/status").catch(()=>null),
      ]);
      if (!manifest && !obs) {
        tsCard.replaceChildren(h("p", { class: "small text-dim" }, "No observation manifest yet — INSUFFICIENT, not 0. Shows timestamp bases, offsets, last error after observation starts."));
        return;
      }
      const bases = manifest?.timestamp_bases ?? {};
      const offsets = manifest?.server_utc_offsets_s ?? obs?.server_utc_offsets_s ?? [];
      tsCard.replaceChildren(
        h("div", { class: "stat-grid" },
          stat({ label: "State", value: obs?.state ?? manifest?.state ?? "UNAVAILABLE", hint: "FS-c42bbd stopped after 30 future failures, now retained offset prevents storm" }),
          stat({ label: "Ticks recorded", value: fmtInt(manifest?.ticks_recorded ?? obs?.ticks_recorded ?? 0), hint: "2396 good ticks then 30 future in FS-c42bbd" }),
          stat({ label: "Offsets", value: offsets.length ? offsets.map((o)=>`${o/3600}h`).join(", ") : "UNAVAILABLE", hint: "+3h=10800 retained on failure, not lost" }),
          stat({ label: "Bases", value: Object.keys(bases).length ? Object.entries(bases).map(([k,v])=>`${k}·${v}`).join(", ") : "UNAVAILABLE", hint: "broker-normalized(measured-m1-bar) vs assumed-utc-fallback" }),
        ),
        obs?.last_error ? banner("warn", "Last collector error — what blocked, why", String(obs.last_error).slice(0,250), "alert") : null,
        banner("info", "Canonical contract — no double-apply, no loss", "True UTC = time.time(). Broker server-local. Offset = server - UTC via forming-M1-bar probe. Normalization = broker_stamp - offset -> UTC single. On probe failure retain last offset (FS-c42bbd fix). Future-tick protection unchanged: age < -1s fails.", "clock"),
      );
    } catch {
      tsCard.replaceChildren(h("p", { class: "small text-dim" }, "Timestamp normalization health unavailable — refresh diagnostics."));
    }
  }
  refreshTimestampCard();


  const demoReasons = h("ul", { class: "reason-list" });
  const liveReasons = h("ul", { class: "reason-list" });
  root.appendChild(h("div", { class: "operator-grid" },
    h("section", { class: "operator-section" }, h("h2", null, "Why DEMO is not an ordinary switch"),
      h("p", { class: "text-dim small" }, "Readiness and durable execution permission are separate. A passing connection check does not enable execution. What blocked, why, what missing, what next is explicit."),
      demoReasons,
      link("Inspect permission & readiness", "#/trading/demo")),
    h("section", { class: "operator-section live-boundary" }, h("h2", null, "LIVE / independent governance"),
      h("p", { class: "text-dim small" }, "Eligibility is not enablement. Observation and DEMO evidence never automatically authorize live capital. LIVE is unmistakable: locked badge, err background, disabled controls."),
      liveReasons,
      link("Inspect missing LIVE evidence", "#/governance/live"))));

  const observationEvidence = h("dl", { class: "evidence-values" });
  const obsFields = {};
  for (const title of ["Session", "Recorded quotes", "Orders submitted (collector)", "Last broker event (UTC)", "Context"]) {
    obsFields[title] = h("dd", null, "UNAVAILABLE");
    observationEvidence.append(h("dt", null, title), obsFields[title]);
  }
  root.appendChild(h("details", { class: "operator-section evidence-disclosure" },
    h("summary", null, "Observation evidence / scope and limitations — summary → detail"),
    observationEvidence,
    h("p", { class: "text-dim small" }, "Recorded quotes are not complete tick history. Collector order counts do not establish terminal-wide activity. Structural consistency does not establish origin, completeness or research sufficiency. Context syncs across windows, never authority."),
    h("p", { class: "text-dim small" }, "No trend chart is drawn here: these endpoints describe current state, not a comparable historical series."),
    link("Open observations", "#/market/observations"), " ", link("Open research inventory", "#/research/data"), " ", link("Account & execution evidence", "#/trading/execution"), " ", link("Audit trail", "#/evidence/audit")));

  const raw = h("pre");
  const technical = h("details", { class: "operator-section" }, h("summary", null, "Raw overview snapshot / technical evidence — drill to raw"), raw);
  const perfHost = h("div");
  const diagnostics = h("details", { class: "operator-section" }, h("summary", null, "UI performance / last 100 measurements — load, transition, refresh, render, dup, recovery, memory"),
    h("p", { class: "text-dim small" }, "Browser request, update and route durations in ms; not broker latency. Bounded 100, no payloads. Heap if performance.memory exposed. Dup coalesced shows GET dedup win. Recovery shows error→ok transitions."),
    perfHost);
  root.append(technical, diagnostics);

  const reasonList = (el, entries) => {
    const signature = JSON.stringify(entries);
    if (el.dataset.signature === signature) return;
    el.dataset.signature = signature;
    const wasOpen = el.querySelector("details")?.open;
    const rest = entries.slice(4);
    el.replaceChildren(...entries.slice(0, 4).map((x) => h("li", null, x)));
    if (rest.length) el.appendChild(h("li", null, h("details", { open: wasOpen }, h("summary", null, `${rest.length} more recorded reasons`), h("ul", null, rest.map((x) => h("li", null, x))))));
  };

  function renderPerf() {
    const byKind = {};
    for (const m of measurements) {
      if (!byKind[m.kind]) byKind[m.kind] = { count: 0, total: 0, failed: 0, max: 0 };
      byKind[m.kind].count++; byKind[m.kind].total += m.ms || 0; byKind[m.kind].max = Math.max(byKind[m.kind].max, m.ms || 0);
      if (m.outcome === "failed") byKind[m.kind].failed++;
    }
    const rows = Object.entries(byKind).map(([kind, v]) => ({ kind, count: v.count, avg: v.count ? v.total / v.count : 0, max: v.max, failed: v.failed })).sort((a, b) => b.count - a.count);
    const heap = measurements.length ? measurements[measurements.length - 1].heapUsed : null;
    perfHost.replaceChildren(
      h("div", { class: "stat-grid" },
        stat({ label: "Total measured", value: `${measurements.length} / 100` }),
        stat({ label: "Heap (last)", value: heap ? `${heap} KB` : "UNAVAILABLE" }),
        stat({ label: "Dup coalesced", value: `${(byKind["dup-coalesced"]?.count ?? 0) + (byKind["dup-sync"]?.count ?? 0)}` }),
        stat({ label: "Recoveries", value: `${byKind["recovery"]?.count ?? 0}` }),
      ),
      rows.length ? table({ columns: [{ key: "kind", label: "Kind" }, { key: "count", label: "Count", num: true }, { key: "avg", label: "Avg ms", num: true, render: (r) => fmtNum(r.avg, 1) }, { key: "max", label: "Max ms", num: true, render: (r) => fmtNum(r.max, 1) }, { key: "failed", label: "Failed", num: true }], rows, dense: true }) : h("p", { class: "small text-dim" }, "No measurements yet — interact to generate evidence."),
    );
  }

  let lastAnnouncement = "";
  function update() {
    if (!root.isConnected) return;
    const started = performance.now();
    const s = operationalState(store.data);
    setText(activity, s.activity);
    setText(explanation, `${s.mode.mode} — ${s.mode.blurb} — context ${getContext().symbol} · ${getContext().timeframe}`);
    setText(next, s.next.label); next.href = s.next.href;
    setText(nextWhy, s.next.why);
    refresh.disabled = Object.values(store.data.resources).some((m) => m.loading);
    const summary = `${s.activity}; DEMO ${s.permission}; LIVE ${s.liveLabel}`;
    if (summary !== lastAnnouncement) { setText(announce, summary); lastAnnouncement = summary; }
    const meanings = {
      mode: "Environment capability is not execution permission.",
      broker: "Terminal connectivity; not proof of a healthy current quote.",
      market: "Backend pipeline status, not proof of a healthy live quote.",
      quoteAge: s.obs?.last_tick_time ? `Last reported broker event: ${fmtUtc(s.obs.last_tick_time)}. Clock accuracy not established.` : "No current collected-quote timestamp. Pipeline health is not quote freshness.",
      observation: s.observing ? "Collector reports active worker. No order path. Context syncs separately." : s.obs?.last_error || s.obs?.note || "No active collection established.",
      permission: !s.sources.demoState.current ? "Current permission cannot be established — stale source." : `Authority state: ${s.demo?.state ?? "UNAVAILABLE"}; risk and execution gates independent.`,
      liveLabel: "Never auto-enabled. Independent evidence and human governance required. Unmistakable locked styling.",
    };
    for (const [key] of definitions) {
      const { state, detail, fresh, resource } = cells[key];
      const value = key === "mode" ? s.mode.mode : s[key];
      const info = statusInfo(value);
      setText(state, value);
      state.className = `badge ${key === "liveLabel" ? "locked" : info.tone}`;
      setText(detail, meanings[key]);
      const m = store.data.resources[resource];
      setText(fresh, `${s.sources[resource].label}${m?.updatedAt ? ` · ${fmtAge(m.updatedAt)}` : ""}`);
      fresh.title = m?.updatedAt ? `Last successful API receipt: ${fmtUtc(m.updatedAt)}; ${RESOURCES[resource].path}` : RESOURCES[resource].path;
    }
    reasonList(demoReasons, !s.sources.demoState.current ? ["Permission source unavailable or stale. Retry or inspect Diagnostics; no current permission is established."] : [
      `Authority reports ${s.permission}.`,
      ...(s.permission === "DISABLED" ? ["Execution remains disabled. Observation does not require enabling it."] : []),
      ...s.reasons.map((r) => `Permission: ${r}`),
      ...s.readinessReasons.map((r) => `Current readiness: ${r}`),
    ]);
    reasonList(liveReasons, !s.sources.live.current ? ["Governance source unavailable or stale. Current eligibility cannot be established."] :
      [`Authority reports ${s.liveLabel}.`, ...s.liveReasons.map((r) => String(r).replace(/_/g, " "))]);
    const obs = s.obs;
    setText(obsFields.Session, obs?.session_id ?? "UNAVAILABLE");
    setText(obsFields["Recorded quotes"], obs?.ticks_recorded == null ? "UNAVAILABLE" : fmtInt(obs.ticks_recorded));
    setText(obsFields["Orders submitted (collector)"], obs?.orders_submitted == null ? "UNAVAILABLE" : fmtInt(obs.orders_submitted));
    setText(obsFields["Last broker event (UTC)"], obs?.last_tick_time ? fmtUtc(obs.last_tick_time) : "UNAVAILABLE");
    setText(obsFields.Context, `${getContext().symbol} · ${getContext().timeframe} — presentation only, syncs via BroadcastChannel`);
    if (technical.open) raw.textContent = JSON.stringify({ sources: store.data.resources, health: store.data.health, observation: store.data.observe, demo: store.data.demoState, live: store.data.live, context: getContext() }, null, 2);
    if (diagnostics.open) renderPerf();
    measure("render", "operator workspace update", performance.now() - started);
  }
  technical.addEventListener("toggle", update);
  diagnostics.addEventListener("toggle", () => { renderPerf(); update(); });
  const off = store.on("resources", () => { update(); renderWorkspaceFacts(); });
  const offCtx = onContext(() => { update(); renderWorkspaceFacts(); });
  const clock = setInterval(update, 1000); clock.unref?.();
  onDispose(root, () => { off(); offCtx(); clearInterval(clock); });
  renderWorkspaceFacts();
  update();
  await syncOperations();
}
