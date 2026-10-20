# 51 years of gold: what extra history buys, and what it rules out

**Date:** 2026-10-20
**Verdict:** `NO_VALIDATED_EDGE` — but for sharper reasons than before.
**Holdout:** 2020-2024 was read **once**, for `tsmom_1m`, and rejected it.

---

## 1. Why 51 years

The M15 study had 17.8 years of DEV data. With `alpha_t = SR * sqrt(years)`, the
2.5 threshold implies a detection floor of Sharpe **0.59** — meaning a genuinely
good SR 0.4 strategy could not have been found even if it were real.

Extending the history is the only way to gain power that does not come from
loosening the gate. At **51 years** the floor falls to **SR 0.35**.

**Data:** FRED `GOLDAMGBD228NLBM` (LBMA Gold Price AM fix), 1969-01-02 → 2019-12-31,
12,894 daily bars. Macro: `GS10` (10y Treasury, monthly, 1953+) and `CPIAUCSL`
(CPI-U, monthly, 1947+), giving a real-yield proxy `GS10 − CPI_YoY` from 1969.

The proxy is **ex-post realised** inflation, so it is deliberately shifted **two
months** — one for the CPI release lag, one for safety. That can only understate a
real-time signal; it cannot manufacture one. All three series are hashed in
`data/research/longgold/provenance.json`.

**Caveat that shapes everything below:** the LBMA fix is a benchmark snapshot at
10:30 London, not an executable quote. It measures whether an effect exists. It
does not establish that you could capture it.

## 2. The tests

16 configurations in 8 families, fixed before running, with reasons rather than
parameter sweeps: real yields (3), inflation (2), trend at documented TSMOM
horizons (5), mean reversion (2), calendar (2), regime conditioning (2).

Split: DEV 1969-2000, VAL 2001-2010, TEST 2011-2019, holdout 2020-2024 on a
different, tradable dataset.

## 3. What failed

| Family | Best DEV alpha t | Note |
|---|---|---|
| real yield | 1.56 | the canonical gold driver, and it does not time gold |
| inflation | 1.30 | hedging claim not supported at trading horizons |
| calendar (Sep-Nov, turn-of-month) | 0.33 | turn-of-month is **negative** (t=−1.43) |
| mean reversion | −3.84 | `reversal_1m` is significant with the **wrong sign** — gold continues, it does not revert |
| regime | 1.74 | `trend_lowvol` positive in all decades but underpowered |

Two cleared DEV and both died for identifiable reasons.

### `ma_trend_12m`: a 1970s effect

DEV alpha t=2.85, DSR 0.994 — a clean pass. By decade:

| 1969s | 1979s | 1989s | 1999s | 2009s | 2019s |
|---|---|---|---|---|---|
| **+4.8%** | +1.0% | −1.2% | −0.8% | +0.1% | +0.0% |

The entire alpha is the post-Bretton-Woods gold bull market, when gold ran from
$35 to $850. Trend-following had something to follow. Since 1989 the sign is
negative or zero. A regime that has not existed in 45 years is not a strategy.

### `tsmom_1m`: the closest call, and why it still failed

One-month time-series momentum — within the documented Moskowitz–Ooi–Pedersen
horizon set — produced the most consistent result in the project:

| Sample | Alpha/yr | t |
|---|---|---|
| LBMA fix 1969-2019 | +8.0% | **2.91** |
| Per decade | +11.7, +9.5, +5.5, +5.4, +4.7, +14.6 | positive 6/6 |
| LBMA fix 2004-2019 | +6.6% | 1.46 |
| **Tradable closes 2004-2019** | +3.5% | 0.94 |
| **Tradable closes 2020-2024 (holdout)** | **−2.1%** | −0.38 |

It cleared DEV (t=2.59, DSR 0.964), kept its sign on VAL (+2.3%) and TEST (+7.2%),
and then failed on data it had never seen.

The same-period comparison is the important column. On the LBMA fix the alpha is
+6.6%; on tradable close data for the same years it is +3.5%. **Part of the
51-year result was an artifact of measuring 10:30 fixings rather than tradable
closes.** That is a methodological finding worth more than the strategy: long
benchmark-fix histories systematically flatter short-horizon momentum, because
fix-to-fix returns embed a daily liquidity cycle that a trader cannot capture.

## 4. Gold/silver relative value

Both directions were declared in advance, since theory supports each: mean
reversion (ratio extremes resolve) and stress momentum (a high ratio marks a
regime where gold keeps winning).

| Hypothesis | DEV alpha t | Validity |
|---|---|---|
| mean reversion, 10y median | −0.66 | negative in every window |
| stress momentum, 10y median | +0.52 | positive 4/4 windows but t<1 throughout |
| extreme only (z < −1) | −0.02 | nothing |

0 DEV survivors. The ratio's 14 → 123 range is real, but it does not translate
into a gold-timing edge. Reproduce: `scripts/edgelab_gsr_run.py`.

## 5. What 51 years actually establishes

- **No price-, macro-, calendar- or relative-value rule among ~75 tested produces
  alpha that survives DEV→VAL→TEST→holdout on tradable prices.** This is now a
  statement with 3x the power of the M15 study.
- **The detection floor is SR 0.35.** Effects smaller than that remain invisible;
  the statement is "no edge above SR 0.35", not "no edge".
- **Benchmark-fix data overstates short-horizon momentum.** Any future long-history
  work must validate on tradable closes before believing a fix-based result.
- **Gold's tradable autocorrelation has decayed.** The 1970s trend effect and the
  pre-2019 1-month momentum both fail on post-2019 data.

## 6. What would change the answer

Not more history and not more price variants. The inputs that could change it are
the ones this environment cannot reach, each attempted and logged in
`docs/research/experiment_register.md`:

- CFTC positioning history (site unreachable, no long mirror on GitHub)
- broker tick data (upstream release download fails)
- measured broker costs (no terminal here; costs stay ASSUMED)
- options-implied volatility (no verified long series)

## 7. Reproduction

```bash
python scripts/edgelab_prepare_longgold.py    # 51-year store + provenance
python scripts/edgelab_longhistory_run.py     # 16 hypotheses through the gate
python scripts/edgelab_gsr_run.py             # gold/silver ratio
```
