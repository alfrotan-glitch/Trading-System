"""Market Regime Observatory — builds regime dataset over time, tracks transitions."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.domain.value_objects import uuid7


class RegimeObservation(BaseModel):
    id: str = Field(default_factory=lambda: f"RG-{uuid7()[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    symbol: str
    trend_strength: float  # e.g., slope normalized
    realized_volatility: float
    volatility_regime: str  # low / normal / high
    range_chop: float  # 0 trend, 1 chop
    spread_regime: str  # tight / normal / wide
    session: str
    acceleration: float
    compression_expansion: str  # compression / expansion
    shock_event: str | None = None
    liquidity_proxy: float | None = None


class RegimeObservatory:
    def __init__(self, db_path: Path | str = "data/sqlite/regime_observatory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS regime_observations (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")
            con.commit()

    def record(self, obs: RegimeObservation):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO regime_observations VALUES (?,?,?)", (obs.id, obs.model_dump_json(), obs.timestamp.isoformat()))
            con.commit()

    def list(self, limit: int = 100) -> list[RegimeObservation]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM regime_observations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [RegimeObservation.model_validate_json(r[0]) for r in rows]

    def transitions(self) -> list[dict[str, Any]]:
        obs = self.list(limit=200)
        obs_sorted = sorted(obs, key=lambda x: x.timestamp)
        transitions = []
        for i in range(1, len(obs_sorted)):
            if obs_sorted[i].volatility_regime != obs_sorted[i-1].volatility_regime:
                transitions.append({"time": obs_sorted[i].timestamp.isoformat(), "from": obs_sorted[i-1].volatility_regime, "to": obs_sorted[i].volatility_regime, "symbol": obs_sorted[i].symbol})
        return transitions

    def summary(self) -> dict[str, Any]:
        obs = self.list(limit=1000)
        if not obs:
            return {"count": 0, "note": "No regime observations yet — run forward_observatory.simulate_observation to generate"}
        vols = [o.volatility_regime for o in obs]
        from collections import Counter
        cnt = Counter(vols)
        return {
            "count": len(obs),
            "volatility_distribution": dict(cnt),
            "trend_strength_avg": float(sum(o.trend_strength for o in obs)/len(obs)) if obs else 0.0,
            "transitions": self.transitions()[:10],
            "question": "How did this strategy behave during each observed state? — join with forward_observatory signals by timestamp",
        }

    def to_json(self, path: Path = Path("data/evidence/market_regime_observations.json")) -> dict[str, Any]:
        s = self.summary()
        s["generated_at"] = datetime.now(UTC).isoformat()
        s["observations_sample"] = [o.model_dump(mode="json") for o in self.list(limit=5)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s, indent=2, default=str))
        return s

    def simulate(self, symbol: str = "XAUUSD", n: int = 20):
        import random
        for _ in range(n):
            vol = random.choice(["low", "normal", "high"])
            obs = RegimeObservation(symbol=symbol, trend_strength=random.uniform(-1,1), realized_volatility=random.uniform(0.005, 0.02), volatility_regime=vol, range_chop=random.uniform(0,1), spread_regime=random.choice(["tight","normal","wide"]), session=random.choice(["London","NY","Asian"]), acceleration=random.uniform(-0.5,0.5), compression_expansion=random.choice(["compression","expansion"]), shock_event=random.choice([None, "shock"]) if random.random()<0.1 else None, liquidity_proxy=random.uniform(0.5,1.5))
            self.record(obs)
        return self.summary()
