# DEMO Preregistration — XAUUSD Public Trend Benchmark

ID: H-TSMOM-01
Strategy: DEMO-XAUUSD-TREND-TSMOM-V1
Date: 2026-10-07

## Purpose

This is a DEMO-only forward measurement policy inspired by publicly documented
time-series momentum / trend-following practice. It is intentionally simple:
a frozen 15-minute-bar fast/slow EMA trend signal, fixed minimum size, protective stop, and
deterministic time exit.

Public evidence supports time-series momentum as a broad research mechanism;
it does not establish that this exact XAUUSD implementation is profitable
today. The system therefore treats this as UNVALIDATED until independent
research gates pass.

## Frozen parameters

- Bar timeframe: 15 minutes
- EMA fast: 12 completed bars
- EMA slow: 48 completed bars
- Stop distance: 3.00 USD
- Size: 0.01 lots
- Maximum hold: 4 hours
- Maximum 2 orders/day
- Minimum order interval: 30 minutes
- Maximum spread: 3 bps
- Maximum quote age: 5 seconds

## Entry

BUY when EMA12 crosses above EMA48 on a newly completed 15-minute bar; SELL when EMA12 crosses below EMA48. Partial bars are never evaluated.
No discretionary filtering or parameter changes are permitted during forward
observation.

## Exit and safety

Every order carries a protective stop. Positions are closed at the deterministic
time limit. The canonical DEMO pre-trade gate, identity pin, quote freshness,
spread, broker order check, idempotency, risk limits, kill switch, and
post-trade reconciliation remain authoritative.

## Research integrity

This policy is ELIGIBLE_DIAGNOSTIC, not ELIGIBLE. DEMO observations are
execution/forward evidence only and must not be used to fit parameters or
retroactively select the strategy. LIVE remains locked.

## Public inspiration

The design is based on openly published descriptions of time-series momentum
and trend-following from AQR and Man AHL. No proprietary source code,
private fund data, or confidential parameters are copied.

## Decision rule

The policy may place DEMO orders only when every runtime safety gate passes.
A positive DEMO result does not promote the strategy. Promotion requires the
existing independent validation and governance pipeline.
