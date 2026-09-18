import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { table, drawer, closeDrawer, confirmModal } from "../../../src/qts/desktop/ui/js/components.js";
import { initPalette } from "../../../src/qts/desktop/ui/js/palette.js";
import { registerRoutes, dispatch, onDispose } from "../../../src/qts/desktop/ui/js/router.js";
import { renderOverview } from "../../../src/qts/desktop/ui/js/views/overview.js";
import { store, RESOURCES } from "../../../src/qts/desktop/ui/js/api.js";
let dom;
before(() => {
  dom = new JSDOM('<div id="app"><button id="launch">Open</button><main id="main" tabindex="-1"></main></div>', {url: "http://qts.test/#/overview", pretendToBeVisual: true});
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
  const p = initPalette([{id:"overview",label:"Overview",icon:"grid"}]);
  document.getElementById("launch").focus(); p.open();
  assert.equal(document.activeElement.className, "input palette-input");
  assert.equal(document.activeElement.getAttribute("aria-activedescendant"), "palette-option-0");
  key("Escape");
  assert.equal(document.activeElement.id, "launch");
});
test("late failing routes cannot replace a newer route; cleanup fires once", async () => {
  let reject, disposed = 0;
  registerRoutes([
    {id:"overview",label:"Slow",render: async (host) => { onDispose(host, () => disposed++); await new Promise((_, r) => { reject=r; }); }},
    {id:"new",label:"New",render: (host) => { host.textContent="Current view"; }},
  ]);
  window.location.hash = "#/overview"; const pending = dispatch();
  window.location.hash = "#/new"; await dispatch();
  const log = console.error; console.error = () => {};
  try { reject(new Error("Old view failed")); await pending; } finally { console.error=log; }
  assert.equal(document.getElementById("main").textContent, "Current view");
  assert.equal(disposed, 1);
});
test("operator updates keep controls, focus and disclosures; no fake zero on source loss", async () => {
  store.set("health", {effective_mode:{effective_mode:"DEVELOPMENT"}, mt5:"Disconnected", market_data:"Healthy"});
  store.set("observe", {state:"STOPPED", ticks_recorded:0, orders_submitted:0});
  store.set("demoState", {state:"DISABLED",execution_permitted:false});
  store.set("live", {eligible:false});
  store.set("notifications", []);
  registerRoutes([{id:"overview",label:"Overview",render:renderOverview},{id:"new",label:"New",render:()=>{}}]);
  window.location.hash="#/overview"; await dispatch();
  const button = document.querySelector(".operator-workspace button");
  const details = document.querySelector(".evidence-disclosure"); details.open=true; button.focus();
  store.set("observe", {state:"OBSERVING",thread_alive:true,ticks_recorded:15,orders_submitted:0});
  assert.equal(document.querySelector(".operator-workspace button"),button);
  assert.equal(document.activeElement,button);
  assert.equal(details.open,true);
  assert.match(document.querySelector("#operator-activity").textContent,/Observing/);
  store.data.resources.observe.error="offline";store.emit("resources");
  assert.equal(document.querySelector('[data-fact="observation"] .badge').textContent,"UNAVAILABLE");
  assert.equal(document.querySelector('[data-fact="permission"] .badge').textContent,"DISABLED");
  assert.ok(document.querySelector(".evidence-values").textContent.includes("UNAVAILABLE"));
  window.location.hash="#/new"; await dispatch();
});
