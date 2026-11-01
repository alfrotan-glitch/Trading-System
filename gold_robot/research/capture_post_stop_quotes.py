"""Read-only WMMarkets post-stop quote replay for a saved QTS V4 MT5 run.

Uses the *already open* MetaTrader 5 terminal's historical bid/ask ticks.
No order_send, login, strategy edits, threshold tuning, or live authorization.
The broker terminal's historical tick database is NOT automatically identical
to the exact tester's simulated tick stream; no winning-trade claim follows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from stop_reversal_audit import audit, load_stops, HORIZONS_MIN
from v4_post_stop_cohorts import summarize, validate_source

MAX_BUNDLE_BYTES = 5_000_000
MAX_TICKS_PER_STOP = 500_000
POST_STOP_MS = 120 * 60_000
FINISH_BUFFER_MS = 60_000


def read_attribution(bundle: Path) -> dict:
    if not bundle.is_file():
        raise ValueError("No saved QTS evidence ZIP. Run QTS_SHARE_RESULTS.bat first.")
    with zipfile.ZipFile(bundle) as archive:
        matches = [x for x in archive.infolist()
                   if x.filename == "QTS_V4_POSITION_ATTRIBUTION.json"]
        if len(matches) != 1 or matches[0].file_size > MAX_BUNDLE_BYTES:
            raise ValueError("Missing/duplicate/oversized original V4 broker attribution")
        data = json.loads(archive.read(matches[0]).decode("utf-8-sig"))
    validate_source(data)
    return data


def stop_source(row: dict) -> dict[str, str]:
    return {
        "trade_id": "7:" + str(row["position_id"]),
        "side": row["side"],
        "entry_time_ms": str(row["entry_time_msc"]),
        "exit_time_ms": str(row["exit_time_msc"]),
        "entry_price": str(row["entry_price"]),
        "initial_stop_price": str(row["initial_sl"]),
        "initial_target_price": str(row["initial_tp"]),
        "exit_price": str(row["exit_price"]),
        "exit_reason": "SL",
    }


def replay_from_mt5(data: dict, mt5, *, symbol: str = "XAUUSD@") -> tuple[dict, dict]:
    """Testable read-only adapter; supply a fake MT5 API in isolated tests."""
    if symbol != "XAUUSD@":
        raise ValueError("The existing V4 broker report is specifically XAUUSD@")
    rows = validate_source(data)
    stopped = [row for row in rows if row["exit_reason"] == "DEAL_REASON_SL"]
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if not account or not terminal:
        raise ValueError("MT5 history source has no verified connected broker terminal")
    if "wmmarkets" not in str(account.server).lower() or str(account.currency).upper() != "USD":
        raise ValueError("Wrong MT5 server/account currency for saved WMMarkets USD test")
    if mt5.symbol_info(symbol) is None:
        raise ValueError("XAUUSD@ missing from this WMMarkets terminal; do not substitute XAUUSD")
    all_individual = []
    aggregate = {str(m): {"eligible_stops_with_contiguous_executable_quotes": 0,
                          "reclaimed_entry_count": 0,
                          "target_eligible_stops": 0,
                          "post_stop_original_target_touch_count": 0,
                          "not_eligible_or_incomplete": 0} for m in HORIZONS_MIN}
    tick_total = 0
    fingerprint = hashlib.sha256()
    quality = {
        "mt5_tick_selection": "COPY_TICKS_INFO_BID_ASK_CHANGES_ONLY",
        "bad_bid_ask_rows": 0,
        "out_of_order_rows": 0,
        "out_of_range_rows": 0,
        "ignored_pre_stop_boundary_rows": 0,
        "ignored_post_buffer_boundary_rows": 0,
        "malformed_rows": 0,
        "failed_history_reads": 0,
        "oversized_history_reads": 0,
        "per_stop": [],
    }
    for row in stopped:
        stops, ignored = load_stops([stop_source(row)])
        if ignored != 0 or len(stops) != 1:
            raise ValueError("Broker stop identity/geometry did not validate")
        exit_ms = row["exit_time_msc"]
        end_ms = exit_ms + POST_STOP_MS + FINISH_BUFFER_MS
        # MT5 tick-history queries are second-based even though executions have
        # millisecond timestamps. Deliberately request the containing UTC
        # seconds, then isolate boundary-only quotes below.
        begin = datetime.fromtimestamp(exit_ms // 1000, timezone.utc)
        end = datetime.fromtimestamp((end_ms + 999) // 1000, timezone.utc)
        # Broker quote-only changes avoid last/volume-only trade ticks.
        # On actual MT5 terminals, COPY_TICKS_ALL can include rows with
        # missing/unusable bid/ask, which used to abort ALL 33 stops.
        original = mt5.copy_ticks_range(symbol, begin, end, mt5.COPY_TICKS_INFO)
        diagnostics = {
            "position_id": str(row["position_id"]),
            "tick_rows_returned": 0,
            "usable_bid_ask_rows": 0,
            "bad_bid_ask_rows": 0,
            "out_of_order_rows": 0,
            "out_of_range_rows": 0,
            "ignored_pre_stop_boundary_rows": 0,
            "ignored_post_buffer_boundary_rows": 0,
            "query_start_utc": begin.isoformat(),
            "query_end_utc": end.isoformat(),
            "malformed_rows": 0,
            "read_status": "OK",
            "affected_unknown_horizons_minutes": [],
        }
        observed = []
        invalid_horizons = set()
        previous = None
        if original is None:
            diagnostics["read_status"] = "HISTORICAL_QUOTE_READ_FAILED"
            quality["failed_history_reads"] += 1
            invalid_horizons.update(HORIZONS_MIN)
        elif len(original) > MAX_TICKS_PER_STOP:
            diagnostics["read_status"] = "HISTORICAL_QUOTE_WINDOW_TOO_LARGE"
            diagnostics["tick_rows_returned"] = len(original)
            quality["oversized_history_reads"] += 1
            invalid_horizons.update(HORIZONS_MIN)
        else:
            diagnostics["tick_rows_returned"] = len(original)
            for tick in original:
                try:
                    ms = int(tick["time_msc"])
                    bid = float(tick["bid"])
                    ask = float(tick["ask"])
                except (KeyError, ValueError, TypeError, OverflowError):
                    diagnostics["malformed_rows"] += 1
                    quality["malformed_rows"] += 1
                    invalid_horizons.update(HORIZONS_MIN)
                    continue
                # A row supplied out of order is a genuine chronology fault,
                # including when it lies in the query's boundary seconds.
                if previous is not None and ms < previous:
                    diagnostics["out_of_order_rows"] += 1
                    quality["out_of_order_rows"] += 1
                    invalid_horizons.update(HORIZONS_MIN)
                    continue
                previous = ms
                # MT5 can return several ticks from the whole *second*
                # containing an SL execution. These are not post-stop quotes.
                # They must not invalidate otherwise complete later horizons.
                if ms <= exit_ms and exit_ms - ms < 1000:
                    diagnostics["ignored_pre_stop_boundary_rows"] += 1
                    quality["ignored_pre_stop_boundary_rows"] += 1
                    continue
                # Likewise discard <=1-second overfetch past the extra
                # 60-second completion buffer, never from within a horizon.
                if ms > end_ms and ms - end_ms < 1000:
                    diagnostics["ignored_post_buffer_boundary_rows"] += 1
                    quality["ignored_post_buffer_boundary_rows"] += 1
                    continue
                if ms <= exit_ms or ms > end_ms:
                    diagnostics["out_of_range_rows"] += 1
                    quality["out_of_range_rows"] += 1
                    invalid_horizons.update(HORIZONS_MIN)
                    continue
                if (not math.isfinite(bid) or not math.isfinite(ask) or
                        bid <= 0 or ask <= bid):
                    diagnostics["bad_bid_ask_rows"] += 1
                    quality["bad_bid_ask_rows"] += 1
                    # Never turn a broken quote into proof of a recovery.
                    # Valid shorter horizons ending BEFORE the anomaly can
                    # still be reported; the affected and longer ones cannot.
                    invalid_horizons.update(
                        h for h in HORIZONS_MIN if ms <= exit_ms + h * 60_000
                    )
                    continue
                observed.append({"time_ms": str(ms), "bid": repr(bid), "ask": repr(ask)})
                fingerprint.update(
                    f"{row['position_id']}|{ms}|{bid:.8f}|{ask:.8f}\n".encode("ascii")
                )
        single = audit(stops, observed)
        tick_total += len(observed)
        individual = single["individual_trade_windows"][0]
        for minutes in invalid_horizons:
            window = individual["windows"][str(minutes)]
            window["complete"] = False
            # Never leak a hindsight TP / reclaim from an untrusted window.
            for key in list(window):
                if key != "complete":
                    window[key] = False if key == "reclaimed_entry" else None
        diagnostics["usable_bid_ask_rows"] = len(observed)
        diagnostics["affected_unknown_horizons_minutes"] = sorted(invalid_horizons)
        quality["per_stop"].append(diagnostics)
        all_individual.append(individual)
        for minutes in HORIZONS_MIN:
            key = str(minutes)
            window = individual["windows"][key]
            dest = aggregate[key]
            if window["complete"]:
                dest["eligible_stops_with_contiguous_executable_quotes"] += 1
                dest["target_eligible_stops"] += 1
                if window["reclaimed_entry"]:
                    dest["reclaimed_entry_count"] += 1
                if window["first_target_touch_ms"] is not None:
                    dest["post_stop_original_target_touch_count"] += 1
            else:
                dest["not_eligible_or_incomplete"] += 1
    # This summary is an independent, read-only comparison of quotes from a
    # connected broker terminal, NOT evidence that the tester used each tick.
    replay = {
        "status": "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY",
        "stop_trades": len(stopped),
        "ticks_scanned": tick_total,
        "max_contiguous_quote_gap_ms": 60_000,
        "horizons_minutes": aggregate,
        "individual_trade_windows": all_individual,
        "quote_source": "WMMarkets_CONNECTED_MT5_TERMINAL_HISTORICAL_TICKS",
        "quote_data_quality": quality,
        "same_source_as_native_tester_not_proven": True,
        "historical_quote_fingerprint_sha256": fingerprint.hexdigest(),
        "warnings": [
            "Boundary-only quotes before an SL or beyond the completion buffer are excluded without inventing post-stop paths.",
            "Materially out-of-range, invalid bid/ask, chronology or missing quote rows keep affected windows UNKNOWN.",
            "Terminal historical ticks may differ from MT5 tester ticks: real-tick mode can replace inconsistent or missing minute ticks.",
            "Missing or non-contiguous post-stop quote windows are UNKNOWN, never a missed/achieved target.",
            "Original TP touched AFTER SL is not a hypothetical executable winning trade.",
            "All quotes are read-only; no live trades, credentials, or order calls.",
        ],
    }
    return replay, summarize(data, replay)


def main(argv=None, *, mt5_module=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--terminal-exe", type=str, default="")
    args = parser.parse_args(argv)
    data = read_attribution(args.bundle)
    if mt5_module is None:
        try:
            import MetaTrader5 as mt5_module
        except ImportError as exc:
            raise ValueError(
                "MetaTrader5 Python package unavailable. Install the official "
                "MetaTrader5 package for the Python used by this QTS launcher; "
                "no price path can be inferred from candles."
            ) from exc
    kwargs = {"path": args.terminal_exe} if args.terminal_exe else {}
    if not mt5_module.initialize(**kwargs):
        raise ValueError("Cannot connect read-only to WMMarkets MT5 terminal: " +
                         str(mt5_module.last_error()))
    try:
        replay, cohorts = replay_from_mt5(data, mt5_module)
    finally:
        mt5_module.shutdown()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    (args.output_directory / "QTS_POST_STOP_REAL_TICK_REVIEW.json").write_text(
        json.dumps(replay, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_directory / "QTS_V4_POST_STOP_STRATEGY_COHORTS.json").write_text(
        json.dumps(cohorts, indent=2) + "\n", encoding="utf-8"
    )
    covered = cohorts["by_strategy_and_regime"]
    coverage = sum(c["horizons"]["120"]["eligible_quote_complete"] for c in covered)
    touch = sum(c["horizons"]["120"]["original_tp_touched"] for c in covered)
    summary = (
        "QTS Gold - Read-only historical post-stop analysis\n"
        "LIVE LOCKED. PROFITABLE EDGE NOT VALIDATED.\n"
        f"Native SL exits: {cohorts['native_stop_exits']}\n"
        f"Quote-complete 120-minute windows: {coverage}\n"
        f"Original TP touched after stop in complete 120-minute windows: {touch}\n"
        f"Unknown/incomplete: {cohorts['native_stop_exits'] - coverage}\n"
        f"Bad or crossed bid/ask quote rows: {replay['quote_data_quality']['bad_bid_ask_rows']}\n"
        f"Ignored UTC-second boundary-only rows: "
        f"{replay['quote_data_quality']['ignored_pre_stop_boundary_rows'] + replay['quote_data_quality']['ignored_post_buffer_boundary_rows']}\n"
        f"Malformed/out-of-order/out-of-range rows: "
        f"{replay['quote_data_quality']['malformed_rows'] + replay['quote_data_quality']['out_of_order_rows'] + replay['quote_data_quality']['out_of_range_rows']}\n"
        f"Failed/oversized tick reads: "
        f"{replay['quote_data_quality']['failed_history_reads'] + replay['quote_data_quality']['oversized_history_reads']}\n"
        f"Status: {cohorts['status']}\n"
        "Broker terminal historical quotes may differ from tester execution history.\n"
        "A touch after SL does NOT prove holding longer or moving SL would win.\n"
        "Research only: original trading rules and broker permissions unchanged.\n"
    )
    (args.output_directory / "QTS_POST_STOP_SUMMARY.txt").write_text(
        summary, encoding="utf-8"
    )
    print(summary)
    return 0 if cohorts["status"] == "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print("POST-STOP NO-GO: " + str(error), file=sys.stderr)
        raise SystemExit(2)
