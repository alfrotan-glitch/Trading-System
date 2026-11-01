"""No-broker regression tests of post-hoc Sweep/Reclaim shadow arithmetic."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from shadow_filter_review import review


def one(period, values, binary="same-ex5"):
    """values: [(side, above_median, dollars, lots), ...]."""
    rows = []
    for idx, (side, high, pnl, lots) in enumerate(values):
        rows.append({
            "style": 3, "position_id": str(idx + 100),
            "side": side, "entry_lots": lots, "net_usd": pnl,
            "month_utc": period[0][:7].replace(".", "-"),
            "atr_band": ("ABOVE_TRAILING_MEDIAN" if high
                         else "AT_OR_BELOW_TRAILING_MEDIAN"),
            "market": {"status": "COMPLETE_CLOSED_BAR_AND_BID_ASK"},
        })
    gross = sum(v[2] for v in values)
    volume = sum(v[3] for v in values)
    return {
        "schema": "qts.mt5.retrospective_context.v1",
        "status": "DESCRIPTIVE_ONLY_REVIEW_REQUIRED",
        "live": "LOCKED", "validated_edge": False,
        "symbol": "XAUUSD@", "test_period": period,
        "source_compiled_ex5_sha256": binary,
        "source_manifest_sha256": "same-manifest",
        "complete_market_snapshots": len(rows),
        "total_positions": len(rows),
        "positions": rows,
        "cohorts": {"style": {"3": {
            "positions": len(rows),
            "native_net_usd": round(gross, 2),
            "entry_lots": round(volume, 5),
        }}},
    }


def samples():
    # Small deliberately conflicting candidate behavior across time.
    early = one(["2026.01.01", "2026.04.01"], [
        ("BUY", True, 3.40, 0.12),
        ("SELL", True, -12.47, 0.04),
        ("BUY", False, 10.43, 0.26),
        ("SELL", False, -11.45, 0.07),
    ])
    later = one(["2026.05.01", "2026.11.01"], [
        ("BUY", True, -124.08, 0.39),
        ("SELL", True, 107.19, 0.57),
        ("BUY", False, 56.78, 0.45),
        ("SELL", False, 91.05, 0.57),
    ])
    return [early, later]


def test_posthoc_shadow_keeps_native_fills_without_replaying():
    result = review(samples())
    assert result["status"] == "POST_HOC_REVIEW_NO_LIVE_PROMOTION"
    assert result["independent_out_of_sample_periods"] == 0
    first = result["cohorts"]["2026.01.01..2026.04.01"]
    last = result["cohorts"]["2026.05.01..2026.11.01"]
    assert first["BASELINE"]["native_net_usd"] == -10.09
    assert first["SHADOW_ATR_LOW"]["native_net_usd"] == -1.02
    assert first["SHADOW_NO_BUY_HIGH_ATR"]["native_net_usd"] == -13.49
    assert last["BASELINE"]["native_net_usd"] == 130.94
    assert last["SHADOW_ATR_LOW"]["native_net_usd"] == 147.83
    assert last["SHADOW_NO_BUY_HIGH_ATR"]["native_net_usd"] == 255.02
    assert last["SHADOW_ATR_LOW"]["hypothetical_after_extra_costs_usd"]["20"] == 127.43
    assert first["SHADOW_ATR_LOW"]["hypothetical_after_extra_costs_usd"]["20"] == -7.62
    assert result["comparisons"]["SHADOW_ATR_LOW"]["positive_delta_in_every_examined_period"]
    assert not result["comparisons"]["SHADOW_NO_BUY_HIGH_ATR"]["positive_delta_in_every_examined_period"]
    assert not result["comparisons"]["SHADOW_ATR_LOW"]["positive_absolute_net_after_20usd_per_lot_in_every_period"]
    assert result["live"] == "LOCKED"
    assert result["can_autotune_or_promote"] is False
    assert result["shadow_signals_sending_orders"] is False


def test_unreconciled_report_does_not_get_filtered():
    reports = samples()
    reports[0]["cohorts"]["style"]["3"]["native_net_usd"] += 20
    with pytest.raises(ValueError, match="reconciled"):
        review(reports)


def test_missing_market_quote_and_partial_original_run_no_go():
    reports = samples()
    reports[0]["positions"][0]["market"]["status"] = "UNKNOWN_MARKET_HISTORY"
    with pytest.raises(ValueError, match="market evidence"):
        review(reports)
    reports = samples()
    reports[0]["quarantined_position_count"] = 1
    with pytest.raises(ValueError, match="Incomplete"):
        review(reports)


def test_different_compiled_ea_must_not_be_pooled():
    reports = samples()
    reports[1]["source_compiled_ex5_sha256"] = "different-ex5"
    with pytest.raises(ValueError, match="mismatch"):
        review(reports)


def test_duplicate_and_overlapping_periods_no_go():
    early, later = samples()
    with pytest.raises(ValueError, match="Duplicate"):
        review([early, early])
    # overlap an existing period with different start/end and coherent source
    overlapping = one(["2026.03.01", "2026.09.01"], [
        ("BUY", False, 11.0, 0.01),
    ])
    with pytest.raises(ValueError, match="Overlapping"):
        review([early, overlapping])


def test_duplicate_position_id_no_go():
    reports = samples()
    reports[0]["positions"][1]["position_id"] = reports[0]["positions"][0]["position_id"]
    with pytest.raises(ValueError, match="Duplicated"):
        review(reports)


def test_invalid_direction_and_nonfinite_net_no_go():
    reports = samples()
    reports[0]["positions"][0]["side"] = "DONT_KNOW"
    with pytest.raises(ValueError, match="market evidence"):
        review(reports)
    reports = samples()
    reports[0]["positions"][0]["net_usd"] = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        review(reports)


def test_source_cannot_send_orders_or_self_promote():
    content = (ROOT / "research" / "shadow_filter_review.py").read_text("utf-8")
    for token in ("order_send(", "OrderSend(", "mt5.login(", "ENABLE_LIVE"):
        assert token not in content
    report = review(samples())
    assert all(c["approval"] == "NOT_APPROVED_POST_HOC"
               for c in report["comparisons"].values())
    assert json.loads(json.dumps(report))["validated_edge"] is False
