/* ============================================================
   QTS FORMAT — pure formatting functions (DOM-free, Node-testable)

   Truthfulness rules encoded here:
   * A MetricValue that is not MEASURED is NEVER rendered as a
     number. UNAVAILABLE stays UNAVAILABLE — visibly distinct
     from 0.
   * Provenance is always rendered as an explicit label.
   * Timestamps are rendered with an explicit basis (UTC).
   ============================================================ */

/**
 * Format a backend MetricValue ({status, value, reason}).
 * MEASURED          → the value, formatted
 * UNAVAILABLE       → "UNAVAILABLE" (+ reason as hint)
 * INSUFFICIENT_*    → the status, humanized
 * plain number      → formatted number (honest pass-through)
 * null/undefined    → "—"
 */
export function fmtMetric(m, digits = 2) {
  if (m === null || m === undefined) return "—";
  if (typeof m === "object" && "status" in m) {
    if (m.status === "MEASURED" || m.status === "OK") {
      return m.value === null || m.value === undefined ? "—" : fmtNum(m.value, digits);
    }
    // Not measured: render the status, never a fabricated number.
    return humanStatus(m.status) + (m.reason ? ` — ${m.reason}` : "");
  }
  if (typeof m === "number") return fmtNum(m, digits);
  if (typeof m === "boolean") return m ? "yes" : "no";
  return String(m);
}

/** Tone (semantic color family) for a MetricValue. */
export function metricTone(m) {
  if (m === null || m === undefined) return "neutral";
  if (typeof m === "object" && "status" in m) {
    if (m.status === "MEASURED" || m.status === "OK") return "ok";
    if (m.status === "UNAVAILABLE" || String(m.status).startsWith("INSUFFICIENT")) return "neutral";
    if (m.status === "ESTIMATED" || m.status === "SYNTHETIC") return "warn";
    return "neutral";
  }
  return "ok";
}

/** 1234.5 → "1,234.50" (tabular-friendly, locale-stable en-US). */
export function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Compact integer: 12345 → "12,345". */
export function fmtInt(v) {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** ISO timestamp/epoch → "12s ago" / "4m ago" / "2h ago" / "—" (never negative). */
export function fmtAge(ts, now = Date.now()) {
  if (!ts) return "—";
  const t = typeof ts === "number" ? ts : Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  let s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Seconds-since value → "12s" (for TTL/age fields sent as durations). */
export function fmtDuration(s) {
  if (s === null || s === undefined || Number.isNaN(Number(s))) return "—";
  s = Number(s);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** ISO → explicit-UTC clock string "2026-09-17 14:03:22 UTC". */
export function fmtUtc(ts) {
  if (!ts) return "—";
  const d = ts instanceof Date ? ts : new Date(typeof ts === "number" ? ts : String(ts).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return String(ts);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
         `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

/** Machine status → human words. UNAVAILABLE stays uppercase (distinct from zero). */
export function humanStatus(s) {
  if (s === null || s === undefined) return "—";
  const map = {
    INSUFFICIENT_EVIDENCE: "INSUFFICIENT EVIDENCE",
    INSUFFICIENT_DATA: "INSUFFICIENT DATA",
    NO_REAL_OBSERVATIONS: "NO REAL OBSERVATIONS",
  };
  return map[s] || String(s).replace(/_/g, " ");
}

/** Provenance → {label, cls} for the .prov strip. Never ambiguous. */
export function provInfo(p) {
  const v = String(p || "").toUpperCase();
  if (v.includes("REAL") && !v.includes("SYNTH")) return { label: "REAL", cls: "real" };
  if (v.includes("DEMO")) return { label: "DEMO", cls: "demo" };
  if (v.includes("SYNTH") || v.includes("SIM") || v.includes("MOCK")) return { label: "SYNTHETIC", cls: "synthetic" };
  if (v.includes("ESTIMAT")) return { label: "ESTIMATED", cls: "synthetic" };
  return { label: v ? v.slice(0, 18) : "PROVENANCE UNAVAILABLE", cls: "" };
}

/** Truncate long strings for table cells. */
export function trunc(s, n = 80) {
  s = String(s ?? "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/** Camel/snake key → Title Words. */
export function humanKey(k) {
  return String(k)
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
