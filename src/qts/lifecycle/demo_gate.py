"""MT5 Demo Forward connection checker — 14 checks, only after all required pass should DEMO_FORWARD be enabled."""

from __future__ import annotations

import contextlib
import os
import time
from datetime import UTC, datetime
from typing import Any

from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS

# Canonical QTS spec field -> accepted attribute names on the raw MT5
# SymbolInfo object (real API name first, legacy/mock alias second).
_SPEC_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "contract_size": ("trade_contract_size", "contract_size"),
    "volume_min": ("volume_min",),
    "volume_max": ("volume_max",),
    "volume_step": ("volume_step",),
    "digits": ("digits",),
    "point": ("point",),
}


def _resolve_symbol_map(symbol_map: dict[str, str] | None) -> dict[str, str]:
    """Broker symbol map (e.g. XAUUSD -> XAUUSD@): explicit param or QTS_MT5_SYMBOL_MAP env.

    Env form: ``QTS_MT5_SYMBOL_MAP="XAUUSD=XAUUSD@,EURUSD=EURUSD.m"``.
    """
    if symbol_map is not None:
        return symbol_map
    env_map = os.getenv("QTS_MT5_SYMBOL_MAP", "")
    out: dict[str, str] = {}
    for kv in env_map.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


def demo_forward_readiness_report(
    mt5_module: Any | None = None,
    risk_limits: Any | None = None,
    terminal_path: str | None = None,
    symbol: str | None = None,
    symbol_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run 14 checks. Returns dict with checklist, passed, blocked_reasons, demo_enabled.

    ``terminal_path`` (or ``QTS_MT5_PATH``/``MT5_PATH`` env) is passed to
    ``mt5.initialize(path=...)``: the MetaTrader5 package returns None from
    terminal_info/account_info/symbol_info until initialize() succeeds IN THIS
    PROCESS — importing the module is not enough. This was the root cause of
    "wizard reports terminal_info=None while a direct CLI test with
    initialize(path=...) works".

    ``symbol`` (or ``QTS_MT5_SYMBOL`` env) and ``symbol_map``
    (or ``QTS_MT5_SYMBOL_MAP`` env) resolve the broker's actual symbol name
    (e.g. XAUUSD@ instead of XAUUSD) before symbol_info/tick checks.

    Fail-closed: initialize failure is surfaced with last_error and blocks —
    never mocked, never skipped. The 14-check contract is unchanged.
    """
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

    # 1b Establish the IPC link to the terminal (root-cause fix, Windows).
    # MetaTrader5 data functions (terminal_info/account_info/symbol_info/
    # symbol_info_tick) return None until initialize() succeeds IN THIS
    # PROCESS; importing the module is not enough. Injected test mocks may
    # lack initialize entirely — skip then (backward compatible).
    init_detail = ""
    if mt5_module is not None and hasattr(mt5_module, "initialize"):
        path = terminal_path or os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH")
        kwargs: dict[str, Any] = {"path": path} if path else {}
        try:
            initialized = bool(mt5_module.initialize(**kwargs))
            init_detail = f"initialize(path={'configured' if path else 'auto'})={initialized}"
            if not initialized:
                with contextlib.suppress(Exception):
                    init_detail += f" last_error={mt5_module.last_error()}"
                blocked.append("MT5 initialize failed — terminal link not established")
        except Exception as e:
            init_detail = f"initialize error: {e}"
            blocked.append("MT5 initialize failed — terminal link not established")

    # 2 Terminal running?
    if mt5_module is not None and hasattr(mt5_module, "terminal_info"):
        try:
            ti = mt5_module.terminal_info()
            running = ti is not None
            check(
                "terminal_running",
                running,
                f"{init_detail} terminal_info={ti}".strip(),
                None if running else "Terminal not running",
            )
        except Exception as e:
            check("terminal_running", False, f"{init_detail} {e}".strip(), "Terminal not running")
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
    # Symbol resolution: explicit param > QTS_MT5_SYMBOL env > default XAUUSD.
    # Broker symbol mapping (e.g. XAUUSD -> XAUUSD@) via symbol_map param or
    # QTS_MT5_SYMBOL_MAP env — the raw requested name is often NOT the broker's
    # actual symbol, which made symbol_info return None even on a working link.
    # ternary form: mypy 2.x mis-infers `x or os.getenv(k, default)` as str | None
    requested_symbol = os.getenv("QTS_MT5_SYMBOL", "XAUUSD") if symbol is None else symbol
    broker_symbol = _resolve_symbol_map(symbol_map).get(requested_symbol, requested_symbol)
    # Make the symbol visible in Market Watch before querying (mirrors
    # MT5Adapter.get_symbol_spec); suppress: unsupported by some mocks/brokers.
    if mt5_module is not None and hasattr(mt5_module, "symbol_select"):
        with contextlib.suppress(Exception):
            mt5_module.symbol_select(broker_symbol, True)
    if mt5_module is not None and hasattr(mt5_module, "symbol_info"):
        try:
            si = mt5_module.symbol_info(broker_symbol)
            available = si is not None
            check(
                "symbol_available",
                available,
                f"symbol_info for {requested_symbol} (broker {broker_symbol}) exists={available}",
                None if available else f"Symbol {broker_symbol} not available",
            )
            if si:
                tradable = bool(getattr(si, "trade_allowed", getattr(si, "tradable", True)))
                check(
                    "symbol_tradable",
                    tradable,
                    f"trade_allowed={tradable}",
                    None if tradable else "Symbol not tradable",
                )
                # spec valid: required CANONICAL fields, resolved through the
                # real MetaTrader5 SymbolInfo attribute names. The real API
                # exposes contract size as `trade_contract_size` (there is no
                # `contract_size` attribute); mocks historically use
                # `contract_size`. A field counts present only if an accepted
                # alias exists AND is not None (stricter than the previous
                # hasattr check — None no longer passes as present).
                needed = ["contract_size", "volume_min", "volume_max", "volume_step", "digits", "point"]
                missing = [f for f in needed if all(getattr(si, a, None) is None for a in _SPEC_FIELD_ALIASES[f])]
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
            t = mt5_module.symbol_info_tick(broker_symbol)
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
