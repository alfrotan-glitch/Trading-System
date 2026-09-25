"""API routes — paper, shadow, and execution evidence."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from qts.config.paths import artifact_path

router = APIRouter()


def _bind():
    """Late lookup so tests can patch seams on ``qts.api.server``."""
    import qts.api.server as server

    return server


@router.get("/api/paper")
def paper_center() -> dict[str, Any]:
    ev_path = artifact_path("paper_trades")
    paper: dict[str, Any] = (
        json.loads(ev_path.read_text(encoding="utf-8"))
        if ev_path.exists()
        else {"fills": [], "positions": [], "pnl": 0, "drawdown": 0}
    )
    return {
        "simulated_positions": paper.get("fills", [])[:10],
        "fills": paper.get("fills", []),
        "pnl": paper.get("pnl", 0),
        "drawdown": paper.get("drawdown", 0),
        "execution_statistics": {
            "total_fills": len(paper.get("fills", [])),
            # PAPER fills are MODEL expectations — slippage is modeled, never
            # observed. The old fabricated 1.5 bps placeholder is removed.
            "avg_slippage_bps": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "slippage is a MODEL assumption for paper fills; observed slippage is UNAVAILABLE because DEMO_EXECUTION is disabled and OBSERVE_ONLY submits no orders",
            },
            "label": "PAPER",
        },
    }




@router.get("/api/shadow")
def shadow_center() -> dict[str, Any]:
    shadow_path = artifact_path("shadow_intents")
    paper_path = artifact_path("paper_trades")
    shadow = (
        json.loads(shadow_path.read_text(encoding="utf-8"))
        if shadow_path.exists()
        else {"intents_sample": [], "skipped": []}
    )
    paper = json.loads(paper_path.read_text(encoding="utf-8")) if paper_path.exists() else {"fills": []}
    # compute discrepancy if both exist
    disc = None
    if shadow_path.exists() and paper_path.exists():
        try:
            from qts.edge.execution_consistency import compare_shadow_paper

            res = compare_shadow_paper(shadow.get("intents_sample", []), paper.get("fills", []), [])
            disc = res.__dict__
        except Exception as e:
            disc = {"error": str(e)}
    return {
        "intent_count": len(shadow.get("intents_sample", [])),
        "would_be_trades": shadow.get("intents_sample", [])[:10],
        "estimated_fills": shadow.get("would_be_fills", [])[:10] if isinstance(shadow, dict) else [],
        "skipped_trades": shadow.get("skipped", [])[:10] if isinstance(shadow, dict) else [],
        # Divergence reasons are not inferred. The comparison result does not
        # record why intents and fills differ; inventing "spread limit" / "risk
        # veto" turned every comparison into a fabricated explanation.
        "reasons": {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": "the comparison does not record why intents and fills diverged; reasons are not inferred",
        },
        "shadow_vs_paper_discrepancy": disc,
    }




@router.get("/api/execution/orders")
def execution_orders(limit: int = 20) -> list[dict[str, Any]]:
    try:
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=limit)
        orders = []
        for e in events:
            if "order" in e.event_type.value.lower() or "execution" in json.dumps(e.payload).lower():
                orders.append(
                    {
                        "time": e.event_time.isoformat(),
                        "type": e.event_type.value,
                        "payload": e.payload,
                        "lifecycle": "INTENT→RISK→SUBMISSION→ACCEPTED→FILLED or REJECTED/CANCELLED/AMBIGUOUS",
                    }
                )
        return orders[:limit]
    except Exception as e:
        return [{"error": str(e)}]




@router.get("/api/execution/orders/{order_id}")
def order_audit(order_id: str) -> dict[str, Any]:
    try:
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=200)
        matched = [e for e in events if order_id in json.dumps(e.payload)]
        if not matched:
            raise HTTPException(404, "order not found")
        return {
            "order_id": order_id,
            "trail": [
                {"time": e.event_time.isoformat(), "type": e.event_type.value, "payload": e.payload} for e in matched
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)) from e



