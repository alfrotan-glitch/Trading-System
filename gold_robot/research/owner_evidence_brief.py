"""Deterministic QTS Gold owner verdict from already saved, source-linked evidence.

READ ONLY: no MT5 API, network, live quotes, account login, orders, EA
parameter changes, or strategy optimization. The historical summaries are
not independent verification and cannot be used to promote a trader.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "qts.gold.owner_evidence_brief.v1"
FORENSICS = "gold_robot/docs/POST_STOP_FORENSIC_EVIDENCE_2026-10-30.md"
RELEASE = "gold_robot/docs/RELEASE_STATUS.json"
PATTERN = re.compile(
    r"^\|\s*(?P<style>[0-7])\s+[^|]+\|\s*(?P<trades>\d+)\s*\|"
    r"\s*(?P<stops>\d+)\s*\|\s*\d+\s*\|\s*\d+\s*\|"
    r"\s*(?P<net>[+-]?\d+(?:\.\d+)?)\s*\|\s*$",
    re.MULTILINE,
)
NAMES = {
    0: "Former-stop",
    1: "Retest",
    2: "Break/retest",
    3: "Sweep/reclaim",
    4: "Trend impulse",
    5: "Range rejection",
    6: "Inside breakout",
    7: "Adaptive router",
}
STUDIES = (
    "mt5_365d_microstructure_summary_20261023.json",
    "mt5_broker_regime_365d_summary_20261023.json",
    "mt5_broker_ema_365d_summary_20261023.json",
    "mt5_broker_rsi_365d_summary_20261023.json",
    "mt5_broker_opening_range_365d_summary_20261023.json",
    "mt5_session_assay_365d_summary_20261023.json",
    "mt5_session_reversal_365d_summary_20261023.json",
)


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Evidence file must be an object: {path.name}")
    return data


def historical_forensics(root: Path) -> dict:
    path = root / FORENSICS
    text = path.read_text(encoding="utf-8")
    items = []
    for match in PATTERN.finditer(text):
        sid = int(match["style"])
        items.append({
            "style_id": sid, "name": NAMES[sid],
            "positions": int(match["trades"]), "sl_exits": int(match["stops"]),
            "native_net_usd": float(match["net"]),
            "gate": "EXPLORATORY_ONLY_NOT_OOS" if sid in (1, 3) else "REJECTED_OR_UNPROMOTED",
        })
    if [r["style_id"] for r in items] != list(range(8)):
        raise ValueError("Historical eight-style source table missing or altered")
    # Verify source arithmetic against the published statement, not against
    # a fabricated combined portfolio. Native runs use separate accounts.
    if (sum(r["positions"] for r in items) != 938 or
        sum(r["sl_exits"] for r in items) != 503 or
        abs(sum(r["native_net_usd"] for r in items) + 549.87) > 0.011):
        raise ValueError("Forensic source table no longer agrees with its published aggregates")
    if ("427 TP exits" not in text or "8 other exits" not in text or
        "cost realism is NOT independently verified" not in text):
        raise ValueError("Forensic document missing required execution caveats")
    return {
        "source": FORENSICS,
        "period": "2026-04-01 through 2026-10-01, individual MT5 simulated runs",
        "positions_across_separate_tests": 938,
        "sl_exits": 503, "tp_exits": 427, "other_exits": 8,
        "arithmetic_net_across_separate_tests_usd": -549.87,
        "not_a_portfolio_pnl": True,
        "broker_fees_independently_verified": False,
        "raw_native_records_private_not_present_in_this_brief": True,
        "styles": items,
        "exploratory_positive_styles": [r["style_id"] for r in items
                                        if r["native_net_usd"] > 0],
    }


def older_studies(root: Path) -> list[dict]:
    base = root / "data" / "evidence"
    records = []
    for filename in STUDIES:
        item = read_json(base / filename)
        decision = item.get("decision")
        claim = item.get("edge_claim")
        if claim != "NOT ESTABLISHED" or decision not in (
            "REJECTED", "INCONCLUSIVE", "NO_PROMOTION"
        ) or item.get("strategy_promoted") is not False:
            raise ValueError("Historical study claims changed: requires a fresh independent audit")
        records.append({
            "source": f"data/evidence/{filename}",
            "study": item.get("study", item.get("experiment", item.get("schema", ""))),
            "decision": decision,
            "economic_edge": claim,
            "native_broker_execution_attested": False,
        })
    return records


def local_inventory(root: Path) -> dict:
    """Report filenames/counts only. Never read or expose native private files."""
    runs = root / "gold_robot" / "reports_local" / "auto_runs"
    files = sorted(runs.glob("*/OPEN_RESULTS.json")) if runs.is_dir() else []
    archives = sorted(runs.glob("*/QTS_SHARE_RESULTS.zip")) if runs.is_dir() else []
    learning = root / "gold_robot" / "reports_local" / "autonomous_learning" / "QTS_AUTONOMOUS_STATUS.json"
    info = {"native_run_summary_files": len(files), "private_trade_archives": len(archives),
            "private_content_read": False, "native_independent_verification": False}
    if learning.is_file():
        try:
            status = read_json(learning)
            if status.get("schema") == "qts.autonomous.research_journal.v1":
                info["research_journal_state"] = str(status.get("state", "UNKNOWN"))[:80]
                info["research_journal_receipts"] = status.get("evidence_receipts")
                info["research_journal_edge_validated"] = False
            else:
                info["research_journal_state"] = "INVALID_SCHEMA"
        except (ValueError, OSError, json.JSONDecodeError):
            info["research_journal_state"] = "UNREADABLE"
    return info


def build(root: Path, *, generated_at: str | None = None) -> dict:
    release = read_json(root / RELEASE)
    if (release.get("validated_profitable_edge") is not False or
        release.get("live_real_money_orders_permitted") is not False):
        raise ValueError("Release decision changed; refusing to overwrite professional acceptance")
    forensic = historical_forensics(root)
    studies = older_studies(root)
    inventory = local_inventory(root)
    return {
        "schema": SCHEMA, "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
        "status": "NO_INDEPENDENTLY_VALIDATED_PROFITABLE_EDGE",
        "live": "LOCKED", "connected_orders_authorized": False,
        "strategy_promoted": False, "validated_edge": False,
        "release_state": str(release.get("release_state", "UNKNOWN")),
        "forensics": forensic, "older_365d_studies": studies,
        "local_evidence_inventory": inventory,
        "research_priority": [
            "DO_NOT_TUNE_ON_ALREADY_VIEWED_2026_APR_OCT_HISTORY",
            "PRESERVE_OLD_NATIVE_RUNS_AND_RECONCILE_TRUE_BROKER_FEES",
            "COMPARE_RETEST_1_AND_SWEEP_3_ON_INDEPENDENT_CHRONOLOGICAL_NATIVE_WINDOW",
            "CHECK_SMALL_ACCOUNT_MINIMUM_VOLUME_MARGIN_AND_STRESSED_SLIPPAGE",
            "DO_NOT_PROMOTE_ANY_STRATEGY_WITHOUT_BROKER_OOS_EVIDENCE",
        ],
        "missing_acceptance": [
            "independently verified native broker costs, commissions, slippage",
            "unseen native chronological out-of-sample replay for current canonical EA",
            "original executable Bid/Ask quote paths for post-stop conclusions",
            "small-account broker minimum-lot and margin feasibility",
            "independent prospective performance and bounded drawdown",
        ],
        "limitations": (
            "This is a review of recorded source summaries, NOT a new MT5 "
            "Strategy Tester run or verified broker fills. Positive native "
            "simulations are hypotheses, not statistical proof. The eight "
            "test PnLs cannot be combined into a portfolio return."
        ),
        "laptop_must_stay_on_to_read_existing_evidence": False,
        "broker_calls": 0, "orders_sent": 0,
    }


def make_html(result: dict) -> str:
    """Static local HTML without JavaScript, external images or private data."""
    esc = lambda item: html.escape(str(item), quote=True)
    f = result["forensics"]
    rows = "".join(
        "<tr><td>" + esc(x["style_id"]) + "</td><td>" + esc(x["name"]) +
        "</td><td>" + esc(x["positions"]) + "</td><td>" +
        esc(f'{x["native_net_usd"]:+.2f}') + "</td><td>" +
        esc(x["gate"]) + "</td></tr>" for x in f["styles"]
    )
    studies = "".join(
        "<tr><td>" + esc(x["study"]) + "</td><td>" +
        esc(x["decision"]) + "</td></tr>" for x in result["older_365d_studies"]
    )
    missing = "".join("<li>" + esc(s) + "</li>" for s in result["missing_acceptance"])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
        '<title>QTS Gold | Owner Evidence Verdict</title>'
        '<style>body{font:16px/1.6 Segoe UI,Arial,sans-serif;color:#182735;'
        'background:#f4f6f8;margin:0}main{max-width:980px;margin:2rem auto;padding:1.25rem}'
        'header{background:#18344b;color:white;padding:1.7rem;border-radius:14px}'
        'section{background:white;padding:1.25rem;margin-top:1rem;border:1px solid #dde5ec;'
        'border-radius:12px}table{width:100%;border-collapse:collapse}'
        'th,td{text-align:left;padding:.55rem;border-bottom:1px solid #dde5ec}'
        'table{display:block;overflow-x:auto}h1,h2{line-height:1.3}small{color:#51606b}</style>'
        '</head><body><main><header><h1>QTS Gold — Owner Verdict</h1>'
        '<p>NO INDEPENDENTLY VALIDATED PROFITABLE EDGE</p>'
        '<p>LIVE LOCKED | Research only | No broker orders</p></header>'
        '<section><h2>What the historical evidence says</h2>'
        '<p>938 completed positions over eight SEPARATE native simulations.'
        ' Arithmetic net across these unrelated tests: -$549.87 (NOT a portfolio result).'
        ' Broker charges and slippage are not independently verified.</p>'
        '<table><thead><tr><th>Style</th><th>Strategy</th><th>Positions</th>'
        '<th>Native USD</th><th>Classification</th></tr></thead><tbody>' +
        rows + '</tbody></table></section>'
        '<section><h2>Earlier 365-day research</h2>'
        '<p>These source summaries do not establish an executable edge.</p>'
        '<table><thead><tr><th>Study</th><th>Verdict</th></tr></thead><tbody>' +
        studies + '</tbody></table></section>'
        '<section><h2>Missing before accepting any strategy</h2><ul>' + missing +
        '</ul><p>Two positive historic styles (1 and 3) are exploratory only;'
        ' the already-viewed test period is not an untouched holdout.</p>'
        '<p>Existing research can be reviewed while your PC is offline.'
        ' Future native MT5 testing needs a running local terminal only during that test.</p>'
        '</section><section><h2>Research provenance</h2><p>' +
        esc(f["source"]) + '</p><p>' +
        esc(result["limitations"]) + '</p><small>Generated ' +
        esc(result["generated_at_utc"]) + '</small></section></main></body></html>'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.repo.resolve()
    target = args.out or (root / "gold_robot" / "reports_local" /
                          "owner_decision" / "QTS_OWNER_VERDICT")
    try:
        result = build(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.with_suffix(".json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8")
        target.with_suffix(".html").write_text(make_html(result), encoding="utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("QTS OWNER VERDICT BLOCKED_NO_GO: " + str(exc)[:250])
        return 2
    print("QTS OWNER VERDICT: " + result["status"])
    print("Native styles 1/3: exploratory only. No new native run was performed.")
    print("Report: " + str(target.with_suffix(".html")))
    print("LIVE LOCKED. No MT5 connection, broker orders, or always-on laptop required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
