# H-DIR-01: search for an independently authenticated Discovery-only source

**BLOCKED — NO AUTHENTICATED DISCOVERY-ONLY VIEW**

H-DIR-01 remains **NOT RUN**. This is a source-availability investigation, **not**
a measurement or a new research design. No Parquet quote member, raw quote
payload, or held-out row was opened, decoded, scanned or inspected for this
search; no canonical ZIP was downloaded or modified. GitHub API queries used
release/commit/tree/artifact/cache *metadata*, not artifact contents. Local
inspection used file names, sizes, safe acquisition/source manifests, bounded
provenance fields and already published aggregate reports. The earlier
[manifest-only audit](xauusd_discovery_boundary_audit.json) is separate and
had already established the mixed-part boundary without opening quote members.

## Locked source and the missing 50,716 rows

- Canonical release `dataset-xauusd-730d-20260919`, asset
  `XAUUSD_730d_20260919T114013Z.zip`, SHA-256
  `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723`.
  Acquisition manifest SHA-256
  `d9a61ad583002c6e24f2ad04aee6399e6ec00a9a47928712a7c3f4418e15972f`;
  full dataset digest
  `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`.
  These identify the **full** archive/ledger, not a Discovery-only prefix.
- Discovery is exactly the first **70,834,426 original rows**, with raw
  `time_msc < 1764563969254`; original held-out starts at row **70,834,426**
  and comprises **69,096,545 rows**. Those row/time facts come from the
  previously published full inventory, not a held-out read in this search.
- The original `part-000441.parquet` spans global rows
  `[70,783,710, 70,916,415)` and contains **50,716 required Discovery rows**
  followed by **81,989 held-out rows**. The acquisition manifest has a SHA-256
  of that *whole* part, but no SHA-256/checkpoint for its Discovery prefix,
  separate prefix copy, page/row-group sidecar index or per-part time bounds.
  The member is ZIP-compressed. Opening it even to investigate its inner footer
  or slice the prefix is disallowed; this search did neither. Omitting its
  Discovery rows would silently change H-DIR-01's population.

## Search record (2026-09-23)

| Surface inspected **without quote-payload access** | Finding relevant to an exact, authentic prefix |
| --- | --- |
| Current repository and ignored/local file names (`git ls-files`, `find`, manifest metadata) | No `data/raw/mt5_ticks/` source, `data/raw/xauusd_discovery_view/`, view authority or 730-day tick prefix. The one local curated Parquet is a **500-row synthetic 1H** fixture per `data/manifests/manifest_20260923-010+7f568197-572728d9.json`, not canonical MT5 ticks; it was not opened. Local SQLite stores are tiny compared with 70.8 million raw ticks. The forward-observatory manifest reports 13,222 observations dated **2026-09-18**, after the locked cutoff; its DB was not opened. |
| Git and GitHub history | Checkout is shallow (seven reachable commits), so checked GitHub's commit/tree **metadata** instead of trusting the shallow log. Examined every one of **61 ancestors dated on/after 2026-09-19** on this branch via recursive Git tree API (none truncated), plus all **12 remote branch tip trees**. No committed `data/raw/`, tick Parquet/ZIP, index, discovery-view or pre-split source was found. An older branch has three small manifests dated 2026-09-16, not this 730-day source. No Git blob containing quote rows was fetched. |
| GitHub Releases and archive member inventory | The release lists **one** asset, the canonical ZIP. The prior [ZIP inventory](canonical_zip_inventory.json) lists only **734 original Parquet parts plus `manifest.json`**, with no independent index or partition. Neither a release sidecar nor an authenticated Discovery-prefix asset exists in the accessible release metadata. |
| GitHub Actions runs, retained artifacts and caches | The Actions API lists **nine runs**, only **two retained artifacts**: both ~1 KB `xauusd-discovery-boundary-audit` metadata reports from the manifest-only runs (IDs `35855849224`, `35856015114`). The Actions cache API reports **zero caches**. Prior full-scan jobs used the ZIP on ephemeral runners and published bounded reports, not a reusable discovery quote dataset. No artifact/cache was downloaded. |
| Published acquisition outputs, manifests and research reports | Original acquisition writer (`src/qts/data/mt5_history_acquisition.py`) persisted **one Parquet per chunk**, no redundant serialization; its ledger hashes only whole parts. The local acquisition report (`data/evidence/mt5_history_acquisition.json`) says `MT5_PACKAGE_UNAVAILABLE` and contains no windows or rows. Published XAUUSD reports record the canonical full-file digests, discovery **counts** and aggregate outcomes, not a per-row prefix digest or the bid/ask/time/order sequence necessary for H-DIR-01. The earlier verified gap disposition identifies the full dataset and manifest, not a boundary-prefix source. |
| Alternative feeds and local caches | The Dukascopy material is 15-minute **bar** data from another feed/venue, not the original WM Markets MT5 tick order and bid/ask stream. The public tick-source assessment explicitly reports `DATA_BLOCKED` / no tick payload obtained. Workspace/home cache names and temporary-test paths showed no independent 730-day Discovery view. No alternative feed or cache was opened as quote data. |

The source-side Windows acquisition path described in the gap evidence is
`data\\raw\\mt5_ticks\\XAUUSD_\\730d__20260919T114013Z` on the original
operator machine, **not** a separate published Discovery-only export. The
acquisition design says Parquet is the *single* raw representation. An
unverified remote machine might have other private data, but it is not an
available, authenticated view here; the known original boundary part is mixed
and remains closed.

## Can an independent source safely produce this exact view now?

**Not on the available evidence.** A new broker-side query restricted to
Discovery time would avoid asking for held-out quotes, but no such independently
persisted snapshot is available here, and the canonical ledger contains **no
hash/proof of the first 50,716 rows inside the mixed part**. Matching its
request dates, total count or aggregate statistics cannot establish byte-for-
byte equality, original quote order or unchanged bid/ask/time fields; a
broker's historical response may change. Validating a re-query against the
mixed original part would require opening that prohibited part. Copying only
previous whole parts loses 50,716 required rows. Dukascopy, the 500-row
synthetic 1H fixture and post-cutoff observation are different populations;
none can fill or authenticate the gap. Do not infer or invent those rows.

**Access/enforcement:** A complete, independently pinned Discovery-only view
was not found and could not be established without breaking the rule. There is
no `docs/xauusd_directional_view_authority.json` and no Discovery-only view to
mount; therefore an H-DIR-01 runner with demonstrably exclusive access to
that view **cannot be provisioned or verified**. The existing runner's missing-
authority gate refuses to start. A future candidate would need immutable
source identity and per-row-order provenance **including the boundary prefix**,
its independently checked checksum, exactly 70,834,426 unchanged original rows
below the locked cutoff, and physically restricted access to *only* that
verified view. None of those missing proofs may be replaced by a changed
cutoff, reduced population, new feed, or a read of the mixed member.

**Decision: BLOCKED — NO AUTHENTICATED DISCOVERY-ONLY VIEW.** H-DIR-01 is **NOT
RUN**; no quote rows were read in this investigation, no held-out data was
accessed, no canonical ZIP or hypothesis was changed, and no promotion, Demo
execution or orders occurred. Stop here unless genuinely new, independently
authenticated Discovery-only source evidence becomes available.
