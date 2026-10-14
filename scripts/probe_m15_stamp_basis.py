#!/usr/bin/env python3
"""Probe whether source M15 stamps mark the bar OPEN or the bar CLOSE.

Two independent, rule-based measurements (no strategy, no returns fitting):

1. **Maintenance-break signature.** CME/spot gold halts 17:00-18:00 ET. In UTC
   that is 22:00-23:00 during US standard time and 21:00-22:00 during US
   daylight time. With OPEN stamps the first bar stamped inside/after the halt
   behaves one way; with CLOSE stamps the pattern shifts one bar earlier. The
   probe counts bar presence by UTC hour in each DST season and reports which
   interpretation matches.

2. **NFP release spike location.** US payrolls are released at 08:30 ET on the
   first Friday of the month (12:30 UTC in EST, 13:30 UTC in EDT). The bar that
   CONTAINS the release carries the volatility spike. With open stamps that is
   the bar stamped 12:30/13:30; with close stamps it is the next bar,
   12:45/13:45. The probe compares normalised intrabar range and tick volume of
   candidate bars on event Fridays versus the same clock hours on control
   Fridays (train years only).

Deterministic and read-only. Writes
``data/evidence/longhistory/stamp_basis_probe.json`` (counts and ratios only,
no price rows).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import sources as S  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
RESEARCH_FILE = PROCESSED / "xauusd_basemax_utc_15m_20040611_20250228.csv"
OUT = REPO_ROOT / "data" / "evidence" / "longhistory" / "stamp_basis_probe.json"

#: Probe never looks at the 2020+ holdout: stamp basis is metadata, not a strategy.
PROBE_END = "2019-12-31"


def dst_flags(idx: pd.DatetimeIndex) -> pd.Series:
    """US daylight-saving flag per UTC stamp (True = EDT)."""
    et = idx.tz_localize("UTC").tz_convert("America/New_York")
    return pd.Series([bool(t.dst()) for t in et], index=idx)


def first_friday_et(year: int, month: int) -> pd.Timestamp:
    """Date of the first Friday of ``year-month`` in US Eastern."""
    d = pd.Timestamp(year=year, month=month, day=1)
    return d + pd.Timedelta(days=(4 - d.dayofweek) % 7)


def nfp_release_utc(year: int, month: int) -> pd.Timestamp:
    """08:30 ET release of the first-Friday payrolls report, as a UTC timestamp."""
    d = first_friday_et(year, month)
    local = pd.Timestamp(year=d.year, month=d.month, day=d.day, hour=8, minute=30)
    return local.tz_localize("America/New_York").tz_convert("UTC").tz_localize(None)


def probe_break_signature(bars: pd.DataFrame) -> dict:
    """Bar presence by UTC hour around the daily maintenance halt, by DST season.

    Predicted stamp patterns (CME/spot gold halts 17:00-18:00 ET; winter halt is
    [22:00, 23:00) UTC, summer halt is [21:00, 22:00) UTC):

    * OPEN stamps  : every stamp whose OPEN falls inside the halt is absent
      (winter: hour 22 empty, 23:00 present; summer: hour 21 empty, 22:00 present).
    * CLOSE stamps : the bar closing at halt start survives, bars closing inside
      the halt and at halt end are absent (winter: 22:00 present, 22:15-23:00
      absent, hour 23 otherwise full; summer: 21:00 present, 21:15-22:00 absent).
    """
    idx = pd.DatetimeIndex(bars.index)
    dst = dst_flags(idx)
    out: dict[str, object] = {}
    minute_sets: dict[str, dict[str, list[int]]] = {}
    for name, mask in (("dst_summer", dst), ("std_winter", ~dst)):
        hours_of_interest = (21, 22, 23) if name == "std_winter" else (20, 21, 22, 23)
        season = idx[mask & idx.hour.isin(hours_of_interest)]
        counts = {int(str(k)): int(v) for k, v in pd.Series(idx[mask].hour).value_counts().sort_index().items()}
        out[name] = {
            "bar_counts_by_utc_hour": counts,
            "distinct_days": int(idx[mask].normalize().nunique()),
            "minutes_by_hour": {
                str(h): sorted({int(m) for m in season[season.hour == h].minute}) for h in hours_of_interest
            },
        }
        minute_sets[name] = out[name]["minutes_by_hour"]  # type: ignore[assignment, index]

    w22 = minute_sets["std_winter"].get("22", [])
    w23_first = 0 in minute_sets["std_winter"].get("23", [])
    s21 = minute_sets["dst_summer"].get("21", [])
    s22_first = 0 in minute_sets["dst_summer"].get("22", [])
    observations = {
        "winter_hour22_minutes": w22,
        "winter_2300_present": w23_first,
        "summer_hour21_minutes": s21,
        "summer_2200_present": s22_first,
    }
    # OPEN predicts: winter 22 empty, 23:00 present, summer 21 empty, 22:00 present.
    # CLOSE predicts: winter 22 == [0], 23:00 absent, summer 21 == [0], 22:00 absent.
    open_votes = int(w22 == []) + int(w23_first) + int(s21 == []) + int(s22_first)
    close_votes = int(w22 == [0]) + int(not w23_first) + int(s21 == [0]) + int(not s22_first)
    out["interpretation_observations"] = observations
    out["open_stamp_votes"] = open_votes
    out["close_stamp_votes"] = close_votes
    out["break_probe_verdict"] = (
        "OPEN_STAMP" if open_votes >= 3 else ("CLOSE_STAMP" if close_votes >= 3 else "AMBIGUOUS")
    )
    return out


def probe_nfp_spike(bars: pd.DataFrame) -> dict:
    """Volatility/volume of the bar containing the 08:30 ET release vs controls."""
    idx = pd.DatetimeIndex(bars.index)
    norm_range = ((bars["high"] - bars["low"]) / bars["close"]).to_numpy(dtype=float)
    vol = bars["volume"].to_numpy(dtype=float)
    # Normalise intraday shape: divide each stamp's value by that stamp's
    # unconditional mean so the comparison is about *relative* spike location.
    hour_min = pd.Series(idx.hour * 60 + idx.minute, index=idx)
    base_r = pd.Series(norm_range, index=idx).groupby(hour_min).transform("mean")
    base_v = pd.Series(vol, index=idx).groupby(hour_min).transform("mean")
    rel_r = pd.Series(norm_range, index=idx) / base_r.replace(0.0, np.nan)
    rel_v = pd.Series(vol, index=idx) / base_v.replace(0.0, np.nan)

    rows = []
    for year in range(2004, 2020):
        for month in range(1, 13):
            rel = nfp_release_utc(year, month)
            if rel > pd.Timestamp(PROBE_END):
                continue
            for delta in (-15, 0, 15, 30):  # stamps around the release minute
                t = rel + pd.Timedelta(minutes=delta)
                hit = int(idx.searchsorted(t))
                if hit < len(idx) and idx[hit] == t:
                    rows.append(
                        {
                            "delta_min": delta,
                            "rel_r": float(rel_r.iloc[hit]),
                            "rel_v": float(rel_v.iloc[hit]),
                        }
                    )
    # Control Fridays: same clock minutes, non-first-Friday days.
    ctrl_rows = []
    event_keys = {
        (first_friday_et(y, m).year, first_friday_et(y, m).month)
        for y in range(2004, 2020)
        for m in range(1, 13)
    }
    for ts_key, pos in zip(idx, range(len(idx)), strict=False):
        if ts_key.year >= 2020:
            break
        if ts_key.dayofweek != 4 or ts_key.minute not in (15, 30, 45, 0):
            continue
        if (ts_key.year, ts_key.month) in event_keys and ts_key.hour in (12, 13) and ts_key.day <= 7:
            continue  # first-Friday daytime rows are event rows
        # keep controls only at the exact candidate minutes
        minute = ts_key.hour * 60 + ts_key.minute
        if minute in (12 * 60 + 15, 12 * 60 + 30, 12 * 60 + 45, 13 * 60 + 15, 13 * 60 + 30, 13 * 60 + 45):
            ctrl_rows.append({"delta_min": 0, "hour_min": minute, "rel_r": float(rel_r.iloc[pos]), "rel_v": float(rel_v.iloc[pos])})

    by_delta = {}
    df_rows = pd.DataFrame(rows)
    for delta in (-15, 0, 15, 30):
        sub = df_rows[df_rows["delta_min"] == delta]
        by_delta[str(delta)] = {
            "n": int(len(sub)),
            "mean_rel_range": round(float(sub["rel_r"].mean()), 4) if len(sub) else None,
            "mean_rel_volume": round(float(sub["rel_v"].mean()), 4) if len(sub) else None,
        }
    ctrl = pd.DataFrame(ctrl_rows)
    ctrl_by_hour_min = {
        str(int(str(k))): {
            "n": int(len(g)),
            "mean_rel_range": round(float(g["rel_r"].mean()), 4),
            "mean_rel_volume": round(float(g["rel_v"].mean()), 4),
        }
        for k, g in ctrl.groupby("hour_min")
    }
    # Decision: with OPEN stamps the spike is at delta 0 (stamps 12:30/13:30);
    # with CLOSE stamps it is at delta +15 (stamps 12:45/13:45).
    d0 = by_delta.get("0", {})
    d15 = by_delta.get("15", {})
    open_score = (d0.get("mean_rel_range") or 0.0) + (d0.get("mean_rel_volume") or 0.0)
    close_score = (d15.get("mean_rel_range") or 0.0) + (d15.get("mean_rel_volume") or 0.0)
    verdict = "OPEN_STAMP" if open_score > close_score else "CLOSE_STAMP"
    return {
        "release_minutes_by_delta": by_delta,
        "control_fridays_by_hour_min": ctrl_by_hour_min,
        "open_stamp_score": round(open_score, 4),
        "close_stamp_score": round(close_score, 4),
        "nfp_probe_verdict": verdict,
    }


def main() -> int:
    if not RESEARCH_FILE.is_file():
        raise SystemExit("research series missing; run scripts/build_longhistory_dataset.py first")
    bars = S.read_csv_utc(RESEARCH_FILE)
    idx = pd.DatetimeIndex(bars.index)
    bars = bars.loc[idx <= pd.Timestamp(PROBE_END)]
    idx = pd.DatetimeIndex(bars.index)
    break_sig = probe_break_signature(bars)
    nfp = probe_nfp_spike(bars)
    # Overall verdict: both probes must agree to establish the basis.
    break_verdict = str(break_sig["break_probe_verdict"])
    agree = break_verdict == nfp["nfp_probe_verdict"]
    out = {
        "schema": "qts.stamp_basis_probe.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "xauusd_basemax_utc_15m_20040611_20250228.csv",
        "probe_window": ["2004-06-11", PROBE_END],
        "rows_probed": int(len(bars)),
        "maintenance_break_probe": break_sig,
        "nfp_release_probe": nfp,
        "break_probe_verdict": break_verdict,
        "probes_agree": agree,
        "established_basis": break_verdict if agree and break_verdict != "AMBIGUOUS" else "UNRESOLVED",
        "notes": [
            "Probe uses bar presence and tick-volume/range location only; no return sign is examined.",
            "First-Friday rule approximates the payrolls calendar; rare off-cycle releases add noise but no direction.",
            "Established basis applies to the BaseMax research series after server->UTC conversion.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"break_verdict={break_verdict} nfp_verdict={nfp['nfp_probe_verdict']} agree={agree}")
    print(f"established_basis={out['established_basis']}")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
