"""Pure log-format regression fixtures; no broker or terminal access."""
from pathlib import Path
import sys
import json
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from audit_mt5_logs import audit, discover_files, main, render_html  # noqa: E402


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


def test_wrong_filename_label_is_not_evidence_of_named_style(tmp_path):
    p = tmp_path / "QTS_0.htm"
    p.write_text(sample(2), encoding="utf-8")
    result = audit([p])
    assert result["filename_mismatches"] == 1
    assert result["sessions"][0]["filename_style_matches"] is False
    assert result["sessions"][0]["eligible_for_comparison"] is False
    html = render_html(result)
    assert "WRONG_FILENAME" in html


def test_changed_inputs_are_not_deduplicated(tmp_path):
    a = tmp_path / "first.log"
    b = tmp_path / "second.log"
    a.write_text(sample(2).replace("EntryStyle=2", "Tester   EntryStyle=2\nTester   RiskPerTradePct=0.50"))
    b.write_text(sample(2).replace("EntryStyle=2", "Tester   EntryStyle=2\nTester   RiskPerTradePct=0.25"))
    result = audit([a, b])
    assert result["complete_unique"] == 2
    assert all(item["duplicate_of"] is None for item in result["sessions"])


def test_html_escapes_malicious_log_text(tmp_path):
    p = tmp_path / "QTS_2.htm.log"
    p.write_text(sample(2) + "\nQTS ENTRY AUDIT bar=2026.01.03 reason=<script>alert(1)</script>")
    rendered = render_html(audit([p]))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered


def test_native_html_is_not_mistaken_for_agent_log(tmp_path):
    p = tmp_path / "QTS_0.htm"
    p.write_text("<!doctype html><html><body>MT5 report</body></html>")
    result = audit([p])
    assert not result["sessions"]
    assert result["edge_validated"] is False


def test_discover_renamed_log_by_contents_and_native_html_separately(tmp_path):
    log = tmp_path / "backtest gold (October).txt"
    log.write_text(sample(2), encoding="utf-16")
    native = tmp_path / "strategy results.html"
    native.write_text("<html><body>MetaTrader 5 - Total Net Profit: 22</body></html>")
    unrelated = tmp_path / "ordinary.log"
    unrelated.write_text("not a QTS tester session")
    discovery = discover_files([tmp_path])
    assert discovery["log_paths"] == [log]
    assert discovery["native_report_paths"] == [native]
    assert discovery["scanned"] == 3


def test_no_matching_logs_generates_actionable_html_not_cli_error(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    json_path = tmp_path / "audit.json"
    html_path = tmp_path / "audit.html"
    monkeypatch.setattr(sys, "argv", ["audit_mt5_logs.py", "--directory", str(empty),
                        "--output", str(json_path), "--html-output", str(html_path)])
    assert main() == 0
    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert result["file_search"]["status"] == "NO_AGENT_LOGS_FOUND"
    assert result["file_search"]["folders_checked"] == [str(empty)]
    assert result["sessions"] == []
    assert "No QTS agent log sessions" in capsys.readouterr().out
    assert "NO_AGENT_LOGS_FOUND" in html_path.read_text(encoding="utf-8")


def test_folder_with_only_native_mt5_report_is_not_a_trade_log(tmp_path, monkeypatch):
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "strategy.html").write_text("<html><body>MetaTrader 5 - Total Net Profit: 22</body></html>")
    json_path = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["audit_mt5_logs.py", "--directory", str(folder),
                                      "--output", str(json_path)])
    assert main() == 0
    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert result["file_search"]["status"] == "NATIVE_HTML_ONLY"
    assert result["sessions"] == []
    assert result["file_search"]["native_html_reports_found"] == ["strategy.html"]
