# MT5 historical timestamp basis — 2026-10-23

The read-only same-session measurement in
`data/evidence/mt5_timestamp_basis_20261023.json` compares the same terminal's
historical `copy_ticks_range` response with its live tick and forming M1 bar.

- Historical raw time aligns with the UTC request end within the fixed
  tolerance.
- Live tick and M1 raw time share the same non-zero server-local offset.
- The evidence is bound by dataset SHA-256 to the nine complete local raw
  acquisitions from 1 through 365 days.
- The result is `MEASURED_SAME_SESSION`; it does not alter the raw manifests or
  silently normalize any stored value.

This is sufficient to unlock UTC session research only for those digest-bound
datasets. It is not evidence about fills, latency, commission, slippage, or
future broker behavior.

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
