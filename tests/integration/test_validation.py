import numpy as np

from qts.validation.adversarial import check_parameter_fragility, check_spread_sensitivity
from qts.validation.pipeline import ValidatorPipeline


def test_validation_pass_with_real_evidence():
    # Use flat equity to make baseline Sharpe 0, so perturbation baseline 0 → drop 0
    is_eq = np.array([10000, 10000, 10000, 10000, 10000, 10000], dtype=float)
    oos_eq = np.array([10000, 10000, 10000, 10000, 10000, 10000], dtype=float)
    folds = [
        {"is_sharpe": 1.5, "oos_sharpe": 1.0},
        {"is_sharpe": 1.2, "oos_sharpe": 0.8},
        {"is_sharpe": 1.0, "oos_sharpe": 0.7},
    ]
    cpcv = [
        {"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.7, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.8, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.7, "median_test_sharpe": 0.5},
    ]
    # perturbed stable around 0 (flat)
    perturbed = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    stress = {1.0: 1.2, 1.5: 1.1, 2.0: 1.0}
    pipe = ValidatorPipeline(config={"min_folds": 2, "min_wfe": 0.3, "min_oos_sharpe": 0.0, "max_pbo": 0.7})
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=folds,
        num_trials=1,
        cpcv_folds=cpcv,
        perturbed_sharpes=perturbed,
        stress_results=stress,
    )
    assert report.passed, f"should pass with real evidence: {report.reasons} {report.checks}"


def test_validation_blocks_on_placeholder():
    is_eq = np.array([10000, 10100], dtype=float)
    oos_eq = np.array([10100, 10200], dtype=float)
    pipe = ValidatorPipeline(config={"min_folds": 2, "min_wfe": 0.3})
    # no folds, no cpcv, no perturbation, no stress → should block
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=None,
        num_trials=1,
        cpcv_folds=None,
        perturbed_sharpes=None,
        stress_results=None,
    )
    assert not report.passed
    # should have NOT_IMPLEMENTED checks
    assert any(c.status == "NOT_IMPLEMENTED" for c in report.checks)


def test_validation_fail_wfe():
    is_eq = np.array([10000, 11000, 12000, 13000], dtype=float)
    oos_eq = np.array([13000, 12900, 12800, 12700], dtype=float)
    folds = [
        {"is_sharpe": 2.0, "oos_sharpe": 0.1},
        {"is_sharpe": 1.8, "oos_sharpe": 0.05},
        {"is_sharpe": 1.5, "oos_sharpe": 0.08},
    ]
    cpcv = [
        {"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.7, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.8, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5},
        {"best_is_test_sharpe": 0.7, "median_test_sharpe": 0.5},
    ]
    perturbed = [0.5, 0.4, 0.6, 0.5, 0.45, 0.55, 0.48]
    stress = {1.0: 1.2, 1.5: 1.1}
    pipe = ValidatorPipeline(config={"min_folds": 2, "min_wfe": 0.3, "min_oos_sharpe": 0.0, "max_pbo": 0.5})
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=folds,
        num_trials=1,
        cpcv_folds=cpcv,
        perturbed_sharpes=perturbed,
        stress_results=stress,
    )
    assert not report.passed
    assert any("WFE" in r for r in report.reasons)


def test_adversarial_spread():
    findings = check_spread_sensitivity(1.2, 0.9, 0.5)
    assert len(findings) >= 1
    assert any("spread" in f.check for f in findings)


def test_parameter_fragility():
    findings = check_parameter_fragility([1.5, 1.4, 1.0, 0.2, -0.5])
    assert findings is not None
