from pathlib import Path

from qts.execution.idempotency import IdempotencyStore


def test_claim_is_atomic_for_the_same_client_order_id(tmp_path: Path):
    store_a = IdempotencyStore(tmp_path / "idempotency.db")
    store_b = IdempotencyStore(tmp_path / "idempotency.db")

    assert store_a.claim("same-order") is True
    assert store_b.claim("same-order") is False
    assert store_b.get_status("same-order") == "PENDING"

    store_a.close()
    store_b.close()
