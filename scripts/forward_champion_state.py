#!/usr/bin/env python3
"""Print/record the frozen champions' current would-be state (research only).

Reads the built monthly research series and reports what the two frozen
forward-validation champions (``ts9_lo``, ``veto9``) would hold as of the
last published month-end, under
``docs/research/forward_validation_champions_2026-10-17.md``. This is a
paper-observation record: it submits nothing, anywhere.

Usage::

    python scripts/forward_champion_state.py            # print only
    python scripts/forward_champion_state.py --record   # also write evidence JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import forward as FWD  # noqa: E402

RESEARCH_FILE = (
    REPO_ROOT / "data/raw/longhistory/processed/xauusd_worldbank_monthly_utc_197301_202609.csv"
)
EVIDENCE = REPO_ROOT / "data/evidence/longhistory/forward_champions_state.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="write the evidence JSON")
    args = parser.parse_args()

    raw = pd.read_csv(RESEARCH_FILE)
    index = pd.to_datetime(raw["date"], utc=True).dt.tz_convert(None)
    frame = raw[["open", "high", "low", "close", "usd"]].astype(float)
    frame.index = pd.DatetimeIndex(index, name="utc")

    states = FWD.current_states(frame)
    record = {
        "protocol": "forward_validation_champions_2026-10-17",
        "generated_at": datetime.now(UTC).isoformat(),
        "nature": "paper observation only; no order, no broker, no DEMO/LIVE state",
        "champions": states,
    }
    print(json.dumps(record, indent=2))
    if args.record:
        EVIDENCE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"recorded: {EVIDENCE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
