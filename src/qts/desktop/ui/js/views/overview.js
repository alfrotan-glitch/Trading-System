/* QTS HOME — the product command center for a normal user.
   Answers, in plain language and in one screen:
   What is QTS doing? · Is my account connected? · What is happening with
   Gold? · Is there a validated opportunity? · Can I trade? · What next?
   All state comes from the backend (guide/risk); nothing is invented. */

import { api, store } from "../api.js";
import { h, icon } from "../dom.js";
import { banner, tech, errorBox, stat, toast } from "../components.js";
import { fmtNum, fmtAge } from "../format.js";
import { navigate, onDispose } from "../router.js";

const setText = (node, value) => { const s = String(value); if (node.textContent !== s) node.textContent = s; };

function heroContent(g) {
  if (!g) {
    return { headline: "Checking status…", reason: "QTS is reading the current state.", tone: "neutral", action: null };
  }
  if (g.can_trade) {
    return {
      headline: "Ready",
      reason: "QTS is ready for Demo trading. Every order still passes the safety checks.",
      tone: "ok",
      action: { label: "Start a trade", run: () => navigate("#/trading") },
    };
  }
  if (g.kill_switch?.active) {
    return {
      headline: "Trading is temporarily stopped",
      reason: "You can review why and resume from the Trading page.",
      tone: "err",
      action: { label: "View status", run: () => navigate("#/trading") },
    };
  }
  if (!g.connection?.connected) {
    return {
      headline: "Connect your Demo account to get started",
      reason: "Open MetaTrader 5 on this computer and sign in to your demo account, then press Connect account.",
      tone: "warn",
      action: { label: "Connect account", run: "check_connection" },
    };
  }
  if (!g.authorization_ok || !g.mode_ok) {
    return {
      headline: "Trading is currently unavailable",
      reason: g.reason || "QTS needs one more setup step before demo trading.",
      tone: "warn",
      action: { label: "Continue setup", run: () => navigate("#/trading") },
    };
  }
  return {
    headline: g.headline || "Almost ready",
    reason: g.reason || "One more step and demo trading is ready.",
    tone: "warn",
    action: { label: "Continue setup", run: () => navigate("#/trading") },
  };
}

export async function renderHome(root) {
  root.classList.add("operator-workspace", "home");

  const hero = h("section", { class: "home-hero", "aria-live": "polite" },
    h("div", { class: "hero-eyebrow" }, "System status"),
    h("h1", { class: "hero-headline" }, "Checking status…"),
    h("p", { class: "hero-reason text-dim" }, "QTS is reading the current state."),
    h("div", { class: "hero-actions" }));

  const grid = h("div", { class: "home-grid" });
  const accountCard = h("div");
  const goldCard = h("div");
  const oppCard = h("div");
  const safetyCard = h("div");
  grid.append(accountCard, goldCard, oppCard, safetyCard);

  const technical = h("details", { class: "home-technical" },
    h("summary", null, "Technical details"),
    h("div", { class: "tech-body" }, h("p", { class: "small text-dim" }, "Loading…")));

  root.append(hero, grid, technical);

  let guide = null;
  let busy = false;

  function paintHero() {
    const c = heroContent(guide);
    setText(hero.querySelector(".hero-headline"), c.headline);
    setText(hero.querySelector(".hero-reason"), c.reason);
    hero.dataset.tone = c.tone;
    const actions = hero.querySelector(".hero-actions");
    clear(actions);
    if (busy) {
      actions.appendChild(h("button", { class: "btn primary lg", disabled: true }, icon("refresh", 15), "Checking…"));
      return;
    }
    if (c.action) {
      actions.appendChild(h("button", {
        class: "btn primary lg",
        onclick: () => { if (c.action.run === "check_connection") load(true); else c.action.run(); },
      }, icon(c.action.run === "check_connection" ? "activity" : "zap", 15), c.action.label));
    }
    if (guide && !guide.can_trade && guide.connection?.connected) {
      actions.appendChild(h("a", { class: "btn ghost lg", href: "#/trading" }, "Open Trading"));
    }
  }

  function clear(el) { el.replaceChildren(); }

  function paintCards() {
    // ---- Demo account -------------------------------------------------
    const conn = guide?.connection || {};
    accountCard.replaceChildren(h("div", { class: "home-card" },
      h("div", { class: "home-card-head" }, icon("shield", 16), h("h2", null, "Demo account")),
      conn.connected
        ? h("div", { class: "stack" },
            h("div", { class: "home-value ok" }, icon("check", 15), " Demo account connected"),
            h("p", { class: "small text-dim" }, `${conn.broker || conn.server || "Your broker"}${conn.login ? ` · account ${conn.login}` : ""}`))
        : h("div", { class: "stack" },
            h("div", { class: "home-value warn" }, icon("alert", 15), " Demo account not connected"),
            h("p", { class: "small text-dim" }, "Open MetaTrader 5 and sign in to your demo account."),
            busy ? null : h("button", { class: "btn sm", onclick: () => load(true) }, icon("refresh", 13), "Connect account")),
    ));

    // ---- Gold ----------------------------------------------------------
    const q = guide?.quote || {};
    const priceOk = Boolean(q.fresh && (q.bid || q.ask));
    goldCard.replaceChildren(h("div", { class: "home-card" },
      h("div", { class: "home-card-head" }, icon("activity", 16), h("h2", null, "Gold — XAUUSD")),
      priceOk
        ? h("div", { class: "stack" },
            h("div", { class: "home-price" }, fmtNum(q.ask ?? q.bid)),
            h("p", { class: "small text-dim" }, `Bid ${fmtNum(q.bid)} · Ask ${fmtNum(q.ask)} · updated ${guide.checked_at ? fmtAge(Date.parse(guide.checked_at)) : "just now"}`))
        : h("div", { class: "stack" },
            h("div", { class: "home-value neutral" }, "Current price unavailable"),
            h("p", { class: "small text-dim" }, guide?.connection?.connected ? "Waiting for a fresh price from your broker." : "Connect your demo account to see live gold prices.")),
      h("a", { class: "home-link small", href: "#/market" }, "View market →"),
    ));

    // ---- Trading opportunity -------------------------------------------
    oppCard.replaceChildren(h("div", { class: "home-card" },
      h("div", { class: "home-card-head" }, icon("scale", 16), h("h2", null, "Trading opportunity")),
      h("div", { class: "home-value neutral" }, "No validated trading opportunity right now."),
      h("p", { class: "small text-dim" }, "QTS only trades a plan that has passed the research gates. No signal is invented here."),
      h("a", { class: "home-link small", href: "#/reports" }, "See reports →"),
    ));

    // ---- Safety / money --------------------------------------------------
    const kill = guide?.kill_switch?.active;
    safetyCard.replaceChildren(h("div", { class: "home-card" },
      h("div", { class: "home-card-head" }, icon("lock", 16), h("h2", null, "Your money")),
      h("div", { class: "home-value ok" }, "Not at risk"),
      h("p", { class: "small text-dim" }, kill
        ? "Trading is temporarily stopped. Live trading stays locked either way."
        : "Demo account only. Live trading stays locked. Real-capital exposure is $0."),
    ));

    // ---- Technical disclosure ---------------------------------------------
    const body = technical.querySelector(".tech-body");
    body.replaceChildren(
      h("p", { class: "small text-dim" }, "Raw backend state for engineers. None of it changes what QTS enforces."),
      tech(guide || {}, "Raw home state"));
  }

  async function load(userInitiated = false) {
    busy = true;
    paintHero();
    try {
      guide = await api.get("/api/demo/guide");
    } catch (e) {
      busy = false;
      hero.dataset.tone = "err";
      hero.querySelector(".hero-actions").replaceChildren();
      hero.querySelector(".hero-headline").textContent = "Status unavailable";
      hero.querySelector(".hero-reason").textContent = "QTS could not read the current state.";
      hero.querySelector(".hero-actions").appendChild(h("button", { class: "btn primary lg", onclick: () => load(true) }, icon("refresh", 15), "Retry"));
      grid.replaceChildren(errorBox({ what: "the home status could not be loaded", next: "Retry. If QTS was just started, give it a moment.", raw: e.message }));
      return;
    }
    busy = false;
    paintHero();
    paintCards();
    if (userInitiated) {
      // honest, visible result of a manual check — the button must never
      // look like it did nothing
      const c = guide?.connection || {};
      if (c.connected) {
        toast("ok", "Demo account connected",
          `${c.broker || c.server || "Your broker"}${c.login ? ` · account ${c.login}` : ""}. QTS only trades demo accounts.`);
      } else {
        const detail = String(guide?.connection?.detail || "");
        const actionable = "Open MetaTrader 5 on this computer and sign in to your demo account, then press Connect account again.";
        toast("warn", "MetaTrader 5 is not connected",
          detail && detail !== "MetaTrader 5 is not connected." ? `${detail} ${actionable}` : actionable);
      }
    }
  }

  // Keep the hero honest if polled sources change while this page is open.
  const off = store.on("resources", () => { if (root.isConnected && guide) paintHero(); });
  onDispose(root, () => { off(); });

  await load();
}
