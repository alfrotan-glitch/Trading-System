import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { table, drawer, closeDrawer, confirmModal } from "../../../src/qts/desktop/ui/js/components.js";
import { initPalette } from "../../../src/qts/desktop/ui/js/palette.js";
import { registerRoutes, dispatch, onDispose } from "../../../src/qts/desktop/ui/js/router.js";
import { renderHome } from "../../../src/qts/desktop/ui/js/views/overview.js";

let dom;
before(() => {
  dom = new JSDOM('<div id="app"><button id="launch">Open</button><main id="main" tabindex="-1"></main></div>', {url: "http://qts.test/#/home", pretendToBeVisual: true});
  for (const key of ["window", "document", "location", "Node", "HTMLElement"]) globalThis[key] = key === "window" ? dom.window : dom.window[key];
  globalThis.requestAnimationFrame = (fn) => fn();
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
});
after(() => dom.window.close());
const key = (value, extra = {}) => document.activeElement.dispatchEvent(new window.KeyboardEvent("keydown", {key: value, bubbles: true, cancelable: true, ...extra}));

test("table sorting is keyboard accessible and missing is not zero", () => {
  const el = table({columns: [{key: "n",label:"Value",num:true}], rows: [{n:null},{n:0},{n:2}]});
  document.getElementById("main").replaceChildren(el);
  const th = el.querySelector("th"); th.focus(); key("Enter");
  assert.equal(th.getAttribute("aria-sort"), "ascending");
  assert.deepEqual([...el.querySelectorAll("td")].map((x) => x.textContent), ["0", "2", "UNAVAILABLE"]);
  key(" "); assert.equal(th.getAttribute("aria-sort"), "descending");
});
test("drawer Escape restores focus and releases background inertness", () => {
  const launch = document.getElementById("launch"); launch.focus();
  const panel = drawer("Evidence", document.createElement("p"));
  assert.equal(document.getElementById("app").inert, true);
  assert.ok(panel.contains(document.activeElement));
  key("Escape");
  assert.equal(document.activeElement, launch);
  assert.notEqual(document.getElementById("app").inert, true);
});
test("confirmation focus is contained and acknowledgements remain mandatory", async () => {
  document.getElementById("launch").focus();
  const result = confirmModal({title:"Test only", body:"No API call", acks:["I understand"], confirmLabel:"Proceed"});
  const modal = document.querySelector(".modal");
  assert.equal([...modal.querySelectorAll("button")].find((b) => b.textContent === "Proceed").disabled, true);
  key("Tab", {shiftKey:true});
  assert.ok(modal.contains(document.activeElement));
  key("Escape"); assert.equal(await result, false);
  assert.equal(document.activeElement.id, "launch");
});
test("palette button API opens focused search and Escape restores focus", () => {
  const p = initPalette([{id:"home",label:"Home",icon:"home"}]);
  document.getElementById("launch").focus(); p.open();
  assert.equal(document.activeElement.className, "input palette-input");
  assert.equal(document.activeElement.getAttribute("aria-activedescendant"), "palette-option-0");
  key("Escape");
  assert.equal(document.activeElement.id, "launch");
});
test("late failing routes cannot replace a newer route; cleanup fires once", async () => {
  let reject, disposed = 0;
  registerRoutes([
    {id:"home",label:"Slow",render: async (host) => { onDispose(host, () => disposed++); await new Promise((_, r) => { reject=r; }); }},
    {id:"new",label:"New",render: (host) => { host.textContent="Current view"; }},
  ]);
  window.location.hash = "#/home"; const pending = dispatch();
  window.location.hash = "#/new"; await dispatch();
  const log = console.error; console.error = () => {};
  try { reject(new Error("Old view failed")); await pending; } finally { console.error=log; }
  assert.equal(document.getElementById("main").textContent, "Current view");
  assert.equal(disposed, 1);
});
test("home degrades honestly when its source is unreachable — no invented numbers", async () => {
  registerRoutes([{id:"home",label:"Home",render:renderHome},{id:"new",label:"New",render:()=>{}}]);
  window.location.hash = "#/home";
  await dispatch();
  const hero = document.querySelector(".home-hero");
  assert.ok(hero, "home renders a hero even when the guide source fails");
  assert.equal(hero.dataset.tone, "err");
  assert.match(hero.querySelector(".hero-headline").textContent, /status unavailable/i);
  // The error copy never fabricates account, price, or outcome numbers.
  const text = document.getElementById("main").textContent;
  assert.ok(!/\$\s*\d/.test(text), "no dollar figures on a failed source");
  assert.ok(!/confidence/i.test(text), "no invented confidence figures");
  assert.ok(!/BUY|SELL/.test(text), "no invented trade direction");
  window.location.hash = "#/new"; await dispatch();
});
