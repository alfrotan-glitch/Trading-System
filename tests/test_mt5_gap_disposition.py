from __future__ import annotations
import hashlib, json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from scripts.analyze_mt5_gap_disposition import analyze

def make_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "dataset"; (d / "parts").mkdir(parents=True)
    stamps = [int( datetime_ms("2026-09-18T20:00:00")), int(datetime_ms("2026-09-21T06:00:00")), int(datetime_ms("2026-09-23T06:00:00"))]
    part = d / "parts" / "part-00000.parquet"
    pq.write_table(pa.table({"time_msc": stamps, "bid": [1., 2., 3.], "ask": [1.1,2.1,3.1]}), part)
    digest = hashlib.sha256(part.read_bytes()).hexdigest()
    (d / "manifest.json").write_text(json.dumps({"dataset_sha256":"digest", "row_count":3, "parts":[{"part":part.name, "sha256":digest, "rows":3}]}))
    return d

def datetime_ms(value: str) -> int:
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)

def test_weekend_gap_stays_unresolved_and_has_no_payload(tmp_path):
    result = analyze(make_dataset(tmp_path), analysis_timestamp="2026-09-19T00:00:00+00:00")
    assert result["total_gaps_over_24h"] == 2
    assert result["unresolved_count"] == 2
    assert result["gaps"][0]["classification"] == "UNRESOLVED"
    assert result["raw_tick_payloads_included"] is False
    assert result["timestamp_basis_disposition"]["status"] == "VERIFIED_BY_OFFICIAL_MT5_DOCUMENTATION"
    assert result["evidence_sources"][0]["evidence_type"] == "official_direct_timestamp_basis"
    assert "bid" not in json.dumps(result["gaps"])

def test_documented_and_unexpected_are_explicit(tmp_path):
    d = make_dataset(tmp_path)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"sources":[{"name":"Broker closure notice","date":"2026-09-01","fact":"closed","directly_establishes_closure":True}], "gaps": {"gap-0001":{"classification":"EXPECTED_DOCUMENTED_MARKET_CLOSURE","basis":"notice","evidence_refs":["Broker closure notice"]}, "gap-0002":{"classification":"UNEXPECTED_DATA_GAP","basis":"documented observation"}}}))
    result = analyze(d, evidence, analysis_timestamp="2026-09-19T00:00:00+00:00")
    assert result["counts_by_classification"]["EXPECTED_DOCUMENTED_MARKET_CLOSURE"] == 1
    assert result["counts_by_classification"]["UNEXPECTED_DATA_GAP"] == 1
