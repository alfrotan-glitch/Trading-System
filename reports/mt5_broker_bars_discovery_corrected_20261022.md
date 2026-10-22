# XAUUSD@ MT5 M15 broker-bar discovery (2026-10-22)

**Disposition: DISCOVERY ONLY. No validated edge, no promotion, no orders.**

Corrected v2 run. The original v1 HAC statistics are superseded and retained unchanged for traceability.

Input rows: `29987`; SHA-256: `0dfd3025fb6b3fc636d8531b22ab30640f45f7bfa344136ce181f29e76adbab2`.
Observed intervals longer than 15 minutes: `328`; maximum: `4395.0` minutes.

Signals were evaluated at a completed-bar close and applied at the next observed bar open. Missing bars flatten the position before the next observed bar; no unknown gap return is credited. Costs are assumed price distances per side, not broker measurements.

HAC statistics use the daily difference between compounded strategy and control returns; intrabar active-return differences are not compounded as a separate portfolio.

| Hypothesis | Discovery t (cost 0.30) | Validation t | Holdout t | Holdout Sharpe |
|---|---:|---:|---:|---:|
| H-MT5-TREND-12 | -1.256040783557026 | 0.642395467867598 | -1.903960624547026 | -3.4831800922720615 |
| H-MT5-REVERT-4 | -4.267279102730175 | 0.18194134117056204 | -1.634074513341427 | -5.099931017627763 |
| H-MT5-BREAKOUT-32 | -1.168872587860918 | -1.023658993141319 | -0.771632734697933 | -1.5138970485434957 |
| H-MT5-SESSION-MOM-4 | -1.7041622974583577 | -0.9560497243721465 | -1.321499853263189 | -2.989149085497852 |

The broker OHLC export does not contain executable bid/ask event history, fill prices, commission, slippage, or swap evidence. The `spread` field is broker points and was not converted. These results cannot support a profitability claim or a DEMO/LIVE decision.

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
