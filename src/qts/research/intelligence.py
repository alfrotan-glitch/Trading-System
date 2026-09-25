"""Autonomous Research Intelligence Layer — orchestration, hypothesis generation, lineage, budget."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.db import connect as db_connect
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
    # Explicit scientific specification fields.  Defaults preserve loading of
    # older hypothesis rows; newly generated hypotheses fill them from the
    # thought and remain incomplete only when the source thought is incomplete.
    null_hypothesis: str = "No incremental predictive or economic effect beyond the declared baseline and costs"
    competing_explanations: list[str] = Field(
        default_factory=lambda: [
            "selection or multiple-testing artifact",
            "regime/sample dependence",
            "unmodeled spread, slippage, or latency",
        ]
    )
    horizon: str = "declared out-of-sample evaluation horizon"
    population: str = "declared instrument, timeframe, and available provenance-qualified sample"
    falsification_criteria: str = ""
    required_data: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IntelligenceOrchestrator:
    """Inspects data/evidence, identifies weaknesses, generates falsifiable hypotheses, designs experiments, runs bounded, analyzes failures, mutates, maintains lineage."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with db_connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS research_thoughts (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS hypothesis_specs (id TEXT PRIMARY KEY, thought_id TEXT, payload TEXT, created_at TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS thought_lineage (parent TEXT, child TEXT, relation TEXT, PRIMARY KEY(parent, child))"
            )
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
        if latest and bars_count:
            span_days = (latest.end - latest.start).total_seconds() / 86_400
            limitation = (
                f"{bars_count} bars across {span_days:.1f} days for {latest.instrument} {latest.timeframe}; "
                "dataset depth, symbol/timeframe breadth, provenance, and field semantics must be verified before claims"
            )
        elif latest:
            limitation = "Manifest exists but readable bars are unavailable; depth/span cannot be measured"
        else:
            limitation = "No canonical dataset manifest is available"
        return {
            "versions": versions,
            "latest": latest.model_dump() if latest else None,
            "bars": bars_count,
            "span_days": (latest.end - latest.start).total_seconds() / 86_400 if latest and bars_count else None,
            "limitation": limitation,
        }

    def inspect_evidence(self) -> dict[str, Any]:
        ev_path = Path("data/evidence/edge_validation.json")
        ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
        camp_path = Path("data/evidence/campaigns_summary.json")
        camps = json.loads(camp_path.read_text(encoding="utf-8")) if camp_path.exists() else {}
        # Identify weaknesses
        weaknesses = []
        es = ev.get("edge_survival", {})
        pbo = es.get("pbo")
        if isinstance(pbo, (int, float)) and pbo > 0.5:
            weaknesses.append("PBO high — overfitting")
        elif pbo is None:
            weaknesses.append("PBO unavailable — CPCV evidence is missing")
        dsr = es.get("dsr")
        if not isinstance(dsr, (int, float)) or dsr < 0.95:
            weaknesses.append("DSR unavailable/low — multiple-testing penalty")
        break_even = es.get("cost_break_even_bps")
        if isinstance(break_even, (int, float)) and break_even < 20:
            weaknesses.append("Cost break-even low — no economic edge")
        elif break_even is None:
            weaknesses.append("Cost break-even unavailable — cost evidence is missing")
        # Regime worst
        regs = ev.get("regime", [])
        regime_rows = regs if isinstance(regs, list) else []
        worst = min(regime_rows, key=lambda x: x.get("sharpe", 0)) if regime_rows else None
        if worst and worst.get("sharpe", 0) < -2:
            weaknesses.append(f"Regime failure {worst.get('regime')} Sharpe {worst.get('sharpe'):.2f}")
        elif not regime_rows:
            weaknesses.append("Regime evidence unavailable or not trial-bound")
        return {"evidence": ev, "campaigns": camps, "weaknesses": weaknesses, "worst_regime": worst}

    def generate_thought(self, question: str, mechanism: str, **kwargs) -> ResearchThought:
        thought = ResearchThought(
            question=question,
            mechanism=mechanism,
            why=kwargs.get("why", ""),
            assumption=kwargs.get("assumption", ""),
            support_observation=kwargs.get("support", ""),
            falsify_observation=kwargs.get("falsify", ""),
            data_required=kwargs.get("data_required", ""),
            cost_conditions=kwargs.get("cost_conditions", ""),
            regimes_expected=kwargs.get("regimes_expected", ""),
            regimes_stop=kwargs.get("regimes_stop", ""),
            lineage=kwargs.get("lineage", []),
        )
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO research_thoughts VALUES (?,?,?)",
                (thought.id, thought.model_dump_json(), thought.timestamp.isoformat()),
            )
            con.commit()
        return thought

    def propose_hypothesis(
        self, thought: ResearchThought, family: str, statement: str, falsifiable_prediction: str
    ) -> HypothesisSpec:
        hyp = HypothesisSpec(
            thought_id=thought.id,
            statement=statement,
            mechanism=thought.mechanism,
            why=thought.why,
            falsifiable_prediction=falsifiable_prediction,
            support=thought.support_observation,
            falsify=thought.falsify_observation,
            data_required=thought.data_required,
            cost_conditions=thought.cost_conditions,
            regimes=thought.regimes_expected,
            stop_conditions=thought.regimes_stop,
            family=family,
            null_hypothesis="No incremental predictive or economic effect beyond the declared baseline and costs",
            competing_explanations=[
                "selection or multiple-testing artifact",
                "regime/sample dependence",
                "unmodeled spread, slippage, or latency",
            ],
            horizon="the declared out-of-sample evaluation horizon",
            population="the declared instrument, timeframe, regime, and provenance-qualified dataset",
            falsification_criteria=thought.falsify_observation,
            required_data=thought.data_required,
        )
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO hypothesis_specs VALUES (?,?,?,?)",
                (hyp.id, thought.id, hyp.model_dump_json(), hyp.created_at.isoformat()),
            )
            con.execute("INSERT OR IGNORE INTO thought_lineage VALUES (?,?,?)", (thought.id, hyp.id, "generates"))
            con.commit()
        return hyp

    def generate_mechanism_hypotheses(
        self,
        mechanism_pool: list[str] | None = None,
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "1H",
        data_description: str | None = None,
    ) -> list[HypothesisSpec]:
        """Generate bounded, explicitly falsifiable hypotheses with declared scope."""
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
                question=f"Does {mech} produce executable edge in {symbol} {timeframe} after costs?",
                mechanism=mech,
                why=f"Previous evidence shows regime dependence and cost sensitivity — testing {mech} may reveal conditional edge",
                assumption=f"Market exhibits {mech} that persists beyond spread/slippage",
                support="OOS Sharpe >0.3 with WFE>0.3, DSR>0.95, regime stable, cost BE >20bps",
                falsify="OOS Sharpe <=0, WFE<0.3, DSR <0.5, or placebo equivalent, or cost BE <5bps",
                data_required=data_description or f"{symbol} {timeframe} bars with provenance, timestamps, costs, and regime labels; depth/span must be measured before claims",
                cost_conditions="spread 3bps, slippage realistic, latency 100ms, next-bar-open execution",
                regimes_expected="trend for persistence, range for mean-reversion",
                regimes_stop="high_vol or opposite regime should degrade",
            )
            hyp = self.propose_hypothesis(
                t,
                family=mech.replace(" ", "_")[:20],
                statement=f"{mech}: if {mech} exists, strategy capturing it should survive walk-forward, CPCV, costs, regime",
                falsifiable_prediction=f"Strategy on {mech} will have DSR>0.95, PBO<0.5, cost BE>20bps, and separate from null",
            )
            thoughts.append(hyp)
        return thoughts

    def lineage(self, parent: str, child: str, relation: str = "mutates"):
        with db_connect(self.db_path) as con:
            con.execute("INSERT OR IGNORE INTO thought_lineage VALUES (?,?,?)", (parent, child, relation))
            con.commit()

    def all_thoughts(self, limit: int = 20) -> list[ResearchThought]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT payload FROM research_thoughts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [ResearchThought.model_validate_json(r[0]) for r in rows]

    def all_hypotheses(self, limit: int = 20) -> list[HypothesisSpec]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT payload FROM hypothesis_specs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [HypothesisSpec.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        with contextlib.suppress(Exception):
            # File-backed connections are opened/closed per operation via qts.db.connect,
            # so no persistent handle exists here. We must NOT re-open the database file
            # in close()/__del__: that recreates deleted files and re-acquires Windows
            # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                with contextlib.suppress(Exception):
                    mem.commit()
                    mem.close()
                self._memory_con = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
