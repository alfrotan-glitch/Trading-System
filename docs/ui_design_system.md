# QTS UI — Design System & Product Architecture

The desktop interface is a **command center for a scientific trading system**.
It is built as a coherent product: one visual language, one information
architecture, one rule — **the UI renders canonical backend state and never
invents its own**.

---

## 1. Architecture

| Decision | Choice | Rationale |
|---|---|---|
| Stack | Vanilla ES modules + CSS custom properties | No build step; FastAPI serves the files; pywebview/WebView2 loads them over HTTP; Windows packaging stays `python -m qts.desktop` |
| Charts | In-house SVG (`spark`, `barList`) | No CDN dependency (offline desktop); renders only real recorded values; refuses to draw with < 2 points |
| State | Tiny pub-sub `store` + per-view fetch | The backend is the only authority; no duplicated business rules in the frontend |
| Location | `src/qts/desktop/ui/` | `index.html`, `css/` (4 layers), `js/` (core + `views/`) |

DOM-free logic (`format.js`, `status.js`) is unit-tested with Node
(`node --test tests/ui/js/`); the full shell is exercised by a jsdom
functional tour against a **real** backend (`tests/test_ui_logic.py`);
Playwright/Chromium specs run wherever a browser is available
(`tests/ui/test_browser.py`) and capture screenshots of the key screens.

## 2. Information architecture

28 equally-weighted tabs became **8 primary areas with contextual sub-navigation**
(reachable via the sidebar or `Ctrl/⌘+K` command palette):

| Area | Contains |
|---|---|
| **Overview** | Command center: mode, broker, market data, permission, lifecycle rail, attention list, guided setup journey, account/positions, recent activity, research pulse |
| **Research** | Campaigns · Hypotheses · Experiment ledger · Strategy library · Validation scorecard · Research memory · Data observatory |
| **Market** | Market monitor · Observations (forward observatory) · Data quality · Lineage |
| **Trading** | Demo forward control · Paper/Shadow · Execution · Comparison |
| **Risk** | Safety cockpit: effective limits + provenance, vetoes, mode restrictions, config hash |
| **Evidence** | Evidence explorer (self-audit) · Audit trail |
| **System** | Setup · MT5 connection · Diagnostics |
| **Governance** | LIVE — LOCKED. Deliberately calm, restricted, separate |

Routes are hash-based (`#/market/observations`) and deep-linkable.

## 3. Design tokens (`css/tokens.css`)

- **Surfaces**: graphite scale `--bg-0…3`, inset wells; structure carried by 1px borders, not shadows.
- **Type**: `Inter/Segoe UI` UI stack; `JetBrains Mono/Consolas` for numerics with `tabular-nums`; 11–28 px scale.
- **Spacing**: 4 px scale. **Radii**: 4/8/12. **Elevation**: 2 subtle shadows (drawers/modals only).
- **Accent**: one restrained blue. Semantic state trios (`bg/border/text`) for:
  `ok · run · info · warn · err · neutral · research · locked`.

### Semantic states — color is never the only channel
Every status renders as a **badge with a label and a redundant mark**
(`●` ok, `▲` warn, `■` err, `○` neutral/locked). Canonical states used across
the UI: HEALTHY, READY, OBSERVING, RUNNING, BLOCKED, DEGRADED, WARNING, ERROR,
**UNAVAILABLE**, **INSUFFICIENT EVIDENCE**, **LOCKED**.
`UNAVAILABLE` is always typeset as a word — it must never be confusable with `0`.

## 4. Truthfulness contract (the UI is a presentation layer over truth)

Enforced by tests (`tests/ui/js/*.test.mjs`, `tests/test_ui_shell.py`, jsdom tour):

1. `fmtMetric` renders a value **only** when the backend says `MEASURED`;
   otherwise it prints the status (`UNAVAILABLE`, `INSUFFICIENT EVIDENCE`, …) plus reason.
2. Provenance is always shown explicitly (REAL / DEMO / SYNTHETIC / … chips).
3. Timestamps carry their basis (`… UTC`); ages are honest and clamped.
4. The header always shows the effective mode and a permanent **LIVE LOCKED** chip.
5. Demo permission display mirrors `/api/demo/state` verbatim (e.g. `DEMO EXECUTION: DISABLED`);
   enabling requires the same acks the backend enforces, and a 409 renders the full blocker list.
6. Empty states state what is missing and the next safe action; charts never draw
   fabricated history (`Not enough observations yet`).
7. Failures show what failed, what QTS knows, what it does not know, and what to do next —
   with a Retry control; API requests abort at 20 s and surface instead of freezing.
8. No external origins (offline desktop), no decorative fabrication, no dark patterns —
   the LIVE enablement control is disabled and quiet while the gate is locked.

## 5. Operator model

Every page answers, in order: **primary answer** (page head), **primary action**
(page actions), **supporting evidence** (cards/checklists), **advanced details**
(`<details class="tech">` raw JSON). The Overview additionally runs the
**setup journey**: six steps (terminal → data freshness → research → readiness →
demo → governance), each verified live against canonical endpoints, never assumed.

Real-time behavior: header syncs every 15 s, observation view every 5 s, global
notifications every 20 s — all paused while the window is hidden, all showing a
connection indicator (`synced Xs ago` / `API unreachable — values may be stale`).

## 6. Testing matrix

| Layer | File | Requires |
|---|---|---|
| Truthfulness logic units | `tests/ui/js/format.test.mjs`, `status.test.mjs` | Node |
| Full functional tour (real backend, real DOM) | `tests/ui/js/shell.test.mjs` via `tests/test_ui_logic.py` | Node + jsdom (auto-installed) |
| Served-shell integrity | `tests/test_ui_shell.py` | — |
| Browser + screenshots + stale/error behavior | `tests/ui/test_browser.py` | `pip install playwright && playwright install chromium` (skip-guarded) |

Screenshots land in `artifacts/ui_screens/` (gitignored) for visual review;
diffing baselines can be added on top of them without touching product code.
