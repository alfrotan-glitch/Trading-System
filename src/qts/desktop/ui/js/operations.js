/* Pure operational presentation: authority freshness is independent for every source. */
import { RESOURCES } from "./api.js";
import { modeInfo } from "./status.js";

export function freshness(meta = {}, key, now = Date.now()) {
  if (meta.error) return { label: meta.updatedAt ? "STALE · RETRYING" : "UNAVAILABLE · RETRYING", current: false };
  if (!meta.updatedAt) return { label: meta.loading ? "LOADING" : "UNAVAILABLE", current: false };
  if (now - meta.updatedAt > RESOURCES[key].stale) return { label: "STALE", current: false };
  return { label: meta.loading ? "REFRESHING" : "CURRENT", current: true };
}
const text = (x) => typeof x === "string" && x.trim() ? x : "UNAVAILABLE";
export function operationalState(data, now = Date.now()) {
  const sources = Object.fromEntries(Object.keys(RESOURCES).map((k) => [k, freshness(data.resources?.[k], k, now)]));
  const health = sources.health.current ? data.health : null;
  const obs = sources.observe.current ? data.observe : null;
  const demo = sources.demoState.current ? data.demoState : null;
  const live = sources.live.current ? data.live : null;
  const mode = modeInfo(health?.effective_mode?.effective_mode);
  const observing = obs?.state === "OBSERVING" && obs?.thread_alive === true;
  let observation = text(obs?.state);
  if (obs?.state === "OBSERVING" && obs?.thread_alive !== true) observation = "DEGRADED";
  const demoKnown = demo && typeof demo.execution_permitted === "boolean";
  // A boolean from the authority is not inferred from readiness or risk status.
  const permission = !demoKnown ? "UNAVAILABLE" : demo.execution_permitted === true
    ? mode.mode === "DEMO_EXECUTION" && demo.state === "ENABLED" ? "PERMITTED BY AUTHORITY" : "CONFLICT · INSPECT" : demo.state === "DISABLED" ? "DISABLED" : "BLOCKED";
  const reasons = Array.isArray(demo?.reasons) ? demo.reasons : [];
  const readinessReasons = Array.isArray(demo?.current_readiness?.blocked_reasons) ? demo.current_readiness.blocked_reasons : [];
  const liveReasons = Array.isArray(live?.blocked_reasons) ? live.blocked_reasons : [];
  const liveLabel = live?.eligible === false ? "LOCKED" : live?.eligible === true ? "ELIGIBLE · STILL GATED" : "UNAVAILABLE";
  let next = { label: "Review observation prerequisites", href: "#/market/observations", why: "Review source health and collection evidence. Observation never grants execution permission." };
  if (!sources.health.current || !sources.observe.current || !sources.demoState.current || !sources.live.current) {
    next = { label: "Inspect unavailable sources", href: "#/system/diagnostics", why: "One or more operating facts are unavailable or stale. Restore the source before relying on its last-known value." };
  } else if (obs?.state === "OBSERVING" && !observing || obs?.state === "STOPPED_ON_ERRORS") {
    next = { label: "Inspect observation failure", href: "#/market/observations", why: text(obs.last_error) };
  } else if (String(health?.mt5).toLowerCase() !== "connected") {
    next = { label: "Review MT5 connection", href: "#/system/mt5", why: "The terminal is not reporting a connected state. Inspect connection details; do not enable execution." };
  } else if (observing) {
    next = { label: "Inspect collected evidence", href: "#/market/observations", why: "The collector reports OBSERVING with its worker alive. Review quote timestamps and provenance separately from API freshness." };
  }
  return { sources, mode, health, obs, demo, live, observing, observation, permission, liveLabel, reasons, readinessReasons, liveReasons, next,
    activity: observing ? "Observing market data · no order path" : obs ? `Observation ${observation.toLowerCase()}` : "Observation state unavailable",
    quoteAge: !obs?.last_tick_time || !Number.isFinite(Date.parse(obs.last_tick_time)) ? "UNAVAILABLE"
      : now < Date.parse(obs.last_tick_time) ? "CLOCK SKEW"
      : `${Math.floor((now - Date.parse(obs.last_tick_time)) / 1000)}s · LAST REPORTED EVENT`,
    market: text(health?.market_data), broker: text(health?.mt5),
  };
}
