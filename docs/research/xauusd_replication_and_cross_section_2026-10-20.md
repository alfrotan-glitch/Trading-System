# Replication and cross-section: is the gold result a feed artefact or a dead family?

**Date:** 2026-10-20
**Verdict:** `NO_VALIDATED_EDGE` (unchanged, and now better supported)
**Holdout status:** TEST 2022-2024 and OOS 2025-2026 **not read**. All work here is
inside DEV (window ends 2018-12-31).

The Edge Lab's first gated run (see `xauusd_edge_lab_verdict_2026-10-20.md`)
rejected 52 configurations, best `alpha_t` 2.14. That answers "did we find one",
not "should we keep looking". This study asks the two questions that decide
whether further search is worth anything:

1. Is the gold result a property of **one broker's price feed**? (cross-source)
2. Do these rule families work **anywhere**? (cross-section)

Both were pre-specified, and only **three** configurations were tested. Running
all 52 would reintroduce exactly the multiple-testing problem the gate exists to
prevent.

---

## 1. Cross-source: same instrument, same calendar, different broker

BaseMax gold (primary) and `ejtraderLabs/historical-data` gold (Apache-2.0,
pinned `fbd29b3c`) are independent MT5 exports. Both restricted to the shared
window **2012-05-15 → 2018-12-31**.

| Rule | BaseMax alpha/yr | BaseMax t | ejtrader alpha/yr | ejtrader t |
|---|---|---|---|---|
| `tsmom_d5` | +3.10% | 0.69 | +5.26% | 0.95 |
| `ma_50_200` | −0.43% | −0.11 | +0.72% | 0.16 |
| `volman_15_d60` | −0.66% | −0.75 | −0.66% | −0.60 |

Two things follow.

**The signals are not feed artefacts.** `tsmom_d5` is positive on both, with the
same order of magnitude. Whatever it is measuring, it is measuring it in the
market and not in the vendor's data.

**But the effect is much weaker than the headline.** On this 6.6-year window
`tsmom_d5` reaches only t=0.69 / 0.95, against t=2.11 on the full 2004-2018 DEV
window. The difference is not noise from a different broker — it is that most of
the apparent alpha sits outside 2012-2018.

`volman_15_d60` returns **−0.66% on both feeds, to two decimal places**. That is
a clean, independently confirmed negative result: volatility-managed exposure does
not beat buy-and-hold on gold.

## 2. Sub-period stability: where does the alpha come from?

BaseMax D1, DEV split in half. A real effect should be present in both halves.

| Rule | 2004-2011 | t | 2012-2018 | t |
|---|---|---|---|---|
| `tsmom_d5` | +10.67%/yr | 1.71 | +3.67%/yr | 0.83 |
| `ma_50_200` | +5.83%/yr | 1.08 | +0.16%/yr | 0.04 |
| `volman_15_d60` | **+3.52%/yr** | **2.43** | **−0.58%/yr** | −0.86 |

This is the most important table in the study.

`volman_15_d60` looked mildly interesting in the full DEV window (+1.0%/yr alpha).
It is now clear that **all of it** came from 2004-2011 — the great gold bull run,
when realised volatility was high and the vol target kept exposure near maximum.
Since 2012 the sign is negative. The pooled figure is an average of a live effect
and a dead one, which is precisely what a regime-dependent artefact looks like.

`tsmom_d5` decays from +10.67% to +3.67% and is insignificant in both halves. Its
full-period t=2.11 is two weak halves added together, not a stable edge.

## 3. Cross-section: do these families work on anything?

Same three rules, 12 instruments (gold plus 11 FX pairs), pre-holdout window.

| Rule | Positive in | Median alpha/yr | Sign-test p |
|---|---|---|---|
| `tsmom_d5` | **6/12** | −0.03% | 1.000 |
| `ma_50_200` | 7/12 | +0.73% | 0.564 |
| `volman_15_d60` | 2/12 | −0.32% | 0.021 |

`tsmom_d5` landing on exactly 6 of 12 is the signature of a coin flip. Trend
rules show no general validity across these instruments — the gold result was one
draw from a zero-mean distribution, not a member of a working family.

`volman_15_d60` is significantly **negative** (2/12, p=0.021). Across 11 FX pairs
and gold, volatility-managed long exposure underperforms simply holding. This
corroborates the gold finding independently: the mechanism is not mysterious — vol
targeting cuts exposure after volatility spikes, which is often just before the
recovery. It is a risk-management tool that costs return, and it should be
described that way rather than as alpha.

**Caveat that must not be dropped:** these 12 instruments are far from
independent. EURUSD, GBPUSD, EURGBP, EURJPY, USDJPY, GBPJPY, AUDJPY, USDCHF,
USDCAD and EURCHF share dominant USD/EUR/JPY factors, so the effective sample is
closer to 3-4. The p-values above are optimistic upper bounds, and the honest
reading is "no detectable consistency" rather than "proven inconsistency".

## 4. Power: what this could and could not have seen

The shared window gives ~6.1 years inside DEV, so the per-instrument detection
floor at `alpha_t = 2.5` is `2.5/sqrt(6.1) = 1.01` Sharpe.

A **null result on 6.1 years is inconclusive, not evidence of absence.** An SR 0.3
rule — a good live strategy — is invisible here. The cross-section's value is that
it tests *sign consistency* across many series, which is a different and more
forgiving question than per-instrument significance. It cannot rescue a rule, but
it can kill one, and for `volman` it did.

## 5. What this changes

Before this study, the position was "52 configurations failed on one gold dataset".
The obvious objection was that the dataset, the feed, or the harness was at fault.

That objection is now closed:

- The rules **do** reproduce across two independent brokers — the measurement is
  sound.
- The effect **is not stable within the sample** — it decays and, for `volman`,
  changes sign.
- The families **do not generalise** across instruments — 6 of 12 is a coin flip.

The result is not "our data was bad" or "our harness was broken". It is that these
price-derived rule families carry no reliable alpha on gold. Two of the three
probes are now understood mechanistically rather than merely rejected.

## 6. What this does not establish

- That no XAUUSD edge exists — only that these families, and price-derived rules
  generally, show nothing at SR ≳ 0.6.
- Anything about order flow, options-implied volatility, ETF flows or positioning.
  None are available in this environment, and all remain genuinely untested.
- Anything about the TEST or OOS periods, which stay unread.

## 7. Reproduction

```bash
python scripts/edgelab_cross_section.py            # this study
python scripts/edgelab_report.py --timeframes D1,H1 # the acceptance gate
```

Artifacts: `data/research/experiments/cross_section_*.json`.
Data: `data/raw/longhistory/historical-data-fbd29b3c.../` (gitignored, pinned).
