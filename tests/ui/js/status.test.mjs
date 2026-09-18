/* Node unit tests — status.js semantic model (no DOM needed). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { statusInfo, gateInfo, modeInfo, lifecycleStages, attentionRank, freshnessTone } from "../../../src/qts/desktop/ui/js/status.js";

test("statusInfo: healthy/pass family → ok", () => {
  for (const s of ["Healthy", "connected", "PASSED", "Running", "fresh"]) {
    assert.equal(statusInfo(s).tone, "ok", s);
  }
});

test("statusInfo: blocked/fail family → err with distinct mark", () => {
  for (const s of ["BLOCKED", "Suspended", "FAILED", "error"]) {
    assert.equal(statusInfo(s).tone, "err", s);
    assert.equal(statusInfo(s).mark, "■");
  }
});

test("statusInfo: unavailable/unknown → neutral, label preserved", () => {
  const i = statusInfo("UNAVAILABLE");
  assert.equal(i.tone, "neutral");
  assert.equal(i.label, "UNAVAILABLE");
  assert.equal(statusInfo(null).label, "UNAVAILABLE");
});

test("gateInfo: true/false/null — never guesses", () => {
  assert.equal(gateInfo(true).tone, "ok");
  assert.equal(gateInfo(false).tone, "err");
  assert.equal(gateInfo(null).tone, "neutral");
  assert.equal(gateInfo(undefined).label, "NOT EVALUATED");
});

test("modeInfo: canonical modes carry submit/data truth", () => {
  assert.equal(modeInfo("DEVELOPMENT").canSubmit, false);
  assert.equal(modeInfo("PAPER").canSubmit, false);
  assert.equal(modeInfo("SHADOW").canSubmit, false);
  assert.equal(modeInfo("SHADOW").realData, false);
  assert.equal(modeInfo("DEMO_FORWARD").canSubmit, false);
  assert.equal(modeInfo("LIVE").canSubmit, "gated");
  assert.equal(modeInfo("LIVE").tone, "locked");
});

test("modeInfo: unknown mode renders as no-permission, not a guess", () => {
  const m = modeInfo("WEIRD_MODE");
  assert.equal(m.canSubmit, false);
  assert.match(m.blurb, /no-permission/);
});

test("lifecycleStages: development sandbox → demo stages blocked, LIVE locked", () => {
  const stages = lifecycleStages({ mode: "DEVELOPMENT", observeState: "idle", demoState: "DISABLED", liveEligible: false });
  const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
  assert.equal(byId.demo_obs.state, "blocked");
  assert.equal(byId.demo_exec.state, "blocked");
  assert.equal(byId.live.state, "live-locked");
  assert.ok(byId.demo_obs.blockedWhy.length > 0);
  assert.ok(byId.live.blockedWhy.includes("locked"));
});

test("lifecycleStages: demo_forward observing → demo_obs current", () => {
  const stages = lifecycleStages({ mode: "DEMO_FORWARD", observeState: "OBSERVING", demoState: "DISABLED", liveEligible: false });
  const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
  assert.equal(byId.demo_obs.state, "current");
  assert.equal(byId.demo_exec.state, "blocked");
});

test("lifecycleStages: demo execution authority → demo_exec current; no inferred research completion", () => {
  const stages = lifecycleStages({ mode: "DEMO_EXECUTION", observeState: "OBSERVING", demoState: "ENABLED", demoPermitted: true, liveEligible: false });
  const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
  assert.equal(byId.demo_exec.state, "current");
  assert.equal(byId.research.state, "unknown");
  assert.equal(byId.demo_obs.state, "current");
  assert.equal(byId.live.state, "live-locked"); // demo never unlocks live
});

test("lifecycleStages: live eligible never 'done' — stays pending governance", () => {
  const stages = lifecycleStages({ mode: "DEMO_FORWARD", observeState: "OBSERVING", demoState: "ENABLED", liveEligible: true });
  const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
  assert.equal(byId.live.state, "eligible");
  assert.equal(byId.live.blockedWhy, null);
});

test("attentionRank: critical first, stable", () => {
  const out = attentionRank([
    { level: "info", title: "a" }, { level: "critical", title: "b" }, { level: "warning", title: "c" },
  ]);
  assert.deepEqual(out.map((x) => x.title), ["b", "c", "a"]);
});

test("freshnessTone: 60s contract", () => {
  assert.equal(freshnessTone(10_000), "ok");
  assert.equal(freshnessTone(120_000), "warn");
  assert.equal(freshnessTone(400_000), "err");
  assert.equal(freshnessTone(null), "neutral");
});

test("blocked compound statuses are never healthy", () => {
  for (const state of ["ENABLED_BUT_BLOCKED", "unhealthy", "connected_but_failed"]) assert.notEqual(statusInfo(state).tone, "ok");
  assert.equal(modeInfo("DEMO_EXECUTION").canSubmit, "gated");
  const stages = lifecycleStages({ mode: "DEVELOPMENT", observeState: "STOPPED", ticksRecorded: 900 });
  assert.equal(stages.find((x) => x.id === "demo_obs").state, "blocked");
});
