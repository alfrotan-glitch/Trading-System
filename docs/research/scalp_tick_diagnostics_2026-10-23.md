# QTS scalp tick research: diagnostic interpretation

The frozen tick-sequenced XAUUSD discovery replay is not validation of a
profitable strategy. The next task is understanding its losing trades
without rerunning the raw MT5 ledger, optimizing entry thresholds on the
already-examined sample, or making an unsupported execution claim.

The read-only command
`python scripts/analyze_xauusd_scalp_tick_replay.py`
reads the existing local, gitignored
`data/raw/scalp_replay_reports/report.json` and produces
`diagnostics.json` plus `diagnostics.md` in the same directory.
No raw MT5 tick processing, MT5 connection, strategy registration or orders.

Diagnostics: realized-on-simulated-quote mean and median net bps, average
winning/losing trade, break-even win-rate for the observed payoff sizes;
the contribution of each exit reason and direction; all three fixed,
equal-calendar-time partitions of the existing discovery window; and
weekly UTC per-mode outcomes on the same time window. Week-to-week
comparisons are descriptive and not paired trade experiments (different
modes can generate different trade sequences). No post-hoc weekly filter is
automatically turned into a trading rule. Subgroup data must not be used
as independent out-of-sample evidence.

Both modes must be from the same quote-row count, LIVE must be locked,
holdout excluded, order count zero, and all trade times causal and within
the original discovery cutoff. Additive bps are NOT a capital return.

Do not trade this system with real funds on these results alone.
