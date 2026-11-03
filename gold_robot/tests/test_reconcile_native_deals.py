"""Offline adversarial tests for independent QTS MT5 deal reconciliation."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from reconcile_native_deals import AuditError, read_csv, reconstruct, reconcile

HEADERS = ["position_id", "deal_id", "order_id", "entry", "reason", "type",
           "time_msc", "volume", "price", "sl", "tp", "gross", "commission", "swap", "fee", "setup_reason"]


def deal(*, pid="100", did="1001", oid="2001", entry="DEAL_ENTRY_IN", side="DEAL_TYPE_BUY",
         time="1000000000000", lots="0.03", price="3000", sl="2995", tp="3005",
         gross="0", commission="-0.15", swap="0", fee="0", reason="DEAL_REASON_EXPERT",
         setup_reason="QTS-DUAL-M2-S1"):
    return dict(position_id=pid, deal_id=did, order_id=oid, entry=entry, reason=reason,
                type=side, time_msc=time, volume=lots, price=price, sl=sl, tp=tp,
                gross=gross, commission=commission, swap=swap, fee=fee,
                setup_reason=setup_reason)


def base_deals():
    entry = deal()
    exit_ = deal(did="1002", oid="2002", entry="DEAL_ENTRY_OUT", side="DEAL_TYPE_SELL",
                 time="1000000060000", price="3005", gross="15", reason="DEAL_REASON_TP")
    return [entry, exit_]



def native_deal_html(record):
    stamp = datetime.fromtimestamp(int(record["time_msc"]) / 1000, timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
    fields = [stamp, record["deal_id"], "XAUUSD@",
              record["type"].removeprefix("DEAL_TYPE_").lower(),
              "in" if record["entry"] == "DEAL_ENTRY_IN" else "out",
              record["volume"], record["price"], record["order_id"], record["commission"],
              record["swap"], record["gross"], "3000.00", record["setup_reason"]]
    return "<tr bgcolor='#FFFFFF'>" + "".join("<td>" + str(x) + "</td>" for x in fields) + "</tr>"


def write_run(folder, deals=None, *, forensics=None, report_net="14.70", report_count=1, pf="1.10"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "native").mkdir(exist_ok=True)
    deals = base_deals() if deals is None else deals
    with (folder / "native" / "QTS_7_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS, delimiter=";")
        w.writeheader()
        w.writerows(deals)
    (folder / "native" / "QTS_7.htm").write_text(
        '<html><td>Total Net Profit:</td><td>' + str(report_net) + '</td>'
        '<td>Total Trades:</td><td>' + str(report_count) + '</td>'
        '<td>Profit Factor:</td><td>' + pf + '</td>'
        '<div><b>Deals</b></div>' + ''.join(native_deal_html(d) for d in deals) +
        '</html>', encoding="utf-16")
    (folder / "OPEN_RESULTS.json").write_text(json.dumps({
        "research_variant": "DUAL_DIRECTIONAL", "selected_styles": [7],
        "symbol": "XAUUSD@", "timeframe": "M15", "model": 4, "deposit_usd": 3000,
        "live": "LOCKED", "validated_edge": False, "real_money_orders": False,
        "from_date": "2025.01.01", "to_date": "2026.11.03"}), encoding="utf-8")
    t = dict(position_id="100", status="COMPLETE", setup_reason="QTS-DUAL-M2-S1",
             side="BUY", exit_reason="DEAL_REASON_TP", entry_time_msc="1000000000000",
             exit_time_msc="1000000060000", deal_count=2, net_usd=14.7, gross_usd=15,
             charges_usd=-0.3, entry_lots=.03, exit_lots=.03, entry_price=3000,
             exit_price=3005, initial_sl=2995)
    if forensics is not None:
        t.update(forensics)
    (folder / "QTS_TRADE_BY_TRADE.json").write_text(json.dumps({
        "live": "LOCKED", "edge_validated": False, "selected_styles": [7], "trades": [t]}), encoding="utf-8")
    return folder


def test_closed_deal_reconstructs_and_counts_entry_charges(tmp_path):
    folder = write_run(tmp_path)
    # Winning-only trade cannot have a finite native PF.
    with pytest.raises(AuditError, match="Profit Factor"):
        reconcile(folder)
    pos = reconstruct("100", read_csv(folder/"native"/"QTS_7_trades.csv")["100"], None)
    assert pos["net_usd"] == Decimal("14.70")
    assert pos["charges_usd"] == Decimal("-0.30")
    assert pos["r_multiple_indicative"] is None
    assert pos["r_limitation"] == "CONTRACT_SIZE_NOT_ATTESTED_R_UNAVAILABLE"


def test_complete_2_position_native_report_reconciliation(tmp_path):
    deals = base_deals()
    deals += [deal(pid="101", did="1011", oid="2011", time="1000000100000", side="DEAL_TYPE_SELL",
                   sl="3005", tp="2995", reason="DEAL_REASON_EXPERT", setup_reason="QTS-DUAL-M2-S3"),
              deal(pid="101", did="1012", oid="2012", entry="DEAL_ENTRY_OUT",
                   side="DEAL_TYPE_BUY", time="1000000160000", price="3004", sl="3005", tp="2995",
                   gross="-12", reason="DEAL_REASON_SL", setup_reason="QTS-DUAL-M2-S3")]
    folder = write_run(tmp_path, deals=deals, report_net="2.40", report_count=2, pf="1.20")
    data = json.loads((folder/"QTS_TRADE_BY_TRADE.json").read_text())
    data["trades"].append(dict(position_id="101", status="COMPLETE", side="SELL",
        setup_reason="QTS-DUAL-M2-S3", exit_reason="DEAL_REASON_SL",
        entry_time_msc="1000000100000", exit_time_msc="1000000160000",
        entry_price=3000, exit_price=3004, initial_sl=3005, entry_lots=.03, exit_lots=.03,
        gross_usd=-12, charges_usd=-.3, net_usd=-12.3, deal_count=2))
    (folder/"QTS_TRADE_BY_TRADE.json").write_text(json.dumps(data))
    report, positions = reconcile(folder, expect_positions=2, expect_net=Decimal("2.40"))
    assert report["status"] == "RECONCILED_RESEARCH_ONLY"
    assert report["positions"] == 2
    assert report["native_recorded_net_usd"] == "2.40"
    assert report["no_extra_costs_added_to_native_net"]
    assert all("native/" in k or k.endswith(".json") for k in report["files_sha256"])


@pytest.mark.parametrize("change,why", [
    ({"net_usd": 15}, "net_usd"),
    ({"entry_price": 3001}, "entry_price"),
    ({"charges_usd": 0}, "charges_usd"),
    ({"side": "SELL"}, "side"),
    ({"deal_count": 3}, "deal_count"),
    ({"setup_reason": "RETEST"}, "setup_reason"),
])
def test_detects_tampered_forensic_position(tmp_path, change, why):
    folder = write_run(tmp_path, forensics=change)
    with pytest.raises(AuditError, match=why):
        reconcile(folder)


def test_duplicate_native_deal_rejected(tmp_path):
    folder = write_run(tmp_path, deals=base_deals() * 2)
    with pytest.raises(AuditError, match="Duplicate broker deal ID"):
        reconcile(folder)


def test_reversal_rejected(tmp_path):
    deals = base_deals()
    deals[1]["entry"] = "DEAL_ENTRY_INOUT"
    folder = write_run(tmp_path, deals=deals)
    with pytest.raises(AuditError, match="Unsupported netting reversal"):
        reconcile(folder)


def test_reused_position_id_after_close_rejected(tmp_path):
    deals = base_deals()
    deals += [deal(did="1003", oid="2003", time="1000000100000")]
    folder = write_run(tmp_path, deals=deals)
    with pytest.raises(AuditError, match="new entry after an exit"):
        reconcile(folder)


def test_wrong_exit_side_rejected(tmp_path):
    deals = base_deals()
    deals[1]["type"] = "DEAL_TYPE_BUY"
    folder = write_run(tmp_path, deals=deals)
    with pytest.raises(AuditError, match="wrong exit direction"):
        reconcile(folder)


def test_missing_native_report_rejected(tmp_path):
    folder = write_run(tmp_path)
    (folder/"native"/"QTS_7.htm").unlink()
    with pytest.raises(AuditError, match="Required original evidence missing"):
        reconcile(folder)


def test_raw_report_net_mismatch_rejected(tmp_path):
    folder = write_run(tmp_path, report_net="999")
    with pytest.raises(AuditError, match="does not reconcile"):
        reconcile(folder)


def test_missing_native_deals_rejected(tmp_path):
    folder = write_run(tmp_path, deals=[])
    with pytest.raises(AuditError, match="No native broker deals"):
        reconcile(folder)


def test_invalid_contract_size_rejected(tmp_path):
    folder = write_run(tmp_path)
    with pytest.raises(AuditError, match="Contract size"):
        reconcile(folder, contract_size=Decimal("-1"))


def test_directional_style_mapping_rejected(tmp_path):
    deals = base_deals()
    deals[0]["setup_reason"] = "QTS-DUAL-M2-S3"  # Sweep BUY forbidden in Mode 2
    folder = write_run(tmp_path, deals=deals)
    with pytest.raises(AuditError, match="dual directional setup/side"):
        reconcile(folder)


def test_run_window_mismatch_rejected(tmp_path):
    folder = write_run(tmp_path)
    with pytest.raises(AuditError, match="exclusive end date"):
        reconcile(folder, expect_to="2026.11.04")


def test_native_mt5_deal_price_tamper_rejected(tmp_path):
    folder = write_run(tmp_path)
    report = folder / "native" / "QTS_7.htm"
    source = report.read_text(encoding="utf-16")
    assert "<td>3005</td>" in source
    report.write_text(source.replace("<td>3005</td>", "<td>3004</td>", 1), encoding="utf-16")
    with pytest.raises(AuditError, match="Native MT5 deal row"):
        reconcile(folder)


def test_missing_native_mt5_deal_row_rejected(tmp_path):
    folder = write_run(tmp_path)
    report = folder / "native" / "QTS_7.htm"
    source = report.read_text(encoding="utf-16")
    source = source.replace(native_deal_html(base_deals()[1]), "", 1)
    report.write_text(source, encoding="utf-16")
    with pytest.raises(AuditError, match="deal ID set"):
        reconcile(folder)
