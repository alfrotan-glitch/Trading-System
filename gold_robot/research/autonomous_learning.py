"""QTS autonomous research journal. Never changes EA code, orders, risk or live flags.

On Windows a scheduled runner reads NEW local native MT5 evidence. Months are
unique units of observation; four arms from the same month are NOT independent
trials. Decisions are hypotheses for future tests, not optimizer permissions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from ablate_revised_variants import ARMS, STYLES, compare_ablation

SCHEMA = "qts.autonomous.research_journal.v1"
MAX_ARCHIVE = 30_000_000
MAX_MEMBER = 8_000_000
PERIOD_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")


def safe_save(path: Path, value: dict) -> None:
    """Atomic update for derived state. Evidence receipts are content addressed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False,
        suffix=".tmp"
    ) as stream:
        temp = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp, path)


def parse_day(value: str) -> date:
    if not PERIOD_PATTERN.fullmatch(value):
        raise ValueError("Malformed research period")
    return datetime.strptime(value, "%Y.%m.%d").date()


def month_after(start: date) -> date:
    return date(start.year + (start.month == 12),
                1 if start.month == 12 else start.month + 1, 1)


def accepted_window(start: str, end: str) -> bool:
    first, last = parse_day(start), parse_day(end)
    return (first == date(2026, 10, 1) and last == date(2026, 10, 30)) or (
        first >= date(2026, 11, 1) and first.day == 1 and
        month_after(first) == last)


def read_verified_archive(path: Path) -> dict:
    """Accept only canonical native evidence; never extract unsafe ZIP names."""
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Evidence archive absent or oversized")
    with tempfile.TemporaryDirectory(prefix="qts-autoresearch-") as scratch:
        root = Path(scratch)
        present = set()
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 100:
                raise ValueError("Evidence has too many members")
            total = 0
            for member in members:
                if member.is_dir():
                    continue
                rel = member.filename.replace("\\", "/")
                parts = rel.split("/")
                if (rel.startswith("/") or ".." in parts or
                    not (len(parts) in (2, 3) and parts[0] in
                         tuple(a.lower() for a in ARMS)) or
                    (len(parts) == 3 and parts[1] != "native")):
                    # Top-level comparison JSON and RUN_STATUS.txt are
                    # supplementary, and never treated as authoritative.
                    if rel in ("QTS_V2_ABLATION_COMPARISON.json", "RUN_STATUS.txt"):
                        continue
                    raise ValueError("Unrecognized or unsafe ZIP member")
                name = parts[-1]
                is_native = (
                    name.startswith("QTS_") and (
                        (name.endswith("_trades.csv") and
                         name[4:-11].isdigit() and int(name[4:-11]) in STYLES) or
                        (name.endswith(".htm") and
                         name[4:-4].isdigit() and int(name[4:-4]) in STYLES)
                    )
                )
                is_summary = (name == "OPEN_RESULTS.json" or
                              re.fullmatch(r"QTS_Gold_Comparison_[\w-]+\.json", name))
                is_detail = name == "QTS_TRADE_BY_TRADE.json"
                if not (is_native or is_summary or is_detail):
                    raise ValueError("Unexpected native ZIP member")
                if member.file_size > MAX_MEMBER:
                    raise ValueError("Oversized native evidence member")
                total += member.file_size
                canonical = parts[0] + "/" + ("native/" if is_native else "") + name
                if total > 35_000_000 or canonical in present:
                    raise ValueError("Duplicate or oversized ZIP evidence")
                present.add(canonical)
                dest = (root / parts[0] / ("native" if is_native else "") / name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(member)
                if len(data) != member.file_size:
                    raise ValueError("Truncated compressed evidence")
                dest.write_bytes(data)
        for arm in ARMS:
            low = arm.lower()
            if f"{low}/OPEN_RESULTS.json" not in present:
                raise ValueError("Missing arm research manifest")
            for style in STYLES:
                if f"{low}/native/QTS_{style}_trades.csv" not in present:
                    raise ValueError("Missing native position ledger")
                if f"{low}/native/QTS_{style}.htm" not in present:
                    raise ValueError("Missing original MT5 HTML report")
        result = compare_ablation(root)
    if result["live"] != "LOCKED" or result["edge_validated"] is not False:
        raise ValueError("Unsafe or unsupported reported trade authority")
    if not accepted_window(result["from_date"], result["to_date"]):
        raise ValueError("Invalid or overlapping research period")
    return result


def make_receipt(digest: str, result: dict) -> dict:
    """Derive every learned metric solely from validated native evidence."""
    receipt = {
        "schema": SCHEMA, "sha256": digest, "source_name": path.name,
        "period_start": result["from_date"],
        "period_end": result["to_date"],
        "status": result["status"], "live": "LOCKED",
        "trading_authority": False,
        "studies": [{
            "style": s["style"],
            "arms": {arm: {
                "net_usd": s["arms"][arm]["recorded_net_usd"],
                "positions": s["arms"][arm]["positions"],
                "lots": s["arms"][arm]["entry_lots_sum"],
                "cost_stress_10": s["arms"][arm]["additional_round_turn_cost_10_per_lot_usd"],
                "drawdown_usd": s["arms"][arm]["max_equity_drawdown_usd"],
            } for arm in ARMS},
            "interaction_usd": s["entry_exit_interaction_usd"],
            "paired": {arm: {
                "matched": s["exact_entry_pair_audit"][arm]["matched_entries"],
                "baseline_only": s["exact_entry_pair_audit"][arm]["baseline_only_entries"],
                "variant_only": s["exact_entry_pair_audit"][arm]["revised_only_entries"],
            } for arm in ARMS[1:]},
        } for s in result["studies"]],
    }
    return receipt


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preserve_archive(source: Path, target: Path, digest: str) -> None:
    """Keep an independent, content-addressed source for every receipt."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(target) != digest:
            raise ValueError("Stored original evidence checksum mismatch")
        return
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with source.open("rb") as original:
                shutil.copyfileobj(original, stream)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        if sha256_file(temporary) != digest:
            raise ValueError("Evidence changed while being archived")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def read_receipts(store: Path) -> tuple[list[dict], list[dict]]:
    """Fail closed for any modified or unbacked receipt; never trust JSON alone."""
    reports, problems = [], []
    for path in sorted((store / "evidence").glob("*.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            digest = result.get("sha256")
            if (result.get("schema") != SCHEMA or
                not isinstance(digest, str) or
                re.fullmatch(r"[0-9a-f]{64}", digest) is None or
                path.name != digest + ".json"):
                raise ValueError("Invalid content-addressed receipt")
            original = store / "archives" / (digest + ".zip")
            if not original.is_file() or sha256_file(original) != digest:
                raise ValueError("Original ZIP missing or checksum mismatch")
            rebuilt = make_receipt(digest, read_verified_archive(original))
            if result != rebuilt:
                raise ValueError("Receipt does not match independently rederived native data")
            reports.append(result)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            problems.append({"filename": path.name, "parent": "journal",
                             "error": ("Untrusted stored receipt: " + str(exc))[:250]})
    return reports, problems


def ingest(evidence_root: Path, store: Path) -> tuple[list[dict], list[dict]]:
    receipts, issues = read_receipts(store)
    existing = {r["sha256"] for r in receipts}
    # Never truncate discovery: old/new periods are not cherry-picked.
    for path in sorted(evidence_root.glob("**/QTS_V2_ABLATION_EVIDENCE.zip")):
        try:
            if path.stat().st_size > MAX_ARCHIVE:
                raise ValueError("Oversized evidence archive")
            digest = sha256_file(path)
            if digest in existing:
                continue
            destination = store / "evidence" / (digest + ".json")
            if destination.exists():
                raise ValueError("Existing receipt is untrusted; inspect or quarantine it first")
            result = read_verified_archive(path)
            receipt = make_receipt(digest, result)
            preserve_archive(path, store / "archives" / (digest + ".zip"), digest)
            safe_save(destination, receipt)
            receipts.append(receipt)
            existing.add(digest)
        except (OSError, ValueError, zipfile.BadZipFile,
                KeyError, TypeError) as exc:
            issues.append({"filename": path.name, "parent": path.parent.name,
                           "error": str(exc)[:250]})
    return receipts, issues


def lessons(receipts: list[dict]) -> dict:
    months = defaultdict(list)
    for receipt in receipts:
        months[(receipt["period_start"], receipt["period_end"])].append(receipt)
    conflicts = [
        {"from": a, "to": b, "receipt_count": len(group)}
        for (a, b), group in sorted(months.items()) if len(group) > 1
    ]
    # Conflicted months never enter learning, even if one variant won.
    unique = [g[0] for g in months.values() if len(g) == 1]
    unique.sort(key=lambda r: r["period_start"])
    summaries = []
    for style in STYLES:
        evidence = [next(s for s in r["studies"] if s["style"] == style)
                    for r in unique]
        prior = [row for row, r in zip(evidence, unique)
                 if parse_day(r["period_start"]) >= date(2026, 11, 1)]
        by_arm = {}
        for arm in ARMS:
            by_arm[arm] = {
                "studied_months": len(evidence),
                "future_months_since_november_2026": len(prior),
                "months_positive_after_extra_cost": sum(
                    s["arms"][arm]["cost_stress_10"] > 0 for s in prior),
                "monthly_results": [
                    {"month": r["period_start"],
                     "net_usd": s["arms"][arm]["net_usd"],
                     "cost_stress_10": s["arms"][arm]["cost_stress_10"],
                     "positions": s["arms"][arm]["positions"]}
                    for r, s in zip(unique, evidence)],
            }
        notes = []
        if evidence:
            latest = evidence[-1]
            original = latest["arms"]["BASELINE"]["net_usd"]
            filtered = latest["arms"]["ENTRY_FILTER"]["net_usd"]
            exit_only = latest["arms"]["NEAR_TP"]["net_usd"]
            if latest["interaction_usd"] != 0:
                notes.append("NON_ADDITIVE_ENTRY_EXIT_INTERACTION: audit actual position sequence")
            if filtered > original:
                notes.append("ENTRY_FILTER_IMPROVED_OBSERVED_MONTH: retest prospectively")
            if exit_only < original:
                notes.append("NEAR_TP_WORSENED_OBSERVED_MONTH: do not assume protective stop helps")
            if original < 0:
                notes.append("NEGATIVE_BASELINE_EXPECTANCY_OBSERVED: investigate entry setup families")
            if not notes:
                notes.append("NO_CLEAR_ADVANTAGE: preserve baseline and gather new independent periods")
        else:
            notes.append("NO_RECONCILED_NATIVE_EVIDENCE")
        summaries.append({"style": style, "by_arm": by_arm,
                          "research_notes": notes,
                          "approved_configuration": None,
                          "may_self_modify_live_robot": False})
    return {"conflicting_periods": conflicts,
            "unique_periods": len(unique),
            "periods": [r["period_start"] for r in unique],
            "strategies": summaries}


def next_window(today: date, receipts: list[dict], attempts: dict) -> dict | None:
    """Oldest missing completed calendar month first; no retroactive holdout claims."""
    completed = date(today.year, today.month, 1)
    start = date(2026, 11, 1)
    recorded = {(r["period_start"], r["period_end"]) for r in receipts}
    while start < completed:
        end = month_after(start)
        a, b = start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d")
        if (a, b) not in recorded and attempts.get(a, 0) < 2:
            return {"from_date": a, "to_date": b,
                    "attempts_so_far": attempts.get(a, 0)}
        start = end
    return None


def cycle(evidence_root: Path, store: Path, today: date) -> dict:
    receipts, issues = ingest(evidence_root, store)
    attempts_path = store / "attempts.json"
    attempts = json.loads(attempts_path.read_text(encoding="utf-8")) if attempts_path.exists() else {}
    info = {
        "schema": SCHEMA, "state": "AUTONOMOUS_RESEARCH_READY",
        "live": "LOCKED", "edge_validated": False,
        "orders_sent": 0, "auto_modify_ea": False,
        "independent_broker_costs_verified": False,
        "evidence_receipts": len(receipts), "rejected_evidence": issues,
        "lessons": lessons(receipts),
        "next_monthly_test": next_window(today, receipts, attempts),
        "warning": "Monthly MT5 tests on the owner's Windows PC only; no automatic trade authorization or code rewriting.",
    }
    safe_save(store / "QTS_AUTONOMOUS_STATUS.json", info)
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--today", default=None, help="ISO local calendar date; tests only")
    parser.add_argument("--reserve", default=None, help="reserve next approved YYYY.MM.DD monthly research window")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    status = cycle(args.evidence_root, args.state_root, today)
    if args.reserve:
        w = status["next_monthly_test"]
        if w is None or w["from_date"] != args.reserve:
            raise SystemExit("No new eligible monthly window to reserve")
        attempts_file = args.state_root / "attempts.json"
        attempts = json.loads(attempts_file.read_text()) if attempts_file.exists() else {}
        attempts[args.reserve] = attempts.get(args.reserve, 0) + 1
        safe_save(attempts_file, attempts)
        status = cycle(args.evidence_root, args.state_root, today)
    print(json.dumps({
        "live": status["live"], "receipts": status["evidence_receipts"],
        "next_monthly_test": status["next_monthly_test"],
        "conflicts": len(status["lessons"]["conflicting_periods"]),
        "rejected": len(status["rejected_evidence"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
