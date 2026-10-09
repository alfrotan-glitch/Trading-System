#!/usr/bin/env bash
# Reproduce every walk-forward result in
# docs/research/walkforward_findings_2026-10-09.md.
#
# Requires the real 15m XAUUSD dataset to be ingested:
#   python scripts/acquire_xauusd_dukascopy.py --source-dir <mirror clone> --ingest
# then confirm the data version:
#   .venv/bin/python -c "from qts.data.store import SqliteParquetDataStore; \
#     print([m for m in SqliteParquetDataStore().list_manifests()])"
#
# Every run reports `coverage`. If coverage is below 100% the result is
# truncated and must not be reported as a strategy result — see
# tests/unit/test_backtest_halt_detection.py.
set -u
cd "$(dirname "$0")/.."
V=${QTS_DATA_VERSION:-20261009-010+2b024334-1ba57af7}
PY=${PYTHON:-.venv/bin/python}

run() {
  local name="$1"; shift
  echo "######## $name ########"
  timeout 2400 $PY scripts/run_walkforward_research.py \
    --data-version "$V" \
    --out "data/evidence/wf_${name}.json" "$@" 2>&1
  echo "exit=$?"
}

STOPS=(--stop-distance-usd 40 --max-hold-bars 96)
COST2=(--spread-bps 6 --slippage-bps 4 --commission-per-lot 14)
COST3=(--spread-bps 9 --slippage-bps 6 --commission-per-lot 21)

# Bare families, 4 folds.
run trend            --family trend           --folds 4
run breakout         --family breakout        --folds 4
run mean_reversion   --family mean_reversion  --folds 4

# With risk management.
run breakout_stops   --family breakout --folds 4 "${STOPS[@]}"
run trend_stops      --family trend    --folds 4 "${STOPS[@]}"

# Robustness: finer partition and cost stress.
run breakout_8fold      --family breakout --folds 8 "${STOPS[@]}"
run breakout_cost2x     --family breakout --folds 4 "${STOPS[@]}" "${COST2[@]}"
run trend_stops_8fold   --family trend    --folds 8 "${STOPS[@]}"
run trend_stops_cost2x  --family trend    --folds 4 "${STOPS[@]}" "${COST2[@]}"
run trend_stops_cost3x  --family trend    --folds 4 "${STOPS[@]}" "${COST3[@]}"

# These two trade on nearly every bar; the grid is capped so they finish.
run momentum    --family momentum   --folds 4 "${STOPS[@]}" --max-configs 4
run volatility  --family volatility --folds 4 "${STOPS[@]}" --max-configs 4

echo "######## ALL DONE ########"
