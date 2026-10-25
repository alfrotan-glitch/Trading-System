# QTS Gold Robot - Initial Development: performance and delivery evidence

The mandate is **not complete**. No tested strategy demonstrated a reliable
positive after-cost edge. The package is an installable, compiled research build;
new broker DEMO entries remain blocked by the evidence gate. Real money is blocked.

## Native EA execution

The interim March 2025 run used a custom symbol copied from WMMarkets XAUUSD@
cache, not an active broker connection: 3,771,581 real ticks, 1,932 bars, 100% real
tick quality, six completed trades, net -$4.65, profit factor 0.95, expected payoff
-$0.78, maximum equity drawdown $145.04 (1.44%). This is before extra hypothetical
commissions/slippage. Native ledger commission was zero; zero is not a verified
claim about historical broker charging. The symbol uses current cloned contract
settings and a simulated $10,000 USD account, 1:100 leverage, 100 ms tester delay.

An earlier six-month run had zero trades because the H1 moving average readiness check
preceded its first buffer request. On a cold history cache `BarsCalculated` stayed
at `-1` while H1 price bars accumulated. A before/after January diagnostic is in
`evidence/native/h1_cold_cache_diagnostic.log`. Requesting the closed H1 buffer
before checking readiness restored order entry; the January replay accepted five
LIMIT orders, filled one trade, and lost $17.40 natively.

The corrected canonical EA then completed the full January-June 2025 native run:
28,969,323 ticks, 11,460 bars, 99% real-tick quality, 136 accepted LIMIT orders,
18 completed trades, **-$5.54 native net**, profit factor **0.98**, expected payoff
-$0.31/trade, and maximum equity drawdown $180.41 (1.77%). The native report showed
zero commission; that is not a verified WMMarkets tariff. With an *additional*
assumed $10 round-trip commission per lot and 0.05 price units of adverse exit
slippage, 3.19 exited lots incur $47.85 extra and indicative net becomes **-$53.39**.
Swap and historical execution tariffs remain unverified. The result is negative
before and after these extra costs, so no positive edge is claimed. Reproduce the
extraction with `python research/parse_native_report.py
runtime/terminal/native_development_2025.htm evidence/native/native_development_metrics.json`.
The raw HTML and agent log are retained in `evidence/native/`. The installed
EX5 was also replayed over January 1-8: six accepted LIMIT orders, two broker
deals, one completed trade, and the same -$17.40 native net. This verifies the
installer-produced binary on the cold-cache path; the six-month run used the
canonical source compiled separately with the same MetaEditor build.

During this run, 33 local cancel requests raced with server expiry and MT5 returned
`Invalid request` after the order had already expired. Broker history reconciliation
handled those races; no protective cancellation failure or execution halt was logged.
This does not certify connected broker execution or partial-fill recovery.

A logging-only native probe reproduced the canonical balance, accepted-order count,
and all 18 trades exactly. Its sequential M15 funnel is retained in
`evidence/native/coverage_probe_summary.json`:

| Stage | Count |
|---|---:|
| Completed M15 bars | 11,460 |
| Broker session open | 7,992 |
| Indicator data ready after exposure/quote checks | 7,835 |
| ADX threshold passed | 6,703 |
| EMA pullback cross after ADX | 327 |
| H1 trend filter passed | 242 |
| Broker-safe former-stop LIMIT accepted | 136 |
| Pending orders filled | 18 |

H1 rejected 85 cross candidates; the structural LIMIT checks rejected 104 of
242 H1-approved signals, and 2 lacked a safe server expiry. Only 2 bars had a
quote/spread/broker-permission veto at that stage. This is an opportunity funnel,
not evidence that the rejected signals would have earned money.

Native order coverage is quantified in `evidence/native/native_order_coverage.json`:
136 accepted former-stop LIMIT orders produced 18 fills (13.2%); 85 were canceled
and 33 expired. Filled orders took a median 17.6 minutes to fill. The median
initial entry distance was 1.32 M15 ATR using a causal Python ATR proxy; that
proxy is not identical to MT5 indicator warmup. Of the 118 unfilled orders, the
old executable level was revisited within 30 minutes after removal for 22, and
within two hours for 46. These later touches are **not** profitable missed trades:
extending orders would alter risk, exposure, queue position, and subsequent signals.
No expiry or distance parameter was loosened on this evidence.

Pending acceptance, delayed fills, stop/target exits, server expiry, and protective
cancellation were observed. The old 10009 failure is fixed: valid accepted tickets
are retained and fills are attributed only from deals. Receipt policy also passed
12 actual MQL script cases. This does not certify connected broker execution,
partial fills, disconnect recovery, queue behavior, or every adverse-event race.

## Reproducible hypothesis research

Development interval: 2024-09-19 through 2025-06-30. Both passes replayed the same
45,280,491 genuine exported bid/ask ticks across 200 trading days, independently
per strategy. There were zero missing tick days, zero bar intervals without ticks,
and zero rejected malformed/out-of-order ticks in that interval. Data hashes and
per-day coverage are in the JSON reports. The complete cached export contains
541 daily files (approximately 6.2 GB); this is not a claim of complete coverage
outside the evaluated interval.

| Hypothesis | Trades | Net USD | Profit factor | Max marked DD USD | 99% bootstrap lower expectancy USD/trade | Decision |
|---|---:|---:|---:|---:|---:|---|
| trend_pullback | 48 | -339.28 | 0.63 | 403.52 | -19.53 | Reject |
| range_reversion | 18 | -373.77 | 0.00 | 402.37 | -21.79 | Reject |
| breakout_retest | 1 | -21.59 | 0.00 | 44.71 | -21.59 | Reject |
| failed_breakout | 17 | -405.65 | 0.18 | 482.59 | -59.74 | Reject |
| compression_expansion | 0 | 0.00 | n/a | 0.00 | n/a | Reject |
| session_reversal | 14 | -311.84 | 0.00 | 404.53 | -23.17 | Reject |
| channel_momentum | 212 | -321.19 | 0.83 | 403.40 | -4.18 | Reject |
| opening_range_breakout | 181 | -143.04 | 0.92 | 323.84 | -4.40 | Reject |
| exhaustion_reversal | 154 | -343.56 | 0.79 | 402.91 | -5.54 | Reject |

The first six hypotheses use the preferred former-stop LIMIT entry. The final
three are distinct market-entry research alternatives; no market-entry fallback
was added to the EA.

A third, preregistered experiment used previous **completed day** levels, with
market entry after either a failed sweep or an accepted break. It replayed the
same 45,280,491 development ticks with zero missing/invalid ticks. Its protocol
and source hashes are in `evidence/prior_day/run_manifest.json`; results and
trade ledger are in `evidence/prior_day/`. No validation or holdout was scored.

| Prior-day hypothesis | Trades | Net USD after assumed costs | Profit factor | 99% day-block lower expectancy | Positive quarters | Decision |
|---|---:|---:|---:|---:|---:|---|
| previous_day_sweep | 74 | +148.56 | 1.25 | -3.78 USD/trade | 2 | Reject: fails minimum sample, quarter stability, lower-bound gates |
| previous_day_acceptance | 94 | -7.70 | 0.99 | -4.68 USD/trade | 3 | Reject: negative net and stability |

The sweep's positive development net is exploratory only. Its stressed net was
+$107.56 under the stated extra-cost stress, but a 74-trade sample and negative
bootstrap bound do not establish durable expectancy. The acceptance candidate
also fails. Neither was combined with another strategy or added to the EA.
Reproduce with `python research/prior_day.py`.

The original sweep was then replayed **unchanged** on a separate July-December
2025 block: 32,364,244 valid ticks across 131 trading days, 60 trades, **-$324.83**
net after assumed costs, profit factor **0.47**, negative in both quarters and in
all prespecified efficiency regimes. Its 99% day-block lower expectancy was
-$10.35/trade and stressed net -$345.43. The original and separate blocks total
134 trades and -$176.27 across independently reset accounts. This is a failed
replication, so the January-May 2026 forward block was not scored. The final
June-October 2026 holdout remains sealed. Protocol and evidence are in
`research/sweep_followup_protocol.json` and `evidence/sweep_followup/`.

Two distinct tick-event hypotheses then tested 20-second quote bursts with a
later executable market entry, costs, and a 20-minute hold. On the 45,280,491-tick
development block, quote-burst momentum lost **$383.65** over 37 trades (PF 0.25);
quote-burst reversion lost **$345.03** over 60 trades (PF 0.48). Both reached the
4% peak drawdown stop early and were left stopped. No later block was scored.
Their frozen protocol, code hashes, coverage and ledgers are in
`research/quote_burst_protocol.json` and `evidence/quote_burst/`. The market-entry
results demonstrate that abandoning LIMIT orders alone did not produce an edge.
At least 15 families have now been screened; nominal favorable slices require
multiple-testing-aware prospective evidence before promotion.

A separate day-horizon experiment used the previous completed day's candle
body to test continuation and reversal with same-day market exits. Its frozen
rules produced 117 signals per side, but 107 were vetoed because the broker's
0.01-lot minimum would exceed the 0.25% risk budget at a day-scale stop.
Continuation earned +$42.93 on only 8 trades; reversal lost $26.62 on 8.
Neither meets sample adequacy; risk was not raised to force trading. Results and
hashes are in `evidence/daily_direction/` and
`research/daily_direction_protocol.json`. Both are rejected.

The original trend research proxy is not an exact reproduction of the EA's
MT5 ADX/H1 implementation. Canonical EA performance is reported separately.

All candidate positions use executable bid/ask quotes. Limits require one tick
of penetration after submission, receive no favorable entry improvement, expire
after 30 minutes, and are cancelled across observed quote gaps longer than one
minute. Position gaps use the next executable stop quote. Market alternatives
include adverse entry slippage. Max hold is 180 minutes. No mid-price fills,
bar-high/low fill ordering guesses, or future-bar indicators are used.

Costs are explicit assumptions: $10 round-trip commission per lot and 0.05 price
units adverse exit slippage (plus 0.05 entry slippage for market alternatives).
Cost stress adds another $10/lot and 0.10 adverse exit price units. These are
sensitivity assumptions, not verified broker tariffs. Spread is already in
executable quotes. Financing/swap and complete historical contract/session
changes are unverified; therefore these results cannot certify all-in profitability.

Sizing is 0.25% of **current** equity with a 35% reserve and rounded-down lots,
starting at $10,000. The first protocol text says initial equity; the recorded
engine actually uses current equity. This discrepancy is disclosed rather than
silently changing the frozen protocol. Daily loss and permanent peak-drawdown
stops are 1.5% and 4%. Gaps/price movement can exceed those percentages. Stopped
strategies were not reset to manufacture a longer profitable sample. These are
individual strategy accounts, not a combined portfolio.

The 1,000-resample Monte Carlo uses whole trading-day blocks, including zero-trade
days, with fixed seed 6241024. Confidence bounds are screening diagnostics on a
selected development sample, not independent proof. Daily Sharpe, recovery,
regime and quarterly results, execution vetoes and stress totals are preserved in
the JSON. No parameter optimization was performed. Parameter-neighborhood and
walk-forward testing were not run because every candidate failed development.
Post-hoc favorable regime slices were not promoted.

Validation (2025-07-01 to 2026-05-31) and final holdout (2026-06-01 to 2026-10-23)
were **not performance-evaluated**. Exporting/hashing bars and ticks does not make
them an independent result. New hypotheses must be frozen before evaluating
validation, and the final holdout must remain a one-use acceptance check.

## Engineering, reproduction, and remaining work

- MetaEditor: zero errors and warnings; compiler evidence in `evidence/compile.log`.
- Native receipt test: `evidence/QTS_receipt_test.txt` (12 cases, zero failures).
- Installer succeeded inside `runtime/terminal`; log in `evidence/installer.log`.
- Python regression result is recorded in `evidence/pytest.txt`.
- Run `python research/research.py`, `python research/alternatives.py`, and
  `python research/prior_day.py`, `python research/sweep_followup.py`, and
  `python research/quote_burst.py`, and `python research/daily_direction.py` to
  reproduce the tested research blocks from the
  retained export. These require only Python's standard library. Protocols and
  engine hashes are retained with results.
- Native fixture creation uses `research/BuildTesterFixture.mq5`; it copies
  174,528 M1 bars and 29,434,622 original cached ticks for January-June 2025.
  `research/RunNativeValidation.ps1` reruns the prepared native configuration.
- The former duplicate package is archived; the current installer deploys one EA
  and its receipt module, validates checksums, and restores backups on failure.

Remaining blockers are a credible positive edge, verified historical costs and
execution distributions, native/independent-model agreement for any proposed
strategy, and connected DEMO fault injection. Historical midnight floating equity
cannot be reconstructed exactly after a late first attachment. Broker corrections
to old ledger rows need statement reconciliation. Simulated rejection/queue/partial
fill probabilities are not measured. Stops cannot guarantee a maximum loss.

Do not interpret clean compilation, passing tests, or a completed backtest as
production readiness. No profitable strategy or combined portfolio is claimed.

## Experimental branch caution (2026-10-25)

All above native performance numbers refer to the earlier canonical M15 former-stop EA, NOT the expanded M5/retest-limit research version. The current research version has no native compilation or historical execution result. Risk now defaults to 1.0% with a 2.0% configured maximum, explicit fee/slippage allowance, and small-account min-lot/margin rejection. None of these changes is evidence of positive expectancy.
