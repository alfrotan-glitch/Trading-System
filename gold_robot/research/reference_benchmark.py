"""Strict, read-only QTS versus external-EA trade-ledger comparator.

This module does not submit orders or infer profitability from vendor claims.
The two inputs MUST describe the same broker, symbol, execution environment,
measurement period, cost convention and account currency. Meta-data claims are
provided by the operator and are not independently authenticated.

Run:
  python gold_robot/research/reference_benchmark.py \
      --candidate qts.json --reference external.json

Manifest v1 fields:
  source, broker, symbol, account_type (TESTER/DEMO/REAL),
  account_currency (USD), account_key (unique *pseudonym*; no login or secret),
  period_start, period_end (YYYY-MM-DD), initial_equity_usd (>0),
  cost_basis (EXECUTABLE_BID_ASK), market_data_sha256 (broker tick data),
  execution_model (REAL_TICKS/BROKER_LIVE/DEMO_LIVE), broker_server,
  contract_size, point_size, volume_step, leverage,
  ledger (CSV basename), ledger_sha256.

CSV fields:
  deal_id, position_id, exit_time_utc, side (BUY/SELL), gross_usd,
  commission_usd, slippage_usd, swap_usd, fee_usd.

gross_usd is broker P&L measured at ACTUAL executed entry and exit fills.
This already incorporates spread and execution slippage. Subtract only
commission, fee and swap charges (swap may be a credit). slippage_usd is
OPTIONAL measured diagnostic metadata, never subtracted a second time.
Empty slippage means UNKNOWN, not zero. Several close deals for one MT5
position are aggregated for position-level PF, but their dated P&L remains
on the actual exit dates. The tool cannot prove a position is fully closed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class Ledger:
    meta: dict
    trades: tuple[tuple[date, float], ...]
    gross_usd: float
    explicit_cost_usd: float
    position_pnl: tuple[float, ...]
    observed_slippage_usd: float
    unknown_slippage_deals: int


def _money(value: object, *, allow_negative: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid monetary value") from exc
    if not math.isfinite(parsed) or (parsed < 0 and not allow_negative):
        raise ValueError("non-finite or disallowed negative monetary value")
    return parsed


def _day(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("date must be YYYY-MM-DD")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return result


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("exit_time_utc must be a timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid exit_time_utc") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError("exit_time_utc must be explicitly in UTC")
    return dt.astimezone(timezone.utc)


def load_ledger(manifest_path: Path) -> Ledger:
    with manifest_path.open(encoding="utf-8") as stream:
        meta = json.load(stream)
    required = {
        "schema_version", "source", "broker", "symbol", "account_type",
        "account_currency", "account_key", "period_start", "period_end",
        "initial_equity_usd", "cost_basis", "market_data_sha256",
        "execution_model", "broker_server", "contract_size", "point_size",
        "volume_step", "leverage", "ledger", "ledger_sha256",
    }
    if not isinstance(meta, dict) or not required.issubset(meta):
        raise ValueError("incomplete benchmark manifest")
    if meta["schema_version"] != 1:
        raise ValueError("unsupported manifest schema")
    for key in ("source", "broker", "broker_server", "symbol", "account_key"):
        if not isinstance(meta[key], str) or not meta[key].strip():
            raise ValueError(f"missing {key}")
    if meta["account_type"] not in ("TESTER", "DEMO", "REAL"):
        raise ValueError("unknown account_type")
    if meta["account_currency"] != "USD":
        raise ValueError("USD reporting required; FX conversions are not modeled")
    if meta["cost_basis"] != "EXECUTABLE_BID_ASK":
        raise ValueError("gross must use executable Bid/Ask, not candle close")
    expected_model = {"TESTER": "REAL_TICKS", "DEMO": "DEMO_LIVE", "REAL": "BROKER_LIVE"}[meta["account_type"]]
    if meta["execution_model"] != expected_model:
        raise ValueError("inconsistent account type and execution model")
    market_hash = meta["market_data_sha256"]
    if not isinstance(market_hash, str) or len(market_hash) != 64 or any(c not in "0123456789abcdef" for c in market_hash):
        raise ValueError("market_data_sha256 must identify the exact tick archive")
    for param in ("contract_size", "point_size", "volume_step", "leverage"):
        meta[param] = _money(meta[param])
        if meta[param] <= 0:
            raise ValueError("invalid broker contract or leverage")
    first, last = _day(meta["period_start"]), _day(meta["period_end"])
    if first > last:
        raise ValueError("reversed benchmark period")
    if (last - first).days > 3652:
        raise ValueError("benchmark window exceeds 10 years")
    meta["initial_equity_usd"] = _money(meta["initial_equity_usd"])
    if meta["initial_equity_usd"] <= 0:
        raise ValueError("initial equity must be positive")
    # Only files alongside the manifest: fail closed on opaque remote paths.
    filename = meta["ledger"]
    if not isinstance(filename, str) or filename != Path(filename).name or not filename.endswith(".csv"):
        raise ValueError("ledger must be a local CSV basename")
    ledger_path = manifest_path.parent / filename
    digest = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    if digest != meta["ledger_sha256"]:
        raise ValueError("ledger checksum mismatch; data may have changed")
    required_fields = {
        "deal_id", "position_id", "exit_time_utc", "side", "gross_usd",
        "commission_usd", "slippage_usd", "swap_usd", "fee_usd",
    }
    values: list[tuple[date, float]] = []
    seen: set[str] = set()
    positions: dict[str, float] = {}
    prior_time: datetime | None = None
    gross_total = cost_total = observed_slippage = 0.0
    unknown_slippage_deals = 0
    with ledger_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not required_fields.issubset(reader.fieldnames or []):
            raise ValueError("ledger missing mandatory execution/cost fields")
        for row in reader:
            key = str(row["deal_id"]).strip()
            if not key or key in seen:
                raise ValueError("missing or duplicate deal identifier")
            seen.add(key)
            position_id = str(row["position_id"] or "").strip()
            if not position_id:
                raise ValueError("missing position identifier")
            if row["side"] not in ("BUY", "SELL"):
                raise ValueError("invalid trade direction")
            timestamp = _timestamp(row["exit_time_utc"])
            if prior_time is not None and timestamp < prior_time:
                raise ValueError("ledger not ordered by exit time")
            prior_time = timestamp
            when = timestamp.date()
            if when < first or when > last:
                raise ValueError("trade outside declared benchmark period")
            gross = _money(row["gross_usd"], allow_negative=True)
            commission = _money(row["commission_usd"])
            slip_raw = row["slippage_usd"]
            if slip_raw is None or str(slip_raw).strip() == "":
                unknown_slippage_deals += 1
            else:
                # Adverse (+) or favorable (-) slippage is ALREADY in fill P&L.
                observed_slippage += _money(slip_raw, allow_negative=True)
            swap = _money(row["swap_usd"], allow_negative=True)
            fee = _money(row["fee_usd"])
            costs = commission + swap + fee
            net = gross - costs
            values.append((when, net))
            positions[position_id] = positions.get(position_id, 0.0) + net
            gross_total += gross
            cost_total += costs
    return Ledger(meta, tuple(values), gross_total, cost_total,
                  tuple(positions.values()), observed_slippage,
                  unknown_slippage_deals)


def _arm(ledger: Ledger) -> dict:
    net = [value for _, value in ledger.trades]
    position_net = ledger.position_pnl
    wins = sum(x for x in position_net if x > 0)
    losses = -sum(x for x in position_net if x < 0)
    balance = peak = drawdown = 0.0
    for value in net:
        balance += value
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    start = ledger.meta["initial_equity_usd"]
    return {
        "trades": len(position_net),  # distinct position IDs, NOT deal rows
        "closing_deals": len(net),
        "net_usd": round(sum(net), 6),
        "net_pct_starting_equity": round(100 * sum(net) / start, 6),
        "net_expectancy_usd_per_trade": round(sum(net) / len(position_net), 6) if position_net else None,
        "profit_factor": wins / losses if losses else None,
        "max_realized_deal_drawdown_pct_starting_equity": 100 * drawdown / start,
        "gross_usd": round(ledger.gross_usd, 6),
        "explicit_cost_usd": round(ledger.explicit_cost_usd, 6),
        "diagnostic_slippage_usd_included_in_gross": round(ledger.observed_slippage_usd, 6),
        "unmeasured_slippage_deals": ledger.unknown_slippage_deals,
    }


def compare(candidate: Ledger, reference: Ledger, *, seed: int = 6241024) -> dict:
    important = (
        "broker", "symbol", "account_type", "account_currency",
        "period_start", "period_end", "cost_basis", "execution_model",
        "market_data_sha256", "broker_server", "contract_size",
        "point_size", "volume_step", "leverage", "initial_equity_usd",
    )
    differences = [k for k in important if candidate.meta[k] != reference.meta[k]]
    if differences:
        raise ValueError("incomparable account or evaluation conditions: " + ", ".join(differences))
    if candidate.meta["account_key"] == reference.meta["account_key"]:
        raise ValueError("same underlying account; two websites are not independent evidence")
    first, last = _day(candidate.meta["period_start"]), _day(candidate.meta["period_end"])
    dates = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    # Compare normalized daily realised P&L; no-trade days MUST be included.
    def daily(ledger: Ledger) -> dict[date, float]:
        result = dict.fromkeys(dates, 0.0)
        for day, net in ledger.trades:
            result[day] += net / ledger.meta["initial_equity_usd"]
        return result
    c_daily, r_daily = daily(candidate), daily(reference)
    deltas = [c_daily[d] - r_daily[d] for d in dates]
    mean = sum(deltas) / len(deltas)
    rng = random.Random(seed)
    # Preserve week-length serial clusters. Very short histories are NOT
    # assigned a comforting numerical confidence interval.
    boots: list[float] = []
    if len(deltas) >= 28:
        width = 7
        for _ in range(2000):
            sample: list[float] = []
            while len(sample) < len(deltas):
                start_index = rng.randrange(len(deltas))
                sample.extend(deltas[(start_index + step) % len(deltas)]
                              for step in range(width))
            boots.append(sum(sample[:len(deltas)]) / len(deltas))
        boots.sort()
    return {
        "status": "RESEARCH_COMPARISON_ONLY_NOT_VALIDATED",
        "broker": candidate.meta["broker"],
        "symbol": candidate.meta["symbol"],
        "account_type": candidate.meta["account_type"],
        "period_start": first.isoformat(),
        "period_end": last.isoformat(),
        "calendar_days_including_no_trades": len(dates),
        "candidate": _arm(candidate),
        "reference": _arm(reference),
        "paired_daily_mean_difference_pct_starting_equity": 100 * mean,
        "paired_week_block_bootstrap_99pct_lower_difference_pct": 100 * boots[19] if boots else None,
        "notes": [
            "Signed metadata and SHA-256 check file integrity, NOT authenticity of vendor results.",
            "7-calendar-day circular block bootstrap; interval omitted for fewer than 28 days. No formal statistical edge claim.",
            "Actual-fill gross already includes spread/slippage. Only broker charges are deducted; reported slippage is diagnostic.",
            "MT5 position_id groups partial closing deals; a closed deal ledger does not prove no positions remain open.",
            "Matched dates and broker do not guarantee identical fill models or strategy exposure.",
            "Positive comparisons never grant DEMO or LIVE execution authority.",
            "Confirm on an untouched future broker-tick sample with measured costs and native MT5 receipts.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only matched live-EA reference study")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(load_ledger(args.candidate), load_ledger(args.reference))
    rendered = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
