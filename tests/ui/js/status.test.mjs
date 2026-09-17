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
  assert.equal(modeInfo("SHADOW").realData, true);
  assert.equal(modeInfo("DEMO_FORWARD").canSubmit, "gated");
  assert.equal(modeInfo("LIVE").canSubmit, true);
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
  const stages = lifecycleStages({ mode: "DEMO_FORWARD", observeState: "running", demoState: "DISABLED", liveEligible: false });
  const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
  assert.equal(byId.demo_obs.state, "current");
  assert.equal(byId.demo_exec.state, "blocked");
});

test("lifecycleStages: demo enabled → demo_exec current; earlier stages done", () => {
  const stages = lifecycleStages({ mode: "DEMO_FORWARD", observeState: "running", demoState: "ENABLED", demoPermitted: true, liveEligible: false });
  const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
  assert.equal(byId.demo_exec.state, "current");
  assert.equal(byId.demo_obs.state, "done");
  assert.equal(byId.live.state, "live-locked"); // demo never unlocks live
});

test("lifecycleStages: live eligible never 'done' — stays pending governance", () => {
  const stages = lifecycleStages({ mode: "DEMO_FORWARD", observeState: "running", demoState: "ENABLED", liveEligible: true });
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
