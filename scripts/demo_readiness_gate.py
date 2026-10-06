#!/usr/bin/env python
"""Demo Readiness Gate runner — the executable form of the DEMO-READY-02 hand-off.

Drives the 10-step Demo Readiness Gate against a RUNNING QTS instance through
the canonical API only, and records the step-10 verdict mechanically.

Rules enforced by construction:

* **Backend is the authority.** This script never evaluates a trading rule
  itself — every PASS criterion is read from the product's own responses.
* **Fail closed.** It halts at the FIRST failing step, prints the product's
  reasons verbatim, records ``ENVIRONMENT BLOCKED`` / ``GATE BLOCKED``, and
  exits 2. It never retries a POST and never continues past a failure.
* **No gate weakening.** It sends only the canonical operator-intent fields
  (``confirmed``/``risk_ack``/``rationale``); whether a trade happens is
  decided entirely by the server-side gates.

Default run executes steps 1-3 (read-only verification). Steps 4-7 — one
controlled order, broker acknowledgement, safe close, final reconcile — run
only with ``--execute``, which additionally requires ``--quantity`` and
``--stop-loss`` stated explicitly by the operator.

Usage (on the Windows host, with QTS started under QTS_MODE=demo_execution):

    python scripts/demo_readiness_gate.py                 # steps 1-3
    python scripts/demo_readiness_gate.py --execute \\
        --side BUY --quantity 0.01 \\
        --rationale "demo readiness gate step 4"          # steps 1-7
    # (no --stop-loss: the product derives the registered policy's stop at
    #  order time — the canonical path; pass one only to go TIGHTER)

Exit codes: 0 = gate passed (DEMO READY, or VERIFY PASS for steps 1-3),
2 = blocked (record names the blocker), 3 = QTS unreachable.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Fetch = Callable[[str, str, dict[str, Any] | None], tuple[int, Any]]


def http_fetcher(base_url: str, timeout: float = 30.0) -> Fetch:
    """Return a fetch function bound to ``base_url`` (canonical API, JSON only)."""

    def fetch(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(  # noqa: S310 — operator-provided local QTS URL
            base_url.rstrip("/") + path,
            method=method,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                body = resp.read()
                return resp.status, json.loads(body) if body else None
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"detail": raw.decode("utf-8", errors="replace")[:500]}
            return err.code, parsed

    return fetch


class StepResult:
    def __init__(self, step: int, title: str) -> None:
        self.step = step
        self.title = title
        self.failures: list[str] = []
        self.evidence: dict[str, Any] = {}

    @property
    def passed(self) -> bool:
        return not self.failures

    def fail(self, reason: str) -> None:
        self.failures.append(reason)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "title": self.title,
            "passed": self.passed,
            "failures": self.failures,
            "evidence": self.evidence,
        }


def step1_start(fetch: Fetch) -> StepResult:
    r = StepResult(1, "QTS running under the approved DEMO configuration")
    status, config = fetch("GET", "/api/demo/config", None)
    if status != 200 or not isinstance(config, dict):
        r.fail(f"GET /api/demo/config answered {status} — QTS is not healthy")
        return r
    mode = config.get("mode")
    r.evidence["mode"] = mode
    r.evidence["mode_source"] = config.get("mode_source")
    if mode != "DEMO_EXECUTION":
        r.fail(
            f"mode is {mode!r} — start QTS with QTS_MODE=demo_execution "
            "(the approved DEMO configuration); QTS never switches modes itself"
        )
    return r


def step2_connection(fetch: Fetch) -> StepResult:
    r = StepResult(2, "MT5 connection, account identity, symbol mapping, fresh market data")
    status, mt5 = fetch("GET", "/api/mt5", None)
    if status != 200 or not isinstance(mt5, dict):
        r.fail(f"GET /api/mt5 answered {status}")
        return r
    if not mt5.get("connected"):
        health = mt5.get("health") or {}
        detail = health.get("error") or mt5.get("terminal_status") or "no detail"
        r.fail(f"MT5 not connected: {detail}")

    status, ready = fetch("GET", "/api/demo/readiness", None)
    if status != 200 or not isinstance(ready, dict):
        r.fail(f"GET /api/demo/readiness answered {status}")
        return r
    if not ready.get("passed"):
        for reason in ready.get("blocked_reasons") or ["readiness did not pass (no reasons given)"]:
            r.fail(f"readiness: {reason}")

    status, guide = fetch("GET", "/api/demo/guide", None)
    if status != 200 or not isinstance(guide, dict):
        r.fail(f"GET /api/demo/guide answered {status}")
        return r
    conn = guide.get("connection") or {}
    identity = guide.get("identity") or {}
    quote = guide.get("quote") or {}
    r.evidence["broker"] = conn.get("broker")
    r.evidence["server"] = conn.get("server")
    r.evidence["login"] = conn.get("login")
    r.evidence["account_type"] = conn.get("account_type")
    r.evidence["quote"] = {"fresh": quote.get("fresh"), "bid": quote.get("bid"), "ask": quote.get("ask")}
    if not identity.get("verified"):
        r.fail(
            f"account identity not verified: {identity.get('detail') or 'record + confirm it via the guide'}"
        )
    if not quote.get("fresh"):
        r.fail("market data is not fresh (no live bid/ask) — no tick may be assumed")
    return r


def step3_safety(fetch: Fetch) -> StepResult:
    r = StepResult(3, "Safety gates and durable risk/reconcile state are clean")
    status, risk = fetch("GET", "/api/risk", None)
    if status != 200 or not isinstance(risk, dict):
        r.fail(f"GET /api/risk answered {status}")
        return r
    kill = risk.get("kill_switch_detail") or {}
    r.evidence["kill_switch"] = {"killed": kill.get("killed"), "source": kill.get("source")}
    if kill.get("killed"):
        r.fail(
            f"kill switch ACTIVE ({kill.get('reason')}) — clear it only through the "
            "guide's resume path with a recorded reason, never by editing state"
        )

    status, guide = fetch("GET", "/api/demo/guide", None)
    if status != 200 or not isinstance(guide, dict):
        r.fail(f"GET /api/demo/guide answered {status}")
        return r
    rec = guide.get("reconciliation") or {}
    r.evidence["reconciliation"] = {"clean": rec.get("clean"), "suspended": rec.get("suspended")}
    if rec.get("suspended"):
        r.fail(f"reconciliation suspended: {rec.get('suspended_reason')}")
    elif not rec.get("clean"):
        r.fail(f"reconciliation not clean: {rec.get('details') or rec.get('drift')}")
    blockers = (guide.get("suspension") or {}).get("active_blockers") or []
    for blocker in blockers:
        r.fail(
            f"active blocker {blocker.get('id')}: {blocker.get('detail')} "
            f"(recoverable by: {blocker.get('recoverable_by')})"
        )
    return r


def step4_order(fetch: Fetch, args: argparse.Namespace) -> StepResult:
    r = StepResult(4, "One controlled DEMO order through the canonical path")
    # Readiness-evidence renewal is CANONICAL product behavior, not runner
    # bookkeeping: the order request below carries explicit operator intent
    # (confirmed + risk_ack), and when the authority's evidence has merely
    # decayed past its TTL the backend re-proves it ITSELF — a fresh
    # live-terminal readiness probe, durably recorded through the same
    # authority gates — inside the order request, before any gate judges.
    # If that fresh probe fails, the order refuses with the probe's own
    # reasons and this step halts. No client-side refresh exists here BY
    # DESIGN: this runner is a pure sequencer, not a second safety layer.
    payload = {
        "side": args.side,
        "quantity": args.quantity,
        "confirmed": True,
        "risk_ack": True,
        "rationale": args.rationale,
    }
    # Stop-loss: the CANONICAL source is the registered policy — when the
    # operator supplies none, the product derives the stop at order time at
    # exactly the policy distance (fixed_price_distance from the executable
    # quote side, rounded away from entry) and the gate enforces that
    # distance as a cap (equal-or-tighter passes, wider refuses). A manual
    # stop computed from an earlier quote races a moving market and lands
    # wider than the policy allows — so the runner only forwards a stop the
    # operator EXPLICITLY chose (a deliberate tighter-than-policy stop) and
    # otherwise lets the policy derivation decide.
    if args.stop_loss is not None:
        payload["stop_loss"] = args.stop_loss
    status, out = fetch("POST", "/api/demo/order", payload)
    if not isinstance(out, dict):
        r.fail(f"POST /api/demo/order answered {status} with a non-JSON body")
        return r
    r.evidence["client_order_id"] = out.get("client_order_id")
    r.evidence["journal_id"] = out.get("journal_id")
    r.evidence["broker_order_id"] = out.get("broker_order_id")
    r.evidence["broker_position_id"] = out.get("broker_position_id")
    if status != 200 or not out.get("allowed"):
        for reason in out.get("reasons") or [out.get("detail") or f"refused with HTTP {status}"]:
            r.fail(str(reason))
        return r
    if not out.get("broker_order_id") or not out.get("broker_position_id"):
        r.fail("order reported allowed but broker order/position IDs were not captured — HALT")
    return r


def step5_position(fetch: Fetch, broker_position_id: Any) -> StepResult:
    r = StepResult(5, "Broker acknowledgement and position state")
    status, out = fetch("GET", "/api/demo/positions", None)
    if status != 200 or not isinstance(out, dict):
        detail = out.get("detail") if isinstance(out, dict) else None
        r.fail(f"positions answered {status}: {detail or 'unavailable'} — this is a HALT, not a retry")
        return r
    match = next(
        (p for p in out.get("positions") or [] if str(p.get("ticket")) == str(broker_position_id)),
        None,
    )
    if match is None:
        r.fail(
            f"broker did not report position {broker_position_id} "
            f"(positions seen: {[p.get('ticket') for p in out.get('positions') or []]})"
        )
        return r
    r.evidence["position"] = {
        "ticket": match.get("ticket"),
        "side": match.get("side"),
        "volume": match.get("volume"),
        "price_open": match.get("price_open"),
        "journal_id": match.get("journal_id"),
    }
    return r


def step6_close(fetch: Fetch, broker_position_id: Any) -> StepResult:
    r = StepResult(6, "Safe close through the canonical close authority")
    payload = {
        "ticket": broker_position_id,
        "confirmed": True,
        "risk_ack": True,
        "reason": "demo readiness gate step 6 — controlled close",
    }
    status, out = fetch("POST", "/api/demo/close", payload)
    if status != 200 or not isinstance(out, dict) or not out.get("success"):
        detail = out.get("detail") if isinstance(out, dict) else None
        r.fail(f"close refused (HTTP {status}): {detail or out}")
        return r
    r.evidence["realized_pnl"] = out.get("realized_pnl")
    reconciliation = out.get("reconciliation") or {}
    if reconciliation.get("requires_suspend"):
        r.fail(f"post-close reconciliation requires suspend: {reconciliation}")
    return r


def step7_final(fetch: Fetch, journal_id: Any) -> StepResult:
    r = StepResult(7, "Final broker state, journal state, reconciliation")
    status, out = fetch("GET", "/api/demo/positions", None)
    if status != 200 or not isinstance(out, dict):
        r.fail(f"positions answered {status} — final flatness is NOT verified")
    elif out.get("count") != 0:
        r.fail(f"broker still reports {out.get('count')} open position(s)")
    else:
        r.evidence["verified_flat"] = True

    status, journal = fetch("GET", "/api/demo/journal", None)
    row = None
    if status == 200 and isinstance(journal, dict):
        row = next(
            (o for o in journal.get("orders") or [] if str(o.get("journal_id")) == str(journal_id)),
            None,
        )
    if row is None:
        r.fail(f"journal row {journal_id} not found")
    elif row.get("state") != "CLOSED":
        r.fail(f"journal row {journal_id} state is {row.get('state')!r}, expected CLOSED")
    else:
        r.evidence["journal"] = {"journal_id": row.get("journal_id"), "state": row.get("state")}

    status, guide = fetch("GET", "/api/demo/guide", None)
    if status != 200 or not isinstance(guide, dict):
        r.fail(f"GET /api/demo/guide answered {status}")
    else:
        rec = guide.get("reconciliation") or {}
        if not rec.get("clean") or rec.get("suspended"):
            r.fail(f"final reconciliation not clean: {rec}")
        else:
            r.evidence["reconciliation_clean"] = True
    return r


def run_gate(fetch: Fetch, args: argparse.Namespace) -> tuple[str, list[StepResult]]:
    """Execute the gate; returns (verdict, step results). Halts at the first failure."""
    results: list[StepResult] = []

    for produce in (step1_start, step2_connection, step3_safety):
        result = produce(fetch)
        results.append(result)
        if not result.passed:
            verdict = "ENVIRONMENT BLOCKED" if result.step <= 2 else "GATE BLOCKED"
            return verdict, results

    if not args.execute:
        return "VERIFY PASS", results

    order = step4_order(fetch, args)
    results.append(order)
    if not order.passed:
        return "GATE BLOCKED", results

    ticket = order.evidence["broker_position_id"]
    position = step5_position(fetch, ticket)
    results.append(position)
    if not position.passed:
        return "GATE BLOCKED", results

    close = step6_close(fetch, ticket)
    results.append(close)
    if not close.passed:
        return "GATE BLOCKED", results

    final = step7_final(fetch, order.evidence["journal_id"])
    results.append(final)
    if not final.passed:
        return "GATE BLOCKED", results

    return "DEMO READY", results


def write_record(path: Path, verdict: str, results: list[StepResult], args: argparse.Namespace) -> None:
    record = {
        "schema": "qts.demo_readiness_gate_record.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "executed_order_steps": bool(args.execute),
        "verdict": verdict,
        "steps": [r.as_dict() for r in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--execute", action="store_true", help="run steps 4-7 (order, ack, close, reconcile)")
    parser.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    parser.add_argument("--quantity", default=None, help="order size in lots (required with --execute)")
    parser.add_argument(
        "--stop-loss",
        default=None,
        help=(
            "OPTIONAL explicit stop price — only to choose a TIGHTER stop than the "
            "registered policy. Omit it (recommended) and the product derives the "
            "stop at order time at exactly the policy distance; the gate refuses "
            "any stop wider than the policy cap."
        ),
    )
    parser.add_argument("--rationale", default="demo readiness gate step 4 — controlled order")
    parser.add_argument("--record", default=None, help="record JSON path (default data/evidence/, timestamped)")
    args = parser.parse_args(argv)

    if args.execute and args.quantity is None:
        parser.error("--execute requires an explicit --quantity")

    fetch = fetch or http_fetcher(args.base_url)
    try:
        verdict, results = run_gate(fetch, args)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"QTS unreachable at {args.base_url}: {exc}")
        print("VERDICT: ENVIRONMENT BLOCKED (QTS is not running — step 1 could not even be probed)")
        return 3

    for result in results:
        marker = "PASS" if result.passed else "HALT"
        print(f"[step {result.step}] {marker} — {result.title}")
        for key, value in result.evidence.items():
            print(f"    {key}: {value}")
        for failure in result.failures:
            print(f"    BLOCKER: {failure}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    record_path = Path(args.record) if args.record else Path("data/evidence") / f"demo_readiness_gate_{stamp}.json"
    write_record(record_path, verdict, results, args)

    print(f"\nVERDICT: {verdict}")
    print(f"record: {record_path}")
    if verdict == "VERIFY PASS":
        print("steps 1-3 clean — run again with --execute --quantity ... --stop-loss ... for steps 4-7")
    return 0 if verdict in ("DEMO READY", "VERIFY PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
