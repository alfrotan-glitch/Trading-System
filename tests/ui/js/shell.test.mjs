/* ============================================================
   QTS UI shell functional tests — jsdom + the REAL ES modules
   + the REAL backend API (QTS_UI_BASE, default :8901).

   These tests assert that displayed state corresponds to
   backend truth (mission §40): mode display, LIVE locked,
   demo permission display, readiness checks, empty states,
   navigation, palette.
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
  /* bridge Node/jsdom globals so our ES modules run against the jsdom DOM */
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
  await waitUntil(() => document.querySelectorAll(".nav-item").length > 0, 15000, "shell bootstrap");
  await waitUntil(() => document.querySelectorAll("[data-fact]").length === 7 && /unavailable|disconnected/i.test(document.querySelector("[data-fact=broker]")?.textContent || ""), 20000, "overview data render");
});

after(() => {
  if (dom) dom.window.close();
});

test("IA: exactly 8 primary groups, 23 total destinations (was 28 equally-weighted tabs)", () => {
  const groups = [...document.querySelectorAll(".sidebar-group-label")].map((e) => e.textContent.trim());
  assert.deepEqual(groups, ["Overview", "Research", "Market", "Trading", "Risk", "Evidence", "System", "Governance"]);
  assert.equal(document.querySelectorAll(".nav-item").length, 23);
  assert.ok(document.querySelector(".nav-item.restricted"), "Governance is marked restricted");
});

test("header communicates the critical operating facts continuously", async () => {
  const facts = document.getElementById("header-facts");
  await waitUntil(() => facts.textContent.includes("DEVELOPMENT"), 15000, "mode fact");
  assert.ok(facts.textContent.includes("mode"), "mode chip present");
  await waitUntil(() => facts.textContent.includes("LIVE LOCKED"), 15000, "LIVE authority response");
  assert.ok(facts.querySelector(".fact.live-locked"), "locked chip styled as locked");
});

test("overview: operational hierarchy and truthful broker state", () => {
  const broker = document.querySelector('[data-fact="broker"]');
  assert.match(broker.textContent, /UNAVAILABLE|Unavailable|DISCONNECTED/i);
  assert.ok(document.querySelector(".operator-summary"));
  assert.equal(document.querySelectorAll(".next-action a").length, 1);
  assert.equal(document.querySelectorAll(".rail-node").length, 0, "no implied lifecycle completion");
  assert.equal(document.querySelectorAll(".journey-step").length, 0, "no execution-enabling checklist in primary layer");
});
test("overview: high-level posture strip is truthful and keeps safety visible", async () => {
  await waitUntil(() => document.querySelectorAll(".pulse-card").length === 4, 15000, "posture strip");
  assert.equal(document.querySelectorAll(".high-level-strip .pulse-card").length, 4);
  const safety = document.querySelector('[data-pulse="safety"]');
  assert.ok(safety.classList.contains("locked"), "safety boundary remains visually locked");
  assert.match(safety.textContent, /NO_TRADE|DISABLED BY POLICY/i);
  const evidence = document.querySelector('[data-pulse="evidence"]');
  assert.match(evidence.textContent, /INSUFFICIENT|recorded/i, "evidence stays explicit at a glance");
});

test("overview: authority, evidence and technical disclosure are distinct", async () => {
  await waitUntil(() => document.querySelector('[data-fact="permission"]').textContent.includes("DISABLED"));
  await waitUntil(() => document.querySelector('[data-fact="liveLabel"]').textContent.includes("LOCKED"));
  assert.ok(document.body.textContent.includes("Raw overview snapshot"));
  const details = document.querySelectorAll(".operator-workspace > details");
  assert.equal(details.length, 3);
  assert.ok([...details].every((x) => !x.open));
});

test("navigation to Trading → Demo shows authority truth: DISABLED + failing checks", async () => {
  location.hash = "#/trading/demo";
  await waitUntil(() => document.body.textContent.includes("Demo Forward Control"), 20000, "demo view");
  // readiness probing runs the full 14-check gate server-side per request —
  // allow a generous window (shared server, parallel test files)
  await waitUntil(() => document.querySelectorAll(".check").length >= 10, 75000, "readiness checks");
  assert.ok(document.body.textContent.includes("DEMO EXECUTION: DISABLED"), "authority state shown verbatim");
  const failing = document.querySelectorAll(".check.fail").length;
  assert.ok(failing >= 1, `sandbox readiness must show failing checks (no MT5), got ${failing}`);
  assert.ok(!document.querySelector(".banner.ok")?.textContent.includes("ALL CHECKS PASSED"), "no false pass banner");
});

test("navigation to Governance shows LIVE — LOCKED hero with disabled request control", async () => {
  location.hash = "#/governance/live";
  await waitUntil(() => document.body.textContent.includes("Live Trading Governance"), 15000, "governance view");
  await waitUntil(() => document.body.textContent.includes("Why it is locked"), 30000, "governance checklist");
  assert.ok(document.body.textContent.includes("LIVE — LOCKED"));
  const req = [...document.querySelectorAll("button")].find((b) => /enablement/i.test(b.textContent));
  assert.ok(req, "an enablement control exists");
  assert.ok(req.disabled, "enablement control is disabled while locked (calm, not pushy)");
});

test("navigation to Risk shows blocked-or-permitted banner with reasons from authority", async () => {
  location.hash = "#/risk";
  await waitUntil(() => document.body.textContent.includes("Risk Center"), 15000, "risk view");
  await waitUntil(() => document.body.textContent.match(/TRADING IS (CURRENTLY BLOCKED|PERMITTED)/), 15000, "risk banner");
  assert.ok(document.body.textContent.includes("Config hash") || document.body.textContent.includes("config"), "config hash displayed");
});

test("navigation to Market → Monitor shows honest empty state (no fabricated charts)", async () => {
  location.hash = "#/market/monitor";
  await waitUntil(() => document.body.textContent.includes("Market Monitor"), 15000, "monitor view");
  await waitUntil(() => document.body.textContent.match(/No real observations recorded yet|Current quote/), 15000, "monitor content");
  if (!document.querySelector("svg")) {
    assert.ok(document.body.textContent.includes("No real observations recorded yet"));
  }
});

test("observation view: orders-submitted stat exists and observation copy never implies trading", async () => {
  location.hash = "#/market/observations";
  await waitUntil(() => document.body.textContent.includes("Forward Observatory"), 15000, "observation view");
  await waitUntil(() => document.body.textContent.includes("Orders submitted"), 15000, "order count stat");
  assert.ok(document.body.textContent.includes("never submits orders"));
});

test("command palette: Ctrl+K opens, search filters, Enter navigates", async () => {
  document.querySelector('[aria-label="Open command palette (Ctrl+K)"]').click();
  const input = document.querySelector(".palette-input");
  assert.ok(input, "palette input exists");
  input.value = "governance";
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(50);
  const items = [...document.querySelectorAll(".palette-item")];
  assert.ok(items.length >= 1, "palette finds governance");
  assert.ok(items[0].textContent.toLowerCase().includes("governance"));
  items[0].dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await waitUntil(() => document.body.textContent.includes("Live Trading Governance"), 10000, "palette navigation");
  assert.ok(!document.body.classList.contains("palette-open"), "palette closes after action");
});

test("no uncaught page errors during the whole tour", () => {
  const real = errors.filter((e) => !/Could not load content|css/i.test(e));
  assert.deepEqual(real, [], `page errors: ${real.join(" | ")}`);
});
