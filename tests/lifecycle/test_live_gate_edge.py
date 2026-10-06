import json

from qts.lifecycle.live_gate import check_validated_edge


def test_live_gate_rejects_blocked_edge(monkeypatch, tmp_path):
    evidence = tmp_path / "edge_validation.json"
    evidence.write_text(
        json.dumps(
            {
                "conclusion": "NO_VALIDATED_EDGE",
                "edge_survival": {"passed": False},
                "promotion": {"advanced": False},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "qts.config.paths.artifact_path",
        lambda name: evidence if name == "edge_validation" else tmp_path / name,
    )
    passed, detail = check_validated_edge()
    assert passed is False
    assert "blocked" in detail.lower()


def test_live_gate_accepts_only_explicit_validated_edge(monkeypatch, tmp_path):
    evidence = tmp_path / "edge_validation.json"
    evidence.write_text(
        json.dumps(
            {
                "conclusion": "VALIDATED",
                "edge_survival": {"passed": True},
                "promotion": {"advanced": True},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "qts.config.paths.artifact_path",
        lambda name: evidence if name == "edge_validation" else tmp_path / name,
    )
    passed, detail = check_validated_edge()
    assert passed is True
    assert "validated" in detail.lower()
