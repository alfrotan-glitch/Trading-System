# XAUUSD@ MT5 M15 broker-bar discovery (2026-10-22)

**Disposition: DISCOVERY ONLY. No validated edge, no promotion, no orders.**

Input rows: `29987`; SHA-256: `0dfd3025fb6b3fc636d8531b22ab30640f45f7bfa344136ce181f29e76adbab2`.
Observed intervals longer than 15 minutes: `328`; maximum: `4395.0` minutes.

Signals were evaluated at a completed-bar close and applied at the next observed bar open. Missing bars flatten the position before the next observed bar; no unknown gap return is credited. Costs are assumed price distances per side, not broker measurements.

| Hypothesis | Discovery t (cost 0.30) | Validation t | Holdout t | Holdout Sharpe |
|---|---:|---:|---:|---:|
| H-MT5-TREND-12 | -1.2706888200135669 | 0.6362335522140694 | -1.9077751266661649 | -3.4831800922720615 |
| H-MT5-REVERT-4 | -4.308560432420532 | 0.18917829088716462 | -1.612528915154339 | -5.099931017627763 |
| H-MT5-BREAKOUT-32 | -1.171231681821867 | -1.02315147935678 | -0.7717329697600775 | -1.5138970485434957 |
| H-MT5-SESSION-MOM-4 | -1.7020556938398903 | -0.9557687915078386 | -1.3296855555329306 | -2.989149085497852 |

The broker OHLC export does not contain executable bid/ask event history, fill prices, commission, slippage, or swap evidence. The `spread` field is broker points and was not converted. These results cannot support a profitability claim or a DEMO/LIVE decision.

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
