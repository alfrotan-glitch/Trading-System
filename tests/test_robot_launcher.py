"""Windows robot shortcut cannot bypass the canonical demo-only launcher."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_robot_shortcut_has_one_canonical_backend_and_memory_preflight():
    content = (ROOT / "ROBOT.bat").read_text(encoding="utf-8").lower()
    assert 'call "scripts\\run_qts.bat"' in content
    assert "python.exe" in content
    assert "if errorlevel 1" in content
    assert "no strategy is validated profitable" in content
    # The shortcut must never turn a button into an order or change authority.
    for forbidden in (
        "order_send", "autopilot --confirm", "demo enable", "demo arm",
        "qts_mode=", "qts_env=demo_execution", "qts_mt5_mode=real",
        "reg add", "setx", "mt5_login=", "git clean", "rmdir /s",
    ):
        assert forbidden not in content


def test_operator_documentation_does_not_promise_profitable_orders():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/robot-operator-windows.md").read_text(encoding="utf-8")
    assert "ROBOT.bat" in readme and "ROBOT.bat" in guide
    assert "not a proven" in readme
    assert "LIVE = LOCKED" in guide
    assert "authorization" in guide.lower()
