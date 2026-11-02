"""Observe subsequent XAUUSD@ Bid/Ask movement after prospectively logged DEMO signals.

Purely descriptive post-signal PRICE paths, never a limit-fill simulation.
No orders, hypothetical execution, TP/SL claims, P/L or trade promotion.

A native signal must have been logged AFTER the immutable V2 registration,
and the full 60-minute observation horizon must have elapsed before any quote
is requested. A gap/stale/wrong-account result remains UNKNOWN. Historical
MT5 tick retrieval is not guaranteed complete; never call this tick capture.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

from forward_shadow_observer import (
    FILE_PATTERN, FIELDS, _event_files, _valid_row, default_signals_dir, freeze,
    select_study_dir,
)

UTC = timezone.utc
SCHEMA = "qts.mt5.forward_shadow_quote_path.v1"
HORIZON_SECONDS = 3600
START_GAP_MAX_MS = 60_000
END_GAP_MAX_MS = 60_000
BETWEEN_TICKS_MAX_MS = 60_000
MAX_TICKS = 200_000
MAX_EVENTS_PER_REVIEW = 64


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def _canonical_path(value: str | Path) -> str:
    """Compare terminal roots on Windows without leaking user-specific paths."""
    return os.path.normcase(os.path.normpath(str(Path(value).resolve()))).casefold()


def _demo_terminal(*, executable: Path | None = None,
                   data_dir: Path | None = None):
    """Open the explicitly selected MT5 DEMO, never guess a second instance.

    A terminal/data-folder binding is mandatory for prospective quote review.
    Identity must match BOTH the executable's installation folder and the
    native terminal data folder, not merely a WMMarkets server label.
    """
    if executable is None or data_dir is None:
        raise ValueError("PINNED_MT5_TARGET_REQUIRED_NO_GO")
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("PINNED_MT5_EXE_INVALID_NO_GO")
    if executable.name.casefold() != "terminal64.exe":
        raise ValueError("PINNED_MT5_EXE_NAME_INVALID_NO_GO")
    if not data_dir.is_absolute() or not data_dir.is_dir():
        raise ValueError("PINNED_MT5_DATA_DIR_INVALID_NO_GO")
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise ValueError("MetaTrader5 Python package unavailable") from exc
    if not mt5.initialize(str(executable)):
        mt5.shutdown()
        raise ValueError("PINNED_WMMARKETS_DEMO_NOT_CONNECTED_NO_GO")
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    server = str(getattr(account, "server", "")).lower().replace(" ", "")
    expected_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    install_path = str(getattr(terminal, "path", "") or "")
    actual_data = str(getattr(terminal, "data_path", "") or "")
    if not (
        account is not None
        and terminal is not None
        and bool(getattr(terminal, "connected", False))
        and expected_mode is not None
        and account.trade_mode == expected_mode
        and "wmmarkets" in server
        and mt5.symbol_info("XAUUSD@") is not None
        and bool(install_path) and bool(actual_data)
        and _canonical_path(install_path) == _canonical_path(executable.parent)
        and _canonical_path(actual_data) == _canonical_path(data_dir)
    ):
        mt5.shutdown()
        raise ValueError("PINNED_MT5_IDENTITY_OR_DEMO_MISMATCH_NO_GO")
    return mt5


def quote_path(event: dict, terminal, *, now_utc_s: int) -> dict:
    """Evaluate only mature future quotations; never invent a broker fill."""
    origin = event["tick_server_msc"]
    observed = event["observed_utc_s"]
    _require(abs(origin - observed * 1000) <= 120_000,
             "Cannot reconcile native server tick and observation UTC clocks")
    start_ms = origin + 1
    end_ms = origin + HORIZON_SECONDS * 1000
    _require(now_utc_s * 1000 >= end_ms + 60_000,
             "Signal horizon has not completed: NO FUTURE PRICE INSPECTION")
    start = datetime.fromtimestamp(start_ms / 1000, UTC)
    end = datetime.fromtimestamp(end_ms / 1000, UTC)
    ticks = terminal.copy_ticks_range("XAUUSD@", start, end, terminal.COPY_TICKS_ALL)
    _require(ticks is not None and 0 < len(ticks) <= MAX_TICKS,
             "Missing/oversized broker quote window")
    vals = []
    for tick in ticks:
        stamp = int(tick["time_msc"])
        if stamp <= origin or stamp > end_ms:
            continue
        bid, ask = float(tick["bid"]), float(tick["ask"])
        _require(math.isfinite(bid) and math.isfinite(ask)
                 and 0 < bid < ask,
                 "Invalid broker Bid/Ask in future quote window")
        vals.append((stamp, bid, ask))
    _require(len(vals) >= 2, "Insufficient future broker quotes")
    vals.sort(key=lambda item: item[0])
    _require(vals[0][0] - start_ms <= START_GAP_MAX_MS
             and end_ms - vals[-1][0] <= END_GAP_MAX_MS,
             "Incomplete quote coverage at start or end of 60-minute window")
    _require(all(0 <= next_tick[0] - previous[0] <= BETWEEN_TICKS_MAX_MS
                 for previous, next_tick in zip(vals, vals[1:])),
             "Gapped broker quote history; price excursion unknown")
    first_bid = event["bid"]
    first_ask = event["ask"]
    if event["side"] == "BUY":
        favorable = max(0.0, max(b for _, b, _ in vals) - first_ask)
        adverse = max(0.0, first_ask - min(b for _, b, _ in vals))
    else:
        favorable = max(0.0, first_bid - min(a for _, _, a in vals))
        adverse = max(0.0, max(a for _, _, a in vals) - first_bid)
    return {
        "status": "POST_SIGNAL_QUOTES_OBSERVED_NO_FILL",
        "signal_event_utc_s": observed,
        "signal_bar_server_s": event["bar_server_s"],
        "style": event["style"], "side": event["side"],
        "atr_band": event["atr_band"],
        "quote_count": len(vals),
        "first_quote_ms": vals[0][0],
        "last_quote_ms": vals[-1][0],
        "horizon_seconds": HORIZON_SECONDS,
        "favorable_quote_excursion_price": round(favorable, 5),
        "adverse_quote_excursion_price": round(adverse, 5),
        "quote_units": "XAUUSD dollars per troy ounce (NOT account USD P/L)",
        "entry_order_planned": False,
        "executed_entry_fill_known": False,
        "sl_hit_known": False,
        "tp_hit_known": False,
    }


def _native_events(signals: Path, freeze_utc_s: int, now_utc_s: int):
    events, unknown, before_registration = [], [], 0
    seen = set()
    for path in _event_files(signals):
        try:
            _require(path.stat().st_size <= 4_000_000, "Oversized signal CSV")
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                _require(reader.fieldnames == list(FIELDS), "Invalid V2 CSV schema")
                for line, raw in enumerate(reader, 2):
                    try:
                        event = _valid_row(raw, path.name, now_utc_s)
                        if event["observed_utc_s"] <= freeze_utc_s:
                            before_registration += 1
                            continue
                        key = (event["style"], event["bar_server_s"])
                        _require(key not in seen, "Duplicate native signal bar")
                        seen.add(key)
                        events.append(event)
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        unknown.append({"file": path.name, "line": line,
                                        "reason": str(exc)[:180]})
        except (ValueError, OSError, UnicodeError, csv.Error) as exc:
            unknown.append({"file": path.name, "reason": str(exc)[:180]})
    return sorted(events, key=lambda e: e["observed_utc_s"]), unknown, before_registration


def review(report_dir: Path, signal_dir: Path, ea_source: Path,
           mt5, *, now_utc_s: int) -> dict:
    registration = freeze(report_dir, ea_source, now_utc_s=now_utc_s)
    events, unknown, excluded_old = _native_events(
        signal_dir, registration["frozen_at_utc_s"], now_utc_s)
    results, pending = [], []
    # Always inspect the newest bounded batch, not the first 64 forever:
    # otherwise a collector with 65+ native signals would never inspect
    # any subsequently recorded signal. Excluded older events remain
    # prominently counted and invalidate completeness claims.
    for event in events[-MAX_EVENTS_PER_REVIEW:]:
        key = {
            "style": event["style"], "event_utc_s": event["observed_utc_s"],
            "bar_server_s": event["bar_server_s"],
        }
        if now_utc_s * 1000 < event["tick_server_msc"] + (
            HORIZON_SECONDS + 60) * 1000:
            pending.append(key)
            continue
        try:
            result = quote_path(event, mt5, now_utc_s=now_utc_s)
        except (ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
            unknown.append({**key, "reason": str(exc)[:180]})
        else:
            results.append(result)
    not_reviewed = max(0, len(events) - MAX_EVENTS_PER_REVIEW)
    stats = {}
    for label, keep in {
        "SWEEP_BASELINE": lambda e: e["style"] == 3,
        "SWEEP_ATR_LOW": lambda e: e["style"] == 3 and
            e["atr_band"] == "AT_OR_BELOW_TRAILING_MEDIAN",
        "SWEEP_NO_BUY_HIGH_ATR": lambda e: e["style"] == 3 and not (
            e["side"] == "BUY" and e["atr_band"] == "ABOVE_TRAILING_MEDIAN"),
    }.items():
        chosen = [e for e in results if keep(e)]
        stats[label] = {
            "mature_quote_paths": len(chosen),
            "median_favorable_quote_excursion_price": (
                round(statistics.median(e["favorable_quote_excursion_price"]
                                        for e in chosen), 5) if chosen else None),
            "median_adverse_quote_excursion_price": (
                round(statistics.median(e["adverse_quote_excursion_price"]
                                        for e in chosen), 5) if chosen else None),
        }
    status = ("QUOTE_PATHS_UNKNOWN_NO_GO" if unknown or not_reviewed else
              "WAITING_FOR_NEW_NATIVE_SIGNALS" if not events else
              "WAITING_FOR_COMPLETED_POST_SIGNAL_WINDOWS" if not results else
              "POST_SIGNAL_QUOTE_EXCURSIONS_ONLY_UNVALIDATED")
    return {
        "schema": SCHEMA, "status": status,
        "registered_at_utc_s": registration["frozen_at_utc_s"],
        "horizon_seconds": HORIZON_SECONDS,
        "prospective_signals_seen": len(events),
        "pre_registration_signals_excluded": excluded_old,
        "quote_paths_complete_by_gap_heuristic": len(results),
        "paths_waiting_for_maturity": len(pending),
        "not_reviewed_due_to_bounded_batch": not_reviewed,
        "unknown_quote_paths": unknown,
        "post_signal_price_paths": results,
        "historical_candidate_filter_comparisons": stats,
        "quote_completeness_warning": (
            "MT5 historical ticks are retrieved AFTER native signals are logged; "
            "a max-gap heuristic cannot prove complete, independently signed "
            "or executable broker tick history. Unavailable windows remain UNKNOWN."
        ),
        "model_warning": (
            "No limit-entry fill or original SL/TP geometry is available. "
            "Favorable/adverse quote movement is NOT realized or simulated "
            "profit, not a filled trade, not a stop/target hit and not a win rate."
        ),
        "ea_binary_attested": False,
        "independent_out_of_sample_edge_validated": False,
        "broker_account_wide_order_count_verified": False,
        "orders_sent_by_this_reader": 0,
        "can_autotune_or_promote": False, "validated_edge": False,
        "connected_orders_authorized": False, "live": "LOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--signals-dir", type=Path)
    parser.add_argument("--terminal-path", type=Path)
    parser.add_argument("--terminal-data-dir", type=Path)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    ea_source = Path(__file__).resolve().parents[1] / "mt5_robot" / "QTS_Gold_Robot.mq5"
    mt5 = None
    try:
        study = select_study_dir(report_dir, ea_source)
        sigdir = (args.signals_dir or default_signals_dir()).resolve()
        now = int(datetime.now(UTC).timestamp())
        registration = freeze(study, ea_source, now_utc_s=now)
        events, errors, old = _native_events(sigdir, registration["frozen_at_utc_s"], now)
        # Without a mature prospective event, importing/initializing MT5
        # cannot add any evidence and can spuriously fail on busy terminals.
        # Still use the complete read-only review for NO-GO input errors.
        matured = any(now * 1000 >= e["tick_server_msc"] +
                      (HORIZON_SECONDS + 60) * 1000 for e in events[-MAX_EVENTS_PER_REVIEW:])
        if matured:
            mt5 = _demo_terminal(
                executable=args.terminal_path,
                data_dir=args.terminal_data_dir,
            )
        result = review(study, sigdir, ea_source, mt5, now_utc_s=now)
        result["study_epoch_dir"] = str(study)
        result["legacy_frozen_cohort_preserved"] = study != report_dir
        result["terminal_identity_bound_for_mature_quotes"] = (
            bool(mt5 is not None) and bool(args.terminal_path)
            and bool(args.terminal_data_dir)
        )
    except (ValueError, TypeError, OSError, KeyError, RuntimeError,
            csv.Error, json.JSONDecodeError) as exc:
        result = {
            "schema": SCHEMA, "status": "QUOTE_PATHS_UNAVAILABLE_NO_GO",
            "reason": str(exc)[:260],
            "can_autotune_or_promote": False, "validated_edge": False,
            "connected_orders_authorized": False, "live": "LOCKED",
        }
    finally:
        if mt5 is not None:
            mt5.shutdown()
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        out = report_dir / "QTS_FORWARD_SHADOW_V2_QUOTE_PATHS.json"
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    except OSError as exc:
        print("QTS QUOTE PATH NO-GO: cannot save report: " + str(exc)[:200])
        return 2
    print("QTS Forward Shadow 60-minute quotes: " + result["status"])
    print("Report: " + str(out))
    print("LIVE LOCKED | NOT an entry fill, P/L, SL or TP assessment")
    return 2 if "NO_GO" in result["status"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
