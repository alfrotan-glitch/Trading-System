# Long-history volatility-managed results — LH-XAUUSD-VOLM-2026-10-17

**Verdict: `NO_VALIDATED_EDGE`.** Claim: `none`.
Preregistration: `preregistration_longhistory_volmanaged_2026-10-17.md` ·
Evidence: `data/evidence/longhistory/volmanaged_research_final.json`

| Group | Selected | WF SR | Holdout net | Sharpe | DD | Holm | DSR (N=285) | Gates |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `vm_veto` | `veto9_fv3` | +0.251 | +43,487 | 0.624 | −38.0% | 0.009 | 0.657 | 6/9 |
| `vm_lo` | `lo9_fv3` | 0.000* | +65,084 | 0.811 | −30.8% | 0.006 | 0.917 | 5/9 |

\* eligibility artefact of the slow long-or-flat family (see ENS results).

**Conclusion: the sizing-clock hypothesis is falsified.** Sizing from
3-month realised volatility improved the ≤1989 discovery slices but
*dilutes* both champions on the evaluation window (`lo9_fv3` Sharpe
0.811 / DSR 0.917 vs the frozen 12-month base 0.837 / 0.945;
`veto9_fv3` 0.624 / 0.657 vs 0.662 / 0.752) and does not reduce drawdown
(−30.8% vs −31.0%). Faster de-risking whipsaws size in gold's
mean-reverting vol spikes. The 12-month sizing of the forward-frozen
champions stands unchanged; nothing in the forward package is altered
by this cycle. Replicate selections remain positive (+$20,379 / +$13,142).
