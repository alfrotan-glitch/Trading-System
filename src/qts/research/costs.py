"""Canonical, provenance-carrying transaction-cost model.

Why this module exists
----------------------
An edge is a NET-of-cost claim. Gold spot at a retail MT5 venue is not free to
trade: you cross a spread on every fill, you pay commission, you slip, and you
pay financing for every night a position is held. A backtest that reports gross
P&L as "expectancy" is not evidence of an edge — it is evidence of arithmetic.

Before this module the system could only answer "is there a gross/net cost
decomposition?" with ``NOT_IMPLEMENTED``, which meant the economic-edge gate
could never pass and — worse — the expectancy gate silently ran with
``costs_per_trade=0.0``, so *net* expectancy was gross expectancy wearing a
costume.

Design rules
------------
1. **Every cost component declares its provenance.** ``MEASURED`` means it came
   from an observation (a quote, a broker statement, a journal). ``ASSUMED``
   means somebody chose a number. ``UNKNOWN`` means it is not known — and an
   UNKNOWN component makes the decomposition NOT claim-eligible.
2. **Costs are per round turn**, because a trade is a round turn. Entry and
   exit each cost money.
3. **Nothing is inferred from the equity curve.** This module takes trades and
   a cost model and returns money. It never "estimates" a cost from a P&L
   series — that would fit the cost to the result it is supposed to test.
4. **The break-even cost multiple is the headline number.** It answers the only
   question that matters for robustness: *how much worse would execution have
   to get before this stops working?*
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


class CostBasis(StrEnum):
    """Where a cost number came from."""

    #: Observed: a broker quote, a filled order, a broker statement.
    MEASURED = "MEASURED"
    #: Chosen by a human/protocol, not observed. Legal, but never claim-grade.
    ASSUMED = "ASSUMED"
    #: Not known. Blocks claim eligibility — we do not invent a number.
    UNKNOWN = "UNKNOWN"


#: The ONLY basis an edge claim may rest on.
#:
#: An ASSUMED cost still produces a perfectly good decomposition — it is the
#: right way to run a sensitivity sweep ("even at 3x the spread I modelled,
#: this survives"). It is NOT the right basis for "this strategy makes money":
#: gross P&L minus a number somebody chose is arithmetic about the number
#: somebody chose. Go and measure the spread, the commission and the swap, or
#: do not claim an economic edge.
CLAIM_ELIGIBLE_BASES = frozenset({CostBasis.MEASURED})


# --------------------------------------------------------------------------- #
# One cost component
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CostComponent:
    """A single, named cost of doing one round turn.

    A component is expressed in whichever unit is natural for it and converted
    to USD at evaluation time:

    * ``price_units_per_lot`` — a price distance (spread, slippage). Multiplied
      by ``lots * contract_size``.
    * ``usd_per_lot`` — a flat charge (commission). Multiplied by ``lots``.
    * ``usd_per_lot_per_night`` — financing (swap). Multiplied by
      ``lots * nights_held``.

    ``fills`` is how many times the component is charged per round turn: the
    spread is crossed once per round turn (half on entry, half on exit, and a
    quoted spread is the full round-turn width), while slippage and commission
    are charged on each of the two fills.
    """

    name: str
    basis: CostBasis = CostBasis.ASSUMED
    source: str = ""
    price_units_per_lot: float = 0.0
    usd_per_lot: float = 0.0
    usd_per_lot_per_night: float = 0.0
    fills: int = 1
    note: str = ""
    #: Set when a zero magnitude is a fact (a commission-free account, a
    #: strategy that never holds overnight) rather than an unfilled field.
    zero_is_known: bool = False

    def __post_init__(self) -> None:
        if self.fills < 0:
            raise ValueError(f"cost component {self.name!r}: fills must be >= 0")
        if not self.name:
            raise ValueError("cost component requires a name")
        # A component with no magnitude is either a mistake or a placeholder.
        # Placeholders are legal (basis=UNKNOWN) but must say so.
        magnitude = (self.price_units_per_lot, self.usd_per_lot, self.usd_per_lot_per_night)
        if all(v == 0 for v in magnitude) and self.basis is not CostBasis.UNKNOWN and not self.zero_is_known:
            raise ValueError(
                f"cost component {self.name!r} has zero magnitude but basis {self.basis.value} — "
                "a zeroed cost must be declared UNKNOWN, not silently free"
            )

    def cost_usd(self, lots: float, contract_size: float, nights_held: float = 0.0) -> float:
        """USD cost of this component for one round turn."""
        lots = float(lots)
        per_fill = (self.price_units_per_lot * contract_size) + self.usd_per_lot
        return (per_fill * self.fills * lots) + (self.usd_per_lot_per_night * lots * max(0.0, nights_held))

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "basis": self.basis.value,
            "source": self.source,
            "price_units_per_lot": self.price_units_per_lot,
            "usd_per_lot": self.usd_per_lot,
            "usd_per_lot_per_night": self.usd_per_lot_per_night,
            "fills": self.fills,
            "note": self.note,
            "zero_is_known": self.zero_is_known,
        }


# --------------------------------------------------------------------------- #
# A round-turn trade
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TradeRecord:
    """One completed round turn, in the units a cost model needs.

    ``gross_pnl_usd`` is the P&L BEFORE any cost — i.e. the raw
    ``(exit - entry) * direction * lots * contract_size`` figure a cost-free
    backtest would report. Providing it explicitly (rather than recomputing it
    here) keeps this module a cost model and not a second P&L implementation
    that could disagree with the engine that produced the trade.
    """

    lots: float
    gross_pnl_usd: float
    nights_held: float = 0.0
    entry_price: float | None = None
    exit_price: float | None = None
    side: str = ""
    opened_at: str | None = None
    closed_at: str | None = None

    def __post_init__(self) -> None:
        if self.lots < 0:
            raise ValueError(f"TradeRecord lots must be >= 0 (got {self.lots})")
        for name in ("gross_pnl_usd", "nights_held"):
            value = getattr(self, name)
            if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
                raise ValueError(f"TradeRecord.{name} must be finite (got {value})")


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CostModel:
    """An explicit cost model for one instrument.

    Nothing here is inferred from results. Build it from broker facts
    (contract size, quoted spread, commission schedule, swap table) and mark
    each number with where it came from.
    """

    instrument: str = "XAUUSD"
    contract_size: float = 100.0  # troy oz per standard lot
    components: tuple[CostComponent, ...] = ()
    #: Human-readable description of what this model represents.
    description: str = ""

    def __post_init__(self) -> None:
        if self.contract_size <= 0:
            raise ValueError("contract_size must be > 0")
        seen: set[str] = set()
        for c in self.components:
            if c.name in seen:
                raise ValueError(f"duplicate cost component {c.name!r}")
            seen.add(c.name)

    # ------------------------------------------------------------------ build

    @classmethod
    def xauusd_default(
        cls,
        *,
        spread_price_units: float = 0.30,
        commission_per_lot_usd: float = 0.0,
        slippage_price_units: float = 0.10,
        #: ``None`` means "not supplied" → the financing component is UNKNOWN
        #: (not claim-eligible). Pass ``0.0`` to state "no financing cost".
        swap_per_night_per_lot_usd: float | None = None,
        contract_size: float = 100.0,
        basis: CostBasis = CostBasis.ASSUMED,
        source: str = "qts.research.costs.xauusd_default (assumed retail MT5 gold conditions)",
    ) -> CostModel:
        """A conservative, explicitly-ASSUMED retail XAUUSD cost model.

        Defaults are deliberately middle-of-the-road for a retail gold CFD and
        are marked ``ASSUMED``: they are a starting point for a sensitivity
        sweep, not a measurement of your broker. Replace them with measured
        values before any claim rests on them.

        The spread is charged once per round turn (a quoted spread is already
        the round-turn width between bid and ask). Slippage and commission are
        charged on each of the two fills.
        """
        return cls(
            instrument="XAUUSD",
            contract_size=contract_size,
            description="Retail MT5 XAUUSD round-turn cost model (spread + commission + slippage + financing)",
            components=(
                CostComponent(
                    name="spread",
                    basis=basis,
                    source=source,
                    price_units_per_lot=spread_price_units,
                    fills=1,
                    zero_is_known=True,
                    note="quoted bid/ask width — crossed once per round turn",
                ),
                CostComponent(
                    name="commission",
                    basis=basis,
                    source=source,
                    usd_per_lot=commission_per_lot_usd,
                    fills=2,
                    zero_is_known=True,
                    note="commission charged per fill (entry and exit) — 0 is a real spread-only account",
                ),
                CostComponent(
                    name="slippage",
                    basis=basis,
                    source=source,
                    price_units_per_lot=slippage_price_units,
                    fills=2,
                    zero_is_known=True,
                    note="realized-vs-expected fill distance, charged per fill",
                ),
                CostComponent(
                    name="financing",
                    basis=basis if swap_per_night_per_lot_usd is not None else CostBasis.UNKNOWN,
                    source=source,
                    usd_per_lot_per_night=float(swap_per_night_per_lot_usd or 0.0),
                    zero_is_known=True,
                    note=(
                        "overnight swap/financing per lot per night"
                        if swap_per_night_per_lot_usd is not None
                        else "overnight swap/financing NOT SUPPLIED — UNKNOWN, not claim-eligible"
                    ),
                ),
            ),
        )

    # --------------------------------------------------------------- evaluate

    def round_turn_cost(self, trade: TradeRecord) -> dict[str, float]:
        """Per-component USD cost for one round turn (plus a ``total`` key)."""
        out: dict[str, float] = {}
        for c in self.components:
            out[c.name] = c.cost_usd(trade.lots, self.contract_size, trade.nights_held)
        out["total"] = float(sum(v for k, v in out.items()))
        return out

    def basis_summary(self) -> dict[str, str]:
        return {c.name: c.basis.value for c in self.components}

    def claim_eligible(self) -> bool:
        """A cost model is claim-grade only if every component was MEASURED."""
        return bool(self.components) and all(c.basis in CLAIM_ELIGIBLE_BASES for c in self.components)

    def measured_components(self) -> list[str]:
        return [c.name for c in self.components if c.basis is CostBasis.MEASURED]

    def assumed_components(self) -> list[str]:
        """Components that are known but not measured — sensitivity only."""
        return [c.name for c in self.components if c.basis is CostBasis.ASSUMED]

    def as_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "contract_size": self.contract_size,
            "description": self.description,
            "claim_eligible": self.claim_eligible(),
            "components": [c.as_dict() for c in self.components],
        }


# --------------------------------------------------------------------------- #
# Decomposition
# --------------------------------------------------------------------------- #


@dataclass
class CostDecomposition:
    """Gross -> cost -> net, with everything needed to judge the claim."""

    gross_pnl_usd: float
    cost_usd: float
    net_pnl_usd: float
    trades: int
    gross_expectancy_per_trade: float
    net_expectancy_per_trade: float
    cost_per_trade: float
    #: Fraction of gross P&L consumed by costs. >1.0 means costs ate it all.
    cost_drag: float
    #: How many times costs could rise before net P&L reaches zero.
    break_even_cost_multiple: float
    per_component_usd: dict[str, float] = field(default_factory=dict)
    #: Gross and net equity curves (starting at 0, cumulative per trade).
    equity_gross: list[float] = field(default_factory=list)
    equity_net: list[float] = field(default_factory=list)
    claim_eligible: bool = False
    basis_summary: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "gross_pnl_usd": self.gross_pnl_usd,
            "cost_usd": self.cost_usd,
            "net_pnl_usd": self.net_pnl_usd,
            "trades": self.trades,
            "gross_expectancy_per_trade": self.gross_expectancy_per_trade,
            "net_expectancy_per_trade": self.net_expectancy_per_trade,
            "cost_per_trade": self.cost_per_trade,
            "cost_drag": self.cost_drag,
            "break_even_cost_multiple": self.break_even_cost_multiple,
            "per_component_usd": dict(self.per_component_usd),
            "claim_eligible": self.claim_eligible,
            "basis_summary": dict(self.basis_summary),
            "reasons": list(self.reasons),
        }


def decompose_costs(trades: list[TradeRecord], model: CostModel) -> CostDecomposition:
    """Turn gross trades into a gross/cost/net decomposition.

    Refuses to guess: an empty trade list or a model with UNKNOWN components
    still returns numbers (they are arithmetic) but is marked not
    claim-eligible with a legible reason.
    """
    reasons: list[str] = []
    equity_gross: list[float] = []
    equity_net: list[float] = []
    per_component: dict[str, float] = {c.name: 0.0 for c in model.components}

    gross_total = 0.0
    cost_total = 0.0
    for trade in trades:
        breakdown = model.round_turn_cost(trade)
        cost = breakdown["total"]
        gross_total += float(trade.gross_pnl_usd)
        cost_total += cost
        for name, amount in breakdown.items():
            if name != "total":
                per_component[name] = per_component.get(name, 0.0) + amount
        equity_gross.append(gross_total)
        equity_net.append(gross_total - cost_total)

    n = len(trades)
    net_total = gross_total - cost_total
    gross_exp = gross_total / n if n else 0.0
    net_exp = net_total / n if n else 0.0
    cost_per = cost_total / n if n else 0.0

    # Cost drag: share of GROSS consumed by costs. When gross <= 0 there is no
    # positive gross to be dragged, so it is reported as uninformative (inf is
    # not a number an operator should read).
    cost_drag = (cost_total / gross_total) if gross_total > 0 else float("nan")

    # Break-even cost multiple: gross / cost. 2.0 means costs could double
    # before the strategy stops making money. <= 1.0 means it never did.
    break_even = gross_total / cost_total if cost_total > 0 else (float("inf") if gross_total > 0 else 0.0)

    # Claim eligibility is decided component by component, and only over the
    # components that COULD have altered these numbers. Financing that was never
    # incurred (no overnight hold) is a known zero for this trade set, not an
    # unpriced risk — so it neither blocks nor weakens the claim.
    nights_total = float(sum(max(0.0, t.nights_held) for t in trades))
    never_incurred: set[str] = set()
    incurred_unknown: list[str] = []
    for c in model.components:
        if c.basis is not CostBasis.UNKNOWN:
            continue
        only_financing = c.usd_per_lot_per_night != 0 or (c.price_units_per_lot == 0 and c.usd_per_lot == 0)
        if only_financing and nights_total <= 0:
            never_incurred.add(c.name)
            reasons.append(f"cost component {c.name!r} is UNKNOWN but was never incurred (no overnight hold)")
        else:
            incurred_unknown.append(c.name)

    judged = [c for c in model.components if c.name not in never_incurred]
    claim_eligible = bool(judged) and all(c.basis in CLAIM_ELIGIBLE_BASES for c in judged)
    if incurred_unknown:
        claim_eligible = False
        reasons.append(
            f"cost component(s) with UNKNOWN basis: {', '.join(sorted(incurred_unknown))} — not claim-eligible"
        )
    if n == 0:
        reasons.append("no trades supplied — the decomposition is empty, not favourable")
        claim_eligible = False
    if not model.components:
        reasons.append("cost model declares no components — costs would be silently zero")
        claim_eligible = False
    if not incurred_unknown and model.components:
        measured = model.measured_components()
        assumed = model.assumed_components()
        if measured:
            reasons.append(f"MEASURED: {', '.join(measured)}")
        if assumed:
            reasons.append(
                f"ASSUMED: {', '.join(assumed)} — a valid sensitivity result, but an economic-edge "
                "claim requires measured costs"
            )

    return CostDecomposition(
        gross_pnl_usd=gross_total,
        cost_usd=cost_total,
        net_pnl_usd=net_total,
        trades=n,
        gross_expectancy_per_trade=gross_exp,
        net_expectancy_per_trade=net_exp,
        cost_per_trade=cost_per,
        cost_drag=cost_drag,
        break_even_cost_multiple=break_even,
        per_component_usd=per_component,
        equity_gross=equity_gross,
        equity_net=equity_net,
        claim_eligible=claim_eligible,
        basis_summary=model.basis_summary(),
        reasons=reasons,
    )


def cost_summary_line(dec: CostDecomposition) -> str:
    """One honest sentence for a report or a UI."""
    if dec.trades == 0:
        return "no trades — cost decomposition empty (not evidence of profitability)"
    return (
        f"gross {dec.gross_pnl_usd:+.2f} USD - costs {dec.cost_usd:.2f} USD = net {dec.net_pnl_usd:+.2f} USD "
        f"over {dec.trades} trade(s); net expectancy {dec.net_expectancy_per_trade:+.4f} USD/trade; "
        f"break-even cost multiple {dec.break_even_cost_multiple:.2f}x"
    )
