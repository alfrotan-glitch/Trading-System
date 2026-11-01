"""Offline fixtures for automatic saved-run discovery; no MT5 broker required."""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLD / "research"))
from auto_context_review import candidates, review

UTC = timezone.utc


def archive(root: Path, dirname: str, from_date="2026.01.01",
            to_date="2026.04.01", *, gross=12.0,
            evidence_gaps=False, style_ids=(1, 3)):
    folder = root / "auto_runs" / dirname
    folder.mkdir(parents=True, exist_ok=True)
    entry = datetime.strptime(from_date, "%Y.%m.%d").replace(
        tzinfo=UTC).timestamp() + 14 * 86400 + 15 * 3600
    entry_ms = int(entry * 1000)
    row = {
        "style": 1, "position_id": "a",
        "status": "PARTIAL_OR_OPEN" if evidence_gaps else "COMPLETE",
        "side": "BUY", "exit_reason": "DEAL_REASON_TP",
        "entry_time_msc": str(entry_ms), "exit_time_msc": str(entry_ms + 20000),
        "entry_lots": 0.01, "exit_lots": 0.005 if evidence_gaps else 0.01,
        "net_usd": gross, "gross_usd": gross, "charges_usd": 0,
        "exit_legs": [{"deal_id": "a", "reason": "DEAL_REASON_TP",
                       "time_msc": str(entry_ms + 20000),
                       "lots": 0.005 if evidence_gaps else 0.01}],
    }
    forensics = {
        "schema": "qts.mt5.trade_forensics.v1",
        "status": ("EVIDENCE_GAPS_NO_GO" if evidence_gaps else
                   "SELECTED_IMPORTED_FOR_REVIEW"),
        "live": "LOCKED", "edge_validated": False,
        "targeted": True, "selected_styles": list(style_ids),
        "trades": [row],
    }
    manifest = {
        "live": "LOCKED", "validated_edge": False,
        "targeted": True, "selected_styles": list(style_ids),
        "research_variant": "BASELINE", "symbol": "XAUUSD@", "model": 4,
        "from_date": from_date, "to_date": to_date,
    }
    path = folder / "QTS_SHARE_RESULTS.zip"
    with zipfile.ZipFile(path, "w") as f:
        f.writestr("QTS_TRADE_BY_TRADE.json", json.dumps(forensics))
        f.writestr("OPEN_RESULTS.json", json.dumps(manifest))
    return path


def test_saved_runs_auto_discovered_no_retests_or_manual_path(tmp_path):
    archive(tmp_path, "jan", gross=-10)
    archive(tmp_path, "may", "2026.05.01", "2026.11.01", gross=15)
    result = review(tmp_path, tmp_path / "context_auto")
    assert result["status"] == "INCOMPLETE_OR_QUARANTINED_EVIDENCE_NO_GO"
    assert result["archives_discovered"] == 2
    assert result["studied_runs"] == 2
    assert result["periods"] == ["2026.01.01..2026.04.01", "2026.05.01..2026.11.01"]
    assert all(r["run_status"] == "MARKET_HISTORY_INCOMPLETE_NO_GO"
               for r in result["runs"])
    assert {r["period"]: r["native_profit_by_style_usd"]["1"]
            for r in result["runs"]} == {
                "2026.01.01..2026.04.01": -10.0,
                "2026.05.01..2026.11.01": 15.0,
            }
    assert len(list((tmp_path / "context_auto").glob("QTS_CONTEXT_*.json"))) == 2
    assert result["live"] == "LOCKED"
    assert result["validated_edge"] is False


def test_duplicate_archives_do_not_double_count_trades(tmp_path):
    archive(tmp_path, "copy_1")
    archive(tmp_path, "copy_2")
    result = review(tmp_path, tmp_path / "output")
    assert result["studied_runs"] == 1
    assert result["archives_discovered"] == 2
    assert result["skipped"][0]["status"] == "DUPLICATE_IDENTICAL_LEDGER"
    assert result["period_conflicts"] == []


def test_conflicting_ledgers_in_same_period_are_no_go(tmp_path):
    archive(tmp_path, "a", gross=13)
    archive(tmp_path, "b", gross=-13)
    result = review(tmp_path, tmp_path / "output")
    assert result["status"] == "CONFLICTING_PERIOD_EVIDENCE_NO_GO"
    assert len(result["period_conflicts"]) == 1
    assert result["period_conflicts"][0]["distinct_forensic_ledgers"] == 2
    assert result["validated_edge"] is False


def test_partial_positions_are_reported_not_silently_approved(tmp_path):
    archive(tmp_path, "partial", evidence_gaps=True)
    result = review(tmp_path, tmp_path / "output")
    assert result["studied_runs"] == 1
    assert result["status"] == "INCOMPLETE_OR_QUARANTINED_EVIDENCE_NO_GO"
    assert result["runs"][0]["excluded_position_count"] == 1
    assert result["runs"][0]["native_profit_by_style_usd"] == {}
    assert result["can_autotune_or_promote"] is False


def test_nonbaseline_archive_is_skipped_not_mislabeled(tmp_path):
    archive(tmp_path, "wrong", style_ids=(0, 9))
    result = review(tmp_path, tmp_path / "output")
    assert result["status"] == "NO_ELIGIBLE_ARCHIVE_NO_GO"
    assert result["studied_runs"] == 0
    assert result["skipped"][0]["status"] == "UNUSABLE_OR_NON_BASELINE"


def test_empty_archive_set_fail_closed(tmp_path):
    assert candidates(tmp_path) == []
    result = review(tmp_path, tmp_path / "output")
    assert result["status"] == "NO_SAVED_BASELINE_ARCHIVES_NO_GO"
    assert result["live"] == "LOCKED"


def test_never_runs_order_sender_or_changes_ea():
    source = (GOLD / "research" / "auto_context_review.py").read_text("utf-8")
    for forbidden in ("order_send(", "mt5.login(", "OrderSend(", "ENABLE_LIVE"):
        assert forbidden not in source
    assert "research_filters_applied_to_trading" in source
    assert "data_snooping_warning" in source
