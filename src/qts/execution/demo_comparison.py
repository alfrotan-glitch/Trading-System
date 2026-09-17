"""Paper vs Shadow vs Demo comparison — measurements or UNAVAILABLE, never zeros.

Closes audit finding #7. The previous comparison presented fabricated
placeholder metrics as measurements:

* ``expected_entry_difference_bps = 0.0`` / ``actual_entry_difference_bps =
  0.0`` / ``spread_difference_bps = 0.0`` — computed nowhere, hardcoded zero.
* ``exit_differences = 0`` — never computed.
* ``signal_agreement`` — a count ratio (min/max of two list lengths), not an
  event-level alignment.

Now every metric is one of:

* **MEASURED** — computed from real event alignment / real recorded fields.
* **UNAVAILABLE** — with a machine-readable reason (no data, not measured).

Demo-side execution metrics come from the canonical observation store; when
no demo-execution fills have ever been recorded they are UNAVAILABLE — NOT
zero. Signal agreement uses genuine event alignment: a paper fill agrees
with a shadow intent when both reference the SAME decision event (matching
bar-timestamp extracted from the event identity) — count ratios cannot
pretend to be agreement.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.domain.provenance import MetricValue

_SHADOW_ID_TS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")

#: Two decision events are the SAME event when their bar timestamps fall in
#: this window (paper fills are stamped next-bar-open, +1h vs the decision
#: bar on 1H data; shadow intents carry the decision bar itself).
_EVENT_MATCH_WINDOW_S = 3700.0  # 1H bar + sub-second receipt drift


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts))
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d
    except (TypeError, ValueError):
        return None


def _event_key_from_shadow_id(client_order_id: Any) -> datetime | None:
    m = _SHADOW_ID_TS.search(str(client_order_id or ""))
    return _parse_iso(m.group(1)) if m else None


def _align_events(
    paper_fills: list[dict[str, Any]],
    shadow_intents: list[dict[str, Any]],
    *,
    window_s: float = _EVENT_MATCH_WINDOW_S,
) -> MetricValue:
    """Event-level signal agreement: matched decision events / shadow intents.

    A paper fill and a shadow intent refer to the SAME decision event when a
    paper fill's bar-time matches a shadow intent's bar-time within the
    window. Each shadow intent is matched at most once (greedy nearest).
    Returns UNAVAILABLE when either side has no events — a count ratio of
    empty lists is not agreement, and 0.0 would be a fabricated measurement.
    """
    paper_times: list[datetime] = []
    for f in paper_fills:
        t = _parse_iso(f.get("time") or f.get("bar_time") or f.get("event_time"))
        if t is None:
            t = _event_key_from_shadow_id(f.get("client_order_id"))
        if t is not None:
            paper_times.append(t)
    intent_times: list[datetime] = []
    for i in shadow_intents:
        t = _event_key_from_shadow_id(i.get("client_order_id"))
        if t is None:
            t = _parse_iso(i.get("time") or i.get("bar_time"))
        if t is not None:
            intent_times.append(t)
    if not paper_times or not intent_times:
        return MetricValue.unavailable(
            "NO_DATA", "signal agreement requires both paper fills and shadow intents with parseable event times"
        )
    matched = 0
    used: set[int] = set()
    for it in sorted(intent_times):
        best: int | None = None
        best_dt = window_s
        for j, pt in enumerate(paper_times):
            if j in used:
                continue
            dt = abs((pt - it).total_seconds())
            if dt <= best_dt:
                best, best_dt = j, dt
        if best is not None:
            used.add(best)
            matched += 1
    return MetricValue.ok(round(matched / len(intent_times), 3))


def _demo_observations_from_canonical_store() -> list[dict[str, Any]]:
    """Demo observations from the ONE canonical store (never a derived JSON)."""
    try:
        from qts.observability.forward_observatory import ForwardObservatory

        return ForwardObservatory().list_ticks(limit=1000)
    except Exception:
        return []


def compare_paper_shadow_demo(
    paper_fills: list[dict[str, Any]] | None = None,
    shadow_intents: list[dict[str, Any]] | None = None,
    demo_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the comparison report. Every metric is MEASURED or UNAVAILABLE."""
    if paper_fills is None:
        paper_fills = _load_evidence_list("paper_trades.json", "fills")
    if shadow_intents is None:
        shadow_intents = _load_evidence_list("shadow_intents.json", "intents_sample")
    if demo_observations is None:
        demo_observations = _demo_observations_from_canonical_store()

    agreement = _align_events(paper_fills, shadow_intents)

    # Demo EXECUTION metrics: require real recorded demo fills (order lifecycle
    # data). Canonical store observations are ticks — no fills exist until
    # DEMO_EXECUTION actually records them; then they must carry real fields.
    demo_fills = [
        o
        for o in demo_observations
        if str(o.get("type", "")).startswith("demo_fill") and o.get("requested_price") and o.get("actual_price")
    ]
    slips = [float(o["slippage_bps"]) for o in demo_fills if o.get("slippage_bps") is not None]
    lats = [float(o["latency_ms"]) for o in demo_fills if o.get("latency_ms") is not None]

    result: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "paper_source": "data/evidence/paper_trades.json (PAPER class)",
            "shadow_source": "data/evidence/shadow_intents.json (SHADOW class)",
            "demo_source": "canonical observation store (DEMO class)",
            "label": "DEMO never LIVE",
        },
        "paper_trades": len(paper_fills),
        "shadow_intents": len(shadow_intents),
        "demo_observations": len(demo_observations),
        "demo_fills_recorded": len(demo_fills),
        "signal_agreement": agreement.as_dict(),
        # Execution-reality metrics — each is a real measurement or an
        # explicit UNAVAILABLE; a zero is NEVER a stand-in for "not measured".
        "expected_entry_difference_bps": MetricValue.unavailable(
            "NOT_MEASURED",
            "requires paired paper+demo execution of the SAME signal; no paired events recorded",
        ).as_dict(),
        "actual_entry_difference_bps": MetricValue.unavailable(
            "NO_DATA", "no demo fills recorded in the canonical store"
        ).as_dict()
        if not demo_fills
        else _mean_bps(demo_fills, "actual_entry_diff_bps"),
        "spread_difference_bps": MetricValue.unavailable(
            "NO_DATA", "no paired paper/demo spread observations"
        ).as_dict(),
        "slippage_demo_bps": _mean(slips, "demo fill slippage"),
        "latency_demo_ms": _mean(lats, "demo fill latency"),
        "rejected_orders_demo": len([o for o in demo_observations if o.get("type") == "demo_rejected"]),
        "partial_fills_demo": len([o for o in demo_observations if o.get("type") == "demo_partial"]),
        "exit_differences": MetricValue.unavailable(
            "NOT_MEASURED", "exit comparison requires paired paper+demo position lifecycles; none recorded"
        ).as_dict(),
    }
    return result


def _load_evidence_list(filename: str, key: str) -> list[dict[str, Any]]:
    p = Path("data/evidence") / filename
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        v = data.get(key, [])
        return v if isinstance(v, list) else []
    return []


def _mean(values: list[float], name: str) -> dict[str, Any]:
    if not values:
        return MetricValue.unavailable("NO_DATA", f"no {name} observations").as_dict()
    return MetricValue.ok(round(sum(values) / len(values), 2)).as_dict()


def _mean_bps(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    vals = [float(o[key]) for o in rows if o.get(key) is not None]
    return _mean(vals, key)


def write_comparison(path: Path = Path("data/evidence/paper_shadow_demo_comparison.json")) -> dict[str, Any]:
    res = compare_paper_shadow_demo()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
