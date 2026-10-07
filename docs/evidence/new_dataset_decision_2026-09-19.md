# New XAUUSD 15-minute dataset decision

## Acquisition

The original frozen source was reproducibly reacquired from the pinned upstream
GitHub commit `vudo805/forex-price-simulator@4d6f15543e6285fad91fd57fe42f716bc7273075`.
All 14 source Parquet SHA-256 values matched the pinned values in the existing
QTS acquisition script. The export contains 26,038 UTC 15-minute XAUUSD
mid-price OHLC rows from 2025-08-06 through 2026-09-16. The export SHA-256 is:

`7271892fa9bacf2a4ad20655d6a019020a4aaf057510e769bb42c5ba59d0a074`

This is a new acquisition record. It is not asserted to be byte-identical to
the lost old dataset because the old artifact retained only a truncated
`sha256:1ba57af7d9d034d9` identifier.

## Quality gate

The existing QTS quality machinery was run unchanged against the new 15-minute
export. Structural checks passed: monotonic UTC timestamps, timezone-aware
rows, valid positive OHLC, no duplicate intervals, valid session boundaries,
and nonnegative volume.

Completeness failed the existing gate:

- expected intervals: 39,072
- actual rows: 26,038
- calendar missing: 13,034 (33.36%)
- gap events: 336
- recognized weekend-boundary closure events: 57
- unexpected gap events: 279
- unexpected missing intervals: 1,785
- active expected intervals: 27,823
- unexpected active-span missing: 6.42%
- unchanged limit: 2%

The quality disposition is therefore:

```text
BLOCKED_INSUFFICIENT_DATA
```

No holiday assumptions were used to forgive gaps. No bars were repaired,
interpolated, synthesized, or deleted.

## OOS decision

The preregistered OOS experiment was **not executed**. The unchanged completeness
gate failed before research execution. Although the new dataset has the same
row count as the lost artifact, that coincidence does not authorize transfer of
the old index boundaries or claim identity with the old source.

The source acquisition and quality evidence are recorded in:

- `data/evidence/xauusd_dukascopy_acquisition_new.json`
- `data/evidence/xauusd_dukascopy_new_quality.json`

The raw source and exports remain gitignored/local. QTS remains `NO_TRADE`.
