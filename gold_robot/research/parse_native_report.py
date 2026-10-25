"""Extract native MT5 tester evidence and apply explicit hypothetical extra costs."""
from __future__ import annotations
import argparse
import html
import hashlib
import json
import re
from pathlib import Path


def cells(row: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)]


def value(document: str, label: str) -> str:
    match = re.search(r"<td\b[^>]*>\s*" + re.escape(label) +
                      r"\s*</td>\s*<td\b[^>]*>(.*?)</td>", document, re.I | re.S)
    if not match:
        raise ValueError(f"MT5 report field missing: {label}")
    return cells("<td>" + match.group(1) + "</td>")[0]


def number(raw: str) -> float:
    return float(raw.replace(" ", "").replace("\xa0", "").replace(",", ""))


def parse(path: Path, commission_per_lot: float = 10.0,
          exit_slippage_price: float = 0.05, contract_size: float = 100.0) -> dict:
    document = path.read_text(encoding="utf-16")
    summary = {name: value(document, label) for name, label in (
        ("history_quality", "History Quality:"), ("bars", "Bars:"),
        ("ticks", "Ticks:"), ("native_net_usd", "Total Net Profit:"),
        ("native_profit_factor", "Profit Factor:"),
        ("total_trades", "Total Trades:"),
        ("expected_payoff_usd", "Expected Payoff:"),
        ("equity_drawdown_maximal", "Equity Drawdown Maximal:"))}
    section = document.split(">Deals</b>", 1)
    if len(section) != 2:
        raise ValueError("MT5 deals table missing")
    exits = []
    for row in re.findall(r"<tr\s+bgcolor=[^>]+>(.*?)</tr>", section[1], re.I | re.S):
        fields = cells(row)
        if len(fields) >= 13 and fields[4].lower() in ("out", "in/out", "out by"):
            exits.append({"time": fields[0], "volume_lots": number(fields[5]),
                          "native_profit_usd": number(fields[10])})
    lots = sum(deal["volume_lots"] for deal in exits)
    native_net = number(summary["native_net_usd"])
    extra = lots * (commission_per_lot + exit_slippage_price * contract_size)
    return {"report": str(path), "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "summary": summary, "exit_deals": len(exits),
            "exited_volume_lots": round(lots, 8),
            "cost_assumption": {"extra_roundtrip_commission_usd_per_lot": commission_per_lot,
                                "extra_exit_slippage_price": exit_slippage_price,
                                "contract_size_oz_per_lot": contract_size,
                                "broker_tariff_verified": False},
            "additional_assumed_cost_usd": round(extra, 2),
            "indicative_net_after_extra_cost_usd": round(native_net-extra, 2),
            "note": "Spread is in native executable quotes. Extra fees and slippage are assumptions; swap and historical broker tariffs are unverified."}


if __name__ == "__main__":
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("report", type=Path)
    command.add_argument("output", type=Path)
    args = command.parse_args()
    result = parse(args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
