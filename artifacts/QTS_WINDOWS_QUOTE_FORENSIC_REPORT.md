# Forensic diagnosis — Windows run: `quote not fresh on server clock` / order 409

Date: 2026-09-30 · Branch: `arena/01a0ce9f-trading-system` · Diagnosis verified at `a29842a` · **Read-only diagnosis — no code changed.**

## Environment constraint (stated first, not hidden)

The diagnosis was performed in a Linux sandbox. `import MetaTrader5` fails there (`platform: linux`; the package is Windows-only), so **no live connection to the WMMarkets-Demo terminal was possible from the sandbox and no "live" value was fabricated.** Items 1–4 below are answered in two forms: (a) the exact relationships derived arithmetically from the numbers captured on the Windows machine (internally consistent and matching the code precisely), and (b) a read-only probe — committed at `scripts/probe_quote_forensics.py` — that captures the absolute live values on the Windows machine in one run (section B). Items 5–9 are answered definitively from the code and the captured numbers.

## A. Findings per requested item

Let `N` = `time.time()` (true UTC) on the Windows machine at the moment of the failing check.

**1. Raw `time` / `time_msc` of the latest XAUUSD@ tick.**
Derived: `epoch ≈ N + 1695` (server-basis stamp), i.e. `time ≈ N+1695`, `time_msc ≈ (N+1695)·1000`. Source: the audit line `raw local age -1695.0s` is computed as `raw_age = now − epoch` (`demo_gate.evaluate_tick_epoch_freshness`). Absolute value requires the Windows probe (section B).

**2. Current local UTC on the Windows machine.**
`N` = `time.time()` at the check. Symbolic only from the sandbox; the probe prints it explicitly. Note: the local clock is verified *consistent with true UTC* by item 4 (a skewed local clock would shift the implied offset away from +3h; it reads +2h59m).

**3. The server timestamp the tick represents.**
The raw stamp `N + 1695` is trade-server local time (MT5 stamps ticks in server time). Subtracting the measured server offset (~10740s, item 4): the tick's **true-UTC occurrence ≈ N − 9045**, i.e. the tick actually happened **≈ 2h 30m 45s before the check**.

**4. WMMarkets-Demo server timezone/offset.**
MT5's Python API exposes no timezone call; the best MT5-derived facts are (a) the bar-probe implied offset printed by QTS: **+2h59m** (`implied_offset = bar_time + 30 − now`, `demo_gate.py:137`), and (b) `mt5.terminal_info().time` (server time) minus `time.time()` — captured by the probe. Conclusion: **≈ UTC+3, currently reading ≈ +2h59m — i.e. about one minute off the exact +3h mark.** Earlier sessions measured +3h exactly (`measured-m1-bar`, 10800s). This matters — see finding F2.

**5. Why QTS derives `raw local age = −1695s`.**
`raw_age = now − epoch = N − (N + 1695) = −1695`. The raw stamp carries a +3h server basis but the tick itself is ~2.5h old, so the net effect is a stamp only ~28 min "ahead" of true UTC: `+10740 − 9045 ≈ +1695`. Negative raw age here does **not** mean a future/fabricated tick; it means a stale tick on a +3h server basis.

**6. Why QTS derives `server offset = +2h59m`.**
`implied_offset = bar_time + 30 − now`. The current M1 bar open (server basis) is ≈ `N + 10710`, so `implied ≈ 10740s = +2h59m` (the +30s is the mid-bar assumption). This is an honest estimate of server-now − UTC-now.

**7. Is the tick genuinely stale, or is QTS misreading the timestamp? → GENUINELY STALE.**
Decisive evidence: the failing comparison is `epoch < bar_time` where **both values come from MT5 on the same server time basis** (`epoch` from `symbol_info_tick`, `bar_time` from `copy_rates_from_pos(XAUUSD@, M1, 0, 1)`). Same-basis differences are immune to local-clock error and to any timezone interpretation. `bar_time − epoch = 9069s` means the last tick predates the currently forming M1 bar by ~2h31m in the server's own time. A fresh tick must be inside the current bar. **QTS is interpreting the MT5 timestamp correctly; the freshness gate is doing exactly its job.** Corroboration: had the tick been fresh, raw local age would read ≈ −3h (−10740s); it reads −1695s, precisely `−10740 + 9045` — a ~2.5h-old tick under a +3h basis.

**8. Exact reason for the `/api/demo/order` 409.**
Fail-closed refusal in the pre-trade gate on `market_data_fresh`. Chain: `session.submit` → `build_context` → `_quote_probe` → `MarketDataProvider.get_tick` → adapter `ticks()` reads `symbol_info_tick("XAUUSD@")`; `server_utc_offset` returned `(0.0, "assumed-utc-fallback")` for this tick (see F2), so `_validate_tick` delegated to the shared contract `raw_tick_freshness` → `evaluate_tick_epoch_freshness` → `epoch < bar_time` → `MarketDataError("tick not fresh on server clock: last tick precedes the current M1 bar by 9069s — server-clock age >= 9069s, provably not fresh (raw local age -1695.0s, implied server offset +2h59m) for XAUUSD@")`. `_quote_probe` catches it and returns `{ok:false, fresh:false, age_s:null}`; the gate records `market_data_fresh = UNKNOWN` ("tick age could not be computed" — no usable quote), which fails closed; `run_pretrade_gate` verdict `passed=False` → `SubmissionResult(allowed=False, state="NO_TRADE")` → route returns `JSONResponse(status_code=409)`. (The full `reasons[]` array in the 409 body lists every unmet check; quote freshness is the one quoted.)

**9. Complete path MT5 tick → order gate (verified in code).**
```
mt5.symbol_info_tick("XAUUSD@")                     [adapter.ticks, mt5_adapter.py:1629]
  base = time_msc/1000 (else time)                  [mt5_adapter.py:1633-1644]
  offset, basis = server_utc_offset(sym)            [mt5_adapter.py:1511; quantized 15-min grid]
  event_time = base − offset; provenance records raw stamps + basis
MarketDataProvider.get_tick                          [market_data.py:130]
  _validate_tick: basis == "assumed-utc-fallback"   [market_data.py:66-84]
    → broker.raw_tick_freshness(sym, raw_epoch)     [mt5_adapter.py:1579]
      → evaluate_tick_epoch_freshness               [demo_gate.py:114]
          raw_age = now − epoch      (≤ 60s rule)
          bar_time = copy_rates(M1,0,1)[0]["time"]  (server basis)
          epoch < bar_time  → STALE  ← this fired (9069s)
    → MarketDataError "tick not fresh on server clock"
_quote_probe catches → {ok:false}                    [demo_session.py:323]
build_context: tick_age_s = None                     [demo_session.py:776]
run_pretrade_gate: market_data_fresh UNKNOWN→fail    [demo_pretrade.py:346-358]
submit → NO_TRADE → HTTP 409                         [demo_session.py:1099; demo.py:352]
```
The readiness gate (check #9 `market_data_fresh`, `demo_gate.py:456-464`) uses the **same** contract. `_guide_response` returns HTTP 200 **only when ok**, and `stage.advance` enforces **all** prerequisites (`demo_stage.can_advance`), so **`prepare` returning 200 proves the quote was genuinely fresh at prepare time** — full readiness + fresh quote + authority enablement all passed then. Between prepare and the order attempt the feed stopped producing XAUUSD@ ticks; by order time the last tick was ~2.5h old. There is no QTS-side tick cache in the executable path (`get_tick` always calls live `symbol_info_tick`).

## A2. Secondary finding (F2) — offset off the quantization grid

`server_utc_offset` only accepts an offset that is an **exact multiple of 15 minutes** inside the 60s bar window (`mt5_adapter.py:1551-1556`). With the current true offset ≈ +2h59m, the window `[bar_time−now, bar_time+60−now)` sits ≈ `[10710, 10830)`; the only nearby grid point, 10800 (+3h), falls inside that window **only part of the minute** (when `lo > 10740`) and outside it otherwise — so the measurement is marginal/failing and the session sits on `assumed-utc-fallback` (which is exactly the basis the failing order used). Important: **this does not cause the 409 and it does not admit stale quotes** — the fallback delegates to the same shared contract. Its real effects are: `event_time` cannot be normalized (observations recorded on the fallback basis) and every quote takes the raw-stamp path. It is a latent fragility, not the cause of the refusal.

## B. Live probe — `scripts/probe_quote_forensics.py` (committed, read-only)

The probe is committed on this branch at **`scripts/probe_quote_forensics.py`**. It prints exactly the ten required facts:

1. `time.time()` in UTC (epoch + ISO)
2. `terminal_info().time`
3. `symbol_info_tick("XAUUSD@").time`
4. `symbol_info_tick("XAUUSD@").time_msc`
5. `copy_rates_from_pos("XAUUSD@", M1, 0, 1)[0]["time"]`
6. latest tick vs current M1 bar (bar open − tick epoch; positive = tick older)
7. terminal time − UTC now
8. tick `bid`, `ask`, `last`, `volume`
9. `terminal_info()` / connection status
10. final classification `FRESH / STALE / NO_TICK` (gate constants imported from `qts.lifecycle.demo_gate` — nothing hard-coded)

Run it on the Windows machine with MetaTrader 5 open and signed in to WMMarkets-Demo — ideally while the stale-quote state is showing:

```bat
cd /d C:\path\to\Trading-System
.venv\Scripts\python.exe scripts\probe_quote_forensics.py
```

How to read it:
- `tick.time` advances between repeated runs and item 6 ≈ 0 → the feed IS ticking; the 409 was a prepare-vs-order timing gap (the feed had already stopped by order time).
- `tick.time` frozen across runs and item 6 large positive → the last tick is genuinely old: either market/session closed (check broker session hours for gold) or the terminal is not streaming ticks for XAUUSD@.
- Item 7 gives the true server offset from MT5 itself — compare against the 15-minute grid {9900s, 10800s} (see F2).

## C. Verdict

1. **There is no timestamp/timezone misreading bug in the freshness path.** The shared contract correctly proved, on MT5's own consistent server basis, that the last XAUUSD@ tick was ~2h31m older than the forming M1 bar. The 409 is the correct, fail-closed outcome: QTS refuses to trade on a 2.5-hour-old quote. This is exactly the behavior the gate exists to enforce.
2. **`prepare` = 200 is not a contradiction**: prepare enforces the same fresh-quote contract and passed *at that moment*; the feed stopped ticking between prepare and the order.
3. **The open question is not in QTS code but at the market/terminal level**: why does MT5 report a ~2.5h-old last tick for XAUUSD@ (current M1 bars exist while the last tick is old). The probe in section B distinguishes market-closed vs non-streaming symbol vs transient gap.

## D. Proposed minimal fix (NOT implemented — awaiting probe output)

Guided by the constraints (no threshold change, no gate bypass, no stale prices, no hard-coded offset):

1. **No change to freshness logic.** Nothing there is broken; loosening it would be wrong.
2. **Operational, based on probe result:**
   - Market/session closed → QTS's refusal is the correct end state. Optional *wording-only* improvement: surface "market appears closed — last tick was HH:MM (Xh ago)" in the guide/trading page so the user isn't left guessing. No gate change.
   - Market open but `symbol_info_tick` frozen → terminal-level remedy (ensure XAUUSD@ is subscribed/streaming in Market Watch, reopen chart, restart terminal). If it persists, that is an MT5 API/terminal anomaly to report upstream — the gate must not paper over it.
3. **Separate, secondary, only if the probe confirms a persistently off-grid offset:** relax `server_utc_offset`'s quantization from exact 15-minute multiples to a finer *measured* grid (e.g. 1 minute), keeping the bar-window constraint and never hard-coding a value. This restores `event_time` normalization for this broker (cleaner observatory timestamps, measured-basis instead of permanent fallback). It is independent of the 409 — it would neither have caused nor prevented the refusal — and would need its own regression tests (offset grid, FS-c42bbd retention contract, adversarial mt5 boundary suite) before acceptance.

**Nothing has been implemented. Awaiting the Windows probe output.**
