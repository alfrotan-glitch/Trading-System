import { focusDialog } from "./focus.js";
/* ============================================================
   QTS COMPONENTS — design-system building blocks
   Every component renders backend truth as-is; components have
   no business logic and never transform measured values into
   other values.
   ============================================================ */
import { h, icon, clear } from "./dom.js";
import { fmtMetric, fmtNum, fmtAge, fmtUtc, humanKey, trunc, provInfo, humanStatus, metricTone } from "./format.js";
import { statusInfo, gateInfo } from "./status.js";

export { h, icon, clear };

/* ---------------- badge ---------------- */
export function badge(textOrInfo, opts = {}) {
  const info = typeof textOrInfo === "string" ? statusInfo(textOrInfo) : textOrInfo;
  const mark = opts.noMark ? null : h("span", { class: `dot${info.mark === "■" ? " square" : info.mark === "▲" ? " tri" : ""}`, "aria-hidden": "true" });
  return h("span", { class: `badge ${info.tone} ${opts.lg ? "lg" : ""}`, role: "status" }, mark, info.label);
}

export function chipRow(children) {
  return h("div", { class: "chip-row" }, children);
}

export function provStrip(p) {
  const i = provInfo(p);
  return h("span", { class: `prov ${i.cls}`, title: "Data provenance — where this value comes from" }, i.label);
}

/* ---------------- stat card ---------------- */
export function stat({ label, value, tone, hint, icon: ic }) {
  return h("div", { class: `stat${tone ? ` tone-${tone}` : ""}` },
    h("div", { class: "stat-label" }, ic ? icon(ic, 13) : null, label),
    h("div", { class: `stat-value${String(value).length > 18 ? " sm" : ""}${tone ? ` tone-${tone}` : ""}` }, value ?? "—"),
    hint ? h("div", { class: "stat-hint" }, hint) : null,
  );
}

/** Stat from a backend MetricValue — honest UNAVAILABLE rendering. */
export function metricStat({ label, metric, digits, hint, icon: ic }) {
  const tone = metricTone(metric);
  return stat({ label, value: fmtMetric(metric, digits), tone, hint: hint ?? (metric && metric.reason ? metric.reason : null), icon: ic });
}

/* ---------------- card ---------------- */
export function card({ title, sub, actions, body, bodyClass, icon: ic }) {
  return h("div", { class: "card" },
    (title || actions) && h("div", { class: "card-head" },
      h("div", null, title && h("h3", null, ic ? icon(ic, 15) : null, title), sub && h("div", { class: "meta" }, sub)),
      actions && h("div", { class: "card-actions" }, actions),
    ),
    h("div", { class: `card-body${bodyClass ? ` ${bodyClass}` : ""}` }, body),
  );
}

/* ---------------- kv list ---------------- */
export function kv(pairs, opts = {}) {
  return h("div", { class: "kv" },
    pairs.filter(Boolean).map(([k, v, cls]) => [h("div", { class: "k" }, humanKey(k)), h("div", { class: `v${cls ? ` ${cls}` : ""}` }, v)]),
  );
}

/* ---------------- tech details (raw JSON, explicit layer) ---------------- */
export function tech(obj, summaryText = "Technical details") {
  return h("details", { class: "tech" },
    h("summary", null, summaryText),
    h("div", { class: "tech-body" },
      h("pre", null, typeof obj === "string" ? obj : JSON.stringify(obj, null, 2)),
    ),
  );
}

/* ---------------- check grid (readiness / gates) ---------------- */
export function checkGrid(checks, details = {}) {
  const entries = Object.entries(checks || {});
  if (!entries.length) return emptyState({ icon: "shield", title: "No checks recorded", desc: "Run the readiness gate to evaluate connection, account, symbol, and data checks." });
  return h("div", { class: "check-grid" },
    entries.map(([k, v]) => {
      const info = gateInfo(v, null);
      return h("div", { class: `check ${info.tone === "ok" ? "pass" : info.tone === "err" ? "fail" : "na"}` },
        h("div", { class: "mark", "aria-hidden": "true" }, info.mark),
        h("div", null,
          h("div", { class: "name" }, humanKey(k)),
          details[k] ? h("div", { class: "detail" }, details[k]) : null,
        ),
      );
    }),
  );
}

/* ---------------- empty state ---------------- */
export function emptyState({ icon: ic = "database", title, desc, actions }) {
  return h("div", { class: "empty" },
    h("div", { class: "empty-icon" }, icon(ic, 36)),
    h("div", { class: "empty-title" }, title),
    desc ? h("div", { class: "empty-desc" }, desc) : null,
    actions ? h("div", { class: "empty-action" }, actions) : null,
  );
}

/* ---------------- skeleton loader ---------------- */
export function skeletonInto(el, shape = "cards") {
  clear(el);
  if (shape === "stats") {
    el.appendChild(h("div", { class: "stat-grid" }, Array.from({ length: 4 }, () => h("div", { class: "skeleton skl-stat" }))));
  } else {
    el.appendChild(h("div", { class: "card" }, h("div", { class: "card-body" },
      Array.from({ length: 5 }, (_, i) => h("div", { class: "skeleton skl-line", style: { width: `${90 - i * 12}%` } })),
    )));
  }
  return el;
}

/* ---------------- error box (what failed / known / unknown / next) ---------------- */
export function errorBox({ what, known, next, raw }) {
  return h("div", { class: "error-box", role: "alert" },
    h("div", { class: "what" }, "Something failed: ", what),
    known ? h("div", { class: "know" }, h("b", null, "What QTS knows: "), known) : null,
    h("div", { class: "next" }, h("b", null, "What QTS does not know: "), "the current state of this view until a successful refresh."),
    next ? h("div", { class: "next" }, h("b", null, "What you can do: "), next) : null,
    raw !== undefined ? h("details", null, h("summary", null, "Technical details"), h("pre", null, String(raw))) : null,
  );
}

/* ---------------- table (sortable, honest empties) ---------------- */
/**
 * table({columns:[{key,label,num,render}], rows, empty, onRowClick, sortable})
 * render(row) → node|string; empty → node|string shown when rows=[]
 */
export function table({ columns, rows, empty, onRowClick, sortable = true, dense }) {
  const state = { key: null, dir: 1 };
  const wrap = h("div", { class: `tbl-wrap${dense ? " dense" : ""}` });
  const tbl = h("table", { class: `tbl${dense ? " dense" : ""}` });
  const thead = h("thead");
  const tr = h("tr");
  for (const c of columns) {
    const th = h("th", { class: `${c.num ? "num" : ""}${sortable && !c.noSort ? "" : " no-sort"}`, scope: "col" }, c.label);
    if (sortable && !c.noSort) {
      th.setAttribute("aria-sort", "none");
      th.tabIndex = 0;
      th.setAttribute("aria-label", `${c.label}: activate to sort`);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); th.click(); } });
      th.addEventListener("click", () => {
        state.dir = state.key === c.key ? -state.dir : 1;
        state.key = c.key;
        renderBody();
        thead.querySelectorAll("th").forEach((x) => {
          x.textContent = x.textContent.replace(/ [▲▼]$/, "");
          if (x.getAttribute("aria-sort")) x.setAttribute("aria-sort", "none");
        });
        th.textContent = c.label + (state.dir === 1 ? " ▲" : " ▼");
        th.setAttribute("aria-sort", state.dir === 1 ? "ascending" : "descending");
      });
    }
    tr.appendChild(th);
  }
  thead.appendChild(tr);
  const tbody = h("tbody");
  tbl.append(thead, tbody);
  wrap.appendChild(tbl);

  function renderBody() {
    clear(tbody);
    let data = [...(rows || [])];
    if (state.key) {
      const col = columns.find((c) => c.key === state.key);
      data.sort((a, b) => {
        const va = col.sortVal ? col.sortVal(a) : a[state.key];
        const vb = col.sortVal ? col.sortVal(b) : b[state.key];
        const absentA = va == null || va === "", absentB = vb == null || vb === "";
        if (absentA || absentB) return absentA === absentB ? 0 : absentA ? 1 : -1;
        const na = Number(va), nb = Number(vb);
        const cmp = Number.isFinite(na) && Number.isFinite(nb) ? na - nb : String(va ?? "").localeCompare(String(vb ?? ""));
        return cmp * state.dir;
      });
    }
    if (!data.length) {
      tbody.appendChild(h("tr", { class: "row-empty" }, h("td", { colspan: columns.length }, empty ?? "Nothing recorded yet.")));
      return;
    }
    for (const r of data) {
      const tds = columns.map((c) => {
        const raw = c.render ? c.render(r) : r[c.key];
        const v = raw == null ? "UNAVAILABLE" : raw;
        return h("td", { class: c.num ? "num" : "" }, typeof v === "object" && v !== null && !(v instanceof Node) ? String(v) : v);
      });
      const trR = h("tr", { class: onRowClick ? "clickable" : "", tabindex: onRowClick ? "0" : null, role: onRowClick ? "button" : null }, tds);
      if (onRowClick) {
        trR.addEventListener("click", () => onRowClick(r));
        trR.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRowClick(r); } });
      }
      tbody.appendChild(trR);
    }
  }
  renderBody();
  return wrap;
}

/* ---------------- sparkline (SVG, real data only) ---------------- */
/**
 * spark(values, {width, height, min, max}) → SVG | null.
 * Returns null for < 2 points — never fabricates a shape.
 */
export function spark(values, { width = 260, height = 60 } = {}) {
  const pts = (values || []).filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v))).map(Number);
  if (pts.length < 2) return null;
  const min = Math.min(...pts), max = Math.max(...pts);
  const span = max - min || 1;
  const px = (i) => 2 + (i / (pts.length - 1)) * (width - 4);
  const py = (v) => height - 4 - ((v - min) / span) * (height - 8);
  const line = pts.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  const area = `${line} L${px(pts.length - 1).toFixed(1)},${height - 2} L${px(0).toFixed(1)},${height - 2} Z`;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", height);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Line chart, ${pts.length} real observations, range ${fmtNum(min)} to ${fmtNum(max)}`);
  for (const d of [h("path", { class: "spark-area", d: area }), h("path", { class: "spark-line", d: line })]) {
    svg.appendChild(d);
  }
  return svg;
}

/** Horizontal labeled bars: rows = [{label, value, max, tone, valText}] */
export function barList(rows) {
  return h("div", { class: "bars" },
    rows.map((r) => {
      const pct = r.max ? Math.max(0, Math.min(100, (r.value / r.max) * 100)) : 0;
      return h("div", { class: "bar-row" },
        h("div", null, r.label),
        h("div", { class: "bar-track" }, h("div", { class: `bar-fill ${r.tone || ""}`, style: { width: `${pct}%` } })),
        h("div", { class: "bar-val" }, r.valText ?? String(r.value)),
      );
    }),
  );
}

/* ---------------- lifecycle rail ---------------- */
export function rail(stages) {
  return h("div", { class: "rail", role: "list", "aria-label": "Strategy lifecycle" },
    stages.map((s, i) => {
      const cls = s.state === "current" ? "current" : s.state === "done" ? "done" : s.state === "live-locked" ? "live-locked" : "blocked";
      const mark = s.state === "done" ? "✓" : s.state === "current" ? "●" : s.state === "live-locked" ? "🔒" : i + 1;
      return h("div", { class: "rail-stage", role: "listitem" },
        i > 0 && h("div", { class: `rail-link${stages[i - 1].state === "done" ? " done" : ""}` }),
        h("div", { class: `rail-node ${cls}`, title: s.blockedWhy || s.sub || "" },
          h("div", { class: "rail-dot" }, mark),
          h("div", { class: "rail-label" }, s.label),
          h("div", { class: "rail-sub" }, s.blockedWhy ? `blocked: ${s.blockedWhy}` : s.sub),
        ),
      );
    }),
  );
}

/* ---------------- journey (onboarding) ---------------- */
export function journey(steps) {
  return h("div", { class: "journey" },
    steps.map((s, i) => h("div", { class: `journey-step ${s.state}` },
      h("div", { class: "j-step-mark", "aria-hidden": "true" }, s.state === "done" ? "✓" : i + 1),
      h("div", null,
        h("div", { class: "j-title" }, s.title),
        h("div", { class: "j-desc" }, s.desc),
      ),
      s.action ? h("div", { class: "j-action" }, s.action) : null,
    )),
  );
}

/* ---------------- pipeline ---------------- */
export function pipeline(stages, reachedCount, activeIdx = -1) {
  return h("div", { class: "pipeline" },
    stages.map((s, i) => [
      i > 0 && h("span", { class: "pipe-arrow", "aria-hidden": "true" }, "→"),
      h("span", { class: `pipe-stage${i < reachedCount ? " reached" : ""}${i === activeIdx ? " active" : ""}` }, s),
    ]),
  );
}

/* ---------------- timeline ---------------- */
export function timeline(items) {
  return h("div", { class: "tl" },
    items.map((it) => h("div", { class: `tl-item ${it.tone || ""}` },
      h("div", { class: "tl-when" }, it.when),
      h("div", { class: "tl-what" }, it.what),
      it.detail ? h("div", { class: "meta" }, it.detail) : null,
    )),
  );
}

/* ---------------- drawer ---------------- */
let drawerEl = null;
let releaseDrawer = null;
export function drawer(title, bodyNode) {
  releaseDrawer?.(); releaseDrawer = null;
  if (!drawerEl) {
    const scrim = h("div", { class: "drawer-scrim", onclick: closeDrawer });
    drawerEl = h("div", { class: "drawer", role: "dialog", "aria-modal": "true" });
    document.body.append(scrim, drawerEl);
  }
  drawerEl.setAttribute("aria-label", title);
  clear(drawerEl);
  drawerEl.append(
    h("div", { class: "drawer-head" },
      h("h3", null, title),
      h("button", { class: "btn ghost sm", onclick: closeDrawer, "aria-label": "Close details panel" }, icon("x", 14), "Close"),
    ),
    h("div", { class: "drawer-body" }, bodyNode),
  );
  document.body.classList.add("drawer-open");
  releaseDrawer = focusDialog(drawerEl, closeDrawer);
  return drawerEl;
}
export function closeDrawer() {
  document.body.classList.remove("drawer-open");
  releaseDrawer?.(); releaseDrawer = null;
}

/* ---------------- modal confirm ---------------- */
/**
 * confirmModal({title, body, confirmLabel, danger, acks:[str], confirmDisabled})
 * acks = list of acknowledgment checkbox labels that must all be checked
 * to enable the confirm button. Resolves true/false.
 */
export function confirmModal({ title, body, confirmLabel = "Confirm", danger = false, acks = [], info }) {
  return new Promise((resolve) => {
    const scrim = h("div", { class: "modal-scrim" });
    const checkboxes = [];
    let releaseFocus;
    const finish = (ok) => { document.body.classList.remove("modal-open"); releaseFocus?.(); scrim.remove(); resolve(ok); };
    const confirmBtn = h("button", { class: `btn ${danger ? "danger" : "primary"}`, disabled: acks.length > 0 }, confirmLabel);
    const sync = () => (confirmBtn.disabled = !checkboxes.every((c) => c.checked));
    const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "modal-head" }, h("h3", null, title),
        h("button", { class: "btn ghost sm", "aria-label": "Cancel", onclick: () => finish(false) }, icon("x", 14))),
      h("div", { class: "modal-body" },
        typeof body === "string" ? h("p", { class: "text-dim" }, body) : body,
        info,
        acks.length ? h("div", { class: "stack", style: { marginTop: "12px" } },
          acks.map((txt) => {
            const cb = h("input", { type: "checkbox" });
            checkboxes.push(cb);
            return h("label", { class: "field-inline", style: { alignItems: "flex-start", fontSize: "var(--fs-12)", color: "var(--text-2)" } }, cb, h("span", null, txt));
          }),
        ) : null,
      ),
      h("div", { class: "modal-foot" },
        h("button", { class: "btn", onclick: () => finish(false) }, "Cancel"),
        confirmBtn,
      ),
    );
    checkboxes.forEach((c) => c.addEventListener("change", sync));
    confirmBtn.addEventListener("click", () => finish(true));
    scrim.appendChild(modal);
    scrim.addEventListener("click", (e) => { if (e.target === scrim) finish(false); });
    document.body.classList.add("modal-open");
    document.body.appendChild(scrim);
    releaseFocus = focusDialog(modal, () => finish(false));
  });
}

/* ---------------- toast ---------------- */
export function toast(kind, title, sub) {
  let host = document.querySelector(".toasts");
  if (!host) { host = h("div", { class: "toasts", "aria-live": "polite" }); document.body.appendChild(host); }
  const t = h("div", { class: `toast ${kind}`, role: "status" },
    icon(kind === "ok" ? "check" : kind === "err" ? "alert" : kind === "warn" ? "alert" : "info", 15),
    h("div", null, h("div", { class: "t-title" }, title), sub ? h("div", { class: "t-sub" }, sub) : null),
  );
  host.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 320); }, 4200);
}

/* ---------------- freshness stamp ---------------- */
export function freshStamp(getTs, intervalMs = 1000) {
  const el = h("span", { class: "fresh" }, h("span", { class: "fresh-dot" }), "updated —");
  const tick = () => {
    const ts = getTs();
    const age = ts ? Date.now() - (typeof ts === "number" ? ts : Date.parse(ts)) : null;
    el.className = `fresh${age === null ? "" : age > 120000 ? " down" : age > 45000 ? " stale" : ""}`;
    el.lastChild.textContent = ts ? `updated ${fmtAge(ts)}` : "never updated";
  };
  tick();
  const iv = setInterval(() => { if (!el.isConnected) { clearInterval(iv); return; } if (!document.hidden) tick(); }, intervalMs);
  if (typeof iv.unref === "function") iv.unref();
  el.addEventListener("DOMNodeRemoved", () => clearInterval(iv), { once: true });
  return el;
}

/* ---------------- banner ---------------- */
export function banner(tone, title, sub, iconName) {
  return h("div", { class: `banner ${tone}` },
    icon(iconName || (tone === "ok" ? "check" : tone === "err" ? "alert" : tone === "warn" ? "alert" : "info"), 16),
    h("div", null,
      h("div", { class: "banner-title" }, title),
      sub ? h("div", { class: "banner-sub" }, sub) : null,
    ),
  );
}

/* ---------------- page scaffold ---------------- */
export function page({ crumb, group, title, answer, actions, subnav: sub, body }) {
  return h("div", { class: "page" },
    h("div", { class: "page-head" },
      h("div", { class: "breadcrumbs" }, crumb, group && [h("span", { class: "sep" }, "›"), group]),
      h("div", { class: "page-title-row" },
        h("div", null,
          h("h1", { class: "page-title" }, title),
          answer && h("div", { class: "page-answer" }, answer),
        ),
        actions && h("div", { class: "page-actions" }, actions),
      ),
      sub,
    ),
    body,
  );
}

export { fmtNum, fmtMetric, fmtUtc, fmtAge, trunc, humanKey, humanStatus, statusInfo, gateInfo };
