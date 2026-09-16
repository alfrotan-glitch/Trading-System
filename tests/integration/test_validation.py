import numpy as np

from qts.validation.adversarial import check_parameter_fragility, check_spread_sensitivity
from qts.validation.pipeline import ValidatorPipeline


def test_validation_pass():
    is_eq = np.array([10000, 10100, 10200, 10300, 10400], dtype=float)
    oos_eq = np.array([10400, 10500, 10600, 10700, 10800], dtype=float)
    folds = [
        {"is_sharpe": 1.5, "oos_sharpe": 1.0, "wfe": 0.66},
        {"is_sharpe": 1.2, "oos_sharpe": 0.8, "wfe": 0.66},
        {"is_sharpe": 1.0, "oos_sharpe": 0.7, "wfe": 0.7},
    ]
    pipe = ValidatorPipeline(config={"min_folds": 2, "min_wfe": 0.3, "min_oos_sharpe": 0.0})
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=folds,
        num_trials=1,
        spread_stress={1.5: 1.2},
    )
    assert report.passed


def test_validation_fail_wfe():
    is_eq = np.array([10000, 11000, 12000, 13000], dtype=float)
    oos_eq = np.array([13000, 12900, 12800, 12700], dtype=float)
    folds = [
        {"is_sharpe": 2.0, "oos_sharpe": 0.1, "wfe": 0.05},
        {"is_sharpe": 1.8, "oos_sharpe": 0.05, "wfe": 0.02},
    ]
    pipe = ValidatorPipeline(config={"min_folds": 2, "min_wfe": 0.3, "min_oos_sharpe": 0.0})
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=folds,
        num_trials=1,
    )
    assert not report.passed


def test_adversarial_spread():
    findings = check_spread_sensitivity(1.2, 0.9, 0.5)
    assert len(findings) >= 1
    assert any("spread" in f.check for f in findings)


def test_parameter_fragility():
    findings = check_parameter_fragility([1.5, 1.4, 1.0, 0.2, -0.5])
    assert findings is not None
