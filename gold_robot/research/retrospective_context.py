"""Read-only, no-lookahead market-context audit for native MT5 Retest/Sweep tests.

This is descriptive research, not an EA, a trade filter, or trading permission.
Only H1/M15 bars closed BEFORE entry and executable quotes timestamped at/before
entry may be used. Data missing from broker history is explicitly UNKNOWN.
No network upload, account identity export, login, or broker order functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "qts.mt5.retrospective_context.v1"
UTC = timezone.utc
SYMBOL = "XAUUSD@"
STYLES = {1: "RETEST", 3: "SWEEP_RECLAIM"}
MAX_SOURCE_BYTES = 5_000_000


def _required(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json_bytes(raw: bytes) -> dict:
    _required(len(raw) <= MAX_SOURCE_BYTES, "Oversized research evidence")
    data = json.loads(raw.decode("utf-8-sig"))
    _required(isinstance(data, dict), "Expected JSON object")
    return data


def load_evidence(path: Path) -> tuple[dict, dict, str]:
    """Read only the two named evidence records, never arbitrary ZIP entries."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            _required(len(entries) < 100, "Oversized research archive")
            for name in ("QTS_TRADE_BY_TRADE.json", "OPEN_RESULTS.json"):
                matching = [e for e in entries if e.filename == name]
                _required(len(matching) == 1, f"{name}: missing or duplicated")
                _required(matching[0].file_size <= MAX_SOURCE_BYTES,
                          f"{name}: oversized broker evidence")
            raw = archive.read("QTS_TRADE_BY_TRADE.json")
            manifest = _json_bytes(archive.read("OPEN_RESULTS.json"))
    else:
        _required(path.name == "QTS_TRADE_BY_TRADE.json",
                  "Select QTS_HOLDOUT_REVIEW.zip or QTS_TRADE_BY_TRADE.json")
        raw = path.read_bytes()
        manifest = _json_bytes((path.parent / "OPEN_RESULTS.json").read_bytes())
    forensic = _json_bytes(raw)
    # Keep malformed individual deals visible for quarantined NO-GO audit.
    # Envelope identity must still be strict before opening any MT5 history.
    validate_envelope(forensic, manifest)
    return forensic, manifest, hashlib.sha256(raw).hexdigest()


def validate_envelope(forensic: dict, manifest: dict) -> tuple[datetime, datetime]:
    _required(forensic.get("schema") == "qts.mt5.trade_forensics.v1"
              and forensic.get("status") in ("SELECTED_IMPORTED_FOR_REVIEW",
                                             "EVIDENCE_GAPS_NO_GO"),
              "Unrecognized native deal ledger state")
    _required(forensic.get("live") == "LOCKED"
              and forensic.get("edge_validated") is False
              and manifest.get("live") == "LOCKED"
              and manifest.get("validated_edge") is False,
              "Research safety contract missing")
    _required(manifest.get("symbol") == SYMBOL and manifest.get("model") == 4
              and manifest.get("research_variant") == "BASELINE"
              and manifest.get("targeted") is True
              and manifest.get("selected_styles") == [1, 3],
              "Wrong native symbol/model/strategy/baseline identity")
    _required(forensic.get("targeted") is True
              and forensic.get("selected_styles") == [1, 3],
              "Forensics are not the selected baseline strategies")
    _required(isinstance(forensic.get("trades"), list)
              and len(forensic["trades"]) > 0, "No broker positions")
    start = datetime.strptime(manifest["from_date"], "%Y.%m.%d").replace(tzinfo=UTC)
    end = datetime.strptime(manifest["to_date"], "%Y.%m.%d").replace(tzinfo=UTC)
    _required(start < end, "Invalid test date window")
    return start, end


def validate_position(row: dict, start: datetime, end: datetime,
                      unique: set[tuple[int, str]]) -> None:
    _required(isinstance(row, dict), "Invalid native broker position record")
    identity = str(row.get("position_id", "UNKNOWN"))
    quality = row.get("status")
    reason = row.get("exit_reason")
    _required(row.get("style") in STYLES and row.get("side") in ("BUY", "SELL"),
              f"Position {identity}: unknown style or direction")
    # The canonical broker exporter marks fully reconciled multi-exit
    # positions COMPLETE_MULTI_EXIT. Reject incomplete, open and reversal
    # evidence, but do NOT reject valid multi-leg exits or expert/stop-out
    # exit causes merely because they are not a simple SL/TP.
    _required(quality in ("COMPLETE", "COMPLETE_MULTI_EXIT"),
              f"Position {identity}: evidence status {quality!r}; "
              "incomplete/reversed broker positions cannot be studied")
    _required(isinstance(reason, str) and
              (reason.startswith("DEAL_REASON_") or reason == "MIXED_EXIT_REASONS"),
              f"Position {identity}: invalid broker exit reason {reason!r}")
    key = (row["style"], identity)
    _required(identity not in ("", "None", "UNKNOWN") and key not in unique,
              "Duplicate or missing native broker position identity")
    unique.add(key)
    first = int(row["entry_time_msc"])
    last = int(row["exit_time_msc"])
    _required(start.timestamp() * 1000 <= first < end.timestamp() * 1000
              and first < last, f"Position {identity}: outside native test window")
    lots = float(row["entry_lots"])
    exit_lots = float(row["exit_lots"])
    net = float(row["net_usd"])
    gross = float(row["gross_usd"])
    charges = float(row["charges_usd"])
    _required(all(math.isfinite(v) for v in (lots, exit_lots, net, gross, charges))
              and lots > 0 and abs(lots - exit_lots) < 0.000001
              and abs(net - gross - charges) < 0.05,
              f"Position {identity}: unreconciled broker position P/L or volume")
    legs = row.get("exit_legs")
    _required(isinstance(legs, list) and legs,
              f"Position {identity}: missing broker exit legs")
    _required((quality == "COMPLETE_MULTI_EXIT") == (len(legs) > 1),
              f"Position {identity}: exit-leg count contradicts broker status")
    _required((reason == "MIXED_EXIT_REASONS") ==
              (len({leg.get("reason") for leg in legs
                    if isinstance(leg, dict)}) > 1),
              f"Position {identity}: mixed-exit attribution disagrees with legs")
    leg_total = 0.0
    leg_times = []
    for leg in legs:
        _required(isinstance(leg, dict)
                  and isinstance(leg.get("reason"), str)
                  and leg["reason"].startswith("DEAL_REASON_"),
                  f"Position {identity}: invalid broker exit leg")
        leg_lots = float(leg["lots"])
        leg_time = int(leg["time_msc"])
        _required(math.isfinite(leg_lots) and leg_lots > 0
                  and first <= leg_time <= last,
                  f"Position {identity}: invalid exit volume/time")
        leg_total += leg_lots
        leg_times.append(leg_time)
    _required(abs(leg_total - exit_lots) < 0.000001
              and leg_times == sorted(leg_times)
              and leg_times[-1] == last,
              f"Position {identity}: incomplete or out-of-order exit evidence")
    if reason != "MIXED_EXIT_REASONS":
        _required(all(leg["reason"] == reason for leg in legs),
                  f"Position {identity}: broker exit reason disagrees with legs")


def validate_evidence(forensic: dict, manifest: dict) -> None:
    """Strict contract for tests and any caller that requires zero exclusions."""
    start, end = validate_envelope(forensic, manifest)
    unique: set[tuple[int, str]] = set()
    for row in forensic["trades"]:
        validate_position(row, start, end, unique)


def ema(closes: list[float], period: int) -> float:
    _required(len(closes) >= period * 2, "H1 EMA warmup unavailable")
    alpha = 2.0 / (period + 1)
    result = statistics.fmean(closes[:period])
    for close in closes[period:]:
        result = alpha * close + (1.0 - alpha) * result
    return result


def atr_at(bars: list[dict], stop: int, period: int = 14) -> float:
    """TR from bars [stop-period, stop), with their previous closed bar."""
    _required(stop >= period + 1, "ATR warmup unavailable")
    tr = []
    for idx in range(stop - period, stop):
        bar = bars[idx]
        prev_close = float(bars[idx - 1]["close"])
        tr.append(max(float(bar["high"]) - float(bar["low"]),
                      abs(float(bar["high"]) - prev_close),
                      abs(float(bar["low"]) - prev_close)))
    result = statistics.fmean(tr)
    _required(math.isfinite(result) and result > 0, "Invalid historical ATR")
    return result


def _closed_bars(mt5, timeframe: int, timestamp_s: float, seconds: int,
                 *, need: int = 110) -> list[dict]:
    # copy_rates_from can include a still-forming bar. Explicitly exclude it.
    when = datetime.fromtimestamp(timestamp_s, UTC)
    rates = mt5.copy_rates_from(SYMBOL, timeframe, when, 180)
    _required(rates is not None, "Broker OHLC history unavailable")
    closed = []
    for r in rates:
        t = int(r["time"])
        if t + seconds > timestamp_s:
            continue
        values = {name: float(r[name]) for name in ("open", "high", "low", "close")}
        _required(all(math.isfinite(v) and v > 0 for v in values.values())
                  and values["low"] <= values["high"], "Invalid broker OHLC")
        closed.append({"time": t, **values})
    closed.sort(key=lambda x: x["time"])
    _required(len(closed) >= need, "Insufficient closed-bar history")
    _required(closed[-1]["time"] + seconds > timestamp_s - seconds * 2,
              "Closed-bar history stale at entry")
    _required(len({b["time"] for b in closed}) == len(closed),
              "Duplicate broker bar timestamp")
    return closed


def market_at_entry(mt5, entry_ms: int) -> dict:
    """Fail closed for missing/stale evidence; never forward-fill market quotes."""
    timestamp_s = entry_ms / 1000.0
    try:
        h1 = _closed_bars(mt5, mt5.TIMEFRAME_H1, timestamp_s, 3600)
        m15 = _closed_bars(mt5, mt5.TIMEFRAME_M15, timestamp_s, 900)
        h1fast = ema([b["close"] for b in h1], 20)
        h1slow = ema([b["close"] for b in h1], 50)
        atr = atr_at(m15, len(m15))
        historical_atrs = [atr_at(m15, idx) for idx in range(len(m15) - 48, len(m15))]
        atr_ref = statistics.median(historical_atrs)
        _required(atr_ref > 0, "No ATR reference")
        when = datetime.fromtimestamp(timestamp_s, UTC)
        ticks = mt5.copy_ticks_range(SYMBOL, when - timedelta(seconds=10),
                                     when, mt5.COPY_TICKS_ALL)
        _required(ticks is not None and len(ticks) > 0, "Historical Bid/Ask missing")
        possible = [x for x in ticks if int(x["time_msc"]) <= entry_ms]
        _required(possible, "Only future quotes are available")
        tick = max(possible, key=lambda x: int(x["time_msc"]))
        tick_age_ms = entry_ms - int(tick["time_msc"])
        bid = float(tick["bid"])
        ask = float(tick["ask"])
        _required(0 <= tick_age_ms <= 5000 and 0 < bid < ask,
                  "Stale/invalid executable quote")
        spread = ask - bid
        bias = "BUY" if h1fast > h1slow else "SELL" if h1fast < h1slow else "NEUTRAL"
        return {
            "status": "COMPLETE_CLOSED_BAR_AND_BID_ASK",
            "h1_ema20": round(h1fast, 5),
            "h1_ema50": round(h1slow, 5),
            "h1_bias": bias,
            "m15_atr14": round(atr, 5),
            "m15_atr_ratio_to_trailing_median": round(atr / atr_ref, 5),
            "spread_price": round(spread, 5),
            "spread_to_atr": round(spread / atr, 5),
            "quote_age_ms": tick_age_ms,
            "h1_last_closed_open_utc": h1[-1]["time"],
            "m15_last_closed_open_utc": m15[-1]["time"],
        }
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return {"status": "UNKNOWN_MARKET_HISTORY", "missing_reason": str(exc)[:150]}


def _cohort(rows: list[dict]) -> dict:
    n = len(rows)
    positive = [r for r in rows if r["net_usd"] > 0]
    total_lots = sum(r["entry_lots"] for r in rows)
    net = sum(r["net_usd"] for r in rows)
    return {
        "positions": n,
        "wins": len(positive),
        "native_net_usd": round(net, 2),
        "win_rate": round(len(positive) / n, 4) if n else None,
        "after_10usd_per_lot_extra_cost": round(net - 10 * total_lots, 2),
        "after_20usd_per_lot_extra_cost": round(net - 20 * total_lots, 2),
        "entry_lots": round(total_lots, 5),
        "sample_too_small_for_selection": n < 50,
    }


def evaluate(forensic: dict, manifest: dict, source_sha256: str, mt5=None) -> dict:
    start, end = validate_envelope(forensic, manifest)
    unique: set[tuple[int, str]] = set()
    quarantined: list[dict] = []
    rows = []
    for item in forensic["trades"]:
        try:
            validate_position(item, start, end, unique)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            # A single incomplete, partially closed or malformed broker
            # position must never crash the whole read-only report or be
            # silently dropped from its coverage denominator.
            quarantined.append({
                "style": item.get("style") if isinstance(item, dict) else None,
                "position_id": str(item.get("position_id", "UNKNOWN"))[:80]
                               if isinstance(item, dict) else "UNKNOWN",
                "status": str(item.get("status", "INVALID"))[:80]
                          if isinstance(item, dict) else "INVALID",
                "exit_reason": str(item.get("exit_reason", "UNKNOWN"))[:80]
                               if isinstance(item, dict) else "UNKNOWN",
                "problem": str(exc)[:200],
            })
            continue
        stamp = int(item["entry_time_msc"])
        dt = datetime.fromtimestamp(stamp / 1000, UTC)
        features = (market_at_entry(mt5, stamp) if mt5 is not None
                    else {"status": "UNKNOWN_MARKET_HISTORY",
                          "missing_reason": "Broker MT5 history not connected"})
        row = {
            "style": item["style"],
            "position_id": str(item["position_id"]),
            "entry_time_utc": dt.isoformat(),
            "entry_lots": float(item["entry_lots"]),
            "side": item["side"],
            "exit_reason": item["exit_reason"],
            "exit_status": item["status"],
            "exit_leg_count": len(item["exit_legs"]),
            "exit_category": (item["exit_reason"] if item["exit_reason"]
                              in ("DEAL_REASON_TP", "DEAL_REASON_SL")
                              else "BROKER_OTHER_OR_MIXED"),
            "net_usd": float(item["net_usd"]),
            "month_utc": dt.strftime("%Y-%m"),
            "utc_entry_hour": dt.hour,
            "market": features,
        }
        if features["status"] == "COMPLETE_CLOSED_BAR_AND_BID_ASK":
            row["h1_alignment"] = ("ALIGNED" if item["side"] == features["h1_bias"]
                                    else "COUNTER" if features["h1_bias"] != "NEUTRAL"
                                    else "NEUTRAL")
            row["spread_atr_band"] = ("ABOVE_20_PERCENT" if features["spread_to_atr"] > .2
                                       else "AT_OR_BELOW_20_PERCENT")
            row["atr_band"] = ("ABOVE_TRAILING_MEDIAN" if
                               features["m15_atr_ratio_to_trailing_median"] > 1
                               else "AT_OR_BELOW_TRAILING_MEDIAN")
        rows.append(row)
    cohorts: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        cohorts["style"][str(row["style"])].append(row)
        cohorts["month"][row["month_utc"] + ":style_" + str(row["style"])].append(row)
        cohorts["side"][str(row["style"]) + ":" + row["side"]].append(row)
        cohorts["exit_category"][str(row["style"]) + ":" +
                                 row["exit_category"]].append(row)
        if row["market"]["status"] == "COMPLETE_CLOSED_BAR_AND_BID_ASK":
            for dim in ("h1_alignment", "spread_atr_band", "atr_band"):
                cohorts[dim][str(row["style"]) + ":" + row[dim]].append(row)
            cohorts["utc_hour"][str(row["style"]) + ":" +
                                str(row["utc_entry_hour"])].append(row)
    complete = sum(r["market"]["status"] == "COMPLETE_CLOSED_BAR_AND_BID_ASK" for r in rows)
    unusual = sum(r["exit_category"] == "BROKER_OTHER_OR_MIXED" for r in rows)
    multi = sum(r["exit_status"] == "COMPLETE_MULTI_EXIT" for r in rows)
    total_source = len(forensic["trades"])
    output_status = ("FORENSIC_POSITION_GAPS_NO_GO"
                     if quarantined or forensic["status"] == "EVIDENCE_GAPS_NO_GO" else
                     "DESCRIPTIVE_ONLY_REVIEW_REQUIRED" if complete == len(rows)
                     else "MARKET_HISTORY_INCOMPLETE_NO_GO")
    return {
        "schema": SCHEMA,
        "status": output_status,
        "source_forensics_sha256": source_sha256,
        "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        "source_compiled_ex5_sha256": manifest.get("compiled_ex5_sha256"),
        "symbol": SYMBOL,
        "test_period": [manifest["from_date"], manifest["to_date"]],
        "complete_market_snapshots": complete,
        "total_positions": total_source,
        "validated_positions": len(rows),
        "quarantined_position_count": len(quarantined),
        "quarantined_positions": quarantined,
        "coverage_warning": ("NO-GO: some native positions are excluded from P/L cohorts; "
                             "never treat those cohorts as reconciled to the full MT5 report"
                             if quarantined else "All native positions structurally reconciled."),
        "complete_multi_exit_positions": multi,
        "other_or_mixed_exit_positions": unusual,
        "exit_cause_warning": "Mixed, manual, expert and stop-out exits remain separate; do not infer a stopped or TP trade from their net profit.",
        "cohorts": {dim: {key: _cohort(value) for key, value in sorted(groups.items())}
                    for dim, groups in sorted(cohorts.items())},
        "positions": rows,
        "research_filters_applied_to_trading": False,
        "data_snooping_warning": "All studied months already inspected; cohorts cannot validate a filter.",
        "cost_warning": "Native profit includes tester fill prices. Additional $10/$20 per lot is hypothetical; do not double-count native commission.",
        "source_warning": "Terminal historical Bid/Ask may differ from exact native Strategy Tester tick stream.",
        "can_autotune_or_promote": False,
        "connected_orders_authorized": False,
        "live": "LOCKED",
        "validated_edge": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--forensics", type=Path, required=True,
                   help="QTS_HOLDOUT_REVIEW.zip or matching QTS_TRADE_BY_TRADE.json")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mt5", action="store_true",
                   help="Use already authorized Windows WMMarkets terminal, READ ONLY")
    args = p.parse_args()
    forensic, manifest, source_hash = load_evidence(args.forensics)
    terminal = None
    if args.mt5:
        try:
            import MetaTrader5 as terminal
        except ImportError as exc:
            raise SystemExit("MetaTrader5 Python package unavailable; no data fabricated") from exc
        if not terminal.initialize():
            raise SystemExit("Cannot connect to WMMarkets terminal for historical quotes")
        account = terminal.account_info()
        symbol = terminal.symbol_info(SYMBOL)
        server = str(getattr(account, "server", "")).lower().replace(" ", "")
        demo_mode = getattr(terminal, "ACCOUNT_TRADE_MODE_DEMO", None)
        is_demo = (demo_mode is not None and account is not None
                   and getattr(account, "trade_mode", None) == demo_mode)
        if "wmmarkets" not in server or symbol is None or not is_demo:
            terminal.shutdown()
            raise SystemExit("WMMarkets DEMO broker/symbol identity unavailable; NO-GO")
    try:
        result = evaluate(forensic, manifest, source_hash, terminal)
    finally:
        if terminal is not None:
            terminal.shutdown()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"QTS CONTEXT {result['status']}: {result['complete_market_snapshots']}"
          f"/{result['total_positions']} complete; LIVE LOCKED")
    print(f"Report: {args.output}")
    return 0 if result["status"] == "DESCRIPTIVE_ONLY_REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
