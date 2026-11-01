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
            _required(len(archive.infolist()) < 100, "Oversized research archive")
            _required(sum(x.filename == "QTS_TRADE_BY_TRADE.json"
                          for x in archive.infolist()) == 1, "Forensics missing/duplicated")
            _required(sum(x.filename == "OPEN_RESULTS.json"
                          for x in archive.infolist()) == 1, "Run manifest missing/duplicated")
            raw = archive.read("QTS_TRADE_BY_TRADE.json")
            manifest = _json_bytes(archive.read("OPEN_RESULTS.json"))
    else:
        _required(path.name == "QTS_TRADE_BY_TRADE.json",
                  "Select QTS_HOLDOUT_REVIEW.zip or QTS_TRADE_BY_TRADE.json")
        raw = path.read_bytes()
        manifest = _json_bytes((path.parent / "OPEN_RESULTS.json").read_bytes())
    forensic = _json_bytes(raw)
    validate_evidence(forensic, manifest)
    return forensic, manifest, hashlib.sha256(raw).hexdigest()


def validate_evidence(forensic: dict, manifest: dict) -> None:
    _required(forensic.get("schema") == "qts.mt5.trade_forensics.v1"
              and forensic.get("status") == "SELECTED_IMPORTED_FOR_REVIEW",
              "Unrecognized/incomplete native deal ledger")
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
    unique = set()
    for row in forensic["trades"]:
        _required(isinstance(row, dict)
                  and row.get("style") in STYLES
                  and row.get("status") == "COMPLETE"
                  and row.get("side") in ("BUY", "SELL")
                  and row.get("exit_reason") in ("DEAL_REASON_SL", "DEAL_REASON_TP"),
                  "Unknown, partial, or mixed-exit broker position")
        key = (row["style"], str(row.get("position_id")))
        _required(key not in unique, "Duplicate native broker position")
        unique.add(key)
        first = int(row["entry_time_msc"])
        last = int(row["exit_time_msc"])
        _required(start.timestamp() * 1000 <= first < end.timestamp() * 1000
                  and first < last, "Native position outside manifest window")
        lots = float(row["entry_lots"])
        exit_lots = float(row["exit_lots"])
        net = float(row["net_usd"])
        gross = float(row["gross_usd"])
        charges = float(row["charges_usd"])
        _required(all(math.isfinite(v) for v in (lots, exit_lots, net, gross, charges))
                  and lots > 0 and abs(lots - exit_lots) < 0.000001
                  and abs(net - gross - charges) < 0.05,
                  "Unreconciled native broker position")


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
    validate_evidence(forensic, manifest)
    rows = []
    for item in forensic["trades"]:
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
        if row["market"]["status"] == "COMPLETE_CLOSED_BAR_AND_BID_ASK":
            for dim in ("h1_alignment", "spread_atr_band", "atr_band"):
                cohorts[dim][str(row["style"]) + ":" + row[dim]].append(row)
            cohorts["utc_hour"][str(row["style"]) + ":" +
                                str(row["utc_entry_hour"])].append(row)
    complete = sum(r["market"]["status"] == "COMPLETE_CLOSED_BAR_AND_BID_ASK" for r in rows)
    return {
        "schema": SCHEMA,
        "status": ("DESCRIPTIVE_ONLY_REVIEW_REQUIRED" if complete == len(rows)
                   else "MARKET_HISTORY_INCOMPLETE_NO_GO"),
        "source_forensics_sha256": source_sha256,
        "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        "source_compiled_ex5_sha256": manifest.get("compiled_ex5_sha256"),
        "symbol": SYMBOL,
        "test_period": [manifest["from_date"], manifest["to_date"]],
        "complete_market_snapshots": complete,
        "total_positions": len(rows),
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
    return 0 if result["complete_market_snapshots"] == result["total_positions"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
