"""Capital readiness can evaluate native evidence but cannot unlock real orders."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from capital_readiness import InvalidEvidence, audit, load_native, discover_pairs

FIRST = date(2026, 11, 1)
SOURCE = "a" * 64


def month_after(a: date) -> date:
    return date(a.year + (a.month == 12), (a.month % 12) + 1, 1)


def fixture(root: Path, variant: str, start: date, *,
            profit: float = 7.0, count: int = 1, source: str = SOURCE) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    native = root / "native"
    native.mkdir(exist_ok=True)
    end = month_after(start)
    (root / "OPEN_RESULTS.json").write_text(json.dumps({
        "schema": "qts.mt5.auto_tester.v1",
        "state": "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
        "live": "LOCKED", "validated_edge": False,
        "real_money_orders": False,
        "targeted": True, "selected_styles": [7],
        "research_variant": variant, "symbol": "XAUUSD@",
        "model": 4, "timeframe": "M15", "deposit_usd": 3000,
        "from_date": start.strftime("%Y.%m.%d"),
        "to_date": end.strftime("%Y.%m.%d"),
        "source_manifest_sha256": source,
    }), encoding="utf-8")
    rows = ["position_id;deal_id;entry;type;time_msc;volume;price;sl;tp;reason;gross;commission;swap;fee"]
    timestamp = int(datetime(start.year, start.month, 5, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    for i in range(count):
        clock = timestamp + i * 1000 * 60
        pid = f"{variant}-{start.year}{start.month:02}-{i}"
        rows.extend((
            f"{pid};{pid}-in;DEAL_ENTRY_IN;DEAL_TYPE_BUY;{clock};0.01;4000;3990;4020;DEAL_REASON_EXPERT;0;0;0;0",
            f"{pid};{pid}-out;DEAL_ENTRY_OUT;DEAL_TYPE_SELL;{clock+30000};0.01;4001;3990;4020;DEAL_REASON_TP;{profit};0;0;0",
        ))
    (native / "QTS_7_trades.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    net = count * profit
    original = (
        "<!doctype html><html><body>EntryStyle=7"
        "<table><tr><td>Total Net Profit</td><td>" + str(net) + "</td></tr>"
        "<tr><td>Profit Factor</td><td>1.2</td></tr>"
        "<tr><td>Total Trades</td><td>" + str(count) + "</td></tr>"
        "<tr><td>Equity Drawdown Maximal</td><td>15.0</td></tr>"
        "</table></body></html>"
    ).encode("utf-8")
    (native / "QTS_7.htm").write_bytes(original)
    (root / "QTS_Gold_Comparison_synthetic.json").write_text(json.dumps({
        "live": "LOCKED", "validated_edge": False,
        "reports_parsed": 1, "all_styles_identified": False,
        "results": [{"style": 7, "state": "PARSED",
                     "style_identity": "STYLE_VERIFIED",
                     "sha256": hashlib.sha256(original).hexdigest(),
                     "net_usd": net, "profit_factor": 1.2,
                     "maximal_equity_drawdown": 15.0, "trades": count}],
    }), encoding="utf-8")
    return root


def pair(tmp_path, start=FIRST, *, baseline=5.0, revised=8.0, trades=1, source=SOURCE):
    a = fixture(tmp_path / start.isoformat() / "base", "BASELINE", start,
                profit=baseline, count=trades, source=source)
    b = fixture(tmp_path / start.isoformat() / "v3", "CONTEXT_V3", start,
                profit=revised, count=trades, source=source)
    return a, b


def test_no_evidence_cannot_grant_capital_authority():
    result = audit([], as_of=date(2026, 11, 1))
    assert result["capital_decision"] == "DO_NOT_ENTRUST_REAL_CAPITAL"
    assert result["live"] == "LOCKED"
    assert result["can_send_orders"] is False
    assert result["edge_validated"] is False
    assert "INSUFFICIENT_COMPLETED_PROSPECTIVE_MONTHS" in result["blockers"]


def test_valid_native_month_still_never_approves_live(tmp_path):
    a, b = pair(tmp_path)
    result = audit([(a, b)], as_of=date(2026, 12, 1))
    assert result["months_verified"] == 1
    assert result["native_v3_positions"] == 1
    assert result["v3_minus_baseline_stressed_net"] == 3.0
    assert result["native_evidence_issues"] == []
    assert result["capital_decision"] == "DO_NOT_ENTRUST_REAL_CAPITAL"
    assert "CONNECTED_DEMO_FORWARD_RELIABILITY_NOT_QUALIFIED" in result["blockers"]


def test_corrupted_original_html_digest_excluded(tmp_path):
    a, b = pair(tmp_path)
    with (b / "native" / "QTS_7.htm").open("ab") as stream:
        stream.write(b"altered original")
    report = audit([(a, b)], as_of=date(2026, 12, 1))
    assert report["months_verified"] == 0
    assert "NATIVE_EVIDENCE_INVALID_OR_INCOMPLETE" in report["blockers"]


def test_native_deal_mismatch_is_rejected(tmp_path):
    a, b = pair(tmp_path)
    file = b / "native" / "QTS_7_trades.csv"
    file.write_text(file.read_text("utf-8").replace(";8.0;0;0;0", ";800.0;0;0;0"), encoding="utf-8")
    with pytest.raises(InvalidEvidence, match="conflict"):
        load_native(b, "CONTEXT_V3", date(2026, 12, 1))


def test_source_identity_missing_or_changed_fails_closed(tmp_path):
    a, b = pair(tmp_path)
    manifest = json.loads((b / "OPEN_RESULTS.json").read_text("utf-8"))
    manifest.pop("source_manifest_sha256")
    (b / "OPEN_RESULTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert audit([(a, b)], as_of=date(2026, 12, 1))["months_verified"] == 0
    a, b = pair(tmp_path / "different", source="b" * 64)
    b_manifest = json.loads((b / "OPEN_RESULTS.json").read_text("utf-8"))
    b_manifest["source_manifest_sha256"] = "c" * 64
    (b / "OPEN_RESULTS.json").write_text(json.dumps(b_manifest), encoding="utf-8")
    assert audit([(a, b)], as_of=date(2026, 12, 1))["months_verified"] == 0


def test_incomplete_or_replayed_month_cannot_pass(tmp_path):
    a, b = pair(tmp_path)
    result = audit([(a, b)], as_of=date(2026, 11, 15))
    assert result["months_verified"] == 0
    result = audit([(a, b), (a, b)], as_of=date(2026, 12, 1))
    assert result["months_verified"] == 1
    assert "NATIVE_EVIDENCE_INVALID_OR_INCOMPLETE" in result["blockers"]


def test_nonconsecutive_months_must_be_reported(tmp_path):
    first = pair(tmp_path, date(2026, 11, 1))
    third = pair(tmp_path, date(2027, 1, 1))
    result = audit([third, first], as_of=date(2027, 2, 1))
    assert result["months_verified"] == 2
    assert any("Missing/unsorted prospective" in x.get("reason", "")
               for x in result["native_evidence_issues"])


def test_unrealistic_positive_synthetic_results_do_not_unlock(tmp_path):
    pairs = []
    month = FIRST
    for i in range(6):
        pairs.append(pair(tmp_path, month, baseline=1.0,
                          revised=90.0, trades=40))
        month = month_after(month)
    result = audit(pairs, as_of=date(2027, 5, 1))
    assert result["months_verified"] == 6
    assert result["native_v3_positions"] == 240
    assert result["v3_net_after_additional_10_usd_per_lot_stress"] > 0
    assert result["v3_minus_baseline_stressed_net"] > 0
    assert result["capital_decision"] == "DO_NOT_ENTRUST_REAL_CAPITAL"
    assert "REAL_MONEY_ORDER_AUTHORIZATION_NOT_AVAILABLE" in result["blockers"]
    assert result["can_send_orders"] is False


def test_auto_discovery_rejects_missing_and_duplicate_arms(tmp_path):
    root = tmp_path / "collected"
    single = fixture(root / "one", "BASELINE", FIRST)
    paths, problems = discover_pairs(root)
    assert paths == []
    assert any("Missing or duplicate" in p["reason"] for p in problems)
    other = fixture(root / "two", "CONTEXT_V3", FIRST)
    paths, problems = discover_pairs(root)
    assert paths == [(single, other)]
    assert not problems
    fixture(root / "three", "CONTEXT_V3", FIRST)
    paths, problems = discover_pairs(root)
    assert paths == []
    assert problems


def test_out_of_period_broker_trade_cannot_fake_month(tmp_path):
    a, b = pair(tmp_path)
    csv = b / "native" / "QTS_7_trades.csv"
    txt = csv.read_text("utf-8")
    original = int(datetime(2026, 11, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
    outside = int(datetime(2026, 10, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
    csv.write_text(txt.replace(str(original), str(outside)), encoding="utf-8")
    with pytest.raises(InvalidEvidence, match="timestamps outside"):
        load_native(b, "CONTEXT_V3", date(2026, 12, 1))


def test_quick_run_remains_read_only():
    launcher = (ROOT / "REVIEW_CAPITAL_READINESS.bat").read_text("utf-8")
    assert "capital_readiness.py" in launcher
    assert "--auto-discover" in launcher
    assert "LIVE: LOCKED" in launcher
    assert "OrderSend(" not in launcher


def test_no_real_order_code_or_unlocked_status():
    module = (ROOT / "research" / "capital_readiness.py").read_text("utf-8")
    runner = (ROOT / "research" / "RunAutomaticTester.ps1").read_text("utf-8")
    assert "OrderSend(" not in module
    assert "order_send(" not in module
    assert '"can_send_orders": False' in module
    assert "source_manifest_sha256=$sourceManifestSha256" in runner
