"""Phase 17: Real-time emergency controls — 10 independent safeguards."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class EmergencyConfig:
    max_order_rate_per_sec: int = 5
    max_order_size_lots: float = 1.0
    max_spread_bps: float = 100
    max_latency_ms: float = 2000
    max_data_staleness_s: float = 5.0


class EmergencyControls:
    def __init__(self, config: EmergencyConfig | None = None):
        self.config = config or EmergencyConfig()
        self._order_times: deque[float] = deque()
        self._killed = False
        self._suspended = False

    def kill_switch(self, reason: str):
        self._killed = True

    def cancel_all(self, order_manager):
        order_manager.cancel_all_pending()

    def suspend_new_orders(self):
        self._suspended = True

    def check_order_rate(self) -> tuple[bool, str]:
        now = time.time()
        # prune >1 sec
        while self._order_times and now - self._order_times[0] > 1.0:
            self._order_times.popleft()
        if len(self._order_times) >= self.config.max_order_rate_per_sec:
            return False, "max_order_rate"
        self._order_times.append(now)
        return True, "ok"

    def check_order_size(self, qty: Decimal) -> tuple[bool, str]:
        if float(qty) > self.config.max_order_size_lots:
            return False, "max_order_size"
        return True, "ok"

    def check_spread(self, spread_bps: float) -> tuple[bool, str]:
        if spread_bps > self.config.max_spread_bps:
            return False, "abnormal_spread_stop"
        return True, "ok"

    def check_latency(self, latency_ms: float) -> tuple[bool, str]:
        if latency_ms > self.config.max_latency_ms:
            return False, "execution_latency_stop"
        return True, "ok"

    def check_data_staleness(self, age_s: float) -> tuple[bool, str]:
        if age_s > self.config.max_data_staleness_s:
            return False, "stale_data_stop"
        return True, "ok"

    def check_account_state(self, account) -> tuple[bool, str]:
        # account equity/balance missing or negative
        try:
            if account.equity <= Decimal("0") or account.balance <= Decimal("0"):
                return False, "account_state_stop"
        except Exception:
            return False, "account_state_stop"
        return True, "ok"

    def check_reconciliation(self, is_suspended: bool) -> tuple[bool, str]:
        if is_suspended:
            return False, "reconciliation_stop"
        return True, "ok"

    def pre_trade_gate(
        self, qty: Decimal, spread_bps: float, latency_ms: float, data_age_s: float, account, is_suspended: bool
    ) -> tuple[bool, str]:
        for check in [
            self.check_order_rate,
            lambda: self.check_order_size(qty),
            lambda: self.check_spread(spread_bps),
            lambda: self.check_latency(latency_ms),
            lambda: self.check_data_staleness(data_age_s),
            lambda: self.check_account_state(account),
            lambda: self.check_reconciliation(is_suspended),
        ]:
            ok, reason = check()
            if not ok:
                return False, reason
        if self._killed or self._suspended:
            return False, "killed_or_suspended"
        return True, "ok"

    def is_killed(self) -> bool:
        return self._killed
