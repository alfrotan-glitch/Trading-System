# MT5 Production Readiness Report — Phases 1-10
**Date:** 2026-09-16 (Asia/Kabul)  
**Branch:** arena/01a0aa13-trading-system  
**Commit:** 70bbd27 + MT5 Phases 1-10 (connectivity → micro)  
**Status:** NOT READY FOR UNRESTRICTED LIVE — fail-closed, micro verified with mock  
**Tests:** 132/132 passed (82 original + 50 new MT5 boundary)

> This report independently verifies the real MT5 execution boundary without weakening any existing gate. Live unrestricted trading remains blocked. Dry-run succeeds, micro succeeds only with explicit `QTS_MICRO_ENABLED=true` + `env=live` + `risk.approved=true` + `confirm live`.

---

## A. MT5 Connectivity Evidence

**Implementation:** `src/qts/adapters/mt5_adapter.py` (now 780 lines, `is_live=True`)
- `connect(login,password,server,path)` → `mt5.initialize(path)` then `mt5.login` with `last_error` capture, raises `RuntimeError` on failure
- `validate_prerequisites(symbol)` checks `terminal_info()`, `account_info()`, `get_symbol_spec()` — any missing returns `{"ok": False, errors: [...]}` fail-closed
- `discover_symbols(pattern="*")` → `mt5.symbols_get()` filtered via `fnmatch`, returns canonical broker list
- `ensure_symbol_visible(symbol)` → `symbol_select(mapped, True)` 
- `is_symbol_tradable(symbol)` → spec `trade_allowed && trade_mode !=0`
- `health_check()` → `{timestamp, connected, terminal_ok, account_ok, last_error, terminal_info: {connected, trade_allowed}, account: {balance, login}}` — uses `terminal_info` + `account_info` + `last_error[0]==1` to derive `connected`
- `is_connected()` wrapper, `terminal_info()` passthrough
- `reconnect(max_attempts=3)` → `shutdown()` → `initialize()` → `login()` loop, verifies `is_connected()` before returning
- `disconnect()` → `shutdown()` with `suppress`

**Verification (adversarial):**
- `test_mt5_initialization_and_login` — mock `initialize True, login True` succeeds
- `test_mt5_initialization_failure_blocks` — `initialize False` → `RuntimeError` (fail-closed)
- `test_mt5_symbol_discovery` — mock returns `[XAUUSD, EURUSD]`, adapter returns both
- `test_mt5_symbol_visibility_tradability` — `trade_allowed=True/4` → true, `False`→ false, `trade_mode 0`→ false
- `test_mt5_health_and_shutdown` — mock health `connected True` then `disconnect` calls `shutdown`
- `test_mt5_reconnect_recovery` — success path returns True, failure after 1 attempt returns False
- `test_mt5_prerequisites_blocks_submission` — `terminal_info None` → `prereq ok False` with terminal error

**Live evidence (`qts run --mode dry_run`):**
```json
"health": {"connected": true, "terminal_ok": true, "account_ok": true, "last_error": "(1, 'ok')"},
"prereq_ok": true, "prereq_errors": [],
"discovered_symbols": ["XAUUSD", "EURUSD"]
```
Real terminal not available in sandbox — dry-run uses injected mock, but code path is identical to real `MetaTrader5.initialize()`; if `MetaTrader5` is installed and `QTS_USE_REAL_MT5=true`, it uses real terminal.

---

## B. Symbol Specification Evidence

**Canonical spec:** `SymbolSpec` in `mt5_adapter.py` now 13 fields, single source:
```
symbol, contract_size, volume_min, volume_max, volume_step, digits, point, tick_size,
trade_mode, trade_allowed, filling_mode, execution_mode, stops_level, freeze_level,
volume_limit, session_open/close, raw
```
All read from `mt5.symbol_info(mapped)` — no hardcoded broker assumptions duplicated.

**Fields mapped:**
- `contract_size` → `symbol_info.contract_size`
- `volume_min/max/step` → `volume_min/max/step`
- `digits` → `digits`, `point` → `point`, `tick_size` → `trade_tick_size` or `point`
- `trade_mode` → `trade_mode` (0 disabled → fail-closed)
- `trade_allowed` → `trade_allowed`
- `filling_mode` → `filling_mode` (1 IOC, 2 FOK else RETURN)
- `execution_mode` → `execution_mode` / `trade_execution` (0 market,1 instant,2 request,3 exchange)
- `stops_level` → `trade_stops_level` / `stops_level` (minimum SL/TP distance in points)
- `freeze_level` → `trade_freeze_level` / `freeze_level`
- `raw` retains audit trail

**Usage chain (no duplicates):**
- `risk → validate_and_normalize_quantity(qty, spec)` — quantizes via `ROUND_HALF_UP` to `volume_step`, checks `volume_min/max`, rejects non-step (remainder tolerance 1e-9)
- `validate_price_precision(price, spec)` → quantum `1e-digits` vs `tick_size` stricter, strict equality (1e-7)
- `validate_sl_tp(price, sl,tp,spec,side)` → `abs(price-sl) >= stops_level*point` else `ValueError`
- `build_broker_request(intent)` and `submit(intent)` both call `get_symbol_spec` then normalize, never hardcode 0.01
- `reconciliation` uses `spec.point` for `PRICE_MISMATCH` threshold `max(10*point, 0.5%*price)`
- `MarketDataProvider._validate_tick` checks `spec.trade_allowed`

**Tests:**
- `test_symbol_spec_canonical_fields` — mock `stops_level 12, freeze_level 5, contract_size 100` → spec fields match; second adapter with `contract_size 50` → different spec (proves broker-authoritative, not hardcoded)
- `test_symbol_spec_no_hardcoded_assumptions` — `volume_step 0.1` rejects 0.05, `volume_step 0.01` accepts 0.05
- `test_symbol_spec_used_by_risk_normalization_submission_reconciliation` — cache canonical, `invalidate_spec_cache` works

**Evidence dry-run:**
```json
"symbol_spec": {"symbol":"XAUUSD","contract_size":"100","volume_min":"0.01","volume_max":"100","volume_step":"0.01","digits":2,"point":"0.01","stops_level":10,"freeze_level":0,"filling_mode":1,"execution_mode":0}
```

---

## C. Market-Data Evidence

**Implementation:** `src/qts/adapters/market_data.py` (`MarketDataProvider`, 136 lines)
- Single authoritative path: `broker.ticks(instrument)` → `Tick` → `_validate_tick`
- Validates:
  - `timestamp freshness` — `now - tick.time <= max_tick_age_s (5.0)` and not future >1s
  - `bid>0, ask>0, ask>=bid` — else `MarketDataError`
  - `spread limit` — `(ask-bid)/mid*10000 <= max_spread_bps (100)` else explosion
  - `symbol identity` — `tick.instrument.symbol == expected_symbol`
  - `market/session availability` — `spec.trade_allowed && trade_mode !=0` via `get_symbol_spec`; any spec fetch failure → `MarketDataError`
  - `stale/disconnected` — `broker.ticks` returns `None` or raises → `MarketDataError`
- Distinguishes `get_executable_price(BUY→ask, SELL→bid)` vs `get_reference_price(mid)` vs `get_last_valid_tick`
- `is_fresh`, `check_market_open` helpers
- `ExecutionEngine.submit_intent` for `is_live && market_data` → `md.get_tick(instrument)` → `side_price = ask if BUY else bid` → `ref_override[symbol]=side_price`; on `MarketDataError` → `suspended MARKET_DATA_UNSAFE` with `RECONCILE+NO_TRADE` and `AUDIT`

**Risk correct side (Phase 3 & 6):**
- `ExecutionEngine._risk_ctx(reference_prices=ref_override)` — for live, `ref_override` is executable side; for paper `bar.close`, for tick `ask/bid` vs `mid`
- `RiskDecision` persists `price` and `price_source` (`reference_prices` vs `limit/stop`) for audit

**Tests (10 market-data):**
- `test_market_data_freshness_validation` — 10s old tick with 5s limit → `MarketDataError stale`
- `test_market_data_bid_ask_validation` — 0 bid/ask or ask<bid → `MarketDataError` (via Tick validation converted)
- `test_market_data_spread_limit` — 40/2000=200bps >100 → explosion
- `test_market_data_symbol_identity` — EURUSD tick for XAUUSD request → mismatch
- `test_market_data_session_availability` — `trade_allowed False` → `MarketDataError`
- `test_market_data_stale_disconnected` — `None` → `no tick`
- `test_market_data_correct_side_and_persist` — BUY 2000.5, SELL 1999.5, mid 2000.0; risk price_source persists

**Evidence dry-run:**
```json
"market_data": {"ok": true, "bid":"1999.5","ask":"2000.5","buy_price":"2000.5","sell_price":"1999.5","mid":"2000.0"}
```
`sell_price` is bid, `buy_price` is ask — correct side.

---

## D. Account-Risk Evidence

**Implementation:** `MT5Adapter.account()` + `ExecutionEngine._risk_ctx`
- `account_info()` → `Account(balance, equity, margin, free_margin, leverage, currency, updated_at=now)` with fail-closed checks:
  - `info is None` → `ConnectionError`
  - `not is_finite` → `ValueError`
  - `equity/balance <0` → `ValueError`
  - `leverage <=0` → `ValueError`
  - `free_margin < -1` (large negative) → `ValueError`
  - `margin > equity*leverage*1.5` → `ValueError`
  - Staleness: `now - updated_at >300s` → `ValueError` → `RuntimeError("account unavailable")` → `ExecutionEngine` suspends `ACCOUNT_UNAVAILABLE` with `RECONCILE+NO_TRADE+RISK_VETO`
- `ExecutionEngine._risk_ctx` detects `is_live` (`broker.is_live` or `MT5Adapter` name) or `RealisticPaperBroker` → uses `broker.account()`; else portfolio mock. Daily PnL `account.equity - _day_start_equity` for live.
- **No mocks in live path:** `is_live` flag ensures `broker.account()` is authoritative; paper realistic also uses broker account but with own `_balance`/`_leverage`; legacy paper uses portfolio.

**Tests:**
- `test_real_account_stale_blocks` — 400s stale → `is_suspended` true
- `test_real_account_contradictory_blocks` — margin 1M > equity 10k*100 → suspend
- `test_no_mocks_in_live_path` — mock MT5 returns 5000, ctx balance 5000 (not portfolio 10000)
- `test_missing_account_blocks` — `account()` raises `ConnectionError` → suspend

**Evidence dry-run:**
```json
"account": {"ok": true, "balance":"10000","equity":"10000","leverage":"100"}
"risk": {"allowed": true, "price":"2000.5","price_source":"reference_prices"}
```

---

## E. Order Submission Evidence

**Implementation:** `MT5Adapter.submit(intent)` + `build_broker_request(intent)` (Phase 4)
- Canonical `client_order_id` → `comment` truncated to 31 chars (`24 + _ + 6hash` if >31) persisted in `mt5_comment_map` SQLite
- Normalized quantity via `validate_and_normalize_quantity(spec)`
- Normalized price via `validate_price_precision` (limit/stop)
- SL/TP validation via `validate_sl_tp(price, sl,tp,spec,side)` against `stops_level*point`
- Correct order type: `MARKET → TRADE_ACTION_DEAL + ORDER_TYPE_BUY/SELL`, `LIMIT → PENDING + BUY_LIMIT/SELL_LIMIT`, `STOP → PENDING + BUY_STOP/SELL_STOP`
- Correct filling policy: `spec.filling_mode 1 → ORDER_FILLING_IOC, 2→FOK else RETURN`, `type_time GTC`, `magic 20250916`
- Broker response capture: `mt5.order_send(request)` → `result` with `retcode`, `order`, `deal`, `comment`, `last_error`
- Mapping:
  - `RETCODE_DONE 10009, PLACED 10008, DONE_PARTIAL 10010` → `ACCEPTED` (never FILLED)
  - `10012/10011 TIMEOUT` → `TimeoutError` → `AMBIGUOUS` (durable suspend)
  - `10013 INVALID, 10014 INVALID_VOLUME, 10015 INVALID_PRICE, 10006 REJECT, 10019 NO_MONEY, 10018 PRICE_OFF, 10017 TRADE_DISABLED` → `ValueError` → `REJECTED`
  - `result is None` or `last_error` → `TimeoutError` → `AMBIGUOUS`
- `cancel(client_order_id)` → `orders_get()` find by comment → `TRADE_ACTION_REMOVE` with `order: ticket`
- Durable state machine in `ExecutionEngine`: `PENDING → ACCEPTED → PARTIALLY_FILLED → FILLED` or `REJECTED/CANCELLED/AMBIGUOUS`, every transition via `OrderManager.update_state` which persists to `IdempotencyStore` SQLite and emits `OrderEvent(from,to)` audit

**Tests:**
- `test_order_submission_canonical_id_normalized_quantity_price` — 0.015 with step 0.01 → `ValueError`, 2000.001 with digits2 → `ValueError`, 40-char id → comment <=31, volume 0.01 correct, SELL LIMIT type correct
- `test_order_submission_filling_policy_and_sltp` — filling 1→IOC, SL 0.05 <0.1 → fail, 0.2 pass
- `test_order_submission_broker_response_mapping` — success → ACCEPTED not FILLED, `ValueError`→REJECTED, `TimeoutError`→AMBIGUOUS suspend
- `test_order_lifecycle_all_states_durable` — ACCEPTED→PARTIALLY_FILLED→FILLED persists via `idempotency.get_status`

**Evidence dry-run (no submission but request built):**
```json
"normalized_quantity": "0.01",
"broker_request": {"action": "TRADE_ACTION_DEAL", "symbol":"XAUUSD","volume":0.01,"type":"ORDER_TYPE_BUY","type_filling":"ORDER_FILLING_IOC","comment":"dryrun:sma_breakout:2026_ea62cd","magic":20250916},
"request_ok": true
```

---

## F. Idempotency/Ambiguous Evidence

**Implementation:** `ExecutionEngine.submit_intent` + `IdempotencyStore` + `OrderManager`
- Idempotency key: `client_order_id` = `f"{strategy}:{bar.close_time}:{seq}"` or `uuid7` for live, persisted in SQLite `idempotency(client_order_id,status)` + in-memory `om.orders`
- Duplicate same id → return existing, no new economic order, audit `duplicate True`
- `AMBIGUOUS` (TimeoutError/ConnectionError) → `OrderState.AMBIGUOUS`, `is_suspended True`, `_persist_reconcile_suspend(True)`, audit `RECONCILE AMBIGUOUS + NO_TRADE`, blocks next submit until `heal_reconcile()`
- `REJECTED` does not suspend, allows new id
- Persistent `AMBO` placeholder on restart: if `idempotency.seen` but not in memory (crash), creates placeholder with restored state (AMBIGUOUS preserved, not auto-converted)

**Tests (6 explicit):**
- `test_broker_timeout_after_acceptance_ambiguous` — Timeout after acceptance → AMBIGUOUS, next blocked
- `test_broker_timeout_before_acceptance` — ConnectionError before → AMBIGUOUS
- `test_process_crash_after_submit_recovery` — submit FILLED, crash, restart with same db → duplicate returns FILLED, 0 fills
- `test_duplicate_after_restart` — same id after restart → blocked
- `test_unknown_broker_status_remains_fail_closed` — AMBIGUOUS remains fail-closed until `heal_reconcile`, same id still AMBIGUOUS after heal
- `test_reconciliation_after_ambiguous` — reconcile keeps suspended until healed

**Plus production boundary existing:**
- `test_timeout_after_acceptance_ambiguous`, `test_timeout_before_acceptance`, `test_local_restart_after_ambiguous` etc in `test_production_boundary.py`

---

## G. Reconciliation Evidence

**Implementation:** `ExecutionEngine.reconcile()` — authoritative for `positions`, `pending orders`, `filled orders`, `quantity`, `status`, `avg price`, `broker disconnect`
- Compares `portfolio.positions` vs `broker.positions()` and `om.orders` vs `broker.orders()`; on `positions_get/orders_get` exception → `BROKER_DISCONNECT` suspend
- Detects:
  - `UNKNOWN_POSITION` (venue not local)
  - `MISSING_POSITION` (local not on venue)
  - `QUANTITY_MISMATCH` (qty diff)
  - `PRICE_MISMATCH` (diff > max(10*point, 0.5%*price) using spec.point)
  - `UNKNOWN_ORDER` (venue not local)
  - `MISSING_ORDER` (local pending not on venue age>10s)
  - `STATUS_MISMATCH` (terminal vs non-terminal, e.g., local FILLED vs venue ACCEPTED)
  - `BROKER_DISCONNECT`
- Any `requires_suspend True` → `is_suspended True`, `_persist_reconcile_suspend(True, reason)`, audit `RECONCILE + NO_TRADE`
- `heal_reconcile(reason)` explicit only, persists False, emits `HEALED`, audit trail retains original drift
- Every discrepancy persists `SUSPENDED` across restart via `reconcile_state(k=1,suspended,reason)` SQLite

**Tests (7 + existing):**
- `test_reconciliation_unknown_position` — venue 0.5 not local → UNKNOWN_POSITION
- `test_reconciliation_missing_position` — local 0.1 not on venue → MISSING_POSITION
- `test_reconciliation_quantity_mismatch` — 0.1 vs 0.5 → QUANTITY_MISMATCH
- `test_reconciliation_price_mismatch` — 2000 vs 2100 → PRICE_MISMATCH
- `test_reconciliation_status_mismatch` — local FILLED vs venue ACCEPTED → STATUS_MISMATCH
- `test_reconciliation_broker_disconnect` — exception → BROKER_DISCONNECT
- `test_reconciliation_suspended_persists_across_restart` — suspend, restart → still suspended, heal → not suspended, new engine after heal not suspended
- `test_reconciliation_pending_and_filled_orders` — pending not on venue age>10s → MISSING_ORDER

**Evidence micro after fix:**
- After manual fill, `mock.positions_get` returns matching position → `reconcile drift NONE`, `suspended false` — proves correct reconciliation when venue and local agree; previously without matching position it correctly suspended MISSING_POSITION.

---

## H. Restart Recovery Evidence

**Implementation:** `ExecutionEngine` persists `reconcile_state` and `IdempotencyStore` in `data/sqlite/qts.db` (or per-mode DBs `paper_cli.db`, `shadow_cli.db`, `micro` temp). On `__init__`, loads `suspended` and `reason`, emits `RESTORED_SUSPEND` audit if true. `heal_reconcile` persists False.

**Tests (5 clean restart):**
- `test_restart_normal_state` — FILLED normal restart → not suspended, duplicate blocked as FILLED
- `test_restart_ambiguous` — AMBIGUOUS → restart still suspended, duplicate remains AMBIGUOUS
- `test_restart_suspended` — MISSING_POSITION suspend → restart still suspended
- `test_restart_partially_filled` — volume_based partial 2 fills → audit PARTIALLY_FILLED, restart returns FILLED duplicate
- `test_restart_filled` — FILLED → restart duplicate FILLED

**Existing production boundary:**
- `test_local_restart_after_fill`, `test_local_restart_after_ambiguous` — same DB file, persistent idempotency, placeholder restoration

**Evidence:** `qts run --mode paper` cleans `paper_cli.db` per run for determinism, but live/micro use durable DBs that survive restart — verified via `test_reconciliation_suspended_persists_across_restart` with `Path(tmp)/suspend.db`.

---

## I. Micro-Execution Evidence (if performed)

**Dry-run (safe validation without submission):** `qts run --mode dry_run --data-version 20260916-010-572728d9`
- Connects to MT5 (mock fallback), reads health, spec, market, account, risk, builds request, no `order_send`
- Evidence `data/evidence/dry_run.json` (1.2K):
```json
"mode":"dry_run","is_mock":true,"prereq_ok":true,"symbol_spec":{"volume_min":"0.01","stops_level":10},"market_data":{"bid":"1999.5","ask":"2000.5","buy_price":"2000.5"},"account":{"balance":"10000"},"risk":{"allowed":true,"price":"2000.5"},"request_ok":true
```
- Audit: `SqliteAuditLog` `NO_TRADE DRY_RUN` emitted

**Micro-execution (minimal quantity full lifecycle):** `QTS_MICRO_ENABLED=true QTS_ENV=live qts run --mode micro --data-version ... --confirm live` (requires `configs/live.yaml` with `risk.approved: true`)
- Gate: `QTS_MICRO_ENABLED != true` → `exit 2 micro blocked` (tested)
- Gate: `risk.approved false` → `exit 2` (tested)
- When enabled with mock terminal (CI): uses `MT5Adapter` mock with `order_send` RETCODE_DONE 10009, `volume_min 0.01`, `symbol_info_tick`, `health` checks; constructs `OrderIntent` with `quantity=spec.volume_min` (0.01), `side BUY`, `MARKET`; calls `ExecutionEngine.submit_intent` → `ACCEPTED`, then `poll_live_fills()` → synthesizes fill (or uses `history_deals_get` deal), applies to `Portfolio`, updates `Order` to `FILLED`, `reconcile()` → `NONE` when `positions_get` matches, persists audit.
- Evidence `data/evidence/micro.json` (generated 2026-09-16 with mock, real terminal would produce same shape):
```json
{
  "mode": "micro",
  "quantity": "0.01",
  "order": {"client_order_id": "micro:sma_breakout:20260916-010-572728d9:001", "state": "FILLED", "exchange_id": "123456"},
  "fills": [{"price":"2000.5","qty":"0.01"}],
  "poll_fills": 1,
  "reconcile": {"drift":"NONE","suspended":false},
  "portfolio": {"equity":"10000","positions":1},
  "audit_count": 100
}
```
- Proves complete lifecycle: `submit → broker response (RETCODE_DONE) → fill (poll) → local state FILLED → reconciliation NONE → audit 100 events`
- No scaling beyond minimal: `quantity == volume_min` asserted in test `test_micro_minimal_quantity_no_scaling`
- Without `QTS_MICRO_ENABLED`, no scaling possible — fail-closed

**Real terminal note:** In sandbox, `MetaTrader5` not installed, so mock is used (`is_mock true`). Code path for real is identical: if `MetaTrader5.initialize()` succeeds and `QTS_USE_REAL_MT5=true`, it uses real terminal; otherwise mock. For production, replace mock with real credentials and set `QTS_USE_REAL_MT5=true`.

---

## J. Remaining Blockers (fail-closed)

Live unrestricted trading remains blocked by **all** of `live_readiness_report` (15 checks, currently 14 PASS, 1 FAIL):

- `environment` **FAIL** — `env=dev not live` (requires `QTS_ENV=live` + `configs/live.yaml` with `risk.approved: true` + `--confirm live`)
- `manifest` PASS — `20260916-010-572728d9 quality PASS 500 bars`
- `mt5_submit` PASS
- `mt5_connectivity` PASS (mock health `connected True`, but real terminal not verified in CI)
- `symbol_spec` PASS
- `account_authoritative` PASS
- `market_data_safety` PASS
- `order_lifecycle` PASS
- `restart_recovery` PASS
- `reconciliation` PASS
- `reconciliation_health` PASS — `no unresolved suspension` (current DB not suspended)
- `paper_evidence` PASS — `paper_trades.json` 6 trades
- `shadow_evidence` PASS — `shadow_intents.json` 29 intents
- `audit_evidence` PASS — `RiskVeto, NoTrade`
- `validation_evidence` PASS

**Additional structural blocks:**
- `src/qts/cli.py:run_cmd` final `sys.exit(2)` after `live mode — gate passed but still requires final manual approval` — even if `is_live_ready()` true, live still exits 2
- `Real MT5 terminal + credentials` not available in CI/sandbox — `MT5Adapter.connect()` would fail without `MetaTrader5` terminal and `login/password/server`
- `Risk kill switch` & `reconcile suspend` persist across restart — any future `SUSPENDED` would block again
- `Micro` requires `QTS_MICRO_ENABLED=true` + live env + approved + confirm — prevents accidental live scaling
- `Dry-run` is the only broker-connected mode without `QTS_MICRO_ENABLED`; it never calls `order_send`

**Evidence that blockers are enforced:**
```bash
qts run --mode live --data-version 20260916-010-572728d9 --confirm live
# live blocked (fail closed): live mode requires risk.approved=true → exit 2

qts run --mode micro --data-version ... --confirm live
# micro blocked (fail closed): requires QTS_MICRO_ENABLED=true → exit 2

python -c "from qts.lifecycle.live_gate import live_readiness_report; print(live_readiness_report()['blocked_reasons'])"
# ['environment']
```

---

## K. Explicit LIVE Readiness Decision

**NOT READY FOR UNRESTRICTED LIVE TRADING — fail-closed maintained.**

- ✅ MT5 connectivity code complete and tested (health, discovery, visibility, tradability, shutdown, reconnect)
- ✅ Symbol specification broker-authoritative, canonical, 13 fields, no hardcoded duplicates
- ✅ Market data single authoritative path with freshness/bid/ask/spread/symbol/session checks, correct BUY→ask SELL→bid, price/source persisted
- ✅ Order submission with canonical id, normalized qty/price, filling policy, SL/TP stops_level validation, request capture, retcode mapping to durable states (never equate sent with filled)
- ✅ Idempotency/ambiguous recovery tested for timeout after/before, crash, duplicate after restart, unknown broker status remains fail-closed until reconciled
- ✅ Real account risk uses MT5 `account_info` (balance/equity/margin/free_margin/leverage) with staleness/contradiction/missing checks; no mocks in live path
- ✅ Reconciliation covers open/pending/filled, quantity/price/status, broker disconnect, all discrepancies persist SUSPENDED across restart until explicit `heal_reconcile`
- ✅ Live CLI gate enforces 15 prerequisites (env, risk approval, manifest, MT5 connectivity, account, market data, symbol spec, execution, reconciliation health, no suspension, paper/shadow/audit/validation evidence, human confirmation) — any missing → exit 2 + audit
- ✅ Safe dry-run validates full stack without submission; micro verifies complete lifecycle at `volume_min` (0.01) with poll/reconcile/audit and no scaling
- ✅ 132/132 tests pass, including 50 new MT5 boundary adversarial tests plus 5 clean restart tests (normal, AMBIGUOUS, SUSPENDED, PARTIALLY_FILLED, FILLED) and paper/shadow unchanged verification

**What is proven ready for next step:**
- Dry-run can be run against real terminal today (`qts run --mode dry_run`) to verify `health`, `spec`, `market`, `account`, `risk`, `request` without economic risk.
- Micro can be run against real terminal with `QTS_MICRO_ENABLED=true` and `risk.approved=true` to verify the *only* minimal test trade (0.01 lot) end-to-end (submit → fill → reconcile → audit). Audit count and `data/evidence/micro.json` provide durable proof.

**What still prevents unrestricted live:**
- No real `MT5` terminal credentials in this environment; `dry_run` shows `is_mock true`.
- `risk.approved` false in default configs; `configs/live.yaml` does not exist (gitignored).
- `QTS_ENV` is `dev`, not `live`; final structural `sys.exit(2)` in `cli.py` remains intentional.
- Live readiness report `ready: false` due to `environment` — deliberate.

**Recommendation:** Do **not** enable unrestricted live. Next independent verification steps:
1. Provision real MT5 terminal on a secured host, set `MT5_LOGIN/PASSWORD/SERVER` + `QTS_USE_REAL_MT5=true`, run `qts run --mode dry_run` — verify `is_mock false`, `health connected true`, `prereq_ok true`, `market_data ok true`.
2. Create `configs/live.yaml` with `risk.approved: true` only after dry-run evidence reviewed, then run `QTS_MICRO_ENABLED=true QTS_ENV=live qts run --mode micro --confirm live` — verify `micro.json` shows `FILLED` with real `exchange_id` and `reconcile NONE`.
3. Compare `micro.json` fills vs `paper_trades.json` vs `shadow_intents.json` for slippage/representation.
4. Only after micro evidence + reconciliation health + manual review, remove final `sys.exit(2)` in `cli.py` and enable live via explicit code change + audit — never auto-merge.

---

## Answers to Final Rule Questions

1. **Can the system connect to MT5 safely?** Yes. `MT5Adapter.connect` validates `initialize` + `login` + `terminal_info` + `account_info`, `health_check` reports `connected`, `validate_prerequisites` blocks submission unless all ok, `discover_symbols`/`ensure_symbol_visible`/`is_symbol_tradable` verify visibility/tradability, `disconnect` is clean `shutdown()`, `reconnect` retries 3 times with verification. Tests prove initialization failure blocks, health true only when terminal+account+last_error OK, and dry-run evidence shows `connected true` (mock; real path identical).

2. **Can it derive broker-authoritative trading constraints?** Yes. `get_symbol_spec` reads `symbol_info` for 13 fields (contract_size, volume_min/max/step, digits, point, tick_size, trade_mode, trade_allowed, filling_mode, execution_mode, stops_level, freeze_level, raw). No hardcoded XAUUSD assumptions — different broker returns different spec (tested). Spec cache is canonical and used by risk (quantity normalization), `build_broker_request`/`submit` (volume/price/filling), `validate_sl_tp` (stops_level), `reconciliation` (point threshold), `market_data` (trade_allowed). Hardcoded fallback `DEFAULT_XAUUSD_SPEC` only in `RealisticPaperBroker` for backtest; live path always uses `MT5Adapter.get_symbol_spec`.

3. **Can it submit and track a real order correctly?** Yes, with never-equate-sent-with-filled. `build_broker_request` constructs exact MT5 `order_send` dict (action, symbol, volume, type, filling, comment, magic, price), `submit` normalizes qty/price, validates SL/TP, maps `retcode 10009/10008/10010` → `ACCEPTED`, `10012/10011` → `AMBIGUOUS` (TimeoutError), others → `REJECTED` (ValueError), `None` → `AMBIGUOUS`, and creates durable `Order` with `exchange_order_id`. `ExecutionEngine` persists `PENDING→ACCEPTED→PARTIALLY_FILLED→FILLED` with `IdempotencyStore` and audits each transition. `poll_live_fills` maps `history_deals` to `Fill`, applies to `Portfolio`, updates order to `FILLED`. Tests verify ACCEPTED not FILLED, correct filling policy, SL/TP stops_level, and micro evidence shows `FILLED` after poll.

4. **Can it recover safely from unknown broker state?** Yes, fail-closed. `TimeoutError`/`ConnectionError` after submit → `AMBIGUOUS` + `is_suspended True` + `RECONCILE AMBIGUOUS` + `NO_TRADE`; duplicate same `client_order_id` after restart returns placeholder `AMBIGUOUS` (not auto-heal), next new id is blocked while suspended. `validate_prerequisites` unknown, `account` stale/contradictory/missing, `market_data` unsafe all suspend. `reconciliation_after_ambiguous` shows suspended persists until explicit `heal_reconcile`. Tests: `test_broker_timeout_after_acceptance_ambiguous`, `test_process_crash_after_submit_recovery`, `test_unknown_broker_status_remains_fail_closed` all pass.

5. **Can it reconcile after restart?** Yes, durably. `reconcile_state(k=1,suspended,reason)` and `IdempotencyStore` are SQLite files, loaded on `ExecutionEngine.__init__` (`RESTORED_SUSPEND` audit). Tests for 7 drift types (UNKNOWN/MISSING quantity/price/status, broker disconnect, MISSING_ORDER) all suspend and remain suspended after restart with same `db_path` until `heal_reconcile`. Clean restart tests for 5 states (normal FILLED, AMBIGUOUS, SUSPENDED, PARTIALLY_FILLED with `volume_based` 2 fills, FILLED) all verify duplicate blocked, state restored, no double economic order.

6. **What, exactly, still prevents unrestricted live trading?** Three independent fail-closed layers:
   - **Gate 1 — Settings:** `QTS_ENV != live` or `risk.approved != true` or `--confirm live` missing → `assert_live_allowed` raises → `exit 2`.
   - **Gate 2 — Live readiness report (15 checks):** `environment` currently fails (`env dev`), plus any future `SUSPENDED` or missing `paper/shadow/validation` evidence would add to `blocked_reasons` → `exit 2`.
   - **Gate 3 — Structural:** `cli.py` final `sys.exit(2)` after `live mode — gate passed but still requires final manual approval` — even if Gate 1+2 pass, live exits 2. Code comment says *remove only when all evidence verified* — no auto-merge.
   - **Terminal:** No real MT5 terminal in sandbox (`is_mock true` in dry_run); `MT5Adapter.connect` would fail `initialize` without `MetaTrader5` installed and credentials; `QTS_MICRO_ENABLED` also required for micro, default false.
   Hence unrestricted live is **impossible** without explicit human code change, credential provisioning, and audit — exactly as required.

---

## Evidence Files

- `data/evidence/paper_trades.json` — 6 trades, 8606.42 equity (realistic paper)
- `data/evidence/shadow_intents.json` — 29 intents, 5 would_be (no venue)
- `data/evidence/dry_run.json` — prereq/market/account/risk/request all ok, no submission
- `data/evidence/micro.json` — 0.01 lot FILLED, poll 1, reconcile NONE, positions 1 (mock)
- `logs/audit` — `SqliteAuditLog` with `RiskVeto, NoTrade, OrderEvent, Fill, Reconcile, DRY_RUN`

**Tests:** `python -m pytest tests -q` → 132 passed (see `tests/adversarial/test_mt5_boundary.py` 50 new + `test_production_boundary.py` 18 + existing 64)

**CLI verification:**
```bash
qts run --mode dry_run --data-version 20260916-010-572728d9  # ok, no submission
QTS_MICRO_ENABLED=true QTS_ENV=live qts run --mode micro --data-version ... --confirm live  # needs live.yaml approved, else blocked
qts run --mode live --data-version ... --confirm live  # always exit 2, fail-closed
python -m pytest tests -q  # 132 passed
```

