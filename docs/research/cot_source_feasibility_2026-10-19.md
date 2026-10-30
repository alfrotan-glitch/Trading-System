# COT source-feasibility audit — 2026-10-19

**Status:** input-only audit; no hypothesis was preregistered or tested. The
frozen cross-metal relative-momentum screen remains rejected. `LIVE` remains
locked, no orders were submitted, and the 730-day holdout was not accessed.
At this audit the long-history count was `N=356`; the subsequent Brent-gate, FX-dispersion, and commodity-breadth screens each added one separately preregistered configuration, so the current count is `N=359`. A later CPI-acceleration attempt failed its pinned CSV/schema check before features or outcomes and did not add a trial; the denominator remains `N=359`.

## Scope and handling

This audit checked GitHub repository metadata, pinned commit trees/file names,
licenses, and source/provenance documentation only. No row-level COT positions
or price observations were downloaded, opened, or parsed; no candidate code was
run; no evidence JSON was changed.

One mixed provenance document in the `closeofbusiness/market-plumbing` source
also contained summaries of unrelated COT study outcomes. Those summaries were
incidentally visible while checking provenance. The source is quarantined from
this edge search: none of those figures is reproduced here or used to choose a
candidate, and this audit is not an internal trial or a change to the DSR
multiple-testing count.

## Subsequent long-history FX quote-convention caveat

The later FX-dispersion gate (`LH-XAUUSD-FX-DISPERSION-GATE-2026-10-19`)
followed its pinned README-based inversion claims for Australia, New Zealand,
and the United Kingdom. A post-run code audit found those claims conflict with
the pre-existing `scripts/build_longhistory_monthly_dataset.py` contract,
which treats all eight H.10 observations as currency-per-USD. Preserve the
runner's `REJECTED` output, but classify the intended FX-dispersion hypothesis
as **INCONCLUSIVE**; do not invert/correct the orientation or rerun it on the
reused partitions. Evidence/report:
`data/evidence/longhistory/fx_dispersion_gate_discovery_dev.json` and
`docs/research/fx_dispersion_gate_results_2026-10-19.md`. This source
convention issue does not change the COT-source feasibility conclusion above.

## Source findings

| Pinned source | Metadata/provenance finding | Decision |
|---|---|---|
| [`closeofbusiness/market-plumbing@1eac1547efb8262619bdb6fb3849f576d6cc8299`](https://github.com/closeofbusiness/market-plumbing/tree/1eac1547efb8262619bdb6fb3849f576d6cc8299) | GitHub declares CC-BY-4.0. Its raw-source manifest identifies CFTC Disaggregated COT API extracts (`72hh-3qpy`, `kh3c-gbw2`), with `report_date >= 2010-01-01`; it identifies the CFTC source as public domain and notes the API serves revised history without as-of vintages. The repository also contains derived gold/COT files, but their row dates were not inspected. | Not eligible for the required pre-2000 discovery/development path: the declared raw CFTC extraction begins in 2010. The mixed source document also exposed unrelated results, so do not use this repository to select or validate a candidate. |
| [`NDelventhal/cot_reports@3a96210386e4523f4dccd90407b7e06f812e9a01`](https://github.com/NDelventhal/cot_reports/tree/3a96210386e4523f4dccd90407b7e06f812e9a01) | MIT-licensed downloader/library; its repository description lists Legacy Futures-only and other CFTC report types. Pinned tree contains no CSV/ZIP/Excel/Parquet archive. | Useful software lead, not a usable dataset. Direct CFTC endpoints are outside this sandbox's allowed outbound hosts, so no archive was fetched. |
| [`xseeope/two_tale_1.2@42eb5e6165086685ad6558d924e7218402bcb036`](https://github.com/xseeope/two_tale_1.2/tree/42eb5e6165086685ad6558d924e7218402bcb036) | Repository includes an MIT LICENSE; its source sections describe CFTC Legacy weekly commercial/non-commercial positions for 1994–2017 and daily-to-weekly Tuesday-close prices for 22 futures from Yahoo Finance. The README notes the gold series is a continuous futures contract, not a specific expiry. The tree contains raw/processed COT and gold-price files, but no row contents were read. The license file names CFTC data as public domain and Yahoo Finance as a source while leaving provider-term compliance to users. | Only 1994–1999 lies before the project cutoff, so it cannot support a governed 1986–1989 discovery slice. Yahoo-derived price terms and revision/vintage controls are not established, and continuous GC futures are not XAUUSD spot. The repository is an existing academic replication, so its processed outputs are not used. Not eligible for this cycle. |
| [`kustex/CFTC-COT-Report@1838a8d4d5eef5351fcc72244c7fa107daa90c2c`](https://github.com/kustex/CFTC-COT-Report/tree/1838a8d4d5eef5351fcc72244c7fa107daa90c2c) | MIT-licensed report downloader/dashboard; the inspected README describes 2020–2025 as its default archive years. | Does not establish a pre-2000 COT history. Not eligible. |
| [`krss1985-prog/seasonality-cot@c380a47937e1c761fefcfbdd1df5039aed6df16a`](https://github.com/krss1985-prog/seasonality-cot/tree/c380a47937e1c761fefcfbdd1df5039aed6df16a) | GitHub API has no SPDX license; the fetch code starts at 2006-01-01 and queries CFTC Socrata. | Not eligible for pre-2000 research; license is unresolved and the direct source host is outside the outbound allowlist. No bundled CSV values were read. |
| [`ngohamah/cftc-cot-data-extraction-pipeline@af153f5f3e3935c44952a208a4e7425a2ce98811`](https://github.com/ngohamah/cftc-cot-data-extraction-pipeline/tree/af153f5f3e3935c44952a208a4e7425a2ce98811) | GitHub API has no declared license. Its tree includes processed `data/` and `signal/` files; neither file contents nor date coverage were inspected. | Excluded: rights, provenance, transformations, and outcome contamination are not established. |
| [`ajaiupadhyaya/creditrisk`](https://github.com/ajaiupadhyaya/creditrisk) | Earlier metadata/tree check found a `COTHist2026.csv`, but no GitHub-declared license or LICENSE file in the checked tree. | Excluded: license, source, and date coverage remain unverified. No CSV values were read. |

## Feasibility conclusion

No examined GitHub source satisfies the governed time window and provenance
requirements for a gold COT experiment. One MIT-licensed replication bundle
claims CFTC Legacy and Yahoo-derived weekly futures inputs for 1994–2017, but
only 1994–1999 is pre-cutoff: it cannot provide a preregistered 1986–1989
discovery slice; its continuous GC futures series is not XAUUSD spot, and Yahoo terms and
revision/vintage controls are unresolved. Other available COT mirrors are
fetcher code without data, begin in 2006/2010, or lack verified licensing and
provenance. The local price inventory contains monthly World Bank averages,
not a newly identified independent daily/weekly gold series that would support
point-in-time alignment to weekly COT releases. Therefore
no distinct COT hypothesis is frozen yet; choosing a specification before
resolving the eligible data and release-date inputs would create a fragile
protocol rather than a valid experiment.

## Required gate to resume this branch of research

Provide an official/public-domain CFTC Legacy gold futures-only archive covering
a preregistered 1986–1989 discovery slice and the 1990–1999 development period,
including report dates and publication/release metadata, plus a provenance-clear gold
price series at a frequency sufficient for the intended execution timing.
Before opening any feature values, record
source URLs, licenses/terms, extraction date, hashes, report definitions,
revision/vintage behavior, and point-in-time release rules; then preregister one
new hypothesis and freeze its runner. If it is evaluated, it will be a new
trial after the current long-history `N=359`. Keep the 2000+ price window and
the locked 730-day partition closed.
