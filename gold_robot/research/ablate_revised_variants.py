"""Four-arm native MT5 forensic comparison; RESEARCH ONLY.

October 2026 has already been inspected. This is an exploratory ablation,
NOT an independent future holdout. No trading orders and no parameter fitting.
All strategies are independent MT5 studies, not a combined portfolio.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
from collections import Counter
from pathlib import Path
from datetime import date, datetime, timedelta

from compare_revised_variants import load_run
from paired_variant_diagnostics import paired_diagnostic

ARMS = ("BASELINE", "ENTRY_FILTER", "NEAR_TP", "COMBINED")
STYLES = (1, 3, 7, 8)


def factorial_interaction(baseline: float, entry_only: float,
                          exit_only: float, combined: float) -> float:
    """Non-additive A/B interaction; not a causal estimate of live PnL."""
    return round(combined - entry_only - exit_only + baseline, 2)


def ledger(root: Path, style: int) -> dict:
    """Reconcile the raw exported broker deals with comparison HTML metrics."""
    path = root / "native" / f"QTS_{style}_trades.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if not rows:
        raise ValueError(f"Missing native deal evidence: {path}")
    seen_deals = set()
    positions = {}
    gross = charges = 0.0
    lots = 0.0
    for row in rows:
        did = row["deal_id"]
        if did in seen_deals:
            raise ValueError(f"Duplicate broker deal id {did} style={style}")
        seen_deals.add(did)
        pid = row["position_id"]
        pos = positions.setdefault(pid, {"entries": 0, "exits": 0})
        entry = row["entry"]
        if entry == "DEAL_ENTRY_IN":
            pos["entries"] += 1
            lots += float(row["volume"])
        elif entry == "DEAL_ENTRY_OUT":
            pos["exits"] += 1
        else:
            raise ValueError(f"Unsupported partial or reversing broker deal: {entry}")
        gross += float(row["gross"])
        charges += sum(float(row[k]) for k in ("commission", "swap", "fee"))
    if any(p["entries"] != 1 or p["exits"] != 1 for p in positions.values()):
        raise ValueError("Partial position or missing entry/exit leg: require exact native facts")
    return {
        "positions": len(positions), "entry_lots_sum": round(lots, 8),
        "native_deals": len(rows), "gross_usd": round(gross, 2),
        "recorded_charges_usd": round(charges, 2),
        "recorded_net_usd": round(gross + charges, 2),
    }



def verify_original_report(folder: Path, style: int, row: dict) -> None:
    """Reconcile reported MT5 metrics against the preserved, hash-matched HTML."""
    path = folder / "native" / f"QTS_{style}.htm"
    original = path.read_bytes()
    checksum = hashlib.sha256(original).hexdigest()
    if checksum != str(row["sha256"]).lower():
        raise ValueError(f"Native HTML checksum mismatch: style={style}")
    if original.startswith((b"\xff\xfe", b"\xfe\xff")):
        document = original.decode("utf-16")
    elif b"\x00" in original[:100]:
        document = original.decode("utf-16-le")
    else:
        try:
            document = original.decode("utf-8-sig")
        except UnicodeDecodeError:
            document = original.decode("cp1252")
    if re.search(r"(?is)<html\b|<!doctype\s+html\b", document) is None:
        raise ValueError(f"Native HTML report invalid: style={style}")
    visible = html.unescape(re.sub(r"(?is)<[^>]+>", " ", document))
    styles = re.findall(r"(?i)\bEntryStyle\s*=\s*([0-9])\b", visible)
    if not styles or any(int(found) != style for found in styles):
        raise ValueError(f"Native HTML EntryStyle mismatch: style={style}")
    fields = ("Total Net Profit", "Profit Factor",
              "Total Trades", "Equity Drawdown Maximal")
    found = {}
    for match in re.finditer(r"(?is)<tr\b[^>]*>(.*?)</tr>", document):
        cells = [
            html.unescape(re.sub(r"(?is)<[^>]*>", "", item.group(1))).strip()
            for item in re.finditer(r"(?is)<td\b[^>]*>(.*?)</td>", match.group(1))
        ]
        for index, cell in enumerate(cells[:-1]):
            label = cell.rstrip(":").strip()
            if label in fields and label not in found:
                found[label] = cells[index + 1]
    if set(found) != set(fields):
        raise ValueError(f"Native HTML metrics missing: style={style}")
    def numeric(value: str) -> float:
        first = value.split("(", 1)[0]
        cleaned = re.sub(r"[\s,\u00a0\u202f]", "", first)
        result = float(cleaned)
        if not math.isfinite(result):
            raise ValueError("Nonfinite MT5 HTML metric")
        return result
    expected = {
        "Total Net Profit": float(row["net_usd"]),
        "Profit Factor": float(row["profit_factor"]),
        "Total Trades": float(row["trades"]),
        "Equity Drawdown Maximal": float(row["maximal_equity_drawdown"]),
    }
    for label, reported in expected.items():
        observed = numeric(found[label])
        if not math.isfinite(reported) or abs(observed - reported) > (
                0 if label == "Total Trades" else 0.021):
            raise ValueError(f"Native HTML metric mismatch: {label} style={style}")



def compare_ablation(root: Path) -> dict:
    loaded = {}
    for arm in ARMS:
        run = root / arm.lower()
        outcome, reports = load_run(run, arm)
        loaded[arm] = (run, outcome, reports)
    keys = ("from_date", "to_date", "deposit_usd", "model", "symbol", "timeframe")
    base = loaded["BASELINE"][1]
    if any(loaded[arm][1].get(key) != base.get(key) for arm in ARMS for key in keys):
        raise ValueError("Native four-arm strategy tester settings do not match")
    try:
        start = datetime.strptime(base["from_date"], "%Y.%m.%d").date()
        end = datetime.strptime(base["to_date"], "%Y.%m.%d").date()
    except (KeyError, ValueError) as exc:
        raise ValueError("Malformed native test interval") from exc
    legacy_october = (start == date(2026, 10, 1) and end == date(2026, 10, 30))
    future_calendar_month = (
        start >= date(2026, 11, 1) and start.day == 1 and
        end == (date(start.year + 1, 1, 1) if start.month == 12
                else date(start.year, start.month + 1, 1))
    )
    if not (legacy_october or future_calendar_month):
        raise ValueError("Ablation only accepts original October study or complete future calendar months")
    studies = []
    for style in STYLES:
        arms = {}
        for arm in ARMS:
            folder, _, parsed = loaded[arm]
            row = parsed[style]
            verify_original_report(folder, style, row)
            raw = ledger(folder, style)
            if abs(raw["recorded_net_usd"] - float(row["net_usd"])) > 0.02:
                raise ValueError(f"Broker deal PnL disagrees with native report: {arm} style={style}")
            if raw["positions"] != int(row["trades"]):
                raise ValueError(f"Broker position count differs from native report: {arm} style={style}")
            arms[arm] = {
                **raw,
                "profit_factor": float(row["profit_factor"]),
                "max_equity_drawdown_usd": float(row["maximal_equity_drawdown"]),
                "additional_round_turn_cost_10_per_lot_usd": round(
                    raw["recorded_net_usd"] - 10 * raw["entry_lots_sum"], 2),
                "profit_per_position_usd": round(
                    raw["recorded_net_usd"] / raw["positions"], 4)
                if raw["positions"] else None,
            }
        # Do not describe a net difference as an entry/exit improvement until
        # executed broker entries are aligned. Different fills/order sequence
        # explain changes that naive PnL subtraction cannot attribute.
        paired = {}
        for variant in ARMS[1:]:
            paired[variant] = paired_diagnostic(
                loaded["BASELINE"][0] / "native" / f"QTS_{style}_trades.csv",
                loaded[variant][0] / "native" / f"QTS_{style}_trades.csv",
                expected_base_trades=arms["BASELINE"]["positions"],
                expected_revised_trades=arms[variant]["positions"],
                expected_base_net=arms["BASELINE"]["recorded_net_usd"],
                expected_revised_net=arms[variant]["recorded_net_usd"],
            )
        interaction = factorial_interaction(
            arms["BASELINE"]["recorded_net_usd"],
            arms["ENTRY_FILTER"]["recorded_net_usd"],
            arms["NEAR_TP"]["recorded_net_usd"],
            arms["COMBINED"]["recorded_net_usd"],
        )
        studies.append({
            "style": style, "arms": arms,
            "exact_entry_pair_audit": paired,
            "entry_exit_interaction_usd": interaction,
            "non_additive_entry_exit_interaction": abs(interaction) >= 0.01,
            "evidence_sufficient_for_automatic_promotion": False,
            "delta_entry_filter_usd": round(
                arms["ENTRY_FILTER"]["recorded_net_usd"] -
                arms["BASELINE"]["recorded_net_usd"], 2),
            "delta_near_tp_usd": round(
                arms["NEAR_TP"]["recorded_net_usd"] -
                arms["BASELINE"]["recorded_net_usd"], 2),
            "delta_combined_usd": round(
                arms["COMBINED"]["recorded_net_usd"] -
                arms["BASELINE"]["recorded_net_usd"], 2),
        })
    return {
        "schema": "qts.mt5.v2.four_arm_exploratory_ablation.v2",
        "status": "RESEARCH_ONLY_POST_HOC_OCTOBER" if legacy_october else "RESEARCH_ONLY_NEW_MONTH_NO_TRADE_APPROVAL",
        "from_date": base["from_date"], "to_date": base["to_date"],
        "arms": {
            "BASELINE": ["EntryQualityV2=off", "ProtectNearTPV2=off"],
            "ENTRY_FILTER": ["EntryQualityV2=on", "ProtectNearTPV2=off"],
            "NEAR_TP": ["EntryQualityV2=off", "ProtectNearTPV2=on"],
            "COMBINED": ["EntryQualityV2=on", "ProtectNearTPV2=on"],
        },
        "studies": studies,
        "costs_independently_verified": False,
        "live": "LOCKED",
        "edge_validated": False,
        "warnings": [
            "Historical replay or repeated inspection cannot establish independent future performance. October 2026 was previously inspected.",
            "Interaction and differences in executed entries must be investigated before claiming one filter caused an improvement.",
            "A one-month outcome or selected style cannot certify repeatable positive expectancy.",
            "No strategy is automatically promoted or enabled on connected broker accounts.",
            "Each strategy was tested separately. Do not sum the PnL into a portfolio.",
            "Additional per-lot cost is a scenario, not a claim about WMMarkets actual commissions or already-filled spread.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = compare_ablation(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("QTS GOLD FOUR ARM ABLATION - RESEARCH ONLY / LIVE LOCKED")
    for s in data["studies"]:
        print(f"Style {s['style']}: " + ", ".join(
            f"{arm}={s['arms'][arm]['recorded_net_usd']:+.2f}"
            for arm in ARMS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
