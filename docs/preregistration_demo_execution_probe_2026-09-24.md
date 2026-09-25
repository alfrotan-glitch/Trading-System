# Preregistration — DEMO execution-cost probe (H-EXEC-01)

**Status:** PREREGISTERED 2026-09-24 · **Class:** `DEMO_FORWARD_RESEARCH_POLICY` ·
**Version:** 1.0.0 · **Policy id:** `DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1`
**Registered as:** `DEMO-EXECPROBE-XAUUSD-V1` in
`data/evidence/demo_forward_validation_registry_2026-09-23.json`
**Venue:** MT5 **DEMO** account, symbol `XAUUSD` (broker symbol `XAUUSD@`)
**Real capital exposure:** 0 USD · **LIVE:** locked

---

## 1. Why this experiment exists

The research ledger is closed with `decision: NO_VALIDATED_EDGE`
(`reports/research_cycle_closure_2026-09-23.json`). Every preregistered XAUUSD
hypothesis — H-DIR-01/02, H-DIR-03a/b, H-TEMP-01, H-ST-02WF, H-XF-01, H-XF-02,
H-MM-01, H-MM-02, H-MS-01/02, H-QD-01/02, H-INT-01, H-1M-01, H-VL-01…04 — is
REJECTED or INCONCLUSIVE with `strategy_promoted: false`. The surviving
magnitude results are **process structure, not directional trades**
("mean signed move ~0.8 cent, P(up)~0.506 at 256q; not executable — no
volatility instrument, no side").

So there is no hypothesis that may be traded forward, and inventing one to make
the DEMO account produce orders would be the exact research-integrity failure
this project forbids. What *can* be measured honestly, and what every future
hypothesis needs before it can be judged, is the **cost and behaviour of the
execution path itself**: the DEMO venue's spread at the moments QTS would
trade, the slippage between requested and executed price, the latency between
signal and venue acknowledgement, whether the protective stop is honoured and
at what deviation, and whether the system's own reconciliation agrees with the
venue after every order.

This policy exists to measure those quantities on the DEMO account. It is an
instrument, not an idea.

## 2. What is being measured (the object of study)

Per round turn, recorded in `demo_order_journal` and exportable:

| Measurement | Field(s) | Why it matters |
|---|---|---|
| Spread at entry | `spread_bps`, quoted bid/ask | The dominant cost of a minimum-size round turn |
| Slippage | `requested_price` vs `executed_price` (`slippage_bps`) | Whether the venue fills at the displayed quote |
| Submission latency | `latency_ms` (signal → broker ack) | Whether the venue/path is compatible with the policy's delay assumption |
| Stop behaviour | stop on the order, exit reason, realized P&L | Whether the protective stop is honoured, and at what deviation |
| Time-exit behaviour | `exit_reason = max_hold_seconds exceeded` | Cost of a deterministic exit when neither stop nor target fires |
| Round-turn cost | realized P&L including spread and slippage | The number any future hypothesis must beat |
| Market state at entry/exit | `market_state_entry`, `market_state_exit` | Context for every measurement |
| Reconciliation agreement | `reconciled`, drift, per-order journal row | Whether internal state tracks the venue |

Aggregate outputs: distribution of spread/slippage/latency by session hour,
realized cost per round turn, count of stops honoured vs deviated, count of
reconciliation breaks, and count of `NO_TRADE` refusals with their reasons.

## 3. What is explicitly NOT claimed

* **No edge.** Entry direction alternates by parity of the UTC hour so the
  sample set carries no net directional exposure. Any P&L is venue cost plus
  noise.
* **No signal.** No indicator, no pattern, no prediction, no parameter search.
* **No optimisation.** Parameters are frozen (`config_hash`) and the provider
  source is pinned (`code_hash`); the loop halts on either drift.
* **Not research data for strategy selection.** Forward observations recorded
  here must never be used to re-fit this policy or to select another strategy —
  that is the `no_forward_optimization` covenant in the authorization artifact.
* **Not evidence about a real account.** This is a DEMO venue; its fill
  behaviour is not a claim about live execution.

## 4. Exact rules (frozen)

**Signal logic.** Scheduled sampling. At most one entry per UTC hour
(`sample_interval_minutes: 60`), and only when: a two-sided quote exists, the
quote age is ≤ `max_tick_age_s` (5 s), and the spread is measurable. No market
condition other than cost and freshness gates an entry.

**Entry conditions.** `side = BUY` when the UTC hour is even, `SELL` when odd
(`side_rule: utc_hour_parity`) — deterministic, restart-independent, and
directionally neutral across samples. Size = broker minimum (0.01 lots).
Protective stop = `stop_distance_price` 2.00 USD from the entry reference
(ask for BUY, bid for SELL), attached to the order itself. No take-profit.

**Exit conditions.** Close at `max_hold_seconds` = 900 s (15 min) after entry,
or earlier if the protective stop is hit at the venue. Either way the exit
reason and the venue's realized P&L are recorded. No discretionary exit, no
trailing stop, no "let it run because it is winning".

**Position sizing.** Fixed 0.01 lots — the broker minimum — regardless of
account equity. One position at a time (`max_simultaneous_exposure_lots` 0.01),
which makes exposure deterministic rather than equity-dependent.

**Limits.** 2 orders/day, minimum 900 s between orders, max daily loss 5.00 USD,
max drawdown 10.00 USD, spread ≤ 3.0 bps, slippage assumption 2.0 bps,
execution-delay assumption 1500 ms.

**Session.** Monday–Friday 08:00–16:00 UTC: the London–New York overlap, chosen
because it is the liquid window for XAUUSD where a spread measurement is
representative rather than a rollover artefact. No weekend or rollover sampling.

**Minimum data requirements.** A fresh two-sided quote (≤ 5 s), a broker symbol
spec, a passing broker `order_check`, and a resolved risk-limit snapshot. The
gate encodes these as mandatory checks; if any is not PASS the order is refused.

**Failure-closed behaviour.** Any `UNKNOWN` gate check fails the order. Missing
quote, unverifiable account type, unreadable kill-switch state, or a
reconciliation older than 120 s all refuse.

**Kill conditions.** Daily-loss breach, drawdown breach, reconciliation
suspension or drift, parameter drift, code drift, identity mismatch,
authorization revoked, stage no longer order-permitted, and stale market data.
Each raises the durable kill switch and halts the stage — recovery requires
`qts demo clear-kill --reason … --confirm` followed by an explicit re-arm.

**Reconciliation.** After every order, and after every close. Drift halts.

## 5. Stopping and review

The run stops on any kill condition, on reaching the daily order budget, or on
operator action (`qts demo kill`). Review is by **measurement completeness**,
not by profit: did we obtain spread/slippage/latency/stop observations with
reconciliation clean throughout? A run that loses money and produces complete
measurements succeeded. A run that makes money but cannot show why did not.

## 6. Change control

Any change to the rules above is a **new** policy version with a new
preregistration and a new `config_hash`, not an edit — and never a response to
an observed result. The registry refuses an entry whose `params_hash` or
`config_hash` no longer matches what was registered (`PARAMETER_DRIFT`).
