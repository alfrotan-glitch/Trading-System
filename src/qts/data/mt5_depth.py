"""Read-only MT5 history-depth probe — how much history does this terminal HAVE?

Why this exists
---------------
The 15m benchmark audit was blocked on a number: "the broker gives 30 days".
That number came from ``scripts/probe_mt5_history.py``, which issues ONE
``copy_ticks_range`` call per window (1, 7, 30, 365 days) and reports what
comes back. The 365-day request failed — and the evidence file says so
explicitly, in its own words: *"This proves a working limited historical
tick/bid/ask capability, not the maximum retention boundary."*

A single oversized request failing is what you would expect from a
**request-size limit**. It is not evidence of a **retention limit**. Those two
are worth distinguishing before concluding that a broker cannot supply enough
data, and the acquisition layer already assumes the difference: it chunks at
24h and recursively halves on failure (``qts.data.mt5_history_acquisition``),
a design that only makes sense if a big request can fail where small ones
succeed.

This module answers the question directly, in seconds, without downloading
anything:

* **bar depth** — how many M15 bars does the terminal hold? Asked with
  ``copy_rates_from_pos``, which is a positional read and is not subject to the
  range-request failure mode at all. This is the number the frozen benchmark
  needs, and it has never been measured.
* **tick depth** — probe a few small windows at increasing age rather than one
  huge one, so a request-size limit does not masquerade as a retention limit.

Every probe is read-only. No order API is ever called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

#: How far back the tick probes reach, in days. Deliberately a handful of small
#: windows: the question is "does history exist at this age", not "download it".
DEFAULT_TICK_PROBE_AGES_DAYS = (7, 30, 90, 180, 365, 730)

#: M15 bar counts to try, ascending. The first is what the bar minimum needs.
BAR_PROBE_COUNTS = (5000, 10_000, 20_000, 50_000, 100_000)


@dataclass
class DepthObservation:
    """One probe: what was asked, what came back, and how to read it."""

    probe: str
    requested: str
    observed: str
    rows: int | None
    status: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe": self.probe,
            "requested": self.requested,
            "observed": self.observed,
            "rows": self.rows,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class DepthReport:
    """What the terminal actually holds, as far as a read-only probe can tell."""

    symbol: str
    generated_at: str
    observations: list[DepthObservation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def max_bar_rows(self) -> int | None:
        rows = [
            o.rows
            for o in self.observations
            if o.probe == "bars" and o.status == "OK" and o.rows is not None
        ]
        return max(rows) if rows else None

    @property
    def oldest_tick_age_days(self) -> int | None:
        ages = [
            int(o.requested.split()[0])
            for o in self.observations
            if o.probe == "ticks" and o.status == "OK" and o.rows
        ]
        return max(ages) if ages else None

    @property
    def bar_depth_sufficient(self) -> bool:
        return self.max_bar_rows is not None and self.max_bar_rows >= 5000

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "qts.mt5_depth_probe.v1",
            "symbol": self.symbol,
            "generated_at": self.generated_at,
            "observations": [o.as_dict() for o in self.observations],
            "max_bar_rows": self.max_bar_rows,
            "oldest_tick_age_days": self.oldest_tick_age_days,
            "bar_depth_sufficient_for_frozen_benchmark": self.bar_depth_sufficient,
            "notes": self.notes,
            "orders_submitted": 0,
            "order_apis_called": [],
        }


def _mt5_constant(mt5: Any, name: str, default: int | None = None) -> int | None:
    value = getattr(mt5, name, None)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def probe(mt5: Any, symbol: str, *, now: datetime | None = None) -> DepthReport:
    """Ask the terminal how much history it holds. Read-only, no downloads.

    ``mt5`` is the MetaTrader5 module. A terminal that is not connected yields
    observations with status ``UNAVAILABLE`` rather than an exception, because
    the whole point is to report what is missing.
    """
    now = now or datetime.now(UTC)
    report = DepthReport(symbol=symbol, generated_at=now.isoformat())

    if mt5 is None:
        report.notes.append(
            "no MT5 module — this probe must run on the Windows machine with the "
            "MetaTrader5 package and a connected DEMO terminal"
        )
        return report

    report.observations.extend(_probe_bars(mt5, symbol))
    report.observations.extend(_probe_ticks(mt5, symbol, now))

    if report.max_bar_rows == 0:
        report.notes.append(
            "the terminal returned no bars at all — check the symbol is selected "
            "in Market Watch and that History is not empty"
        )
    if report.bar_depth_sufficient:
        report.notes.append(
            "M15 bar history meets the 5,000-bar minimum: broker 15m history is "
            "sufficient for the frozen benchmark on depth"
        )
    else:
        report.notes.append(
            "M15 bar history is below the 5,000-bar minimum on this terminal"
        )
    report.notes.append(
        "tick probes use small windows at increasing age on purpose: a single "
        "oversized request failing shows a REQUEST-SIZE limit, not a retention "
        "limit, and the two must not be confused"
    )
    return report


def _probe_bars(mt5: Any, symbol: str) -> list[DepthObservation]:
    """How many M15 bars exist? Positional read; not a range request."""
    getter = getattr(mt5, "copy_rates_from_pos", None)
    tf_m15 = _mt5_constant(mt5, "TIMEFRAME_M15", 15)
    if getter is None:
        return [
            DepthObservation(
                probe="bars", requested="M15 bars", observed="api unavailable",
                rows=None, status="UNAVAILABLE",
                detail="copy_rates_from_pos not exposed by the MT5 package",
            )
        ]

    out: list[DepthObservation] = []
    for count in BAR_PROBE_COUNTS:
        try:
            rows = getter(symbol, tf_m15, 0, count)
        except Exception as exc:
            out.append(
                DepthObservation(
                    probe="bars", requested=f"{count} M15 bars", observed="query error",
                    rows=None, status="QUERY_ERROR",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        n = 0 if rows is None else len(rows)
        out.append(
            DepthObservation(
                probe="bars",
                requested=f"{count} M15 bars",
                observed=f"{n} bars returned",
                rows=n,
                status="OK" if n else "EMPTY",
                detail="" if n >= count else f"terminal holds fewer than {count} bars",
            )
        )
        # Ascending: stop as soon as the terminal cannot fill the request.
        if n < count:
            break
    return out


def _probe_ticks(mt5: Any, symbol: str, now: datetime) -> list[DepthObservation]:
    """Does tick history exist at increasing ages? Small windows, oldest first."""
    getter = getattr(mt5, "copy_ticks_range", None)
    flags = _mt5_constant(mt5, "COPY_TICKS_ALL", 1)
    if getter is None:
        return [
            DepthObservation(
                probe="ticks", requested="any", observed="api unavailable",
                rows=None, status="UNAVAILABLE",
                detail="copy_ticks_range not exposed by the MT5 package",
            )
        ]

    out: list[DepthObservation] = []
    for age_days in DEFAULT_TICK_PROBE_AGES_DAYS:
        end = now - timedelta(days=age_days)
        start = end - timedelta(hours=1)  # a one-hour window: small by design
        try:
            rows = getter(symbol, start, end, flags)
        except Exception as exc:
            out.append(
                DepthObservation(
                    probe="ticks", requested=f"{age_days} days ago", observed="query error",
                    rows=None, status="QUERY_ERROR",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        n = 0 if rows is None else len(rows)
        out.append(
            DepthObservation(
                probe="ticks",
                requested=f"{age_days} days ago",
                observed=f"{n} ticks in the 1h window",
                rows=n,
                status="OK" if n else "EMPTY",
                detail="" if n else "no tick history at this age",
            )
        )
    return out


def markdown(report: DepthReport) -> str:
    lines = [
        f"# MT5 history depth probe — {report.symbol}",
        "",
        f"**Generated:** {report.generated_at}  ",
        f"**M15 bars available:** {report.max_bar_rows}  ",
        f"**Oldest tick history with data:** {report.oldest_tick_age_days} days  ",
        f"**Bar depth sufficient for the frozen benchmark (5,000):** "
        f"{'YES' if report.bar_depth_sufficient else 'NO'}  ",
        "**Orders submitted:** 0  ",
        "",
        "| Probe | Requested | Observed | Rows | Status | Detail |",
        "|:---|:---|:---|---:|:---|:---|",
    ]
    for o in report.observations:
        lines.append(
            f"| {o.probe} | {o.requested} | {o.observed} | "
            f"{'' if o.rows is None else o.rows} | {o.status} | {o.detail} |"
        )
    if report.notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in report.notes]
    return "\n".join(lines) + "\n"
