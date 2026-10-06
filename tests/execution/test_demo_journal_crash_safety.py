from datetime import UTC, datetime, timedelta

from qts.db import connect
from qts.execution.demo_journal import DemoOrderJournal


def _claim(journal: DemoOrderJournal, client_order_id: str):
    return journal.claim_order_slot(
        client_order_id=client_order_id,
        strategy_id="test-strategy",
        strategy_config_hash="hash",
        symbol="XAUUSD",
        broker_symbol="XAUUSD@",
        side="BUY",
        requested_lots="0.01",
        order_request={"symbol": "XAUUSD@", "volume": "0.01"},
        min_interval_s=0,
        stale_inflight_s=120,
    )


def test_stale_inflight_becomes_ambiguous_not_rejected(tmp_path):
    journal = DemoOrderJournal(tmp_path / "journal.db")
    journal.open_order(
        client_order_id="old-order",
        strategy_id="test-strategy",
        strategy_config_hash="hash",
        symbol="XAUUSD",
        side="BUY",
        requested_lots="0.01",
        order_request={"symbol": "XAUUSD@"},
    )
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    with connect(journal.db_path) as con:
        con.execute(
            "UPDATE demo_order_journal SET requested_at=?, updated_at=? WHERE client_order_id=?",
            (old, old, "old-order"),
        )
        con.commit()

    journal.expire_inflight_rows(max_age_s=120)
    row = journal.get_by_client_order_id("old-order")

    assert row is not None
    assert row["state"] == "AMBIGUOUS"
    assert "reconciliation required" in row["exit_reason"]


def test_claim_rejects_reused_client_order_id(tmp_path):
    journal = DemoOrderJournal(tmp_path / "journal.db")
    first, reason = _claim(journal, "same-id")
    assert first is not None
    assert reason == "claimed"

    second, reason = _claim(journal, "same-id")
    assert second is None
    assert "already exists" in reason


def test_ambiguous_order_is_global_submission_barrier(tmp_path):
    journal = DemoOrderJournal(tmp_path / "journal.db")
    journal.open_order(
        client_order_id="ambiguous-id",
        strategy_id="test-strategy",
        strategy_config_hash="hash",
        symbol="XAUUSD",
        side="BUY",
        requested_lots="0.01",
        order_request={"symbol": "XAUUSD@"},
    )
    with connect(journal.db_path) as con:
        con.execute(
            "UPDATE demo_order_journal SET state='AMBIGUOUS', exit_reason='unknown' "
            "WHERE client_order_id='ambiguous-id'"
        )
        con.commit()

    claimed, reason = _claim(journal, "new-economic-id")
    assert claimed is None
    assert "ambiguous" in reason.lower()
