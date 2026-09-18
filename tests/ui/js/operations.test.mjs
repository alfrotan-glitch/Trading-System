import { test } from "node:test";
import assert from "node:assert/strict";
import { api, store, syncResource, RESOURCES, poll, measurements, measure } from "../../../src/qts/desktop/ui/js/api.js";
import { freshness, operationalState } from "../../../src/qts/desktop/ui/js/operations.js";
import { sanitizeWorkspace } from "../../../src/qts/desktop/ui/js/workspace.js";
const NOW = 1000000;
function data() {
  return { resources: Object.fromEntries(Object.keys(RESOURCES).map((k) => [k, { updatedAt: NOW }])),
    health: { effective_mode: {effective_mode: "DEMO_FORWARD"}, mt5: "Connected", market_data: "Healthy" },
    observe: {state: "OBSERVING", thread_alive: true, ticks_recorded: 10},
    demoState: {state: "DISABLED", execution_permitted: false, current_readiness: {passed: true}},
    live: {eligible: false, blocked_reasons: ["validation_evidence"]} };
}

test("canonical OBSERVING requires a current source and an active worker", () => {
  const d = data();
  assert.equal(operationalState(d, NOW).observing, true);
  d.observe.thread_alive = false;
  assert.equal(operationalState(d, NOW).observation, "DEGRADED");
  d.observe = {state: "STOPPED", ticks_recorded: 9000};
  assert.equal(operationalState(d, NOW).observing, false);
});
test("healthy pipeline is not manufactured quote freshness", () => {
  const d = data();
  assert.equal(operationalState(d, NOW).market, "Healthy");
  assert.equal(operationalState(d, NOW).quoteAge, "UNAVAILABLE");
});
test("passing readiness never grants execution permission", () => {
  const s = operationalState(data(), NOW);
  assert.equal(s.permission, "DISABLED");
  assert.equal(s.mode.canSubmit, false);
  assert.equal(s.liveLabel, "LOCKED");
});
test("stale or failed authority cannot show currently permitted", () => {
  const d = data(); d.health.effective_mode.effective_mode = "DEMO_EXECUTION";
  d.demoState = {state: "ENABLED", execution_permitted: true};
  assert.equal(operationalState(d, NOW).permission, "PERMITTED BY AUTHORITY");
  d.resources.demoState.updatedAt = NOW - 46000;
  assert.equal(operationalState(d, NOW).permission, "UNAVAILABLE");
  d.resources.demoState = {updatedAt: NOW, error: "offline"};
  assert.equal(operationalState(d, NOW).permission, "UNAVAILABLE");
});
test("conflicting mode/permission is flagged, not papered over", () => {
  const d = data(); d.demoState = {state: "ENABLED", execution_permitted: true};
  assert.equal(operationalState(d, NOW).permission, "CONFLICT · INSPECT");
  d.demoState.execution_permitted = "true";
  assert.equal(operationalState(d, NOW).permission, "UNAVAILABLE");
});
test("one failed source does not erase other current facts", () => {
  const d = data(); d.resources.observe.error = "offline";
  const s = operationalState(d, NOW);
  assert.equal(s.observation, "UNAVAILABLE");
  assert.equal(s.mode.mode, "DEMO_FORWARD");
  assert.equal(s.permission, "DISABLED");
  assert.match(s.next.label, /unavailable/);
});
test("LIVE eligibility is never rendered as enabled", () => {
  const d = data(); d.live.eligible = true;
  assert.equal(operationalState(d, NOW).liveLabel, "ELIGIBLE · STILL GATED");
  d.resources.live.error = "offline";
  assert.equal(operationalState(d, NOW).liveLabel, "UNAVAILABLE");
});
test("freshness distinguishes loading, current refresh, stale, failed and unknown", () => {
  assert.equal(freshness({}, "health", NOW).label, "UNAVAILABLE");
  assert.equal(freshness({loading: true}, "health", NOW).label, "LOADING");
  assert.equal(freshness({updatedAt: NOW, loading: true}, "health", NOW).label, "REFRESHING");
  assert.equal(freshness({updatedAt: NOW-31000}, "health", NOW).current, false);
  assert.equal(freshness({updatedAt: NOW, error: "failed"}, "health", NOW).current, false);
});
test("presentation preferences reject permission, mode, arbitrary routes and unknown values", () => {
  const p = sanitizeWorkspace({density: "huge", width: "wide", enabled: true, mode: "LIVE", risk_ack: true, route: "#/demo/enable?yes=true", rememberRoute: true});
  assert.deepEqual(p, {density: "compact", width: "wide", navigation: "standard", rememberRoute: true, route: "#/overview"});
  assert.equal(sanitizeWorkspace(null).rememberRoute, false);
});
test("GET requests coalesce and POST requests never coalesce", async () => {
  const old = globalThis.fetch; let finish, calls = 0;
  globalThis.fetch = async () => { calls++; await new Promise((r) => { finish = r; }); return {ok: true, text: async () => '{}'}; };
  try {
    const a = api.get("/dedup-test"), b = api.get("/dedup-test");
    assert.equal(a, b); assert.equal(calls, 1); finish(); await Promise.all([a,b]);
    globalThis.fetch = async () => { calls++; return {ok: true, text: async () => '{}'}; };
    await Promise.all([api.post("/post-test"), api.post("/post-test")]);
    assert.equal(calls, 3);
  } finally { globalThis.fetch = old; }
});
test("failure retains last successful receipt time; notifications never freshen health", async () => {
  const old = globalThis.fetch;
  store.set("health", {mt5: "Connected"});
  const stamp = store.data.resources.health.updatedAt;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    await syncResource("health", {force: true});
    store.set("notifications", []);
    assert.equal(store.data.resources.health.updatedAt, stamp);
    assert.equal(store.data.lastSync, stamp);
    assert.equal(freshness(store.data.resources.health, "health").current, false);
    globalThis.fetch = async () => ({ok: true, text: async () => '{"mt5":"Connected"}'});
    await syncResource("health", {force: true});
    assert.equal(freshness(store.data.resources.health, "health").current, true);
  } finally { globalThis.fetch = old; }
});
test("malformed successful response does not replace last-known state", async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async () => ({ok: true, text: async () => 'null'});
  store.set("observe", {state: "STOPPED"});
  try {
    await syncResource("observe", {force: true});
    assert.equal(store.data.observe.state, "STOPPED");
    assert.equal(freshness(store.data.resources.observe, "observe").current, false);
  } finally { globalThis.fetch = old; }
});
test("a stopped in-flight poll cannot schedule new work; hidden polls do not fetch", async () => {
  const old = globalThis.document;
  const doc = new EventTarget(); doc.hidden = false; globalThis.document = doc;
  let finish, calls = 0;
  const stop = poll(async () => { calls++; await new Promise((r) => { finish = r; }); }, 3);
  stop(); finish(); await new Promise((r) => setTimeout(r, 20));
  assert.equal(calls, 1);
  doc.hidden = true;
  const stop2 = poll(async () => { calls++; }, 3);
  await new Promise((r) => setTimeout(r, 15));
  assert.equal(calls, 1);
  doc.hidden = false; doc.dispatchEvent(new Event("visibilitychange"));
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(calls, 2);
  stop2(); globalThis.document = old;
});
test("performance history is bounded", () => {
  for (let i=0; i<300; i++) measure("test", "bounded", i);
  assert.equal(measurements.length, 100);
});
