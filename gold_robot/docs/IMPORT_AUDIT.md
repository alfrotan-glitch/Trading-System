# QTS Gold Robot source import audit — 2026-10-25

## Scope and provenance

29 source/test/documentation files were supplied in a Windows export ZIP. The local export manifest was excluded from this PUBLIC GitHub source snapshot because it contains an absolute user-specific Windows path. All primary EA, receipt, installer and Python research scripts were retained under a distinct `gold_robot/` directory to avoid overwriting the existing QTS platform code.

## Audit findings

- The local snapshot had 46 passing tests and three failing tests, all because the export omitted `README.txt`, `docs/RELEASE_STATUS.json`, and `docs/SOURCE_CHECKSUMS.json` (plus its absent compiler log dependency). Those source/package metadata files were recreated with current truthful development status. Do not interpret a green source-check suite as a successful native MetaEditor compile.
- A hard-coded broker DEMO login was found in `research/RunNativeValidation.ps1`. It was removed; pass `-DemoLogin` locally if needed.
- `RiskPerTradePct` previously rejected values above 1.0%; the tester-only configuration ceiling was increased to the owner's explored 2.0%. **The default remains 0.25%** to avoid silently changing all historical backtest assumptions. This is not a broker-enforced or slippage-proof stop-loss cap.
- RewardToRisk is currently a *minimum* structural ratio of 1.7; structural Take Profit can be far from entry. No adaptive near-TP win-probability research is validated. Do not claim a 100% or near-certain TP reach rate.
- 136 accepted LIMIT orders and 18 filled trades in the January–June 2025 native report (13.2% fill ratio); native PF 0.98 and native net -$5.54 before additional hypothesized costs. These were on a simulated $10,000 account; they are not representative $100/$200 account results.
- `docs/PERFORMANCE_REPORT.md` records at least 15 tested strategy families without confirmed positive out-of-sample edge.
- The exported archive lacked the large `evidence/` directory and cached ticks; historic numeric claims in its report cannot be independently reproduced from this source snapshot alone.
- Real-money trading remains disabled by account-type checks. New non-tester DEMO order entry is also gated off by `StrategyEvidenceApproved()`; live DEMO lifecycle has not been independently verified.

## Required before operation

1. Recompile the exact imported source in local MetaEditor and capture zero warnings/errors as external local evidence; update release metadata only after verification.
2. Reproduce native real-tick tests using appropriate actual $100 and $200 tester deposits and verified WMMarkets symbol min-lot/margin/fees, including rejected trades and gap risk.
3. Reconcile native and offline research results; obtain sufficient independent after-cost evidence before declaring any edge or turning on autonomous entries.
4. Verify restart, disconnect, duplicate pending receipt, and partial-close lifecycle on connected DEMO.
5. Only after these checks, select an evidence-backed TP and risk policy. The implemented max input is a research ceiling, not a recommendation to use 2% routinely.

**Status:** Imported source baseline, NOT RELEASED, no proven trading edge, not ready for real-money operation.

## Subsequent experimental revision (2026-10-25)

The original 0.25% default and older 1.7R requirement described earlier in this audit refer to the imported source **before** the new intraday research revision. Current experimental source defaults are 1.0% budget, 1.0R, $10/lot assumed commission, 0.10 gold-price-unit stress allowance and explicit min-lot/margin veto. These are not calibrated to verified live WMMarkets costs and are NOT production recommendations. See INTRADAY_DESIGN.md.
