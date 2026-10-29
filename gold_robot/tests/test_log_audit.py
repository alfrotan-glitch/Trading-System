"""Pure log-format regression fixtures; no broker or terminal access."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from audit_mt5_logs import audit  # noqa: E402


def sample(style: int, completed: bool = True) -> str:
    lines = [
        "testing of Experts\\QTS_Gold_Robot.ex5 from 2026.01.01 00:00 to 2026.02.05 00:00 started with inputs:",
        f"EntryStyle={style}",
        "QTS DEMO LIMIT accepted order=5",
        "QTS broker deal: deal=6 entry=0 volume=0.01 price=4000.00 gross=0.00 commission=0.00 swap=0.00 fee=0.00 net=0.00",
        "QTS broker deal: deal=7 entry=1 volume=0.01 price=4001.00 gross=1.00 commission=0.00 swap=0.00 fee=0.00 net=1.00",
    ]
    if completed:
        lines.extend(["final balance 3001.00 USD", "Test passed in 0:00:30.00"])
    return "\n".join(lines)


def test_complete_duplicate_and_fee_stress(tmp_path):
    a = tmp_path / "QTS_0.htm.log"
    b = tmp_path / "QTS_2.htm"
    a.write_text(sample(2), encoding="utf-16")
    b.write_text(sample(2), encoding="utf-16")
    report = audit([a, b], 10.0)
    assert report["complete_unique"] == 1
    assert report["sessions"][0]["entry_style"] == 2
    assert report["sessions"][1]["duplicate_of"]
    assert report["sessions"][0]["deal_net_usd"] == 1.0
    assert report["sessions"][0]["stressed_net_usd"] == 0.9
    assert report["edge_validated"] is False


def test_partial_log_is_not_certified(tmp_path):
    p = tmp_path / "partial.log"
    p.write_text(sample(0, completed=False) + "\nstopped by user", encoding="utf-8")
    report = audit([p])
    assert report["complete_unique"] == 0
    assert report["sessions"][0]["state"] == "INCOMPLETE_LOG_ONLY"
    assert report["sessions"][0]["final_balance"] is None


def test_fails_closed_for_invalid_cost(tmp_path):
    p = tmp_path / "log.txt"
    p.write_text(sample(1))
    with pytest.raises(ValueError):
        audit([p], -1)
