# Capital Preservation Policy
**Generated:** 2026-09-16T13:49:19.328123+00:00

Hard limits (Phase 12) — crossing any forces NO_TRADE or SUSPENDED, no adaptive expansion after losses.

- risk_per_trade: 50 bps
- total_open_exposure: 2.0 lots
- daily_loss: 200 USD
- rolling_loss: 500 USD
- max_drawdown: 500 USD
- consecutive_losses: 5
- num_trades/day: 20
- order_frequency: 10/min
- spread: 100 bps
- slippage: 20 bps
- latency: 2000 ms
- data_staleness: 5s
- reconciliation_drift: any drift → SUSPENDED

Current check: {'passed': True, 'reason': None}

Emergency controls (Phase 17): kill_switch, cancel_all, suspend_new_orders, max_order_rate, max_order_size, stale_data_stop, abnormal_spread_stop, latency_stop, account_state_stop, reconciliation_stop — independently tested.

