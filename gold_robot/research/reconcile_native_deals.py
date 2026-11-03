"""Independently reconcile QTS Style 7 MT5 deal CSV, position JSON and tester report.

Offline/read-only. No broker access, trade authorization, assumed costs or optimization.
Fails closed on incomplete deal lifecycles; does not infer hypothetical executions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

CENT = Decimal("0.01")
TOL = Decimal("0.000001")
FIELDS = {"position_id", "deal_id", "order_id", "entry", "reason", "type",
          "time_msc", "volume", "price", "sl", "tp", "gross", "commission", "swap", "fee"}
IN = "DEAL_ENTRY_IN"
OUT = {"DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY"}


class AuditError(ValueError):
    pass


def num(value: object) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AuditError("Invalid numeric deal field") from exc
    if not d.is_finite():
        raise AuditError("Nonfinite numeric deal field")
    return d


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise AuditError("Missing or duplicate deal CSV headers")
        if not FIELDS.issubset(reader.fieldnames):
            raise AuditError("Missing deal CSV columns: " + ",".join(sorted(FIELDS - set(reader.fieldnames))))
        for index, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise AuditError(f"Malformed deal CSV row {index}")
            pid, did, oid = (row[key].strip() for key in ("position_id", "deal_id", "order_id"))
            if not (pid.isdigit() and did.isdigit() and oid.isdigit()) or "0" in (pid, did, oid):
                raise AuditError(f"Missing/invalid native identifiers at row {index}")
            if did in seen:
                raise AuditError(f"Duplicate broker deal ID {did}")
            seen.add(did)
            if row["entry"] not in ({IN} | OUT):
                raise AuditError(f"Unsupported netting reversal/entry type in deal {did}")
            if row["type"] not in {"DEAL_TYPE_BUY", "DEAL_TYPE_SELL"}:
                raise AuditError(f"Unsupported deal side in deal {did}")
            try:
                time_ms = int(row["time_msc"])
            except ValueError as exc:
                raise AuditError(f"Invalid millisecond timestamp in deal {did}") from exc
            if time_ms <= 0:
                raise AuditError(f"Invalid millisecond timestamp in deal {did}")
            for field in ("volume", "price", "sl", "tp", "gross", "commission", "swap", "fee"):
                row[field] = num(row[field])
            if row["volume"] <= 0 or row["price"] <= 0:
                raise AuditError(f"Invalid lot size or price in deal {did}")
            row["_time_ms"] = time_ms
            groups[pid].append(row)
    if not groups:
        raise AuditError("No native broker deals; cannot claim zero-trade completeness")
    return groups


def reconstruct(pid: str, deals: list[dict], contract_size: Decimal | None) -> dict:
    deals = sorted(deals, key=lambda d: (d["_time_ms"], int(d["deal_id"])))
    opened = Decimal(0)
    in_value = out_value = in_lots = out_lots = Decimal(0)
    gross = charges = Decimal(0)
    first = last = None
    first_exit = False
    exit_reasons = set()
    for d in deals:
        is_entry = d["entry"] == IN
        if is_entry:
            if first_exit:
                raise AuditError(f"Position {pid}: new entry after an exit; lifecycle ambiguous")
            if first is None:
                first = d
            elif d["type"] != first["type"]:
                raise AuditError(f"Position {pid}: conflicting entry sides")
            opened += d["volume"]
            in_lots += d["volume"]
            in_value += d["price"] * d["volume"]
        else:
            first_exit = True
            last = d
            if first is None or d["type"] == first["type"]:
                raise AuditError(f"Position {pid}: exit before entry or wrong exit direction")
            opened -= d["volume"]
            if opened < -TOL:
                raise AuditError(f"Position {pid}: exit volume exceeds open volume")
            out_lots += d["volume"]
            out_value += d["price"] * d["volume"]
            exit_reasons.add(d["reason"])
        gross += d["gross"]
        charges += d["commission"] + d["swap"] + d["fee"]
    if first is None or last is None or abs(opened) > TOL or abs(in_lots-out_lots) > TOL:
        raise AuditError(f"Position {pid}: missing exit or unclosed/partially reconciled volume")
    side = "BUY" if first["type"] == "DEAL_TYPE_BUY" else "SELL"
    setup = first.get("setup_reason", "").strip()
    if (setup, side) not in {("QTS-DUAL-M2-S1", "BUY"), ("QTS-DUAL-M2-S3", "SELL")}:
        raise AuditError(f"Position {pid}: invalid dual directional setup/side attribution")
    entry_price, exit_price = in_value/in_lots, out_value/out_lots
    stop = first["sl"]
    risk = None
    risk_issue = None
    if stop <= 0 or (side == "BUY" and stop >= entry_price) or (side == "SELL" and stop <= entry_price):
        risk_issue = "MISSING_OR_WRONG_SIDE_INITIAL_STOP"
    elif contract_size is None:
        risk_issue = "CONTRACT_SIZE_NOT_ATTESTED_R_UNAVAILABLE"
    elif any(d["sl"] != stop for d in deals if d["entry"] == IN):
        risk_issue = "MULTIPLE_INITIAL_STOPS_R_UNAVAILABLE"
    else:
        risk_usd = abs(entry_price-stop) * in_lots * contract_size
        risk = str((gross + charges)/risk_usd) if risk_usd > 0 else None
    reason = next(iter(exit_reasons)) if len(exit_reasons) == 1 else "MIXED_EXIT_REASONS"
    return {"position_id": pid, "status": "COMPLETE_MULTI_EXIT" if sum(d["entry"] in OUT for d in deals) > 1 else "COMPLETE",
            "setup_reason": setup,
            "side": side, "entry_time_msc": str(first["time_msc"]), "exit_time_msc": str(last["time_msc"]),
            "entry_price": entry_price, "exit_price": exit_price, "initial_sl": stop,
            "entry_lots": in_lots, "exit_lots": out_lots, "deal_count": len(deals),
            "gross_usd": gross, "charges_usd": charges, "net_usd": gross + charges,
            "exit_reason": reason, "r_multiple_indicative": risk, "r_limitation": risk_issue}



def verify_native_deal_table(document: str, groups: dict[str, list[dict]]) -> int:
    """Validate each native MT5 HTML deal against broker-exported CSV fields.

    Summary-only matching can conceal offsetting per-deal corruption.
    The MT5 HTML does not expose DEAL_FEE, which is counted only from CSV.
    """
    from parse_native_report import cells

    section = document.split(">Deals</b>", 1)
    if len(section) != 2:
        raise AuditError("Native MT5 deals table missing")
    reported = {}
    for row in re.findall(r"<tr\b[^>]*>.*?</tr>", section[1], re.I | re.S):
        fields = cells(row)
        if len(fields) != 13 or fields[3].lower() not in ("buy", "sell"):
            continue
        if fields[1] in reported:
            raise AuditError("Duplicate native MT5 deal ID")
        reported[fields[1]] = fields
    raw = {d["deal_id"]: d for records in groups.values() for d in records}
    if set(reported) != set(raw) or len(reported) != sum(len(x) for x in groups.values()):
        raise AuditError("Native MT5 deal ID set does not match original broker CSV")
    for ticket, d in raw.items():
        row = reported[ticket]
        direction = "in" if d["entry"] == IN else "out"
        side = d["type"].removeprefix("DEAL_TYPE_").lower()
        stamp = datetime.fromtimestamp(int(d["time_msc"]) / 1000, timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
        match = (
            row[0] == stamp and row[2] == "XAUUSD@" and
            row[3].lower() == side and row[4].lower() == direction and
            row[7] == d["order_id"] and
            abs(num(row[5]) - d["volume"]) < Decimal("0.000001") and
            abs(num(row[6]) - d["price"]) < Decimal("0.00001") and
            abs(num(row[8]) - d["commission"]) <= CENT and
            abs(num(row[9]) - d["swap"]) <= CENT and
            abs(num(row[10]) - d["gross"]) <= CENT
        )
        if not match:
            raise AuditError("Native MT5 deal row does not match broker CSV ticket " + ticket)
    return len(reported)


def reconcile(run: Path, *, contract_size: Decimal | None = None,
              expect_positions: int | None = None, expect_net: Decimal | None = None,
              expect_from: str | None = None, expect_to: str | None = None) -> tuple[dict, list[dict]]:
    native = run / "native" / "QTS_7_trades.csv"
    positions_json = run / "QTS_TRADE_BY_TRADE.json"
    metadata_json = run / "OPEN_RESULTS.json"
    native_report = run / "native" / "QTS_7.htm"
    for path in (native, positions_json, metadata_json, native_report):
        if not path.is_file():
            raise AuditError(f"Required original evidence missing: {path.name}")
    meta = json.loads(metadata_json.read_text(encoding="utf-8-sig"))
    forensic = json.loads(positions_json.read_text(encoding="utf-8-sig"))
    if (meta.get("research_variant") != "DUAL_DIRECTIONAL" or meta.get("selected_styles") != [7]
        or meta.get("symbol") != "XAUUSD@" or meta.get("timeframe") != "M15"
        or meta.get("model") != 4 or num(meta.get("deposit_usd")) != 3000
        or meta.get("live") != "LOCKED" or meta.get("validated_edge") is not False
        or meta.get("real_money_orders") is not False
        or forensic.get("live") != "LOCKED" or forensic.get("edge_validated") is not False
        or forensic.get("selected_styles") != [7]):
        raise AuditError("Source identity or safety lock mismatch")
    if expect_from is not None and meta.get("from_date") != expect_from:
        raise AuditError("Run start date disagrees with expected period")
    if expect_to is not None and meta.get("to_date") != expect_to:
        raise AuditError("Run exclusive end date disagrees with expected period")
    if contract_size is not None and contract_size <= 0:
        raise AuditError("Contract size must be strictly positive")
    groups = read_csv(native)
    positions = [reconstruct(pid, records, contract_size) for pid, records in groups.items()]
    exported = forensic.get("trades")
    if not isinstance(exported, list) or len(exported) != len(positions):
        raise AuditError("Position count differs between native CSV and forensic JSON")
    indexed = {str(row.get("position_id")): row for row in exported}
    if len(indexed) != len(exported) or set(indexed) != set(groups):
        raise AuditError("Duplicate, missing or extra positions in forensic JSON")
    for item in positions:
        ref = indexed[item["position_id"]]
        for key in ("status", "side", "setup_reason", "exit_reason", "entry_time_msc", "exit_time_msc", "deal_count"):
            if str(ref.get(key)) != str(item[key]):
                raise AuditError(f"Position {item['position_id']}: {key} differs from original deals")
        for key in ("net_usd", "gross_usd", "charges_usd"):
            if money(num(ref.get(key))) != money(item[key]):
                raise AuditError(f"Position {item['position_id']}: {key} does not reconcile")
        for key, tolerance in (("entry_lots", TOL), ("exit_lots", TOL),
                               ("entry_price", Decimal("0.00001")), ("exit_price", Decimal("0.00001")),
                               ("initial_sl", Decimal("0.000001"))):
            if abs(num(ref.get(key)) - item[key]) > tolerance:
                raise AuditError(f"Position {item['position_id']}: {key} does not reconcile")
    # Use native totals as recorded; do not double-count hypothetical commissions.
    from parse_native_report import number, value
    document = native_report.read_text(encoding="utf-16")
    native_deal_rows_verified = verify_native_deal_table(document, groups)
    tester_net = num(number(value(document, "Total Net Profit:")))
    tester_trades = int(number(value(document, "Total Trades:")))
    tester_pf = num(number(value(document, "Profit Factor:")))
    total = sum((p["net_usd"] for p in positions), Decimal(0))
    winners = sum(p["net_usd"] > 0 for p in positions)
    losers = sum(p["net_usd"] < 0 for p in positions)
    gp = sum((p["net_usd"] for p in positions if p["net_usd"] > 0), Decimal(0))
    gl = -sum((p["net_usd"] for p in positions if p["net_usd"] < 0), Decimal(0))
    pf = gp/gl if gl > 0 else None
    if tester_trades != len(positions) or abs(tester_net-total) > CENT:
        raise AuditError("Native MT5 report total/count does not reconcile with raw broker deals")
    if pf is None or abs(tester_pf-pf) > Decimal("0.02"):
        raise AuditError("Native MT5 report Profit Factor does not reconcile with positions")
    if expect_positions is not None and expect_positions != len(positions):
        raise AuditError("Expected position count differs from independent reconstruction")
    if expect_net is not None and abs(money(total)-expect_net) > CENT:
        raise AuditError("Expected published net differs from independent reconstruction")
    report = {
        "schema": "qts.mt5.independent_deal_reconciliation.v1", "status": "RECONCILED_RESEARCH_ONLY",
        "live": "LOCKED", "edge_validated": False, "trade_permission": False,
        "independent_broker_fee_verification": False, "spread_already_reflected_in_mt5_fills": True,
        "no_extra_costs_added_to_native_net": True,
        "contract_size_supplied_but_not_independently_verified": contract_size is not None,
        "verified_native_deal_rows": native_deal_rows_verified,
        "positions": len(positions), "winners": winners, "losers": losers,
        "native_recorded_net_usd": str(money(total)), "tester_net_usd": str(money(tester_net)),
        "native_profit_factor_positions": str(pf), "tester_profit_factor": str(tester_pf),
        "raw_recorded_charges_usd": str(money(sum((p["charges_usd"] for p in positions), Decimal(0)))),
        "files_sha256": {path.relative_to(run).as_posix(): sha256(path)
                         for path in (native, positions_json, metadata_json, native_report)},
        "limitations": ["Native tester historical trades are not independent out-of-sample evidence",
                        "Zero recorded commissions do not verify WMMarkets charges",
                        "Stop execution slippage and post-stop price paths need broker ticks/journal",
                        "R multiples require independently attested symbol contract and tick valuation"],
    }
    return report, positions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Local native run folder with original MT5 evidence")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-positions", type=int)
    parser.add_argument("--expect-net", type=Decimal)
    parser.add_argument("--expect-from")
    parser.add_argument("--expect-to")
    parser.add_argument("--contract-size", type=Decimal, help="Optional indicative only; not broker verified")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "QTS_NATIVE_RECONCILIATION.json"
    ledger_path = args.output / "QTS_INDEPENDENT_POSITION_LEDGER.csv"
    # A failed rerun must never leave a stale successful ledger behind.
    ledger_path.unlink(missing_ok=True)
    try:
        report, positions = reconcile(args.run, contract_size=args.contract_size,
                                      expect_positions=args.expect_positions, expect_net=args.expect_net,
                                      expect_from=args.expect_from, expect_to=args.expect_to)
        fields = ("position_id", "setup_reason", "side", "status", "entry_time_msc", "exit_time_msc",
                  "entry_price", "exit_price", "initial_sl", "entry_lots", "exit_lots",
                  "gross_usd", "charges_usd", "net_usd", "exit_reason", "r_multiple_indicative", "r_limitation")
        with ledger_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in positions:
                writer.writerow({key: str(row[key]) if row[key] is not None else "" for key in fields})
        code = 0
    except (AuditError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
        report = {"schema": "qts.mt5.independent_deal_reconciliation.v1",
                  "status": "RECONCILIATION_FAILED_NO_GO", "live": "LOCKED",
                  "edge_validated": False, "trade_permission": False, "blocker": str(exc)}
        code = 2
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report_path)
    print(report["status"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
