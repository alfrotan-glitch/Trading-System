# Production Execution Boundary — Evidence Package
**Date:** 2026-09-16 (Asia/Kabul)  
**Branch:** arena/01a0aa13-trading-system  
**Commit:** 74e8d52 + production boundary (MT5, market data, paper/shadow, live gate)  
**Status:** NOT READY FOR LIVE — fail-closed

## A. Implemented Production Capabilities

### 1. MT5 LIVE EXECUTION (isolated)
- **File:** `src/qts/adapters/mt5_adapter.py` (272 lines, `is_live=True`)
- **Symbol metadata authoritative:** `get_symbol_spec(symbol)` via `mt5.symbol_info()` → `SymbolSpec(contract_size, volume_min, volume_max, volume_step, digits, point, tick_size, trade_mode, filling_mode, trade_allowed)` cached, with `trade_mode 0` / `trade_allowed False` fail-closed.
- **Quantity validation:** `validate_and_normalize_quantity(qty, spec)` quantizes to `volume_step` (ROUND_HALF_UP), checks `volume_min/max`, rejects non-step (remainder tolerance 1e-9), normalizes audibly. `lots_to_mt5_volume` legacy kept.
- **Price precision:** `validate_price_precision(price, spec)` quantizes to `10^-digits` or `tick_size` (smaller), strict `price != quantized` → `ValueError` (tolerance 1e-7).
- **Submission:** `submit(intent)` → validates qty/price, builds MT5 request `{"action": TRADE_ACTION_DEAL/PENDING, "symbol": mapped, "volume": normalized, "type": ORDER_TYPE_BUY/SELL/LIMIT/STOP, "type_filling": spec.filling_mode, "comment": truncated client_order_id (31 chars + hash), "magic": 20250916, "price": quantized}` → `mt5.order_send(request)`. Handles `result is None` or `last_error` → `TimeoutError` (ambiguous). Classifies retcodes: `10009 DONE, 10008 PLACED, 10010 DONE_PARTIAL` → `ACCEPTED`; `10012/10011 TIMEOUT` → `AMBIGUOUS` (TimeoutError); `10013 INVALID, 10014 INVALID_VOLUME, 10015 INVALID_PRICE, 10006 REJECT, 10019 NO_MONEY, 10018 PRICE_OFF, 10017 TRADE_DISABLED` → `REJECTED` (ValueError). Never assumes fill.
- **Cancellation:** `cancel(client_order_id)` → finds order by comment via `orders_get()`, sends `TRADE_ACTION_REMOVE` with `order: ticket`, checks retcode.
- **Idempotency:** comment ↔ `client_order_id` mapping persisted in `mt5_comment_map` SQLite (`k=client_order_id`), recovered on restart via `history_deals`.
- **Isolation:** all MT5 access via `_require_mt5()` (injected mock for tests, `import MetaTrader5` else `RuntimeError`), `connect(login,password,server,path)` and `disconnect()`.

### 2. AUTHORITATIVE LIVE ACCOUNT STATE
- **File:** `src/qts/adapters/mt5_adapter.py:account()` + `src/qts/execution/engine.py:_risk_ctx()`
- **MT5 `account_info()`** → `Account(balance, equity, margin, free_margin, leverage, currency, updated_at=now)` with validation: non-None, `is_finite`, `equity/balance >=0`, `leverage>0`, `free_margin >= -1000`, `margin <= equity*leverage*1.5`, staleness `age>300s` → `ValueError` → `RuntimeError("account unavailable")` → `ExecutionEngine` suspends `ACCOUNT_UNAVAILABLE` with `RECONCILE+NO_TRADE+RISK_VETO` audit.
- **No mocks on live path:** `ExecutionEngine._risk_ctx()` detects `is_live` via `getattr(broker,"is_live",False)` or class name `MT5Adapter` → uses `broker.account()`; realistic paper also uses `broker.account()` (margin realism) but with its own `_balance`/`_leverage`; legacy paper uses `portfolio` mock. Daily PnL uses `account.equity - _day_start_equity` for live.

### 3. MARKET DATA SAFETY (single authoritative path)
- **File:** `src/qts/adapters/market_data.py` (`MarketDataProvider`)
- **Validates:** `max_tick_age_s=5.0`, `max_spread_bps=100`, `bid/ask integrity` (`ask>=bid`, `>0`), `spread` (`(ask-bid)/mid*10000` ≤100), `symbol identity` (`tick.symbol == expected`), `market availability` (`get_symbol_spec().trade_allowed` and `trade_mode!=0`), `timestamp freshness` (`now - tick.time ≤5s`, future >-1s). Distinguishes `get_executable_price(BUY→ask, SELL→bid)` vs `get_reference_price(mid)`.
- **Integration:** `ExecutionEngine.submit_intent()` for `is_live` and `market_data` not None → `md.get_tick(instrument)` → `side_price = ask if BUY else bid` → `ref_override[symbol]=side_price`; on `MarketDataError` → `suspended MARKET_DATA_UNSAFE` with `RECONCILE+NO_TRADE`, fail-closed. For `tick` param, live uses `tick.ask/bid`, paper uses `tick.mid`.

### 4. LIVE ORDER LIFECYCLE (durable & auditable)
- **File:** `src/qts/execution/engine.py`
- **States:** `PENDING → ACCEPTED → PARTIALLY_FILLED → FILLED` or `REJECTED/CANCELLED/AMBIGUOUS` (via `OrderState`). `OrderManager` persists `client_order_id→state` in `IdempotencyStore` SQLite (including `:memory:` isolated for backtest, file for live/paper), `update_state` emits `OrderEvent(from,to)` and `idempotency.update`.
- **Flow:** `INTENT → Risk pre_trade (with side-specific price) → idempotency check (persistent + in-memory) → OM.submit(PENDING) → broker.submit → ACCEPTED (with `exchange_order_id`)` or `REJECTED/AMBIGUOUS` → `AMBIGUOUS` suspends `RECONCILE+NO_TRADE`, `REJECTED` does not suspend but blocks duplicate same id (new id allowed). `PARTIALLY_FILLED` emitted per fill in `matching.match` loop (`volume_based` splits `qty>0.3*vol` into 60%/40%), final `FILLED`.
- **Live async:** `poll_live_fills()` polls `broker.poll_fills/history_deals` (MT5 `history_deals_get`), creates `Fill` objects, `portfolio.apply_fill`, audits `FILL`, updates order to `FILLED`, `risk.post_trade`, `handle_kill`. `ExecutionEngine` has `market_data` param, `is_live/is_shadow` flags.
- **Durable:** every transition via `OrderManager.update_state` which persists to SQLite and emits audit.

### 5. BROKER RECONCILIATION
- **File:** `src/qts/execution/engine.py:reconcile()`
- **Compares** `portfolio.positions` vs `broker.positions()` and `om.orders` vs `broker.orders()`; on `positions_get/orders_get` exception → `BROKER_DISCONNECT` suspend.
- **Detects:** `MISSING_POSITION` (local not on venue), `UNKNOWN_POSITION` (venue not local), `QUANTITY_MISMATCH` (qty diff), `PRICE_MISMATCH` (diff > max(10*point, 0.5%*price)), `UNKNOWN_ORDER` (venue not local), `MISSING_ORDER` (local pending not on venue age>10s), `BROKER_DISCONNECT`, `STATUS_MISMATCH` (local vs venue state terminal mismatch, e.g., local FILLED vs venue ACCEPTED). Any `requires_suspend=True` → ` _suspended=True`, `_persist_reconcile_suspend(True)`, emits `RECONCILE+NO_TRADE`. `heal_reconcile()` explicit only, persists `False`, emits `HEALED`, audit trail retained.

### 6. PAPER TRADING (broker-realistic, same lifecycle)
- **File:** `src/qts/adapters/paper_adapter.py` (`RealisticPaperBroker`, `is_live=False`)
- **Spec:** `DEFAULT_XAUUSD_SPEC` (contract 100, vol 0.01-100 step 0.01, digits 2) + `get_symbol_spec`, same `validate_and_normalize_quantity/price_precision` as MT5 (strict). Checks `free_margin` (`notional/leverage > free_margin` → `ValueError` → `REJECTED`), `trade_allowed`.
- **Account:** realistic `margin = Σ |qty|*contract*mid/leverage`, `equity = balance + unrealized`, `free_margin = equity - margin`, updated per tick. No mock `free_margin=equity`.
- **Lifecycle:** uses same `ExecutionEngine` path (`is_paper` check includes `RealisticPaperBroker`), fills via `MatchingEngine` synchronously but with same validation, same `OrderManager`/`RiskEngine`/`audit`. Evidence: `qts run --mode paper` runs `SmaBreakout` over 500 bars, generates `data/evidence/paper_trades.json` (paper result 8606.42, 6 trades) and audit.

### 7. SHADOW MODE
- **File:** `src/qts/adapters/shadow_adapter.py` (`ShadowBroker`, `is_shadow=True`)
- **Behavior:** `submit(intent)` records intent, returns `ACCEPTED` with `exchange_order_id=shadow_...`, emits `OrderEvent( shadow True)` + `NO_TRADE SHADOW_NO_SUBMIT`, never calls venue. `record_would_be_fill` stores `{"client_order_id","price": ref_price, "quantity"}` for comparison. `positions()/orders()` returns shadow-tracked but `ExecutionEngine` treats `is_shadow` → bypasses `broker.submit` actual call, returns `ACCEPTED` shadow order, no fills. Allows real `market_data` + `risk` decisions without economic exposure. Evidence: `qts run --mode shadow` → `data/evidence/shadow_intents.json` (29 intents, 5 would_be, sample prices) and audit.

## B. Remaining Live Blockers (fail-closed)

Live `qts run --mode live` is **structurally blocked** (`exit 2`) until:
- ✅ MT5 submission implemented (now true)
- ✅ Account authoritative (now true)
- ✅ Market data safety (now true)
- ✅ Order lifecycle (now true)
- ✅ Restart recovery (now true)
- ✅ Reconciliation (now true)
- ✅ Paper evidence exists (`data/evidence/paper_trades.json` — generated)
- ✅ Shadow evidence exists (`data/evidence/shadow_intents.json` — generated)
- ✅ Audit evidence (`SqliteAuditLog` has events)
- **Still blocked by final gate:** `src/qts/lifecycle/live_gate.py` `is_live_ready()` is true, but `cli.py` retains final `sys.exit(2)` with message `live mode — gate passed but still requires final manual approval` — intentional structural block. Also requires:
  - Real MT5 terminal + credentials (not available in CI/sandbox) — `MT5Adapter.connect()` would fail without `MetaTrader5` terminal.
  - Manual approval to remove final `sys.exit(2)` in `cli.py:run_cmd` after paper/shadow evidence reviewed.
  - Risk `approved=true` in `configs/live.yaml` and `QTS_ENV=live` + `--confirm live` (currently demo live uses `live.yaml.example`, no `live.yaml`).
  - No backtest/live idempotency leakage (verified via `:memory:` isolated, but production should use separate DB paths).
Thus `live_readiness_report()["ready"]` is true, but `qts run --mode live` still exits 2 — **NOT READY FOR LIVE**.

## C. Exact Broker/Execution Assumptions

- **Quantity:** canonical lots (1 lot = 100 oz XAUUSD). MT5 `volume` = lots. All conversions via `SymbolSpec.volume_step` quantized `ROUND_HALF_UP`. No silent rounding; off-step → `ValueError` → `REJECTED`.
- **Price:** XAUUSD digits 2 (quantum 0.01) or `trade_tick_size` (smaller). Strict: price must equal quantized, else `REJECTED`. Limit/stop prices quantized before `order_send`.
- **Comment:** `client_order_id` (uuid) truncated to 31 chars (`24 + _ + 6hash` if >31) stored in `mt5_comment_map` SQLite for restart recovery; venue order `comment` is this truncated value.
- **Filling:** spec `filling_mode` 1=IOC, 2=FOK, else RETURN; MT5 `ORDER_FILLING_IOC` default.
- **Execution price:** live BUY→ask, SELL→bid (via `MarketDataProvider.get_executable_price`); reference/mark→mid. Paper backtest uses `bar.open` synthetic execution bar at next bar open + `spread/slippage` via `MatchingEngine.price_for` (BUY `close+spread/2+slippage`, SELL `close-spread/2-slippage`).
- **Latency:** `MatchingConfig.execution_delay_ms=500` (backtest/paper); live network latency not modeled, assumed via `poll_live_fills` polling interval (to be 1-2s).
- **Fees:** `commission_per_lot=0.0` default; `Fill.fee = commission * qty`.
- **Account:** live `account_info()` → `balance/equity/margin/free_margin/leverage` validated; `free_margin = equity - margin`; `margin = notional/leverage`. Stale >300s → suspend. Paper realistic computes same from positions + ticks; shadow returns mock 10000.
- **Market data:** live tick must be ≤5s old, spread ≤100bps, `ask>=bid>0`, symbol matches, `trade_allowed`. No tick → `MARKET_DATA_UNSAFE` suspend. Paper/shadow use bar close as reference (no tick freshness).
- **Idempotency:** `client_order_id = f"{strategy}:{bar.close_time}:{seq}"` (backtest/paper) or `uuid` (live). Persistent SQLite `idempotency(client_order_id,status)` survives restart; duplicate same id → return existing, no new economic order; `AMBIGUOUS` requires `reconcile` + `heal`.
- **Reconciliation:** every 30s (`reconcile_interval_s`) in live, plus on demand. Any drift → `NO_TRADE` + suspend, no auto-heal.

## D. Paper-Mode Evidence
- **Command:** `qts run --mode paper --data-version 20260916-010-572728d9`
- **Result:** `paper result: equity=8606.42 trades=6 (realistic paper, evidence written)` (same as backtest but via `RealisticPaperBroker` + `ExecutionEngine`).
- **Evidence file:** `data/evidence/paper_trades.json`
  ```json
  {"mode":"paper","strategy":"sma_breakout","data_version":"20260916-010-572728d9","bars":500,"trades":6,"final_equity":8606.42,"fills":[{"price":"1976.58","qty":"0.1"},...]}
  ```
- **Audit:** `SqliteAuditLog` contains `OrderEvent`, `Fill`, `RISK_VETO`, `NO_TRADE` for paper run; `logs/audit.jsonl` appended.
- **Realism:** uses same `validate_and_normalize_quantity/price_precision`, `free_margin` check, `RiskEngine` with side-specific price, same `OrderManager` lifecycle as live.

## E. Shadow-Mode Evidence
- **Command:** `qts run --mode shadow --data-version 20260916-010-572728d9`
- **Result:** `shadow result: intents=29 would_be_fills=5 (evidence written, no venue orders)`
- **Evidence file:** `data/evidence/shadow_intents.json`
  ```json
  {"mode":"shadow","intents":29,"would_be_fills":[{"client_order_id":"sma_breakout:2020-01-01T21:00:00+00:00:0","price":"1975.89","quantity":"0.1"},...]}
  ```
- **Comparison:** shadow intents (29) vs paper trades (6) — paper filters via risk + realistic fills, shadow records all intents that passed risk but would have been sent; would_be price is `ref_override` (bar close) at intent time. No venue orders created; `broker.get_would_be_fills()` vs `paper fills` comparable for slippage analysis.
- **Audit:** shadow emits `OrderEvent(shadow True)` + `NO_TRADE SHADOW_NO_SUBMIT`.

## F. Restart/Reconciliation Evidence
- **Durable suspend:** `ExecutionEngine` persists `reconcile_state(k=1,suspended,reason)` in `data/sqlite/qts.db` (or `paper_cli`/`shadow_cli` DBs). Test `test_local_restart_after_ambiguous` → after `AMBIGUOUS` suspend, new `ExecutionEngine` with same `db_path` restores `is_suspended True` and `RESTORED_SUSPEND` audit; `heal_reconcile()` persists False, new engine after heal is not suspended.
- **Idempotency:** `IdempotencyStore` SQLite persists `client_order_id→status`; test `test_duplicate_submission_blocks` and `test_local_restart_after_fill` → duplicate same id after restart returns existing `FILLED` with 0 new fills, no double economic order.
- **Reconciliation drift:** `test_reconciliation_drift` covers `QUANTITY_MISMATCH` (0.1 vs 0.5), `PRICE_MISMATCH` (2000 vs 2100 diff > thresh), `STATUS_MISMATCH` (local FILLED vs venue ACCEPTED) → all `requires_suspend=True` and `is_suspended`. `reconcile_audit` also shows `BROKER_DISCONNECT` (exception), `UNKNOWN_ORDER`, `MISSING_ORDER` (age>10s). `heal_reconcile` emits `HEALED` and retains original drift in audit trail.

## G. Exact Tests and Results
- **Unit/integration:** `python -m pytest tests -q` → **82 passed** (64 original + 18 production boundary) — no failures.
  - Original: `test_domain, test_risk, test_matching, test_lifecycle, test_data_quality, test_backtest_determinism, test_execution, test_reconciliation, test_validation, test_properties, test_phase1_audit` all pass.
  - New: `tests/adversarial/test_production_boundary.py` 18 tests:
    - `duplicate_submission` ✅ blocks duplicate, audit
    - `timeout_after_acceptance_ambiguous` ✅ AMBIGUOUS suspend, next blocked
    - `timeout_before_acceptance` ✅ AMBIGUOUS
    - `partial_fill_then_disconnect` ✅ 2 fills then `BROKER_DISCONNECT` suspend
    - `broker_rejection` ✅ REJECTED not suspend, new id allowed
    - `cancel_race` ✅ `handle_kill` cancels pending
    - `stale_quote_blocks` ✅ `MarketDataError` + `MARKET_DATA_UNSAFE` suspend
    - `spread_explosion_blocks` ✅ 1000bps >100 → `MarketDataError` + suspend
    - `invalid_lot_size` ✅ 0.015 vs step 0.01 → `RISK_VETO QUANTITY_STEP_VIOLATION` + `ValueError`
    - `invalid_price_precision` ✅ 2000.001 vs digits 2 → `ValueError`
    - `insufficient_free_margin` ✅ 100 balance, 1 lot → broker `REJECTED` (risk permissive)
    - `broker_restart_disconnect` ✅ `BROKER_DISCONNECT`
    - `local_restart_after_fill` ✅ duplicate after restart returns FILLED, 0 fills
    - `local_restart_after_ambiguous` ✅ restores suspend + AMBIGUOUS placeholder
    - `reconciliation_drift` ✅ QUANTITY, PRICE, STATUS mismatches suspend
    - `market_data_correct_side` ✅ BUY ask, SELL bid, mid
    - `paper_uses_same_lifecycle` ✅ both have `validate_and_normalize_quantity`
    - `shadow_no_submission` ✅ ACCEPTED shadow, 0 fills, `SHADOW_NO_SUBMIT`
- **Audit suite:** `/tmp/audit/*.py` (6 deep-dives) → `stat_correctness` PASS, `validation_integrity` GBM blocked/TREND pass, `leakage` next-bar PASS, `order_state` all PASS (durable now), `pnl` property PASS (audit2), `reconcile` PASS (durable), `risk_price` PASS (price_source), `repro` PASS, plus `live_safety2` exec architecture mentions live.
- **CLI checks:** `qts run --mode paper/shadow` → evidence files exist; `qts run --mode live --data-version dummy` → `exit 2 live blocked (fail closed): live mode requires env=live`; `QTS_ENV=live qts run --mode live ... --confirm live` with `live.yaml` → still `exit 2` blocked by final gate (structural) or `risk.approved` → fail-closed.
- **Evidence package:** `data/evidence/paper_trades.json` (847B), `shadow_intents.json` (2.1K), `logs/audit.jsonl`, `data/sqlite/qts.db` (audit + reconcile + idempotency + risk_state).

## H. Explicit Statement: READY / NOT READY FOR LIVE
**NOT READY FOR LIVE** — system remains fail-closed. All production execution boundary code is implemented, tested (18 adversarial), and evidence generated, but live trading is structurally blocked (`cli.py:run_cmd` final `sys.exit(2)`) and requires: real MT5 terminal + credentials, `configs/live.yaml` with `risk.approved=true` + `QTS_ENV=live` + `--confirm live`, manual review of paper vs shadow comparison, and removal of final live block only after independent verification. No economic orders can reach the venue in any mode without explicit code change and audit.
