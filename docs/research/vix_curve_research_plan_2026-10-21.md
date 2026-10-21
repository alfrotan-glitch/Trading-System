# New information channel: Cboe implied-volatility TERM STRUCTURE

**Created 2026-10-21. Status: EXPERIMENT CODE WRITTEN, NOT RUN ON REAL DATA.
Verdict: NO EDGE CLAIMED. LIVE REMAINS LOCKED.**

## Why this is not another failed VIX-level indicator

The earlier stress-complex rounds used VIX *level*, credit stress, NFCI,
and St Louis FSI. These do not observe the **relative slope across option
maturities**, an independent economic variable.

Lehnert (2025), *Commodity Risk Premia and the VIX Term Structure*,
reports incremental predictive information from the VIX term-structure shape
for gold and oil futures. The cited paper uses a richer term-structure
representation; **our simple two-point spread is NOT a replication of its
estimated model and must not inherit its reported alpha**.

Primary study: https://orbilu.uni.lu/handle/10993/65946
Official Cboe history: https://www.cboe.com/tradable-products/vix/vix-historical-data
Cboe volatility term structure: https://www.cboe.com/tradable_products/vix/term_structure

## Data and strict timing

- Official Cboe daily VIX (30-day) and VIX3M (3-month), downloaded into the
  gitignored `data/raw/edgelab/cboe_vix_curve/` with SHA256 provenance.
- Only dates with both VIX and VIX3M present are admitted. Nothing is
  interpolated or backfilled.
- Explanatory feature: `log(VIX3M / VIX)`, trailing 20 published observations.
- **Two and only two predeclared hypotheses**: long gold in contango, or
  long gold in backwardation. Not both chosen retrospectively.
- Monthly decisions every 21 Cboe observations, held long or flat. One extra
  Cboe observation delay before use, PLUS the standard executable lag in
  `run_vector`. This is intentionally conservative.
- Signals can only be filled forward from earlier published values, for at
  most 5 calendar days; older data means flat.
- Cboe closes must never be credited with the gold move that occurred before
  their release.
- The gold benchmark is a tradable 24-hour close, not LBMA's 10:30 AM fix.

## Controls and integrity

- Evaluate on historical DEV/VAL/diagnostic partitions; **all are spent
  already** by prior gold research, so a positive value here cannot be an
  untouched out-of-sample validation.
- Compare each timing rule to a *static, exposure-matched* gold allocation,
  not only an unscaled buy-and-hold series. Calculate the paired net daily
  difference after identical financing and turnover assumptions, and report
  its Newey–West/HAC statistic, **not only** a Sharpe difference. Even a
  significant result here remains DISCOVERY because the historical windows
  are spent.
- Charge the existing `CostModel.realistic_ecn()` on turnover and report
  cost model as **ASSUMED**. Verify the price-dependent per-side costs.
- Add explicit **hypothetical funding stress** at 0, 0.5, 1.0 and 2.0 basis
  points per elapsed **calendar day** held, including weekends. These rates
  are scenario assumptions, not current broker swaps. Actual broker swap,
  rollover policy, triple-swap days and execution must still be measured
  before any practical edge can be claimed.
- Both orientations add to the multiple-testing register; do not select the
  best sign and report it as a pre-specified single trial.
- Reject a strategy that fails positive net-of-all-cost evidence, HAC
  inference, stability, timing, or independent validation. Keep LIVE locked.

## Reproducible commands

```bash
python scripts/fetch_cboe_vix_curve.py
python scripts/edgelab_vix_curve_run.py --gold-source basemax
pytest tests/unit/test_edgelab_vix_curve.py -q
```

If Cboe blocks a sandbox download, report the exact failure. The raw data
must not be forged or replaced by synthetic observations. No claim of a
completed backtest is allowed until the experiment artifact exists.

The run writes `data/research/experiments/vix_curve_*.json` and labels every
historical result `EVALUATED_SPENT_DATA`, with `fresh_oos_confirmed:false`
and `validated_edge:false`. It cannot unlock live trading.

## Follow-up

1. Obtain real official Cboe history with the script and verify freshness,
   hashes, overlap and coverage.
2. Run the unaltered two-direction tests, analyze turnover and matched
   controls, then add broker financing sensitivity.
3. If there is a mechanistically plausible and statistically robust candidate,
   freeze its definition *before* accumulating genuinely new observations.
4. Continue independent research, particularly futures basis/term structure,
   ETF physical flows, and scheduled-event information — but require data
   provenance, executable timestamps and rigorous comparisons.


## Automated GitHub execution

The repository also contains
`.github/workflows/vix-curve-research.yml`, which is configured to run on
relevant `main` pushes or through GitHub Actions' manual dispatch. It:

1. Installs the project and runs timing, regime and VIX unit tests.
2. Downloads official Cboe histories with hashes.
3. Downloads the pinned BaseMax archive at commit
   `43f4177e701fdf3643cc02413e4337932af57401`.
4. Builds UTC daily closes only from M15 days with at least 80 bars, so the
   BaseMax feed's almost-empty 2025 tail cannot contaminate returns.
5. Executes all two frozen orientations and four predeclared financing stress
   levels, and uploads **only** JSON research evidence, not raw price archives.

Open the repository's **Actions → QTS VIX Curve Research** page and inspect
the latest run and its `qts-vix-curve-research-*` artifact. A workflow
definition committed to GitHub is *not* proof its job passed: until the
associated run has been checked, test and experiment status remain
**UNVERIFIED**. External data/network failures must be reported rather than
replaced by synthetic prices.

The historical gold feed used by this automated test is the pinned BaseMax
M15 source (not the actual owner's WMMarkets `XAUUSD@` bid/ask execution feed).
The live product therefore remains **locked** regardless of a promising
research result.
