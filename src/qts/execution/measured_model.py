"""Assemble a MEASURED cost model from broker evidence — or refuse to.

Inputs are the three evidence artifacts of the cost pipeline:

* a spread profile (``qts.spread_profile.v1``) — median spread in bps,
* symbol cost terms (``qts.broker_symbol_cost_terms.v1``) — directional
  swap converted to USD/lot/night plus the mid price that turns bps into
  price units,
* recorded deal evidence (``CostEvidenceStore.deals()``) — the venue's own
  commission per lot, and execution-reality slippage observations.

Every component is tagged with its own basis via
:class:`qts.research.costs.CostComponent`. A component whose measurement is
absent stays ``UNKNOWN`` (magnitude 0, ``zero_is_known=True`` is NOT claimed
by silence — the component simply has no measured value) and the resulting
model is not claim-eligible. ``claim_eligible`` is computed by the existing
:meth:`CostModel.claim_eligible` rule: every component MEASURED or the model
is evidence for sensitivity analysis only.

The financing component is DIRECTIONAL: ``direction="long"`` (the frozen
champions' dominant exposure) uses ``swap_long``; ``"short"`` uses
``swap_short``. The unused direction is kept in the provenance block so a
reader can see both broker numbers, not a silent choice.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from qts.research.costs import CostBasis, CostComponent, CostModel


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def commission_per_lot_side(deals: list[Any]) -> tuple[float | None, int]:
    """Median |commission| per lot per side over recorded deals.

    Swap-only postings (volume 0) and deals without a commission field are
    skipped, never zero-filled. Returns (usd_per_lot_side, deals_used).
    """
    ratios: list[float] = []
    for deal in deals:
        volume = _num(getattr(deal, "volume", None))
        commission = _num(getattr(deal, "commission", None))
        if volume is None or volume <= 0 or commission is None:
            continue
        # A deal is one side of a round turn; a true 0.0 commission is a
        # measurement (spread-only account), not a missing value.
        ratios.append(abs(commission) / volume)
    if not ratios:
        return None, 0
    return float(median(ratios)), len(ratios)


def build_measured_cost_model(
    *,
    spread_profile: dict[str, Any] | None = None,
    symbol_terms: dict[str, Any] | None = None,
    deals: list[Any] | None = None,
    slippage_bps: float | None = None,
    direction: str = "long",
    instrument: str = "XAUUSD",
) -> dict[str, Any]:
    """Build the cost model + provenance. Nothing here trades or connects."""
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    provenance: dict[str, Any] = {"inputs": {}, "direction": direction}

    mid: float | None = None
    if symbol_terms:
        bid, ask = _num(symbol_terms.get("bid")), _num(symbol_terms.get("ask"))
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
        provenance["inputs"]["symbol_terms"] = {
            "schema": symbol_terms.get("schema"),
            "observed_at": symbol_terms.get("observed_at"),
            "unavailable_fields": symbol_terms.get("unavailable_fields"),
        }

    # --- spread: profile bps at the terms mid -> price units per lot (1 fill)
    spread_units: float | None = None
    spread_basis = CostBasis.UNKNOWN
    if spread_profile and mid:
        stats = (spread_profile.get("spread_bps") or {})
        p50 = _num(stats.get("p50"))
        if p50 is not None:
            spread_units = p50 / 1e4 * mid
            spread_basis = CostBasis.MEASURED
        provenance["inputs"]["spread_profile"] = {
            "schema": spread_profile.get("schema"),
            "samples_usable": spread_profile.get("samples_usable"),
            "spread_bps_p50": p50,
            "mid_price_used": mid,
        }

    # --- commission: median |commission|/lot over recorded deals (per side)
    commission: float | None = None
    commission_basis = CostBasis.UNKNOWN
    n_deals = 0
    if deals:
        commission, n_deals = commission_per_lot_side(deals)
        if commission is not None:
            commission_basis = CostBasis.MEASURED
    provenance["inputs"]["deals"] = {"deals_used_for_commission": n_deals}

    # --- slippage: reality-store bps at mid -> price units (per fill)
    slippage_units: float | None = None
    slippage_basis = CostBasis.UNKNOWN
    if slippage_bps is not None and mid:
        slippage_units = abs(slippage_bps) / 1e4 * mid
        slippage_basis = CostBasis.MEASURED
        provenance["inputs"]["slippage"] = {"avg_abs_slippage_bps": slippage_bps, "mid_price_used": mid}

    # --- financing: directional swap from symbol terms (per lot per night)
    swap: float | None = None
    swap_basis = CostBasis.UNKNOWN
    if symbol_terms:
        key = f"swap_{direction}_usd_per_lot_night"
        swap = _num(symbol_terms.get(key))
        if swap is not None:
            swap_basis = CostBasis.MEASURED
        swap_long_num = _num(symbol_terms.get("swap_long_usd_per_lot_night"))
        swap_short_num = _num(symbol_terms.get("swap_short_usd_per_lot_night"))
        provenance["inputs"]["swap"] = {
            "direction_used": direction,
            "swap_long_usd_per_lot_night": symbol_terms.get("swap_long_usd_per_lot_night"),
            "swap_short_usd_per_lot_night": symbol_terms.get("swap_short_usd_per_lot_night"),
            "swap_rollover3days": symbol_terms.get("swap_rollover3days"),
            "swap_sign_convention": "mt5_venue_signed (negative = debit/cost to holder, positive = credit to holder)",
            "financing_cost_usd_per_lot_night": round(-swap, 4) if swap is not None else None,
            "financing_cost_bps_per_day_at_mid": (
                round((-swap) / (100.0 * mid) * 1e4, 4) if (swap is not None and mid) else None
            ),
            "financing_long_bps_per_day_at_mid": (
                round((-swap_long_num) / (100.0 * mid) * 1e4, 4) if (swap_long_num is not None and mid) else None
            ),
            "financing_short_bps_per_day_at_mid": (
                round((-swap_short_num) / (100.0 * mid) * 1e4, 4) if (swap_short_num is not None and mid) else None
            ),
        }

    def component(name: str, basis: CostBasis, value: float | None, **kw: Any) -> CostComponent:
        return CostComponent(
            name=name,
            basis=basis,
            source=f"qts.execution.measured_model ({name}: {basis.value})",
            zero_is_known=basis is CostBasis.MEASURED,
            **kw,
        )

    model = CostModel(
        instrument=instrument,
        contract_size=100.0,
        description=(
            "Broker-measured XAUUSD cost model assembled from spread profile, "
            "symbol cost terms and recorded deal evidence (per-component basis)"
        ),
        components=(
            component("spread", spread_basis, spread_units, price_units_per_lot=spread_units or 0.0, fills=1,
                      note="median sampled quoted spread, crossed once per round turn"),
            component("commission", commission_basis, commission, usd_per_lot=commission or 0.0, fills=2,
                      note="median |commission| per lot per side over recorded broker deals"),
            component("slippage", slippage_basis, slippage_units, price_units_per_lot=slippage_units or 0.0,
                      fills=2, note="mean absolute realized slippage, charged per fill"),
            component("financing", swap_basis, swap, usd_per_lot_per_night=swap or 0.0,
                      note=f"directional overnight swap ({direction}) per lot per night from symbol terms"),
        ),
    )
    out = model.as_dict()
    out["provenance"] = provenance
    return out


def assumed_vs_measured_comparison(measured_model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare historical research cost assumptions against measured broker evidence.

    Missing measurements stay explicitly ``UNMEASURED`` with ``value: None`` —
    never substituted with zero or an assumed default.
    """
    comp_map: dict[str, dict[str, Any]] = {}
    if isinstance(measured_model, dict):
        for comp in measured_model.get("components") or []:
            if isinstance(comp, dict) and comp.get("name"):
                comp_map[str(comp["name"])] = comp
    prov_inputs = ((measured_model or {}).get("provenance") or {}).get("inputs") or {}
    spread_in = prov_inputs.get("spread_profile") or {}
    swap_in = prov_inputs.get("swap") or {}
    slip_in = prov_inputs.get("slippage") or {}
    deals_in = prov_inputs.get("deals") or {}

    def _live_status(name: str, val_key: str) -> dict[str, Any]:
        c = comp_map.get(name)
        if not c or c.get("basis") != "MEASURED":
            return {
                "status": "UNMEASURED",
                "basis": c.get("basis", "UNKNOWN") if c else "UNKNOWN",
                "value": None,
                "reason": f"No live DEMO {name} measurement recorded yet — never assumed zero.",
            }
        return {
            "status": "MEASURED",
            "basis": "MEASURED",
            "value": c.get(val_key),
            "source": c.get("source"),
        }

    spread_live = _live_status("spread", "price_units_per_lot")
    if spread_live["status"] == "MEASURED":
        spread_live["spread_bps_p50"] = spread_in.get("spread_bps_p50")
        spread_live["samples_usable"] = spread_in.get("samples_usable")

    comm_live = _live_status("commission", "usd_per_lot")
    if comm_live["status"] == "MEASURED":
        comm_live["deals_used"] = deals_in.get("deals_used_for_commission", 0)

    slip_live = _live_status("slippage", "price_units_per_lot")
    if slip_live["status"] == "MEASURED":
        slip_live["avg_abs_slippage_bps"] = slip_in.get("avg_abs_slippage_bps")

    fin_live = _live_status("financing", "usd_per_lot_per_night")
    if fin_live["status"] == "MEASURED":
        fin_live["swap_long_usd_per_lot_night"] = swap_in.get("swap_long_usd_per_lot_night")
        fin_live["swap_short_usd_per_lot_night"] = swap_in.get("swap_short_usd_per_lot_night")
        fin_live["financing_cost_usd_per_lot_night"] = swap_in.get("financing_cost_usd_per_lot_night")
        fin_live["financing_cost_bps_per_day_at_mid"] = swap_in.get("financing_cost_bps_per_day_at_mid")
        fin_live["swap_rollover3days"] = swap_in.get("swap_rollover3days")

    return {
        "schema": "qts.assumed_vs_measured_costs.v1",
        "claim_eligible": bool((measured_model or {}).get("claim_eligible")),
        "components": {
            "spread": {
                "assumed_longhistory_d1_monthly": {
                    "basis": "ASSUMED",
                    "spread_bps": 3.0,
                    "note": "3.0 bps full width ($0.39/oz at $1,300; $0.795/oz at $2,650)",
                },
                "assumed_intraday_15m": {
                    "basis": "ASSUMED",
                    "spread_usd_per_oz": 0.30,
                    "note": "$0.30/oz ($30/lot round-turn)",
                },
                "historical_quote_archives": {
                    "status": "ARCHIVE_REFERENCE_ONLY",
                    "account_specific": False,
                    "eligible_for_live_cost_gate": False,
                    "note": (
                        "Historical quote archives are not this account's realized execution costs; "
                        "they are excluded from the live cost comparison."
                    ),
                },
                "live_terminal": spread_live,
            },
            "commission": {
                "assumed_longhistory_d1_monthly": {
                    "basis": "ASSUMED",
                    "usd_per_lot_side": 7.0,
                    "usd_per_lot_round_turn": 14.0,
                },
                "assumed_intraday_15m": {
                    "basis": "ASSUMED",
                    "usd_per_lot_side": 0.0,
                    "note": "Spread-only CFD assumption",
                },
                "live_terminal": comm_live,
            },
            "slippage": {
                "assumed_longhistory_d1_monthly": {
                    "basis": "ASSUMED",
                    "slippage_bps_per_side": 1.0,
                    "slippage_bps_round_turn": 2.0,
                },
                "assumed_intraday_15m": {
                    "basis": "ASSUMED",
                    "slippage_usd_per_oz_side": 0.10,
                    "slippage_usd_per_oz_round_turn": 0.20,
                },
                "live_terminal": slip_live,
            },
            "financing": {
                "assumed_longhistory_g9": {
                    "basis": "ASSUMED",
                    "financing_bps_per_day": 0.25,
                    "note": "0.25 bps/calendar day symmetric carry (~0.91%/yr; ~$6.63/lot/night at $2,650 gold)",
                },
                "historical_break_even_reference": {
                    "status": "ARCHIVED_NOT_RECALCULATED",
                    "claim_eligible": False,
                    "note": (
                        "Archived break-even figures are not current account-cost measurements and are not "
                        "recalculated or surfaced in the operator cost summary."
                    ),
                },
                "live_terminal": fin_live,
            },
        },
    }


def reevaluate_frozen_champions(
    measured_model: dict[str, Any] | None = None,
    *,
    monthly_csv_path: Any = None,
    allow_explicit_research_evaluation: bool = False,
) -> dict[str, Any]:
    """Return cost status; run an offline reevaluation only by explicit opt-in.

    The operator API/CLI calls this without an input path or opt-in and therefore
    never opens the repository's historical market-data file. Explicit research
    use requires both a caller-supplied path and
    ``allow_explicit_research_evaluation=True``. A cost-model result alone is
    never a strategy validation or permission to trade.
    """
    from pathlib import Path

    import pandas as pd

    from qts.research.longhistory import engine as ENG
    from qts.research.longhistory import ensemble_signals as ES
    from qts.research.longhistory import hybrid_protocol as HYB
    from qts.research.longhistory import runner as R
    from qts.research.longhistory import stats as ST

    comp_map: dict[str, dict[str, Any]] = {}
    if isinstance(measured_model, dict):
        for comp in measured_model.get("components") or []:
            if isinstance(comp, dict) and comp.get("name"):
                comp_map[str(comp["name"])] = comp

    measured_names = [k for k, v in comp_map.items() if v.get("basis") == "MEASURED"]
    unmeasured_names = [
        k for k in ("spread", "commission", "slippage", "financing") if k not in measured_names
    ]
    claim_eligible = bool((measured_model or {}).get("claim_eligible")) and not unmeasured_names

    out: dict[str, Any] = {
        "schema": "qts.champion_cost_reevaluation.v2",
        "candidates": ["ts9_lo", "veto9"],
        "evaluation_status": "NOT_RUN",
        "evaluation_scope": "EXPLICIT_RESEARCH_INPUT_REQUIRED",
        "retuned": False,
        "claim_eligible": claim_eligible,
        "measured_components": measured_names,
        "unmeasured_components": unmeasured_names,
        "historical_metrics": {
            "status": "ARCHIVED_NOT_SURFACED",
            "claim_eligible": False,
            "note": "Historical evaluation figures are not recalculated or presented as current performance.",
        },
        "claim_grade_measured": None,
        "partial_measurement_sensitivity": None,
        "overall_verdict": "NO_VALIDATED_EDGE",
        "decision_summary": (
            "Unmeasured cost components remain (" + ", ".join(unmeasured_names) + "); "
            "no candidate may be promoted on assumed or partial costs. Overall verdict stays NO_VALIDATED_EDGE."
            if unmeasured_names
            else "All four cost components are MEASURED, but this status request does not run a strategy evaluation. "
            "Overall verdict remains NO_VALIDATED_EDGE."
        ),
    }

    if not measured_names:
        out["evaluation_status"] = "BLOCKED_UNMEASURED_COSTS"
        return out

    if monthly_csv_path is None or not allow_explicit_research_evaluation:
        out["evaluation_status"] = "NOT_RUN_EXPLICIT_OPT_IN_REQUIRED"
        out["decision_summary"] += (
            " Supply an explicitly approved research input and opt in through a governed offline workflow; "
            "the operator API/CLI never loads a default historical dataset."
        )
        return out

    csv_path = Path(monthly_csv_path)
    if not csv_path.is_file():
        out["evaluation_status"] = "EXPLICIT_DATASET_MISSING"
        out["decision_summary"] += " The explicitly supplied research dataset is unavailable; no data were read."
        return out

    raw = pd.read_csv(csv_path)
    idx = pd.to_datetime(raw["date"], utc=True).dt.tz_convert(None)
    bars = raw[["open", "high", "low", "close", "usd"]].astype(float)
    bars.index = pd.DatetimeIndex(idx, name="utc")

    prov_inputs = ((measured_model or {}).get("provenance") or {}).get("inputs") or {}
    spread_in = prov_inputs.get("spread_profile") or {}
    swap_in = prov_inputs.get("swap") or {}
    slip_in = prov_inputs.get("slippage") or {}

    spread_bps = (
        float(spread_in["spread_bps_p50"])
        if "spread" in measured_names and spread_in.get("spread_bps_p50") is not None
        else HYB.COST_BASE.spread_bps
    )
    slip_bps = (
        abs(float(slip_in["avg_abs_slippage_bps"]))
        if "slippage" in measured_names and slip_in.get("avg_abs_slippage_bps") is not None
        else HYB.COST_BASE.slippage_bps
    )
    comm_usd = (
        float(comp_map["commission"]["usd_per_lot"])
        if "commission" in measured_names and comp_map["commission"].get("usd_per_lot") is not None
        else HYB.COST_BASE.commission_usd_per_lot_side
    )
    fin_long_bps = (
        float(swap_in["financing_long_bps_per_day_at_mid"])
        if "financing" in measured_names and swap_in.get("financing_long_bps_per_day_at_mid") is not None
        else (
            float(swap_in["financing_cost_bps_per_day_at_mid"])
            if "financing" in measured_names and swap_in.get("financing_cost_bps_per_day_at_mid") is not None
            else HYB.FINANCING_BPS_PER_DAY
        )
    )
    fin_short_bps = (
        float(swap_in["financing_short_bps_per_day_at_mid"])
        if "financing" in measured_names and swap_in.get("financing_short_bps_per_day_at_mid") is not None
        else fin_long_bps
    )

    engine_cost = ENG.CostModel(
        spread_bps=max(0.0, spread_bps),
        slippage_bps=max(0.0, slip_bps),
        commission_usd_per_lot_side=max(0.0, comm_usd),
        financing_bps_per_day=max(0.0, fin_long_bps),
        basis="MEASURED" if claim_eligible else "PARTIAL_MEASURED_SENSITIVITY",
        financing_long_bps_per_day=fin_long_bps,
        financing_short_bps_per_day=fin_short_bps,
    )

    p_ts9 = ES.tsmom_single(bars, lookback=9, long_only=True, vol_n=12, ann=12)
    p_veto9 = ES.ensemble_usd_veto(bars, lookbacks=(9,), usd_lb=12, vol_n=12, ann=12)
    r_ts9 = R.run_window(bars, p_ts9, "2000-01-01", "2026-09-30", engine_cost)
    r_veto9 = R.run_window(bars, p_veto9, "2000-01-01", "2026-09-30", engine_cost)
    s_ts9: dict[str, Any] = ST.summarize(r_ts9, periods_per_year=12)
    s_veto9: dict[str, Any] = ST.summarize(r_veto9, periods_per_year=12)

    eval_payload: dict[str, Any] = {
        "cost_model_used": engine_cost.describe(),
        "ts9_lo": {
            "net_usd": round(float(s_ts9["net_usd"]), 2),
            "gross_usd": round(float(r_ts9.gross_usd), 2),
            "fill_cost_usd": round(float(r_ts9.cost_usd), 2),
            "financing_usd": round(float(r_ts9.financing_usd), 2),
            "sharpe": round(float(s_ts9["sharpe"]), 4),
            "max_drawdown": round(float(s_ts9["max_drawdown"]), 4),
            "round_turns": int(s_ts9["round_turns"]),
            "financed_positive_g9": bool(s_ts9["net_usd"] > 0),
        },
        "veto9": {
            "net_usd": round(float(s_veto9["net_usd"]), 2),
            "gross_usd": round(float(r_veto9.gross_usd), 2),
            "fill_cost_usd": round(float(r_veto9.cost_usd), 2),
            "financing_usd": round(float(r_veto9.financing_usd), 2),
            "sharpe": round(float(s_veto9["sharpe"]), 4),
            "max_drawdown": round(float(s_veto9["max_drawdown"]), 4),
            "round_turns": int(s_veto9["round_turns"]),
            "financed_positive_g9": bool(s_veto9["net_usd"] > 0),
        },
    }

    out["evaluation_status"] = "EXPLICIT_INPUT_EVALUATED"
    if claim_eligible:
        out["claim_grade_measured"] = eval_payload
        both_pos = eval_payload["ts9_lo"]["financed_positive_g9"] and eval_payload["veto9"]["financed_positive_g9"]
        out["decision_summary"] = (
            f"All 4 cost components MEASURED (financing_long={fin_long_bps:.3f} bps/day, "
            f"financing_short={fin_short_bps:.3f} bps/day). "
            f"ts9_lo net=${eval_payload['ts9_lo']['net_usd']:,.2f} (SR {eval_payload['ts9_lo']['sharpe']:.3f}), "
            f"veto9 net=${eval_payload['veto9']['net_usd']:,.2f} (SR {eval_payload['veto9']['sharpe']:.3f}). "
            f"G9 financing gate: {'PASS' if both_pos else 'FAIL'}. "
            "Overall promotion verdict remains NO_VALIDATED_EDGE pending 24-36 months of forward out-of-sample observation (gates G3/G5/G6)."
        )
    else:
        out["partial_measurement_sensitivity"] = eval_payload
    return out
