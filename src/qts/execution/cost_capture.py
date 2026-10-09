"""Capture, preserve and reconcile ACTUAL DEMO execution costs.

Why this module exists
----------------------
A cost model is a hypothesis about what trading costs. A broker statement is
the measurement. Until now QTS had only the hypothesis: every cost number in
the system was modelled, and the phrase "measured costs" referred to costs
measured by a *simulation*, not by a venue.

This module captures what the broker actually reported and reconciles it
against what the model predicted, so the two can be compared instead of
assumed to agree.

Non-negotiable rules
--------------------
1. **UNAVAILABLE is not zero.** A broker field that is missing, `None`,
   non-numeric, NaN or infinite is recorded as ``None`` AND named in
   ``unavailable_fields``. Summing absent charges as 0.00 is the single easiest
   way to manufacture a favourable result, so it is structurally impossible
   here: :func:`cost_total` refuses to total an incomplete record.
2. **The raw broker record is preserved verbatim** in ``raw``. Derived values
   can be recomputed; the original cannot be recovered once dropped.
3. **Append-only and deduplicated.** A reconnect, a replay, or a second call
   after a partial fill must not create a second economic record. Duplicate
   events are counted, not silently dropped and not double-counted.
4. **Tamper-evident.** Each record carries a SHA-256 over its own content and
   the previous record's hash, so a gap or an edit in the file is detectable by
   :meth:`CostEvidenceStore.verify_chain`.
5. **Fail closed.** A broker failure, an unreadable deal, or a missing cost
   field marks the record INCOMPLETE. An incomplete record can never produce a
   favourable reconciliation — it produces no conclusion.

Currency
--------
MT5 reports deal profit, commission, swap and fee in the **account deposit
currency**. That is an assumption about the venue, so it is recorded explicitly
(``account_currency``, ``currency_source``) rather than buried in arithmetic.
No conversion is applied unless a rate is supplied with provenance; an
unconverted non-USD figure is reported as unconverted, never as USD.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCHEMA = "qts.demo_cost_evidence.v1"
RECORD_SCHEMA_DEAL = "qts.demo_cost_evidence.deal.v1"
RECORD_SCHEMA_SUBMIT = "qts.demo_cost_evidence.submit.v1"

ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Field extraction — UNAVAILABLE is not zero
# --------------------------------------------------------------------------- #


def _decimal_field(raw: Any, name: str) -> tuple[Decimal | None, bool]:
    """Read a numeric broker field. Missing/non-finite → ``(None, False)``.

    ``False`` means "the broker did not give us a usable number", which is a
    different fact from "the broker said zero".
    """
    if raw is None:
        return None, False
    try:
        value = Decimal(str(getattr(raw, name) if not isinstance(raw, dict) else raw.get(name)))
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation):
        return None, False
    if not value.is_finite():
        return None, False
    return value, True


def _int_field(raw: Any, name: str) -> tuple[int | None, bool]:
    if raw is None:
        return None, False
    try:
        raw_value = getattr(raw, name) if not isinstance(raw, dict) else raw.get(name)
        if raw_value is None:
            return None, False
        value = int(raw_value)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None, False
    return value, True


def _str_field(raw: Any, name: str) -> str | None:
    if raw is None:
        return None
    try:
        value = getattr(raw, name) if not isinstance(raw, dict) else raw.get(name)
    except (AttributeError, KeyError):
        return None
    if value is None:
        return None
    text = str(value)
    return text or None


def _raw_mapping(raw: Any) -> dict[str, Any]:
    """The untouched broker record, serialisable and complete."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        source: Iterable[tuple[str, Any]] = raw.items()
    elif hasattr(raw, "_asdict"):  # namedtuple (the MT5 API returns these)
        source = raw._asdict().items()
    elif hasattr(raw, "__dict__"):
        source = vars(raw).items()
    else:
        return {"_repr": repr(raw)}
    out: dict[str, Any] = {}
    for key, value in source:
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
        else:
            out[str(key)] = str(value)
    return out


# --------------------------------------------------------------------------- #
# Evidence records
# --------------------------------------------------------------------------- #


@dataclass
class SubmitEvidence:
    """What we asked for, before the venue answered.

    Captured separately from the deal because the comparison "requested versus
    executed" is only possible if the request was recorded before it was sent.
    """

    client_order_id: str
    canonical_symbol: str
    broker_symbol: str | None
    side: str
    requested_volume: Decimal | None
    requested_price: Decimal | None
    order_type: str
    requested_at: str
    #: Broker-reported bid/ask at request time, when the API provided them.
    bid: Decimal | None
    ask: Decimal | None
    #: Broker-reported spread in points at request time.
    spread_points: int | None
    account_currency: str | None
    currency_source: str
    source: str
    raw: dict[str, Any] = field(default_factory=dict)
    unavailable_fields: tuple[str, ...] = ()

    def identity_key(self) -> str:
        return f"submit:{self.client_order_id}"

    def as_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["unavailable_fields"] = list(self.unavailable_fields)
        body["kind"] = "submit"
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in body.items()}


#: Fields whose absence makes a cost record incomplete rather than merely less
#: detailed. Everything else (``entry``, ``time_msc``, ``type``, …) is provenance:
#: recorded when missing, but it does not invalidate a cost measurement.
#:
#: ``profit`` is deliberately NOT here. MQL5 defines DEAL_PROFIT, but the
#: MetaTrader5 Python package's deal record does not reliably expose it, and
#: net P&L is not what this module measures — the charges are. Making an
#: uncertain field blocking would mark every deal from such a terminal as
#: incomplete and silence the one measurement that works.
_REQUIRED_DEAL_FIELDS = ("volume", "price", "commission", "swap", "fee")


@dataclass
class DealEvidence:
    """One broker deal — the venue's own account of one fill.

    ``commission``, ``swap`` and ``fee`` are reported by MT5 in the account
    deposit currency and are NEGATIVE when charged. ``profit`` excludes them;
    net = profit + commission + swap + fee. That convention is the venue's, and
    it is preserved here rather than normalised away.
    """

    deal_ticket: str | None
    order_ticket: str | None
    position_id: str | None
    client_order_id: str | None
    #: Local DEMO journal row this deal belongs to, when known. Provenance:
    #: it ties broker evidence back to the order that produced it.
    journal_id: int | None
    canonical_symbol: str
    broker_symbol: str | None
    side: str | None
    entry_type: int | None  # MT5 DEAL_ENTRY: 0 in, 1 out, 2 inout, 3 out_by
    volume: Decimal | None  # lots
    price: Decimal | None  # executed price
    #: Price we asked for, when the session recorded one. Without it slippage
    #: is unmeasurable -- and NO, that is not the same as zero slippage.
    requested_price: Decimal | None
    profit: Decimal | None
    commission: Decimal | None
    swap: Decimal | None
    fee: Decimal | None
    #: The broker's own stamp, in milliseconds, exactly as reported.
    time_msc: int | None
    #: TRUE UTC, only when the server->UTC offset was supplied. ``None``
    #: otherwise -- never guessed, because MT5 stamps are SERVER-basis and on
    #: a UTC+3 broker an uncorrected stamp reads three hours in the future.
    time_iso: str | None
    #: The same instant rendered on the broker's clock. Always available from
    #: the raw stamp, and always labelled: it is NOT UTC.
    time_iso_broker: str | None
    #: "utc-corrected" or "broker-basis-only". Recorded so a reader can never
    #: mistake a server-basis stamp for a UTC one.
    time_basis: str
    #: Seconds to subtract from a server stamp to get UTC, when known.
    server_utc_offset_s: float | None
    #: Broker-reported spread in points at capture time (from symbol_info).
    spread_points: int | None
    account_currency: str | None
    currency_source: str
    source: str
    captured_at: str
    raw: dict[str, Any] = field(default_factory=dict)
    unavailable_fields: tuple[str, ...] = ()

    # ------------------------------------------------------------------ keys
    def identity_key(self) -> str:
        """Deals are unique per ticket. Without a ticket we cannot dedupe safely,
        so the key stays unique and the record is flagged instead."""
        if self.deal_ticket:
            return f"deal:{self.deal_ticket}"
        return f"deal:unticketed:{self.client_order_id}:{self.time_msc}:{self.volume}"

    @property
    def is_identified(self) -> bool:
        return bool(self.deal_ticket)

    # ------------------------------------------------------------- economics
    @property
    def complete(self) -> bool:
        """Every COST-BEARING field the venue should report is present.

        Deliberately narrower than "no field is missing": a deal that lacks
        ``entry`` or ``time_msc`` still tells us exactly what it cost, and
        refusing to measure it would throw away good economics over
        provenance detail. The missing provenance stays visible in
        ``unavailable_fields`` -- it just does not block the measurement.
        """
        return not (set(self.unavailable_fields) & set(_REQUIRED_DEAL_FIELDS))

    @property
    def reported_charges(self) -> Decimal | None:
        """commission + swap + fee, sign-preserved (negative = charged).

        ``None`` when ANY component is unavailable: a partial total would be a
        smaller number that looks better than the truth.
        """
        if self.commission is None or self.swap is None or self.fee is None:
            return None
        return self.commission + self.swap + self.fee

    @property
    def reported_cost(self) -> Decimal | None:
        """Money actually charged, as a POSITIVE number."""
        charges = self.reported_charges
        return None if charges is None else -charges

    @property
    def net_pnl(self) -> Decimal | None:
        if self.profit is None or self.commission is None or self.swap is None or self.fee is None:
            return None
        return self.profit + self.commission + self.swap + self.fee

    @property
    def is_swap_only(self) -> bool:
        """A financing posting rather than a fill (volume 0)."""
        return self.volume is not None and self.volume == ZERO

    def as_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["unavailable_fields"] = list(self.unavailable_fields)
        body["kind"] = "deal"
        body["complete"] = self.complete
        charges = self.reported_charges
        body["reported_charges"] = None if charges is None else str(charges)
        body["net_pnl"] = None if self.net_pnl is None else str(self.net_pnl)
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in body.items()}




def _coerce_decimal(value: Decimal | str | float | int | None) -> Decimal | None:
    """Best-effort Decimal conversion; None in, None out.

    A value that cannot be parsed is treated as ABSENT rather than as zero,
    for the same reason every other field is.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation, ArithmeticError):
        return None


def deal_evidence_from_broker(
    raw: Any,
    *,
    canonical_symbol: str,
    client_order_id: str | None = None,
    journal_id: int | None = None,
    spread_points: int | None = None,
    requested_price: Decimal | str | float | None = None,
    server_utc_offset_s: float | None = None,
    account_currency: str | None = None,
    currency_source: str = "mt5.account_info.currency",
    source: str = "mt5.history_deals_get",
    captured_at: datetime | None = None,
) -> DealEvidence:
    """Turn one raw MT5 deal row into preserved evidence.

    Every field is read defensively. A field the broker did not provide is
    recorded as ``None`` and named — never defaulted to zero.
    """
    missing: list[str] = []

    def dec(name: str) -> Decimal | None:
        value, ok = _decimal_field(raw, name)
        if not ok:
            missing.append(name)
        return value

    def num(name: str) -> int | None:
        value, ok = _int_field(raw, name)
        if not ok:
            missing.append(name)
        return value

    volume = dec("volume")
    price = dec("price")
    profit = dec("profit")
    commission = dec("commission")
    swap = dec("swap")
    fee = dec("fee")
    time_msc = num("time_msc")
    entry_type = num("entry")

    ticket = num("ticket")
    if ticket is None:
        missing.append("ticket")

    # Timestamps. MT5 reports deal time on the SERVER's clock, not UTC. The
    # broker in this project's own evidence (WMMarkets-Demo) stamps UTC+3, and
    # `tests/test_tick_timestamp_contract.py` exists because treating a
    # server stamp as UTC once made every live tick look three hours old in
    # the future. The same trap applies to deals, so:
    #   * the raw stamp is always preserved verbatim (time_msc);
    #   * the broker-basis rendering is always available and always labelled;
    #   * true UTC is produced ONLY when the measured offset was supplied.
    time_basis = "broker-basis-only"
    time_iso_broker: str | None = None
    time_iso: str | None = None
    if time_msc is not None:
        try:
            time_iso_broker = datetime.fromtimestamp(time_msc / 1000.0, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            missing.append("time_msc_unparseable")
    if time_iso_broker is None:
        raw_time = _str_field(raw, "time")
        if raw_time is not None:
            time_iso_broker = raw_time
        else:
            missing.append("time")
    if time_iso_broker is not None and server_utc_offset_s is not None:
        try:
            corrected = (
                datetime.fromisoformat(time_iso_broker) - timedelta(seconds=float(server_utc_offset_s))
                if "T" in time_iso_broker
                else datetime.fromtimestamp(
                    float(time_msc or 0) / 1000.0 - float(server_utc_offset_s), tz=UTC
                )
            )
            time_iso = corrected.isoformat()
            time_basis = "utc-corrected"
        except (OverflowError, OSError, ValueError, TypeError):
            # A correction that cannot be computed is recorded as such, not
            # silently replaced by the uncorrected stamp.
            missing.append("time_offset_unapplicable")

    # MT5 deal type: 0 BUY, 1 SELL, ... (2-5 are balance/credit operations)
    deal_type = num("type")
    side: str | None = None
    if deal_type is not None:
        side = {0: "BUY", 1: "SELL"}.get(deal_type)
        if side is None:
            # A non-trading deal (balance, credit, …) has no side. That is a
            # fact about the record, not a missing field.
            side = None
    else:
        missing.append("type")

    return DealEvidence(
        deal_ticket=str(ticket) if ticket is not None else None,
        order_ticket=(lambda v: None if v is None else str(v))(num("order")),
        position_id=(lambda v: None if v is None else str(v))(num("position_id")),
        client_order_id=client_order_id or _str_field(raw, "comment"),
        journal_id=journal_id,
        canonical_symbol=canonical_symbol,
        broker_symbol=_str_field(raw, "symbol"),
        side=side,
        entry_type=entry_type,
        volume=volume,
        price=price,
        requested_price=_coerce_decimal(requested_price),
        profit=profit,
        commission=commission,
        swap=swap,
        fee=fee,
        time_msc=time_msc,
        time_iso=time_iso,
        time_iso_broker=time_iso_broker,
        time_basis=time_basis,
        server_utc_offset_s=server_utc_offset_s,
        spread_points=spread_points,
        account_currency=account_currency,
        currency_source=currency_source,
        source=source,
        captured_at=(captured_at or datetime.now(UTC)).isoformat(),
        raw=_raw_mapping(raw),
        unavailable_fields=tuple(sorted(set(missing))),
    )


def submit_evidence_from_request(
    *,
    client_order_id: str,
    canonical_symbol: str,
    broker_symbol: str | None,
    side: str,
    requested_volume: Decimal | None,
    requested_price: Decimal | None,
    order_type: str,
    requested_at: datetime | None = None,
    bid: Decimal | None = None,
    ask: Decimal | None = None,
    spread_points: int | None = None,
    account_currency: str | None = None,
    currency_source: str = "mt5.account_info.currency",
    source: str = "qts.execution.submit",
    raw: dict[str, Any] | None = None,
) -> SubmitEvidence:
    missing: list[str] = []
    if requested_volume is None:
        missing.append("requested_volume")
    if requested_price is None:
        # A market order has no requested PRICE, but it does have a requested
        # SIDE price. Its absence is recorded, not invented.
        missing.append("requested_price")
    return SubmitEvidence(
        client_order_id=client_order_id,
        canonical_symbol=canonical_symbol,
        broker_symbol=broker_symbol,
        side=side,
        requested_volume=requested_volume,
        requested_price=requested_price,
        order_type=order_type,
        requested_at=(requested_at or datetime.now(UTC)).isoformat(),
        bid=bid,
        ask=ask,
        spread_points=spread_points,
        account_currency=account_currency,
        currency_source=currency_source,
        source=source,
        raw=dict(raw or {}),
        unavailable_fields=tuple(sorted(set(missing))),
    )


# --------------------------------------------------------------------------- #
# The store — append-only, deduplicated, hash-chained, restart-safe
# --------------------------------------------------------------------------- #


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _record_fingerprint(body: dict[str, Any], previous_hash: str) -> str:
    return hashlib.sha256((previous_hash + _canonical_json(body)).encode("utf-8")).hexdigest()


GENESIS_HASH = "0" * 64


class CostEvidenceStore:
    """A durable, restart-safe evidence log.

    Restart safety comes from three properties:

    * the file is opened in append mode, so a crash cannot truncate history;
    * every record's identity key is loaded at construction, so a replay after
      a reconnect is recognised as a duplicate rather than recorded twice;
    * the hash chain is verified on load, so a partially written line is
      detected instead of being mistaken for a complete record.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._keys: set[str] = set()
        self._last_hash = GENESIS_HASH
        self.duplicates_skipped = 0
        self.malformed_lines: list[int] = []
        self._truncated = False
        self._load()

    @property
    def head_path(self) -> Path:
        """Sidecar recording how many records the log SHOULD contain.

        A hash chain proves no record was EDITED or reordered; it cannot prove
        none was REMOVED from the end, because the surviving tail still chains
        correctly. This file closes that gap: if the log is shorter than the
        head says, history was truncated and the measurement is not complete.
        """
        return self.path.with_suffix(self.path.suffix + ".head")

    # --------------------------------------------------------------- reading
    def _load(self) -> None:
        if not self.path.exists():
            return
        read = 0
        with self.path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    self.malformed_lines.append(number)
                    continue
                read += 1
                self._last_hash = str(record.get("hash") or GENESIS_HASH)
                key = str(record.get("identity_key") or "")
                if key:
                    self._keys.add(key)
        # Counted by records read, not by distinct keys: two records are never
        # written with the same key, so any shortfall is a missing record.
        self._truncated = read < self._head_count()

    def _head_count(self) -> int:
        """Records the log should contain, per the sidecar. 0 when absent."""
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return 0
        try:
            return int(head.get("count") or 0)
        except (TypeError, ValueError):
            return 0

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
        return out

    def deals(self) -> list[DealEvidence]:
        out: list[DealEvidence] = []
        for record in self.records():
            if record.get("kind") != "deal":
                continue
            out.append(_deal_from_record(record))
        return out

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Recompute every hash. A broken chain means the file was edited.

        A log that was never written is intact, not broken — but it is also
        empty, which the caller must not confuse with "verified evidence".
        """
        problems: list[str] = []
        if not self.path.exists():
            return True, problems
        if self._truncated:
            problems.append(
                f"log holds {len(self._keys)} record(s) but the head records {self._head_count()} "
                "— the tail was truncated; the measurement is incomplete"
            )
        expected_previous = GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    problems.append(f"line {number}: not valid JSON")
                    continue
                body = {k: v for k, v in record.items() if k not in ("hash", "prev_hash")}
                declared_previous = str(record.get("prev_hash") or "")
                if declared_previous != expected_previous:
                    problems.append(f"line {number}: prev_hash does not chain (record removed or reordered)")
                recomputed = _record_fingerprint(body, declared_previous)
                if str(record.get("hash") or "") != recomputed:
                    problems.append(f"line {number}: content hash mismatch (record was edited)")
                expected_previous = str(record.get("hash") or expected_previous)
        return (not problems), problems

    # -------------------------------------------------------------- writing
    def append(self, evidence: DealEvidence | SubmitEvidence) -> tuple[dict[str, Any] | None, str]:
        """Append one record. Returns ``(record, outcome)``.

        ``outcome`` is ``appended``, ``duplicate`` or ``rejected_unidentified``.
        A duplicate is counted and never written twice: a reconnect must not
        turn one fill into two.
        """
        record = evidence.as_dict()
        key = evidence.identity_key()
        record["identity_key"] = key

        if isinstance(evidence, DealEvidence) and not evidence.is_identified:
            # Without a broker ticket we cannot prove two events are the same
            # fill, so we refuse to record economics we cannot deduplicate.
            return None, "rejected_unidentified"

        if key in self._keys:
            self.duplicates_skipped += 1
            return None, "duplicate"

        body = {k: v for k, v in record.items() if k not in ("hash", "prev_hash")}
        record["prev_hash"] = self._last_hash
        record["hash"] = _record_fingerprint(body, self._last_hash)

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
        self._keys.add(key)
        self._last_hash = str(record["hash"])
        self._write_head(len(self._keys))
        return record, "appended"

    def _write_head(self, count: int) -> None:
        """Persist the record count atomically, after the record itself.

        Written AFTER the append deliberately: if the process dies between the
        two, the head under-reports and the log is merely treated as complete
        up to its last record. Writing it first could make a full log look
        truncated and discard good evidence.
        """
        payload = {
            "schema": "qts.cost_evidence_head.v1",
            "count": count,
            "last_hash": self._last_hash,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        tmp = self.head_path.with_suffix(self.head_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self.head_path)
        except OSError:  # pragma: no cover - defensive
            # A missing head weakens truncation detection; it must not lose a
            # record that was already durably appended.
            pass

    # ----------------------------------------------------------- reporting
    def completeness_report(self) -> dict[str, Any]:
        deals = self.deals()
        incomplete = [d for d in deals if not d.complete]
        fields: dict[str, int] = {}
        for deal in deals:
            for name in deal.unavailable_fields:
                fields[name] = fields.get(name, 0) + 1
        return {
            "schema": SCHEMA,
            "path": str(self.path),
            "records": len(self.records()),
            "deals": len(deals),
            "complete_deals": len(deals) - len(incomplete),
            "incomplete_deals": len(incomplete),
            "unticketed_deals": sum(1 for d in deals if not d.is_identified),
            "swap_only_deals": sum(1 for d in deals if d.is_swap_only),
            "duplicates_skipped": self.duplicates_skipped,
            "truncated": self._truncated,
            "expected_records": self._head_count(),
            "malformed_lines": list(self.malformed_lines),
            "unavailable_field_counts": fields,
            "chain_ok": self.verify_chain()[0],
            "chain_problems": self.verify_chain()[1],
        }


def _deal_from_record(record: dict[str, Any]) -> DealEvidence:
    def dec(name: str) -> Decimal | None:
        raw = record.get(name)
        if raw is None:
            return None
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None

    def num(name: str) -> int | None:
        raw = record.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return DealEvidence(
        deal_ticket=record.get("deal_ticket"),
        order_ticket=record.get("order_ticket"),
        position_id=record.get("position_id"),
        client_order_id=record.get("client_order_id"),
        journal_id=num("journal_id"),
        canonical_symbol=str(record.get("canonical_symbol") or "UNKNOWN"),
        broker_symbol=record.get("broker_symbol"),
        side=record.get("side"),
        entry_type=num("entry_type"),
        volume=dec("volume"),
        price=dec("price"),
        requested_price=dec("requested_price"),
        profit=dec("profit"),
        commission=dec("commission"),
        swap=dec("swap"),
        fee=dec("fee"),
        time_msc=num("time_msc"),
        time_iso=record.get("time_iso"),
        time_iso_broker=record.get("time_iso_broker"),
        time_basis=str(record.get("time_basis") or "broker-basis-only"),
        server_utc_offset_s=(
            float(record["server_utc_offset_s"])
            if record.get("server_utc_offset_s") is not None
            else None
        ),
        spread_points=num("spread_points"),
        account_currency=record.get("account_currency"),
        currency_source=str(record.get("currency_source") or "unknown"),
        source=str(record.get("source") or "unknown"),
        captured_at=str(record.get("captured_at") or ""),
        raw=dict(record.get("raw") or {}),
        unavailable_fields=tuple(record.get("unavailable_fields") or ()),
    )


# --------------------------------------------------------------------------- #
# Reconciliation — actual versus modelled
# --------------------------------------------------------------------------- #


@dataclass
class FillReconciliation:
    """One fill: what the model predicted against what the broker reported.

    A positive ``delta_usd`` means the model UNDER-charged (reality was more
    expensive). That is the direction that hurts, so it is the direction the
    report leads with.
    """

    deal_ticket: str | None
    position_id: str | None
    side: str | None
    volume: Decimal | None

    modelled_cost: Decimal | None
    #: commission + swap + fee charged, as a positive number.
    reported_cost: Decimal | None
    #: Adverse distance between the requested and the executed price.
    slippage_price: Decimal | None
    #: Slippage converted to money with the instrument's contract size.
    slippage_cost: Decimal | None
    #: reported_cost + slippage_cost — everything we can see.
    observed_cost: Decimal | None
    #: observed_cost - modelled_cost. Positive = reality was worse.
    delta: Decimal | None

    complete: bool
    #: Broker fields the broker simply did not report.
    missing_fields: tuple[str, ...]
    #: Components that exist but could not be computed (e.g. slippage with no
    #: requested price). Reported separately from ``missing_fields`` because the
    #: remedy is different: record the request, do not ask the broker again.
    unmeasurable_components: tuple[str, ...]
    currency: str | None
    converted: bool
    notes: list[str] = field(default_factory=list)

    @property
    def incomplete_reasons(self) -> tuple[str, ...]:
        """Every reason this fill's total is not trustworthy as a comparison."""
        return tuple(self.missing_fields) + tuple(self.unmeasurable_components)

    def as_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["missing_fields"] = list(self.missing_fields)
        body["unmeasurable_components"] = list(self.unmeasurable_components)
        body["incomplete_reasons"] = list(self.incomplete_reasons)
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in body.items()}


@dataclass
class RoundTripReconciliation:
    """One position: every fill reconciled, plus the totals that matter."""

    position_id: str
    fills: list[FillReconciliation]
    deal_count: int
    modelled_total: Decimal | None
    observed_total: Decimal | None
    delta_total: Decimal | None
    #: True when a deal arrived for a position already reconciled (a delayed
    #: swap posting after the close was captured, for example).
    revised: bool
    last_deal_time: str | None
    complete: bool
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "deal_count": self.deal_count,
            "modelled_total": None if self.modelled_total is None else str(self.modelled_total),
            "observed_total": None if self.observed_total is None else str(self.observed_total),
            "delta_total": None if self.delta_total is None else str(self.delta_total),
            "revised": self.revised,
            "last_deal_time": self.last_deal_time,
            "complete": self.complete,
            "notes": list(self.notes),
            "fills": [f.as_dict() for f in self.fills],
        }


def _sum_or_none(values: Sequence[Decimal | None]) -> Decimal | None:
    """Total a list, or return None if ANY value is unavailable.

    This is the whole point of the module: an incomplete sum is not a smaller
    sum, it is no answer at all.
    """
    # An EMPTY list is also unavailable. Summing nothing to zero would let
    # "we measured no fills at all" be reported as "we measured zero cost".
    if not values or any(v is None for v in values):
        return None
    total = ZERO
    for value in values:
        if value is None:  # pragma: no cover - guarded by the check above
            return None
        total += value
    return total


#: A round turn is two fills. A component's ``cost_usd`` returns its round-turn
#: amount, so one fill carries half of it regardless of how many times the
#: component is charged per round turn.
_FILLS_PER_ROUND_TURN = 2


def per_fill_modelled_cost(model: Any, lots: Decimal | None, contract_size: float) -> Decimal | None:
    """The model's cost attributable to ONE fill.

    Financing is a round-turn charge and is excluded here — it belongs to the
    round-trip total, not to a single fill.

    Raises ``ValueError`` when the model cannot be evaluated. Returning ``None``
    instead would make a broken model indistinguishable from "no model", and a
    silently-zero modelled cost is the single most dangerous outcome in this
    module: it makes reality look expensive, or a bad fill look fine.
    """
    if lots is None:
        return None
    total = ZERO
    for component in getattr(model, "components", ()) or ():
        try:
            amount = component.cost_usd(float(lots), float(contract_size), 0.0)
        except Exception as exc:
            raise ValueError(
                f"cost model component {getattr(component, 'name', '?')!r} could not be "
                f"evaluated for {lots} lots: {type(exc).__name__}: {exc}"
            ) from exc
        name = str(getattr(component, "name", ""))
        if name == "financing":
            continue
        total += Decimal(str(amount)) / Decimal(_FILLS_PER_ROUND_TURN)
    return total


def reconcile_fill(
    deal: DealEvidence,
    *,
    model: Any | None = None,
    contract_size: float = 100.0,
    requested_price: Decimal | None = None,
    fx_rate: Decimal | None = None,
    fx_source: str | None = None,
) -> FillReconciliation:
    """Compare one broker deal against the modelled cost of one fill."""
    notes: list[str] = []

    reported = deal.reported_cost
    if reported is None:
        notes.append(
            "broker did not report every charge ("
            + ", ".join(f for f in deal.unavailable_fields if f in _REQUIRED_DEAL_FIELDS)
            + ") — the actual cost is UNAVAILABLE, not zero"
        )

    # Slippage: adverse distance between what we asked for and what we got.
    # The requested price attached to the deal at capture time is used when the
    # caller does not supply one -- capture is when it is known for certain.
    reference_price = requested_price if requested_price is not None else deal.requested_price
    if requested_price is None and deal.requested_price is not None:
        notes.append("requested price taken from the capture-time record")
    slippage_price: Decimal | None = None
    slippage_cost: Decimal | None = None
    if reference_price is not None and deal.price is not None:
        side = (deal.side or "").upper()
        if side == "BUY":
            slippage_price = deal.price - reference_price  # paying more is adverse
        elif side == "SELL":
            slippage_price = reference_price - deal.price  # taking less is adverse
        else:
            notes.append("deal has no BUY/SELL side — slippage cannot be signed")

        if slippage_price is not None:
            slippage_cost = slippage_price * Decimal(str(contract_size)) * (deal.volume or ZERO)
    elif requested_price is None:
        notes.append("no requested price was recorded for this fill — slippage cannot be measured")

    if deal.volume is None:
        notes.append("broker did not report the filled volume — costs cannot be scaled")

    # Observed cost totals everything we can actually SEE and names what is
    # excluded. Without this, a fill whose slippage could not be measured would
    # report no total at all — which reads the same as "the broker told us
    # nothing" and is not the same fact.
    parts: list[tuple[str, Decimal | None]] = [("reported_charges", reported), ("slippage", slippage_cost)]
    observed = _sum_or_none([value for _name, value in parts if value is not None])
    excluded_from_total = [name for name, value in parts if value is None]
    if excluded_from_total:
        notes.append(
            "not included in the observed total: " + ", ".join(excluded_from_total) + " (unavailable)"
        )
    modelled: Decimal | None = None
    if model is not None:
        try:
            modelled = per_fill_modelled_cost(model, deal.volume, contract_size)
        except ValueError as exc:
            # A model we cannot evaluate is a fact about the measurement, not a
            # zero. Named here so the report can never show it as a clean 0.
            modelled = None
            notes.append(f"modelled cost could not be evaluated — {exc}")
    else:
        notes.append("no cost model supplied — modelled cost was not computed")

    # The delta is the number an operator would act on, so it is computed ONLY
    # from a total that includes every component. Comparing a partial observed
    # total against a full modelled one produces a confident-looking number
    # that is simply wrong in the direction of "cheaper than we modelled" --
    # and the direction that hurts is the one that must never be suppressed.
    delta: Decimal | None = None
    if observed is not None and modelled is not None and not excluded_from_total:
        delta = observed - modelled
        if delta > ZERO:
            notes.append(f"reality was {delta} worse than the model predicted")
    elif observed is not None and modelled is not None and excluded_from_total:
        notes.append(
            "no delta computed: the observed total is partial, so any comparison "
            "would understate the real cost"
        )

    converted = False
    currency = deal.account_currency
    if fx_rate is not None and currency and currency.upper() != "USD":
        # An explicit rate with provenance is the only thing that may convert.
        observed = None if observed is None else observed * fx_rate
        reported = None if reported is None else reported * fx_rate
        slippage_cost = None if slippage_cost is None else slippage_cost * fx_rate
        delta = None if (observed is None or modelled is None) else observed - modelled
        converted = True
        notes.append(f"converted from {currency} at {fx_rate} (source: {fx_source or 'UNSTATED'})")
        currency = "USD"
    elif currency and currency.upper() != "USD":
        notes.append(
            f"amounts are in {currency} and were NOT converted to USD — no rate with provenance was supplied"
        )

    return FillReconciliation(
        deal_ticket=deal.deal_ticket,
        position_id=deal.position_id,
        side=deal.side,
        volume=deal.volume,
        modelled_cost=modelled,
        reported_cost=reported,
        slippage_price=slippage_price,
        slippage_cost=slippage_cost,
        observed_cost=observed,
        delta=delta,
        # Complete only when every component is present: a comparison built on
        # a partial total would be biased towards looking cheap.
        complete=deal.complete and not excluded_from_total and observed is not None and modelled is not None,
        missing_fields=deal.unavailable_fields,
        unmeasurable_components=tuple(excluded_from_total),
        currency=currency,
        converted=converted,
        notes=notes,
    )


def reconcile_round_trip(
    deals: list[DealEvidence],
    *,
    position_id: str,
    model: Any | None = None,
    contract_size: float = 100.0,
    requested_prices: dict[str, Decimal] | None = None,
    fx_rate: Decimal | None = None,
    fx_source: str | None = None,
    previously_reconciled_deal_count: int = 0,
) -> RoundTripReconciliation:
    """Reconcile every deal belonging to one position.

    ``previously_reconciled_deal_count`` supports the delayed-charge case: a
    swap posting that arrives after the close was already reconciled makes this
    round trip ``revised``, so a stale "reconciled, agrees with model" result
    cannot survive a later, more expensive deal.
    """
    prices = requested_prices or {}
    fills = [
        reconcile_fill(
            deal,
            model=model,
            contract_size=contract_size,
            requested_price=prices.get(str(deal.deal_ticket or "")),
            fx_rate=fx_rate,
            fx_source=fx_source,
        )
        for deal in deals
    ]

    modelled_total = _sum_or_none([f.modelled_cost for f in fills]) if model is not None else None
    observed_total = _sum_or_none([f.observed_cost for f in fills])
    delta_total = None
    if modelled_total is not None and observed_total is not None:
        delta_total = observed_total - modelled_total

    # Either basis orders identically (both are monotonic in the same instant),
    # so the broker rendering is a valid fallback when UTC is unavailable.
    times: list[str] = [
        stamp for stamp in (d.time_iso or d.time_iso_broker for d in deals) if stamp
    ]
    last_time = max(times) if times else None
    # "Revised" means a deal arrived for a position whose round trip had
    # ALREADY been reconciled. On a first reconciliation there is nothing to
    # revise, so a prior count of 0 must not mark every trip as revised.
    revised = previously_reconciled_deal_count > 0 and len(deals) > previously_reconciled_deal_count

    notes: list[str] = []
    if not deals:
        notes.append("no deals for this position — nothing was measured")
    if any(d.time_iso is None and d.time_iso_broker for d in deals):
        notes.append(
            "deal times are broker-basis (no server offset was supplied at capture) — "
            "they are NOT UTC and must not be compared against UTC timestamps"
        )
    if not position_id:
        notes.append(
            "these deals carry no position identifier — they cannot be attributed to a round trip"
        )
    if revised:
        notes.append(
            f"{len(deals) - previously_reconciled_deal_count} deal(s) arrived after this round trip was "
            "first reconciled (a delayed charge such as an overnight swap) — the earlier total was incomplete"
        )
    if any(d.is_swap_only for d in deals):
        notes.append("includes a financing-only posting (volume 0)")
    incomplete = [f for f in fills if not f.complete]
    if incomplete:
        notes.append(f"{len(incomplete)} of {len(fills)} fill(s) are incomplete — totals are UNAVAILABLE, not small")

    return RoundTripReconciliation(
        position_id=position_id,
        fills=fills,
        deal_count=len(deals),
        modelled_total=modelled_total,
        observed_total=observed_total,
        delta_total=delta_total,
        revised=revised,
        last_deal_time=last_time,
        complete=bool(deals) and not incomplete,
        notes=notes,
    )


def reconcile_store(
    store: CostEvidenceStore,
    *,
    model: Any | None = None,
    contract_size: float = 100.0,
    requested_prices: dict[str, Decimal] | None = None,
    fx_rate: Decimal | None = None,
    fx_source: str | None = None,
    prior_deal_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Reconcile every position in the store and report completeness.

    The report leads with what is MISSING, because a favourable-looking
    comparison built on incomplete data is the failure mode this whole module
    exists to prevent.
    """
    prior = prior_deal_counts or {}
    by_position: dict[str, list[DealEvidence]] = {}
    orphan: list[DealEvidence] = []
    for deal in store.deals():
        if deal.position_id:
            by_position.setdefault(deal.position_id, []).append(deal)
        else:
            orphan.append(deal)

    trips = [
        reconcile_round_trip(
            deals,
            position_id=position_id,
            model=model,
            contract_size=contract_size,
            requested_prices=requested_prices,
            fx_rate=fx_rate,
            fx_source=fx_source,
            previously_reconciled_deal_count=prior.get(position_id, 0),
        )
        for position_id, deals in sorted(by_position.items())
    ]

    complete_trips = [t for t in trips if t.complete]
    deltas = [t.delta_total for t in complete_trips if t.delta_total is not None]
    total_delta = _sum_or_none(deltas)
    undercharged = [t for t in complete_trips if t.delta_total is not None and t.delta_total > ZERO]

    return {
        "schema": "qts.cost_reconciliation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "store_completeness": store.completeness_report(),
        "positions": len(by_position),
        "round_trips": [t.as_dict() for t in trips],
        "orphan_deals": [
            {"deal_ticket": d.deal_ticket, "reason": "no position identifier — cannot be attributed"}
            for d in orphan
        ],
        "complete_round_trips": len(complete_trips),
        "incomplete_round_trips": len(trips) - len(complete_trips),
        "round_trips_where_reality_was_worse": len(undercharged),
        "total_delta_usd": None if total_delta is None else str(total_delta),
        "revised_round_trips": [t.position_id for t in trips if t.revised],
        "conclusion": _reconciliation_conclusion(trips, complete_trips, store),
    }


def _reconciliation_conclusion(
    trips: list[RoundTripReconciliation],
    complete_trips: list[RoundTripReconciliation],
    store: CostEvidenceStore,
) -> str:
    if not trips:
        return "NO_EVIDENCE — no broker deals have been captured; nothing was measured"
    report = store.completeness_report()
    if report["malformed_lines"] or not report["chain_ok"]:
        return "EVIDENCE_UNRELIABLE — the evidence log failed integrity verification"
    if not complete_trips:
        missing: set[str] = set()
        for trip in trips:
            for fill in trip.fills:
                missing.update(fill.incomplete_reasons)
        return (
            "INCOMPLETE — every round trip has unavailable cost components "
            f"({', '.join(sorted(missing)) or 'unknown'}); no conclusion may be drawn, and none is drawn"
        )
    return (
        f"MEASURED on {len(complete_trips)} complete round trip(s) — this compares "
        "modelled against reported costs; it is not evidence of a trading edge"
    )
