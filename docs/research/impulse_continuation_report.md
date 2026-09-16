# Impulse Continuation Research — Report

**Date:** 2026-09-16 · **Status:** RESEARCH ARTIFACT — not a strategy, not tradeable, no promotion
**Conclusion:** `BLOCKED_INSUFFICIENT_DATA` · research **GO/BLOCK: BLOCK** (for real-market claims)
**Machine evidence:** `data/evidence/impulse_research.json` · generated detail: `impulse_continuation_evidence.md`
**Code:** `src/qts/research/impulse/` · **CLI:** `qts research impulse` · **Tests:** 118 (see §8)

---

## 1. Research question

When price begins an unusually strong directional movement (an *impulse*), does the
conditional distribution of the next short horizon become sufficiently directional and
persistent to produce **positive net expectancy after spread, commission, slippage, and
execution latency** — for LONG and SHORT impulses alike?

This was built strictly as a **research capability**. It is not connected to order
submission, does not modify live eligibility, does not touch promotion state, and its
design makes it impossible to auto-promote the best-looking impulse definition.

## 2. Pre-registered design (no data-driven search)

**Detector families — 5 definitions × 2 parameterizations = 10 families** (all recorded
in `PRE_REGISTERED_FAMILIES`; nothing else is ever evaluated):

| Definition | Trigger (causal, at bar close *i*) | Direction | Baseline / Variant |
|---|---|---|---|
| `range_expansion` | range(i) > k · median(range of prior 20 bars) | sign(close−open) | k=2.5 / k=3.5 |
| `price_velocity` | \|close(i)−close(i−3)\| > k · σ(prior 3-bar moves, window 60, completed before the trigger) | sign(move) | k=2.5 / k=3.5 |
| `vol_expansion` | σ(last 6 returns) > k · σ(prior 18 returns) | sign(6-bar move) | k=2.0 / k=3.0 |
| `range_breakout` | close(i) > max(high prior 20/40) or < min(low prior 20/40) | break side | N=20 / N=40 |
| `breakout_with_expansion` | breakout AND range expansion, same direction | agreeing side | N=20,k=2.0 / N=40,k=2.0 |

**Causality is structural, not conventional:** detectors receive only `bars[:i+1]`;
baseline statistics use bars strictly *before* the trigger (a bar can never inflate its
own threshold); warmup is 64 bars; adversarial tests mutate the future and assert past
detections are bit-identical.

**Measurement (independent module):** entry at the close of bar `i + latency`; horizon
H ∈ {12 (primary), 4}; target = adverse = 1.0 × ATR(14) (symmetric race, pre-registered).
Per event: time-to-target (censoring explicit), MFE, MAE, continuation/reversal at
horizon, duration, first-passage race (TARGET / ADVERSE / NEITHER), gross and net
horizon return in bps. **Intra-bar ordering is unknown from OHLC**: when both thresholds
are touched in the same bar the race resolves **ADVERSE-first** (conservative — we never
claim a target hit that bar data cannot prove). Events whose window extends past the end
of the series are **excluded and counted**, never measured on truncated paths.

**Baseline & placebo:** non-event bars outside every event's measurement window, seeded
random directions, identical measurement; plus 200 seeded placebo draws (random timing,
same event count) producing an empirical one-sided p-value for the continuation
advantage.

**Partitions:** chronological discovery (60%) / validation (20%) via the existing
`LockedTestPartitioner`; the **locked 20% is never measured** (11 events detected there
were discarded and counted). No OOS claim can be made from discovery alone.

**Multiple testing:** Holm-Bonferroni across the 10 families per (horizon, split), plus
deflated Sharpe ratio penalized with the **full cumulative ledger trial count** (N=57 at
run time — the ledger is never reset). 40 trials (10 families × 2 horizons × 2 splits)
were recorded in the `ExperimentStore` ledger for this run, including every rejection.

## 3. Declared cost model (explicit, auditable — class ESTIMATED)

Spread 2.0 bps round turn · commission 0.4 bps round turn · slippage 0.5 bps per side
→ **3.4 bps round turn**; latency 1 bar (base). These are *assumptions*, labeled
`ESTIMATED:declared_assumption` — not broker observations. Sensitivity sweeps are part
of every evidence file: cost ×{0.5, 1, 1.5, 2}, spread ×{0.5, 1, 1.5, 2}, latency
∈{0, 1, 2} bars.

## 4. Data audit — FIRST deliverable, performed before any claim

Available dataset (exact provenance): version `20260916-010-572728d9`, XAUUSD 1H, venue
MT5, checksum `sha256:572728d92ebb5c2a`, 500 rows, span 2020-01-01 → 2020-01-21 (UTC),
source label `SYNTHETIC:fixture:XAUUSD_1H_500.csv`, **data class SYNTHETIC** (GBM seed=42).

| Req | Minimum | Observed | Passed |
|---|---|---|---|
| R1 real provenance | class == REAL | SYNTHETIC | **FAIL** |
| R2 depth | ≥ 5,000 bars (target 17,520) | 500 | **FAIL** |
| R3 regime coverage | ≥ 180 days | 20.8 days | **FAIL** |
| R4 freshness | last bar ≤ 7 days old | 2,429.9 days old | **FAIL** |
| R5 execution data | real spread/bid-ask/tick history | OHLC bars only | FAIL (non-blocking: cost sweeps compensate) |
| R6 event sufficiency | ≥ 100 events, ≥ 30/side | 53 total (27 L / 26 S) | **FAIL** |

**Verdict: the current data is NOT adequate for this research.** Per the mandate, no
synthetic substitute was quietly made: the run executed in `MECHANISM_VALIDATION` mode,
every output is labeled accordingly, and the classifier forces
`BLOCKED_INSUFFICIENT_DATA` — real-market claims are impossible in this mode *whatever
the numbers look like* (truth-table tested).

## 5. Example experiment — results (mechanism validation on the SYNTHETIC fixture)

Pooled discovery+validation, primary horizon 12 bars, costs 3.4 bps, seed 42:

| Family | n | cont. | baseline | diff | p_raw | p_holm | gross bps | net bps | net CI | target-hit | MFE | MAE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IMP-BE-B | 7 | 0.43 | 0.46 | −0.03 | 1.000 | 1.000 | −231.2 | −234.6 | [−586, +71] | 0.43 | 196 | 212 |
| IMP-BE-V | 3 | 0.67 | 0.50 | +0.17 | 1.000 | 1.000 | +61.8 | +58.4 | [−330, +275] | 1.00 | 345 | 96 |
| IMP-PV-B | 6 | 0.50 | 0.45 | +0.05 | 1.000 | 1.000 | −203.4 | −206.8 | [−716, +321] | 0.33 | 163 | 315 |
| IMP-PV-V | 1 | 0.00 | 0.51 | −0.51 | 0.494 | 1.000 | −938.6 | −942.0 | [−942, −942] | 0.00 | 16 | 461 |
| IMP-RB-B | 16 | 0.38 | 0.45 | −0.08 | 0.620 | 1.000 | −132.6 | −136.0 | [−350, +71] | 0.44 | 182 | 219 |
| IMP-RB-V | 10 | 0.50 | 0.46 | +0.04 | 1.000 | 1.000 | −16.7 | −20.1 | [−329, +307] | 0.60 | 258 | 206 |
| IMP-RE-B | 7 | 0.29 | 0.52 | −0.24 | 0.270 | 1.000 | −150.3 | −153.7 | [−664, +356] | 0.71 | 255 | 187 |
| IMP-RE-V | 1 | 0.00 | 0.52 | −0.52 | 0.475 | 1.000 | −1003.5 | −1006.9 | [−1007, −1007] | 1.00 | 303 | 129 |
| IMP-VE-B | 2 | 0.00 | 0.49 | −0.49 | 0.500 | 1.000 | −566.7 | −570.1 | [−896, −244] | 0.50 | 304 | 268 |
| IMP-VE-V | 0 | — | 0.50 | — | 1.000 | 1.000 | — | — | — | — | — | — |

Counts: bars 500 · events detected 53 · measured 106 (53 × 2 horizons) · excluded 0 ·
discarded-in-locked 11 · trials recorded 40 · ledger total 57 · DSR penalized with N=57.

Reading (mechanism level only): min Holm-adjusted p = 1.0 in both splits; no family
shows corrected-significant continuation; net CIs straddle or sit below zero. This is
exactly what momentumless GBM should produce — the pipeline manufactures no edge
(asserted by `TestNullBehaviorOnGBM` on an independent 1,500-bar GBM seed). Small-n
families (n ≤ 3) illustrate why R6 exists: no inference is possible at these counts.

## 6. Conclusion taxonomy (deterministic, tested truth-table)

The classifier can output exactly: `NO_EDGE_FOUND`, `REGIME_DEPENDENT`,
`EDGE_BEFORE_COSTS_ONLY`, `SURVIVES_OOS_AND_FORWARD`, `PROMISING_INSUFFICIENT`,
`BLOCKED_INSUFFICIENT_DATA` — precedence: data gate first, then OOS+forward, costs,
regime, promising, null. `SURVIVES_OOS_AND_FORWARD` (the only `GO`) requires corrected
significance **in both splits**, cost-robustness across the sweep, **and** ≥10 recorded
forward observations — the last of which does not exist, so it is currently unreachable
by design. For this dataset the conclusion is forced to:

> **BLOCKED_INSUFFICIENT_DATA — research BLOCK.** No evidence for or against real-market
> impulse continuation can be established from a 500-bar synthetic single-regime fixture.
> This is a data verdict, not a NO_EDGE_FOUND verdict: on this data the question is
> unanswerable, and the system says so instead of guessing.

## 7. Minimum data required to unblock (exact)

1. **REAL** provenance label (`real_*` source at ingest; broker MT5 history export
   qualifies when labeled truthfully) — R1.
2. ≥ **5,000** 1H bars (target 17,520 ≈ 2 years), span ≥ **180 days** — R2/R3. For
   genuinely *short-horizon* impulse research, 15m/5m bars or ticks are strongly
   preferred; 1H is the coarsest admissible frame.
3. Last bar within **7 days** of assessment (staleness gate) — R4.
4. Real spread/bid-ask/tick history to replace declared cost assumptions — R5
   (non-blocking; until then every cost conclusion carries the ESTIMATED label and must
   survive the 2× sweep).
5. ≥ **100** measured events with ≥ **30 per side** after warmup/exclusions — R6.
6. Forward observation corpus (Demo Forward → `demo_forward_observations.json`, ≥10
   records) before any `SURVIVES_OOS_AND_FORWARD` claim is possible.

## 8. Validation & reproducibility

- **Tests:** 118 new deterministic tests across 8 files — unit (detectors, measurement,
  costs, statistics), adversarial lookahead (prefix equivalence, future corruption,
  measurement locality, locked isolation, warmup), property-based (hypothesis: prefix
  agreement, MFE horizon-monotonicity, net = gross − declared cost), adequacy gate,
  conclusion truth-table, pipeline (fail-closed, ledger accounting incl. cumulative
  re-run, determinism across workspaces, GBM null, evidence schema).
- **Gates:** full suite green (368+ passed, integration 14 via `--run-integration`),
  ruff/format/mypy(103 files)/bandit clean, coverage ≥60%, ASCII-locale green,
  clean-clone reproducibility preserved (all impulse tests use tmp workspaces; repo
  `data/` untouched except the committed evidence artifact).
- **Reproduce:** `qts data bootstrap && qts research impulse
  --report-out docs/research/impulse_continuation_evidence.md` (deterministic, seed 42;
  appends 40 trials to the cumulative ledger per run).

## 9. Limitations (explicit)

Bar-data intra-bar ambiguity (resolved conservatively); synthetic single-regime dataset
(no real-market claim possible); 1H timeframe bounds "short horizon" to hours; declared
costs are assumptions until broker-observed; small event counts make per-family CIs
wide; GBM fixture has no momentum by construction, so this run validates *mechanism*,
not *economics*; forward-observation channel empty ⇒ strongest conclusion unreachable;
placebo/baseline use seeded randomness (recorded seeds), not broker randomness.

## 10. Safety invariants (asserted in evidence and tests)

live_trading_enabled: False · live_eligibility_modified: False ·
order_submission_connected: False · promotion_state_modified: False ·
locked_test_partition_accessed: False · trial_ledger_reset: False.
