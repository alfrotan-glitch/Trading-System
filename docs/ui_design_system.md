# QTS UI — Design System & Operator Workstation

The desktop interface is a **professional research and market-operations workstation** with a deliberate **neon-deep-space visual identity**: layered dark surfaces with ambient cyan/violet depth, luminous primary actions, glowing active tabs and meaningful state glows. Rich visuals are in service of the same priorities — clarity, speed, trust, hierarchy, controlled complexity. The UI renders canonical backend state and never invents its own; visual richness never changes what a state means (see §5 truthfulness, which is unchanged and binding).

## 1. Architecture — what was changed and why

| Decision | Current choice | Why it matters for modern QTS |
|---|---|---|
| Stack | Vanilla ES modules + CSS custom properties, no build step | FastAPI serves files directly; Windows packaging stays `python -m qts.desktop`; no hidden bundler magic |
| State authority | `RESOURCES` map + per-source freshness, `operationalState()` pure derivation | One fact = one source. Health, observation, DEMO permission, LIVE governance and notifications have independent staleness. No single “synced X ago” that lies about authority |
| Transport | Request coalescing for GET, timeout 20s, bounded performance log | Prevents duplicate polling storms; stale/failed sources stay visible instead of freezing |
| Presentation prefs | `workspace.js` sanitized to density/width/navigation + opt-in route restore | Workspace behavior without persisting permission, mode, or risk acknowledgements |
| Focus model | `focus.js` shared dialog containment, inert background, Escape restores invoker | Keyboard-first, WCAG 2.2 visible focus, predictable modal/palette/drawer behavior |
| Shell | `router.js` disposes per-route resources, cancels late renders, measures route duration | No leaked intervals, no interleaved content when navigation races |

DOM-free logic is unit-tested with Node (`format.test.mjs`, `status.test.mjs`, `operations.test.mjs`, `workstation.test.mjs`). The full shell is exercised by a jsdom functional tour against a real backend (`tests/test_ui_logic.py`). Playwright specs capture 11 key screens.

## 2. Information architecture

8 primary areas, 23 destinations. Every legacy endpoint has a home.

| Area | Operator question it answers |
|---|---|
| **Overview** | What is QTS doing now? What mode? Is data healthy? Is observation running? Is execution permitted? Why is it blocked? What next? |
| **Research** | What has been tried, what survived falsification, what data exists |
| **Market** | What did the broker report, when, with what provenance |
| **Trading** | What execution authority says, what would-be vs real fills show |
| **Risk** | Why trading is blocked or permitted, with config hash |
| **Evidence** | Append-only audit, searchable |
| **System** | Setup, MT5 connection, diagnostics (per-source freshness) |
| **Governance** | LIVE — LOCKED, calm, restricted, never auto-enabled |

Routes are hash-based and deep-linkable. Sidebar has a local filter input. Ctrl+K opens a command palette with `aria-activedescendant` and focus containment.

## 3. Design tokens and workstation layer

- Surfaces: deep-space layered `--bg-0…3` over an ambient cyan/violet wash; borders plus elevation shadows carry structure. Gradients are reserved for primary actions, the brand mark, active tab/nav runs and text accents; glows mark meaningful state (`run`, `err`, LIVE-locked, connections) and focus — never ambient decoration. `workstation.css` is the operator-density layer on top.
- Type: Inter/Segoe UI + JetBrains Mono with tabular-nums for numeric columns. 11–28px scale, one spacing system (4px), one radii system (6/8/12).
- Density: compact (6px table padding) vs comfortable (11px), focused (1440px) vs wide (2400px) content width. Remembers only presentation, never authority.
- Semantic states: `ok · run · info · warn · err · neutral · research · locked` each with bg/line/text trio plus redundant mark `● ▲ ■ ○ ✓ ✕`. `UNAVAILABLE` is a word, never `0` or `-`.
- Responsive: header wraps at 1120px, sidebar becomes overlay drawer below 920px, operator facts table scrolls horizontally with keyboard focus ring at 640px. No horizontal overflow at 900px.
- Reduced motion: `prefers-reduced-motion` disables all animations.

## 4. Modern QTS principles implemented

**Instant situational awareness:** Overview shows NOW / OBSERVATION (activity + environment blurb) and exactly one NEXT MEANINGFUL ACTION with why. Header chips: mode, observation, DEMO, LIVE LOCKED, plus per-source freshness in the facts table.

**Hierarchy, not dumping:** Primary layer = human-readable state. Secondary = metrics/evidence. Technical = raw JSON behind `<details>`. Primary facts are 6–7 rows, not 20 cards.

**High density without chaos:** Facts table with aligned numeric columns, compact tables, expandable detail, drawers for row drill-down. Missing values render as `UNAVAILABLE`.

**Progressive disclosure:** Overview has three disclosure levels: operating facts (always), evidence values (observation evidence details), technical snapshots (raw). Drawer for audit/order details.

**Workspace-oriented:** Persistent presentation prefs (density/width/navigation), remember-route opt-in, New Window opens current hash for multi-monitor, sidebar filter, Ctrl+K palette, keyboard sortable tables (Enter/Space), focus restoration on Escape.

**Data visualization that explains:** No fabricated trend chart on Overview. Charts elsewhere require ≥2 real points or show empty state with reason. Quote age is separate from pipeline health.

**Real-time alive without flicker:** Polling via `poll()` with one in-flight iteration, hidden-tab pause, visibility resume, per-resource loading/error state. Updates reuse nodes (setText) and preserve focus/open disclosures. Source failure shows `STALE · RETRYING` not stale data as current.

**Truth is visual design:** States `MEASURED`, `UNAVAILABLE`, `INSUFFICIENT EVIDENCE`, `BLOCKED`, `DEGRADED`, `READY`, `OBSERVING`, `LOCKED` are first-class. Pipeline HEALTHY ≠ quote freshness. `DISABLED` authority + passing readiness ≠ permission.

**Safety understandable:** DEMO readiness permits observation only; DEMO_EXECUTION is always `DISABLED BY POLICY` and has no enable control. LIVE shows `LOCKED` vs `ELIGIBLE · STILL GATED` vs `UNAVAILABLE`, never enabled. DEMO and LIVE remain unmistakable.

**Navigation minimal cost:** 8 groups, searchable sidebar, palette with fuzzy scoring, shallow hierarchy, `aria-current=page`, skip link, workspace preferences.

**Consistency:** One spacing, typography, icon (24px stroke), state, table, button hierarchy. Visual treatments (gradients, glows, shadows) are tokenized and reused, never one-off.

**Accessibility:** Skip link, landmarks, visible focus, inert background for modals/drawers, focus containment, Escape handling, sortable headers keyboard accessible, `aria-sort`, `aria-activedescendant`, live region for operator activity changes.

**Performance is UX:** Request coalescing, bounded 100-entry measurement log (request/render/route/coalesced), per-view refresh guards, interval cleanup on route dispose. Heap growth requires separate browser profiling — not faked.

**Professional instrument:** Operator feels oriented (activity + mode), informed (per-source freshness), in control (inspect links), never misled (UNAVAILABLE ≠ 0), never overwhelmed (one next action), able to inspect deeply (evidence disclosures).

## 5. Truthfulness contract

Enforced by tests:

1. `fmtMetric` only formats when `MEASURED`.
2. `statusInfo` exact match — `ENABLED_BUT_BLOCKED` never healthy; `DISCONNECTED` never connected.
3. `modeInfo` — DEVELOPMENT/PAPER/SHADOW cannot submit; DEMO_FORWARD is observation-only; DEMO_EXECUTION is disabled by policy; LIVE is gated and locked.
4. `operationalState` — OBSERVING requires `state=OBSERVING` + `thread_alive=true` + current source; stale/failed authority → `UNAVAILABLE`; conflicting mode/permission → `CONFLICT · INSPECT`.
5. Failure retains last receipt time; notifications never freshen health; malformed success does not replace state.
6. GET coalesces, POST never coalesces; stopped poll cannot resurrect; hidden polls do not fetch.
7. Table missing → `UNAVAILABLE`, not 0; sort pushes missing to end.
8. Drawer/modal focus contained, Escape restores invoker, background inert.
9. Palette button opens focused search, Escape restores focus.
10. Late failing route cannot replace newer route; cleanup fires once.

## 6. Testing matrix

| Layer | File | Checks |
|---|---|---|
| Truthfulness units | `format.test.mjs`, `status.test.mjs`, `operations.test.mjs` | 39 cases: mode, permission, freshness, coalescing, bounded log, blocked states |
| Interaction & a11y | `workstation.test.mjs` | Table keyboard, drawer inertness, modal ack, palette focus, route race, disclosure preservation |
| Full functional tour | `shell.test.mjs` via `test_ui_logic.py` | 11 routes, header facts, broker truthfulness, DEMO DISABLED + failing checks, LIVE LOCKED hero, risk banner, observation zero-orders, palette |
| Served-shell integrity | `test_ui_shell.py` | Design tokens, truthfulness primitives, asset existence, no CDN, IA 8 groups, legacy endpoint coverage |
| Browser + screenshots | `test_browser.py` (skip-guarded) | 11 screens to `artifacts/ui_screens/`, mode chip = backend truth, permission banner, blocked risk, stale indicator |

Workstation screenshots in `artifacts/workstation/` are generated with the same Chromium used for Playwright when network is unavailable.

## 7. What is intentionally not implemented

- Native multi-monitor workspace restoration and synchronized crosshairs (TradingView benchmark) — not implemented; New Window opens current hash for manual multi-monitor use, honestly documented in workspace preferences.
- Quote-arrival intensity charts from 1s polling — not complete tick history; would mislead.
- Automatic LIVE enablement from observation/DEMO evidence — structurally forbidden.
