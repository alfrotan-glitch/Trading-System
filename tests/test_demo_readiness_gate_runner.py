"""Tests for scripts/demo_readiness_gate.py — the executable Demo Readiness Gate.

The runner must be a pure sequencer: every verdict it prints has to come from
the product's responses, it must halt at the first failing step, and it must
never mistake "unreadable" for "flat" or "refused" for "done".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "demo_readiness_gate", REPO_ROOT / "scripts" / "demo_readiness_gate.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_readiness_gate"] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


# ---------------------------------------------------------------------------
# Canned canonical responses
# ---------------------------------------------------------------------------

GREEN: dict[tuple[str, str], tuple[int, Any]] = {
    ("GET", "/api/demo/config"): (200, {"mode": "DEMO_EXECUTION", "mode_source": "QTS_MODE=demo_execution"}),
    ("GET", "/api/mt5"): (200, {"connected": True}),
    ("GET", "/api/demo/readiness"): (200, {"passed": True, "blocked_reasons": []}),
    ("GET", "/api/demo/guide"): (
        200,
        {
            "connection": {"connected": True, "broker": "B", "server": "S", "login": 1, "account_type": "demo"},
            "identity": {"verified": True},
            "quote": {"fresh": True, "bid": 2000.0, "ask": 2000.3},
            "reconciliation": {"clean": True, "suspended": False},
            "suspension": {"active_blockers": []},
        },
    ),
    ("GET", "/api/risk"): (200, {"kill_switch_detail": {"killed": False, "source": "durable:risk_state"}}),
    ("POST", "/api/demo/order"): (
        200,
        {
            "allowed": True,
            "client_order_id": "demo-x",
            "journal_id": 7,
            "broker_order_id": 111,
            "broker_position_id": 222,
            "state": "FILLED",
        },
    ),
    ("GET", "/api/demo/positions"): (
        200,
        {"positions": [{"ticket": 222, "side": "BUY", "volume": 0.01, "price_open": 2000.3, "journal_id": 7}], "count": 1},
    ),
    ("POST", "/api/demo/close"): (
        200,
        {"success": True, "ticket": 222, "realized_pnl": "-0.10", "reconciliation": {"requires_suspend": False}},
    ),
    ("GET", "/api/demo/journal"): (200, {"orders": [{"journal_id": 7, "state": "CLOSED"}]}),
}


def make_fetch(overrides: dict[tuple[str, str], Any] | None = None, sequences: dict[tuple[str, str], list[Any]] | None = None):
    """Fetch over canned responses; ``sequences`` yields per-call responses in order."""
    calls: list[tuple[str, str]] = []
    seq_state = {k: list(v) for k, v in (sequences or {}).items()}

    def fetch(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        key = (method, path)
        calls.append(key)
        if key in seq_state and seq_state[key]:
            return seq_state[key].pop(0)
        table = dict(GREEN)
        table.update(overrides or {})
        return table[key]

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def args(**kw: Any):
    import argparse

    base = {
        "base_url": "http://test",
        "execute": False,
        "side": "BUY",
        "quantity": "0.01",
        "stop_loss": "1995.00",
        "rationale": "test",
        "record": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# Halts
# ---------------------------------------------------------------------------


def test_halts_at_step1_when_mode_is_not_demo_execution():
    fetch = make_fetch({("GET", "/api/demo/config"): (200, {"mode": "DEVELOPMENT", "mode_source": "default"})})
    verdict, results = runner.run_gate(fetch, args())
    assert verdict == "ENVIRONMENT BLOCKED"
    assert [r.step for r in results] == [1]
    assert "QTS_MODE=demo_execution" in results[0].failures[0]


def test_halts_at_step2_when_terminal_absent():
    fetch = make_fetch(
        {
            ("GET", "/api/mt5"): (200, {"connected": False, "health": {"error": "MetaTrader5 package not installed"}}),
            ("GET", "/api/demo/readiness"): (200, {"passed": False, "blocked_reasons": ["MT5 not installed"]}),
            ("GET", "/api/demo/guide"): (
                200,
                {
                    "connection": {"connected": False},
                    "identity": {"verified": False, "detail": "not recorded"},
                    "quote": {"fresh": False, "bid": None, "ask": None},
                },
            ),
        }
    )
    verdict, results = runner.run_gate(fetch, args())
    assert verdict == "ENVIRONMENT BLOCKED"
    assert results[-1].step == 2
    joined = " ".join(results[-1].failures)
    assert "MetaTrader5 package not installed" in joined
    assert "MT5 not installed" in joined
    # steps 3+ never probed
    assert ("GET", "/api/risk") not in fetch.calls


def test_halts_at_step3_on_durable_blockers_without_touching_order_path():
    guide = json.loads(json.dumps(GREEN[("GET", "/api/demo/guide")][1]))
    guide["reconciliation"] = {"clean": False, "suspended": True, "suspended_reason": "broker disconnect"}
    guide["suspension"] = {
        "active_blockers": [
            {"id": "reconciliation_suspension", "detail": "broker disconnect", "recoverable_by": "a fresh clean reconciliation"}
        ]
    }
    fetch = make_fetch({("GET", "/api/demo/guide"): (200, guide)})
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "GATE BLOCKED"
    assert results[-1].step == 3
    assert ("POST", "/api/demo/order") not in fetch.calls


def test_refused_order_is_a_halt_with_server_reasons():
    fetch = make_fetch(
        {("POST", "/api/demo/order"): (409, {"allowed": False, "state": "NO_TRADE", "reasons": ["broker_order_check: refused"]})}
    )
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "GATE BLOCKED"
    assert results[-1].step == 4
    assert results[-1].failures == ["broker_order_check: refused"]
    assert ("GET", "/api/demo/positions") not in fetch.calls


def test_allowed_order_without_broker_ids_is_a_halt():
    out = dict(GREEN[("POST", "/api/demo/order")][1])
    out["broker_position_id"] = None
    fetch = make_fetch({("POST", "/api/demo/order"): (200, out)})
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "GATE BLOCKED"
    assert results[-1].step == 4
    assert "IDs were not captured" in results[-1].failures[0]


def test_positions_503_after_order_is_a_halt_not_a_retry():
    fetch = make_fetch(
        sequences={("GET", "/api/demo/positions"): [(503, {"detail": "broker positions UNAVAILABLE"})]}
    )
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "GATE BLOCKED"
    assert results[-1].step == 5
    assert "HALT, not a retry" in results[-1].failures[0]
    assert fetch.calls.count(("GET", "/api/demo/positions")) == 1
    assert ("POST", "/api/demo/close") not in fetch.calls


# ---------------------------------------------------------------------------
# Pass paths
# ---------------------------------------------------------------------------


def test_verify_mode_passes_without_touching_any_mutating_endpoint():
    fetch = make_fetch()
    verdict, results = runner.run_gate(fetch, args(execute=False))
    assert verdict == "VERIFY PASS"
    assert [r.step for r in results] == [1, 2, 3]
    assert all(method == "GET" for method, _ in fetch.calls)


def test_full_green_run_is_demo_ready_with_broker_evidence(tmp_path):
    # after close, broker is flat
    fetch = make_fetch(
        sequences={
            ("GET", "/api/demo/positions"): [
                GREEN[("GET", "/api/demo/positions")],
                (200, {"positions": [], "count": 0}),
            ]
        }
    )
    a = args(execute=True)
    verdict, results = runner.run_gate(fetch, a)
    assert verdict == "DEMO READY"
    assert [r.step for r in results] == [1, 2, 3, 4, 5, 6, 7]
    order = results[3]
    assert order.evidence["broker_order_id"] == 111
    assert order.evidence["broker_position_id"] == 222
    final = results[6]
    assert final.evidence == {"verified_flat": True, "journal": {"journal_id": 7, "state": "CLOSED"}, "reconciliation_clean": True}

    record = tmp_path / "record.json"
    runner.write_record(record, verdict, results, a)
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["schema"] == "qts.demo_readiness_gate_record.v1"
    assert data["verdict"] == "DEMO READY"
    assert len(data["steps"]) == 7


# ---------------------------------------------------------------------------
# Readiness-evidence renewal is canonical product behavior (the backend
# re-proves decayed evidence inside the order request itself). The runner is
# a pure sequencer: it must NOT perform any client-side refresh bookkeeping.
# ---------------------------------------------------------------------------


def test_execute_makes_no_client_side_refresh_call():
    """The runner never manages readiness evidence — the backend does."""
    fetch = make_fetch(
        sequences={
            ("GET", "/api/demo/positions"): [
                GREEN[("GET", "/api/demo/positions")],
                (200, {"positions": [], "count": 0}),
            ]
        }
    )
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "DEMO READY"
    assert ("POST", "/api/demo/guide/refresh") not in fetch.calls
    order = results[3]
    assert "reverified" not in order.evidence


def test_verify_pass_then_immediate_execute_uses_fresh_evidence():
    """The literal field sequence: VERIFY PASS, then --execute seconds later.

    The fake backend models the canonical authority: its stored readiness
    evidence is STALE (last preparation 284s ago), and the ORDER request
    itself — explicit confirmed+risk_ack operator intent — is what renews
    it, backend-side, through a fresh durably-recorded probe. The runner
    passes end-to-end without ever calling a client-side refresh.
    """
    state = {"evidence_fresh": False}

    def fetch(method: str, path: str, payload: dict[str, Any] | None = None):
        assert (method, path) != ("POST", "/api/demo/guide/refresh"), (
            "the runner must not manage readiness evidence client-side"
        )
        if (method, path) == ("POST", "/api/demo/order"):
            # Canonical backend behavior: the order request re-proves
            # decayed evidence itself before any gate judges.
            assert payload and payload.get("confirmed") is True and payload.get("risk_ack") is True
            state["evidence_fresh"] = True
            return GREEN[("POST", "/api/demo/order")]
        if (method, path) == ("GET", "/api/demo/positions") and state.get("closed"):
            return (200, {"positions": [], "count": 0})
        if (method, path) == ("POST", "/api/demo/close"):
            state["closed"] = True
            return GREEN[("POST", "/api/demo/close")]
        return GREEN[(method, path)]

    # 1. VERIFY PASS — read-only, renews nothing (and must not).
    verdict, _ = runner.run_gate(fetch, args(execute=False))
    assert verdict == "VERIFY PASS"
    assert state["evidence_fresh"] is False

    # 2. Immediate --execute: the backend renews evidence inside the order.
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "DEMO READY"
    assert [r.step for r in results] == [1, 2, 3, 4, 5, 6, 7]


def test_failed_backend_reproof_refuses_the_order_with_its_reasons():
    """Fail-closed: when the backend's fresh re-proof fails, the order
    refuses with the probe's own reasons and the runner halts at step 4."""
    fetch = make_fetch(
        {
            ("POST", "/api/demo/order"): (
                409,
                {
                    "allowed": False,
                    "state": "NO_TRADE",
                    "reasons": [
                        "execution_permission: durable DEMO authority refuses execution: "
                        "fresh readiness failed: Market data not fresh"
                    ],
                },
            )
        }
    )
    verdict, results = runner.run_gate(fetch, args(execute=True))
    assert verdict == "GATE BLOCKED"
    assert results[-1].step == 4
    assert "Market data not fresh" in " ".join(results[-1].failures)
    assert ("POST", "/api/demo/guide/refresh") not in fetch.calls


def test_main_requires_explicit_size_for_execute(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        runner.main(["--execute"])
    assert exc.value.code == 2
    assert "--quantity" in capsys.readouterr().err


def test_omitted_stop_loss_defers_to_the_canonical_policy_derivation():
    """No --stop-loss ⇒ the order payload carries NO stop_loss key at all.

    The registered policy derives the stop at order time at exactly its
    declared distance; a runner-injected stale price would race the quote
    and land wider than the policy cap. The runner must therefore forward a
    stop ONLY when the operator explicitly chose one.
    """
    def run(stop_loss: str | None) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        def fetch(method: str, path: str, payload: dict[str, Any] | None = None):
            if (method, path) == ("POST", "/api/demo/order"):
                seen["order_payload"] = payload
            if (method, path) == ("GET", "/api/demo/positions") and seen.get("closed"):
                return (200, {"positions": [], "count": 0})
            if (method, path) == ("POST", "/api/demo/close"):
                seen["closed"] = True
            return GREEN[(method, path)]

        verdict, _ = runner.run_gate(fetch, args(execute=True, stop_loss=stop_loss))
        assert verdict == "DEMO READY"
        return seen["order_payload"]

    assert "stop_loss" not in run(None)
    # And an explicit operator stop IS forwarded verbatim.
    assert run("1995.00")["stop_loss"] == "1995.00"
