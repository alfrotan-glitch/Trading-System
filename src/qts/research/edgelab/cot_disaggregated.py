"""Official CFTC GOLD Disaggregated Futures-Only positioning research.

This is NOT the previously tested 2018-2025 Legacy COT workbook. The CFTC
disaggregated dataset distinguishes Managed Money from Producer/Merchant and
reports from 2006 onward. Contract code 088691 is COMEX GOLD futures.

CFTC report dates are positions as-of Tuesday, NOT release timestamps.
The usual release is Friday. We delay positions FOURTEEN calendar days after
their as-of dates; exceptional release delays are still unverified. Historical
results therefore cannot automatically establish executable causality or edge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

GOLD_MARKET_CODE = "088691"
OFFICIAL_CFTC_DATASET = "72hh-3qpy"
ASSUMED_PUBLICATION_LAG_DAYS = 14

REQUIRED_COLUMNS = (
    "report_date_as_yyyy_mm_dd",
    "cftc_contract_market_code",
    "open_interest_all",
    "m_money_positions_long_all",
    "m_money_positions_short_all",
)


def parse_official_gold(rows: Sequence[Mapping[str, object]]) -> pd.DataFrame:
    """Validate direct CFTC records; never interpolate or silently drop bad rows."""
    if len(rows) < 500:
        raise ValueError(f"insufficient official CFTC observations: {len(rows)}")
    records: list[dict[str, object]] = []
    for row in rows:
        missing = set(REQUIRED_COLUMNS).difference(row)
        if missing:
            raise ValueError(f"missing official CFTC fields: {sorted(missing)}")
        if str(row["cftc_contract_market_code"]) != GOLD_MARKET_CODE:
            raise ValueError("non-GOLD contract in CFTC research input")
        report_date = pd.to_datetime(
            str(row["report_date_as_yyyy_mm_dd"])[:10],
            format="%Y-%m-%d",
            errors="raise",
            utc=True,
        )
        try:
            oi = int(str(row["open_interest_all"]))
            money_long = int(str(row["m_money_positions_long_all"]))
            money_short = int(str(row["m_money_positions_short_all"]))
        except ValueError as exc:
            raise ValueError("invalid CFTC managed-money position") from exc
        if oi <= 0 or min(money_long, money_short) < 0 or max(money_long, money_short) > oi:
            raise ValueError("impossible CFTC open interest or managed-money position")
        records.append(
            {
                "date": report_date,
                "open_interest": oi,
                "money_long": money_long,
                "money_short": money_short,
                "managed_money_net_oi": (money_long - money_short) / oi,
            }
        )
    frame = pd.DataFrame.from_records(records).set_index("date").sort_index()
    if bool(frame.index.duplicated().any()):
        raise ValueError("duplicate CFTC observation date")
    if (frame.index[-1] - frame.index[0]).days < 365 * 10:
        raise ValueError("official CFTC gold history does not span ten years")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("official CFTC observation timestamps must be UTC")
    return frame


def fixed_positioning_hypotheses(frame: pd.DataFrame) -> pd.DataFrame:
    """Exactly TWO fixed long/flat hypotheses; no selection by later returns.

    1. crowded_reversal: low money-manager net OI relative to the previous
       ~2 years may precede a reaccumulation by systematic/large managers.
    2. positioning_trend: 13-week net-position change is positive.

    No strategy direction or threshold is fitted to the historical gold price.
    """
    net_oi = frame["managed_money_net_oi"].astype(float)
    def rank_last(values: np.ndarray) -> float:
        return float(np.mean(values[:-1] <= values[-1]))

    percentile = net_oi.rolling(104, min_periods=104).apply(rank_last, raw=True)
    reversal = (percentile < 0.20).astype(float).where(percentile.notna(), 0.0)
    change = net_oi - net_oi.shift(13)
    momentum = (change > 0.0).astype(float).where(change.notna(), 0.0)
    output = pd.DataFrame(
        {"crowded_reversal": reversal, "positioning_trend": momentum},
        index=frame.index,
    )
    # NEVER treat Tuesday's as-of snapshot as a Tuesday-published value.
    output.index = pd.DatetimeIndex(output.index) + pd.Timedelta(
        days=ASSUMED_PUBLICATION_LAG_DAYS
    )
    return output


def align_published_positions(
    signals: pd.DataFrame,
    gold_index: pd.DatetimeIndex,
    *,
    max_stale_days: int = 10,
) -> pd.DataFrame:
    """Forward-fill ONLY already-available reports; silence prolonged gaps."""
    idx = pd.DatetimeIndex(gold_index)
    source_idx = pd.DatetimeIndex(signals.index)
    if idx.tz is None or source_idx.tz is None:
        raise ValueError("CFTC and gold timestamps must both be timezone-aware")
    if not idx.is_monotonic_increasing or bool(idx.duplicated().any()):
        raise ValueError("gold bar index must be unique and ordered")
    if max_stale_days < 1:
        raise ValueError("max_stale_days must be positive")
    src = signals.copy()
    src.index = source_idx.tz_convert("UTC")
    if bool(src.index.duplicated().any()):
        raise ValueError("duplicate CFTC publication assumption")
    aligned = src.reindex(
        idx.tz_convert("UTC"),
        method="ffill",
        tolerance=pd.Timedelta(days=max_stale_days),
    ).fillna(0.0)
    aligned.index = idx
    return aligned.clip(lower=0.0, upper=1.0)
