"""Adversarial Champion-Challenger V5 contract. Synthetic fixtures, no live orders."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"research"))

from ten_trade_learning import reflect
from v5_study import freeze, verify, compare, digest, canonical, SCHEMA

NOW = datetime(2026,11,1,tzinfo=timezone.utc)
MANIFEST = b'{"sha256_files":[]}'
CUTOFF = int(datetime(2026,10,25,tzinfo=timezone.utc).timestamp()*1000)
FUTURE = int(datetime(2026,12,15,tzinfo=timezone.utc).timestamp()*1000)


def pos(i, style=8, regime="TREND", when=None, pnl=-3.0):
    when = when if when is not None else CUTOFF + i*60_000
    return {
        "position_id": str(i), "selected_style": style,
        "strategy": "SMC_FVG_OB" if style == 8 else "RETEST",
        "regime": regime, "side": "BUY", "entry_price": 4000.0,
        "initial_sl": 3990.0, "initial_tp": 4020.0,
        "exit_price": 3988.0, "entry_time_msc": when-60_000,
        "exit_time_msc": when, "exit_reason": "DEAL_REASON_SL",
        "lots": 0.02, "broker_net_usd": pnl,
        "gross_usd": pnl+0.20, "recorded_charges_usd": -0.20,
        "duration_minutes": 1.0, "price_rr_ex_ante": 2.0,
        "broker_exit_deal_ids": ["deal_"+str(i)],
    }


def attributed(rows):
    return {
        "schema": "qts.mt5.v4.position_strategy_attribution.v1",
        "status": "ATTRIBUTED_FOR_RESEARCH_ONLY",
        "live": "LOCKED", "edge_validated": False,
        "can_autotune_or_promote": False, "issues": [],
        "native_positions_seen": len(rows), "native_positions_attributed": len(rows),
        "positions": rows,
    }


def study():
    refl=reflect(attributed([pos(i) for i in range(1,11)]))
    refl["read_only_native_attribution_sha256"]="a"*64
    return freeze(refl, MANIFEST, style=8, regime="TREND", checkpoint=1,
                  from_date="2026.12.01", to_date="2027.01.01", now=NOW)


def run(tmp_path, name, rows, plan, *, variant):
    root=tmp_path/name
    root.mkdir()
    payload = {
        "research_variant": variant, "source_manifest_sha256": digest(MANIFEST),
        "from_date": plan["from_date"], "to_date": plan["to_date"],
        "symbol": "XAUUSD@", "model": 4, "timeframe": "M15",
        "deposit_usd": 3000, "selected_styles": [7], "targeted": True,
        "live": "LOCKED", "validated_edge": False,
        "real_money_orders": False, "state": "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
        "challenger_veto_style": (8 if variant.endswith("_VETO") else None),
        "challenger_veto_regime": (2 if variant.endswith("_VETO") else None),
    }
    (root/"OPEN_RESULTS.json").write_text(json.dumps(payload))
    (root/"QTS_V4_POSITION_ATTRIBUTION.json").write_text(json.dumps(attributed(rows)))
    return root


def test_plan_derived_only_from_observed_proposal_and_starts_in_future():
    plan=study()
    assert plan["schema"] == SCHEMA
    assert plan["frozen_style"] == 8 and plan["frozen_regime_id"] == 2
    assert plan["champion"] == "ADAPTIVE_V4"
    assert plan["challenger"] == "ADAPTIVE_V5_VETO"
    assert plan["real_orders_permitted"] is False
    assert plan["auto_promote"] is False
    verify(plan, manifest_bytes=MANIFEST, now=NOW)
    with pytest.raises(ValueError, match="not completed"):
        verify(plan, manifest_bytes=MANIFEST, now=NOW, completed=True)


def test_modifying_style_during_study_invalidates_integrity():
    plan=study()
    plan["frozen_style"]=3
    with pytest.raises(ValueError, match="changed after freeze"):
        verify(plan, manifest_bytes=MANIFEST)


def test_source_code_or_manifest_change_forces_new_study():
    with pytest.raises(ValueError, match="Native source changed"):
        verify(study(), manifest_bytes=b'{"sha256_files":[1]}')


def test_freeze_cannot_use_seen_period_or_start_on_creation_day():
    refl=reflect(attributed([pos(i) for i in range(1,11)]))
    refl["read_only_native_attribution_sha256"]="a"*64
    with pytest.raises(ValueError, match="START after"):
        freeze(refl, MANIFEST, style=8, regime="TREND", checkpoint=1,
               from_date="2026.10.25", to_date="2026.11.01", now=NOW)
    with pytest.raises(ValueError, match="START after"):
        freeze(refl, MANIFEST, style=8, regime="TREND", checkpoint=1,
               from_date="2026.11.01", to_date="2026.12.01", now=NOW)


def test_no_invented_proposal_and_no_arbitrary_strategy():
    refl=reflect(attributed([pos(i) for i in range(1,11)]))
    refl["read_only_native_attribution_sha256"]="a"*64
    with pytest.raises(ValueError, match="No recorded"):
        freeze(refl, MANIFEST, style=3, regime="TREND", checkpoint=1,
               from_date="2026.12.01", to_date="2027.01.01", now=NOW)
    with pytest.raises(ValueError, match="Invalid frozen"):
        freeze(refl, MANIFEST, style=7, regime="TREND", checkpoint=1,
               from_date="2026.12.01", to_date="2027.01.01", now=NOW)


def test_native_champion_challenger_is_actual_two_arm_full_portfolio_comparison(tmp_path):
    plan=study()
    champion=[pos(1,when=FUTURE,pnl=-8.0),
              pos(2,style=1,regime="RANGE",when=FUTURE+100000,pnl=2.0)]
    challenger=[pos(2,style=1,regime="RANGE",when=FUTURE+100000,pnl=2.0)]
    c=run(tmp_path,"champ",champion,plan,variant="ADAPTIVE_V4")
    v=run(tmp_path,"veto",challenger,plan,variant="ADAPTIVE_V5_VETO")
    report=compare(plan,MANIFEST,c,v,now=datetime(2027,1,2,tzinfo=timezone.utc))
    assert report["status"]=="DESCRIPTIVE_NATIVE_COMPARISON_NO_RELEASE"
    assert report["champion"]["trades"] == 2
    assert report["challenger"]["trades"] == 1
    assert report["actual_champion_positions_matching_veto"] == 1
    assert report["observed_stressed_net_difference_challenger_minus_champion_usd"] > 0
    assert report["auto_promote"] is False
    assert report["real_orders_permitted"] is False
    assert report["floating_equity_drawdown_unavailable"] is True


def test_no_frozen_veto_exercised_never_counts_as_positive_edge(tmp_path):
    plan=study()
    rows=[pos(1,style=1,regime="RANGE",when=FUTURE,pnl=4)]
    c=run(tmp_path,"champ",rows,plan,variant="ADAPTIVE_V4")
    v=run(tmp_path,"veto",rows,plan,variant="ADAPTIVE_V5_VETO")
    output=compare(plan,MANIFEST,c,v,now=datetime(2027,1,3,tzinfo=timezone.utc))
    assert output["status"]=="FROZEN_VETO_UNEXERCISED_NO_GO"
    assert output["edge_validated"] is False


def test_challenger_cannot_execute_preregistered_vetoed_style(tmp_path):
    plan=study()
    c=run(tmp_path,"champ",[pos(1,when=FUTURE)],plan,variant="ADAPTIVE_V4")
    v=run(tmp_path,"veto",[pos(1,when=FUTURE)],plan,variant="ADAPTIVE_V5_VETO")
    with pytest.raises(ValueError, match="violated its frozen veto"):
        compare(plan,MANIFEST,c,v,now=datetime(2027,1,3,tzinfo=timezone.utc))


def test_champion_not_contaminated_or_posthoc_patched(tmp_path):
    plan=study()
    c=run(tmp_path,"champ",[pos(1,when=FUTURE)],plan,variant="ADAPTIVE_V4")
    v=run(tmp_path,"veto",[pos(2,style=1,regime="RANGE",when=FUTURE)],plan,variant="ADAPTIVE_V5_VETO")
    data=json.loads((c/"OPEN_RESULTS.json").read_text())
    data["challenger_veto_style"]=8
    (c/"OPEN_RESULTS.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Champion is contaminated"):
        compare(plan,MANIFEST,c,v,now=datetime(2027,1,3,tzinfo=timezone.utc))


def test_challenger_different_date_or_contract_fails(tmp_path):
    plan=study()
    c=run(tmp_path,"champ",[pos(1,when=FUTURE)],plan,variant="ADAPTIVE_V4")
    v=run(tmp_path,"veto",[pos(2,style=1,regime="RANGE",when=FUTURE)],plan,variant="ADAPTIVE_V5_VETO")
    data=json.loads((v/"OPEN_RESULTS.json").read_text())
    data["to_date"]="2027.02.01"
    (v/"OPEN_RESULTS.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="dates differ"):
        compare(plan,MANIFEST,c,v,now=datetime(2027,2,3,tzinfo=timezone.utc))


def test_mql_native_v5_isolated_veto_and_all_original_risk_guards():
    ea=(ROOT/"mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
    router=(ROOT/"mt5_robot/AdaptiveV4Research.mqh").read_text("utf-8")
    runner=(ROOT/"research/RunAutomaticTester.ps1").read_text("utf-8")
    assert "TesterUsePreregisteredVetoV5 = false" in ea
    assert "TesterVetoStyleV5          = -1" in ea
    assert "TesterVetoRegimeV5         = -1" in ea
    assert "if(TesterUsePreregisteredVetoV5 &&" in router
    assert "chosen_style==TesterVetoStyleV5 && regime==TesterVetoRegimeV5" in router
    assert router.index("evaluated_style=chosen_style;") < router.index("QTS V5 PREREGISTERED_VETO")
    assert "QTS V5 PREREGISTERED_VETO" in router
    assert "if(RealAccountBlocked())" in ea
    assert "OrderCheck(request,check)" in ea
    assert "PlannedOrderFitsRisk(side,lots,price,stop)" in ea
    assert "'ADAPTIVE_V5_VETO'" in runner
    assert "if($ResearchVariant -eq 'ADAPTIVE_V5_VETO')" in runner
    assert "'TesterUsePreregisteredVetoV5'=($ResearchVariant -eq 'ADAPTIVE_V5_VETO')" in runner


def test_one_click_native_study_enforces_two_arms_and_no_live_orders():
    script=(ROOT/"research/RunNativeV5Challenge.ps1").read_text("utf-8")
    assert "--completed" in script
    assert "-ResearchVariant ADAPTIVE_V4" in script
    assert "-ResearchVariant ADAPTIVE_V5_VETO" in script
    assert "Study output already exists" in script
    assert "LIVE LOCKED" in script or "No REAL trading" in script
