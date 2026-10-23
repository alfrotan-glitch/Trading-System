# XAUUSD H-MM-02 — 365-day broker-ledger walk-forward result

This fixed market-making assay compared low-volatility/tight-spread and
high-volatility/wide-spread states on the local 365-day MT5 bid/ask ledger.
Only the chronological discovery prefix was passed to the hypothesis engine;
the held-out suffix was not read by the hypothesis.

Result: **INCONCLUSIVE**, not a validated edge. The pooled favorable-state
fill lift was `0.0183`, below the preregistered `0.05` floor. Its synthetic
risk-adjusted result (`0.0609`) was below the unfavorable state (`0.0739`).
Three of five folds had fewer than 500 favorable observations, with fold
sample sizes `1222, 177, 6, 0, 17769`.

Fills are a synthetic front-of-queue touch model. Bootstrap inference,
commission, slippage, swaps, and realized fills remain unavailable, so no
executable profitability claim is permitted.

Safety: `orders_submitted=0`; `order_send_called=false`;
`DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
