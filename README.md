# Autonomous Quant Research & Trading System

> Enterprise-grade, *science-first* quant platform. Default behavior: **PRESERVE CAPITAL / NO_TRADE**. Target: **XAUUSD on MT5**, architecture pluggable for any instrument/venue.

```
docs/   — Architecture, ADRs, domain, validation, security, plan
src/qts — Modular monolith (domain, data, execution, risk, research, validation, observability)
tests/  — Unit, property (Hypothesis), integration, determinism
configs/— YAML per env (dev/paper/live), live requires --confirm + secrets
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Ingest synthetic XAUUSD (no broker needed)
python -m qts data synthetic --rows 10000 --out data/raw/synthetic_XAUUSD_1m.csv
python -m qts data ingest --source csv --path data/raw/synthetic_XAUUSD_1m.csv --instrument XAUUSD --timeframe 1m
python -m qts data validate --version <printed-version>

# Deterministic backtest
python -m qts backtest --strategy sma_breakout --data-version <version> --seed 42
python -m qts backtest --strategy sma_breakout --data-version <version> --seed 42 --determinism-check

# Validation pipeline
python -m qts validate --strategy sma_breakout --data-version <version>

# Paper trading (needs MT5 or synthetic live feed)
python -m qts run --mode paper --strategy sma_breakout --data-version <version>

# Tests
pytest -q
pytest tests/property -q
pytest tests/integration -q --run-integration

# Health & audit
python -m qts health
python -m qts audit query --strategy sma_breakout --limit 20
```

## Invariants

- No strategy reaches `LIVE` without `ValidationReport.passed` + `RiskLimits.approved` + manual `--confirm live`.
- Risk is independent authority — can veto any `OrderIntent`.
- MT5 is external authority — fills reconciled, never assumed.
- All timestamps UTC ns; prices Decimal; event time ≠ processing time.

## Docs

Start with `docs/00-overview.md` → `docs/13-adrs.md` → `docs/01-architecture.md`.

## Status

Phase 0 foundation — deterministic backtest, risk, execution, validation, audit. See `docs/14-implementation-plan.md`.
