"""Research & Adversarial agents — AI is hypothesis generator, not oracle."""

from __future__ import annotations

from typing import Protocol

from qts.research.experiment import Hypothesis


class ResearchAgent(Protocol):
    def propose(self, n: int = 5, context: str = "") -> list[Hypothesis]: ...  # type: ignore[no-untyped-def]


class NullAgent:
    """Deterministic baseline — no LLM needed."""

    def propose(self, n: int = 5, context: str = "") -> list[Hypothesis]:
        templates = [
            (
                "XAUUSD 1H momentum persists 2-4h after London open conditioned on ATR expansion",
                "momentum",
                "fails if OOS Sharpe <0.3",
            ),
            (
                "XAUUSD mean-reversion on 15m RSI extremes (RSI<30 long, >70 short) with session filter",
                "mean-reversion",
                "fails if win rate <52% after cost",
            ),
            (
                "XAUUSD breakout of London high/low with volume filter outperforms random entry after cost",
                "breakout",
                "fails if spread 1.5x PF<1.0",
            ),
            (
                "XAUUSD volatility-targeted position sizing improves risk-adjusted returns vs fixed size",
                "vol-target",
                "fails if WFE <0.3",
            ),
            (
                "XAUUSD trend vs range regime conditioned entries improve OOS Sharpe vs unconditional",
                "regime",
                "fails if regime-conditioned Sharpe <= unconditional",
            ),
        ]
        out: list[Hypothesis] = []
        for i in range(min(n, len(templates))):
            stmt, rationale, fals = templates[i]
            out.append(Hypothesis(statement=stmt, rationale=rationale, falsifiability=fals, created_by="NullAgent"))
        return out


class AdversarialAgent:
    """Checks a ValidationReport for weaknesses."""

    def review(self, report: dict) -> list[str]:
        findings: list[str] = []
        if report.get("wfe", 1) < 0.3:
            findings.append("WFE <0.3 indicates heavy overfitting")
        if report.get("dsr_prob", 1) < 0.95:
            findings.append("DSR prob <0.95 — edge not deflated-significant")
        if report.get("pbo", 0) > 0.5:
            findings.append("PBO >0.5 — more likely than not overfit")
        if report.get("spread_pf_1_5x", 1) < 1.0:
            findings.append("Spread 1.5x profit factor <1.0 — cost sensitive, likely not live-viable")
        if report.get("oos_sharpe", 0) <= 0:
            findings.append("OOS Sharpe <=0 — no evidence of edge")
        return findings
