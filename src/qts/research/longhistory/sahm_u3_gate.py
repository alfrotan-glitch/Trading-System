"""Pinned BLS U-3 loader and causal Sahm-rule feature for one frozen screen.

Only U3 observations dated before 2000-01-01 are converted. Later rows are
skipped by date alone; the Sahm feature is a retrospective, revised-vintage
research input, not a point-in-time/live signal.
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
U3_SOURCE_COMMIT = "23d5e7795325ce1a69d02bd52e20ad075983082a"
U3_MONTHS = pd.date_range("1948-01-31", "1999-12-31", freq="ME")
SAHM_THRESHOLD_PP = 0.50
U3_PUBLICATION_LAG_MONTHS = 2


class InputBlocked(ValueError):
    """A pinned source, schema, coverage, or time-boundary check failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    """Return Git's blob SHA-1 identity for a standalone file."""
    digest = hashlib.sha1(usedforsecurity=False)
    size = path.stat().st_size
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise InputBlocked(f"{label} has a non-ISO date") from exc


def _parse_u3(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InputBlocked(f"{label} has a non-numeric eligible U3 rate") from exc
    if not math.isfinite(value) or value < 0.0:
        raise InputBlocked(f"{label} must be finite and non-negative")
    return value


def read_eligible_u3(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_git_blob_sha1: str | None,
    expected_months: pd.DatetimeIndex | None = U3_MONTHS,
) -> tuple[pd.Series, dict[str, Any]]:
    """Read the pinned monthly U3 series through 1999; skip later values."""
    if not path.is_file():
        raise InputBlocked(f"U3 source is absent: {path}")
    size = path.stat().st_size
    actual_sha256 = sha256_file(path)
    actual_blob_sha1 = git_blob_sha1(path)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise InputBlocked(f"U3 SHA-256 mismatch: {actual_sha256} != {expected_sha256}")
    if expected_git_blob_sha1 is not None and actual_blob_sha1 != expected_git_blob_sha1:
        raise InputBlocked(f"U3 Git blob mismatch: {actual_blob_sha1} != {expected_git_blob_sha1}")

    values: list[tuple[pd.Timestamp, float]] = []
    last_date: date | None = None
    skipped_post_cutoff = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise InputBlocked("U3 CSV is empty") from exc
        if len(header) != 2 or [item.strip() for item in header] != ["DATE", "UNRATE"]:
            raise InputBlocked("U3 CSV schema must be exactly DATE,UNRATE")

        for row_number, row in enumerate(reader, start=2):
            if len(row) != 2:
                raise InputBlocked(f"U3 row {row_number} has an invalid field count")
            current = _parse_date(row[0], f"U3 row {row_number}")
            if last_date is not None and current <= last_date:
                raise InputBlocked(f"U3 dates duplicate or go backwards at row {row_number}")
            last_date = current
            if current >= CUTOFF:
                # Intentionally do not access row[1] for any post-1999 record.
                skipped_post_cutoff += 1
                continue
            if current.day != 1:
                raise InputBlocked(f"eligible U3 date is not the first of a month: {current}")
            month_end = pd.Timestamp(current) + pd.offsets.MonthEnd(0)
            value = _parse_u3(row[1], f"U3 {month_end.date()}")
            values.append((month_end, value))

    index = pd.DatetimeIndex([stamp for stamp, _ in values], name="date")
    u3 = pd.Series(np.asarray([value for _, value in values], dtype=np.float64), index=index, name="U3_percent")
    if not u3.index.is_monotonic_increasing or u3.index.has_duplicates:
        raise InputBlocked("eligible U3 month index must be unique and chronological")
    u3_index = pd.DatetimeIndex(u3.index)
    if expected_months is not None and not u3_index.equals(expected_months):
        missing = expected_months.difference(u3_index)
        extra = u3_index.difference(expected_months)
        raise InputBlocked(
            f"eligible U3 coverage mismatch: rows={len(u3)}, missing={len(missing)}, extra={len(extra)}"
        )
    return u3, {
        "source_path": str(path),
        "source_commit": U3_SOURCE_COMMIT,
        "source_file_bytes": size,
        "source_file_sha256": actual_sha256,
        "source_git_blob_sha1": actual_blob_sha1,
        "schema": ["DATE", "UNRATE"],
        "units": "seasonally adjusted percent",
        "eligible_months": int(len(u3)),
        "eligible_start": str(u3.index.min().date()) if len(u3) else None,
        "eligible_end": str(u3.index.max().date()) if len(u3) else None,
        "post_1999_rows_skipped_using_date_only": skipped_post_cutoff,
        "post_1999_u3_values_converted": 0,
        "vintage_status": "pinned revised historical snapshot; point-in-time vintages unavailable",
    }


def lagged_sahm_gap(u3: pd.Series, decision_index: pd.DatetimeIndex) -> pd.Series:
    """Build the standard 3m-U3-minus-prior-12m-minimum gap, lagged 2 months.

    For a Gold decision month ``t``, the output uses the indicator through
    unemployment reference month ``t-2``. The indicator is measured in
    percentage points, and the caller applies the frozen 0.50 pp threshold.
    """
    if not isinstance(u3.index, pd.DatetimeIndex) or u3.index.has_duplicates:
        raise InputBlocked("U3 must have a unique DatetimeIndex")
    if not u3.index.is_monotonic_increasing:
        raise InputBlocked("U3 dates must be chronological")
    if not isinstance(decision_index, pd.DatetimeIndex) or decision_index.has_duplicates:
        raise InputBlocked("Gold decision months must be a unique DatetimeIndex")
    if not decision_index.is_monotonic_increasing:
        raise InputBlocked("Gold decision months must be chronological")
    values = u3.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or (values < 0.0).any():
        raise InputBlocked("eligible U3 feature input contains a missing, non-finite, or negative value")

    three_month_average = u3.rolling(3, min_periods=3).mean()
    prior_12_month_minimum = three_month_average.shift(1).rolling(12, min_periods=12).min()
    sahm_gap = three_month_average - prior_12_month_minimum
    sahm_gap.name = "sahm_gap_pp"
    lagged = sahm_gap.shift(U3_PUBLICATION_LAG_MONTHS).reindex(decision_index)
    lagged.name = "sahm_gap_lag2_pp"
    return lagged


def apply_sahm_gate(base: Plan, feature: pd.Series, *, index: pd.DatetimeIndex) -> Plan:
    """Keep the inherited long-only Gold trend only when lagged Sahm gap >= 0.50 pp."""
    if not feature.index.equals(index):
        feature = feature.reindex(index)
    base_target = np.asarray(base.target, dtype=np.float64)
    base_size = np.asarray(base.size, dtype=np.float64)
    gap = feature.to_numpy(dtype=np.float64)
    valid = np.isfinite(base_target) & np.isfinite(base_size) & np.isfinite(gap)
    target = base_target.copy()
    target[valid & (gap < SAHM_THRESHOLD_PP)] = 0.0
    target[~valid] = np.nan
    size = base_size.copy()
    size[~valid] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(base.stop_dist, dtype=np.float64).copy(),
        rebalance=np.asarray(base.rebalance, dtype=bool).copy(),
        family="sahm_u3_gated_tsmom",
        params={
            "gold_lookback_months": 9,
            "sahm_rule_3_month_average": True,
            "sahm_prior_minimum_months": 12,
            "sahm_threshold_percentage_points": SAHM_THRESHOLD_PP,
            "u3_release_lag_months": U3_PUBLICATION_LAG_MONTHS,
            "long_only": True,
            "volatility_lookback_months": 12,
            "annualized_volatility_target": 0.10,
            "maximum_notional_fraction": 1.0,
        },
    )
