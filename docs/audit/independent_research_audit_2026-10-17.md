# Independent Research Audit — Long-History XAUUSD Programme

Date: 2026-10-17. Auditor role: independent of the cycle authors (same-session
audit pass over committed artifacts, code and git history). Scope: the six
gated long-history cycles (daily 2026-10-10 → VOLM 2026-10-17), the 337-trial
ledger, preregistration discipline, data provenance, execution accounting,
cost basis, selection bias, and out-of-sample integrity.

Overall: **no material defect found.** One material *risk finding* (F-1,
financing) that conditions the champions' interpretation until broker swap is
measured. Three cosmetic/documentation defects, all repaired.

## 1. Trial ledger (multiple testing) — PASS

Scripted recount from the protocol modules reproduces the chain
26 → 40 → 47 → 50 → 72 → 149 → 193 → 237 → 262 → 285; Waves 6–8 discovery
increments (+22/+20/+10) bring the count for any future cycle to **337**.
Each cycle's `N_TRIALS` is computed by importing the previous protocol's
count (no hand-edited ledger), and every committed final's recorded DSR
`num_trials` matches its cycle exactly. This is now enforced by
`tests/unit/test_longhistory_trial_ledger.py` (22 tests, in CI).

## 2. Preregistration discipline — PASS (one observation)

Git archaeology: for all five 2026-10-17 cycles the preregistration document
was committed before the final evidence file (timestamps and ancestry
checked). Candidate manifests: the set of candidates evaluated in every
final equals the preregistered `CANDIDATES` with role `CANDIDATE` exactly;
the Bollinger `m_boll20_2` control is evaluated separately by design, and
the only null-cid rows are walk-forward fold aggregates. No unregistered
candidate was ever evaluated; no evaluated candidate was dropped silently.

Observation O-1: for the 2026-10-15 monthly cycle the original freeze commit
(`67e2621`, attested in ARCH-061) is not retained in this clone's object
store after branch consolidation, so its freeze-before-final ordering rests
on the contemporaneous ARCH record rather than re-verifiable history.
Mitigation going forward: keep freeze commits reachable (no squash of
research branches) — PR #23 is a merge, so its freeze history stays
auditable.

## 3. Execution accounting — PASS

The pre-v2 engine's fraction-of-current-equity marking (which silently
resized positions and omitted fills) was found and replaced earlier
(ARCH-060, `fixed_units.v2`). An independent stdlib+numpy reimplementation
sharing no code with the engine reproduces both frozen champions on the
evaluation window to 0.001% (`scripts/verify_champions_independent.py`,
verdict AGREE, `data/evidence/longhistory/champion_independent_verification.json`).

## 4. Costs — PASS with material finding F-1

All research costs are ASSUMED and labelled as such; break-even multiples
vs the 3+1 bps + $7/lot base exceed 50× for both champions, and 2×/3× stress
is inside the frozen gates.

**F-1 (material): G9's financing assumption is broker-fragile.** The frozen
G9 variant charges a symmetric 0.25 bps/day. Re-costing the frozen champions
post-hoc (no re-selection; `champion_financing_sensitivity.json`):

| financing (bps/day) | ts9_lo net | veto9 net |
|---|---|---|
| 0 (base) | +70,989 | +49,897 |
| 0.25 (frozen G9) | +59,931 | +39,392 |
| 0.5 | +50,378 | +30,725 |
| 1.0 | +34,995 | +17,675 |
| 2.0 | +14,958 | +2,760 |
| 3.0 | +3,822 | −4,129 |

Financing break-evens ≈ **3.3 bps/day (`ts9_lo`)** and **≈2.4 bps/day
(`veto9`)** (1 bp/day = $20/lot/night at $2,000 gold). Retail swap_long
schedules for XAUUSD can plausibly exceed the `veto9` break-even, i.e. at a
swap-heavy broker `veto9` — and at ≳3.3 bps/day also `ts9_lo` — would fail
G9 despite passing at the assumed rate. The engine's symmetric bps model
also cannot express directional reality (shorts are often *paid*
swap_short). Consequence: the champions' financing-charged results must not
be quoted without the broker's measured swap; measuring `swap_long`/
`swap_short` is the first step of the Windows runbook (Section 8.1) and is
now supported read-only by `qts demo symbol-terms`. Until then the
financing legs of G9 remain ASSUMED.

## 5. Selection bias & holdout integrity — PASS

Deflated Sharpe uses the cumulative trial count at each cycle (Section 1);
Holm adjustment and bootstrap intervals are in the finals. The 2000–2026
evaluation window was knowingly reused across the 2026-10-17 cycles and is
disclosed as such in every protocol, with the DSR denominator absorbing the
reuse; no gate threshold was moved between cycles (G1–G9 text identical in
all preregistrations). Post-hoc temptations were refused and documented
(lookbacks 10–11 m not adopted; extension gate rejected after episode
attribution). Discovery partitions (≤1989 monthly; 2004–2009 weekly) were
never used for gating decisions about the evaluation window.

## 6. Data provenance — PASS

Gold: World Bank Pink Sheet monthly via `datasets/gold-prices@f6e9761`
(PDDL). USD index: Fed H.10 via pinned mirrors. CPI (Wave-8): BLS CPI-U NSA
via `datasets/cpi-us@dceeb87` (PDDL), anchor values verified against BLS
publications. Cross-checks on file: BaseMax monthly replicate (corr 0.9978),
Pink Sheet mirror gold cross-validation (corr 0.99999989, 624 months).
Clarification recorded: `datasets/gold-prices` is the *same* upstream as the
primary series and must not be cited as an independent source; a genuinely
independent licensed long-history source remains an open blocker.

## 7. Defects found and repaired

- D-1 (documentation): two handbook edits in ARCH-067/068 silently failed to
  persist while the ARCH entries claimed them; content restored and
  grep-verified (`d3c51fe`). All subsequent edits are verified on disk.
- D-2 (cosmetic): intraday/seasonal/reversal protocols compute `N_TRIALS`
  without exposing `N_TRIALS_INHERITED`; values hand-verified (40/47/50).
- D-3 (cosmetic): CLI refusal message pointed at a non-existent runbook
  path; corrected, and the adapter's unrealized-swap flag now covers all
  non-points swap modes (test-covered).

## 8. What this audit does not do

It does not re-litigate the frozen verdict (`NO_VALIDATED_EDGE`), does not
re-run or re-tune any candidate, and does not convert ASSUMED costs into a
claim. Its actionable outputs are: measure broker swap before quoting
financing-charged performance (F-1), keep future freeze commits reachable
(O-1), and let the ledger test veto any future hand-edited trial count.
