"""Domain value objects — immutable, validated, zero dependencies."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError(f"datetime must be tz-aware (UTC), got naive: {dt!r}")
    return dt.astimezone(UTC)


def uuid7() -> str:
    """Return a random 128-bit identifier as 32 lowercase hex characters.

    NAMING WARNING — read before relying on ordering. Despite the name this is
    **not** UUIDv7 and **not** time-ordered; it is exactly ``uuid.uuid4().hex``:

    * random, with no embedded timestamp — lexicographic order of these ids
      carries NO information about creation order;
    * unhyphenated 32-char hex rather than the canonical 8-4-4-4-12 form, so
      ``uuid.UUID(value)`` parses it but ``str(uuid.UUID(value)) != value``;
    * version/variant bits are random, so nothing marks the value as version 7.

    The previous comments here claimed a "uuid1 + uuid4 fallback", a "time
    prefix" and deterministic ordering for tests. None of that was in the
    implementation, and the claim is dangerous: a reader could reasonably sort
    by these ids and get an arbitrary order for orders, fills, events and
    observation records.

    The misleading name is retained because ~20 call sites across execution,
    observability, regime and research modules import it, and changing the
    emitted format would silently mix id formats with values already persisted
    in SQLite/Parquet and recorded in committed evidence artifacts. Correcting
    the documentation is the non-destructive fix; changing the format is a
    deliberate, versioned data-format change that needs an owner decision.

    CONTRACT: ordering must always come from an explicit timestamp column
    (``created_at``, ``open_time``, ``event_time``), never from these ids. If
    monotonic k-sortable identifiers ever become a requirement, adopt a real
    UUIDv7 generator deliberately rather than assuming this function provides
    one.
    """
    return uuid.uuid4().hex


class AssetClass(StrEnum):
    FX = "FX"
    METAL = "METAL"
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"
    CRYPTO = "CRYPTO"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderState(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"  # transport failure/timeout — unknown if venue accepted, fail closed
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class Instrument(BaseModel):
    model_config = {"frozen": True}

    symbol: str
    venue: str = "MT5"
    asset_class: AssetClass = AssetClass.METAL
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal("0.01")
    contract_size: Decimal = Decimal("100")

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol empty")
        return v

    @field_validator("tick_size", "lot_size", "contract_size")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("must be >0")
        return v


class Bar(BaseModel):
    model_config = {"frozen": True}

    instrument: Instrument
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")
    open_time: datetime
    close_time: datetime
    data_version: str = "v0"
    source: str = "unknown"

    @field_validator("open_time", "close_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @model_validator(mode="after")
    def _invariants(self) -> Bar:
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be < close_time")
        if self.high < max(self.open, self.high, self.low, self.close):
            raise ValueError("high must be >= all OHLC")
        if self.low > min(self.open, self.high, self.low, self.close):
            raise ValueError("low must be <= all OHLC")
        if self.high < self.low:
            raise ValueError("high < low")
        # no NaN for Decimal; check for None already
        return self

    def quantize(self) -> Bar:
        # quantize to tick_size if needed
        ts = self.instrument.tick_size

        def q(d: Decimal) -> Decimal:
            return (d / ts).to_integral_value(rounding=ROUND_HALF_UP) * ts

        return self.model_copy(
            update={
                "open": q(self.open),
                "high": q(self.high),
                "low": q(self.low),
                "close": q(self.close),
            }
        )


class Tick(BaseModel):
    model_config = {"frozen": True}

    instrument: Instrument
    bid: Decimal
    ask: Decimal
    last: Decimal | None = None  # last trade price if available
    bid_size: Decimal = Decimal("0")
    ask_size: Decimal = Decimal("0")
    event_time: datetime  # canonical: timestamp
    tick_type: str = "unknown"  # e.g., quote, trade, bid, ask
    session: str = "unknown"  # e.g., London, NY, Asian, weekend_closed
    # Fail-closed: callers must explicitly label verified market evidence.
    # Bare domain ticks are commonly used by tests/adapters and must never
    # become REAL merely because the source argument was omitted.
    source: str = "UNVERIFIED"  # REAL/SYNTHETIC/SIMULATED/ESTIMATED/IMPUTED/BROKER-DERIVED/MODEL-DERIVED/DEMO/UNVERIFIED
    # Broker-timestamp provenance (optional): raw server-basis stamps, the
    # measured server<->UTC offset and its basis, broker symbol, receipt time.
    # Makes the normalized event_time auditable; None for non-broker ticks.
    provenance: dict[str, Any] | None = None

    @field_validator("event_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("source")
    @classmethod
    def _source_label(cls, v: str) -> str:
        allowed = {
            "REAL",
            "SYNTHETIC",
            "SIMULATED",
            "ESTIMATED",
            "IMPUTED",
            "BROKER-DERIVED",
            "MODEL-DERIVED",
            "DEMO",
            "UNVERIFIED",
        }
        up = v.strip().upper()
        if up not in allowed:
            raise ValueError(f"source must be one of {allowed}, got {v!r}")
        return up

    @model_validator(mode="after")
    def _spread(self) -> Tick:
        if self.ask < self.bid:
            raise ValueError(f"ask {self.ask} < bid {self.bid}")
        # Never manufacture real bid/ask from OHLC: if source REAL but bid derived from mid, caller must label SYNTHETIC
        return self

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


class Signal(BaseModel):
    model_config = {"frozen": True}

    instrument: Instrument
    side: Side
    strength: float = Field(ge=-1, le=1)
    event_time: datetime
    hypothesis_id: str = "H-000"
    strategy_id: str = "unknown"
    features: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class OrderIntent(BaseModel):
    model_config = {"frozen": True}

    instrument: Instrument
    side: Side
    quantity: Decimal  # in units (oz for XAUUSD); adapter converts to lots
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    client_order_id: str
    strategy_id: str
    signal_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("quantity")
    @classmethod
    def _qty_pos(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("quantity must be >0")
        return v

    @model_validator(mode="after")
    def _prices(self) -> OrderIntent:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT requires limit_price")
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("STOP requires stop_price")
        return self


class Order(BaseModel):
    model_config = {"frozen": True}

    order_id: str
    client_order_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    order_type: OrderType
    state: OrderState = OrderState.PENDING
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    strategy_id: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    exchange_order_id: str | None = None
    reject_reason: str | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    def with_state(self, state: OrderState, **kwargs: Any) -> Order:
        return self.model_copy(update={"state": state, "updated_at": _utc_now(), **kwargs})


class Fill(BaseModel):
    model_config = {"frozen": True}

    fill_id: str
    order_id: str
    client_order_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    liquidity: str = "Taker"
    event_time: datetime = Field(default_factory=_utc_now)

    @field_validator("event_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("quantity")
    @classmethod
    def _pos(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("fill quantity >0")
        return v


class Position(BaseModel):
    model_config = {"frozen": True}

    instrument: Instrument
    quantity: Decimal  # signed: + long, - short
    avg_price: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("updated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class Account(BaseModel):
    model_config = {"frozen": True}

    balance: Decimal
    equity: Decimal
    margin: Decimal = Decimal("0")
    free_margin: Decimal = Decimal("0")
    # NO fabricated defaults: ``None`` means UNAVAILABLE (broker did not
    # provide it). Safety-critical consumers must treat None as unknown and
    # fail closed — never substitute a guessed leverage or currency.
    leverage: Decimal | None = None
    currency: str | None = None
    #: Provenance of this account state: BROKER | PAPER_SIMULATION | UNKNOWN.
    source: str = "UNKNOWN"
    #: Local RECEIPT time. NOT a broker timestamp — MT5 account_info carries
    #: no server stamp, so account freshness is bounded by receipt time; this
    #: limitation is explicit and documented (docs/mt5_demo_setup.md).
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("updated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class Money(BaseModel):
    model_config = {"frozen": True}

    amount: Decimal
    currency: str = "USD"
