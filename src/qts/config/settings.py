"""Typed settings with env separation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class DataConfig(BaseModel):
    root: Path = Path("data")
    timeframe: str = "1m"


class ExecutionConfig(BaseModel):
    mode: Literal["backtest", "paper", "shadow", "live", "dry_run", "micro"] = "backtest"
    reconcile_interval_s: int = 30
    order_timeout_s: int = 10
    max_retries: int = 3
    spread_bps: float = 3.0
    slippage_bps: float = 2.0
    execution_delay_ms: int = 500
    commission_per_lot: float = 0.0
    partial_fill_model: Literal["none", "volume_based"] = "none"


class RiskConfig(BaseModel):
    max_quantity: float = 1.0
    max_notional: float = 10000.0
    max_risk_per_trade_bps: float = 50.0
    stop_loss_required: bool = False
    max_exposure: float = 2.0
    max_leverage: float = 5.0
    max_correlated_exposure: float = 1.5
    max_open_orders: int = 5
    daily_loss_limit: float = 200.0
    max_drawdown: float = 500.0
    volatility_target: float | None = None
    kill_switch_enabled: bool = True
    flatten_on_kill: bool = False
    approved: bool = False


class ValidationConfig(BaseModel):
    # Single coherent policy — all gates (ValidatorPipeline, CLI, Lifecycle, docs) must use these
    train_ratio: float = 0.6
    val_ratio: float = 0.2
    holdout_ratio: float = 0.2
    walk_forward_train: str = "12M"
    walk_forward_test: str = "3M"
    walk_forward_step: str = "3M"
    min_folds: int = 5
    min_wfe: float = 0.30
    min_oos_sharpe: float = 0.30  # blocks materially negative or flat OOS; null/no-edge ~0 fails
    max_pbo: float = 0.50
    max_perturbation_drop: float = 0.30  # 30% Sharpe drop under ±10/20% fragility
    min_spread_pf: float = 1.0  # PF at 1.5× spread must remain >=1.0
    spread_stress_levels: list[float] = Field(default_factory=lambda: [1.0, 1.5, 2.0])  # type: ignore[arg-type]
    slippage_stress_bps: list[float] = Field(default_factory=lambda: [0, 2, 5, 10])  # type: ignore[arg-type]
    cpcv_min_combos: int = 6  # must match cpcv_splits generation (n_groups=6,n_test=2 ->15 combos)
    perturbation_min_variants: int = 7  # ±5/10/20% + baseline


class ShipperConfig(BaseModel):
    enabled: bool = False
    type: str = "local"  # local | s3
    bucket: str | None = None
    prefix: str = "qts/audit/"
    local_root: Path = Path("data/shipped")
    region: str | None = None

class ObservabilityConfig(BaseModel):
    audit_jsonl: Path = Path("logs/audit.jsonl")
    http_enabled: bool = False
    shipper: ShipperConfig = ShipperConfig()


class Settings(BaseModel):
    env: Literal["dev", "paper", "live"] = "dev"
    data: DataConfig = Field(default_factory=DataConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    confirm_live: bool = False
    strict_quality: bool = True  # fail closed on data quality fail

    def assert_live_allowed(self) -> None:
        if self.execution.mode == "live":
            if self.env != "live":
                raise ValueError("live mode requires env=live (fail closed)")
            if not self.confirm_live:
                raise ValueError("live mode requires --confirm live")
            if not self.risk.approved:
                raise ValueError("live mode requires risk.approved=true")

    def assert_micro_allowed(self) -> None:
        if self.execution.mode == "micro":
            import os
            if os.getenv("QTS_MICRO_ENABLED") != "true":
                raise ValueError("micro mode requires QTS_MICRO_ENABLED=true (fail closed)")
            if self.env != "live":
                raise ValueError("micro mode requires env=live")
            if not self.confirm_live:
                raise ValueError("micro mode requires --confirm live")
            if not self.risk.approved:
                raise ValueError("micro mode requires risk.approved=true")



def load_settings(path: str | Path | None = None, env: str | None = None) -> Settings:
    if path is None:
        env = env or os.getenv("QTS_ENV", "dev")  # type: ignore[assignment]
        cand = Path(f"configs/{env}.yaml")
        if cand.exists():
            path = cand
        else:
            return Settings(env=env)  # type: ignore[arg-type]
    p = Path(path)
    if not p.exists():
        return Settings()
    data = yaml.safe_load(p.read_text()) or {}
    if env:
        data["env"] = env
    return Settings.model_validate(data)
