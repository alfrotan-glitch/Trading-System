"""A missing terminal must be DIAGNOSED, not raised.

`qts demo verify` is the first command an operator runs to find out what is
blocking DEMO execution. It is at its most valuable on the machine where
nothing works yet: MT5 not installed, terminal not running, package missing.

Those were exactly the conditions under which it crashed. Two probes raised
`RuntimeError` instead of reporting UNKNOWN, so the command emitted a raw
Python traceback on precisely the machine that needed the diagnosis — and
`qts demo verify` is the command whose entire job is to answer "what is wrong?".

The surrounding design already had the right answer. `DemoPretradeContext` is
documented as "`None` means UNKNOWN and fails closed", and the gate already
converts `identity=None` into `CHECK_UNKNOWN` with the message "DEMO status
unprovable". The probes just had to stop raising and let it.

These tests pin that: a dead terminal produces a structured, actionable
report from both the connectivity probe and the pre-trade gate.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from qts.execution.demo_session import DemoSession, DemoSessionConfig


class DeadTerminal:
    """Every terminal call fails the way a missing MT5 install fails.

    ``account_info`` matters: that is the first thing the identity probe
    touches, so a fake without it fails for the wrong reason (AttributeError
    instead of "package not installed").
    """

    def account_info(self):
        raise RuntimeError("MetaTrader5 package not installed")

    def broker_identity(self):
        raise RuntimeError("MetaTrader5 package not installed")

    def account(self):
        raise RuntimeError("MetaTrader5 package not installed")

    def positions(self):
        raise RuntimeError("MetaTrader5 package not installed")

    def orders(self):
        raise RuntimeError("MetaTrader5 package not installed")

    def get_symbol_spec(self, symbol):  # noqa: ARG002
        raise RuntimeError("MetaTrader5 package not installed")

    def ensure_symbol_visible(self, symbol):  # noqa: ARG002
        raise RuntimeError("MetaTrader5 package not installed")

    def tick(self, symbol):  # noqa: ARG002
        raise RuntimeError("MetaTrader5 package not installed")

    def order_check(self, **kwargs):  # noqa: ARG002
        raise RuntimeError("MetaTrader5 package not installed")


@pytest.fixture
def session(demo_env, tmp_path) -> DemoSession:  # noqa: ARG001
    """A session whose only fault is that the terminal is unreachable.

    Deliberately NOT armed: no pin, no authority, no stage advancement. It is
    the state of a machine that has never successfully talked to a broker,
    which is exactly when the operator reaches for `qts demo verify`.
    """
    return DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=Path(tmp_path) / "qts.db",
            actor="no-terminal-test",
            mt5_module=DeadTerminal(),
        )
    )


def test_connectivity_report_survives_a_dead_terminal(session):
    """The probe reports the fault instead of raising through the CLI."""
    report = session.connectivity_report()

    assert report["readiness"]["passed"] is False
    # The pinned-identity probe must degrade like its siblings, not explode.
    pin = report["identity_pin"]
    assert pin["ok"] is False
    assert pin["error"], "the operator needs the reason, not just a False"
    assert "MetaTrader5" in pin["error"]


def test_connectivity_report_still_reports_the_pin_state(session):
    """Degrading must not lose information: the pin is still described."""
    pin = session.connectivity_report()["identity_pin"]
    assert pin["pinned"] is False
    assert pin["verified"] is None


def _verdict(session) -> dict:
    """`preflight` returns a report; the gate decision is nested under "verdict"."""
    return session.preflight(side="BUY", lots=Decimal("0.01"))["verdict"]


def test_preflight_denies_without_raising(session):
    """The gate denies on UNKNOWN facts; it does not crash on them."""
    assert _verdict(session)["passed"] is False


def test_a_dead_terminal_produces_unknown_checks_not_silent_passes(session):
    """UNKNOWN must be recorded, never rounded down to 'fine'."""
    verdict = _verdict(session)
    # Identity is unprovable without a terminal, so it must be UNKNOWN.
    assert "account_is_demo" in verdict["unknown"]
    assert "broker_identity_verified" in verdict["unknown"]
    assert "account_is_demo" in verdict["checks"]


def test_preflight_still_names_the_operator_blockers(session):
    """Denial without a reason is just a different way to be unhelpful."""
    reasons = _verdict(session)["reasons"]
    assert reasons, "the operator is told why, not merely that"
