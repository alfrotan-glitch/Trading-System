/* Node unit tests — format.js truthfulness rules (no DOM needed).
   Run: node --test tests/ui/js/format.test.mjs tests/ui/js/status.test.mjs  */
import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtMetric, metricTone, fmtNum, fmtAge, fmtUtc, humanStatus, explainStatus, provInfo, fmtDuration, fmtInt } from "../../../src/qts/desktop/ui/js/format.js";

test("fmtMetric: MEASURED renders the value", () => {
  assert.equal(fmtMetric({ status: "MEASURED", value: 12.345 }), "12.35");
  assert.equal(fmtMetric({ status: "MEASURED", value: 0 }), "0.00"); // a real zero is a zero
});

test("fmtMetric: UNAVAILABLE never renders as a number or 0", () => {
  const out = fmtMetric({ status: "UNAVAILABLE", value: null, reason: "no terminal" });
  assert.equal(out, "UNAVAILABLE — no terminal");
  assert.ok(!/^[0-9]/.test(out));
});

test("fmtMetric: INSUFFICIENT_EVIDENCE humanized", () => {
  assert.equal(fmtMetric({ status: "INSUFFICIENT_EVIDENCE", value: null }), "INSUFFICIENT EVIDENCE");
});

test("fmtMetric: null and plain values", () => {
  assert.equal(fmtMetric(null), "—");
  assert.equal(fmtMetric(undefined), "—");
  assert.equal(fmtMetric(42.5), "42.50");
});

test("metricTone: measured ok, unavailable neutral, estimated warn", () => {
  assert.equal(metricTone({ status: "MEASURED", value: 1 }), "ok");
  assert.equal(metricTone({ status: "UNAVAILABLE", value: null }), "neutral");
  assert.equal(metricTone({ status: "INSUFFICIENT_DATA", value: null }), "neutral");
  assert.equal(metricTone({ status: "ESTIMATED", value: 1 }), "warn");
});

test("fmtNum: locale-stable grouping and dash for junk", () => {
  assert.equal(fmtNum(1234567.891), "1,234,567.89");
  assert.equal(fmtNum(null), "—");
  assert.equal(fmtNum("abc"), "—");
});

test("fmtInt: compact integers", () => {
  assert.equal(fmtInt(12345), "12,345");
  assert.equal(fmtInt(undefined), "—");
});

test("fmtAge: honest, monotonic, never negative", () => {
  const now = Date.now();
  assert.equal(fmtAge(now - 3000, now), "just now");
  assert.equal(fmtAge(now - 65000, now), "1m ago");
  assert.equal(fmtAge(now - 7200000, now), "2h ago");
  assert.equal(fmtAge(now + 60000, now), "just now"); // future ts → clamped
  assert.equal(fmtAge(null, now), "—");
});

test("fmtDuration: seconds/minutes/hours", () => {
  assert.equal(fmtDuration(45), "45s");
  assert.equal(fmtDuration(125), "2m 5s");
  assert.equal(fmtDuration(3900), "1h 5m");
  assert.equal(fmtDuration(null), "—");
});

test("fmtUtc: explicit UTC basis", () => {
  assert.equal(fmtUtc("2026-09-17T14:03:22Z"), "2026-09-17 14:03:22 UTC");
  assert.equal(fmtUtc(null), "—");
});

test("humanStatus: machine codes to words", () => {
  assert.equal(humanStatus("INSUFFICIENT_EVIDENCE"), "INSUFFICIENT EVIDENCE");
  assert.equal(humanStatus("NO_TRADE"), "NO TRADE");
});

test("explainStatus: blocked data is a sentence, not only a code", () => {
  assert.match(explainStatus("BLOCKED_INSUFFICIENT_DATA"), /market data does not currently meet the required quality standard/);
  assert.equal(humanStatus("INSUFFICIENT_EVIDENCE"), "INSUFFICIENT EVIDENCE");
});

test("provInfo: provenance is always explicit, never ambiguous", () => {
  assert.deepEqual(provInfo("REAL"), { label: "REAL", cls: "real" });
  assert.deepEqual(provInfo("DEMO"), { label: "DEMO", cls: "demo" });
  assert.deepEqual(provInfo("SYNTHETIC_TICK"), { label: "SYNTHETIC", cls: "synthetic" });
  const unknown = provInfo("weird_class");
  assert.equal(unknown.label, "WEIRD_CLASS"); // shown, not hidden
  assert.ok(provInfo(null).label.includes("UNAVAILABLE"));
});
