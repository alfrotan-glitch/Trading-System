"""Every refused DEMO order explains itself, in plain language, at the API.

Before this, the API returned the gate's verdict and the browser guessed a
sentence from a hand-written dictionary of eleven entries — for twenty-eight
predicates. Everything unmatched rendered as:

    "A safety check refused the order. See the technical details for the exact reason."

The system knew precisely which predicate had refused and told the operator
nothing actionable. These tests pin the repaired contract:

* the refusal object is built server-side, next to the gate;
* every predicate the gate can emit has a plain sentence AND a retry condition;
* refusals raised outside the gate name their predicate too;
* an unidentifiable refusal says so and never invents a cause;
* HTTP 409 and the refusal itself are untouched — only the explanation changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["test_demo_api"]

SRC = Path(__file__).resolve().parents[1] / "src" / "qts"


# --------------------------------------------------------------- completeness
def _emitted_predicate_names() -> set[str]:
    """Every name that can reach ``record()`` — including the dynamic ones.

    A regex/AST scan for ``record("literal")`` is NOT sufficient: five
    predicates are emitted as ``record(*_helper(...))`` and were completely
    invisible to the first version of this test, which passed while
    ``symbol_mapping_canonical``, ``order_size_within_hard_max``,
    ``stop_loss_present``, ``stop_within_policy_distance`` and
    ``max_total_exposure`` had no operator-facing explanation at all.

    So: collect the literal names AND the names returned by every helper that
    is splatted into ``record``.
    """
    import ast

    tree = ast.parse((SRC / "execution" / "demo_pretrade.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    helper_names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "record"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
        elif isinstance(first, ast.Starred) and isinstance(first.value, ast.Call):
            func = first.value.func
            if isinstance(func, ast.Name):
                helper_names.add(func.id)
    # every string literal returned first-position by those helpers
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in helper_names:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Tuple) and inner.value.elts:
                    head = inner.value.elts[0]
                    if isinstance(head, ast.Constant) and isinstance(head.value, str):
                        names.add(head.value)
    assert helper_names, "no helper-emitted predicates found — the scan is broken"
    return names


def test_every_gate_predicate_has_a_plain_explanation():
    """A new safeguard cannot ship without an operator-facing sentence."""
    from qts.execution.demo_refusal import missing_explanations

    predicates = sorted(_emitted_predicate_names())
    assert len(predicates) >= 30, f"predicate discovery looks wrong: {predicates}"
    missing = missing_explanations(predicates)
    assert missing == [], (
        "these pre-trade predicates would fall back to the generic "
        f"'a safety check refused the order' message: {missing}"
    )


def test_the_gate_refuses_to_emit_an_unregistered_predicate():
    """Runtime enforcement — the guarantee a static scan cannot give.

    This is what actually caught the five helper-emitted predicates.
    """
    from qts.execution import demo_pretrade

    ctx = demo_pretrade.DemoPretradeContext()
    with pytest.raises(KeyError, match="canonical registry"):
        # drive one gate run with a predicate name that has no explanation
        original = demo_pretrade.REFUSAL_EXPLANATIONS
        try:
            demo_pretrade.REFUSAL_EXPLANATIONS = {}
            demo_pretrade.run_pretrade_gate(ctx)
        finally:
            demo_pretrade.REFUSAL_EXPLANATIONS = original


def test_every_explanation_states_a_retry_condition():
    from qts.execution.demo_refusal import REFUSAL_EXPLANATIONS

    for check_id, (plain, retry_when) in REFUSAL_EXPLANATIONS.items():
        assert plain.strip() and plain.endswith("."), check_id
        assert retry_when.strip() and retry_when.endswith("."), check_id
        # The plain sentence must not leak the predicate id at the user.
        assert check_id not in plain, f"{check_id}: plain text leaks the identifier"


def test_the_ui_no_longer_guesses_the_sentence():
    """The browser must render the server's refusal, not a local dictionary."""
    js = (SRC / "desktop" / "ui" / "js" / "views" / "trading.js").read_text(encoding="utf-8")
    assert "humanRefusal" not in js, "the client-side guess is back"
    assert "A safety check refused the order" not in js, "the generic fallback sentence is back"
    assert "r.primary" in js, "the view must render the server-built refusal"


# ------------------------------------------------------------ the builder
@pytest.mark.parametrize(
    ("check_id", "expect_phrase"),
    [
        ("trading_hours_allowed", "outside the permitted trading hours"),
        ("market_data_fresh", "no fresh price"),
        ("reconciliation_ready", "disagree about open positions"),
        ("kill_switch_functional", "stopped by the safety stop"),
        ("max_daily_loss", "loss has reached the limit"),
        ("broker_order_check", "broker refused"),
        ("stage_allows_order", "not been prepared"),
        ("policy_execution_assumptions", "outside what this trading plan assumed"),
    ],
)
def test_each_refusal_category_produces_its_own_sentence(check_id, expect_phrase):
    """Readiness, hours, suspension, freshness, risk and broker each differ."""
    from qts.execution.demo_refusal import explain_refusal

    verdict = {
        "failed": [check_id],
        "unknown": [],
        "checks": {check_id: {"name": check_id, "status": "FAIL", "detail": "age 3833.7s > 60s"}},
    }
    refusal = explain_refusal(verdict=verdict, reasons=[f"{check_id}: age 3833.7s > 60s"])

    assert refusal["allowed"] is False
    assert refusal["explanation_available"] is True
    assert refusal["primary"]["id"] == check_id
    assert expect_phrase in refusal["primary"]["plain"].lower()
    assert refusal["primary"]["retry_when"]
    # current value and technical detail are preserved, separately
    assert refusal["primary"]["current"] == "age 3833.7s > 60s"
    assert "3833.7" in refusal["primary"]["technical"]


def test_an_unidentifiable_refusal_says_so_and_invents_nothing():
    from qts.execution.demo_refusal import explain_refusal

    refusal = explain_refusal(reasons=["something went sideways"])
    assert refusal["allowed"] is False
    assert refusal["explanation_available"] is False
    assert "could not identify" in refusal["primary"]["plain"]
    assert "NOT been sent" in refusal["primary"]["plain"]
    assert refusal["primary"]["technical"] == "something went sideways"
    # no fabricated cause
    assert "trading hours" not in refusal["primary"]["plain"].lower()


def test_all_failed_predicates_are_reported_not_only_the_first():
    from qts.execution.demo_refusal import explain_refusal

    failed = ["stage_allows_order", "trading_hours_allowed", "reconciliation_ready"]
    verdict = {
        "failed": failed,
        "unknown": [],
        "checks": {f: {"name": f, "status": "FAIL", "detail": f"{f} detail"} for f in failed},
    }
    refusal = explain_refusal(verdict=verdict, reasons=[f"{f}: x" for f in failed])
    assert refusal["blocker_ids"] == failed
    assert refusal["primary"]["id"] == "stage_allows_order"
    assert all(b["explained"] for b in refusal["blockers"])


# ------------------------------------------------------- end-to-end at the API
def _seed_registry(api_env):
    """The registry the armed session resolves its entry from."""
    import json

    import fakes_demo_provider as provider_fixture

    (Path(api_env) / "registry.json").write_text(
        json.dumps(
            {
                "schema": "qts.demo_forward_registry.v1",
                "research_integrity": {"optimization_allowed": False, "no_forward_fitting": True},
                "entries": [provider_fixture.registry_entry()],
            }
        ),
        encoding="utf-8",
    )


def _order(client, **over):
    body = {"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True}
    body.update(over)
    return client.post("/api/demo/order", json=body)


def test_a_real_409_carries_the_concrete_reason_to_the_ui(client, api_env, monkeypatch):
    """The whole path: gate verdict -> route -> HTTP 409 body -> UI fields."""
    from fakes_mt5_demo import FakeTerminal
    from test_demo_api import _armed_session

    import qts.api.server as server_module

    _seed_registry(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    monkeypatch.setattr(server_module, "_demo_session", lambda *a, **k: session)

    # A real, current predicate failure: the plan's trading window is closed.
    from qts.execution import demo_pretrade

    real_gate = demo_pretrade.run_pretrade_gate

    def gate_with_closed_market(ctx):
        verdict = real_gate(ctx)
        checks = dict(verdict.checks)
        checks["trading_hours_allowed"] = demo_pretrade.CheckResult(
            name="trading_hours_allowed",
            status=demo_pretrade.CHECK_FAIL,
            detail="now 03:14 UTC is outside the policy window 07:00-20:00 UTC",
        )
        failed = [n for n, c in checks.items() if c.status == demo_pretrade.CHECK_FAIL]
        return demo_pretrade.PretradeVerdict(
            passed=False,
            checks=checks,
            reasons=[f"{n}: {checks[n].detail}" for n in failed],
        )

    monkeypatch.setattr(demo_pretrade, "run_pretrade_gate", gate_with_closed_market)
    monkeypatch.setattr("qts.execution.demo_session.run_pretrade_gate", gate_with_closed_market)

    res = _order(client)

    # 10. HTTP semantics unchanged: still refused, still 409.
    assert res.status_code == 409
    body = res.json()
    assert body["allowed"] is False

    refusal = body["refusal"]
    assert refusal["primary"]["id"] == "trading_hours_allowed"
    assert refusal["primary"]["plain"] == "Trading session is outside the permitted trading hours."
    assert refusal["primary"]["retry_when"] == "The market/trading window is open."
    # the operator sees the actual value, and the technical text stays separate
    assert "03:14 UTC" in refusal["primary"]["current"]
    assert refusal["explanation_available"] is True
    # and the raw verdict is still there for Advanced
    assert body["verdict"]["checks"]["trading_hours_allowed"]["status"] == "FAIL"
    assert terminal.requests == [], "no order may be sent while refusing"


def test_a_refusal_raised_outside_the_gate_is_explained_too(client, api_env, monkeypatch):
    """The stage guard has no verdict — it must still name its predicate."""
    from fakes_mt5_demo import FakeTerminal
    from test_demo_api import _armed_session

    import qts.api.server as server_module

    _seed_registry(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    monkeypatch.setattr(server_module, "_demo_session", lambda *a, **k: session)

    from qts.execution.demo_session import SubmissionResult

    def refuse_on_stage(*a, **k):
        return SubmissionResult(
            allowed=False,
            state="NO_TRADE",
            reasons=["stage HALTED does not permit orders"],
            blocked_by="stage_allows_order",
        )

    monkeypatch.setattr(session, "submit", refuse_on_stage)

    res = _order(client)
    assert res.status_code == 409
    refusal = res.json()["refusal"]
    assert refusal["primary"]["id"] == "stage_allows_order"
    assert "not been prepared" in refusal["primary"]["plain"]
    assert refusal["explanation_available"] is True
    assert "HALTED" in refusal["primary"]["technical"]


def test_an_internal_error_stays_fail_closed_and_admits_the_unknown(client, api_env, monkeypatch):
    """Requirement 6: never invent a reason for an internal failure."""
    from fakes_mt5_demo import FakeTerminal
    from test_demo_api import _armed_session

    import qts.api.server as server_module

    _seed_registry(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    monkeypatch.setattr(server_module, "_demo_session", lambda *a, **k: session)

    from qts.execution.demo_session import SubmissionResult

    monkeypatch.setattr(
        session,
        "submit",
        lambda *a, **k: SubmissionResult(
            allowed=False,
            state="REJECTED",
            reasons=["submission error: RuntimeError: disk on fire"],
            blocked_by="submission_error",
        ),
    )

    res = _order(client)
    assert res.status_code == 409
    refusal = res.json()["refusal"]
    assert refusal["primary"]["id"] == "submission_error"
    assert "internal error" in refusal["primary"]["plain"]
    assert "nothing was sent" in refusal["primary"]["plain"].lower()
    assert "disk on fire" in refusal["primary"]["technical"]


def test_the_no_strategy_409_is_explained(client, api_env, monkeypatch):
    """This route returns 409 without ever building a SubmissionResult."""
    from fakes_mt5_demo import FakeTerminal
    from test_demo_api import _armed_session

    import qts.api.server as server_module

    _seed_registry(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    monkeypatch.setattr(server_module, "_demo_session", lambda *a, **k: session)
    # the route imports resolve_entry per call, so patch it at the source
    monkeypatch.setattr(
        "qts.lifecycle.demo_registry.resolve_entry", lambda *a, **k: (None, ["registry empty"])
    )

    res = _order(client)
    assert res.status_code == 409
    refusal = res.json()["refusal"]
    assert refusal["primary"]["id"] == "strategy_registered_frozen"
    assert "approved" in refusal["primary"]["plain"]
    assert refusal["explanation_available"] is True
