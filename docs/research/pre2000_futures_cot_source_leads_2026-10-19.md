# Pre-2000 futures and COT source leads — 2026-10-19

**Disposition:** one potentially relevant monthly gold spot/futures archive was
identified, but no source is admitted yet. This remains metadata/provenance
research only: no candidate was preregistered or tested; long-history
`N_TRIALS` remains `359`; `LIVE` remains locked; no post-1999 gold/eligible-panel
price values or locked holdout were accessed. During a later GitHub README scan,
one generic MNQ example row in an unrelated 2026 TopstepX data repository was
incidentally visible; it was not ingested into an analysis or used as research evidence.

## Scope

Checked GitHub API metadata, repository trees, and source documentation. No
market-data ZIP/CSV/JSON/SQLite contents were downloaded or opened; no COT
position values, gold prices, feature values, or study metrics were used to
select a hypothesis. The README/PDF documentation for the futures-data lead
was read only for its declared schema, provenance, and terms.

## Potential gold futures-curve source

[`SSEconomics/commodity-spot-and-futures-data@300840ee19d9ae8aafef757ac6791e58da4c388a`](https://github.com/SSEconomics/commodity-spot-and-futures-data/tree/300840ee19d9ae8aafef757ac6791e58da4c388a)
contains ZIP-named spot and futures packages. Its README describes monthly
spot prices and contract-level futures prices aligned by delivery horizon for
17 commodities, including gold, with a static archive through December 2022.
The separate futures README describes nominal raw contract settlements before
interpolation, which could support a genuinely distinct term-structure
hypothesis if the relevant gold history and rights qualify. No archive was
downloaded, so the gold sample start date and contract coverage remain unknown.

The repository has no SPDX license metadata or LICENSE file. Its README
shows a CC-BY-4.0 badge, while the supplementary spot/futures READMEs say the
data are for academic use, not for resale, and recommend a non-commercial
Creative Commons license. The README directs users to the paper's ticker/source
and sample-period tables; the underlying provider terms and gold sample period
were not verified. These conflicting rights statements and unknown pre-2000
gold coverage block use. Do not inspect the ZIPs or register a trial until
explicit data-use permission/terms and the eligible date coverage are resolved.
If cleared, only the raw contract-level futures/spot observations should be
considered; do not use the repository's preconstructed forecast paths as
features.

## COT repository leads

| Source | Metadata/provenance finding | Decision |
|---|---|---|
| [`souravh093/cot_reports_data@d4dab67a6c2b38c747ccbfef0e839709425db161`](https://github.com/souravh093/cot_reports_data/tree/d4dab67a6c2b38c747ccbfef0e839709425db161) | README claims direct official-CFTC retrieval and 1986-to-present coverage; the pinned tree contains an example-output JSON rather than a historical archive, and no LICENSE file is present despite an MIT claim in the README. | Not a dataset bundle. Direct CFTC retrieval is outside this sandbox's allowed network hosts; no rows or API calls were used. |
| [`whitenoise1/RCoT@97be341a889c58b31b85387328969ba4e514de9b`](https://github.com/whitenoise1/RCoT/tree/97be341a889c58b31b85387328969ba4e514de9b) | README describes Legacy backfill from CFTC annual ZIPs to 1986 and weekly updates from the CFTC API. The tree contains software, lookup tables, and test fixtures, not a bundled historical archive; no license is declared. | Software lead only. No eligible data bundle or reuse terms; direct CFTC fetch unavailable here. |
| [`MFlab-inc/CFTC-COT@0cd9210abd6d33de13e7d17f939d2cf2f007aa54`](https://github.com/MFlab-inc/CFTC-COT/tree/0cd9210abd6d33de13e7d17f939d2cf2f007aa54) | README identifies CFTC official reports/annual ZIPs and says the repository's backfill defaults to 2005, though official Legacy ZIPs reach back to 1986. The tree contains `data/csv/gold.csv` and `data/cot-feed.json`, but GitHub reports no license and the current bundle's exact coverage, publication-vintage behavior, and immutable source snapshot are not established. No contents were read. | The checked-in/default archive is not shown to cover the required pre-2000 slice; rebuilding from the official CFTC host is outside this sandbox's allowed network hosts. Not admitted pending rights, pinned provenance, coverage, and point-in-time release controls. |
| [`Garrincha077/cot-atlas@158764fdf3e63bf452f6875b16079af6f1cf9359`](https://github.com/Garrincha077/cot-atlas/tree/158764fdf3e63bf452f6875b16079af6f1cf9359) | The repository describes a CFTC-sourced multi-decade archive and first-observed report vintages. Its README also contains unrelated empirical COT/price-study outcome summaries that were incidentally visible during metadata triage. | Quarantined from candidate selection and validation; none of its outcome summaries or data are used. No archive or price rows were opened. |

## Additional source-search exclusions

| Source | Metadata-only finding | Decision |
|---|---|---|
| `yydsdefi-cmyk/COMEX-Gold-Tracker` | README describes 26 archived official-CME gold-stock reports for activity dates 2026-08-28 through 2026-10-05. The repository has no declared license and does not establish pre-2000 coverage. | Recent warehouse-stock observations are not an eligible historical gold-price or COT series; no report contents were opened. |
| `axb0306/cme-futures-ohlc` | README identifies TopstepX API as the source; visible file names cover March–April 2026 and GitHub reports no license. | Not an eligible pre-2000 source. Its README's generic MNQ sample row was incidentally visible during triage but was not ingested into an analysis or used; no gold data or holdout was accessed. |
| `MOHAMED-EL-HADDIOUI/Gold-Futures-Historical-Data-Analysis-and-Prediction` | Tree contains a gold-futures CSV, but no verified license, source lineage, point-in-time vintage, or eligible date coverage was established from repository metadata. | Excluded; the CSV was not downloaded or opened. |

## Further COT archive search — metadata only

| Source | Metadata finding | Decision |
|---|---|---|
| [`edulongo18/cftc-cot-data-archive@71fedc343b685c350b861ea8c3ae7edef5fc3d1f`](https://github.com/edulongo18/cftc-cot-data-archive/tree/71fedc343b685c350b861ea8c3ae7edef5fc3d1f) | File names show annual workbooks and Disaggregated-report ZIPs for 2020–2026; no license is declared. | Post-2000 archive only; not eligible for the frozen pre-2000 discovery/development path. No contents opened. |
| [`hikarus211/cot-data@91dd6a5d403d2f3c43aa73350f6fbf065b59446e`](https://github.com/hikarus211/cot-data/tree/91dd6a5d403d2f3c43aa73350f6fbf065b59446e) | Auto-updated CFTC mirror with visible weekly files for 2026; no license is declared. | Current-year mirror, not pre-2000 coverage. No data rows opened. |
| [`Gembot-ai/cot-data-visualization@791a6e0a6255a2df918b798d06b84f48c7d083fe`](https://github.com/Gembot-ai/cot-data-visualization/tree/791a6e0a6255a2df918b798d06b84f48c7d083fe) | Repository description claims 19 years of CFTC history, but the pinned tree has no CSV/Excel/Parquet archive and GitHub reports no license; the exact source, date range, and vintage handling were not established. | Application/software lead only; not an auditable pre-2000 dataset. |
| [`ghler/CFTC-cot-weekly@bb04f5fae7f65a8a3714fe6a4581b20fc52be6ad`](https://github.com/ghler/CFTC-cot-weekly/tree/bb04f5fae7f65a8a3714fe6a4581b20fc52be6ad) | Tree includes a database and workbook but has no declared license or source/coverage manifest; it also contains mixed agent/session artifacts. No database or workbook contents were opened. | Excluded pending provenance, rights, and clean data lineage. |

The `MFlab-inc/CFTC-COT` README and backfill script set the default start year
to 2005 while noting that official CFTC Legacy annual ZIPs extend to 1986.
Reaching the earlier period requires fetching directly from `cftc.gov`, which is
outside the sandbox's allowed network hosts. No CFTC data files were fetched.

## Gate to any next experiment

A suitable source must establish, before feature inspection, (1) rights to use
the source for this research, (2) gold coverage of the frozen pre-2000
selection/development partitions, (3) original source lineage and extraction
hashes, (4) point-in-time report/release dates or futures settlement timing,
and (5) revision/vintage behavior. Then freeze one genuinely distinct
hypothesis and runner. The CMR, Brent, commodity-breadth, FX-dispersion, and
CPI/inflation-gating families remain closed; no substitute basket or parameter
variant is authorized on reused partitions.
