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

## Audit outcome

Awaiting independent metadata-only runner evidence. Until then the discovery
view and separate H-DIR execution boundary are **NOT VERIFIED** and H-DIR-01
remains **NOT RUN**.
