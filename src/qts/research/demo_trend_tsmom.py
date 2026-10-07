"""Publicly documented trend-following benchmark for DEMO forward observation.

This is deliberately a simple, frozen implementation inspired by publicly
documented managed-futures/time-series-momentum practice (fast/slow trend
response, small fixed risk, protective stop). It is NOT represented as a
validated edge and must remain a DEMO research policy until independent
validation passes.

No proprietary code or private fund parameters are copied.

Frozen signal semantics
-----------------------
* XAUUSD, 15-minute bars, **completed bars only** — a partial bar is never
  evaluated, and intra-bar quotes only move the current bar's close;
* EMA(12) / EMA(48) over completed-bar closes (mid of the two-sided quote);
* one directional signal per completed-bar crossover, identified by the
  completed-bar boundary (``signal_id`` is ``tsmom-<side>-<YYYYMMDDTHHMMSSZ>``,
  the instant the bar completed), so the same bar can never produce two signals;
* fixed DEMO size, protective stop, no take-profit (enforced by the registered
  policy, mirrored in :data:`DEFAULT_PARAMS`);
* a quote must be two-sided, fresh, and carry a usable timestamp.

Restart recovery
----------------
The signal needs ``slow_ema + 1`` completed bars before a crossover can be
detected. Waiting for those bars live costs roughly twelve hours, so on DEMO
startup the strategy may be *seeded* with a bounded window of recent **completed**
bars taken from the terminal's own M15 history
(:meth:`MT5Adapter.recent_closed_bars`). Seeding:

* accepts only bars that are provably completed (the forming bar is excluded);
* never fabricates, interpolates or re-labels a bar;
* never evaluates a boundary and therefore never emits a signal;
* is a startup-only operation (refused once live quotes have been consumed);
* leaves the strategy in its normal "warming up" state if the window is short,
  unavailable, or fails validation — the loop then warms up from live quotes.

Because the benchmark's exponential averages are evaluated over the last
``period`` completed closes, a bounded window of ``slow_ema + 1`` bars
reconstructs the *exact* state a continuously running strategy would hold.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from qts.adapters.base import MEASURED_SERVER_OFFSET_BASES
from qts.execution.demo_autopilot import Signal

STRATEGY_ID = "DEMO-XAUUSD-TREND-TSMOM-V1"

#: Frozen parameter set. This mapping is the single source of truth: the
#: registry's ``params``/``params_hash``, the policy's ``config_hash`` and the
#: runtime ``config_hash()`` must all agree with it exactly (types included).
DEFAULT_PARAMS: dict[str, Any] = {
    "fast_ema": 12,
    "slow_ema": 48,
    "stop_distance_price": 3.0,
    "max_hold_seconds": 14400,
    "max_tick_age_s": 5.0,
    "bar_timeframe_minutes": 15,
    "lots": 0.01,
    "require_spread_within_policy": True,
    "comment": "RESEARCH_DEMO_ORDER trend benchmark",
}

#: Canonical broker-clock bases (see qts.adapters.base). History may only be
#: seeded from a clock whose offset was actually measured.
_MEASURED_BASIS = MEASURED_SERVER_OFFSET_BASES


def _hash(params: dict[str, Any]) -> str:
    from qts.lifecycle.demo_registry import params_fingerprint

    return params_fingerprint(params)


class TrendTimeSeriesMomentum:
    """Frozen EMA crossover benchmark with deterministic DEMO risk controls."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = dict(DEFAULT_PARAMS if params is None else params)
        self._fast_n = int(self.params["fast_ema"])
        self._slow_n = int(self.params["slow_ema"])
        if self._fast_n < 2 or self._slow_n <= self._fast_n:
            raise ValueError("fast_ema must be >= 2 and slow_ema must be greater than fast_ema")
        self._timeframe_minutes = self._valid_timeframe(self.params["bar_timeframe_minutes"])
        self._max_tick_age_s = float(self.params["max_tick_age_s"])
        self._require_spread = bool(self.params["require_spread_within_policy"])
        #: Completed bar closes. Bounded exactly as the semantics require: the
        #: benchmark's EMAs read only the last ``period`` closes, so
        #: ``slow_ema + 1`` closes reproduce a continuous run's state.
        self._closes: deque[Decimal] = deque(maxlen=self._slow_n + 1)
        #: Boundary (start) of the bar currently forming, and its latest close.
        #: Both are advanced by *quotes*, never by the execution polling clock.
        self._bar_start: datetime | None = None
        self._bar_close: Decimal | None = None
        #: Newest completed bar boundary observed (seeded or completed live).
        self._last_completed_bar: datetime | None = None
        #: Boundary of the last completed bar that produced a signal.
        self._last_signal_bar: datetime | None = None
        self._last_fast: Decimal | None = None
        self._last_slow: Decimal | None = None
        self._signals = 0
        self._bar_gaps = 0
        self._clock_basis: str | None = None
        self._provenance: dict[str, Any] = {"source": "none", "bars": 0}
        self._last_rationale = "no completed bars yet"

    # ------------------------------------------------------------- identity
    @property
    def strategy_id(self) -> str:
        return STRATEGY_ID

    def config_hash(self) -> str:
        return _hash(self.params)

    def last_rationale(self) -> str:
        return self._last_rationale

    @property
    def bar_timeframe_minutes(self) -> int:
        return self._timeframe_minutes

    @property
    def completed_bars(self) -> int:
        """Number of completed bars currently in EMA history."""
        return len(self._closes)

    @property
    def signals_emitted(self) -> int:
        return self._signals

    def history_provenance(self) -> dict[str, Any]:
        """Where the seeded history came from (empty history reads ``none``)."""
        out = dict(self._provenance)
        out["completed_bars"] = len(self._closes)
        out["last_completed_bar"] = (
            self._last_completed_bar.isoformat() if self._last_completed_bar else None
        )
        out["bar_gaps"] = self._bar_gaps
        return out

    def warmup_plan(self) -> dict[str, Any]:
        """Bounded completed-bar window that makes the strategy signal-ready."""
        return {
            "timeframe_minutes": self._timeframe_minutes,
            "bars": self._slow_n + 1,
            "completed_only": True,
        }

    # ---------------------------------------------------------------- seeding
    def seed_completed_bars(
        self,
        bars: Iterable[tuple[datetime, Decimal | str]],
        *,
        source: str = "unstated",
    ) -> dict[str, Any]:
        """Seed EMA history from *completed* bars. Never evaluates, never signals.

        Returns a provenance record (``accepted`` plus counts/reason). Invalid
        input is refused as a whole: a partially applied history would be a
        history nobody registered.
        """
        if self._bar_start is not None or self._closes:
            return {
                "accepted": False,
                "bars": len(self._closes),
                "reason": "history already active — seeding is a startup-only operation",
            }

        normalised: list[tuple[datetime, Decimal]] = []
        problems: list[str] = []
        previous: datetime | None = None
        for item in bars:
            try:
                raw_boundary, raw_close = item
            except (TypeError, ValueError):
                problems.append(f"malformed bar {item!r}")
                continue
            boundary = self._coerce_boundary(raw_boundary)
            if boundary is None:
                problems.append(f"bar {raw_boundary!r} is not a timezone-aware boundary timestamp")
                continue
            if self._bar_bucket(boundary) != boundary:
                problems.append(f"bar {boundary.isoformat()} is not aligned to the frozen {self._timeframe_minutes}m grid")
                continue
            close = self._coerce_close(raw_close)
            if close is None:
                problems.append(f"bar {boundary.isoformat()} has no usable close price")
                continue
            if previous is not None and boundary <= previous:
                problems.append(f"bar {boundary.isoformat()} is not strictly newer than {previous.isoformat()}")
                continue
            previous = boundary
            normalised.append((boundary, close))

        if problems:
            return {"accepted": False, "bars": len(self._closes), "reason": "; ".join(problems)}
        if not normalised:
            return {"accepted": False, "bars": 0, "reason": "no completed bars supplied"}

        limit = self._slow_n + 1
        supplied = len(normalised)
        window = normalised[-limit:]
        self._closes.extend(close for _boundary, close in window)
        self._last_completed_bar = window[-1][0]
        self._provenance = {
            "source": str(source),
            "bars": len(window),
            "supplied_bars": supplied,
            "truncated": supplied > len(window),
            "first_bar": window[0][0].isoformat(),
            "last_bar": window[-1][0].isoformat(),
            "completed_only": True,
        }
        if len(self._closes) < self._slow_n + 1:
            self._last_rationale = (
                f"seeded {len(self._closes)}/{self._slow_n + 1} completed bars from {source}"
            )
        else:
            self._last_rationale = f"history seeded from {source}: {len(self._closes)} completed bars"
        return {"accepted": True, "bars": len(self._closes), **{k: v for k, v in self._provenance.items()}}

    # --------------------------------------------------------------- bars
    def _valid_timeframe(self, raw: Any) -> int:
        try:
            minutes = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bar_timeframe_minutes must be an integer, got {raw!r}") from exc
        if minutes <= 0 or 60 % minutes != 0 or minutes > 60:
            raise ValueError("bar_timeframe_minutes must be a positive divisor of one hour")
        return minutes

    def _bar_bucket(self, moment: datetime) -> datetime:
        """Start of the ``timeframe_minutes`` bar containing ``moment`` (UTC)."""
        moment = moment.astimezone(UTC)
        minute = (moment.minute // self._timeframe_minutes) * self._timeframe_minutes
        return moment.replace(minute=minute, second=0, microsecond=0)

    @staticmethod
    def _coerce_boundary(raw: Any) -> datetime | None:
        if isinstance(raw, str):
            try:
                raw = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        if not isinstance(raw, datetime) or raw.tzinfo is None:
            return None
        return raw.astimezone(UTC)

    @staticmethod
    def _coerce_close(raw: Any) -> Decimal | None:
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return value if value.is_finite() and value > 0 else None

    @staticmethod
    def _ema(values: list[Decimal], period: int) -> Decimal:
        alpha = Decimal("2") / Decimal(period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = alpha * value + (Decimal("1") - alpha) * ema
        return ema

    # ------------------------------------------------------------- signals
    def _complete_previous_bar(self, boundary: datetime) -> str | None:
        """Append one completed bar and report a crossing side, if any."""
        assert self._bar_close is not None  # narrowed by the caller
        self._closes.append(self._bar_close)
        self._last_completed_bar = self._bar_start
        if len(self._closes) < self._slow_n + 1:
            self._last_rationale = (
                f"warming up: {len(self._closes)}/{self._slow_n + 1} completed bars"
            )
            return None

        values = list(self._closes)
        fast = self._ema(values[-self._fast_n :], self._fast_n)
        slow = self._ema(values[-self._slow_n :], self._slow_n)
        previous = values[:-1]
        prev_fast = self._ema(previous[-self._fast_n :], self._fast_n)
        prev_slow = self._ema(previous[-self._slow_n :], self._slow_n)
        self._last_fast, self._last_slow = fast, slow

        if prev_fast <= prev_slow and fast > slow:
            return "BUY"
        if prev_fast >= prev_slow and fast < slow:
            return "SELL"
        self._last_rationale = (
            f"no crossover at {boundary.isoformat()}: EMA{self._fast_n}={fast:.5f}, "
            f"EMA{self._slow_n}={slow:.5f}"
        )
        return None

    def _signal(
        self,
        *,
        side: str,
        boundary: datetime,
        bid: Decimal,
        ask: Decimal,
        basis: str | None,
    ) -> Signal | None:
        if self._last_signal_bar == boundary:
            # Structurally impossible for a single completion event, but a
            # replayed/duplicated boundary must never become a second order.
            self._last_rationale = f"crossover at {boundary.isoformat()} already signalled"
            return None
        self._last_signal_bar = boundary
        distance = Decimal(str(self.params["stop_distance_price"]))
        reference = ask if side == "BUY" else bid
        stop = reference - distance if side == "BUY" else reference + distance
        lots = Decimal(str(self.params["lots"]))
        basis_note = "" if basis in (None, *_MEASURED_BASIS) else f"; clock basis={basis}"
        self._last_rationale = (
            f"15m trend-following benchmark crossover: {side}; EMA{self._fast_n} crossed "
            f"EMA{self._slow_n} on the bar completed at {boundary.isoformat()}; fixed DEMO "
            f"size={lots}; protective stop distance={distance}; no validated-edge claim{basis_note}"
        )
        self._signals += 1
        # Compact UTC stamp: deterministic, sortable, and unambiguous to parse
        # (an ISO stamp with dashes cannot be recovered by splitting on "-").
        stamp = boundary.strftime("%Y%m%dT%H%M%SZ")
        return Signal(
            side=side,
            lots=lots,
            stop_loss=stop,
            take_profit=None,
            rationale=self._last_rationale,
            signal_id=f"tsmom-{side.lower()}-{stamp}",
        )

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        """Consume one quote. Signals only on a newly completed bar."""
        bid = self._coerce_close(market_state.get("bid"))
        ask = self._coerce_close(market_state.get("ask"))
        if bid is None or ask is None:
            self._last_rationale = "no two-sided quote"
            return None
        age = market_state.get("age_s")
        if age is not None and float(age) > self._max_tick_age_s:
            self._last_rationale = f"quote is stale: age={age}s"
            return None
        if self._require_spread and market_state.get("spread_bps") is None:
            self._last_rationale = "spread unavailable"
            return None

        moment = self._coerce_boundary(market_state.get("event_time") or market_state.get("at"))
        if moment is None:
            self._last_rationale = "quote timestamp unavailable or not timezone-aware"
            return None
        basis = market_state.get("timestamp_basis")
        if basis is not None:
            self._clock_basis = str(basis)

        bucket = self._bar_bucket(moment)
        mid = (bid + ask) / Decimal("2")

        if self._bar_start is None:
            # First live quote. History may have been seeded: the bar it ends
            # must be strictly newer than the newest seeded completed bar, or
            # the window itself was not completed-only.
            if self._last_completed_bar is not None and bucket <= self._last_completed_bar:
                self._last_rationale = (
                    f"refusing quote at {bucket.isoformat()}: not newer than the newest completed "
                    f"bar {self._last_completed_bar.isoformat()} (completed-only contract)"
                )
                return None
            self._bar_start = bucket
            self._bar_close = mid
            self._last_rationale = f"bar {bucket.isoformat()} opened; awaiting completion"
            return None

        if bucket < self._bar_start:
            # Out-of-order or re-labelled quote (broker clock change). Never
            # rewrite a completed bar; refuse and stay flat until the stream is
            # ordered again.
            self._last_rationale = (
                f"refusing out-of-order quote at {bucket.isoformat()}: current bar started "
                f"{self._bar_start.isoformat()}"
            )
            return None

        if bucket == self._bar_start:
            self._bar_close = mid
            self._last_rationale = f"bar {bucket.isoformat()} updated; awaiting completion"
            return None

        # A new bar began: the previous bar is now complete, exactly once.
        expected = self._bar_start + timedelta(minutes=self._timeframe_minutes)
        if bucket > expected:
            # Unobserved bars are counted, never fabricated: the EMA history
            # simply continues from the last bar that was actually observed.
            self._bar_gaps += 1
        side = self._complete_previous_bar(bucket)
        self._bar_start = bucket
        self._bar_close = mid
        if side is None:
            return None
        return self._signal(side=side, boundary=bucket, bid=bid, ask=ask, basis=basis)
