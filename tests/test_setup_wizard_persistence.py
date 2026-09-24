"""Setup Wizard persistence — truthful save, credential-free, consistent gates.

Fixes proven here:
1. "Save Setup" previously displayed saved:true while persisting nothing
   (truthfulness violation). POST /api/setup/mt5 now stores terminal_path /
   symbol / symbol_map in a machine-local gitignored file (QTS_SETUP_FILE).
2. Credentials are NEVER persisted even when supplied — rejected explicitly
   and reported in rejected_fields.
3. /api/demo/readiness AND /api/demo/enable resolve the SAME connection
   config (param > saved file > env inside the gate), so demo-enablement can
   never evaluate a different terminal than the one the user tested.
4. Validation is fail-closed: bad input -> 400, nothing stored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import qts.lifecycle.demo_gate as dg
from qts.api.server import app
from qts.config.wizard import load_setup, save_setup, setup_file

TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("QTS_SETUP_FILE", str(tmp_path / "mt5_setup.json"))
    return TestClient(app)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture what the server forwards to the readiness gate."""
    cap: dict[str, Any] = {}

    def fake_report(**kwargs: Any) -> dict[str, Any]:
        cap.update(kwargs)
        return {
            "passed": False,
            "demo_enabled": False,
            "warn_live_in_demo": False,
            "blocked_reasons": [],
            "checks": {},
        }

    monkeypatch.setattr(dg, "demo_forward_readiness_report", fake_report)
    return cap


def test_save_load_roundtrip(tmp_path: Path):
    f = tmp_path / "mt5_setup.json"
    out = save_setup({"terminal_path": TERMINAL_PATH, "symbol": "XAUUSD@"}, path=f)
    assert out["saved"]["terminal_path"] == TERMINAL_PATH
    assert out["saved"]["symbol"] == "XAUUSD@"
    assert out["rejected_fields"] == []
    loaded = load_setup(f)
    assert loaded["terminal_path"] == TERMINAL_PATH
    assert loaded["symbol"] == "XAUUSD@"
    # partial update merges, does not clobber
    save_setup({"symbol_map": {"XAUUSD": "XAUUSD@"}}, path=f)
    merged = load_setup(f)
    assert merged["terminal_path"] == TERMINAL_PATH
    assert merged["symbol_map"] == {"XAUUSD": "XAUUSD@"}


def test_credentials_are_never_persisted(tmp_path: Path):
    f = tmp_path / "mt5_setup.json"
    out = save_setup(
        {
            "terminal_path": TERMINAL_PATH,
            "login": 1234567,
            "password": "hunter2",
            "server": "WMMarkets-Demo",
        },
        path=f,
    )
    assert out["rejected_fields"] == ["login", "password", "server"]
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert "password" not in raw and "login" not in raw and "server" not in raw
    assert "hunter2" not in f.read_text(encoding="utf-8")
    assert "NEVER stored" in out["credentials_note"]


def test_validation_is_fail_closed(tmp_path: Path):
    f = tmp_path / "mt5_setup.json"
    with pytest.raises(ValueError):
        save_setup({"symbol": "BAD SYMBOL; DROP"}, path=f)
    with pytest.raises(ValueError):
        save_setup({"terminal_path": "x" * 600}, path=f)
    with pytest.raises(ValueError):
        save_setup({"terminal_path": "   "}, path=f)
    with pytest.raises(ValueError):
        save_setup({"symbol_map": {"XAUUSD": "ok", "bad key!": "y"}}, path=f)
    assert not f.exists(), "invalid payloads must store nothing"


def test_corrupt_or_missing_file_yields_empty(tmp_path: Path):
    assert load_setup(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_setup(bad) == {}


def test_setup_file_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("QTS_SETUP_FILE", str(tmp_path / "custom.json"))
    assert setup_file() == tmp_path / "custom.json"
    monkeypatch.delenv("QTS_SETUP_FILE")
    assert setup_file().resolve() == Path("data/setup/mt5_setup.json").resolve()


def test_api_save_and_get(client: TestClient):
    r = client.post("/api/setup/mt5", json={"terminal_path": TERMINAL_PATH, "symbol": "XAUUSD@"})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"]["terminal_path"] == TERMINAL_PATH
    assert body["rejected_fields"] == []

    r2 = client.get("/api/setup/mt5")
    assert r2.status_code == 200
    assert r2.json()["setup"]["symbol"] == "XAUUSD@"

    # invalid input -> 400, nothing stored for that field
    r3 = client.post("/api/setup/mt5", json={"symbol": "bad symbol!"})
    assert r3.status_code == 400


def test_readiness_uses_saved_setup(client: TestClient, captured: dict[str, Any]):
    client.post(
        "/api/setup/mt5",
        json={"terminal_path": TERMINAL_PATH, "symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}},
    )
    r = client.get("/api/demo/readiness")
    assert r.status_code == 200
    assert captured["terminal_path"] == TERMINAL_PATH
    assert captured["symbol"] == "XAUUSD"
    assert captured["symbol_map"] == {"XAUUSD": "XAUUSD@"}

    # explicit query param beats the saved file
    captured.clear()
    r2 = client.get("/api/demo/readiness", params={"terminal_path": r"D:\Other\terminal64.exe", "symbol": "GOLD#"})
    assert r2.status_code == 200
    assert captured["terminal_path"] == r"D:\Other\terminal64.exe"
    assert captured["symbol"] == "GOLD#"

    # nothing saved, no params -> None (gate falls back to env/auto-detect)
    captured.clear()
    setup_file().unlink()
    r3 = client.get("/api/demo/readiness")
    assert r3.status_code == 200
    assert captured["terminal_path"] is None
    assert captured["symbol"] is None
    assert captured["symbol_map"] is None


def test_demo_enable_evaluates_the_same_saved_connection(client: TestClient, captured: dict[str, Any]):
    client.post("/api/setup/mt5", json={"terminal_path": TERMINAL_PATH, "symbol": "XAUUSD@"})
    r = client.post("/api/demo/enable", json={"confirmed": True, "risk_ack": True})
    # In this sandbox readiness cannot pass (no real terminal): the endpoint
    # must REFUSE with 409, return disabled=false and the blocked reasons —
    # never a 200 with demo_enabled=true (the old fabricated enablement).
    assert r.status_code == 409
    body = r.json()
    assert body["enabled"] is False
    assert body["execution_permitted"] is False
    assert body["state"] == "DISABLED"
    assert body["reasons"], "refusal must carry reasons"
    # ... and it must evaluate the SAME saved connection the user configured.
    assert captured["terminal_path"] == TERMINAL_PATH
    assert captured["symbol"] == "XAUUSD@"

    # missing acks refused BEFORE any readiness evaluation
    captured.clear()
    r2 = client.post("/api/demo/enable", json={"confirmed": False, "risk_ack": True})
    assert r2.status_code == 400
    assert captured == {}

    # the authoritative state endpoint agrees: nothing was enabled
    st = client.get("/api/demo/state")
    assert st.status_code == 200
    assert st.json()["enabled"] is False
    assert st.json()["execution_permitted"] is False


def test_ui_wires_save_to_the_endpoint():
    js = Path("src/qts/desktop/ui/js/views/system.js").read_text(encoding="utf-8")
    api_js = Path("src/qts/desktop/ui/js/api.js").read_text(encoding="utf-8")
    assert '"/api/setup/mt5"' in js
    assert "api.post" in js  # save issues a POST
    # never claim success on 4xx — structurally: the api layer throws non-2xx
    assert "if (!resp.ok) throw" in api_js
    assert 'toast("err", "Could not save setup"' in js  # failure surfaced, not swallowed
    assert "Nothing is enabled from this page" in js  # truthful about what save does
    assert "XAUUSD@" in js  # broker-suffix hint next to the symbol field
