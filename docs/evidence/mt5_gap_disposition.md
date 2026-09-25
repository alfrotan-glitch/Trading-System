# MT5 long-gap disposition

Run on the Windows operator machine; the dataset path is local and gitignored:

```powershell
.\.venv\Scripts\python.exe scripts\analyze_mt5_gap_disposition.py `
  --dataset "data\raw\mt5_ticks\XAUUSD_\730d__20260919T114013Z" `
  --output data\evidence\mt5_history_analysis\XAUUSD__730d_gap_disposition.json
```

The tool reads only `manifest.json` and the Parquet parts, selecting only
`time_msc`. It does not import or connect to MT5 and never writes the dataset.
It emits no quote payloads. By default every >24-hour gap is `UNRESOLVED`.
Documented dispositions may be supplied in a separate operator evidence JSON
(not the raw dataset), keyed by `gap-0001`, etc., with `classification`,
`basis`, and `evidence_refs`; `sources` contains the source name/date/fact and
whether it directly establishes closure or merely supports an interpretation.

`time_msc` values remain integers exactly as acquired. ISO strings and weekend
checks are explicitly provisional UTC renderings until the historical timestamp
basis is independently verified. A gap is an observation of tick arrivals,
not proof of missing data, closure, a halt, or acquisition failure. Use
`--analysis-timestamp` when a byte-for-byte reproducible report export is
needed. The committed report is bounded derived evidence only; raw Parquet
files remain private/local and gitignored.
