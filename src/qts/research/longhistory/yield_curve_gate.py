"""Causal source loaders and signal construction for the frozen yield-curve gate.

This module is deliberately narrow: raw pre-2000 gold prices, monthly H.15
GS10, daily FRED DFF, and a lagged binary inversion state. It never turns any
post-1999 gold-price cell into a number.
"""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import Plan

CUTOFF = date(2000, 1, 1)
GOLD_MONTHS = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
MODEL_MONTHS = pd.date_range("1971-12-31", "1999-12-31", freq="ME")


class InputBlocked(ValueError):
    """A pinned source, schema, coverage, or time-boundary check failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    """Git blob identity for a standalone file (used as an immutable source pin)."""
    digest = hashlib.sha1(usedforsecurity=False)
    size = path.stat().st_size
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_source(
    path: Path,
    *,
    label: str,
    expected_sha256: str | None = None,
    expected_git_blob_sha1: str | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        raise InputBlocked(f"{label} source is absent: {path}")
    size = path.stat().st_size
    actual_sha256 = sha256_file(path)
    actual_blob = git_blob_sha1(path)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise InputBlocked(f"{label} SHA-256 mismatch: {actual_sha256} != {expected_sha256}")
    if expected_git_blob_sha1 is not None and actual_blob != expected_git_blob_sha1:
        raise InputBlocked(f"{label} Git blob mismatch: {actual_blob} != {expected_git_blob_sha1}")
    return {
        "path": str(path),
        "bytes": size,
        "sha256": actual_sha256,
        "git_blob_sha1": actual_blob,
    }


def _parse_date(raw: str, label: str) -> date:
    text = raw.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        if len(text) == 7 and text[4] == "-":
            try:
                return date.fromisoformat(f"{text}-01")
            except ValueError as exc:
                raise InputBlocked(f"{label} has an invalid month: {raw!r}") from exc
        raise InputBlocked(f"{label} has a non-ISO date: {raw!r}") from None


def _parse_finite(raw: str, label: str, *, allow_zero: bool = True) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InputBlocked(f"{label} has a non-numeric eligible value") from exc
    if not math.isfinite(value) or (value < 0.0 if allow_zero else value <= 0.0):
        relation = "non-negative" if allow_zero else "positive"
        raise InputBlocked(f"{label} must be finite and {relation}")
    return value


def _validate_expected_index(
    series: pd.Series,
    expected: pd.DatetimeIndex | None,
    label: str,
) -> None:
    if expected is None:
        return
    actual = pd.DatetimeIndex(series.index)
    if not actual.equals(expected):
        missing = expected.difference(actual)
        extra = actual.difference(expected)
        raise InputBlocked(
            f"{label} coverage mismatch: rows={len(actual)}, missing={len(missing)}, extra={len(extra)}"
        )


def read_eligible_gold(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_git_blob_sha1: str | None,
    expected_months: pd.DatetimeIndex | None = GOLD_MONTHS,
) -> tuple[pd.Series, dict[str, Any]]:
    """Read raw Gold ``price_nominal_usd`` values through 1999 only."""
    identity = _verify_source(
        path,
        label="gold panel",
        expected_sha256=expected_sha256,
        expected_git_blob_sha1=expected_git_blob_sha1,
    )
    rows: list[tuple[pd.Timestamp, float]] = []
    seen: set[pd.Timestamp] = set()
    last_date: date | None = None
    skipped_post_cutoff = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "commodity_name", "price_nominal_usd"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise InputBlocked("gold panel does not have the frozen raw-price schema")
        for row_number, row in enumerate(reader, start=2):
            if (row.get("commodity_name") or "").strip() != "Gold":
                continue
            current = _parse_date(row.get("date") or "", f"gold row {row_number}")
            if last_date is not None and current <= last_date:
                raise InputBlocked(f"Gold dates duplicate or go backwards at row {row_number}")
            last_date = current
            if current >= CUTOFF:
                # Do not fetch or convert the post-cutoff price field.
                skipped_post_cutoff += 1
                continue
            if current.day != 1:
                raise InputBlocked(f"eligible Gold date is not first-of-month: {current}")
            month_end = pd.Timestamp(current) + pd.offsets.MonthEnd(0)
            if month_end in seen:
                raise InputBlocked(f"duplicate eligible Gold month: {month_end.date()}")
            value = _parse_finite(row.get("price_nominal_usd") or "", f"Gold {month_end.date()}", allow_zero=False)
            seen.add(month_end)
            rows.append((month_end, value))

    index = pd.DatetimeIndex([stamp for stamp, _ in rows], name="date")
    gold = pd.Series(np.asarray([value for _, value in rows], dtype=np.float64), index=index, name="Gold")
    if not gold.index.is_monotonic_increasing or gold.index.has_duplicates:
        raise InputBlocked("eligible Gold month index must be unique and chronological")
    _validate_expected_index(gold, expected_months, "eligible Gold")
    identity.update(
        {
            "eligible_months": int(len(gold)),
            "eligible_start": str(gold.index.min().date()) if len(gold) else None,
            "eligible_end": str(gold.index.max().date()) if len(gold) else None,
            "post_1999_rows_skipped_by_date_name_only": skipped_post_cutoff,
            "post_1999_price_values_converted": 0,
        }
    )
    return gold, identity


def read_monthly_gs10(
    path: Path,
    *,
    expected_git_blob_sha1: str,
    cutoff: date = CUTOFF,
    expected_months: pd.DatetimeIndex | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Read eligible H.15 monthly GS10 observations; skip post-1999 rate cells."""
    identity = _verify_source(path, label="H.15 GS10", expected_git_blob_sha1=expected_git_blob_sha1)
    values: list[tuple[pd.Timestamp, float]] = []
    seen: set[pd.Timestamp] = set()
    last_date: date | None = None
    skipped_post_cutoff = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"Date", "Rate"}.issubset(reader.fieldnames):
            raise InputBlocked("H.15 monthly file does not have the frozen Date/Rate schema")
        for row_number, row in enumerate(reader, start=2):
            current = _parse_date(row.get("Date") or "", f"GS10 row {row_number}")
            if last_date is not None and current <= last_date:
                raise InputBlocked(f"GS10 dates duplicate or go backwards at row {row_number}")
            last_date = current
            if current >= cutoff:
                # Do not fetch or convert post-cutoff rate cells.
                skipped_post_cutoff += 1
                continue
            month_end = pd.Timestamp(current) + pd.offsets.MonthEnd(0)
            if month_end in seen:
                raise InputBlocked(f"duplicate GS10 month: {month_end.date()}")
            value = _parse_finite(row.get("Rate") or "", f"GS10 {month_end.date()}", allow_zero=True)
            seen.add(month_end)
            values.append((month_end, value))

    index = pd.DatetimeIndex([stamp for stamp, _ in values], name="date")
    gs10 = pd.Series(np.asarray([value for _, value in values], dtype=np.float64), index=index, name="GS10")
    if not gs10.index.is_monotonic_increasing or gs10.index.has_duplicates:
        raise InputBlocked("eligible GS10 month index must be unique and chronological")
    _validate_expected_index(gs10, expected_months, "eligible GS10")
    identity.update(
        {
            "eligible_months": int(len(gs10)),
            "eligible_start": str(gs10.index.min().date()) if len(gs10) else None,
            "eligible_end": str(gs10.index.max().date()) if len(gs10) else None,
            "post_1999_rows_skipped_using_date_only": skipped_post_cutoff,
            "post_1999_rate_values_converted": 0,
        }
    )
    return gs10, identity


def read_daily_dff_monthly(
    path: Path,
    *,
    expected_git_blob_sha1: str,
    cutoff: date = CUTOFF,
    expected_months: pd.DatetimeIndex | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Average daily FRED DFF by month, never converting post-cutoff rows."""
    identity = _verify_source(path, label="FRED DFF snapshot", expected_git_blob_sha1=expected_git_blob_sha1)
    values: list[tuple[pd.Timestamp, float]] = []
    seen: set[date] = set()
    last_date: date | None = None
    skipped_post_cutoff = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"Date", "ffr_effective"}.issubset(reader.fieldnames):
            raise InputBlocked("FRED snapshot does not have the frozen Date/ffr_effective schema")
        for row_number, row in enumerate(reader, start=2):
            current = _parse_date(row.get("Date") or "", f"DFF row {row_number}")
            if last_date is not None and current <= last_date:
                raise InputBlocked(f"DFF dates duplicate or go backwards at row {row_number}")
            last_date = current
            if current >= cutoff:
                # Do not fetch or convert post-cutoff rate cells.
                skipped_post_cutoff += 1
                continue
            if current in seen:
                raise InputBlocked(f"duplicate DFF daily observation: {current}")
            value = _parse_finite(row.get("ffr_effective") or "", f"DFF {current}", allow_zero=True)
            seen.add(current)
            values.append((pd.Timestamp(current), value))

    if not values:
        raise InputBlocked("no eligible pre-2000 DFF observations")
    daily_index = pd.DatetimeIndex([stamp for stamp, _ in values], name="date")
    daily = pd.Series(
        np.asarray([value for _, value in values], dtype=np.float64),
        index=daily_index,
        name="DFF_daily",
    )
    monthly = daily.groupby(daily_index.to_period("M")).mean()
    monthly_period_index = pd.PeriodIndex(monthly.index)
    monthly.index = pd.DatetimeIndex(monthly_period_index.to_timestamp("M"), name="date")
    monthly.name = "DFF"
    if not monthly.index.is_monotonic_increasing or monthly.index.has_duplicates:
        raise InputBlocked("eligible monthly DFF index must be unique and chronological")
    _validate_expected_index(monthly, expected_months, "eligible monthly DFF")
    identity.update(
        {
            "eligible_daily_rows": int(len(daily)),
            "eligible_months": int(len(monthly)),
            "eligible_start": str(monthly.index.min().date()),
            "eligible_end": str(monthly.index.max().date()),
            "post_1999_rows_skipped_using_date_only": skipped_post_cutoff,
            "post_1999_rate_values_converted": 0,
            "aggregation": "arithmetic mean of eligible daily DFF values by calendar month",
        }
    )
    return monthly, identity


def lagged_term_spread(gs10: pd.Series, dff: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Align monthly rates and return the prior-complete-month GS10 minus DFF."""
    for label, series in (("GS10", gs10), ("DFF", dff)):
        if not isinstance(series.index, pd.DatetimeIndex) or series.index.has_duplicates:
            raise InputBlocked(f"{label} must have a unique DatetimeIndex")
        if not series.index.is_monotonic_increasing:
            raise InputBlocked(f"{label} dates must be chronological")
    aligned = pd.concat([gs10.rename("GS10"), dff.rename("DFF")], axis=1).reindex(index)
    raw_spread = aligned["GS10"] - aligned["DFF"]
    feature = raw_spread.shift(1)
    feature.name = "GS10_minus_DFF_lag1"
    return feature


def apply_inversion_gate(base: Plan, feature: pd.Series, *, index: pd.DatetimeIndex) -> Plan:
    """Keep inherited long-only trend only when prior-month spread is < 0."""
    if not feature.index.equals(index):
        feature = feature.reindex(index)
    target = np.asarray(base.target, dtype=float).copy()
    size = np.asarray(base.size, dtype=float).copy()
    valid_base = np.isfinite(target) & np.isfinite(size)
    spread = feature.to_numpy(dtype=float)
    if np.any(valid_base & ~np.isfinite(spread)):
        raise InputBlocked("lagged GS10-DFF feature is missing where the base trend is tradable")
    inverted = spread < 0.0
    target[valid_base & ~inverted] = 0.0
    target[~valid_base] = np.nan
    size[~valid_base] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(base.stop_dist, dtype=float).copy(),
        rebalance=np.asarray(base.rebalance, dtype=bool).copy(),
        family="yield_curve_inversion_gated_tsmom",
        params={
            "gold_signal": "ts9_lo",
            "curve_spread": "prior-month mean GS10 minus prior-month mean DFF, percentage points",
            "inverted_rule": "strictly below 0.0",
            "rate_publication_lag_months": 1,
        },
    )
