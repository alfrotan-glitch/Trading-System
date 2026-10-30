"""Mirror-logic tests for router hardening + SMC. Screening only.

These tests verify the frozen Python mirror in research/router_logic.py,
which mirrors AdaptiveResearch.mqh / SmcResearch.mqh. They do NOT test
the MQL5 EA itself (no MetaEditor/MT5 on Linux) and must never be quoted
as MT5 results. Native parity on Windows is still required.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
ROOT = Path(__file__).resolve().parents[1]

from router_logic import (
    RouterState,
    atr_guard_pass,
    raw_regime,
    scalp_signal,
    smc_signal,
    transition_allowed,
)


def test_raw_regime_or_means_high_adx_small_gap_is_range():
    assert raw_regime(30.0, 0.05) == 0
    assert raw_regime(30.0, 0.12) == 2
    assert raw_regime(22.0, 0.10) == 1
    assert raw_regime(10.0, 0.50) == 0


def test_persistence_requires_three_consecutive_closed_bars():
    s = RouterState()
    assert s.confirmed_regime(2) == -1
    assert s.confirmed_regime(2) == -1
    assert s.confirmed_regime(2) == 2
    # One flip does not immediately switch the confirmed regime.
    assert s.confirmed_regime(0) == 2
    assert s.confirmed_regime(0) == 2
    assert s.confirmed_regime(0) == 0


def test_atr_guard_abstains_only_above_90th_percentile():
    # Input order is MQL5 CopyBuffer order: OLDEST first, so the current
    # (latest closed) ATR is the LAST element.
    # Current ATR is the maximum of 50 -> percentile 1.0 -> abstain.
    assert atr_guard_pass([1.0] * 49 + [10.0]) is False
    # Current ATR is the median -> pass.
    assert atr_guard_pass([10.0] * 25 + [5.0] * 25) is True
    assert atr_guard_pass([1.0] * 10) is False  # wrong length, fail closed


def test_atr_guard_uses_latest_closed_bar_not_oldest():
    # Regression for the 2026-10-30 MQL5 indexing defect: the guard
    # previously read values[0] (the OLDEST bar, shift 50) as current.
    # Here the oldest bar is the maximum (would abstain under the bug)
    # but the latest closed bar is the median (must pass when fixed).
    assert atr_guard_pass([10.0] + [1.0] * 24 + [9.0] * 24 + [5.0]) is True
    # And symmetrically: a calm oldest bar must not mask a current spike.
    assert atr_guard_pass([1.0] * 49 + [10.0]) is False
    # The MQL5 source must read the last element of the 50-bar window.
    adaptive = (ROOT / "mt5_robot" / "AdaptiveResearch.mqh").read_text(encoding="utf-8")
    assert "values[ROUTER_ATR_LOOKBACK_BARS-1]" in adaptive
    assert "double current=values[0];" not in adaptive


def test_transition_abstention():
    assert transition_allowed(4, 1.0) is True
    assert transition_allowed(3, 2.0) is False
    assert transition_allowed(4, 0.9) is False


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def _long_smc_bars():
    # Prior 12 bars: range 100-110, last opposing (down) candle at index 11.
    bars = [_bar(100 + i * 0.1, 110, 100, 105) for i in range(11)]
    bars.append(_bar(106, 110, 104, 105))  # index 11, down candle = OB [104,110]
    bars.append(_bar(105, 115, 105, 114))  # index 12, displacement close 114 > 110+1.0
    bars.append(_bar(114, 116, 111, 115))  # index 13, FVG: low 111 > bar11 high 110 -> zone [110,111]
    bars.append(_bar(115, 115, 110.5, 114))  # index 14, mitigation into [110,111], closes up
    bars.extend([_bar(114, 115, 113, 114) for _ in range(4)])  # 15-18, neutral
    bars.append(_bar(114, 116, 113, 115))  # index 19, BOS close 115 > swing 110, up
    return bars


def test_smc_long_mitigation_plus_bos_passes():
    r = smc_signal(_long_smc_bars(), atr=10.0, h1_close=120.0, h1_ma=100.0)
    assert r["side"] == 1
    assert r["level"] == 111.0  # FVG top
    assert r["anchor"] == 110.0  # FVG bottom


def test_smc_without_bos_fails():
    bars = _long_smc_bars()
    bars[19] = _bar(114, 115, 108, 109)  # close below swing, no BOS
    assert smc_signal(bars, atr=10.0)["side"] == 0


def test_smc_without_mitigation_fails():
    bars = _long_smc_bars()
    # Bar 13 still defines the FVG (low 111) but must not itself mitigate:
    # make it a down close, and keep bar 14 out of the zone [110,111].
    bars[13] = _bar(115, 116, 111, 112)
    bars[14] = _bar(115, 116, 112, 115)
    assert smc_signal(bars, atr=10.0)["side"] == 0


def test_smc_h1_veto():
    r = smc_signal(_long_smc_bars(), atr=10.0, h1_close=90.0, h1_ma=100.0)
    assert r["side"] == 0
    assert r["reason"] == "H1 veto"


def test_source_contract_frozen_constants_present():
    root = Path(__file__).resolve().parents[1]
    adaptive = (root / "mt5_robot" / "AdaptiveResearch.mqh").read_text()
    assert "ROUTER_PERSISTENCE_BARS 3" in adaptive
    assert "ROUTER_TRANSITION_MIN_PRIORITY 4" in adaptive
    assert "ROUTER_ATR_ABSTAIN_PERCENTILE 0.90" in adaptive
    ea = (root / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text()
    assert "QTS_SMC_FVG_OB=8" in ea
    assert "(int)EntryStyle>9" in ea
    assert "CompletedSmcSignal" in ea and "PrepareSmcLimit" in ea
    smc = (root / "mt5_robot" / "SmcResearch.mqh").read_text()
    assert "SMC_WINDOW_BARS 20" in smc
    assert "MQL_TESTER" not in smc  # tester-only is enforced in the EA (styles>=4)
    assert "((int)EntryStyle>=4" in ea


# ---------------------------------------------------------------- M1 scalp
def test_scalp_pullback_buy():
    past = list(range(100, 132))  # 100..131
    past[-1] = 129.0  # dip below previous 130
    closes = [99.0] + [float(x) for x in past] + [130.5]
    out = scalp_signal(closes)
    assert out["side"] == 1
    assert out["level"] == 130.5
    assert abs(out["stop"] - 130.5 * (1 - 12.0 / 10000.0)) < 1e-9
    assert abs(out["target"] - 130.5 * (1 + 15.0 / 10000.0)) < 1e-9


def test_scalp_range_fade_buy():
    past = [100, 108, 101, 107, 102, 106, 103, 105, 104, 104, 103, 105,
            102, 106, 101, 107, 100, 108, 101, 107, 102, 106, 103, 105,
            104, 104, 103, 105, 102, 106, 101, 100]
    out = scalp_signal([99.0] + [float(x) for x in past] + [101.5])
    assert out["side"] == 1 and out["level"] == 101.5


def test_scalp_breakout_buy():
    past = [100 + i * 0.1 for i in range(32)]
    out = scalp_signal([99.0] + past + [104.0])
    assert out["side"] == 1 and out["level"] == 104.0


def test_scalp_flat_and_short_fail_closed():
    assert scalp_signal([100.0] * 34)["side"] == 0
    assert scalp_signal([100.0] * 10)["side"] == 0


def test_scalp_source_contract():
    ea = (ROOT / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text(encoding="utf-8")
    scalp = (ROOT / "mt5_robot" / "ScalpResearch.mqh").read_text(encoding="utf-8")
    assert "QTS_M1_SCALP=9" in ea
    assert 'if((int)EntryStyle<0 || (int)EntryStyle>9 ||' in ea
    assert "SignalTimeframe!=PERIOD_M1 || MaxPositionMinutes!=15" in ea
    assert "CompletedScalpSignal" in ea and "PrepareScalpLimit" in ea
    assert '"QTS M1 SCALP"' in ea
    assert "#define SCALP_TP_BPS 15.0" in scalp
    assert "#define SCALP_SL_BPS 12.0" in scalp
    assert "#define SCALP_BARS 34" in scalp
    assert "SCALP_EFF_HIGH 0.43" in scalp and "SCALP_EFF_LOW 0.28" in scalp
    assert "MQL_TESTER" not in scalp  # tester-only enforced in the EA, as for SMC
