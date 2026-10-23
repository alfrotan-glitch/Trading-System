# Preregistration: MT5 XAUUSD fixed session reversal

This follow-up is registered before its measurement on the one-year local
ledger. It is a separate directional hypothesis family from the already
measured session-momentum family.

## Fixed rules

- Historical `time_msc` must pass the digest-bound same-session UTC evidence
  gate.
- Use only the stored bid/ask tick ledger; no rows are repaired or reordered.
- At 08:00 UTC and 13:30 UTC, compute the preceding four-hour mid-price
  return from the last observed quote before each endpoint.
- Enter at the first valid quote at or after the session start, in the
  opposite direction of that return.
- Exit at the first valid quote at or after the fixed four-hour session end.
- Reject an event when endpoint availability is more than 30 minutes late.
- Use actual bid/ask sides for entry and exit. Add fixed 0, 1, and 2 bps
  round-trip price-cost stress; no commission or fill assumption is hidden.
- Split calendar dates chronologically 60/20/20, shared across both
  hypotheses. No threshold, boundary, or holding-period search is permitted.

Hypotheses are `H-SES-LDN-REV-4H` and `H-SES-NY-REV-4H`. A result is not a
validated edge unless all three chronological splits have at least 20 events,
positive mean net return at the 1 bps stress, and the holdout t-statistic is at
least 2.0. No result can promote a strategy automatically.

Safety: the assay is offline and read-only; `orders_submitted=0`,
`DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
