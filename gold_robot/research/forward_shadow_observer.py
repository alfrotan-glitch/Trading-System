"""Forward-only, order-free accounting for real native DEMO closed-bar candidates.

The canonical MQL5 EA exports candidates in its UNARMED DEMO diagnostic path.
This reader NEVER generates a signal from market history, sends broker orders,
simulates fills, or changes any EA parameters. It locks candidate policies at
the first use and excludes every event at/before that registration timestamp.
Candidate count is NOT an executed trade or verified economic edge.
Historical-compatible ATR = simple mean of 14 closed-bar true ranges;
reference median = 48 preceding such ATR readings, excluding current ATR.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "qts.mt5.forward_shadow_observer.v2"
EVENT_SCHEMA = "qts.mt5.forward_shadow_signal.v2"
FREEZE_SCHEMA = "qts.mt5.forward_shadow_freeze.v2"
FIELDS = (
    "schema", "observed_utc_s", "closed_bar_open_server_s",
    "tick_server_time_msc", "symbol", "timeframe", "style", "side",
    "bid", "ask", "atr14", "prior_48_atr_median", "atr_band", "source",
)
POLICIES = {
    "BASELINE": "Keep all native closed-bar style 3 signals",
    "SHADOW_ATR_LOW": "Keep only style 3 ATR14 <= median of 48 older rolling-TR14 ATR readings",
    "SHADOW_NO_BUY_HIGH_ATR": "Keep style 3 unless BUY and ATR14 > older-bar median",
}
POLICY_DIGEST = hashlib.sha256(
    json.dumps(POLICIES, sort_keys=True).encode("ascii")
).hexdigest()
SOURCES = {1: "RETEST", 3: "SWEEP_RECLAIM"}
FILE_PATTERN = re.compile(r"^QTS_ForwardShadowV2_Style([13])_(\d{6})\.csv$")


def _required(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _write_once(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create prevents silent resetting of the future registration.
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(report_dir: Path, ea_source: Path, *, now_utc_s: int) -> dict:
    _required(ea_source.is_file(), "Canonical native EA source is missing")
    _required(now_utc_s > 0, "Invalid UTC registration time")
    marker = report_dir / "QTS_FORWARD_SHADOW_V2_FROZEN.json"
    if not marker.exists():
        try:
            _write_once(marker, {
                "schema": FREEZE_SCHEMA,
                "frozen_at_utc_s": now_utc_s,
                "ea_source_sha256": _sha256(ea_source),
                "policy_sha256": POLICY_DIGEST,
                "policies": POLICIES,
                "symbol": "XAUUSD@", "timeframe": "M15",
                "allowed_styles": [1, 3],
                "native_orders_allowed": False,
                "live": "LOCKED",
                "validated_edge": False,
                "validation": "PROSPECTIVE_UNATTESTED_NATIVE_BINARY",
            })
        except FileExistsError:
            pass
    data = json.loads(marker.read_text(encoding="utf-8"))
    _required(data.get("schema") == FREEZE_SCHEMA
             and data.get("live") == "LOCKED"
             and data.get("validated_edge") is False
             and data.get("native_orders_allowed") is False
             and data.get("symbol") == "XAUUSD@"
             and data.get("timeframe") == "M15"
             and data.get("allowed_styles") == [1, 3]
             and data.get("policies") == POLICIES
             and data.get("policy_sha256") == POLICY_DIGEST
             and data.get("ea_source_sha256") == _sha256(ea_source),
             "Frozen EA source or Shadow rules changed: no valid comparison")
    start = data.get("frozen_at_utc_s")
    _required(type(start) is int and 0 < start <= now_utc_s,
              "Invalid or future registration timestamp")
    return data


def _valid_row(row: dict, filename: str, now_utc_s: int) -> dict:
    _required(set(row) == set(FIELDS), "Unexpected native signal CSV fields")
    _required(row["schema"] == EVENT_SCHEMA and
              row["source"] == "NATIVE_CLOSED_BAR_UNARMED_DEMO"
              and row["symbol"] == "XAUUSD@" and row["timeframe"] == "M15",
              "Wrong native signal source/symbol/timeframe")
    style = int(row["style"])
    expected = FILE_PATTERN.fullmatch(filename)
    _required(style in SOURCES and expected is not None
              and int(expected.group(1)) == style,
              "Native signal style does not match file identity")
    observation = int(row["observed_utc_s"])
    candle = int(row["closed_bar_open_server_s"])
    tick_ms = int(row["tick_server_time_msc"])
    _required(0 < observation <= now_utc_s + 120 and candle > 0
              and 900_000 <= tick_ms - candle * 1000 <= 1_800_000,
              "Impossible native bar/tick timeline")
    declared_month = datetime.fromtimestamp(observation, tz=timezone.utc).strftime("%Y%m")
    _required(expected.group(2) == declared_month, "Native signal file/month mismatch")
    side = row["side"]
    _required(side in ("BUY", "SELL"), "Invalid native signal direction")
    bid, ask, atr, median = (
        float(row[k]) for k in ("bid", "ask", "atr14", "prior_48_atr_median")
    )
    _required(all(math.isfinite(x) and x > 0 for x in (bid, ask, atr, median))
              and ask > bid, "Invalid bid/ask/closed-bar ATR")
    band = ("ABOVE_TRAILING_MEDIAN" if atr > median else
            "AT_OR_BELOW_TRAILING_MEDIAN")
    _required(band == row["atr_band"], "Native ATR band contradicts raw values")
    return {"style": style, "side": side, "bar_server_s": candle,
            "observed_utc_s": observation, "tick_server_msc": tick_ms,
            "atr_band": band, "bid": bid, "ask": ask,
            "atr14": atr, "prior_48_atr_median": median}


def _event_files(signal_dir: Path) -> list[Path]:
    if not signal_dir.is_dir():
        return []
    files = [p for p in signal_dir.iterdir()
             if p.is_file() and FILE_PATTERN.fullmatch(p.name)]
    _required(len(files) <= 80, "Too many native Shadow event files")
    return sorted(files)


def review(report_dir: Path, signal_dir: Path, ea_source: Path,
           *, now_utc_s: int) -> dict:
    registration = freeze(report_dir, ea_source, now_utc_s=now_utc_s)
    records, excluded_old, invalid = [], 0, []
    seen = set()
    files = _event_files(signal_dir)
    for path in files:
        try:
            _required(path.stat().st_size <= 4_000_000,
                      "Native source CSV exceeds review safety limit")
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                _required(reader.fieldnames == list(FIELDS),
                          "Unsupported native candidate CSV header")
                for lineno, row in enumerate(reader, 2):
                    try:
                        item = _valid_row(row, path.name, now_utc_s)
                        if item["observed_utc_s"] <= registration["frozen_at_utc_s"]:
                            excluded_old += 1
                            continue
                        key = (item["style"], item["bar_server_s"])
                        _required(key not in seen,
                                  "Duplicate or conflicting same-bar candidate")
                        seen.add(key)
                        records.append(item)
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        invalid.append({"file": path.name, "line": lineno,
                                        "problem": str(exc)[:180]})
            if len(records) > 100_000:
                raise ValueError("Review size exceeds bounded research window")
        except (ValueError, OSError, UnicodeError, csv.Error) as exc:
            invalid.append({"file": path.name, "problem": str(exc)[:180]})
    cohorts = {}
    for style, name in SOURCES.items():
        cohort = [x for x in records if x["style"] == style]
        cohorts[name] = {
            "native_closed_bar_candidate_count": len(cohort),
            "buy_count": sum(x["side"] == "BUY" for x in cohort),
            "sell_count": sum(x["side"] == "SELL" for x in cohort),
            "above_trailing_median_count": sum(
                x["atr_band"] == "ABOVE_TRAILING_MEDIAN" for x in cohort),
            "at_or_below_trailing_median_count": sum(
                x["atr_band"] == "AT_OR_BELOW_TRAILING_MEDIAN" for x in cohort),
        }
    sweeps = [x for x in records if x["style"] == 3]
    counts = {
        "BASELINE": len(sweeps),
        "SHADOW_ATR_LOW": sum(
            x["atr_band"] == "AT_OR_BELOW_TRAILING_MEDIAN" for x in sweeps),
        "SHADOW_NO_BUY_HIGH_ATR": sum(not (
            x["side"] == "BUY" and x["atr_band"] == "ABOVE_TRAILING_MEDIAN")
            for x in sweeps),
    }
    status = ("EVIDENCE_GAPS_NO_GO" if invalid else
              "REGISTERED_WAITING_FOR_NATIVE_DEMO_SIGNALS" if not records else
              "FORWARD_SIGNALS_OBSERVED_ONLY_NO_TRADE_OUTCOME")
    return {
        "schema": SCHEMA, "status": status,
        "frozen_at_utc_s": registration["frozen_at_utc_s"],
        "rule_sha256": POLICY_DIGEST,
        "native_ea_source_sha256": registration["ea_source_sha256"],
        "binary_attestation": "NOT_VERIFIED",
        "source": "UNARMED_DEMO_NATIVE_CLOSED_BAR_CSV_UNAUTHENTICATED",
        "files_found": len(files),
        "candidate_events_since_registration": len(records),
        "pre_registration_events_excluded": excluded_old,
        "evidence_gaps": invalid,
        "native_candidates_by_style": cohorts,
        "style_3_shadow_candidate_counts": counts,
        "future_price_paths_captured": False,
        "orders_sent_by_this_reader": 0,
        "broker_account_wide_order_count_verified": False,
        "executed_fills_observed": False,
        "performance_pnl_available": False,
        "can_claim_profitable_edge": False,
        "replay_or_autotune_performed": False,
        "note": ("Candidates are NOT fills; EA emits signals only, not a "
                 "validated order limit/SL/TP. No economic P/L or forward "
                 "win rate can be inferred from these counts. Do not infer "
                 "any bar-time UTC without broker clock provenance."),
        "signal_integrity_warning": ("Local CSV and local freeze are NOT "
                                      "independently signed or authenticated; "
                                      "installed EX5 not hash-attested."),
        "can_autotune_or_promote": False,
        "connected_orders_authorized": False, "validated_edge": False,
        "live": "LOCKED",
    }


def default_signals_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    _required(bool(appdata), "Windows APPDATA is missing; cannot locate MT5 common files")
    return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--signals-dir", type=Path)
    parser.add_argument("--ea-source", type=Path)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    marker_path = report_dir / "QTS_FORWARD_SHADOW_V2_FROZEN.json"
    source = args.ea_source or (Path(__file__).resolve().parents[1] /
                               "mt5_robot" / "QTS_Gold_Robot.mq5")
    try:
        result = review(
            report_dir, (args.signals_dir or default_signals_dir()).resolve(),
            source.resolve(), now_utc_s=int(datetime.now(timezone.utc).timestamp()))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = {"schema": SCHEMA, "status": "FORWARD_OBSERVER_BLOCKED_NO_GO",
                  "error": str(exc)[:260], "freeze_file": str(marker_path),
                  "live": "LOCKED", "validated_edge": False,
                  "connected_orders_authorized": False,
                  "can_autotune_or_promote": False,
                  "performance_pnl_available": False}
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "QTS_FORWARD_SHADOW_V2_REPORT.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    except OSError as exc:
        print("QTS SHADOW NO-GO: failed to save report: " + str(exc)[:200])
        return 2
    print("QTS FORWARD SHADOW: " + result["status"])
    print("Native candidate events: " +
          str(result.get("candidate_events_since_registration", "UNKNOWN")))
    print("Report: " + str(path))
    print("No orders, no P/L claims, LIVE LOCKED.")
    return 2 if "NO_GO" in result["status"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
