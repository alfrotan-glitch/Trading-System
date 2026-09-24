"""The one direct-to-broker helper must refuse outside authorized DEMO.

``submit_with_order_check`` calls the broker adapter without going through
``DemoSession``, so it is the single place where the DEMO boundary could be
stepped around. It must fail closed: wrong mode, no authorization, or an
account that cannot be proven DEMO all raise before anything is sent.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qts.adapters.order_check import submit_with_order_check
from qts.lifecycle.demo_authorization import document_fingerprint


def _authorization(tmp_path, **scope_overrides):
    import json

    from qts.lifecycle.demo_authorization import ENV_AUTHORIZATION_PATH

    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": "DEMO-AUTH-DIRECT",
        "authorized_at": "2026-09-24T00:00:00+00:00",
        "authorized_by": "test",
        "statement": "test",
        "scope": {
            "account_type": "demo",
            "modes_allowed": ["DEMO_EXECUTION"],
            "symbols_allowed": ["XAUUSD"],
            "live_locked": True,
            "real_capital_exposure_usd": 0,
            "funds_transfer_permitted": False,
            "broker_switch_permitted": False,
            "autonomous_order_management": True,
            **(scope_overrides or {}),
        },
        "expires_at": None,
    }
    doc["integrity"] = {"content_sha256": document_fingerprint(doc)}
    (tmp_path / "authorization.json").write_text(json.dumps(doc), encoding="utf-8")
    import os

    os.environ[ENV_AUTHORIZATION_PATH] = str(tmp_path / "authorization.json")
    return doc


class RecordingAdapter:
    def __init__(self, identity=None):
        self.calls: list[object] = []
        self._identity = identity

    def broker_identity(self):
        return self._identity

    def submit(self, intent):
        self.calls.append(intent)
        return "SENT"


@pytest.mark.parametrize("mode", ["LIVE", "DEMO_FORWARD", "PAPER", "DEVELOPMENT"])
def test_refuses_outside_demo_execution(tmp_path, monkeypatch, mode):
    _authorization(tmp_path)
    monkeypatch.setenv("QTS_MODE", mode)
    adapter = RecordingAdapter()
    with pytest.raises(PermissionError, match="may not submit broker orders"):
        submit_with_order_check(adapter, None, None, None)
    assert adapter.calls == []


def test_refuses_without_an_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("QTS_MODE", "DEMO_EXECUTION")
    monkeypatch.delenv("QTS_DEMO_AUTHORIZATION", raising=False)
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(tmp_path / "missing.json"))
    adapter = RecordingAdapter()
    with pytest.raises(PermissionError, match="DISABLED BY POLICY"):
        submit_with_order_check(adapter, None, None, None)
    assert adapter.calls == []


def test_refuses_when_the_account_is_not_proven_demo(tmp_path, monkeypatch):
    _authorization(tmp_path)
    monkeypatch.setenv("QTS_MODE", "DEMO_EXECUTION")
    adapter = RecordingAdapter(identity=SimpleNamespace(is_demo=False))
    with pytest.raises(PermissionError, match="not proven DEMO"):
        submit_with_order_check(adapter, None, None, None)
    assert adapter.calls == []


def test_refuses_when_identity_cannot_be_read(tmp_path, monkeypatch):
    _authorization(tmp_path)
    monkeypatch.setenv("QTS_MODE", "DEMO_EXECUTION")

    class Broken:
        def broker_identity(self):
            raise RuntimeError("terminal unavailable")

    with pytest.raises(PermissionError, match="unreadable"):
        submit_with_order_check(Broken(), None, None, None)
