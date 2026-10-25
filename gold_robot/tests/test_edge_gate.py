from gold_robot.research.edge_gate import evaluate_trades


def row(date, gross, fee=0.10, slip=0.05):
    return {"date": date, "gross_usd": gross,
            "commission_usd": fee, "slippage_usd": slip}


def test_no_trades_not_validated():
    result = evaluate_trades([], 20)
    assert result["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"


def test_many_losing_trades_not_validated():
    trades = [row(f"2026-08-{1+i//5:02d}", 0.1) for i in range(100)]
    result = evaluate_trades(trades, 20)
    assert result["trades"] == 100
    assert result["net_usd"] < 0
    assert result["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"


def test_explicit_cost_once():
    result = evaluate_trades([row("2026-08-01", 2, 0.2, 0.1)], 1)
    assert result["net_usd"] == 1.7


def test_bootstrap_deterministic():
    trades = [row(f"2026-08-{i+1:02d}", 1 if i % 2 else -1)
              for i in range(20)]
    assert evaluate_trades(trades, 20) == evaluate_trades(trades, 20)
