# QTS Gold | Original-LIMIT post-fill safety

**Safety status:** research-only; `LIVE LOCKED`; profitable edge not validated.

## Why

A submitted LIMIT can execute at a different price after a gap. The
originally authorized pending BUY/SELL stop geometry can be invalid at the
actual broker fill price even though the order passed preflight checks.

Concrete native October 2026 entry: BUY actual fill **4136.56**, initial
SL **4142.64**, target **4147.04**. Original stop is above the broker fill.
Do not pretend the distance to that stop is a controlled risk.

## What the code does

1. It retains existing pre-order `OrderCheck`, quote, spread, margin,
   planned monetary loss and attached SL/TP checks.
2. On each QTS-origin broker entry `TRADE_TRANSACTION_DEAL_ADD`, it reads
   `DEAL_PRICE`, `DEAL_SL`, `DEAL_TP`, `DEAL_VOLUME`,
   `DEAL_POSITION_ID`, and `DEAL_ORDER` from broker deal history.
3. It rejects missing/wrong-side original stops, a target on the wrong
   side, ambiguous netting reversal, or a post-fill stressed money loss
   above the original pending-order money loss at the same executed volume.
   To avoid an incorrect equity-budget comparison, it retrieves original
   `ORDER_PRICE_OPEN` and `ORDER_SL` from historical OR active order
   records: MT5 transaction events are not guaranteed in order.
4. On unsafe evidence it persists a position-identifier-specific
   unsafe-fill marker, raises the existing entry halt, requests
   cancellation of resting QTS orders, and uses the existing throttled
   protective `PositionClose` path on exactly owned QTS positions.
   Partial close or broker rejection remains observable and retried; an
   acknowledged request is not misrepresented as completed liquidation.
5. For mixed/manual ownership in a netting position or unavailable entry
   provenance, **it abstains from automatic close**, halts new orders and
   requires reconciliation. Do not liquidate someone else's netted trade.
6. On terminal restart it reconstructs unsafe historical entry fills
   for any existing QTS-owned positions and does not clear saved halts
   or incident markers automatically.

**Limitations:** A server SL and a protective close do not guarantee
the stop or requested exit price during gaps, outages or illiquidity.
If broker history cannot be read, the account is halted; automatic close
is not claimed. A marker that cannot be persisted is tracked by the
current process for the identifiable position, but does not guarantee
restart recovery without broker history.

## Missed events and diagnostic artifacts

- The protective timer independently calls `QtsAuditActiveOriginalFills()`
  while an owned position exists, so a lost/delayed `DEAL_ADD` callback is
  not the only chance to identify unsafe entry fills. No real-account
  permission is added.
- The native audit reads **individual entry DEALs**, not only aggregated
  position entry averages. An abnormal small partial fill cannot be masked
  by an otherwise valid weighted-average fill. Original setup attribution,
  entry and exit volumes, and entry timestamps must reconcile.
- If the automatic tester encounters an unsafe original fill, it sets
  `SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO`, exits with status 2, and
  writes `QTS_POST_FILL_SAFETY_AUDIT.json`.
- `QTS_DUAL_QUALITY.bat` preserves
  `QTS_DUAL_QUALITY_EVIDENCE.zip` **including the incident audit** even
  when the test exits NO-GO. `QTS_DUAL_THREEWAY.bat` stops comparison
  immediately and instead preserves `QTS_SAFETY_INCIDENT_NO_GO.zip`.
  Both show the evidence file and return failure; neither substitutes
  an incomplete test for economic comparison.

## Verification gates

- Python regression: `gold_robot/tests/test_execution_fill_safety.py`
  reproduces malformed BUY 4136.56/SL 4142.64, normal BUY/SELL,
  opposite-side SELL failure, missing stops, nonfinite prices,
  risk expansion, ownership and restart/source invariants.
- MetaEditor must compile the canonical EA with **0 errors, 0 warnings**.
- MT5 real-tick replay must demonstrate the incident causes **NO-GO**,
  broker-book reconciliation and no subsequent new exposure.
- Existing risk defaults, strategies and LIVE lock must be unchanged.
- Until native broker replay and manual incident review pass, the release
  is **NOT APPROVED FOR LIVE**.

Never tune a strategy's parameters just to recover an earlier profitable
backtest after introducing this mandatory execution safety check.
