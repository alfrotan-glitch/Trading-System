"""Registered DEMO forward research policy: the execution-cost probe.

What this is
------------
A **measurement instrument**, not a trading strategy. It exists because the
system has no validated edge (every preregistered XAUUSD hypothesis in
``reports/xauusd_*_state.json`` is REJECTED or INCONCLUSIVE with
``strategy_promoted=false``), and because no strategy can be evaluated
honestly without first measuring what the DEMO venue *costs* to trade.

It emits a minimum-size, stop-protected, time-boxed round turn at a fixed
wall-clock cadence and records the full execution record: requested price,
executed price, spread, slippage, latency, stop behaviour, exit reason,
realized P&L. That is the entire object of study.

What it is NOT
--------------
* **not a signal** — there is no indicator, no pattern, no prediction. The
  entry is scheduled; direction alternates by parity of the UTC hour so the
  sample set carries no net directional exposure. Any P&L it produces is a
  property of the venue's cost structure plus noise, not of a hypothesis.
* **not optimisable** — parameters are frozen in the registry entry and hashed
  (``config_hash``), and the module source is hashed (``code_hash``). The
  autopilot halts on either drift.
* **not evidence of an edge** — see the registry entry's ``edge_statement``.
  Forward observations recorded here must never be used to re-fit this policy
  or to select another strategy.

Determinism
-----------
The schedule is derived from UTC wall-clock time, not from randomness or from
provider state, so two runs at the same time make the same decision. Provider
state only suppresses a second emission inside the same sampling window; after
a restart that suppression is lost, which is why the daily order cap, the
minimum order interval and the idempotent ``client_order_id`` are the binding
protections — they, not provider memory, bound the exposure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from qts.execution.demo_autopilot import Signal

STRATEGY_ID = "DEMO-EXECPROBE-XAUUSD-V1"

#: Frozen parameters. The registry entry's ``params`` must equal this dict
#: exactly — its fingerprint is the registered ``config_hash``, and the gate
#: refuses the order on any drift.
DEFAULT_PARAMS: dict[str, Any] = {
    "sample_interval_minutes": 60,
    "side_rule": "utc_hour_parity",  # even UTC hour -> BUY, odd -> SELL
    "stop_distance_price": 2.00,
    "take_profit": None,
    "max_hold_seconds": 900,
    "require_spread_within_policy": True,
    "require_fresh_quote": True,
    "max_tick_age_s": 5.0,
    "lots": 0.01,
    "comment": "RESEARCH_DEMO_ORDER execution-cost probe",
}


def _utc_now(market_state: dict[str, Any] | None = None) -> datetime:
    """Clock source: the venue quote timestamp when present, else UTC now.

    The quote timestamp is preferred so the decision is a function of market
    time rather than of when the loop happened to poll.
    """
    stamp = (market_state or {}).get("at")
    if stamp:
        try:
            moment = datetime.fromisoformat(str(stamp))
        except (TypeError, ValueError):
            moment = None
        if moment is not None:
            return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _config_hash(params: dict[str, Any]) -> str:
    from qts.lifecycle.demo_registry import params_fingerprint

    return params_fingerprint(params)


class ExecutionCostProbe:
    """Emit one scheduled, stop-protected, time-boxed round turn per window.

    Deliberately exposes no ``optimize``/``fit``/``tune``/``search``/
    ``calibrate`` attribute: the autopilot refuses any provider that does,
    because a provider that can re-fit itself on forward DEMO results is a
    research-integrity violation, not a feature.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = dict(DEFAULT_PARAMS if params is None else params)
        self._emitted_windows: set[str] = set()
        self._last_rationale: str = "no sampling window evaluated yet"

    @property
    def strategy_id(self) -> str:
        return STRATEGY_ID

    def config_hash(self) -> str:
        return _config_hash(self.params)

    def last_rationale(self) -> str:
        return self._last_rationale

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        """Return the scheduled probe order, or ``None`` with a recorded reason."""
        now = _utc_now(market_state)
        interval = int(self.params.get("sample_interval_minutes") or 60)
        window = f"{now:%Y%m%dT%H}" if interval >= 60 else f"{now:%Y%m%dT%H%M}-{now.minute // max(interval, 1)}"

        if not market_state.get("bid") or not market_state.get("ask"):
            self._last_rationale = "no executable quote — nothing to measure"
            return None

        if self.params.get("require_fresh_quote") is not False:
            age = market_state.get("age_s")
            cap = float(self.params.get("max_tick_age_s") or 5.0)
            if age is None or float(age) > cap:
                self._last_rationale = f"quote age {age}s exceeds the {cap}s freshness requirement"
                return None

        spread_bps = market_state.get("spread_bps")
        if self.params.get("require_spread_within_policy") is not False and spread_bps is None:
            self._last_rationale = "spread not measurable — cost cannot be bounded"
            return None

        if window in self._emitted_windows:
            self._last_rationale = f"sampling window {window} already sampled"
            return None

        side = "BUY" if (now.hour % 2 == 0) else "SELL"
        reference = Decimal(str(market_state["ask" if side == "BUY" else "bid"]))
        distance = Decimal(str(self.params.get("stop_distance_price") or 0))
        stop = reference - distance if side == "BUY" else reference + distance
        lots = Decimal(str(self.params.get("lots") or "0.01"))

        self._emitted_windows.add(window)
        self._last_rationale = (
            f"scheduled execution-cost probe: window {window}, side {side} by UTC-hour parity "
            f"(no directional claim), stop {distance} from {reference}, size {lots} lots"
        )
        return Signal(
            side=side,
            lots=lots,
            stop_loss=stop,
            take_profit=None,
            rationale=self._last_rationale,
            signal_id=f"probe-{window}-{side.lower()}",
        )
