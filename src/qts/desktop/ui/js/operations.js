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
  // The policy comes from the backend (recorded owner authorization); when the
  // source does not report it, fall back to the conservative reading instead of
  // inferring permission from readiness or mode alone.
  const policyDisabled = demo?.demo_execution_disabled;
  const permission =
    policyDisabled === false
      ? demo.execution_permitted === true
        ? "PERMITTED · DEMO ONLY"
        : demo.state === "DISABLED"
          ? "AUTHORIZED · NOT PERMITTED"
          : "BLOCKED"
      : policyDisabled === true || mode.mode === "DEMO_EXECUTION"
        ? "DISABLED BY POLICY"
        : !demoKnown
          ? "UNAVAILABLE"
          : demo.execution_permitted === true
            ? "CONFLICT · INSPECT"
            : demo.state === "DISABLED" ? "DISABLED" : "BLOCKED";
  const reasons = Array.isArray(demo?.reasons) ? demo.reasons : [];
  const readinessReasons = Array.isArray(demo?.current_readiness?.blocked_reasons) ? demo.current_readiness.blocked_reasons : [];
  const liveReasons = Array.isArray(live?.blocked_reasons) ? live.blocked_reasons : [];
  const liveLabel = live?.eligible === false ? "LOCKED" : live?.eligible === true ? "ELIGIBLE · STILL GATED" : "UNAVAILABLE";
  let next = { label: "Check the gold quotes", href: "#/market/observations", why: "Watching the market does not allow a trade." };
  if (!sources.health.current || !sources.observe.current || !sources.demoState.current || !sources.live.current) {
    next = { label: "Check the unavailable status", href: "#/system/diagnostics", why: "Some status is missing or out of date. Do not act on a blank or old reading." };
  } else if (obs?.state === "OBSERVING" && !observing || obs?.state === "STOPPED_ON_ERRORS") {
    next = { label: "See why quotes stopped", href: "#/market/observations", why: text(obs.last_error) };
  } else if (String(health?.mt5).toLowerCase() !== "connected") {
    next = { label: "Connect the broker terminal", href: "#/system/mt5", why: "The trading terminal is not connected. Do not turn trading on from here." };
  } else if (observing) {
    next = { label: "Review the recorded gold quotes", href: "#/market/observations", why: "Quotes are being recorded. That is not permission to trade." };
  }
  return { sources, mode, health, obs, demo, live, observing, observation, permission, liveLabel, reasons, readinessReasons, liveReasons, next,
    activity: observing ? "Observing market data · no order path" : obs ? `Observation ${observation.toLowerCase()}` : "Observation state unavailable",
    quoteAge: !obs?.last_tick_time || !Number.isFinite(Date.parse(obs.last_tick_time)) ? "UNAVAILABLE"
      : now < Date.parse(obs.last_tick_time) ? "CLOCK SKEW"
      : `${Math.floor((now - Date.parse(obs.last_tick_time)) / 1000)}s · LAST REPORTED EVENT`,
    market: text(health?.market_data), broker: text(health?.mt5),
  };
}
