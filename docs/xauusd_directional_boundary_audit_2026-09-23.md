# H-DIR-01 discovery access: metadata-only boundary audit — 2026-09-23

**Decision checkpoint (before accessing the release):** The H-DIR-01 test is already
preregistered in [the next-step decision](xauusd_directional_next_step_2026-09-23.md)
and remains **NOT RUN**. The approved next action is **access-boundary evidence,
not a quote measurement**. The prior aggregate inventory does not contain
individual part row counts or an independently approved discovery view. No raw
ZIP, view or view authority is available in this checkout.

## Source and permissible access

- Canonical GitHub release: `dataset-xauusd-730d-20260919`, asset
  `XAUUSD_730d_20260919T114013Z.zip`; published and previously independently
  checked SHA-256:
  `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723`.
  Expected original manifest SHA-256 from the earlier verified gap disposition:
  `d9a61ad583002c6e24f2ad04aee6399e6ec00a9a47928712a7c3f4418e15972f`.
  Original acquisition dataset digest:
  `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`.
- From previously published inventory: 139,930,971 rows in original order,
  `time_msc` 1726746013452–1789775939790; Discovery is the first 70,834,426
  original rows with `time_msc < 1764563969254` (exclusive). The remaining
  69,096,545 rows are held out. Times are *raw MT5* stamps, not a verified
  timezone/session clock.
- Repository inspection found no immutable discovery partition or separately
  published per-part/row-group index. The original acquisition ledger in
  `manifest.json` records original sequential part identifiers, row counts,
  lengths and SHA-256 digests; it does **not** record per-part raw timestamp
  bounds or Parquet row-group layout. The existing full-extraction inventory
  and scanner workflows are **not** safe ways to solve H-DIR access.
- The sandbox cannot fetch the release CDN asset. An isolated **preparation**
  Actions runner may download the archive and hash its opaque compressed
  bytes (to establish identity); read ZIP central-directory metadata and
  **open only `manifest.json`**. It must not extract, open or decode *any*
  Parquet/quote member. It uploads only the small boundary audit JSON, never
  the archive or quotes. A **different** runner, with no archive, checks and
  publishes that bounded JSON via GitHub's Contents API to this branch (the
  sandbox cannot download the Actions artifact from its CDN). Neither job
  can invoke the H-DIR runner. The archive is discarded when the preparation
  runner exits.

## Precommitted decision rule

1. Reject missing/mismatched source, manifest or dataset checksums; reject
   inconsistent ledger/ZIP metadata. Such a failure is **not** a research
   result. No unverified data is admitted into H-DIR-01.
2. Independently sum manifest part row counts in **original part order**.
   If the exact 70,834,426-row prefix ends at an immutable part boundary,
   only then assess whether unchanged complete *discovery-only* parts can
   form a separately verified, read-only view. Verify all row-group timestamp
   bounds against the cutoff and all selected part hashes. Require a pinned
   view authority, separate runner with **only** the discovery view mounted,
   and no canonical ZIP/held-out access *before* running H-DIR-01. Merely
   matching part counts does not authorize the experiment.
3. If the split falls *inside* an existing part, do **not** open that mixed
   part to look for a row-group boundary or to slice quote rows. ZIP member
   compression prevents metadata-only inspection of the inner Parquet footer
   without decompressing that member, including bytes from the held-out
   side. No independent row-group/page index was found. Stop with an
   auditable blocker, unless a pre-existing, independently authenticated
   metadata/index or safe partition is found without opening held-out quote
   rows. **Do not** rewrite/regenerate the canonical archive or silently
   change the split.

The preparation code is
[`scripts/audit_xauusd_discovery_boundary.py`](../scripts/audit_xauusd_discovery_boundary.py)
and its manifest-only workflow is
[`.github/workflows/canonical-xauusd-discovery-boundary-audit.yml`](../.github/workflows/canonical-xauusd-discovery-boundary-audit.yml).
Synthetic tests instrument `ZipFile.open` to reject opening every member other
than `manifest.json`. The expected report is a **boundary audit**, not a
trading or H-DIR-01 result. No promotion, Demo execution, order submission,
or held-out quote inspection is authorized.

## Independent audit outcome — BLOCKED (no H-DIR-01 run)

The [metadata-only Actions run](https://github.com/alfrotan-glitch/Trading-System/actions/runs/35856015114)
completed successfully at code commit `90a16333e83c60803dc48a111e11c176cc5b9cdb`.
Its archive-handling job checked the full ZIP's **opaque-byte SHA-256** against
the published release checksum, opened only `manifest.json`, checked its SHA-256
against the previous verified gap disposition, reconciled its 734-part ledger
and dataset digest, and inspected the ZIP central directory. It did **not**
open, extract or decode a Parquet/quote member. A separate publisher job with
**only the small audit JSON** committed
[`reports/xauusd_discovery_boundary_audit.json`](../reports/xauusd_discovery_boundary_audit.json)
to this branch (`de95a87ece1a7ad9847c8aee67bcb79acc21b3a4`);
report file SHA-256:
`f2864545873f98adac4f6b0bd37a806810bca580f006641e3e854efaf3df1153`.
No quote archive or derived rows were published. This report is **metadata
about the original source**, not a discovery quote view or research result.

The exact 70,834,426-row Discovery prefix **does not** end on an immutable
original part boundary:

| Original source part / row interval (zero-based) | Rows | Split |
| --- | ---: | --- |
| `part-000441.parquet`, global `[70,783,710, 70,916,415)` | 132,705 | 50,716 Discovery rows at the start; **81,989 held-out rows** at the end |

The first held-out original row is global index **70,834,426**; the last
Discovery row is **70,834,425**. The previous part, `part-000440.parquet`, is
**empty** and ends at 70,783,710. The ledger's chunk request window for the
mixed part, 2025-11-30T11:40:13.383522+00:00 to
2025-12-01T11:40:13.383522+00:00, is *not* a verified raw row-time range.
The locked raw-time cutoff remains `time_msc < 1764563969254`; original
dataset bounds and the 69,096,545 held-out row count come from the **earlier
published full inventory**, not any held-out row inspection in this audit.
Exact values of the *last Discovery row's* and *first held-out row's* raw
`time_msc` are not provided by the published metadata; the threshold and
original-row positions are exact, but we will not invent those two values or
open the held-out quote row to obtain one.

The source release contains only the ZIP; the ZIP has only 734 Parquet parts
plus the acquisition manifest. There is no separate part/row-group/page index
or immutable discovery partition in its inventory or repository tooling.
The manifest lists part row counts but no per-part raw timestamp or internal
row-group/page bounds. The [prior ZIP central-directory inventory](../reports/canonical_zip_inventory.json)
lists the mixed member as 1,112,372 compressed versus 1,185,224
uncompressed bytes: it is **ZIP-compressed**. Reading its inner footer or
selecting 50,716 rows would require opening/decompressing a member that also
contains 81,989 held-out quote rows. This is forbidden by
the agreed access rule. The metadata audit therefore cannot establish a
complete, independently verified Discovery-only view. It did not try to read
the boundary part or infer a safe row group from its request dates. There is
**no** pinned view authority and **no** view to mount into an isolated
H-DIR-01 runner. Separate-runner enforcement for a real measurement remains
**unverified, not merely inconvenient**.

**Disposition: STOP — `NO_SAFE_DISCOVERY_VIEW_FROM_IMMUTABLE_PARTS`.** H-DIR-01
is **NOT RUN / ACCESS BLOCKED**. Zero held-out quote members were opened and
zero quote rows were decoded **in this audit**; the earlier published inventory
had its own historical access. No hypothesis result, strategy promotion, Demo
execution or orders exist. Do not run H-DIR-01 by slicing/truncating the mixed
part, loosening the cutoff, skipping the missing 50,716 Discovery rows, or
replacing the canonical ZIP. Reconsider only if an independently authenticated
pre-existing index/partition can prove and provide the *complete* prefix
without accessing the mixed member's held-out rows; do not treat this as
permission to construct one by reading them.
