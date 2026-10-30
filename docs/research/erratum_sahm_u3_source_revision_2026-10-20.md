# Erratum — Sahm/U-3 source revision identity

**Recorded:** 2026-10-20, after the single preregistered screen had been rejected.
**Scope:** source-revision metadata only. No candidate parameter, feature, outcome, or trial count is changed.

## Correction

The frozen Sahm/U-3 preregistration and initial run metadata recorded the U-3 mirror revision as:

`pmichaillat/feru@23d5e7795325ce1a69d02bd52e20ad075983082e`

That 40-character SHA does not resolve to a commit in GitHub. The correct commit is:

`pmichaillat/feru@23d5e7795325ce1a69d02bd52e20ad075983082a`

A GitHub API metadata/tree check at the corrected commit confirms that `raw/UNRATE.csv` exists there with Git blob SHA-1 `3e09b6924c5a010da67ffc2e850f9331bd7cdb4b` and file size 13,797 bytes. This is the same blob SHA-1 recorded in the frozen protocol and run evidence. Git blob identity fixes the file contents; the previously recorded file SHA-256 is `c3be736b31e2ea488076b46190efbfa1762ea0bdf6171e92585e710523840a78`.

This correction used only the GitHub commit and tree metadata. It did **not** fetch or parse the CSV, access any U-3 numeric value, recompute the file SHA-256, rerun the screen, or inspect Gold price values or the holdout. The frozen preregistration file is intentionally left unchanged so its original SHA-256 (`160a2babca41d9f9cf0886d9ece8921b284bdb00ab0bfd38dffcd6751936d73d`) remains stable; this erratum supersedes only its misspelled source-commit pointer.

## Result and governance

The input content identity remains fixed by the recorded Git blob and SHA-256. No input rows, features, or outcomes were changed or recomputed. The Sahm/U-3 candidate remains **REJECTED** and closed; do not tune or rerun it. `N_TRIALS` remains **362**. No post-1999 Gold prices or locked holdout data were accessed. `strategy_promoted=false`, `orders_submitted=0`, and `LIVE=LOCKED` remain unchanged.

The runner and source-metadata constant now point to the resolvable commit, and the result evidence records this metadata correction explicitly. See `data/evidence/longhistory/sahm_u3_gate_discovery_dev.json` and `docs/research/sahm_u3_gate_results_2026-10-20.md`.
