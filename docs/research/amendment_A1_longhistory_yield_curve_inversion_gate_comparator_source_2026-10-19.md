# Amendment A1 — frozen comparator source clarification

**Applies to:** `LH-XAUUSD-YC-INVERSION-GATE-2026-10-19`
**Registered:** 2026-10-19, before reading H.10 values for this run or calculating any new candidate outcome.
**Purpose:** make the pre-existing `veto9` comparator's USD input explicit. This is a source clarification only; it does not change the candidate, threshold, lag, sizing, windows, costs, gates, or trial count.

The `veto9` reference is the already-frozen 9-month gold trend with a 12-month USD veto. It is built using the same pinned H.10 eight-currency input and monthly USD-index construction used by the prior long-history screens:

- Repository: `datasets/exchange-rates`
- Commit: `c023dd8b8f879610641a7391c0394c3bbb42d0f7`
- File: `data/daily.csv`
- Expected SHA-256: `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`
- Use only eligible pre-2000 observations required to construct the comparator. For rows dated 2000-01-01 or later, date/name fields may be used to skip; rate values must not be converted or used.

This is not a new FX candidate and does not reopen, correct, or rerun the rejected/inconclusive FX-dispersion hypothesis. The H.10 series is used only to reproduce the `veto9` comparator unchanged. The candidate remains the single lagged term-spread-inversion gate in the original preregistration. Candidate count remains one; `N=360` only if candidate outcomes are calculated.
