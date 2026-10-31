"""Native broker-deal A/B audit. Descriptive only; NEVER authorizes trading.

Matches an entry only when MT5 executed its same timestamp, direction,
price and volume in both runs. A changed exit, nonfill or different entry
cannot silently be presented as a paired counterfactual. Commissions recorded
in native deals are included; extra costs are explicit stress scenarios.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

REQUIRED = frozenset({
    "position_id", "deal_id", "entry", "type", "time_msc", "volume",
    "price", "sl", "tp", "reason", "gross", "commission", "swap", "fee",
})
CHARGES = ("gross", "commission", "swap", "fee")


def finite(row: dict, name: str) -> float:
    value = float(row[name])
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite native deal value: {name}")
    return value


def load_positions(path: Path) -> list[dict]:
    """Fail closed on malformed/partial/duplicate MT5 broker deals.

    A valid header-only export represents zero positions. This is NOT
    evidence of strategy quality, and is reported as inconclusive elsewhere.
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError(f"Native deal fields missing: {path}")
        rows = list(reader)
    deals = set()
    groups: dict[str, dict] = {}
    for row in rows:
        if None in row or not row["position_id"] or not row["deal_id"]:
            raise ValueError("Malformed native deal row")
        if row["deal_id"] in deals:
            raise ValueError("Duplicate native broker deal_id")
        deals.add(row["deal_id"])
        if row["entry"] not in ("DEAL_ENTRY_IN", "DEAL_ENTRY_OUT"):
            raise ValueError("Partial/reversing broker deals require explicit reconstruction")
        if finite(row, "volume") <= 0 or finite(row, "price") <= 0:
            raise ValueError("Invalid broker price or volume")
        for k in ("sl", "tp", *CHARGES):
            finite(row, k)
        if not row["time_msc"].isdigit() or int(row["time_msc"]) <= 0:
            raise ValueError("Invalid broker deal timestamp")
        position = groups.setdefault(row["position_id"], {})
        leg = "open" if row["entry"] == "DEAL_ENTRY_IN" else "close"
        if leg in position:
            raise ValueError("Multiple entries/exits in native position")
        position[leg] = row
    positions = []
    for pid, position in groups.items():
        if set(position) != {"open", "close"}:
            raise ValueError("Missing entry/exit native deal leg")
        entry, close = position["open"], position["close"]
        if abs(finite(entry, "volume") - finite(close, "volume")) > 1e-7:
            raise ValueError("Partial fills require volume-aware position reconstruction")
        if int(close["time_msc"]) < int(entry["time_msc"]):
            raise ValueError("Exit precedes entry")
        position["position_id"] = pid
        position["net"] = sum(finite(d, k) for d in (entry, close) for k in CHARGES)
        positions.append(position)
    return positions


def summary(positions: list[dict]) -> dict:
    lots = sum(finite(p["open"], "volume") for p in positions)
    net = sum(p["net"] for p in positions)
    return {
        "positions": len(positions),
        "recorded_net_usd": round(net, 2),
        "entry_lots_sum": round(lots, 8),
        "extra_cost_10_usd_per_lot_net_usd": round(net - 10.0 * lots, 2),
        "extra_cost_30_usd_per_lot_net_usd": round(net - 30.0 * lots, 2),
        "stop_exits": sum(p["close"]["reason"] == "DEAL_REASON_SL" for p in positions),
        "target_exits": sum(p["close"]["reason"] == "DEAL_REASON_TP" for p in positions),
        "modified_stop_exits": sum(
            p["open"]["sl"] != p["close"]["sl"] for p in positions),
    }


def key(position: dict) -> tuple:
    entry = position["open"]
    return (entry["time_msc"], entry["type"],
            entry["price"], entry["volume"])


def paired_diagnostic(base: Path, revised: Path,
                      *, expected_base_trades: int, expected_revised_trades: int,
                      expected_base_net: float, expected_revised_net: float) -> dict:
    before = load_positions(base)
    after = load_positions(revised)
    a, b = summary(before), summary(after)
    for observed, expected_n, expected_net, label in (
        (a, expected_base_trades, expected_base_net, "baseline"),
        (b, expected_revised_trades, expected_revised_net, "revised"),
    ):
        if observed["positions"] != expected_n or abs(
                observed["recorded_net_usd"] - expected_net) > 0.02:
            raise ValueError(f"Native {label} deal ledger conflicts with MT5 report")
    before_keyed = {key(p): p for p in before}
    after_keyed = {key(p): p for p in after}
    if len(before_keyed) != len(before) or len(after_keyed) != len(after):
        raise ValueError("Ambiguous duplicate native entry identity")
    changed = []
    for k in sorted(before_keyed.keys() & after_keyed.keys()):
        p, q = before_keyed[k], after_keyed[k]
        if abs(p["net"] - q["net"]) > 0.005 or (
                p["close"]["reason"] != q["close"]["reason"]):
            changed.append({
                "entry_time_msc": k[0], "side": k[1],
                "baseline_net_usd": round(p["net"], 2),
                "revised_net_usd": round(q["net"], 2),
                "delta_usd": round(q["net"] - p["net"], 2),
                "baseline_exit_reason": p["close"]["reason"],
                "revised_exit_reason": q["close"]["reason"],
                "protective_stop_modified": q["open"]["sl"] != q["close"]["sl"],
            })
    matched = len(before_keyed.keys() & after_keyed.keys())
    return {
        "baseline": a, "revised": b,
        "native_net_delta_usd": round(b["recorded_net_usd"] - a["recorded_net_usd"], 2),
        "net_delta_after_extra_cost_10_per_lot_usd": round(
            b["extra_cost_10_usd_per_lot_net_usd"] -
            a["extra_cost_10_usd_per_lot_net_usd"], 2),
        "matched_entries": matched,
        "baseline_only_entries": len(before_keyed) - matched,
        "revised_only_entries": len(after_keyed) - matched,
        "matched_entries_with_different_outcomes": changed,
        "evidence_sufficient_for_automatic_promotion": False,
        "limitations": [
            "One previously inspected month is descriptive, not a fresh out-of-sample test.",
            "Identical entries can have different exits; omitted/unmatched entries may change later opportunities.",
            "Native recorded charges are included. Extra per-lot costs are hypothetical, not a broker tariff.",
            "The same entry observed in two tests is NOT a guarantee of identical real-world fills.",
        ],
    }
