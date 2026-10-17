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
        provenance["inputs"]["swap"] = {
            "direction_used": direction,
            "swap_long_usd_per_lot_night": symbol_terms.get("swap_long_usd_per_lot_night"),
            "swap_short_usd_per_lot_night": symbol_terms.get("swap_short_usd_per_lot_night"),
            "swap_rollover3days": symbol_terms.get("swap_rollover3days"),
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
