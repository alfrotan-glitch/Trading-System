"""API routes — market observation."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException

from qts.api.deps import (
    _resolve_observe_symbol,
    _wizard_setup_kwargs,
)

router = APIRouter()


def _bind():
    """Late lookup so tests can patch seams on ``qts.api.server``."""
    import qts.api.server as server

    return server


@router.post("/api/observe/start")
def observe_start(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start OBSERVE-ONLY collection of REAL MT5 ticks. Zero orders.

    Refuses unless DEMO readiness passes (14/14). Idempotent: repeated start
    returns the running session instead of creating a duplicate collector.
    The collector only reaches market-data APIs; order_send is not on any
    code path (pinned by tests/test_observe_only_collector.py).
    """

    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    body = payload if isinstance(payload, dict) else {}
    try:
        interval_s = float(body.get("interval_s", os.getenv("QTS_OBSERVE_INTERVAL_S", "1.0")))
    except (TypeError, ValueError):
        raise HTTPException(400, "interval_s must be a number") from None
    with _bind()._OBSERVE_LOCK:
        existing = _bind()._OBSERVE_STATE.get("collector")
        if existing is not None and existing.state == "OBSERVING":
            return {"started": False, "reason": "already_running", "status": existing.status()}
    # readiness OUTSIDE the lock so /api/observe/status stays responsive
    setup = _wizard_setup_kwargs(None, None)
    readiness = demo_forward_readiness_report(**setup)
    requested, broker = _resolve_observe_symbol(setup)
    with _bind()._OBSERVE_LOCK:  # double-check: a concurrent start may have won the race
        existing = _bind()._OBSERVE_STATE.get("collector")
        if existing is not None and existing.state == "OBSERVING":
            return {"started": False, "reason": "already_running", "status": existing.status()}
        collector = _bind()._build_observe_collector(setup.get("terminal_path"), requested, broker, interval_s)
        # start() refuses internally unless readiness passed -> state BLOCKED is
        # recorded in the collector so /api/observe/status surfaces it to the UI.
        status = collector.start(readiness)
        _bind()._OBSERVE_STATE["collector"] = collector
        resp: dict[str, Any] = {"started": status["state"] == "OBSERVING", "status": status}
        if not resp["started"]:
            resp["note"] = "OBSERVE-ONLY refused: DEMO readiness must pass all 14 checks (fail-closed)"
        return resp




@router.get("/api/observe/status")
def observe_status() -> dict[str, Any]:
    """Operator status: OBSERVING / STOPPED / BLOCKED / STOPPED_ON_ERRORS + counters."""
    with _bind()._OBSERVE_LOCK:
        collector = _bind()._OBSERVE_STATE.get("collector")
        if collector is None:
            return {
                "state": "STOPPED",
                "mode": "OBSERVE_ONLY",
                "orders_submitted": 0,
                "ticks_recorded": 0,
                "note": "no observation session has been started",
            }
        return collector.status()




@router.post("/api/observe/stop")
def observe_stop() -> dict[str, Any]:
    """Deterministic stop: thread join, persisted session end, final manifest."""
    with _bind()._OBSERVE_LOCK:
        collector = _bind()._OBSERVE_STATE.get("collector")
        if collector is None:
            return {"stopped": False, "status": {"state": "STOPPED", "ticks_recorded": 0}}
        if collector.state != "OBSERVING":
            return {"stopped": False, "status": collector.status()}
        return {"stopped": True, "status": collector.stop()}



