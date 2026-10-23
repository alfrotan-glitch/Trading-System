# QTS short-horizon regime scalp — implementation note (2026-10-23)

**Status: research/demo candidate, not a verified profitable edge. LIVE remains locked.**

The reusable provider `qts.research.demo_scalp_provider:RegimeScalpProvider` accepts
only confirmed one-minute-bar closes (with bounded startup warmup). It proposes
a trend pullback, a range fade, or a breakout using information through the
most recently finished minute. Signals use broker bid/ask, a registered stop,
and a cost/volatility feasibility filter. Market-state routing is causal; it
does **not** forecast perfect swing highs/lows, nor promise profitable fills.

The new registered-policy-only `exit_conditions.scalp` fields are
`take_profit_net_bps`, `extra_cost_reserve_bps`,
`max_loss_net_bps`, `max_spread_bps`, and `max_tick_age_s`.
All must be finite positive values. The scalp quote-age and spread limits
cannot exceed the existing DEMO policy's stricter limits. The time limit
(`max_hold_seconds`) and broker protective stops remain mandatory.
The reserve is an estimate, never a claim that commission/slippage was measured.
Only a journal-matched, same-strategy broker position may be scalp-closed.

**Not activated:** The provider is deliberately **not** added to the eligible
strategy registry. Future DEMO activation requires an explicit, preregistered,
hash-pinned policy, matched code/config hash, owner-authorized DEMO account,
broker cost capture, and successful safety gates. Nothing authorizes LIVE.

**Validation needed:** causal bid/ask replay with alternative fills, session
and gaps, actual broker commissions/slippage, a new independent holdout and
DEMO-forward measurements. Research tests and synthetic unit paths are not
profitability evidence.
