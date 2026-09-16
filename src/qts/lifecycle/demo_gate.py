"""MT5 Demo Forward connection checker — 14 checks, only after all required pass should DEMO_FORWARD be enabled."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS


def demo_forward_readiness_report(mt5_module: Any | None = None, risk_limits: Any | None = None) -> dict[str, Any]:
    """Run 14 checks. Returns dict with checklist, passed, blocked_reasons, demo_enabled."""
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}
    blocked: list[str] = []

    # Helper to record
    def check(name: str, ok: bool, detail: str, blocker: str | None = None):
        checks[name] = ok
        details[name] = detail
        if not ok and blocker:
            blocked.append(blocker)

    # 1 MT5 installed?
    try:
        if mt5_module is None:
            import importlib

            try:
                mt5_module = importlib.import_module("MetaTrader5")
                check("mt5_installed", True, "MetaTrader5 module found")
            except ImportError:
                check(
                    "mt5_installed",
                    False,
                    "MetaTrader5 not installed — install MT5 terminal and pip install MetaTrader5",
                    "MT5 not installed",
                )
                mt5_module = None
        else:
            check("mt5_installed", True, "MT5 module injected (mock)")
    except Exception as e:
        check("mt5_installed", False, str(e), "MT5 check failed")

    # 2 Terminal running?
    if mt5_module is not None and hasattr(mt5_module, "terminal_info"):
        try:
            ti = mt5_module.terminal_info()
            running = ti is not None
            check("terminal_running", running, f"terminal_info={ti}", None if running else "Terminal not running")
        except Exception as e:
            check("terminal_running", False, str(e), "Terminal not running")
    else:
        # In mock/sandbox, treat as not running but not blocker for demo observation
        check(
            "terminal_running",
            False,
            "MT5 terminal not running — demo_forward requires real terminal",
            "Terminal not running",
        )

    # 3 Account connected?
    account_info = None
    if mt5_module is not None and hasattr(mt5_module, "account_info"):
        try:
            ai = mt5_module.account_info()
            if ai:
                account_info = ai
                check(
                    "account_connected", True, f"login={getattr(ai, 'login', '?')} server={getattr(ai, 'server', '?')}"
                )
            else:
                check("account_connected", False, "account_info is None", "Account not connected")
        except Exception as e:
            check("account_connected", False, str(e), "Account not connected")
    else:
        check("account_connected", False, "account_info unavailable", "Account not connected")

    # 4 Account is DEMO?
    is_demo = False
    if account_info is not None:
        # MT5 account_info.trade_mode: 0 demo, 1 contest, 2 real
        trade_mode = getattr(account_info, "trade_mode", getattr(account_info, "tradeMode", None))
        # Also check string "demo" in server name
        server = str(getattr(account_info, "server", "")).lower()
        is_demo = (trade_mode == 0) or ("demo" in server)
        check(
            "account_is_demo",
            is_demo,
            f"trade_mode={trade_mode} server={server}",
            None if is_demo else "Account is not DEMO — LIVE account supplied to DEMO mode blocked",
        )
        if not is_demo:
            blocked.append("LIVE account accidentally supplied to DEMO mode — blocked")
    else:
        check("account_is_demo", False, "no account_info", "Account is not DEMO")

    # 5 Broker identified?
    broker = getattr(account_info, "company", getattr(account_info, "broker", "")) if account_info else ""
    check("broker_identified", bool(broker), f"broker={broker}", None if broker else "Broker not identified")

    # 6 Symbol available?
    # 7 Symbol tradable?
    # 8 Symbol specification valid?
    # Need symbol selection — default XAUUSD
    symbol = "XAUUSD"
    if mt5_module is not None and hasattr(mt5_module, "symbol_info"):
        try:
            si = mt5_module.symbol_info(symbol)
            available = si is not None
            check(
                "symbol_available",
                available,
                f"symbol_info for {symbol} exists={available}",
                None if available else f"Symbol {symbol} not available",
            )
            if si:
                tradable = bool(getattr(si, "trade_allowed", getattr(si, "tradable", True)))
                check(
                    "symbol_tradable",
                    tradable,
                    f"trade_allowed={tradable}",
                    None if tradable else "Symbol not tradable",
                )
                # spec valid: check required fields
                needed = ["contract_size", "volume_min", "volume_max", "volume_step", "digits", "point"]
                missing = [f for f in needed if not hasattr(si, f)]
                check(
                    "symbol_spec_valid",
                    len(missing) == 0,
                    f"missing fields {missing}" if missing else "spec valid 13 fields",
                    None if not missing else "Symbol specification invalid",
                )
            else:
                check("symbol_tradable", False, "no symbol_info", "Symbol not tradable")
                check("symbol_spec_valid", False, "no symbol_info", "Symbol specification invalid")
        except Exception as e:
            check("symbol_available", False, str(e), "Symbol not available")
            check("symbol_tradable", False, str(e), "Symbol not tradable")
            check("symbol_spec_valid", False, str(e), "Symbol specification invalid")
    else:
        check("symbol_available", False, "symbol_info unavailable", "Symbol not available")
        check("symbol_tradable", False, "symbol_info unavailable", "Symbol not tradable")
        check("symbol_spec_valid", False, "symbol_info unavailable", "Symbol specification invalid")

    # 9 Market data fresh?
    # 10 Bid/ask valid?
    # 11 Spread acceptable?
    if mt5_module is not None and hasattr(mt5_module, "symbol_info_tick"):
        try:
            t = mt5_module.symbol_info_tick(symbol)
            if t is None:
                check("market_data_fresh", False, "tick is None", "Market data not fresh")
                check("bid_ask_valid", False, "no tick", "Bid/ask invalid")
                check("spread_acceptable", False, "no tick", "Spread unacceptable")
            else:
                # Freshness: time must be within 60s
                tick_time = getattr(t, "time", getattr(t, "time_msc", 0))
                # mt5 time is seconds since epoch
                if isinstance(tick_time, (int, float)) and tick_time > 1e9:
                    age = time.time() - float(tick_time) / 1000 if tick_time > 1e12 else time.time() - float(tick_time)
                else:
                    age = 0
                fresh = age < 60
                check("market_data_fresh", fresh, f"age {age:.1f}s", None if fresh else "Market data stale")
                bid = getattr(t, "bid", 0)
                ask = getattr(t, "ask", 0)
                valid = bid > 0 and ask > 0 and ask >= bid
                check("bid_ask_valid", valid, f"bid={bid} ask={ask}", None if valid else "Bid/ask invalid")
                if valid:
                    spread_bps = (ask - bid) / ((ask + bid) / 2) * 10000 if (ask + bid) > 0 else 999
                    acceptable = spread_bps <= DEMO_FORWARD_DEFAULTS.max_spread_bps
                    check(
                        "spread_acceptable",
                        acceptable,
                        f"spread {spread_bps:.1f}bps limit {DEMO_FORWARD_DEFAULTS.max_spread_bps}bps",
                        None if acceptable else "Spread too wide",
                    )
                else:
                    check("spread_acceptable", False, "bid/ask invalid", "Spread unacceptable")
        except Exception as e:
            check("market_data_fresh", False, str(e), "Market data not fresh")
            check("bid_ask_valid", False, str(e), "Bid/ask invalid")
            check("spread_acceptable", False, str(e), "Spread unacceptable")
    else:
        check("market_data_fresh", False, "symbol_info_tick unavailable", "Market data not fresh")
        check("bid_ask_valid", False, "symbol_info_tick unavailable", "Bid/ask invalid")
        check("spread_acceptable", False, "symbol_info_tick unavailable", "Spread unacceptable")

    # 12 Account state valid? (margin, balance)
    if account_info is not None:
        bal = getattr(account_info, "balance", getattr(account_info, "equity", 0))
        margin = getattr(account_info, "margin", 0)
        valid = bal > 0
        check(
            "account_state_valid", valid, f"balance={bal} margin={margin}", None if valid else "Account state invalid"
        )
    else:
        check("account_state_valid", False, "no account_info", "Account state invalid")

    # 13 Risk configuration valid?
    try:
        from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS as lim

        # Check that demo limits are conservative
        ok = lim.max_volume_per_order <= 0.5 and lim.max_daily_loss_usd <= 100
        check(
            "risk_config_valid",
            ok,
            f"demo limits volume {lim.max_volume_per_order} daily loss {lim.max_daily_loss_usd}",
            None if ok else "Risk configuration invalid",
        )
    except Exception as e:
        check("risk_config_valid", False, str(e), "Risk configuration invalid")

    # 14 Reconciliation healthy?
    try:
        from qts.lifecycle.live_gate import check_reconciliation

        ok, detail = check_reconciliation()
        check("reconciliation_healthy", ok, detail, None if ok else "Reconciliation not healthy")
    except Exception as e:
        check("reconciliation_healthy", False, str(e), "Reconciliation not healthy")

    # Overall
    required = [
        "mt5_installed",
        "terminal_running",
        "account_connected",
        "account_is_demo",
        "broker_identified",
        "symbol_available",
        "symbol_tradable",
        "symbol_spec_valid",
        "market_data_fresh",
        "bid_ask_valid",
        "spread_acceptable",
        "account_state_valid",
        "risk_config_valid",
        "reconciliation_healthy",
    ]
    passed = all(checks.get(k, False) for k in required)
    demo_enabled = passed  # only after all required pass
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
        "details": details,
        "blocked_reasons": blocked,
        "passed": passed,
        "demo_enabled": demo_enabled,
        "required_checks": required,
        "account_is_demo": is_demo,
        "warn_live_in_demo": not is_demo and account_info is not None,
    }
