# Cross-Metal Source-Ingestion Audit — 2026-10-19

**Purpose:** preserve the premeasurement loader correction for `LH-XAUUSD-CMR-2026-10-19`. This is an input-construction note only; no candidate/comparator plan, return, or performance statistic was calculated during the failed attempt or this audit.

## Failed premeasurement attempt

At runner commit `367271a241fe4d0d74bc8f9b3f0774187f7bf8ad`, the first `--stage screen` invocation stopped with exit code 2 while reading the eligible H.10 basket: `Australia 1971-02-12` had an empty `Exchange rate` cell. The source parser had already verified and loaded eligible 1960–1999 metals prices, but execution stopped before the USD index, model frame, plan builders, or any market-outcome calculation. No evidence or results artifact was written. The post-1999 branch was not numerically parsed.

## Pinned H.10 missing-value semantics

The H.10 file is pinned at `datasets/exchange-rates@c023dd8b8f879610641a7391c0394c3bbb42d0f7`, SHA-256 `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`. A bounded source-quality scan restricted to the registered eight currencies and dates before 2000-01 found **58,159 positive finite rates and 2,361 empty rate cells**; no other nonnumeric, non-finite, or non-positive eligible values were present. No post-1999 rates were converted in this scan.

The existing `scripts/build_longhistory_monthly_dataset.py` uses pandas' default empty-cell-to-NA behavior and drops missing `v` rows before building the daily cross-currency index. To match that pinned convention, the cross-metal loader now skips only blank eligible H.10 rate cells, records their counts per country, and still fails on malformed nonblank values, duplicate/out-of-order dates, missing months, or month-end basket coverage below 6/8. This is neither imputation nor a change to the registered currency basket or quote convention.

The synthetic H.10 fixture now includes (1) an eligible blank cell, (2) valid eligible rates, and (3) a nonnumeric post-1999 sentinel. It checks that the blank is excluded and the post-1999 rate is never converted. The frozen candidate, comparator builders, cost models, windows, bootstrap, thresholds, trial denominator, and gates are unchanged.
