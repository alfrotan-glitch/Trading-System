# Initial QTS robot — old stop becomes new entry

This is the **same unreleased robot**; no v1/v2/v3 naming or product releases.

## Explicit owner-directed relocation

Using **completed, contiguous** candles, define structural low `L`, high `H`,
closed-bar ATR `A`, bid-ask spread `S`, and tick size `q`.

Previous long algorithm defined its hypothetical invalidation stop as:

`OldSL_buy = floor_to_tick(L - max(0.20*A, 1.2*S))`

**New BUY LIMIT entry equals that exact old stop:**

`NewEntry_buy = OldSL_buy`

`NewSL_buy = NewEntry_buy - ceil_to_ticks(max(0.25*A, 3*S, broker_stops_level + two_ticks))`

New TP remains at the opposing closed-bar structural extreme (with spread
allowance) only when the **new** reward/risk meets the configured threshold.

For shorts:

`OldSL_sell = ceil_to_tick(H + max(0.20*A, 1.2*S))`

`NewEntry_sell = OldSL_sell`

`NewSL_sell = NewEntry_sell + ceil_to_ticks(max(0.25*A, 3*S, broker_stops_level + two_ticks))`

`NewTP_sell = ceil_to_tick(L + S)` subject to reward/risk and broker spacing.

No arbitrary minimum distance is silently ignored; symbol `SYMBOL_TRADE_STOPS_LEVEL`,
lot step/size, spread, margin, quote freshness, positive stop/target separation,
valid BuyLimit/SellLimit order distance and server-side pending expiration
remain authoritative. Invalid setup → NO_TRADE, not a market order.

This is **liquidity sweep / deep pullback exploration**, not evidence the
fill will reverse; filling at a former SL level can coincide with a breakdown
and may raise, not lower, conditional stop-out risk. No edge inferred.

## Execution

Broker `TRADE_ACTION_PENDING`, `ORDER_TYPE_BUY_LIMIT` or `SELL_LIMIT`,
attached protective SL and TP, server-managed specified expiry, `OrderCheck`,
`OrderSend`. Accepted order is not a completed fill. All old risk/session,
identity, exposure and uncertainty handling stays in place.

[Official MT5 order types](https://www.metatrader5.com/en/terminal/help/trading/general_concept),
[MQL5 stop levels](https://www.mql5.com/en/book/automation/symbols/symbols_spreads_levels).
