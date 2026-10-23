# XAUUSD MT5 history ladder — 2026-10-23

The read-only acquisition ladder obtained complete local bid/ask tick windows
from 1 through 365 days. Every window passed deferred local integrity analysis;
the raw Parquet datasets and detailed acquisition manifests remain local and
untracked. The sanitized digest-bound summary is
`data/evidence/mt5_history_ladder_summary_20261023.json`.

| Window | Rows | Median spread | p95 spread | Analysis |
|---:|---:|---:|---:|---|
| 1d | 203,296 | 0.5831 bps | 0.6606 bps | PASS |
| 7d | 935,472 | 0.5803 bps | 0.6535 bps | PASS |
| 30d | 4,124,595 | 0.5769 bps | 0.6668 bps | PASS |
| 45d | 6,260,797 | 0.5811 bps | 0.6902 bps | PASS |
| 60d | 8,411,211 | 0.5813 bps | 0.6793 bps | PASS |
| 90d | 13,574,657 | 0.5935 bps | 0.7359 bps | PASS |
| 120d | 21,089,755 | 0.6002 bps | 0.7406 bps | PASS |
| 180d | 37,296,873 | 0.5763 bps | 0.7307 bps | PASS |
| 365d | 81,211,638 | 0.5863 bps | 0.9024 bps | PASS |

These are quoted bid/ask costs, not measured commission, slippage, swaps, or
fills. The same-session timestamp evidence confirms historical `time_msc` as
UTC for the digest-bound acquisitions. No order API was called.

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
