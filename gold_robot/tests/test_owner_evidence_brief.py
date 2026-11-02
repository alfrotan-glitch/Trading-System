"""Owner-facing evidence report cannot silently convert old gains into live advice."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from owner_evidence_brief import build, historical_forensics, make_html

ROOT = Path(__file__).resolve().parents[2]


def test_owner_evidence_is_immediate_and_never_promotes_old_winners():
    report = build(ROOT, generated_at="2026-11-02T00:00:00+00:00")
    assert report["schema"] == "qts.gold.owner_evidence_brief.v1"
    assert report["status"] == "NO_INDEPENDENTLY_VALIDATED_PROFITABLE_EDGE"
    assert report["live"] == "LOCKED"
    assert report["validated_edge"] is False
    assert report["strategy_promoted"] is False
    assert report["connected_orders_authorized"] is False
    assert report["broker_calls"] == 0
    assert report["orders_sent"] == 0
    assert report["laptop_must_stay_on_to_read_existing_evidence"] is False
    assert report["forensics"]["exploratory_positive_styles"] == [1, 3]
    assert report["forensics"]["not_a_portfolio_pnl"] is True
    assert len(report["forensics"]["styles"]) == 8
    assert len(report["older_365d_studies"]) == 7
    assert all(s["economic_edge"] == "NOT ESTABLISHED"
               for s in report["older_365d_studies"])
    assert "DO_NOT_TUNE_ON_ALREADY_VIEWED_2026_APR_OCT_HISTORY" in report["research_priority"]
    assert report["local_evidence_inventory"]["private_content_read"] is False


def test_historical_aggregates_are_exact_and_rejected_arms_not_promoted():
    rec = historical_forensics(ROOT)
    assert rec["positions_across_separate_tests"] == 938
    assert rec["sl_exits"] == 503
    assert rec["tp_exits"] == 427
    assert rec["other_exits"] == 8
    assert rec["arithmetic_net_across_separate_tests_usd"] == -549.87
    assert [(s["style_id"], s["positions"], s["native_net_usd"])
            for s in rec["styles"] if s["native_net_usd"] > 0] == [
                (1, 68, 39.92), (3, 54, 45.20)
            ]


def test_source_corruption_blocks_a_verdict(tmp_path):
    import shutil

    dest = tmp_path / "gold_robot" / "docs"
    dest.mkdir(parents=True)
    for name in ("POST_STOP_FORENSIC_EVIDENCE_2026-10-30.md", "RELEASE_STATUS.json"):
        shutil.copyfile(ROOT / "gold_robot" / "docs" / name, dest / name)
    study_base = tmp_path / "data" / "evidence"
    study_base.mkdir(parents=True)
    from owner_evidence_brief import STUDIES
    for filename in STUDIES:
        shutil.copyfile(ROOT / "data" / "evidence" / filename, study_base / filename)
    forensic = dest / "POST_STOP_FORENSIC_EVIDENCE_2026-10-30.md"
    forensic.write_text(forensic.read_text("utf-8").replace("+39.92", "+999.92"),
                        encoding="utf-8")
    with pytest.raises(ValueError, match="published aggregates"):
        build(tmp_path)
    shutil.copyfile(ROOT / "gold_robot" / "docs" /
                    "POST_STOP_FORENSIC_EVIDENCE_2026-10-30.md", forensic)
    release = dest / "RELEASE_STATUS.json"
    data = json.loads(release.read_text("utf-8"))
    data["validated_profitable_edge"] = True
    release.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Release decision changed"):
        build(tmp_path)


def test_html_is_static_and_protects_untrusted_text():
    report = build(ROOT, generated_at="2026-11-02T00:00:00+00:00")
    report["older_365d_studies"][0]["study"] = '<script>alert("x")</script>'
    page = make_html(report)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "LIVE LOCKED" in page
    assert "NOT a portfolio result" in page
    assert "No broker orders" in page
    assert 'src="http' not in page
    assert '<iframe' not in page


def test_windows_one_click_exposes_owner_verdict_without_strategy_changes():
    batch = (ROOT / "QTS_OWNER_VERDICT.bat").read_text("utf-8")
    menu = (ROOT / "START_HERE.bat").read_text("utf-8")
    assert "owner_evidence_brief.py" in batch
    assert "QTS_NO_OPEN" in batch
    assert "OWNER VERDICT" in menu
    assert "goto OWNER_VERDICT" in menu
    assert "QTS_OWNER_VERDICT.bat" in menu
    assert "RunAutomaticTester.ps1" not in batch
    assert "OrderSend(" not in batch
    assert "EnableDemoOrders=true" not in batch
