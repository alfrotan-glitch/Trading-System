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
  if (/^(pass|passed|ok|healthy|enabled|connected|running|observing|measured|fresh|valid)$/.test(s)) {
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
  SHADOW: { tone: "research", canSubmit: false, realData: false, blurb: "Would-be intents only — no broker submission. Data provenance is reported separately." },
  DEMO_FORWARD: { tone: "info", canSubmit: false, realData: true, blurb: "MT5 demo-account observation only — structurally no broker orders." },
  DEMO_EXECUTION: { tone: "locked", canSubmit: false, realData: true, blurb: "Demo trading needs a recorded owner authorization. The shipped default is off. An order also needs staged arming, a confirmed demo account, and the safety checks. Live trading stays locked. This is not a validated trading opportunity." },
  LIVE: { tone: "locked", canSubmit: "gated", realData: true, blurb: "Live capital. Structurally locked until every gate and human approval pass." },
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
  const observing = src.observeState === "OBSERVING";
  const stages = [
    { id: "research", label: "Research", sub: "hypotheses, campaigns", state: "unknown" },
    { id: "validating", label: "Validating", sub: "DSR · PBO · stress", state: "unknown" },
    { id: "paper", label: "Paper", sub: "simulated fills", state: "unknown" },
    { id: "shadow", label: "Shadow", sub: "intents on real data", state: mode === "SHADOW" ? "current" : "unknown" },
    {
      id: "demo_obs",
      label: "Demo Observation",
      sub: "real ticks, zero orders",
      state: observing ? "current" : "blocked",
      blockedWhy: mode === "DEMO_FORWARD" ? null : "requires DEMO_FORWARD environment + MT5 demo terminal",
    },
    {
      id: "demo_exec",
      label: "Demo Execution",
      sub: "authorized ≠ permitted; zero orders until gated",
      // Only the backend authority may call this current: an authorized policy
      // AND execution_permitted, both reported canonically — never inferred.
      state: src.demoPermitted === true && src.policyAuthorized === true ? "current" : "blocked",
      blockedWhy:
        src.policyAuthorized === true && src.demoPermitted !== true
          ? "Authorized, but not allowed to trade yet. A confirmed account and the safety checks are still required."
          : "requires a recorded owner authorization (shipped default: DEMO_EXECUTION = DISABLED BY POLICY), then staged arming and the pre-trade gate",
    },
    {
      id: "live",
      label: "LIVE",
      sub: "real capital",
      state: src.liveEligible === true ? "eligible" : "live-locked",
      blockedWhy: src.liveEligible === true ? null : "structurally locked — independent governance, never auto-enabled",
    },
  ];
  // Mode and record counts do not prove successful research/promotion stages.
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
