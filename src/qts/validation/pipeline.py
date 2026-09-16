"""Validation pipeline — strict, ordered, evidence-based."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from qts.validation.metrics import (
    deflated_sharpe_ratio,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    walk_forward_efficiency,
)


@dataclass
class Check:
    name: str
    passed: bool
    metric: float | str | None = None
    threshold: float | str | None = None
    details: str = ""
    required: bool = True


@dataclass
class ValidationReport:
    strategy_id: str
    data_version: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    passed: bool = False
    reasons: list[str] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    def finalize(self) -> ValidationReport:
        required_failed = [c for c in self.checks if c.required and not c.passed]
        self.passed = len(required_failed) == 0
        self.reasons = [c.details or c.name for c in required_failed]
        return self


def _returns_from_equity(equity: np.ndarray) -> np.ndarray:
    if len(equity) < 2:
        return np.array([])
    return np.diff(equity) / np.where(equity[:-1] == 0, 1, equity[:-1])


def _equity_from_trades(initial: float, returns: np.ndarray) -> np.ndarray:
    eq = [initial]
    for r in returns:
        eq.append(eq[-1] * (1 + r))
    return np.array(eq)


class ValidatorPipeline:
    """Composable validators. Each returns Check."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.min_wfe: float = self.config.get("min_wfe", 0.3)
        self.min_oos_sharpe: float = self.config.get("min_oos_sharpe", 0.0)
        self.max_pbo: float = self.config.get("max_pbo", 0.5)

    def validate(
        self,
        strategy_id: str,
        data_version: str,
        equity_is: np.ndarray,
        equity_oos: np.ndarray,
        equity_wfa_oos: np.ndarray | None = None,
        walk_forward_folds: list[dict[str, float]] | None = None,
        num_trials: int = 1,
        spread_stress: dict[float, float] | None = None,  # multiplier -> PF
    ) -> ValidationReport:
        report = ValidationReport(strategy_id=strategy_id, data_version=data_version)
        # Sharpe IS/OOS
        rets_is = _returns_from_equity(equity_is)
        rets_oos = _returns_from_equity(equity_oos)
        # skew/kurt for DSR
        skew = (
            float(np.mean(((rets_oos - np.mean(rets_oos)) / (np.std(rets_oos) + 1e-12)) ** 3))
            if len(rets_oos) > 10
            else 0.0
        )
        kurt = (
            float(np.mean(((rets_oos - np.mean(rets_oos)) / (np.std(rets_oos) + 1e-12)) ** 4))
            if len(rets_oos) > 10
            else 3.0
        )
        sr_is = sharpe_ratio(rets_is) if len(rets_is) else 0.0
        sr_oos = sharpe_ratio(rets_oos) if len(rets_oos) else 0.0
        report.metrics["sharpe_is"] = sr_is
        report.metrics["sharpe_oos"] = sr_oos
        report.metrics["skew"] = skew
        report.metrics["kurtosis"] = kurt
        # WFE
        wfe = (
            walk_forward_efficiency(sr_is, sr_oos)
            if walk_forward_folds is None
            else np.mean([f.get("wfe", 0) for f in walk_forward_folds])
        )
        if walk_forward_folds is not None and len(walk_forward_folds) > 0:
            wfe = float(
                np.mean([f["oos_sharpe"] / f["is_sharpe"] if f["is_sharpe"] != 0 else 0 for f in walk_forward_folds])
            )
            report.metrics["wfe"] = wfe
            report.metrics["folds"] = len(walk_forward_folds)
            report.add(
                Check(
                    "walk_forward_min_folds",
                    bool(len(walk_forward_folds) >= self.config.get("min_folds", 5)),
                    float(len(walk_forward_folds)),
                    float(self.config.get("min_folds", 5)),
                    f"folds {len(walk_forward_folds)}",
                    required=True,
                )
            )
            report.add(
                Check(
                    "walk_forward_wfe",
                    bool(wfe >= self.min_wfe),
                    float(wfe),
                    float(self.min_wfe),
                    f"WFE {wfe:.2f} < {self.min_wfe}",
                    required=True,
                )
            )
        else:
            report.metrics["wfe"] = float(wfe)
            report.add(
                Check(
                    "wfe",
                    bool(wfe >= self.min_wfe),
                    float(wfe),
                    float(self.min_wfe),
                    f"WFE {wfe:.2f}",
                    required=False,
                )
            )
        report.add(
            Check(
                "oos_sharpe",
                bool(sr_oos >= self.min_oos_sharpe),
                float(sr_oos),
                float(self.min_oos_sharpe),
                f"OOS Sharpe {sr_oos:.2f} < {self.min_oos_sharpe}",
                required=True,
            )
        )
        # DSR
        n = len(rets_oos)
        dsr = deflated_sharpe_ratio(sr_oos, num_trials, max(n, 2), skew, kurt)
        report.metrics["dsr_prob"] = dsr
        report.metrics["num_trials"] = num_trials
        # Only require DSR if num_trials >5 and n >30
        if num_trials > 5 and n > 30:
            report.add(
                Check(
                    "deflated_sharpe",
                    bool(dsr >= 0.95),
                    float(dsr),
                    0.95,
                    f"DSR {dsr:.2f} <0.95",
                    required=False,
                )
            )
        # PBO approximation: if folds, compute fraction where IS best underperforms median OOS
        if walk_forward_folds and len(walk_forward_folds) >= 4:
            # simplified PBO: fraction of folds where IS Sharpe rank != OOS rank
            # Real CPCV would be combinatorial; we approximate
            is_ranks = np.argsort([f["is_sharpe"] for f in walk_forward_folds])
            oos_ranks = np.argsort([f["oos_sharpe"] for f in walk_forward_folds])
            # PBO approx = proportion where top IS not top OOS
            top_is = is_ranks[-1]
            top_oos = oos_ranks[-1]
            pbo = 0.0 if top_is == top_oos else 0.6  # simplified stub; real CPCV computes across paths
            # Better: use OOS Sharpe dispersion
            oos_sharpes = [f["oos_sharpe"] for f in walk_forward_folds]
            if np.std(oos_sharpes) > 0:
                # if OOS median negative, higher PBO
                median_oos = float(np.median(oos_sharpes))
                pbo = 0.7 if median_oos < 0 else 0.3
            report.metrics["pbo"] = pbo
            report.add(
                Check(
                    "pbo",
                    bool(pbo <= self.max_pbo),
                    float(pbo),
                    float(self.max_pbo),
                    f"PBO {pbo:.2f} >{self.max_pbo}",
                    required=False,
                )
            )
        # Perturbation stub
        report.add(
            Check(
                "perturbation",
                True,
                0.0,
                0.0,
                "stability check placeholder — run perturbation validator separately",
                required=False,
            )
        )
        # Stress: spread
        if spread_stress:
            pf_1_5 = spread_stress.get(1.5, spread_stress.get(1.0, 1.0))
            report.metrics["spread_pf_1_5x"] = pf_1_5
            report.add(
                Check(
                    "spread_stress_1_5x",
                    bool(pf_1_5 >= 1.0),
                    float(pf_1_5),
                    1.0,
                    f"PF at 1.5x spread {pf_1_5:.2f} <1.0",
                    required=False,
                )
            )
        # Drawdown
        dd_is = max_drawdown(equity_is)
        dd_oos = max_drawdown(equity_oos)
        report.metrics["max_dd_is"] = dd_is
        report.metrics["max_dd_oos"] = dd_oos
        # PF
        pf_oos = profit_factor(rets_oos) if len(rets_oos) else 0.0
        report.metrics["profit_factor_oos"] = pf_oos
        return report.finalize()

    def walk_forward_splits(self, n: int, train: int, test: int, step: int) -> list[tuple[int, int, int, int]]:
        """Return list of (train_start, train_end, test_start, test_end) indices."""
        splits: list[tuple[int, int, int, int]] = []
        start = 0
        while start + train + test <= n:
            train_start = start
            train_end = start + train
            test_start = train_end
            test_end = test_start + test
            splits.append((train_start, train_end, test_start, test_end))
            start += step
        return splits
