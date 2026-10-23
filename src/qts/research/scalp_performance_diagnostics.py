"""Post-process completed MT5 tick scalp research, without reading raw ticks.

Exploratory diagnosis only. No parameter selection, holdout inspection,
strategy promotion, broker orders or claims of statistical significance.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite
from statistics import fmean, median
from typing import Any

MODES = ("confirmed", "anticipatory")
SEGMENTS = ("early_third", "middle_third", "late_third")


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "trades": 0, "mean_net_bps": None, "median_net_bps": None,
            "win_rate": None, "sum_trade_bps_not_portfolio_return": None,
            "average_win_bps": None, "average_loss_bps": None,
            "break_even_win_rate_for_observed_payoffs": None,
        }
    values = [r["net_bps"] for r in records]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    avg_win = fmean(wins) if wins else None
    avg_loss = fmean(losses) if losses else None
    hurdle = (-avg_loss / (avg_win - avg_loss)) if avg_win is not None and avg_loss is not None else None
    return {
        "trades": len(values),
        "mean_net_bps": fmean(values),
        "median_net_bps": median(values),
        "win_rate": len(wins) / len(values),
        "sum_trade_bps_not_portfolio_return": sum(values),
        "average_win_bps": avg_win,
        "average_loss_bps": avg_loss,
        "break_even_win_rate_for_observed_payoffs": hurdle,
    }


def _read_trades(mode: dict[str, Any], cutoff: int, start: int) -> list[dict[str, Any]]:
    if (
        mode.get("schema") != "qts.scalp_tick_sequenced_replay.v1"
        or mode.get("status") != "RESEARCH_ONLY_QUOTE_EXECUTION_ASSUMED"
        or mode.get("LIVE") != "LOCKED" or mode.get("orders_submitted") != 0
        or mode.get("strategy_promoted") is not False
        or not isinstance(mode.get("trades"), list)
    ):
        raise ValueError("unrecognized or unsafe tick scalp research report")
    parsed: list[dict[str, Any]] = []
    last_entry = -1
    last_exit = -1
    for item in mode["trades"]:
        if not isinstance(item, dict):
            raise ValueError("invalid tick replay trade record")
        try:
            signal = int(item["signal_time_msc"])
            entry = int(item["entry_time_msc"])
            exit_time = int(item["exit_time_msc"])
            net = float(item["net_bps"])
            side = item["side"]
            reason = item["exit_reason"]
            family = item["family"]
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("malformed tick replay trade") from exc
        if (
            not isfinite(net) or signal < start or entry < signal
            or entry < last_entry or entry < last_exit
            or exit_time < entry or exit_time >= cutoff
            or side not in ("BUY", "SELL")
            or not all(isinstance(s, str) and s for s in (reason, family))
        ):
            raise ValueError("noncausal or out-of-window tick replay trade")
        parsed.append({
            "net_bps": net, "entry": entry, "side": side,
            "reason": reason, "family": family,
        })
        last_entry = entry
        last_exit = exit_time
    stated = mode.get("metrics", {}).get("trades")
    if stated != len(parsed):
        raise ValueError("tick replay trade ledger and summary counts disagree")
    return parsed


def _breakdown(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record[key])].append(record)
    return {name: _summary(groups[name]) for name in sorted(groups)}


def _week(entry_ms: int) -> str:
    iso = datetime.fromtimestamp(entry_ms / 1000, tz=UTC).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _third(entry_ms: int, start: int, cutoff: int) -> str:
    idx = min(2, (3 * (entry_ms - start)) // (cutoff - start))
    return SEGMENTS[idx]


def _mode_diagnostics(
    records: list[dict[str, Any]], start: int, cutoff: int
) -> dict[str, Any]:
    thirds = {
        label: _summary([r for r in records if _third(r["entry"], start, cutoff) == label])
        for label in SEGMENTS
    }
    weekly = _breakdown(
        [{**r, "week": _week(r["entry"])} for r in records], "week"
    )
    return {
        "overall": _summary(records),
        "by_exit_reason": _breakdown(records, "reason"),
        "by_side": _breakdown(records, "side"),
        "by_family": _breakdown(records, "family"),
        "fixed_calendar_thirds": thirds,
        "utc_entry_week": weekly,
    }


def analyze_scalp_tick_report(report: dict[str, Any]) -> dict[str, Any]:
    """Analyze the same completed discovery report; never read unseen data."""
    source = report.get("source")
    if (
        not isinstance(source, dict) or source.get("holdout_excluded") is not True
        or not isinstance(source.get("manifest_dataset_sha256"), str)
        or not source["manifest_dataset_sha256"]
    ):
        raise ValueError("diagnostics require verified discovery-only source evidence")
    try:
        start = int(source["data_start_time_msc"])
        cutoff = int(source["discovery_cutoff_time_msc"])
        confirmed = report["tick_execution_replay"]
        early = report["anticipatory_comparison"]["tick_execution_replay"]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("both completed tick-replay modes are required") from exc
    if not 0 <= start < cutoff:
        raise ValueError("invalid discovery interval")
    if (
        confirmed.get("entry_mode") != "confirmed"
        or early.get("entry_mode") != "anticipatory"
        or confirmed.get("raw_quote_rows") != early.get("raw_quote_rows")
        or confirmed.get("raw_quote_rows", 0) <= 0
    ):
        raise ValueError("research modes were not evaluated on identical quote histories")
    items = {
        "confirmed": _read_trades(confirmed, cutoff, start),
        "anticipatory": _read_trades(early, cutoff, start),
    }
    modes = {k: _mode_diagnostics(v, start, cutoff) for k, v in items.items()}
    weekly_a = modes["confirmed"]["utc_entry_week"]
    weekly_b = modes["anticipatory"]["utc_entry_week"]
    common = sorted(set(weekly_a) & set(weekly_b))
    comparable = [
        {
            "week": week,
            "confirmed_trades": weekly_a[week]["trades"],
            "anticipatory_trades": weekly_b[week]["trades"],
            "confirmed_mean_net_bps": weekly_a[week]["mean_net_bps"],
            "anticipatory_mean_net_bps": weekly_b[week]["mean_net_bps"],
            "anticipatory_minus_confirmed_mean_net_bps": (
                weekly_b[week]["mean_net_bps"] - weekly_a[week]["mean_net_bps"]
            ),
        }
        for week in common
    ]
    difference = [x["anticipatory_minus_confirmed_mean_net_bps"] for x in comparable]
    return {
        "schema": "qts.scalp_tick_replay_diagnostics.v1",
        "status": "EXPLORATORY_DISCOVERY_ONLY_NOT_VALIDATED",
        "source_sha256": source["manifest_dataset_sha256"],
        "start_time_msc": start,
        "end_exclusive_time_msc": cutoff,
        "raw_quote_rows_per_mode": confirmed["raw_quote_rows"],
        "modes": modes,
        "matched_utc_weeks": {
            "weeks_with_both_modes": len(common),
            "weeks_early_mean_exceeds_confirmed": sum(x > 0 for x in difference),
            "weeks_early_mean_below_confirmed": sum(x < 0 for x in difference),
            "equal_weeks": sum(x == 0 for x in difference),
            "equal_weight_mean_of_weekly_differences_bps": fmean(difference) if difference else None,
            "weekly_comparison": comparable,
        },
        "limitations": [
            "both modes use DIFFERENT trades and hence are not paired trade experiments",
            "discovery sample was repeatedly inspected; weekly cells are descriptive, not out-of-sample evidence",
            "weekly differences have unequal sample sizes; no inferential significance is claimed",
            "multiple subgroup comparisons must not be used for unregistered strategy selection",
            "slippage and commission remain assumptions; no broker execution records",
            "additive trade bps do not equal compounded or cash portfolio profit",
        ],
        "strategy_promoted": False,
        "orders_submitted": 0,
        "LIVE": "LOCKED",
    }
