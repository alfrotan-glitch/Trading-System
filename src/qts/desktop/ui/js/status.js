/* ============================================================
   QTS STATUS — semantic state model (DOM-free, Node-testable)

   The UI never invents state. Every function here derives its
   answer exclusively from canonical backend values that are
   passed in. Unknown → neutral/UNAVAILABLE, never guessed.
   ============================================================ */

/**
 * Map an arbitrary backend status string to a semantic tone + label.
 * Returns {tone, label, mark} where mark is the redundant glyph
 * (color is never the only channel).
 */
export function statusInfo(raw) {
  const s = String(raw ?? "").toLowerCase();
  if (!s || s === "none" || s === "unknown" || s === "unavailable" || s === "—") {
    return { tone: "neutral", label: raw ? String(raw) : "UNAVAILABLE", mark: "○" };
  }
  if (/(^|_)(pass|passed|ok|healthy|enabled|connected|running|measured|fresh|valid)/.test(s) && !/not|no_|never/.test(s)) {
    return { tone: "ok", label: String(raw).toUpperCase(), mark: "●" };
  }
  if (/(degrad|stale|warn|pending|partial|estimated|synthetic|sufficien|expired)/.test(s)) {
    return { tone: "warn", label: String(raw).toUpperCase(), mark: "▲" };
  }
  if (/(block|fail|error|suspend|reject|kill|violation|live_locked|refused|denied)/.test(s)) {
    return { tone: "err", label: String(raw).toUpperCase(), mark: "■" };
  }
  if (/(observ|disabled|locked|gate|research|no_trade)/.test(s)) {
    return { tone: s.includes("locked") ? "locked" : "neutral", label: String(raw).toUpperCase(), mark: "○" };
  }
  return { tone: "neutral", label: String(raw).toUpperCase(), mark: "○" };
}

/** Boolean gate → statusInfo (true=pass, false=fail, null=not evaluated). */
export function gateInfo(v, label) {
  if (v === true) return { tone: "ok", label: label || "PASS", mark: "✓" };
  if (v === false) return { tone: "err", label: label || "FAIL", mark: "✕" };
  return { tone: "neutral", label: "NOT EVALUATED", mark: "○" };
}

/* ---------------- effective mode ---------------- */

const MODES = {
  DEVELOPMENT: { tone: "neutral", canSubmit: false, realData: false, blurb: "Backtest/research only — mock or historical data, no broker orders." },
  PAPER: { tone: "info", canSubmit: false, realData: false, blurb: "Simulated fills on recorded data — no broker contact." },
  SHADOW: { tone: "research", canSubmit: false, realData: true, blurb: "Real market data, would-be intents only — nothing is submitted." },
  DEMO_FORWARD: { tone: "warn", canSubmit: "gated", realData: true, blurb: "Real MT5 DEMO terminal and account. Orders only if demo execution is enabled — labeled DEMO, never LIVE." },
  LIVE: { tone: "locked", canSubmit: true, realData: true, blurb: "Live capital. Structurally locked until every gate and human approval pass." },
};

/**
 * Metadata for the effective mode. Accepts the canonical
 * effective_mode string; unknown values render as UNAVAILABLE.
 */
export function modeInfo(mode) {
  const m = String(mode || "").toUpperCase().replace(/[-\s]+/g, "_");
  if (MODES[m]) return { mode: m, ...MODES[m] };
  return { mode: m || "UNAVAILABLE", tone: "neutral", canSubmit: false, realData: false, blurb: "Mode not resolved — treat as no-permission until the backend authority resolves it." };
}

/* ---------------- lifecycle rail ---------------- */

/**
 * Derive lifecycle-rail stages from canonical values only.
 * @param {object} src
 *   mode            effective mode (health.effective_mode.effective_mode)
 *   observeState    /api/observe/status .state
 *   demoState       /api/demo/state .state ("DISABLED"|"ENABLED"|…)
 *   demoPermitted   /api/demo/state .execution_permitted
 *   liveEligible    /api/live/status .eligible
 *   liveStatus      /api/live/status .live_trading ("LIVE — LOCKED")
 */
export function lifecycleStages(src = {}) {
  const mode = String(src.mode || "").toUpperCase();
  const observing = src.observeState === "running" || src.observeState === "RUNNING" ||
    (src.ticksRecorded ?? 0) > 0;
  const demoEnabled = src.demoState === "ENABLED" || src.demoPermitted === true;

  const stages = [
    { id: "research", label: "Research", sub: "hypotheses, campaigns", state: "done" },
    { id: "validating", label: "Validating", sub: "DSR · PBO · stress", state: "done" },
    { id: "paper", label: "Paper", sub: "simulated fills", state: "done" },
    { id: "shadow", label: "Shadow", sub: "intents on real data", state: mode === "SHADOW" ? "current" : "done" },
    {
      id: "demo_obs",
      label: "Demo Observation",
      sub: "real ticks, zero orders",
      state: demoEnabled ? "done" : mode === "DEMO_FORWARD" ? "current" : observing ? "done" : "blocked",
      blockedWhy: mode === "DEMO_FORWARD" || demoEnabled ? null : "requires DEMO_FORWARD environment + MT5 demo terminal",
    },
    {
      id: "demo_exec",
      label: "Demo Execution",
      sub: "real demo orders",
      state: demoEnabled ? "current" : "blocked",
      blockedWhy: demoEnabled ? null : "requires all 14 readiness checks + explicit risk acknowledgment",
    },
    {
      id: "live",
      label: "LIVE",
      sub: "real capital",
      state: src.liveEligible === true ? "eligible" : "live-locked",
      blockedWhy: src.liveEligible === true ? null : "structurally locked — independent governance, never auto-enabled",
    },
  ];
  // mark everything before current as done
  const cur = stages.findIndex((s) => s.state === "current");
  if (cur > 0) stages.forEach((s, i) => { if (i < cur && s.state !== "current") s.state = "done"; });
  return stages;
}

/* ---------------- attention ordering ---------------- */

const LEVEL_RANK = { critical: 0, error: 1, warning: 2, info: 3 };
/** Sort notifications by severity (critical first). Stable for ties. */
export function attentionRank(list = []) {
  return [...list].sort((a, b) =>
    (LEVEL_RANK[String(a.level).toLowerCase()] ?? 4) - (LEVEL_RANK[String(b.level).toLowerCase()] ?? 4));
}

/** Freshness tone from an age in ms (data staleness contract: 60s gate). */
export function freshnessTone(ageMs) {
  if (ageMs === null || ageMs === undefined || Number.isNaN(Number(ageMs))) return "neutral";
  if (ageMs <= 60_000) return "ok";
  if (ageMs <= 300_000) return "warn";
  return "err";
}
