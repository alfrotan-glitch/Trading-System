# Market-data source follow-up — 2026-10-19

**Disposition:** no new research-eligible source admitted. This is a source
feasibility review only: no candidate was preregistered or tested, and the
long-history denominator remains `N=359`. `LIVE` remains locked; the 2000+
price window and locked 730-day holdout remain untouched.

## Scope

Reviewed public GitHub metadata, README/source documentation, and pinned tree
paths only. No market-data rows, numerical prices, feature values, or candidate
outcomes were opened or calculated. No source files were downloaded into this
repository.

## Source leads and disposition

| Source | Metadata/provenance finding | Decision |
|---|---|---|
| `rsvp/fecon235` | The user clarified that this repository retrieves FRED (and specialized Quandl) data through APIs and does not bundle a usable historical market-data series beyond a test fixture. | Excluded as a data source. It is retrieval code, not a pinned, locally auditable historical dataset; no API call or data fetch was made. |
| [`unbalancedparentheses/forex-centuries@f79a85bf6ae0dbad8d79ea56902caef43c7bd947`](https://github.com/unbalancedparentheses/forex-centuries/tree/f79a85bf6ae0dbad8d79ea56902caef43c7bd947) | The MIT-licensed repository README identifies an `lbma_gold_daily.csv` file and describes daily LBMA PM gold prices in USD/GBP/EUR for 1968–2025. The README explicitly says each source dataset has its own license; it does not establish the applicable LBMA data-reuse terms. Only README metadata and the file path/size were checked; no CSV rows were opened. | Potential price-history lead, **not admitted**. Verify the official source's terms and the mirror's lineage before any use. If cleared, pre-register a distinct hypothesis and use only eligible pre-2000 prices. The 2000+ portion remains off-limits. |
| [`MohammadrezaAmani/Precious-Base-Metals-Historical-Dataset@efa7f451be871c4a28b818c2d8719cfaa1395dd8`](https://github.com/MohammadrezaAmani/Precious-Base-Metals-Historical-Dataset/tree/efa7f451be871c4a28b818c2d8719cfaa1395dd8) | GitHub reports an MIT license for the repository; its README presents the data as a Kaggle dataset and lists COMEX gold-contract JSON files, but does not establish an underlying source, historical coverage, or a separate license for the bundled observations. Only metadata, README, and file paths/sizes were inspected; no JSON data values were opened. | Excluded pending source, coverage, vintage, and data-rights evidence. The code license alone is not treated as a data license. |

## Short-rate macro source lead (not admitted)

[`OpenSourceEcon/FedFundsPlot@167fd89006994f09f482b9e3c1ad23fecf276416`](https://github.com/OpenSourceEcon/FedFundsPlot/tree/167fd89006994f09f482b9e3c1ad23fecf276416)
contains a generated `data/ffrates_2022-07-29.csv` snapshot. Its code identifies
FRED series `DFF`, `DFEDTAR`, `DFEDTARL`, and `DFEDTARU`, and supports history
from 1954-07 onward. This is a potentially usable **macro short-rate** input,
not a gold-price source, and the repo bundle makes it distinct from the
API-only `fecon235` lead. However, GitHub reports no license and there is no
LICENSE file; source-specific reuse/vintage terms have not been verified, and
the primary FRED host is outside this sandbox's network allowlist. No CSV rows
or rate values were opened. No Fed-funds hypothesis was preregistered or
measured; only eligible pre-2000 values could be used if the rights and
point-in-time handling are resolved.

## Additional rate/event-risk repository checks (metadata only)

| Source | Metadata/provenance finding | Decision |
|---|---|---|
| [`jk98190/Federal@67351b4bff62f28717bd99a4bfd0752b99720c85`](https://github.com/jk98190/Federal/tree/67351b4bff62f28717bd99a4bfd0752b99720c85) | MIT repository bundles `index_cleaned.csv` (README claims monthly 1954–2017) and a daily target/effective-rate file (2016–2026). Its cleaning notebook loads user-local source files not present in the tree; source provider, data rights, and vintage are not established. Only README/file metadata and cleaning-code references were inspected; no CSV rows or notebook outputs were opened. | Not admitted. The repository code license does not establish rights or provenance for the compiled rate observations. |
| [`dmkern03/FRED@6da570b683b6f52d48df22d70f59b600bf3366c4`](https://github.com/dmkern03/FRED/tree/6da570b683b6f52d48df22d70f59b600bf3366c4) and [`kylebrussell/fed-policy-cli@cb17c75723a36e4e13b6aef1dff62e4b4e3d9e4f`](https://github.com/kylebrussell/fed-policy-cli/tree/cb17c75723a36e4e13b6aef1dff62e4b4e3d9e4f) | MIT-licensed code repositories that fetch FRED series through the API; neither tree contains a bundled historical rate dataset. | Excluded as data sources, consistent with the API-only source constraint. |
| Caldara–Iacoviello GPR / event-risk data | GitHub repository searches did not identify a rights- and provenance-clear historical GPR bundle. A repository description for `hansoleg/garch-model-gpr` advertises an existing gold/oil/GPR study; it was quarantined based on that metadata and no contents or outcomes were opened. | No event-risk feature source admitted; no GPR hypothesis preregistered. |

## Research gate

These leads do not resolve the existing COT/price-data blocker. Before a new
COT experiment can be considered, obtain a rights- and provenance-clear CFTC
Legacy gold archive with report/release timing for the preregistered 1986–1989
discovery and 1990–1999 development periods, plus a sufficiently frequent,
rights-cleared gold price series. Freeze one genuinely distinct hypothesis
before inspecting its feature values. Do not revisit the rejected CMR, Brent,
commodity-breadth, FX-dispersion, or CPI/inflation-gating families; do not
access post-1999 price values or the locked holdout.
