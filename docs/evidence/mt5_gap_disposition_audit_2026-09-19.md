# WM Markets XAUUSD 730-day gap evidence audit

## Result

The committed bounded report contains 108 exact gaps above 24 hours. Each was
reviewed against the available evidence boundary. No authoritative WM Markets
historical XAUUSD/Gold schedule or closure notice establishing any particular
observed interval was available in this audit. Accordingly, every gap remains
fail-closed as `UNRESOLVED`.

| Classification | Count |
|---|---:|
| EXPECTED_WEEKEND_CLOSURE | 0 |
| EXPECTED_DOCUMENTED_MARKET_HOLIDAY | 0 |
| EXPECTED_DOCUMENTED_MARKET_CLOSURE | 0 |
| UNEXPECTED_DATA_GAP | 0 |
| UNRESOLVED | 108 |

## Method and boundaries

The exact gap IDs, raw `time_msc` boundaries, and durations were taken from
`data/evidence/mt5_history_analysis/XAUUSD__730d_gap_disposition.json`; no gap
was recreated, merged, split, or inferred from raw data. The evidence artifact
contains one record for each of the 108 IDs. Observed Friday-to-Monday
recurrence is recorded as an empirical limitation, not broker evidence.

A weekend-looking interval is not classified as a weekend closure without
broker-specific schedule evidence. Generic holiday calendars, CME schedules,
and other-broker calendars are not proof of WM Markets `XAUUSD@` closure.
No `UNEXPECTED_DATA_GAP` classification is made because absence of a documented
closure does not prove acquisition failure or missing data.

## Sources

The official MetaQuotes `copy_ticks_range` documentation establishes the UTC
basis of obtained MT5 tick data:

- MetaQuotes, “copy_ticks_range / Python Integration”, page metadata 2022-03-21,
  https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py

That source is timestamp-basis evidence only. It does not establish WM Markets
server time, DST/session rules, or historical XAUUSD holiday closures. The
versioned evidence artifact records this limitation explicitly.

## Special periods

Christmas 2024/2025, New Year 2025/2026, Good Friday/Easter 2025/2026, and the
longer observed intervals were not upgraded: no WM Markets document tying each
specific observed boundary to a closure was available. DST-like changes in
observed durations likewise remain observations, not proof of a WM Markets
session schedule.

Dataset SHA-256: `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`.
Raw Parquet and quote payloads are not included or modified.
