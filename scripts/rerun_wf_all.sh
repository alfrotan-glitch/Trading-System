#!/usr/bin/env bash
# Re-run every walk-forward family after the kill-switch truncation fix.
# Every number produced before this fix described only the first ~18% of the
# series and must be considered invalid.
set -u
cd /home/user/Trading-System
V=20261009-010+2b024334-1ba57af7
PY=.venv/bin/python

run() {
  local name="$1"; shift
  echo "######## $name ########"
  timeout 1500 $PY scripts/run_walkforward_research.py \
    --data-version "$V" \
    --out "data/evidence/wf_${name}_fixed.json" "$@" 2>&1
  echo "exit=$?"
}

run trend           --family trend --folds 4
run breakout        --family breakout --folds 4
run mean_reversion  --family mean_reversion --folds 4
run trend_stops     --family trend --folds 4 --stop-distance-usd 40 --max-hold-bars 96
run breakout_8fold  --family breakout --folds 8 --stop-distance-usd 40 --max-hold-bars 96
run breakout_cost2x --family breakout --folds 4 --stop-distance-usd 40 --max-hold-bars 96 --spread-bps 6 --slippage-bps 4 --commission-per-lot 14
echo "######## ALL DONE ########"
