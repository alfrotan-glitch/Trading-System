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
from forward_shadow_observer import FIELDS, freeze, review, native_heartbeat, select_study_dir

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
    f = signals / f"QTS_ForwardShadowV2_Style{style}_{month}.csv"
    vals = {
        "schema": "qts.mt5.forward_shadow_signal.v2",
        "observed_utc_s": at, "closed_bar_open_server_s": bar,
        "tick_server_time_msc": (bar + 964) * 1000,
        "symbol": "XAUUSD@", "timeframe": "M15",
        "style": style, "side": side,
        "bid": "2450.21", "ask": "2450.42",
        "atr14": "15.0" if high else "6.0",
        "prior_48_atr_median": "10.0",
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



def write_health(signals, at):
    health = signals / "QTS_ForwardShadowV2_HEALTH.csv"
    with health.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["schema", "utc_s", "server_s", "bar_server_s",
                         "symbol", "timeframe", "mode", "connected",
                         "orders_authorized", "phase"])
        writer.writerow(["qts.mt5.forward_shadow_health.v1", at, at,
                         at - 900, "XAUUSD@", "M15",
                         "ONE_CHART_TWO_STYLES", 1, 0, "WAITING_FOR_M15_CLOSE"])


def test_source_upgrade_isolated_epoch_preserves_old_frozen_evidence(tmp_path):
    reports, signals, source = fresh(tmp_path)
    old_path = reports / "QTS_FORWARD_SHADOW_V2_FROZEN.json"
    old_bytes = old_path.read_bytes()
    legacy_report = reports / "QTS_FORWARD_SHADOW_V2_REPORT.json"
    legacy_report.write_text('{"status":"LEGACY_DESCRIPTIVE_ONLY"}', encoding="utf-8")
    assert select_study_dir(reports, source) == reports
    source.write_text("modified future native source", encoding="utf-8")
    epoch_dir = select_study_dir(reports, source)
    assert epoch_dir != reports
    assert "epochs" in epoch_dir.parts
    assert epoch_dir == select_study_dir(reports, source)
    write_health(signals, START + 200)
    append_native(signals, at=START + 65)
    observed = review(epoch_dir, signals, source, now_utc_s=START + 200)
    assert observed["candidate_events_since_registration"] == 0
    assert observed["pre_registration_events_excluded"] == 1
    assert observed["frozen_at_utc_s"] == START + 200
    assert old_path.read_bytes() == old_bytes
    archive = reports / "legacy_epochs" / json.loads(old_bytes)["ea_source_sha256"][:24]
    assert (archive / old_path.name).read_bytes() == old_bytes
    assert (archive / legacy_report.name).read_bytes() == legacy_report.read_bytes()


def test_tampered_freeze_does_not_get_silently_migrated(tmp_path):
    reports, signals, source = fresh(tmp_path)
    marker = reports / "QTS_FORWARD_SHADOW_V2_FROZEN.json"
    data = json.loads(marker.read_text("utf-8"))
    data["policy_sha256"] = "tampered"
    marker.write_text(json.dumps(data), encoding="utf-8")
    source.write_text("new version", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupted or rules changed"):
        select_study_dir(reports, source)


def test_no_native_beacon_cannot_be_mistaken_for_running_system(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    out = review(reports, signals, ea, now_utc_s=START + 100)
    assert out["status"] == "NATIVE_EA_HEARTBEAT_MISSING_NO_GO"
    assert out["native_ea_health"]["status"] == "NATIVE_EA_HEARTBEAT_MISSING_NO_GO"
    write_health(signals, START + 100)
    out = review(reports, signals, ea, now_utc_s=START + 110)
    assert out["status"] == "REGISTERED_WAITING_FOR_NATIVE_DEMO_SIGNALS"
    assert out["native_ea_health"]["age_seconds"] == 10
    out = review(reports, signals, ea, now_utc_s=START + 250)
    assert out["status"] == "NATIVE_EA_HEARTBEAT_INVALID_OR_STALE_NO_GO"


def test_order_authorized_beacon_is_not_trusted(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    write_health(signals, START + 100)
    health = signals / "QTS_ForwardShadowV2_HEALTH.csv"
    text = health.read_text("utf-8").replace(
        "ONE_CHART_TWO_STYLES;1;0;", "ONE_CHART_TWO_STYLES;1;1;"
    )
    health.write_text(text, encoding="utf-8")
    assert native_heartbeat(signals, now_utc_s=START + 110)["status"].endswith("NO_GO")


def test_one_time_freeze_ignores_prior_market_candidates(tmp_path):
    reports, signals, ea = fresh(tmp_path)
    append_native(signals, at=START - 40, bar=START - 1005)
    write_health(signals, START + 120)
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
    write_health(signals, START + 3000)
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
    first = json.loads((reports / "QTS_FORWARD_SHADOW_V2_FROZEN.json").read_text())
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


def test_forward_14tr_48reference_definition_matches_retrospective():
    # Verify the EXACT rolling TR arithmetic used in the native MQL5 loop
    # against the historic Python market context formula, with varied OHLC.
    import statistics
    from retrospective_context import atr_at

    bars = []
    for i in range(64):
        close = 2400.0 + i * 0.17 + (i % 7) * 0.11
        bars.append({
            "open": close - 0.2,
            "high": close + 0.45 + (i % 5) * 0.03,
            "low": close - 0.35 - (i % 3) * 0.07,
            "close": close,
        })
    values = []
    for stop in range(16, 65):
        trsum = 0.0
        for k in range(stop - 14, stop):
            current = bars[k]
            prev = bars[k - 1]["close"]
            trsum += max(
                current["high"] - current["low"],
                abs(current["high"] - prev),
                abs(current["low"] - prev),
            )
        avg_tr = trsum / 14.0
        assert avg_tr == pytest.approx(atr_at(bars, stop))
        if stop < 64:
            values.append(avg_tr)
        else:
            current_atr = avg_tr
    assert len(values) == 48
    assert statistics.median(values) == pytest.approx(
        statistics.median(atr_at(bars, i) for i in range(16, 64))
    )
    assert current_atr == pytest.approx(atr_at(bars, 64))
    code = (GOLD / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text("utf-8")
    assert "for(int stop=16;stop<=64;stop++)" in code
    assert "for(int k=stop-14;k<stop;k++)" in code
    assert "historical_atr[23]+historical_atr[24]" in code


def test_observational_path_excludes_broker_execution_and_historical_fitting():
    source = (GOLD / "research" / "forward_shadow_observer.py").read_text("utf-8")
    ea = (GOLD / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text("utf-8")
    assert "RecordNativeForwardShadow(side,atr,(int)EntryStyle);" in ea
    assert "EnableDemoOrders || EnableDemoForwardOrders" in ea
    assert "CopyRates(_Symbol,PERIOD_M15,1,64,closed_bars)" in ea
    assert "NATIVE_CLOSED_BAR_UNARMED_DEMO" in ea
    for prohibited in ("order_send(", "mt5.login(", "OrderSend(", "ENABLE_LIVE",
                       "optimization_fit(", "broker.execute("):
        assert prohibited not in source
    assert "no trade" in source.lower() or "no orders" in source.lower()
