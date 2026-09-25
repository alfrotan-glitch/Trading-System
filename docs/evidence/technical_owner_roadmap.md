# QTS technical-owner decision record — 2026-09-19

## Current decision

QTS is not authorized to trade a discovered edge. The highest-value next step is
not another strategy search: it is closing the evidence boundary around
execution realism (R5) and completing a real FO-R1 observation run. Existing
research must remain frozen and its gates must not be weakened.

## Facts currently supported by repository evidence

- The repository's canonical research materials describe R5 as FAIL/non-blocking:
  continuous historical bid/ask, measured spread, latency, fill and slippage
  evidence is absent.
- The MT5 acquisition capability has a private local 730-day XAUUSD@ dataset,
  but the raw broker data is not present in this repository and must remain
  local. The bounded derived report records 139,930,971 rows, dataset SHA-256
  `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`, and
  108 gaps above 24 hours.
- All 108 gaps remain `UNRESOLVED`. Recurring weekend-looking intervals are
  observations, not broker schedule proof.
- MetaQuotes documentation supports UTC as the MT5 obtained-tick timestamp
  basis; it does not establish WM Markets historical sessions, DST behavior, or
  holiday closures.
- Quote history is not execution evidence. The MT5 dataset therefore cannot by
  itself solve R5 or authorize live trading.

## Ordered path to a safely tradeable edge

1. **Preserve the evidence boundary.** Keep the raw dataset private and
   immutable. Run the offline integrity and gap tools on Windows, with fixed
   inputs and captured manifests. Do not rewrite timestamps or classify gaps by
   pattern.
2. **Establish execution-cost evidence.** Run the existing order-free FO-R1
   protocol on the real demo terminal for a declared observation horizon. Record
   spread, quote freshness, timestamp basis, terminal/account identity, outages,
   and acquisition health. This is observation, not execution.
3. **Define the execution experiment before strategy reruns.** Preregister
   latency, spread, slippage, rejection, fill, and market-impact measurements;
   specify censoring, outage treatment, regime coverage, and acceptance gates.
4. **Only after valid R5 evidence, rerun the frozen research design unchanged.**
   Use untouched OOS windows, trial accounting, multiple-testing controls, and
   the existing promotion gates. A promising backtest is not a promotion.
5. **Shadow first, then constrained paper/demo validation.** Require a complete
   audit trail and a kill switch. No capital deployment follows from quote-only
   history or synthetic fills.
6. **Production is last.** It requires independently reproduced edge evidence,
   bounded loss, operational health, reconciliation, and explicit human release.

## Stop conditions

- Missing or conflicting provenance: stop and mark unresolved.
- Dataset mutation or checksum mismatch: quarantine the run.
- R5 absent: no claim of execution viability and no live authorization.
- Any strategy result dependent on a changed gate, repaired gaps, synthetic
  quotes, or untracked trials: reject as non-auditable.
