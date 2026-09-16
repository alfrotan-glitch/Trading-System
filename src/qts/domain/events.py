"""Domain events — immutable, time-ordered."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from qts.domain.value_objects import uuid7


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventType(StrEnum):
    BAR = "BarReceived"
    TICK = "TickReceived"
    SIGNAL = "SignalGenerated"
    ORDER_INTENT = "OrderIntentCreated"
    RISK_VETO = "RiskVeto"
    ORDER_EVENT = "OrderEvent"
    FILL = "Fill"
    POSITION_UPDATE = "PositionUpdate"
    ACCOUNT_UPDATE = "AccountUpdate"
    RECONCILE = "ReconcileReport"
    KILL_SWITCH = "KillSwitchEvent"
    LIFECYCLE = "LifecycleTransition"
    DATA_QUALITY = "DataQualityAlert"


class DomainEvent(BaseModel):
    model_config = {"frozen": True}

    event_id: str = Field(default_factory=uuid7)
    event_type: EventType
    event_time: datetime = Field(default_factory=_utc_now)
    recorded_at: datetime = Field(default_factory=_utc_now)
    source: str = "qts"
    version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    code_version: str = "0.1.0"
    data_version: str | None = None

    @field_validator("event_time", "recorded_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("datetime must be tz-aware")
        return v.astimezone(UTC)
