#!/usr/bin/env python3
"""Independent verification of the frozen champions (stdlib + numpy only).

Recomputes ``ts9_lo`` and ``veto9`` evaluation-window results from the
built monthly CSV with a hand-written simulation that shares **no code**
with ``qts.research.longhistory`` (no engine, no signal builders): if a
bug in the research engine inflated the champions, this script must
disagree with the committed evidence. Writes
``data/evidence/longhistory/champion_independent_verification.json``.

Mirror of the frozen conventions: decision at month ``t`` fills at
month ``t+1``'s average (o=h=l=c series; P&L accrues on the
average-to-average step); size = clip(0.10 / (12-month log-return vol
x sqrt(12)), max 1.0) x equity, rebalanced monthly; costs per side
``(3bps/2 + 1bp) + $7/(100 oz x price)`` of traded notional; window
starts flat with $10,000 and force-closes at the final average.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_FILE = REPO_ROOT / "data/raw/longhistory/processed/xauusd_worldbank_monthly_utc_197301_202609.csv"
EVIDENCE = REPO_ROOT / "data/evidence/longhistory/champion_independent_verification.json"

INITIAL = 10_000.0
SPREAD_BPS, SLIP_BPS, COMMISSION = 3.0, 1.0, 7.0


def side_rate(price: float) -> float:
    return SPREAD_BPS / 2 / 1e4 + SLIP_BPS / 1e4 + COMMISSION / (100.0 * price)


def load() -> tuple[list[str], np.ndarray, np.ndarray]:
    dates, close, usd = [], [], []
    with CSV_FILE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            dates.append(row["date"][:10])
            close.append(float(row["close"]))
            usd.append(float(row["usd"]))
    return dates, np.array(close), np.array(usd)


def states(close: np.ndarray, usd: np.ndarray) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    n = len(close)
    logret = np.full(n, np.nan)
    logret[1:] = np.log(close[1:] / close[:-1])
    vol = np.full(n, np.nan)
    for t in range(12, n):
        vol[t] = float(np.std(logret[t - 11 : t + 1], ddof=1)) * math.sqrt(12)
    frac = np.where(np.isfinite(vol) & (vol > 0), np.minimum(0.10 / np.where(vol > 0, vol, np.nan), 1.0), np.nan)
    trend9 = np.full(n, np.nan)
    trend9[9:] = close[9:] / close[:-9] - 1.0
    usd12 = np.full(n, np.nan)
    usd12[12:] = usd[12:] / usd[:-12] - 1.0
    ts = np.where(trend9 > 0, 1.0, 0.0)
    veto = np.where(trend9 > 0, 1.0, np.where((trend9 < 0) & (usd12 > 0), -1.0, 0.0))
    return {"ts9_lo": (ts, frac), "veto9": (veto, frac)}


def simulate(
    dates: list[str], close: np.ndarray, state: np.ndarray, frac: np.ndarray, start: str, end: str
) -> dict[str, float]:
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    equity = INITIAL
    oz = 0.0
    equities: list[float] = []
    entries = 0
    pending: tuple[float, float] | None = None  # window starts flat
    for k, m in enumerate(idx):
        if oz != 0.0:
            equity += oz * (close[m] - close[m - 1])  # average-to-average step
        if pending is not None:
            st, fr = pending
            if math.isfinite(st) and math.isfinite(fr) and fr > 0.0:
                desired = st * fr * equity / close[m]
                equity -= abs(desired - oz) * close[m] * side_rate(close[m])
                if oz == 0.0 and desired != 0.0:
                    entries += 1
                oz = desired
        # decision at this month's close, executed at the next average
        pending = (float(state[m]), float(frac[m])) if k + 1 < len(idx) else None
        equities.append(equity)
    if oz != 0.0:  # forced close at final average
        equity -= abs(oz) * close[idx[-1]] * side_rate(close[idx[-1]])
        equities[-1] = equity
    eq = np.array(equities)
    rets = np.diff(np.concatenate([[INITIAL], eq])) / np.concatenate([[INITIAL], eq])[:-1]
    sharpe = float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(12)) if len(rets) > 2 else 0.0
    peak = np.maximum.accumulate(np.concatenate([[INITIAL], eq]))
    maxdd = float(np.min(np.concatenate([[INITIAL], eq]) / peak - 1.0))
    return {
        "net_usd": round(equity - INITIAL, 2),
        "sharpe": round(sharpe, 4),
        "entries": entries,
        "max_drawdown": round(maxdd, 4),
        "months": len(idx),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import subprocess
    import sys

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ensure-data",
        action="store_true",
        help="fetch and build the canonical monthly dataset first if missing",
    )
    args = parser.parse_args(argv)
    if args.ensure_data and not CSV_FILE.is_file():
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "build_longhistory_monthly_dataset.py"),
                "--ensure-sources",
            ],
            check=True,
        )
    if not CSV_FILE.is_file():
        raise SystemExit(
            f"missing {CSV_FILE}; run:\n"
            "  python scripts/build_longhistory_monthly_dataset.py --ensure-sources\n"
            "(or pass --ensure-data)"
        )
    dates, close, usd = load()
    st = states(close, usd)
    windows = {"evaluation_2000_2026": ("2000-01-01", "2026-09-30")}
    out: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "method": "independent stdlib+numpy reimplementation; no qts.research.longhistory imports",
        "reference_evidence": {
            "ts9_lo": {"net_usd": 70989.0, "sharpe": 0.837, "source": "ensemble/hybrid_research_final.json"},
            "veto9": {"net_usd": 49897.0, "sharpe": 0.662, "source": "hybrid_research_final.json"},
        },
        "windows": {},
    }
    ok = True
    for wname, (s, e) in windows.items():
        rec: dict[str, object] = {}
        for cid, (state, frac) in st.items():
            got = simulate(dates, close, state, frac, s, e)
            ref = out["reference_evidence"][cid]  # type: ignore[index]
            net_dev = abs(got["net_usd"] - ref["net_usd"]) / ref["net_usd"]  # type: ignore[operator]
            sr_dev = abs(got["sharpe"] - ref["sharpe"])  # type: ignore[operator]
            passed = bool(net_dev <= 0.01 and sr_dev <= 0.02)
            ok &= passed
            rec[cid] = {**got, "net_deviation_pct": round(100 * net_dev, 3),
                        "sharpe_deviation": round(sr_dev, 4), "within_tolerance": passed}
        out["windows"][wname] = rec  # type: ignore[index]
    out["verdict"] = "AGREE" if ok else "DISAGREE"
    EVIDENCE.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
