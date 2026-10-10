"""Parsers, clock normalisation and quality checks for third-party XAUUSD bars.

Each parser returns a frame indexed by the timestamp AS STAMPED by its source
(``stamp_basis``). ``to_utc`` converts that to UTC explicitly. Nothing in this
module invents, interpolates or relabels a bar: gaps stay gaps and the quality
report counts them.

Clock findings (see ``docs/research/longhistory_data_provenance_2026-10-10.md``)
------------------------------------------------------------------------------
* ``BaseMax`` stamps are not UTC. Cross-correlating its 15-minute returns with
  the explicitly-UTC Yuan series gives a best shift of +3 h in US-DST months and
  +2 h otherwise (see ``clock_fit``). That is the common GMT+2/GMT+3 broker
  server convention with US DST, so ``server_gmt23_to_utc`` applies it.
* ``ejtraderLabs`` stamps and prices (x100 points) are the same series as
  BaseMax; they are kept for provenance checks but are not counted as a second
  source.
* Yuan and Dukascopy stamps are explicit UTC.
"""

from __future__ import annotations

import csv
import glob
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

OHLC_COLUMNS = ["open", "high", "low", "close", "volume"]
SERVER_OFFSET_HOURS_STANDARD = 2  # GMT+2 outside US daylight-saving time
SERVER_OFFSET_HOURS_DST = 3  # GMT+3 while US daylight-saving time is in effect
BAR_MINUTES = 15


@dataclass(frozen=True)
class QualityReport:
    """Machine-readable description of one series. Contains no price data."""

    name: str
    rows: int
    first_stamp: str | None
    last_stamp: str | None
    duplicate_stamps: int
    non_monotonic_steps: int
    ohlc_violations: int
    nonpositive_prices: int
    nan_cells: int
    off_grid_steps: int
    bars_by_year: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rows": self.rows,
            "first_stamp": self.first_stamp,
            "last_stamp": self.last_stamp,
            "duplicate_stamps": self.duplicate_stamps,
            "non_monotonic_steps": self.non_monotonic_steps,
            "ohlc_violations": self.ohlc_violations,
            "nonpositive_prices": self.nonpositive_prices,
            "nan_cells": self.nan_cells,
            "off_grid_steps": self.off_grid_steps,
            "bars_by_year": dict(self.bars_by_year),
            "notes": list(self.notes),
        }


def sha256_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_basemax_csv(path: Path) -> pd.DataFrame:
    """``Date;Open;High;Low;Close;Volume`` with ``YYYY.MM.DD HH:MM`` stamps (server clock)."""
    raw = pd.read_csv(path, sep=";")
    raw.columns = ["stamp", "open", "high", "low", "close", "volume"]
    index = pd.to_datetime(raw["stamp"], format="%Y.%m.%d %H:%M", errors="raise")
    frame = raw[OHLC_COLUMNS].astype(float)
    frame.index = pd.DatetimeIndex(index, name="stamp")
    return frame


def parse_ejt_m15_csv(path: Path, price_scale: float = 0.01) -> pd.DataFrame:
    """``Date,open,high,low,close,tick_volume`` with prices in points (x100)."""
    raw = pd.read_csv(path)
    index = pd.to_datetime(raw["Date"], format="%Y-%m-%d %H:%M:%S", errors="raise")
    frame = raw[["open", "high", "low", "close", "tick_volume"]].astype(float)
    frame.columns = OHLC_COLUMNS
    frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]] * price_scale
    frame.index = pd.DatetimeIndex(index, name="stamp")
    return frame


def parse_yuan_dir(directory: Path) -> pd.DataFrame:
    """Concatenate Yuan PT15M chunks. Stamps are RFC3339 UTC (``...Z``)."""
    files = sorted(glob.glob(str(directory / "*.csv")))
    if not files:
        raise FileNotFoundError(f"no Yuan PT15M csv files under {directory}")
    frames = []
    for file in files:
        raw = pd.read_csv(file)
        stamps = pd.to_datetime(raw["time"], utc=True).dt.tz_convert(None)
        frame = raw[["open", "high", "low", "close", "volume"]].astype(float)
        frame.index = pd.DatetimeIndex(stamps, name="stamp")
        frames.append(frame)
    combined = pd.concat(frames).sort_index()
    # Chunk boundaries may repeat a bar. Identical repeats are harmless and are
    # dropped; a repeat with DIFFERENT values is refused.
    dup = combined.index.duplicated(keep=False)
    if dup.any():
        dupes = combined[dup]
        if not dupes.groupby(level=0).nunique().le(1).all().all():
            raise ValueError("Yuan chunks contain conflicting duplicate bars; refusing to merge")
        combined = combined[~combined.index.duplicated(keep="first")]
    return combined


def parse_duka_parquet_dir(directory: Path) -> pd.DataFrame:
    """Dukascopy mirror parquet parts (index is UTC, timezone-naive)."""
    import pyarrow  # noqa: F401  (engine must exist; fail early with a clear error)

    files = sorted(glob.glob(str(directory / "XAUUSD_*.parquet")))
    if not files:
        raise FileNotFoundError(f"no XAUUSD parquet files under {directory}")
    frames = []
    for file in files:
        part = pd.read_parquet(file, columns=["open", "high", "low", "close", "ticks"])
        frames.append(part)
    combined = pd.concat(frames).sort_index()
    idx = pd.DatetimeIndex(combined.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    combined.index = pd.DatetimeIndex(idx, name="stamp")
    combined = combined.rename(columns={"ticks": "volume"})
    return combined[OHLC_COLUMNS].astype(float)


def server_gmt23_to_utc(stamps: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Convert GMT+2 / GMT+3 (US-DST) broker-server stamps to naive UTC.

    A stamp ``s`` is UTC+3 when US Eastern daylight-saving time is in effect at
    the corresponding UTC instant, and UTC+2 otherwise. The candidate instant is
    ``s - 3h``; if New York is on DST there, the offset is +3h, otherwise +2h.
    Ambiguity is confined to the one or two hours around a switch.
    """
    s = pd.DatetimeIndex(stamps)
    cand = s - pd.Timedelta(hours=SERVER_OFFSET_HOURS_DST)
    ny_wall = pd.DatetimeIndex(cand).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    ny_offset_h = (ny_wall - cand) / pd.Timedelta(hours=1)
    dst = np.asarray(ny_offset_h == -4.0)
    out = np.where(dst, cand.values, (s - pd.Timedelta(hours=SERVER_OFFSET_HOURS_STANDARD)).values)
    return pd.DatetimeIndex(out, name="utc")


def to_utc(frame: pd.DataFrame, stamp_basis: str) -> pd.DataFrame:
    """Return ``frame`` re-indexed to naive UTC bar opens, sorted and unique.

    ``stamp_basis`` is one of ``utc`` or ``server_gmt23_us_dst``.
    """
    if stamp_basis == "utc":
        index = pd.DatetimeIndex(frame.index, name="utc")
    elif stamp_basis == "server_gmt23_us_dst":
        index = server_gmt23_to_utc(pd.DatetimeIndex(frame.index))
    else:
        raise ValueError(f"unknown stamp basis {stamp_basis!r}")
    out = frame.copy()
    out.index = index
    return out.sort_index()


def clock_fit(reference: pd.DataFrame, candidate: pd.DataFrame, hours: range = range(-4, 5)) -> dict[str, Any]:
    """Best whole-hour shift of ``candidate`` stamps that matches ``reference`` returns.

    Both frames must be on the 15-minute grid. Returns the correlation at each
    shift so the decision is inspectable.
    """
    ref_r = np.log(reference["close"]).diff()
    cand_close = np.log(candidate["close"])
    results: dict[int, float] = {}
    for h in hours:
        shifted = cand_close.copy()
        shifted.index = shifted.index + pd.Timedelta(hours=h)
        cand_r = shifted.diff()
        joined = pd.concat([ref_r.rename("ref"), cand_r.rename("cand")], axis=1, sort=True).dropna()
        results[h] = float(joined.corr().iloc[0, 1]) if len(joined) > 200 else math.nan
    finite = {k: v for k, v in results.items() if np.isfinite(v)}
    best = max(finite, key=lambda k: finite[k]) if finite else None
    return {"best_shift_hours": best, "correlations": {str(k): round(v, 4) for k, v in results.items()}}


def quality_report(frame: pd.DataFrame, name: str, expected_minutes: int = BAR_MINUTES) -> QualityReport:
    """Structural quality of a bar frame (no statistics, no repairs)."""
    idx = pd.DatetimeIndex(frame.index)
    rows = int(len(frame))
    dupes = int(idx.duplicated().sum())
    steps = pd.Series(idx).diff().dropna().dt.total_seconds()
    non_mono = int((steps <= 0).sum())
    off_grid = int((steps % (expected_minutes * 60) != 0).sum()) if rows > 1 else 0
    o, h, low, c = (frame[k].to_numpy(dtype=float) for k in ["open", "high", "low", "close"])
    with np.errstate(invalid="ignore"):
        ohlc_bad = int(np.sum((h < np.maximum(o, c)) | (low > np.minimum(o, c)) | (h < low)))
    nonpos = int(np.sum(np.stack([o, h, low, c]) <= 0))
    nan_cells = int(frame[OHLC_COLUMNS].isna().sum().sum())
    by_year = pd.Series(idx.year).value_counts().sort_index()
    return QualityReport(
        name=name,
        rows=rows,
        first_stamp=idx[0].isoformat() if rows else None,
        last_stamp=idx[-1].isoformat() if rows else None,
        duplicate_stamps=dupes,
        non_monotonic_steps=non_mono,
        ohlc_violations=ohlc_bad,
        nonpositive_prices=nonpos,
        nan_cells=nan_cells,
        off_grid_steps=off_grid,
        bars_by_year={str(k): int(v) for k, v in by_year.items()},
    )


def write_csv_utc(frame: pd.DataFrame, path: Path) -> str:
    """Write ``time,open,high,low,close,volume`` (UTC) and return its SHA-256.

    Used to materialise the normalised research series under the gitignored raw
    directory, so every downstream run reads the same bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        values = frame[OHLC_COLUMNS].to_numpy(dtype=float)
        for ts, row in zip(frame.index, values, strict=True):
            writer.writerow(
                [
                    pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    repr(float(row[0])),
                    repr(float(row[1])),
                    repr(float(row[2])),
                    repr(float(row[3])),
                    repr(float(row[4])),
                ]
            )
    return sha256_bytes(path)


def read_csv_utc(path: Path) -> pd.DataFrame:
    """Read a file written by :func:`write_csv_utc`."""
    raw = pd.read_csv(path)
    index = pd.to_datetime(raw["time"], utc=True).dt.tz_convert(None)
    frame = raw[OHLC_COLUMNS].astype(float)
    frame.index = pd.DatetimeIndex(index, name="utc")
    return frame
