/* Operator workspace: stable primary state → evidence → technical payloads.
   Subscribes to shell resources. No separate polling loop or trading mutation. */
import { store, syncOperations, RESOURCES, measurements, measure } from "../api.js";
import { operationalState } from "../operations.js";
import { h, icon } from "../dom.js";
import { page } from "../components.js";
import { fmtUtc, fmtAge, fmtInt } from "../format.js";
import { statusInfo } from "../status.js";
import { onDispose } from "../router.js";

const link = (label, href, cls = "btn sm") => h("a", { class: cls, href }, label);
const setText = (node, value) => { const s = String(value); if (node.textContent !== s) node.textContent = s; };

export async function renderOverview(root) {
  root.classList.add("operator-workspace");
  const activity = h("h2", { id: "operator-activity" }, "Loading operating state…");
  const explanation = h("p", { class: "text-dim" });
  const next = link("Inspect unavailable sources", "#/system/diagnostics", "btn primary");
  const nextWhy = h("p", { class: "text-dim small" });
  const announce = h("div", { class: "sr-only", role: "status", "aria-live": "polite" });
  const refresh = h("button", { class: "btn", onclick: () => syncOperations(true) }, icon("refresh", 14), "Refresh sources");
  root.appendChild(page({ crumb: "Overview", title: "Operator workspace", answer: "Current operation, authority and evidence — one source per fact.", actions: [refresh] }));
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
    h("h2", { id: "facts-title" }, "Operating facts"),
    h("p", { class: "small text-dim" }, "Freshness below means the last successful API receipt, not the age of a market quote. Stale authority cannot establish current permission."),
    h("div", { class: "tbl-wrap", tabindex: "0", "aria-label": "Operating facts, horizontally scrollable on narrow screens" },
      h("table", { class: "tbl facts-table" },
        h("thead", null, h("tr", null, ["Source", "Reported state", "Meaning / constraint", "API freshness", "Evidence"].map((t) => h("th", { scope: "col" }, t)))), tbody))));

  const demoReasons = h("ul", { class: "reason-list" });
  const liveReasons = h("ul", { class: "reason-list" });
  root.appendChild(h("div", { class: "operator-grid" },
    h("section", { class: "operator-section" }, h("h2", null, "Why DEMO is not an ordinary switch"),
      h("p", { class: "text-dim small" }, "Readiness and durable execution permission are separate. A passing connection check does not enable execution."), demoReasons,
      link("Inspect permission & readiness", "#/trading/demo")),
    h("section", { class: "operator-section live-boundary" }, h("h2", null, "LIVE / independent governance"),
      h("p", { class: "text-dim small" }, "Eligibility is not enablement. Observation and DEMO evidence never automatically authorize live capital."), liveReasons,
      link("Inspect missing LIVE evidence", "#/governance/live"))));

  const observationEvidence = h("dl", { class: "evidence-values" });
  const obsFields = {};
  for (const title of ["Session", "Recorded quotes", "Orders submitted (collector)", "Last broker event (UTC)"]) {
    obsFields[title] = h("dd", null, "UNAVAILABLE");
    observationEvidence.append(h("dt", null, title), obsFields[title]);
  }
  root.appendChild(h("details", { class: "operator-section evidence-disclosure" },
    h("summary", null, "Observation evidence / scope and limitations"), observationEvidence,
    h("p", { class: "text-dim small" }, "Recorded quotes are not complete tick history. Collector order counts do not establish terminal-wide activity. Structural consistency does not establish origin, completeness or research sufficiency."),
    h("p", { class: "text-dim small" }, "No trend chart is drawn here: these endpoints describe current state, not a comparable historical series."),
    link("Open observations", "#/market/observations"), " ", link("Open research inventory", "#/research/data"), " ", link("Account & execution evidence", "#/trading/execution"), " ", link("Audit trail", "#/evidence/audit")));

  const raw = h("pre");
  const technical = h("details", { class: "operator-section" }, h("summary", null, "Raw overview snapshot / technical evidence"), raw);
  const perf = h("pre");
  const diagnostics = h("details", { class: "operator-section" }, h("summary", null, "UI performance / last 100 local measurements"),
    h("p", { class: "text-dim small" }, "Browser request, update and route durations in milliseconds; not broker latency. Bounded to 100 records. Heap growth requires a separate browser profiling run."), perf);
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
  let lastAnnouncement = "";
  function update() {
    if (!root.isConnected) return;
    const started = performance.now();
    const s = operationalState(store.data);
    setText(activity, s.activity);
    setText(explanation, `${s.mode.mode} — ${s.mode.blurb}`);
    setText(next, s.next.label); next.href = s.next.href;
    setText(nextWhy, s.next.why);
    refresh.disabled = Object.values(store.data.resources).some((m) => m.loading);
    const summary = `${s.activity}; DEMO ${s.permission}; LIVE ${s.liveLabel}`;
    if (summary !== lastAnnouncement) { setText(announce, summary); lastAnnouncement = summary; }
    const meanings = {
      mode: "Environment capability is not execution permission.",
      broker: "Terminal connectivity; not proof of a healthy current quote.",
      market: "Backend pipeline status, not proof of a healthy live quote.",
      quoteAge: s.obs?.last_tick_time ? `Last reported broker event: ${fmtUtc(s.obs.last_tick_time)}. Clock accuracy is not established.` : "No current collected-quote timestamp is available. Pipeline health is not quote freshness.",
      observation: s.observing ? "Collector reports an active worker. No order path." : s.obs?.last_error || s.obs?.note || "No active collection is established.",
      permission: !s.sources.demoState.current ? "Current permission cannot be established." : `Authority state: ${s.demo?.state ?? "UNAVAILABLE"}; risk and execution gates remain independent.`,
      liveLabel: "Never auto-enabled. Independent evidence and human governance required.",
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
    if (technical.open) raw.textContent = JSON.stringify({ sources: store.data.resources, health: store.data.health, observation: store.data.observe, demo: store.data.demoState, live: store.data.live }, null, 2);
    if (diagnostics.open) perf.textContent = JSON.stringify(measurements, null, 2);
    measure("render", "operator workspace update", performance.now() - started);
  }
  technical.addEventListener("toggle", update);
  diagnostics.addEventListener("toggle", update);
  const off = store.on("resources", update);
  const clock = setInterval(update, 1000); clock.unref?.();
  onDispose(root, () => { off(); clearInterval(clock); });
  update();
  await syncOperations();
}
