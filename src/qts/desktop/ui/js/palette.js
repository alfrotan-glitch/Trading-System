/* ============================================================
   QTS COMMAND PALETTE — Ctrl/Cmd+K global search & actions
   Keyboard-first: ↑/↓ navigate, Enter run, Esc close.
   ============================================================ */
import { h, icon, clear } from "./dom.js";
import { navigate } from "./router.js";

let items = [];
let sel = 0;
let visible = [];

export function initPalette(IA, actions = []) {
  /* static navigation entries from the IA tree */
  items = [];
  for (const g of IA) {
    if (g.children) {
      for (const c of g.children) items.push({ label: c.label, group: g.label, href: `#/${g.id}/${c.id}`, icon: g.icon });
      items.push({ label: `${g.label} overview`, group: g.label, href: `#/${g.id}/${g.defaultChild ?? g.children[0].id}`, icon: g.icon });
    } else {
      items.push({ label: g.label, group: "Workspace", href: `#/${g.id}`, icon: g.icon });
    }
  }
  items.push(...actions);

  const input = h("input", { class: "input palette-input", placeholder: "Search pages, actions, concepts…", "aria-label": "Command palette search" });
  const list = h("div", { class: "palette-list", role: "listbox", id: "palette-list" });
  const scrim = h("div", { class: "palette-scrim", onclick: (e) => { if (e.target === scrim) close(); } },
    h("div", { class: "palette", role: "dialog", "aria-modal": "true", "aria-label": "Command palette" },
      h("div", { class: "palette-input-row" }, icon("search", 16), input,
        h("span", { class: "kbd" }, "esc")),
      list,
    ),
  );
  document.body.appendChild(scrim);

  input.addEventListener("input", () => renderList(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, visible.length - 1); paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
    else if (e.key === "Enter" && visible[sel]) { e.preventDefault(); run(visible[sel]); }
    else if (e.key === "Escape") close();
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); open(); }
    if (e.key === "Escape") {
      if (document.body.classList.contains("palette-open")) close();
      else if (document.body.classList.contains("drawer-open")) import("./components.js").then((m) => m.closeDrawer());
    }
  });

  function open() {
    document.body.classList.add("palette-open");
    input.value = "";
    sel = 0;
    renderList("");
    requestAnimationFrame(() => input.focus());
  }
  function close() {
    document.body.classList.remove("palette-open");
    input.blur();
  }
  function run(item) {
    close();
    if (item.href) navigate(item.href);
    if (item.run) item.run();
  }
  function renderList(q) {
    const needle = q.trim().toLowerCase();
    visible = items
      .map((it) => ({ it, score: score(it, needle) }))
      .filter((x) => x.score > (needle ? 0 : -1))
      .sort((a, b) => b.score - a.score)
      .slice(0, 12)
      .map((x) => x.it);
    sel = 0;
    clear(list);
    if (!visible.length) {
      list.appendChild(h("div", { class: "palette-empty" }, `Nothing matches “${q}”.`));
      return;
    }
    visible.forEach((it, i) => {
      list.appendChild(h("div", {
        class: `palette-item${i === sel ? " sel" : ""}`, role: "option", "aria-selected": i === sel ? "true" : "false",
        onclick: () => run(it), onmousemove: () => { if (sel !== i) { sel = i; paint(); } },
      },
        icon(it.icon ?? "chevron", 14),
        h("span", null, it.label),
        h("span", { class: "pl-group" }, it.group ?? ""),
      ));
    });
  }
  function paint() {
    list.querySelectorAll(".palette-item").forEach((el, i) => {
      el.classList.toggle("sel", i === sel);
      el.setAttribute("aria-selected", i === sel ? "true" : "false");
      if (i === sel) el.scrollIntoView({ block: "nearest" });
    });
  }
  return { open, close };
}

function score(item, needle) {
  if (!needle) return 1;
  const hay = `${item.label} ${item.group ?? ""}`.toLowerCase();
  if (hay.includes(needle)) return hay.startsWith(needle) ? 100 : 50;
  // subsequence fuzzy
  let i = 0;
  for (const ch of hay) if (ch === needle[i]) i++;
  return i === needle.length ? 10 : -1;
}
