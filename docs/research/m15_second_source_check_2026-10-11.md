# M15 second-source check — 2026-10-11

Status: **rejected as an independent confirmation.** No second source is used by any
research result. No edge is claimed. Diagnostic only.

Reproduce: `python scripts/check_m15_source_overlap.py --candidate <csv> --out <json>`
(the reference is the Dukascopy mirror replicate, fetched and SHA-256-verified by
`scripts/fetch_longhistory_sources.py`).

## Why a second source was needed

The long-history verdicts rest on one primary series (BaseMax 15m, 2004–2025). The
other pinned sources are one quote stream, not independent confirmation (see
`longhistory_data_provenance_2026-10-10.md`). The only other series, Dukascopy, has
no bar overlap with BaseMax, so it cannot cross-check the primary.

## Candidates considered

| Candidate | Coverage | Licence / terms | Provenance | Decision |
|---|---|---|---|---|
| `novandraanugrah` Kaggle XAU 15m (CC0) | 2004 → 2025-08 | CC0 | Same upstream as BaseMax (see provenance note) | **Not independent.** Excluded. |
| getdata-finance GitHub sample `XAUUSD_15m.csv` @ `ae63d12` (2026-09-26) | 2026-03-26 02:30 → 2026-09-25 20:30 UTC, 11,989 bars | MIT (Copyright GetData 2026) | Upstream vendor **not disclosed**; README states "bar open timestamp (UTC)" and tick volume | **Rejected** after the overlap test below. |
| getdata.finance full archive (≈404k 15m rows, from 2009-02-24) | Long history | Not verified: the vendor page returned a Cloudflare tunnel error, so no terms were readable | Not disclosed | Not usable. Not verified. |
| MarketData Hub / Tickstory (paid downloaders) | Claimed 2003 → | Software licence; data redistribution terms not verifiable here | Claimed to be pulled from a broker feed | Not fetched. Not in the allowed network. |

## Overlap test: getdata sample vs Dukascopy replicate

SHA-256 of the sample CSV: `b23257db4b38cbffe431b98449f1aef523cecc232f659e79781aeeff8f2bb4c9`.
Dukascopy replicate loaded: 26,038 bars, 2025-08-06 00:00 → 2026-09-16 23:45 UTC.

1. **Timestamps.** Shift scan from −6 h to +6 h in 15-minute steps. The best alignment
   is at **0 h in every month** (March–September), so the two stamp conventions match.
   The mismatch below is not a clock problem.
2. **Price level.** Over the 11,090-bar overlap, close correlation is 0.996 and bar-return
   correlation is 0.982. Yet the levels differ: median (getdata − Dukascopy) close is
   **+$13.55**, mean +$22.34, std $31.71. Only **0.32%** of bars agree within one cent.
3. **Monthly drift.** The median level difference is not constant:

| Month (2026) | Overlap bars | Median Δ close ($) | Std ($) |
|---|---:|---:|---:|
| March (from 26th) | 357 | +93.71 | 4.27 |
| April | 1,929 | +67.78 | 32.49 |
| May | 1,890 | +56.08 | 21.59 |
| June | 1,986 | +13.37 | 18.52 |
| July | 2,076 | +0.48 | 12.06 |
| August | 1,816 | +14.49 | 7.96 |
| September | 1,036 | −0.15 | 0.15 |

Median absolute close error at the best shift is $15.17 over the full overlap.

**Interpretation (not established).** Two feeds of the same gold quote should agree
to within a few cents to tens of cents. A level gap that is $94 in March, falls to
near zero in July, and is near zero in September is a basis or roll-type difference,
not noise. The cause is not identified. The sample's price basis is undisclosed, and the
Dukascopy mirror's price basis is also unverified. The data do not say which series is
correct.

## Decision and consequences

- **getdata sample: not used.** It is a six-month sample, its provenance is undisclosed,
  its full archive has unverified terms, and it disagrees with the Dukascopy replicate
  by tens of dollars for most of its overlap.
- **Dukascopy replicate: its informational results carry an additional caveat.** Its price
  basis is not validated against any independent source. The replicate results in
  `longhistory_intraday_results_2026-10-10.md` and `longhistory_results_2026-10-10.md`
  are informational and already non-gating. A constant offset would cancel within one
  series, but the basis here changes over time (about +$94 to about $0 across March–July).
  Any trade held across such a change picks up a basis artifact, so the replicate P&L
  figures should not be read as confirmation or refutation.
- **No change to any verdict.** Both verdicts remain `NO_VALIDATED_EDGE`, costs ASSUMED.

## What would close the gap

1. A licensed, documented long-history M15 series with disclosed vendor, licence, and
   timestamp convention, overlapping the Dukascopy window, so the basis question can be
   measured.
2. Measured broker costs and bars from the Windows MT5 DEMO terminal
   (`qts data mt5-depth`, `qts demo cost-check --record`). These come from the same
   broker feed the DEMO account trades against, so they answer a different question than
   a third-party series. Blocked in this sandbox (Linux, no MetaTrader5 package).

## Not claimed

No new edge. No second source validated. Nothing in this note was used to tune or select
any strategy, and the 2025–2026 holdout was not touched.
