/* ============================================================
   QTS product shell functional tests — jsdom + the REAL ES
   modules + the REAL backend API (QTS_UI_BASE).

   The product transformation (2026-09-29) reduced the primary
   navigation to Home · Market · Trading · Reports, with every
   engineering surface under one quiet Advanced area. These tests
   pin that IA AND the unchanged safety truths:
   - the user always sees status, account state and one next step
   - LIVE stays visibly locked (quietly, but always present)
   - no price is shown unless it is fresh; no opportunity invented
   - the demo workflow still renders the full readiness checklist
     and the verbatim authority state under technical disclosure
   - legacy product URLs redirect into the new IA
   ============================================================ */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const UI = path.resolve(__dirname, "../../../src/qts/desktop/ui");
const BASE = process.env.QTS_UI_BASE || "http://127.0.0.1:8901";

let dom, errors = [], document, window;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitUntil(fn, timeoutMs = 15000, what = "condition") {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { if (fn()) return; } catch { /* keep waiting */ }
    await sleep(120);
  }
  throw new Error(`timeout waiting for ${what}`);
}

async function goto(hash) {
  window.location.hash = hash;
  await sleep(200);
}

before(async () => {
  const html = fs.readFileSync(path.join(UI, "index.html"), "utf8");
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => { if (!/css|Could not load/i.test(String(e))) errors.push(String(e)); });
  vc.on("error", (...a) => errors.push(a.join(" ")));
  dom = new JSDOM(html, {
    url: BASE + "/#",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  window = dom.window;
  document = window.document;
  globalThis.window = window;
  globalThis.document = document;
  globalThis.location = window.location;
  globalThis.history = window.history;
  globalThis.Node = window.Node;
  globalThis.HTMLElement = window.HTMLElement;
  globalThis.HTMLInputElement = window.HTMLInputElement;
  globalThis.requestAnimationFrame = window.requestAnimationFrame?.bind(window) ?? ((cb) => setTimeout(cb, 0));
  globalThis.cancelAnimationFrame = window.cancelAnimationFrame?.bind(window) ?? clearTimeout;
  window.HTMLElement.prototype.scrollIntoView = window.HTMLElement.prototype.scrollIntoView || (() => {});
  const realFetch = globalThis.fetch;
  globalThis.fetch = (p, o) => realFetch(String(p).startsWith("http") ? p : BASE + p, o);
  window.fetch = globalThis.fetch;

  await import("../../../src/qts/desktop/ui/js/main.js?boot=" + Date.now());
  await waitUntil(() => document.querySelectorAll(".nav-item").length >= 4, 15000, "shell bootstrap");
  await waitUntil(() => document.querySelectorAll(".home-card").length === 4, 30000, "home render");
});

after(() => {
  if (dom) dom.window.close();
});

test("IA: four product pages, everything else under one quiet Advanced", () => {
  const primary = [...document.querySelectorAll(".nav-item.primary")].map((e) => e.textContent.trim());
  assert.deepEqual(primary, ["Home", "Market", "Trading", "Reports"]);
  const advanced = document.querySelector(".nav-advanced");
  assert.ok(advanced, "one Advanced area exists");
  assert.equal(advanced.querySelectorAll(".nav-item.adv").length, 20, "all engineering pages live under Advanced");
  assert.ok(!advanced.open, "Advanced starts collapsed — quiet by default");
  // engineering vocabulary is not primary navigation
  for (const forbidden of ["Campaigns", "Hypotheses", "Diagnostics", "Audit", "Governance", "Lineage"]) {
    assert.ok(!primary.includes(forbidden), `${forbidden} is not a primary page`);
  }
});

test("header says only what matters — and live lock stays visible", async () => {
  const account = document.getElementById("header-account");
  await waitUntil(() => /Demo account: (Connected|Not connected)/.test(account.textContent), 15000, "account chip");
  assert.ok(document.getElementById("header-status").textContent.length > 0, "an overall status is shown");
  assert.ok(!document.getElementById("header-facts"), "no row of engineering chips in the product header");
  assert.ok(document.querySelector(".conn-dot"), "service health indicator remains (silent staleness is forbidden)");
  const lock = document.querySelector(".header-lock");
  assert.ok(lock && /Live locked/i.test(lock.textContent), "LIVE lock stays visible — quietly, but always");
  // Runtime mode is stated plainly (sandbox runs Development mode) — §3 modes
  const modeChip = document.getElementById("header-mode");
  await waitUntil(() => !modeChip.hidden && modeChip.textContent.length > 0, 15000, "mode chip");
  assert.equal(modeChip.textContent, "Development mode");
});

test("home answers the product questions honestly", async () => {
  await goto("#/home");
  await waitUntil(() => document.querySelectorAll(".home-card").length === 4, 20000, "home cards");
  const body = document.querySelector("#main").textContent;
  // account state, gold honesty, opportunity honesty, money safety
  assert.ok(/Demo account (connected|not connected)/i.test(body), "account state visible");
  assert.ok(body.includes("No validated trading opportunity right now."), "no invented opportunity");
  assert.ok(body.includes("Not at risk"), "real money never at risk");
  assert.ok(/Live trading stays locked/i.test(body), "live lock stated on home");
  // no terminal in the sandbox → no price may be displayed, ever
  assert.ok(body.includes("Current price unavailable"), "stale/missing price is never shown as a number");
  // exactly one primary action in the hero
  assert.equal(document.querySelectorAll(".home-hero .hero-actions .btn.primary").length, 1, "one next action");
});

test("legacy product URLs redirect into the new IA", async () => {
  for (const [legacy, canonical] of [
    ["#/overview", "#/home"],
    ["#/trading/demo", "#/trading"],
    ["#/market/monitor", "#/market"],
    ["#/research/campaigns", "#/advanced/research-campaigns"],
    ["#/governance/live", "#/advanced/governance"],
    ["#/risk", "#/advanced/risk"],
  ]) {
    await goto(legacy);
    await waitUntil(() => window.location.hash === canonical, 10000, `redirect ${legacy} → ${canonical}`);
  }
});

test("trading page keeps the guided workflow and the full checklist", async () => {
  await goto("#/trading");
  await waitUntil(() => document.body.textContent.includes("Is the practice account connected"), 20000, "trading view");
  // the 14-check readiness gate still renders (inside technical disclosure)
  await waitUntil(() => document.querySelectorAll(".check").length >= 10, 75000, "readiness checks");
  assert.ok(document.body.textContent.includes("DEMO EXECUTION: DISABLED"), "authority state shown verbatim under disclosure");
  assert.ok(document.body.textContent.includes("No real money is at risk"), "demo-only reassurance on the trade ticket");
  const failing = document.querySelectorAll(".check.fail").length;
  assert.ok(failing >= 1, `sandbox readiness must show failing checks (no MT5), got ${failing}`);
});

test("market page shows gold honestly — never an invented price", async () => {
  await goto("#/market");
  await waitUntil(() => document.body.textContent.includes("Gold — XAUUSD"), 20000, "market view");
  await waitUntil(() => document.querySelector(".market-price")?.textContent.length > 0, 20000, "price block");
  // no terminal → no fresh quote → the honest sentence, not a number
  assert.ok(document.body.textContent.includes("Current price unavailable"));
  assert.ok(!document.querySelector(".market-chart svg"), "no chart without real recorded observations");
});

test("reports never manufacture a result", async () => {
  await goto("#/reports");
  await waitUntil(() => document.body.textContent.includes("Not enough data to report a result."), 20000, "reports view");
  assert.ok(document.body.textContent.includes("Locked"), "live lock reported");
});

test("governance remains reachable under Advanced, still locked", async () => {
  await goto("#/advanced/governance");
  await waitUntil(() => document.body.textContent.includes("This page cannot open it"), 20000, "governance view");
  assert.ok(document.body.textContent.includes("LIVE — LOCKED"));
  const req = [...document.querySelectorAll("button")].find((b) => /cannot be opened/i.test(b.textContent));
  assert.ok(req && req.disabled, "live control is disabled while locked");
});

test("risk page still states WHY trading is blocked", async () => {
  await goto("#/advanced/risk");
  await waitUntil(() => document.body.textContent.match(/TRADING IS (CURRENTLY BLOCKED|NOT AUTHORIZED)/), 20000, "risk banner");
  assert.ok(!document.body.textContent.includes("TRADING IS PERMITTED"));
});

test("observation view keeps orders-submitted honesty", async () => {
  await goto("#/advanced/data-observations");
  await waitUntil(() => document.body.textContent.includes("Orders submitted"), 20000, "order count stat");
  assert.ok(document.body.textContent.includes("never submits orders") || document.body.textContent.includes("never submits"));
});

test("keyboard search still finds pages (no advertised palette button)", async () => {
  assert.ok(!document.querySelector('[aria-label="Open command palette (Ctrl+K)"]'), "palette is not advertised in the header");
  document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
  await waitUntil(() => document.querySelector(".palette-input"), 5000, "palette via Ctrl+K");
  const input = document.querySelector(".palette-input");
  input.value = "Live trading rules";
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(80);
  const items = [...document.querySelectorAll(".palette-item")];
  assert.ok(items.length >= 1, "search finds the live-rules page");
  items[0].dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await waitUntil(() => window.location.hash === "#/advanced/governance", 10000, "palette navigation");
  await waitUntil(() => document.body.textContent.includes("This page cannot open it"), 15000, "governance render");
});

test("every Advanced page renders under the new IA — nothing broke in the move", async () => {
  const advancedRoutes = [
    "research-campaigns", "research-hypotheses", "research-experiments",
    "research-strategies", "research-validation", "research-memory", "research-data",
    "data-observations", "data-quality", "data-lineage",
    "trading-practice", "trading-history", "trading-comparison",
    "risk", "evidence", "audit", "governance",
    "system-setup", "system-mt5", "system-diagnostics",
  ];
  for (const id of advancedRoutes) {
    await goto(`#/advanced/${id}`);
    await waitUntil(() => document.getElementById("main").textContent.trim().length > 60, 20000, `advanced/${id} content`);
    const body = document.getElementById("main").textContent;
    assert.ok(!body.includes("this view failed to render"), `advanced/${id} fell back to the error box`);
    assert.ok(document.querySelectorAll(".nav-item.adv").length === 20, "Advanced list stays intact while navigating");
  }
});

test("no uncaught page errors during the whole tour", () => {
  const real = errors.filter((e) => !/Could not load content|css/i.test(e));
  assert.deepEqual(real, [], `page errors: ${real.join(" | ")}`);
});
