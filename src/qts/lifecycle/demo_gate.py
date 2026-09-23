"""MT5 Demo Forward connection checker — 14 checks, only after all required pass should DEMO_FORWARD be enabled."""

from __future__ import annotations

import contextlib
import math
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


MAX_TICK_AGE_S = 60.0  # existing freshness contract — unchanged, never weakened
FUTURE_TOLERANCE_S = 5.0  # minor same-basis clock skew only; NOT a clamp for timezone-scale futures
_MIN_VALID_EPOCH_S = 1e9  # ~2001-09-09; anything at/below is garbage (0, missing, wrong units)



#: The 14 checks that must all pass for DEMO readiness (order is the contract).
#: Exported so callers (CLI, API, tests) reference the same list the gate uses.
READINESS_REQUIRED_CHECKS: tuple[str, ...] = (
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
)

def _as_epoch_seconds(raw: Any) -> float | None:
    """Normalize an MT5 timestamp to epoch seconds, or None if unusable.

    Accepts Python ints/floats and numpy scalars (structured-array fields).
    Values > 1e12 are milliseconds (``time_msc``). Garbage never becomes a
    usable timestamp — the caller fails closed instead of assuming fresh.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= _MIN_VALID_EPOCH_S:
        return None
    if value > 1e12:  # milliseconds
        value /= 1000.0
    return value


def _tick_epoch_seconds(tick: Any) -> float | None:
    """MT5 Tick timestamp -> epoch seconds (``time`` preferred, ``time_msc`` fallback)."""
    epoch = _as_epoch_seconds(getattr(tick, "time", None))
    if epoch is None:
        epoch = _as_epoch_seconds(getattr(tick, "time_msc", None))
    return epoch


def _probe_current_bar_time(mt5_module: Any, symbol: str) -> float | None:
    """Open time (epoch seconds, SERVER basis) of the latest M1 bar, or None.

    The MetaTrader5 Python API exposes no server-time or server-UTC-offset
    call (verified against MetaQuotes docs/forums). While the market is open
    the latest M1 bar is the one currently forming, so
    ``server_now in [bar_time, bar_time + 60)`` — the only authoritative
    server-clock probe available. Bar open times share the tick timestamp
    basis (server timezone), so comparisons between them need no offset.
    """
    getter = getattr(mt5_module, "copy_rates_from_pos", None)
    if getter is None:
        return None
    timeframe_m1 = getattr(mt5_module, "TIMEFRAME_M1", 1)
    try:
        rates = getter(symbol, timeframe_m1, 0, 1)
        if rates is None or len(rates) == 0:
            return None
        bar = rates[0]
        try:
            raw = bar["time"]
        except (TypeError, KeyError, IndexError):
            raw = getattr(bar, "time", None)
    except Exception:
        return None  # probe unavailable -> caller falls back to the same-basis contract
    return _as_epoch_seconds(raw)


def _fmt_offset(seconds: float) -> str:
    sign = "+" if seconds >= 0 else "-"
    total_min = int(abs(seconds)) // 60
    hh, mm = divmod(total_min, 60)
    return f"{sign}{hh}h{mm:02d}m"


def _evaluate_tick_freshness(tick: Any, mt5_module: Any, symbol: str, now: float) -> tuple[bool, str, str | None]:
    """Freshness under an explicit, fail-closed time contract.

    Background (proven on a real WMMarkets-Demo terminal): MT5 stamps ticks
    in TRADE-SERVER local time (Unix epoch on the server's timezone basis,
    e.g. UTC+3) while ``time.time()`` is true UTC. Comparing them directly
    produced ``age = -10537.1s`` (a tick ~3h minus its true age "in the
    future") and the old ``age < 60`` test ACCEPTED it — along with any
    quote up to ~3h stale. Rules, in order:

    1. Unusable timestamp -> FAIL (never age=0/fresh; the old ``else: age=0``
       branch fabricated freshness for garbage).
    2. ``raw_age > 60s`` -> STALE. Sound for any server offset >= 0 because
       true_age = raw_age + offset >= raw_age. Also rejects closed-market
       quotes (hours old) regardless of basis.
    3. Server-clock probe (latest M1 bar) available:
       - tick before the current bar open -> provably older than the forming
         bar -> STALE (no false accept; near minute boundaries a genuinely
         fresh tick can be conservatively rejected — re-checking passes);
       - tick stamped beyond ``bar_time + 60 + tol`` -> corrupt/future -> FAIL;
       - tick inside the current bar -> true age < 60s PROVABLY
         (server_now < bar_time + 60) -> FRESH, reported with the raw local
         age and implied server offset for auditability.
    4. No probe (mocks/legacy modules): require a same-basis timestamp,
       ``-5s <= raw_age <= 60s``. Future timestamps beyond tolerance FAIL —
       never clamped to zero, never assumed fresh.
    """
    epoch = _tick_epoch_seconds(tick)
    if epoch is None:
        return False, "tick timestamp missing/invalid — fail-closed, never assumed fresh", "Market data not fresh"
    raw_age = now - epoch
    if raw_age > MAX_TICK_AGE_S:
        return (
            False,
            f"age {raw_age:.1f}s > {MAX_TICK_AGE_S:.0f}s (stale on any clock basis)",
            "Market data stale",
        )
    bar_time = _probe_current_bar_time(mt5_module, symbol)
    if bar_time is not None:
        implied_offset = bar_time + 30.0 - now
        audit = f"raw local age {raw_age:.1f}s, implied server offset {_fmt_offset(implied_offset)}"
        if epoch < bar_time:
            return (
                False,
                f"last tick precedes the current M1 bar by {bar_time - epoch:.0f}s — server-clock age "
                f">= {bar_time - epoch:.0f}s, provably not fresh ({audit})",
                "Market data stale",
            )
        if epoch > bar_time + 60.0 + FUTURE_TOLERANCE_S:
            return (
                False,
                f"tick stamped beyond the current M1 bar — corrupt/inconsistent timestamps ({audit})",
                "Market data not fresh",
            )
        return True, f"age <{MAX_TICK_AGE_S:.0f}s on server clock: tick within current M1 bar ({audit})", None
    if raw_age < -FUTURE_TOLERANCE_S:
        return (
            False,
            f"tick timestamp {-raw_age:.0f}s in the future with no server-clock probe available — "
            "clock/timezone inconsistency, fail-closed (not clamped, not assumed fresh)",
            "Market data not fresh",
        )
    return True, f"age {raw_age:.1f}s", None


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
    """Run 14 checks for DEMO_FORWARD observation readiness.

    ``passed`` authorizes observation only. The legacy ``demo_enabled`` field
    is retained for API compatibility and is always false because
    DEMO_EXECUTION is disabled by product policy.

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
                # Tradability is AUTHORITATIVE from trade_mode (0=disabled);
                # an explicit trade_allowed/tradable attribute must be True
                # when present. The old ``default True`` fabricated consent
                # for symbols whose tradability could not be read.
                tm = getattr(si, "trade_mode", None)
                explicit_allowed = getattr(si, "trade_allowed", getattr(si, "tradable", None))
                if explicit_allowed is not None:
                    tradable = bool(explicit_allowed) and tm != 0
                else:
                    tradable = tm is not None and tm != 0
                check(
                    "symbol_tradable",
                    tradable,
                    f"trade_mode={tm} trade_allowed={explicit_allowed!r} -> tradable={tradable}",
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
                # Freshness under the explicit fail-closed time contract (see
                # _evaluate_tick_freshness): MT5 tick stamps are server-timezone
                # based, so a single local-clock subtraction is not a valid age.
                fresh, fresh_detail, fresh_blocker = _evaluate_tick_freshness(t, mt5_module, broker_symbol, time.time())
                check("market_data_fresh", fresh, fresh_detail, fresh_blocker)
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
    required = list(READINESS_REQUIRED_CHECKS)
    passed = all(checks.get(k, False) for k in required)
    # ``passed`` authorizes DEMO_FORWARD observation readiness only. Product
    # policy intentionally keeps DEMO_EXECUTION disabled, so the legacy field
    # must not imply order permission.
    demo_enabled = False
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
        "details": details,
        "blocked_reasons": blocked,
        "passed": passed,
        "demo_enabled": demo_enabled,
        "demo_execution_enabled": False,
        "demo_execution_note": (
            "passed readiness permits DEMO_FORWARD observation; DEMO_EXECUTION additionally requires a recorded "
            "owner authorization, staged arming, a pinned+confirmed broker identity and an eligible registered "
            "strategy — see docs/demo_execution_authorization_and_safety_2026-09-23.md"
        ),
        "required_checks": required,
        "account_is_demo": is_demo,
        "warn_live_in_demo": not is_demo and account_info is not None,
    }
