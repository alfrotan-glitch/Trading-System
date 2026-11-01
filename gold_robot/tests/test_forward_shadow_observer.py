"""Prospective native unarmed DEMO observation tests (no MT5 required)."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLD / "research"))
from forward_shadow_observer import FIELDS, freeze, review

START = 1_780_000_000


def fresh(tmp_path, t=START):
    src = tmp_path / "EA.mq5"
    src.write_text("canonical native EA source", encoding="utf-8")
    reports = tmp_path / "reports"
    signals = tmp_path / "common_files"
    signals.mkdir()
    freeze(reports, src, now_utc_s=t)
    return reports, signals, src


def append_native(signals, *, style=3, side="BUY", high=True,
                  at=START + 65, bar=None, override=None):
    if bar is None:
        bar = at - 965
    month = datetime.fromtimestamp(at, tz=timezone.utc).strftime("%Y%m")
    f = signals / f"QTS_ForwardShadow_Style{style}_{month}.csv"
    vals = {
        "schema": "qts.mt5.forward_shadow_signal.v1",
        "observed_utc_s": at, "closed_bar_open_server_s": bar,
        "tick_server_time_msc": (bar + 964) * 1000,
        "symbol": "XAUUSD@", "timeframe": "M15",
        "style": style, "side": side,
        "bid": "2450.21", "ask": "2450.42",
        "atr14": "15.0" if high else "6.0",
        "prior_20_atr_median": "10.0",
        "atr_band": ("ABOVE_TRAILING_MEDIAN" if high
                     else "AT_OR_BELOW_TRAILING_MEDIAN"),
        "source": "NATIVE_CLOSED_BAR_UNARMED_DEMO",
    }
    vals.update(override or {})
    with f.open("a", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(FIELDS), delimiter=";")
        if f.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(vals)
    return f


def test_one_time_freeze_ignores_prior_market_candidates(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    append_native(signals, at=START - 40, bar=START - 1005)
    before = review(reports, signals, ea, now_utc_s=START + 120)
    assert before["candidate_events_since_registration"] == 0
    assert before["pre_registration_events_excluded"] == 1
    assert before["status"] == "REGISTERED_WAITING_FOR_NATIVE_DEMO_SIGNALS"
    assert before["validated_edge"] is False
    assert before["live"] == "LOCKED"


def test_three_frozen_shadow_cohorts_never_claim_profit(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    append_native(signals, side="BUY", high=True, at=START + 65)
    append_native(signals, side="SELL", high=True, at=START + 965)
    append_native(signals, side="BUY", high=False, at=START + 1865)
    append_native(signals, style=1, side="SELL",
                  high=False, at=START + 2765)
    output = review(reports, signals, ea, now_utc_s=START + 3000)
    assert output["status"] == "FORWARD_SIGNALS_OBSERVED_ONLY_NO_TRADE_OUTCOME"
    assert output["candidate_events_since_registration"] == 4
    assert output["native_candidates_by_style"]["RETEST"]["native_closed_bar_candidate_count"] == 1
    assert output["style_3_shadow_candidate_counts"] == {
        "BASELINE": 3, "SHADOW_ATR_LOW": 1,
        "SHADOW_NO_BUY_HIGH_ATR": 2,
    }
    assert output["performance_pnl_available"] is False
    assert output["executed_fills_observed"] is False
    assert output["connected_orders_authorized"] is False
    assert output["can_autotune_or_promote"] is False


def test_policy_and_ea_source_are_immutable_in_same_registration(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    first = json.loads((reports / "QTS_FORWARD_SHADOW_FROZEN.json").read_text())
    second = freeze(reports, ea, now_utc_s=START + 1000)
    assert second["frozen_at_utc_s"] == START
    assert second["policy_sha256"] == first["policy_sha256"]
    ea.write_text("modified EA", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        review(reports, signals, ea, now_utc_s=START + 1000)


def test_duplicate_same_bar_candidate_is_no_go(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    bar = START - 900
    append_native(signals, at=START + 65, bar=bar)
    append_native(signals, at=START + 66, bar=bar)
    out = review(reports, signals, ea, now_utc_s=START + 150)
    assert out["status"] == "EVIDENCE_GAPS_NO_GO"
    assert len(out["evidence_gaps"]) == 1
    assert "Duplicate" in out["evidence_gaps"][0]["problem"]


def test_wrong_atr_band_or_invalid_bidask_never_pass(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    append_native(signals, override={"atr_band": "AT_OR_BELOW_TRAILING_MEDIAN"})
    out = review(reports, signals, ea, now_utc_s=START + 140)
    assert out["status"] == "EVIDENCE_GAPS_NO_GO"
    assert out["candidate_events_since_registration"] == 0


def test_files_with_other_symbols_or_style_mismatch_are_no_go(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    append_native(signals, style=1, override={"symbol": "EURUSD"})
    out = review(reports, signals, ea, now_utc_s=START + 140)
    assert out["status"] == "EVIDENCE_GAPS_NO_GO"


def test_observational_path_excludes_broker_execution_and_historical_fitting():
    source = (GOLD / "research" / "forward_shadow_observer.py").read_text("utf-8")
    ea = (GOLD / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text("utf-8")
    assert "RecordNativeForwardShadow(side,atr);" in ea
    assert "EnableDemoOrders || EnableDemoForwardOrders" in ea
    assert "CopyBuffer(atr_handle,0,2,20,historical_atr)" in ea
    assert "NATIVE_CLOSED_BAR_UNARMED_DEMO" in ea
    for prohibited in ("order_send(", "mt5.login(", "OrderSend(", "ENABLE_LIVE",
                       "optimization_fit(", "broker.execute("):
        assert prohibited not in source
    assert "no trade" in source.lower() or "no orders" in source.lower()
