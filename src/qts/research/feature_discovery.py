"""Controlled Feature Discovery — no leakage, complete lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Any

from pydantic import BaseModel, Field

from qts.domain.value_objects import uuid7, Bar


class FeatureSpec(BaseModel):
    id: str = Field(default_factory=lambda: f"F-{uuid7()[:6]}")
    name: str
    definition: str
    source: str  # price, returns, volatility, range, spread, session, etc.
    timestamp_semantics: str  # e.g., "computed at bar close_time using only bars <= close_time"
    lookback: int
    data_dependencies: list[str]
    version: str = "1.0.0"
    lineage: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    code_hash: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps({"name": self.name, "definition": self.definition, "source": self.source, "lookback": self.lookback}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


class FeatureStore:
    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS features (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS feature_lineage (parent TEXT, child TEXT, relation TEXT, PRIMARY KEY(parent, child))")
            con.commit()

    def register(self, spec: FeatureSpec) -> FeatureSpec:
        # No leakage checks
        if "future" in spec.definition.lower() or "post-trade" in spec.definition.lower():
            raise ValueError(f"feature {spec.name} definition suggests future leakage")
        spec.code_hash = spec.compute_hash()
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO features VALUES (?,?,?)", (spec.id, spec.model_dump_json(), spec.created_at.isoformat()))
            con.commit()
        return spec

    def get(self, fid: str) -> FeatureSpec | None:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM features WHERE id=?", (fid,)).fetchone()
            return FeatureSpec.model_validate_json(row[0]) if row else None

    def list(self) -> list[FeatureSpec]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM features").fetchall()
            return [FeatureSpec.model_validate_json(r[0]) for r in rows]

    def lineage(self, parent: str, child: str, relation: str = "derived"):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR IGNORE INTO feature_lineage VALUES (?,?,?)", (parent, child, relation))
            con.commit()


# Predefined controlled features (no leakage)
CONTROLLED_FEATURES: list[FeatureSpec] = [
    FeatureSpec(name="returns_1", definition="close-to-close return at bar N computed from close_{N-1} to close_N", source="price", timestamp_semantics="close_time of N, uses only closes <=N", lookback=1, data_dependencies=["close"]),
    FeatureSpec(name="range_5", definition="high-low range over last 5 bars ending at N", source="range", timestamp_semantics="close_time N, uses bars N-4..N", lookback=5, data_dependencies=["high","low"]),
    FeatureSpec(name="volatility_20", definition="std of returns over 20 bars ending at N", source="volatility", timestamp_semantics="close_time N, uses returns N-19..N", lookback=20, data_dependencies=["close"]),
    FeatureSpec(name="spread_proxy", definition="high-low as spread proxy at N", source="spread", timestamp_semantics="close_time N", lookback=1, data_dependencies=["high","low"]),
    FeatureSpec(name="session_hour", definition="hour of day extracted from close_time UTC", source="time-of-day", timestamp_semantics="close_time N", lookback=1, data_dependencies=["close_time"]),
    FeatureSpec(name="range_compression", definition="range_5 / range_20 ratio", source="range", timestamp_semantics="close_time N, uses bars N-19..N", lookback=20, data_dependencies=["high","low"]),
]


def compute_feature(spec: FeatureSpec, bars: list[Bar], idx: int) -> float | None:
    """Compute feature at index idx using only bars <= idx (no future)."""
    if idx < spec.lookback:
        return None
    window = bars[idx - spec.lookback + 1: idx + 1]
    if spec.name == "returns_1":
        if idx == 0:
            return None
        prev = float(bars[idx-1].close)
        cur = float(bars[idx].close)
        return (cur - prev) / prev if prev else 0.0
    if spec.name == "range_5":
        return float(max(b.high for b in window) - min(b.low for b in window))
    if spec.name == "volatility_20":
        import numpy as np
        closes = [float(b.close) for b in window]
        rets = np.diff(closes) / np.array(closes[:-1])
        return float(np.std(rets)) if len(rets) else 0.0
    if spec.name == "spread_proxy":
        return float(bars[idx].high - bars[idx].low)
    if spec.name == "session_hour":
        return float(bars[idx].close_time.hour)
    if spec.name == "range_compression":
        r5 = max(float(b.high) for b in bars[idx-4:idx+1]) - min(float(b.low) for b in bars[idx-4:idx+1]) if idx >=4 else 1.0
        r20 = max(float(b.high) for b in window) - min(float(b.low) for b in window) if len(window)>=20 else r5
        return r5 / r20 if r20 else 1.0
    return None
