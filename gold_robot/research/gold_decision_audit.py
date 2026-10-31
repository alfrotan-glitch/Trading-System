"""QTS Gold: deterministic, research-only per-opportunity decision audit.

Not a broker router, order engine, probability forecast, or edge validation.
Only supplied CLOSED-bar context is used; it never reads future market data.
Missing independent calendar, broker contracts, costs or margin => NO_TRADE.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "qts.gold.decision_audit.v1"
STRATEGIES = {
    "TREND_PULLBACK": ("TREND", 5),
    "BREAK_RETEST": ("TREND", 4),
    "MOMENTUM_CONTINUATION": ("TREND", 3),
    "SWEEP_RECLAIM": ("RANGE", 4),
    "RANGE_REJECTION": ("RANGE", 3),
}
RESEARCH_RISK_CAP_PCT = 0.50
MIN_NET_RR = 1.25
UTC = timezone.utc


def instant(raw: str) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("Timestamp must include an explicit UTC offset")
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Naive broker or bar times are not allowed")
    return stamp.astimezone(UTC)


def finite_positive(value: object, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: invalid boolean")
    number = float(value)
    if not math.isfinite(number) or (number < 0 if allow_zero else number <= 0):
        raise ValueError(f"{name}: must be finite and nonnegative")
    return number


def classify_session(now: datetime) -> str:
    if now.weekday() >= 5:
        return "CLOSED_WEEKEND"
    london = now.astimezone(ZoneInfo("Europe/London"))
    new_york = now.astimezone(ZoneInfo("America/New_York"))
    lmin = london.hour * 60 + london.minute
    nmin = new_york.hour * 60 + new_york.minute
    in_london = 8 * 60 <= lmin < 16 * 60 + 30
    london_open = 8 * 60 <= lmin < 11 * 60
    ny_core = 8 * 60 <= nmin < 12 * 60
    if in_london and ny_core:
        return "LONDON_NY_OVERLAP"
    if london_open:
        return "LONDON_OPEN"
    if ny_core:
        return "NY_CORE"
    return "OUTSIDE_STUDY_HOURS"


def time_fresh(raw: object, now: datetime, max_age_seconds: int) -> bool:
    try:
        age = (now - instant(raw)).total_seconds()
    except (ValueError, TypeError):
        return False
    return 0 <= age <= max_age_seconds


def classification(context: dict) -> tuple[str, str, float]:
    atr = finite_positive(context["m15_atr"], "M15 ATR")
    percentile = finite_positive(context["m15_atr_p90"], "M15 ATR percentile")
    if atr > percentile * 1.5:
        return "VOLATILITY_SPIKE", "NEUTRAL", atr
    fast = float(context["m15_ema_fast"])
    slow = float(context["m15_ema_slow"])
    adx = float(context["m15_adx"])
    hfast = float(context["h1_ema_fast"])
    hslow = float(context["h1_ema_slow"])
    if not all(math.isfinite(x) for x in (fast, slow, adx, hfast, hslow)):
        raise ValueError("Nonfinite closed-bar indicator")
    if not 0 <= adx <= 100:
        raise ValueError("Invalid ADX")
    delta = abs(fast - slow) / atr
    regime = "TREND" if adx >= 25 and delta >= 0.12 else (
        "RANGE" if adx <= 19 or delta < 0.07 else "TRANSITION")
    bias = "BUY" if hfast > hslow + 0.10 * atr else (
        "SELL" if hslow > hfast + 0.10 * atr else "NEUTRAL")
    return regime, bias, atr


def news_gate(news: dict, now: datetime) -> list[str]:
    if news.get("status") != "verified" or not time_fresh(news.get("fetched_at"), now, 24 * 3600):
        return ["NEWS_CALENDAR_UNVERIFIED_OR_STALE"]
    events = news.get("events")
    if not isinstance(events, list):
        return ["NEWS_EVENTS_NOT_AVAILABLE"]
    for event in events:
        if not isinstance(event, dict) or any(k not in event for k in ("impact", "currency", "at")):
            return ["INVALID_NEWS_EVENT"]
        if event.get("impact") not in ("low", "medium", "high"):
            return ["UNKNOWN_NEWS_IMPACT"]
        if event.get("currency") not in ("USD", "GLOBAL", "OTHER"):
            return ["UNKNOWN_NEWS_CURRENCY"]
        if event["impact"] != "high" or event["currency"] == "OTHER":
            continue
        try:
            seconds = (now - instant(event.get("at"))).total_seconds()
        except (ValueError, TypeError):
            return ["INVALID_NEWS_EVENT_TIME"]
        if -30 * 60 <= seconds <= 15 * 60:
            return ["HIGH_IMPACT_NEWS_BLACKOUT"]
    return []


def audit(snapshot: dict) -> dict:
    """Audit all candidates independently and rank only eligible research ideas."""
    now = instant(snapshot["as_of"])
    candidates = snapshot.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("candidates must be an array")
    session = classify_session(now)
    common: list[str] = []
    if snapshot.get("symbol") != "XAUUSD@":
        common.append("UNVERIFIED_BROKER_SYMBOL")
    account, broker, context = (snapshot.get(name, {}) for name in ("account", "broker", "context"))
    if not all(isinstance(o, dict) for o in (account, broker, context)):
        raise ValueError("Account, broker and context must be objects")
    try:
        equity = finite_positive(account["equity"], "equity")
        day = finite_positive(account["day_start_equity"], "day equity")
        peak = finite_positive(account["peak_equity"], "peak equity")
        risk_pct = finite_positive(account["risk_pct"], "risk pct")
        balance = finite_positive(account["balance"], "balance")
        if account.get("currency") != "USD":
            common.append("ACCOUNT_NOT_USD")
        if risk_pct > RESEARCH_RISK_CAP_PCT:
            common.append("RISK_EXCEEDS_RESEARCH_CAP")
        if (day - equity) / day > 0.03 or (peak - equity) / peak > 0.08:
            common.append("EQUITY_DRAWDOWN_GUARD")
        if account.get("existing_exposure") is not False:
            common.append("EXPOSURE_UNKNOWN_OR_OCCUPIED")
        if balance < equity * 0.01:
            common.append("ACCOUNT_BALANCE_INVALID")
        contract = finite_positive(broker["contract_size"], "contract size")
        min_lot = finite_positive(broker["min_lot"], "min lot")
        step = finite_positive(broker["lot_step"], "lot step")
        max_lot = finite_positive(broker["max_lot"], "max lot")
        margin_per_lot = finite_positive(broker["margin_per_lot_usd"], "margin per lot")
        free_margin = finite_positive(broker["free_margin_usd"], "free margin")
        spread = finite_positive(broker["spread_price"], "spread", allow_zero=True)
        slippage = finite_positive(broker["adverse_slippage_price"], "slippage", allow_zero=True)
        fee = finite_positive(broker["round_turn_fee_per_lot_usd"], "fees", allow_zero=True)
        min_stop = finite_positive(broker["min_stop_distance_price"], "stop minimum", allow_zero=True)
        bid = finite_positive(broker["bid"], "bid")
        ask = finite_positive(broker["ask"], "ask")
        if max_lot < min_lot or ask <= bid or abs(ask - bid - spread) > max(0.02, spread * 0.05):
            common.append("BROKER_CONTRACT_OR_QUOTE_INVALID")
        if not time_fresh(broker.get("quote_at"), now, 5):
            common.append("QUOTE_STALE")
        regime, bias, atr = classification(context)
        for name, maximum in (("h1_closed_at", 2 * 3600), ("m15_closed_at", 30 * 60),
                              ("m5_closed_at", 10 * 60)):
            if not time_fresh(context.get(name), now, maximum):
                common.append("STALE_CLOSED_BAR_" + name.upper())
        m5close = finite_positive(context["m5_close"], "M5 close")
        m5ema = finite_positive(context["m5_ema_fast"], "M5 EMA")
    except (KeyError, TypeError, ValueError) as exc:
        common.append("REQUIRED_MARKET_OR_BROKER_DATA_INVALID: " + str(exc)[:100])
        equity = risk_pct = contract = min_lot = step = max_lot = margin_per_lot = 0
        free_margin = spread = slippage = fee = min_stop = bid = ask = atr = 0
        m5close = m5ema = 0
        regime, bias = "UNKNOWN", "NEUTRAL"

    common.extend(news_gate(snapshot.get("news", {}) if isinstance(snapshot.get("news"), dict) else {}, now))
    if session in ("CLOSED_WEEKEND", "OUTSIDE_STUDY_HOURS"):
        common.append("SESSION_OUTSIDE_RESEARCH_HOURS")
    if regime in ("VOLATILITY_SPIKE", "UNKNOWN"):
        common.append("NO_STABLE_MARKET_REGIME")
    results = []
    for proposal in candidates:
        reasons = list(common)
        if not isinstance(proposal, dict):
            results.append({"id": None, "status": "REJECT", "reasons": reasons + ["MALFORMED_CANDIDATE"]})
            continue
        name = proposal.get("style")
        side = proposal.get("side")
        if name not in STRATEGIES:
            reasons.append("UNKNOWN_STRATEGY")
        if proposal.get("setup_valid") is not True:
            reasons.append("SETUP_NOT_CONFIRMED_ON_CLOSED_BARS")
        if not time_fresh(proposal.get("closed_at"), now, 15 * 60):
            reasons.append("CANDIDATE_BAR_STALE")
        if side not in ("BUY", "SELL"):
            reasons.append("INVALID_SIDE")
        if name in STRATEGIES and STRATEGIES[name][0] != regime:
            reasons.append("STRATEGY_WRONG_REGIME")
        if name in STRATEGIES and regime == "TREND" and side != bias:
            reasons.append("H1_TREND_MISMATCH")
        if name in STRATEGIES and regime == "TREND" and side in ("BUY", "SELL") and (
            (side == "BUY" and m5close <= m5ema) or
            (side == "SELL" and m5close >= m5ema)
        ):
            reasons.append("M5_CLOSED_BAR_NOT_CONFIRMED")
        lot = net_rr = score = None
        try:
            entry = finite_positive(proposal["entry"], "entry")
            stop = finite_positive(proposal["stop"], "stop")
            target = finite_positive(proposal["target"], "target")
            if side == "BUY" and not stop < entry < target:
                reasons.append("INVALID_BUY_SL_TP_GEOMETRY")
            elif side == "SELL" and not target < entry < stop:
                reasons.append("INVALID_SELL_SL_TP_GEOMETRY")
            elif side not in ("BUY", "SELL"):
                reasons.append("NO_VALID_DIRECTION")
            elif not common:
                gap = abs(entry - stop)
                gain = abs(target - entry)
                if gap < min_stop or gap < 3 * spread or gap < 0.25 * atr:
                    reasons.append("STOP_TOO_CLOSE")
                if abs(entry - (bid + ask) / 2) > atr * 1.8:
                    reasons.append("ENTRY_TOO_FAR_FROM_QUOTE")
                if spread > 0.20 * atr:
                    reasons.append("SPREAD_TOO_HIGH_FOR_ATR")
                cost_per_lot = fee + (spread + slippage) * contract
                risk_per_lot = gap * contract + cost_per_lot
                gain_per_lot = gain * contract - cost_per_lot
                net_rr = round(gain_per_lot / risk_per_lot, 4) if risk_per_lot > 0 else 0
                if net_rr < MIN_NET_RR:
                    reasons.append("NET_REWARD_RISK_TOO_LOW")
                # Full-lot step, margin and risk cap all restrict position size.
                limit = min(equity * min(risk_pct, RESEARCH_RISK_CAP_PCT) / 100 / risk_per_lot,
                            free_margin * 0.20 / margin_per_lot, max_lot)
                # Broker lot steps are normally measured FROM minimum volume.
                # E.g. min=0.03, step=0.02 => 0.03, 0.05, 0.07 (not 0.04).
                units = math.floor((limit - min_lot + 1e-12) / step)
                lot = round(min_lot + max(0, units) * step, 8) if limit >= min_lot else 0.0
                if lot < min_lot:
                    reasons.append("MINIMUM_LOT_EXCEEDS_RISK_OR_MARGIN")
                if not reasons:
                    score = round(STRATEGIES[name][1] + min(net_rr, 2.0) * 0.2
                                  - cost_per_lot / (gap * contract) * 0.3, 6)
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            reasons.append("CANDIDATE_PRICE_OR_SIZE_INVALID: " + str(exc)[:100])
        results.append({"id": proposal.get("id"), "style": name, "side": side,
                        "status": "RESEARCH_ELIGIBLE" if not reasons else "REJECT",
                        "lot_research_only": lot, "net_rr_after_cost_stress": net_rr,
                        "score_not_probability": score, "reasons": sorted(set(reasons))})
    eligible = [row for row in results if row["status"] == "RESEARCH_ELIGIBLE"]
    eligible.sort(key=lambda r: (-r["score_not_probability"], str(r["id"])))
    return {"schema": SCHEMA, "as_of_utc": now.isoformat(), "symbol": snapshot.get("symbol"),
            "session": session, "regime": regime, "h1_bias": bias,
            "decision": "RESEARCH_PROPOSAL_ONLY" if eligible else "NO_TRADE",
            "selected_candidate_id": eligible[0]["id"] if eligible else None,
            "candidate_audit": results, "live": "LOCKED",
            "connected_orders_authorized": False, "validated_edge": False,
            "score_is_not_win_probability": True,
            "warning": "Requires independent native tick and broker-cost validation; no order execution."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    answer = audit(json.loads(args.input.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"QTS GOLD {answer['decision']} session={answer['session']} "
          f"candidate={answer['selected_candidate_id']} LIVE LOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
