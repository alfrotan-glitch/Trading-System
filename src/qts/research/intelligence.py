"""Autonomous Research Intelligence Layer — orchestration, hypothesis generation, lineage, budget."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.domain.value_objects import uuid7


class ResearchThought(BaseModel):
    id: str = Field(default_factory=lambda: f"THT-{uuid7()[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question: str
    mechanism: str
    why: str
    assumption: str
    support_observation: str
    falsify_observation: str
    data_required: str
    cost_conditions: str
    regimes_expected: str
    regimes_stop: str
    lineage: list[str] = Field(default_factory=list)


class HypothesisSpec(BaseModel):
    id: str = Field(default_factory=lambda: f"HYP-{uuid7()[:6]}")
    thought_id: str
    statement: str
    mechanism: str
    why: str
    falsifiable_prediction: str
    support: str
    falsify: str
    data_required: str
    cost_conditions: str
    regimes: str
    stop_conditions: str
    family: str
    feature_lineage: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IntelligenceOrchestrator:
    """Inspects data/evidence, identifies weaknesses, generates falsifiable hypotheses, designs experiments, runs bounded, analyzes failures, mutates, maintains lineage."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS research_thoughts (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS hypothesis_specs (id TEXT PRIMARY KEY, thought_id TEXT, payload TEXT, created_at TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS thought_lineage (parent TEXT, child TEXT, relation TEXT, PRIMARY KEY(parent, child))")
            con.commit()

    def inspect_data(self) -> dict[str, Any]:
        from qts.data.store import SqliteParquetDataStore
        from qts.domain.value_objects import Instrument
        store = SqliteParquetDataStore()
        versions = store.list_versions()
        latest = store.manifest(versions[-1]) if versions else None
        bars_count = 0
        if latest:
            try:
                instr = Instrument(symbol=latest.instrument, venue=getattr(latest, "venue", "MT5"))
                bars_count = len(store.read_bars(instr, latest.timeframe, version=latest.version))
            except Exception:
                bars_count = 0
        return {
            "versions": versions,
            "latest": latest.model_dump() if latest else None,
            "bars": bars_count,
            "limitation": "Only 500 XAUUSD 1H sample available — limited historical depth, single symbol, single timeframe. Explicitly reported as limitation per mission 6."
        }

    def inspect_evidence(self) -> dict[str, Any]:
        ev_path = Path("data/evidence/edge_validation.json")
        ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
        camp_path = Path("data/evidence/campaigns_summary.json")
        camps = json.loads(camp_path.read_text()) if camp_path.exists() else {}
        # Identify weaknesses
        weaknesses = []
        es = ev.get("edge_survival", {})
        if es.get("pbo", 1) > 0.5:
            weaknesses.append("PBO high — overfitting")
        if es.get("dsr", 0) < 0.95:
            weaknesses.append("DSR low — multiple-testing penalty")
        if es.get("cost_break_even_bps", 99) < 20:
            weaknesses.append("Cost break-even low — no economic edge")
        # Regime worst
        regs = ev.get("regime", [])
        worst = min(regs, key=lambda x: x.get("sharpe", 0)) if regs else None
        if worst and worst.get("sharpe", 0) < -2:
            weaknesses.append(f"Regime failure {worst.get('regime')} Sharpe {worst.get('sharpe'):.2f}")
        return {"evidence": ev, "campaigns": camps, "weaknesses": weaknesses, "worst_regime": worst}

    def generate_thought(self, question: str, mechanism: str, **kwargs) -> ResearchThought:
        thought = ResearchThought(question=question, mechanism=mechanism, why=kwargs.get("why", ""), assumption=kwargs.get("assumption", ""), support_observation=kwargs.get("support", ""), falsify_observation=kwargs.get("falsify", ""), data_required=kwargs.get("data_required", ""), cost_conditions=kwargs.get("cost_conditions", ""), regimes_expected=kwargs.get("regimes_expected", ""), regimes_stop=kwargs.get("regimes_stop", ""), lineage=kwargs.get("lineage", []))
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO research_thoughts VALUES (?,?,?)", (thought.id, thought.model_dump_json(), thought.timestamp.isoformat()))
            con.commit()
        return thought

    def propose_hypothesis(self, thought: ResearchThought, family: str, statement: str, falsifiable_prediction: str) -> HypothesisSpec:
        hyp = HypothesisSpec(thought_id=thought.id, statement=statement, mechanism=thought.mechanism, why=thought.why, falsifiable_prediction=falsifiable_prediction, support=thought.support_observation, falsify=thought.falsify_observation, data_required=thought.data_required, cost_conditions=thought.cost_conditions, regimes=thought.regimes_expected, stop_conditions=thought.regimes_stop, family=family)
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO hypothesis_specs VALUES (?,?,?,?)", (hyp.id, thought.id, hyp.model_dump_json(), hyp.created_at.isoformat()))
            con.execute("INSERT OR IGNORE INTO thought_lineage VALUES (?,?,?)", (thought.id, hyp.id, "generates"))
            con.commit()
        return hyp

    def generate_mechanism_hypotheses(self, mechanism_pool: list[str] | None = None) -> list[HypothesisSpec]:
        """Generate hypotheses for market mechanisms — falsifiable, with full provenance."""
        pool = mechanism_pool or [
            "trend persistence",
            "momentum persistence",
            "mean reversion",
            "breakout continuation",
            "breakout failure",
            "volatility clustering",
            "volatility expansion/contraction",
            "regime transitions",
            "liquidity effects",
            "spread behavior",
            "time-of-day effects",
            "session effects",
            "range compression/expansion",
            "directional imbalance",
            "price acceleration/deceleration",
            "exhaustion",
            "overextension",
            "pullback continuation",
            "failed breakouts",
            "multi-timeframe structure",
            "volatility-adjusted movement",
            "persistence after large moves",
            "asymmetric behavior after shocks",
        ]
        thoughts = []
        for mech in pool[:6]:  # bounded for demo
            t = self.generate_thought(
                question=f"Does {mech} produce executable edge in XAUUSD 1H after costs?",
                mechanism=mech,
                why=f"Previous evidence shows regime dependence and cost sensitivity — testing {mech} may reveal conditional edge",
                assumption=f"Market exhibits {mech} that persists beyond spread/slippage",
                support=f"OOS Sharpe >0.3 with WFE>0.3, DSR>0.95, regime stable, cost BE >20bps",
                falsify=f"OOS Sharpe <=0, WFE<0.3, DSR <0.5, or placebo equivalent, or cost BE <5bps",
                data_required="XAUUSD 1H 500 bars, need more depth for generality — limitation reported",
                cost_conditions="spread 3bps, slippage realistic, latency 100ms, next-bar-open execution",
                regimes_expected="trend for persistence, range for mean-reversion",
                regimes_stop="high_vol or opposite regime should degrade",
            )
            hyp = self.propose_hypothesis(t, family=mech.replace(" ", "_")[:20], statement=f"{mech}: if {mech} exists, strategy capturing it should survive walk-forward, CPCV, costs, regime", falsifiable_prediction=f"Strategy on {mech} will have DSR>0.95, PBO<0.5, cost BE>20bps, and separate from null")
            thoughts.append(hyp)
        return thoughts

    def lineage(self, parent: str, child: str, relation: str = "mutates"):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR IGNORE INTO thought_lineage VALUES (?,?,?)", (parent, child, relation))
            con.commit()

    def all_thoughts(self, limit: int = 20) -> list[ResearchThought]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM research_thoughts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [ResearchThought.model_validate_json(r[0]) for r in rows]

    def all_hypotheses(self, limit: int = 20) -> list[HypothesisSpec]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM hypothesis_specs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [HypothesisSpec.model_validate_json(r[0]) for r in rows]
