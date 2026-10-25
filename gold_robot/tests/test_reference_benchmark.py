"""Contract tests for matched external-EA research; no broker calls."""
import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from reference_benchmark import compare, load_ledger

FIELDS = (
    "deal_id", "exit_time_utc", "side", "gross_usd",
    "commission_usd", "slippage_usd", "swap_usd", "fee_usd",
)


def bundle(tmp_path, name, rows, **overrides):
    folder = tmp_path / name
    folder.mkdir()
    ledger = folder / "trades.csv"
    with ledger.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "schema_version": 1,
        "source": f"fixture {name}",
        "broker": "WMMarkets",
        "symbol": "XAUUSD@",
        "account_type": "TESTER",
        "account_currency": "USD",
        "account_key": name,
        "period_start": "2026-10-01",
        "period_end": "2026-10-04",
        "initial_equity_usd": 10000,
        "cost_basis": "EXECUTABLE_BID_ASK",
        "ledger": ledger.name,
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
    }
    manifest.update(overrides)
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def trade(ident="a", when="2026-10-01T10:00:00Z",
          gross=10, commission=1, slip=0.5, swap=0, fee=0):
    return {
        "deal_id": ident,
        "exit_time_utc": when,
        "side": "BUY",
        "gross_usd": gross,
        "commission_usd": commission,
        "slippage_usd": slip,
        "swap_usd": swap,
        "fee_usd": fee,
    }


def test_matched_accounts_compare_after_costs_without_promoting(tmp_path):
    c = load_ledger(bundle(tmp_path, "qts", [trade(gross=10)]))
    r = load_ledger(bundle(tmp_path, "vendor", [trade(gross=5, commission=0, slip=0)]))
    result = compare(c, r)
    assert result == compare(c, r)  # seed controls paired bootstrap
    assert result["candidate"]["net_usd"] == 8.5
    assert result["reference"]["net_usd"] == 5
    assert result["calendar_days_including_no_trades"] == 4
    assert result["candidate"]["net_pct_starting_equity"] == 0.085
    assert result["status"] == "RESEARCH_COMPARISON_ONLY_NOT_VALIDATED"
    assert result["paired_daily_mean_difference_pct_starting_equity"] == pytest.approx(0.00875)


@pytest.mark.parametrize("key,value", [
    ("broker", "OtherBroker"),
    ("symbol", "XAUUSD"),
    ("account_type", "REAL"),
    ("period_start", "2026-10-02"),
    ("period_end", "2026-10-05"),
    ("account_currency", "EUR"),
    ("cost_basis", "MID_PRICE"),
])
def test_reject_incomparable_or_invalid_benchmarks(tmp_path, key, value):
    c = load_ledger(bundle(tmp_path, "qts", [trade()]))
    vendor_path = bundle(tmp_path, "vendor", [trade()], **{key: value})
    if key in ("account_currency", "cost_basis"):
        with pytest.raises(ValueError):
            load_ledger(vendor_path)
    elif key == "period_start":
        with pytest.raises(ValueError, match="outside declared"):
            load_ledger(vendor_path)
    else:
        with pytest.raises(ValueError, match="incomparable"):
            compare(c, load_ledger(vendor_path))


def test_same_underlying_account_on_two_sites_is_not_independent(tmp_path):
    c = load_ledger(bundle(tmp_path, "qts", [trade()]))
    r = load_ledger(bundle(tmp_path, "vendor", [trade()], account_key="qts"))
    with pytest.raises(ValueError, match="same underlying account"):
        compare(c, r)


def test_checksum_change_detected(tmp_path):
    path = bundle(tmp_path, "qts", [trade()])
    ledger = path.parent / "trades.csv"
    ledger.write_text(ledger.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        load_ledger(path)


def test_duplicate_ticket_blocks_fake_trade_count(tmp_path):
    path = bundle(tmp_path, "qts", [trade(), trade(when="2026-10-02T10:00:00Z")])
    with pytest.raises(ValueError, match="duplicate"):
        load_ledger(path)


@pytest.mark.parametrize("when", [
    "2026-10-01T10:00:00",
    "2026-10-01T15:00:00+05:00",
    "2026-09-30T10:00:00Z",
])
def test_reject_timezone_or_out_of_window(tmp_path, when):
    path = bundle(tmp_path, "qts", [trade(when=when)])
    with pytest.raises(ValueError):
        load_ledger(path)


def test_fee_cannot_be_negative_but_swap_credit_can(tmp_path):
    c = load_ledger(bundle(tmp_path, "qts", [trade(swap=-1)]))
    assert c.trades[0][1] == 9.5
    bad = bundle(tmp_path, "vendor", [trade(commission=-1)])
    with pytest.raises(ValueError):
        load_ledger(bad)


def test_no_trade_days_and_zero_trades_are_not_fake_profits(tmp_path):
    c = load_ledger(bundle(tmp_path, "qts", []))
    r = load_ledger(bundle(tmp_path, "vendor", []))
    result = compare(c, r)
    assert result["candidate"]["trades"] == 0
    assert result["candidate"]["profit_factor"] is None
    assert result["paired_daily_mean_difference_pct_starting_equity"] == 0
    assert result["status"].endswith("NOT_VALIDATED")


def test_reject_opaque_or_parent_ledger_path(tmp_path):
    path = bundle(tmp_path, "qts", [trade()], ledger="../trades.csv")
    with pytest.raises(ValueError, match="CSV basename"):
        load_ledger(path)
