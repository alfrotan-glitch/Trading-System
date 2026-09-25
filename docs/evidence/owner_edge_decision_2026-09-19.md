# Owner edge decision — 2026-09-19

## Decision: DATA_BLOCKED; no verified edge

QTS cannot currently answer “yes” to whether it has a real, repeatable,
economically exploitable trading edge. The correct project state is:

```text
NO VERIFIED EDGE FOUND
RESEARCH PATH: DATA_BLOCKED
CAPITAL: NO_TRADE
```

This is not a claim that no market edge exists. It is the stronger and more
honest statement that the repository's available evidence cannot establish one
under the unchanged QTS gates.

## What was actually tested or preserved

The existing frozen REAL impulse study tested a preregistered continuation
mechanism on XAUUSD 15-minute bars. Its conclusion was `REGIME_DEPENDENT` and
promotion was blocked. R5 execution data failed. It is not an executable edge.

The original 26,038-row source was lost and cannot be cryptographically
re-verified. A new reproducible source was acquired from the pinned upstream
commit:

```text
vudo805/forex-price-simulator@4d6f15543e6285fad91fd57fe42f716bc7273075
```

The new export has 26,038 rows and complete source-file hash verification, but
its unchanged QTS completeness gate fails:

```text
unexpected active-span missing: 6.42%
allowed limit:                    2.00%
status:                           BLOCKED_INSUFFICIENT_DATA
```

It therefore cannot support a new confirmatory real-market edge claim. The
matching row count does not make it the old dataset and does not authorize
transfer of the old OOS index boundaries.

The previous DEMO observe-only session recorded quote observations but ended on
stale-data error and contains no realized fills, slippage, rejection, or
execution-cost experiment. It cannot close R5.

## Why no new strategy search is justified

A broad search on the currently available incomplete dataset would create a
selection and missingness problem, not evidence. The existing impulse branch
has already produced a blocked regime-dependent result. Running more indicators
or parameters before obtaining an adequate, immutable, independently verifiable
research population would optimize activity rather than truth.

No candidate is promoted. No failed result is erased. No trial ledger is reset.

## Minimum condition to reopen research

Only one of these evidence paths justifies further confirmatory research:

1. an immutable, cryptographically identified XAUUSD dataset that passes the
   existing completeness gate and supports untouched chronological validation;
   or
2. a documented alternative source with a scientifically valid trading calendar,
   complete provenance, and a separately reviewed completeness rule that does
   not weaken the existing policy or disguise missing intervals.

After that, one preregistered mechanism test may be run. It must include
realistic costs and independent OOS validation. If it fails, the mechanism is
killed. If it survives, execution-specific evidence remains a separate gate.

## Final safety state

- no real orders;
- no capital exposure;
- no execution enablement;
- no change to research gates;
- no repaired or synthesized bars;
- no reinterpretation of historical evidence;
- no claim that quote history is execution evidence.

Until the data requirement is met and all promotion gates pass, QTS remains
`NO_TRADE`.
