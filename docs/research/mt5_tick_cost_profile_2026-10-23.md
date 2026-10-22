# XAUUSD@ MT5 tick quote-cost profile — 2026-10-23

**Disposition:** measured quote evidence only; not an executable cost model,
not a validated edge, and no order authorization.

The local read-only MT5 acquisition workflow captured one complete seven-day
window of broker bid/ask ticks and independently analyzed the persisted raw
Parquet dataset. The raw tick dataset remains local and untracked. The
sanitized summary is `data/evidence/mt5_tick_cost_profile_2026-10-23.json`.

## Measured quote profile

| Measure | Result |
|---|---:|
| Rows | 935,472 |
| Dataset status | `COMPLETE`; analysis `PASS` |
| Non-monotonic raw millisecond timestamps | 0 |
| Invalid bid/ask or ask below bid rows | 0 |
| Zero-spread rows | 0 |
| Median quoted spread | 0.5803 bps |
| Mean quoted spread | 0.5824 bps |
| 95th percentile quoted spread | 0.6535 bps |
| Maximum quoted spread | 3.0910 bps |

Equal-millisecond groups and distinct payloads were retained and measured; they
were not silently deduplicated. The direct historical server/UTC timestamp
basis remains unverified, so the time range is not used as a UTC claim.

## Cost boundary

This measures the quote spread present in the terminal response. It does not
measure a round trip: no order, fill, slippage, commission, swap, or realized
execution record was created. The spread cannot be retroactively joined to the
historical M15 OHLC bars at each hypothetical fill, so the 2026-10-23
conditioned-volatility assay remains scored under its declared price-distance
stress rather than being rewritten with a post-hoc cost.

The evidence supports a future cost model that uses the measured quote-spread
distribution as one input, subject to a verified timestamp join and separate
commission/slippage/swap evidence. It does not support strategy promotion.

Safety: `read_only=true`; `orders_submitted=0`; `order_send_called=false`;
`DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
