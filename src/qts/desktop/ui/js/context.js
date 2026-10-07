/* Shared workspace context — presentation only, never permission/mode/risk.
   Synchronized across tabs/windows via BroadcastChannel + storage event.
   TradingView benchmark: multi-monitor, synchronized context, but honest about
   what is implemented vs not. No crosshair sync claimed if not built. */

const KEY = "qts.context.v1";
const defaults = { symbol: "XAUUSD", timeframe: "1H" };

function readRaw() {
  try {
    const w = typeof window !== "undefined" ? window : null;
    return JSON.parse(w?.localStorage?.getItem(KEY) || "{}") || {};
  } catch { return {}; }
}
function sanitize(raw = {}) {
  const sym = typeof raw.symbol === "string" && /^[A-Z0-9@._-]{2,20}$/i.test(raw.symbol) ? raw.symbol.toUpperCase() : defaults.symbol;
  const tf = typeof raw.timeframe === "string" && /^(1M|5M|15M|1H|4H|1D)$/i.test(raw.timeframe) ? raw.timeframe.toUpperCase() : defaults.timeframe;
  return { symbol: sym, timeframe: tf };
}

let current = sanitize(readRaw());
const listeners = new Set();
let bc = null;
try {
  const w = typeof window !== "undefined" ? window : null;
  bc = w?.BroadcastChannel ? new w.BroadcastChannel("qts-context") : null;
} catch { bc = null; }

function emit() { listeners.forEach((fn) => { try { fn({ ...current }); } catch {} }); }

export function getContext() { return { ...current }; }
export function setContext(patch) {
  const next = sanitize({ ...current, ...patch });
  if (next.symbol === current.symbol && next.timeframe === current.timeframe) return;
  current = next;
  try {
    const w = typeof window !== "undefined" ? window : null;
    w?.localStorage?.setItem(KEY, JSON.stringify(current));
  } catch {}
  try { bc?.postMessage(current); } catch {}
  emit();
}
export function onContext(fn) {
  listeners.add(fn);
  fn({ ...current });
  return () => listeners.delete(fn);
}

if (bc) bc.onmessage = (e) => {
  if (!e.data) return;
  const next = sanitize(e.data);
  if (next.symbol !== current.symbol || next.timeframe !== current.timeframe) {
    current = next;
    try {
      const w = typeof window !== "undefined" ? window : null;
      w?.localStorage?.setItem(KEY, JSON.stringify(current));
    } catch {}
    emit();
  }
};
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY) return;
    const next = sanitize(readRaw());
    if (next.symbol !== current.symbol || next.timeframe !== current.timeframe) {
      current = next;
      emit();
    }
  });
}
