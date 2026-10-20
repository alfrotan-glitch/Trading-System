"""XAUUSD research data preparation — build the canonical bar store for edge work.

Sources are pinned by commit in ``data/evidence/longhistory/source_manifest.json``:

* ``basemax`` — M15 XAUUSD, 2004-06 → 2025-09 (primary discovery history)
* ``vudo805`` — M15 mid OHLC derived from real Dukascopy bid/ask ticks,
  2025-08 → 2026-09 (independent source, untouched OOS)

This module does not "clean" prices. It rejects structural defects (duplicate
timestamps, non-monotonic or zero-length bars) and records them; it never fills,
interpolates or smooths. Missing bars stay missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/longhistory")
OUT = Path("data/research")
BASE_MAX_GLOB = "XAUUSD-LSTM-*/XAU_15m_data.csv"
#: BaseMax bar labels are a fixed UTC+3 MT5 server clock, proven in
#: ``data/research/data_quality_report.json``: the daily break sits at 00:00 server
#: and, shifted by -3h, the weekly boundary (Sun 22:00 open / Fri 20:45 close)
#: matches the independent Dukascopy (true UTC) series exactly.
BASE_MAX_UTC_OFFSET_HOURS = -3
VUDO_GLOB = "forex-price-simulator-*/data/XAUUSD/*.parquet"


@dataclass
class QualityReport:
    source: str
    rows_in: int
    rows_out: int
    first: str | None = None
    last: str | None = None
    duplicates: int = 0
    non_monotonic: int = 0
    bad_ohlc: int = 0
    non_positive: int = 0
    median_gap_minutes: float | None = None
    missing_bars_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _finalize(df: pd.DataFrame, source: str, rows_in: int) -> tuple[pd.DataFrame, QualityReport]:
    rep = QualityReport(source=source, rows_in=rows_in, rows_out=0)
    df = df.copy()
    rep.duplicates = int(df.index.duplicated().sum())
    df = df[~df.index.duplicated(keep="first")]
    rep.non_monotonic = int((df.index.to_series().diff().dt.total_seconds() <= 0).sum())
    df = df.sort_index()

    ohlc = df[["open", "high", "low", "close"]]
    rep.non_positive = int((ohlc <= 0).any(axis=1).sum())
    bad = (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
        | (df["high"] < df["low"])
    )
    rep.bad_ohlc = int(bad.sum())
    df = df[~bad]
    df = df[(ohlc > 0).all(axis=1).reindex(df.index, fill_value=False)]

    if len(df) > 2:
        gaps = df.index.to_series().diff().dt.total_seconds().dropna() / 60.0
        rep.median_gap_minutes = float(gaps.median())
        rep.notes.append(f"gap p50={gaps.median():.0f}m p95={gaps.quantile(0.95):.0f}m max={gaps.max():.0f}m")

    rep.rows_out = len(df)
    if len(df):
        rep.first = df.index[0].isoformat()
        rep.last = df.index[-1].isoformat()
    return df, rep


def load_basemax() -> tuple[pd.DataFrame, QualityReport, dict]:
    path = sorted(RAW.glob(BASE_MAX_GLOB))[0]
    df = pd.read_csv(path, sep=";", dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    ts = pd.to_datetime(df["date"].str.strip(), format="%Y.%m.%d %H:%M", utc=True)
    out = pd.DataFrame(
        {
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df.get("volume"), errors="coerce"),
        }
    )
    out.index = pd.DatetimeIndex(ts, name="time") + pd.Timedelta(hours=BASE_MAX_UTC_OFFSET_HOURS)
    out = out.dropna(subset=["open", "high", "low", "close"])
    clean, rep = _finalize(out, "basemax_m15", len(df))
    rep.notes.append(f"timestamps relabelled from UTC+3 server clock to true UTC (offset {BASE_MAX_UTC_OFFSET_HOURS}h)")
    meta = {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "utc_offset_hours_applied": BASE_MAX_UTC_OFFSET_HOURS,
    }
    return clean, rep, meta


def load_vudo() -> tuple[pd.DataFrame, QualityReport, dict]:
    files = sorted(RAW.glob(VUDO_GLOB))
    frames = []
    digests = {}
    for f in files:
        part = pd.read_parquet(f)
        frames.append(part)
        digests[f.name] = _sha256(f)
    df = pd.concat(frames, ignore_index=False) if frames else pd.DataFrame()
    if df.empty:
        raise RuntimeError("no vudo805 parquet files found")
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.index, pd.DatetimeIndex):  # these files are index-keyed
        ts = pd.to_datetime(df.index, utc=True)
    else:
        tcol = next(c for c in ("time", "timestamp", "date", "datetime") if c in df.columns)
        ts = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    if getattr(ts.dtype, "tz", None) is None:
        ts = ts.tz_localize("UTC")
    out = df[["open", "high", "low", "close"]].copy()
    # `ticks` is a real per-bar tick count; `volume` is the older column name.
    vol_col = next((c for c in ("ticks", "volume") if c in df.columns), None)
    out["volume"] = df[vol_col] if vol_col else pd.NA
    out.index = pd.DatetimeIndex(ts, name="time")
    out = out.dropna(subset=["open", "high", "low", "close"])
    clean, rep = _finalize(out, "vudo805_dukascopy_m15", len(df))
    meta = {"files": len(files), "sha256": digests}
    return clean, rep, meta


def coverage(df: pd.DataFrame) -> dict:
    """Bars per calendar year plus the observed trading-week structure."""
    per_year = df.groupby(df.index.year).size().to_dict()
    dow = df.groupby(df.index.dayofweek).size().to_dict()
    hour = df.groupby(df.index.hour).size().to_dict()
    return {
        "bars_per_year": {int(k): int(v) for k, v in per_year.items()},
        "bars_by_weekday": {int(k): int(v) for k, v in dow.items()},
        "bars_by_hour_utc": {int(k): int(v) for k, v in hour.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    bm, bm_rep, bm_meta = load_basemax()
    vu, vu_rep, vu_meta = load_vudo()

    bm.to_parquet(out / "xauusd_m15_basemax.parquet")
    vu.to_parquet(out / "xauusd_m15_vudo.parquet")

    # Cross-source agreement in the overlap window. Two independent feeds that
    # disagree by more than a few dollars cannot both be right; the check makes
    # that visible instead of assuming the newer file is better.
    overlap = bm.index.intersection(vu.index)
    agreement: dict = {"overlap_bars": int(len(overlap))}
    if len(overlap) > 100:
        a = bm.loc[overlap, "close"]
        b = vu.loc[overlap, "close"]
        diff = (a - b).abs()
        agreement.update(
            {
                "close_diff_median_usd": float(diff.median()),
                "close_diff_p95_usd": float(diff.quantile(0.95)),
                "close_diff_max_usd": float(diff.max()),
                "corr": float(a.corr(b)),
            }
        )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "basemax": {**bm_rep.as_dict(), **coverage(bm), "source_meta": bm_meta},
        "vudo": {**vu_rep.as_dict(), **coverage(vu), "source_meta": {"files": vu_meta["files"]}},
        "cross_source": agreement,
    }
    (out / "data_quality_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps({k: report[k] for k in ("basemax", "vudo", "cross_source")}, indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()
