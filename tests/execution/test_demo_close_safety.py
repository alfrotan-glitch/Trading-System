"""Close-lifecycle safety tests: broker truth and local journal uncertainty fail closed."""

from __future__ import annotations

from types import SimpleNamespace

from qts.domain.modes import ExecutionMode
from qts.execution.demo_session import DemoSession


class _Harness(DemoSession):
    @property
    def mode(self):
        return ExecutionMode.DEMO_EXECUTION


class _Stage:
    def __init__(self) -> None:
        self.halts: list[str] = []

    def halt(self, *, reason: str, actor: str) -> None:
        self.halts.append(reason)


class _Authority:
    def is_execution_permitted(self):
        return True, []


class _Adapter:
    RETCODE_DONE = 10009
    RETCODE_DONE_PARTIAL = 10010
    RETCODE_PLACED = 10008

    def __init__(self, *, close_result=None, close_exc=None, post_close=None) -> None:
        self._close_result = close_result or {"retcode": self.RETCODE_DONE, "deal": "deal-1"}
        self._close_exc = close_exc
        self._positions = [
            {
                "ticket": 123,
                "volume": "0.01",
                "profit": "1.25",
                "price_current": "2001.00",
            }
        ]
        self._post_close = post_close
        self.close_calls = 0

    def position_details(self):
        if self._post_close is not None and self.close_calls:
            if isinstance(self._post_close, Exception):
                raise self._post_close
            return self._post_close
        return list(self._positions)

    def close_position(self, ticket, *, volume, comment):
        self.close_calls += 1
        if self._close_exc is not None:
            raise self._close_exc
        if self._post_close == []:
            self._positions = []
        return dict(self._close_result)


def _session(adapter: _Adapter, *, journal=None):
    obj = object.__new__(_Harness)
    object.__setattr__(obj, "_authority", _Authority())
    object.__setattr__(obj, "_authority_mode", ExecutionMode.DEMO_EXECUTION)
    object.__setattr__(obj, "_adapter", adapter)
    object.__setattr__(obj, "stage", _Stage())
    object.__setattr__(obj, "config", SimpleNamespace(actor="close-test", mode="DEMO_EXECUTION", symbol="XAUUSD", symbol_map={}))
    obj.journal = journal or SimpleNamespace(open_orders=lambda: [])
    obj.sync_fills = lambda: 0
    obj.reconcile = lambda: {"requires_suspend": False, "drift": "OK", "details": ""}
    return obj


def test_unknown_close_retcode_is_ambiguous_and_halts():
    adapter = _Adapter(close_result={"retcode": 99999})
    session = _session(adapter)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert result["success"] is False
    assert "99999" in result["error"]
    assert session.stage.halts
    assert adapter.close_calls == 1


def test_post_close_venue_read_failure_is_ambiguous_and_halts():
    adapter = _Adapter(post_close=ConnectionError("venue read failed"))
    session = _session(adapter)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert "post-close venue verification failed" in result["error"]
    assert session.stage.halts


def test_close_transport_exception_is_ambiguous_and_halts():
    adapter = _Adapter(close_exc=TimeoutError("close timeout"))
    session = _session(adapter)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert "timeout" in result["error"].lower()
    assert session.stage.halts


def test_venue_closed_without_matching_journal_row_is_ambiguous():
    adapter = _Adapter(post_close=[])
    session = _session(adapter)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert "local journal lifecycle could not be matched" in result["error"]
    assert session.stage.halts


def test_local_close_journal_failure_is_ambiguous_and_halts():
    adapter = _Adapter(post_close=[])
    journal = SimpleNamespace(
        open_orders=lambda: [{"journal_id": 7, "broker_position_id": "123"}],
        mark_outcome=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")),
    )
    session = _session(adapter, journal=journal)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert "journal persistence failed" in result["error"]
    assert session.stage.halts
