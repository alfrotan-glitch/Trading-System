# Gold Robot acceptance checklist — latest main source

**Decision: NOT RELEASED.** The current EA is not demonstrated profitable. LIVE trading stays locked.

## Engineering evidence

- [x] Canonical MQL5 EA and order-receipt include are versioned in `main`.
- [x] Fail-closed REAL account prohibition and research-only strategy gate are present.
- [x] Old `10009` pending receipt defect has a tested correction.
- [x] Planned losses are capped against 1–2% per-trade risk AND the remaining daily loss allowance before submission.
- [x] Installer has rollback and source checksum tests.
- [x] Python and static-source regression checks are exercised in GitHub CI.
- [x] Native tester configuration supports separate $100/$200 reports and rejects stale installed EX5 binaries.

## Still REQUIRED for the CURRENT MQL5 revision

- [ ] Clean MetaEditor compilation of the current `main` EA and include (not the older M15 build).
- [ ] Native real-tick runs with genuine $100 and $200 deposits; evaluate minimum lot and margin vetoes.
- [ ] Specific M5 and retest-LIMIT execution comparisons using the EA input settings actually loaded by Strategy Tester.
- [ ] Broker-verified spread/commission/slippage/swap and realistic stop gaps.
- [ ] Multiple independent after-cost strategy validation periods, with positive net expectancy and robust drawdown.
- [ ] Connected DEMO restart, connection-loss, partial-fill and order-cancellation fault injection.
- [ ] Clear one-click customer workflow and release packaging after all gates pass.

## Historic results are not current acceptance

An older M15 source compiled and was tested on 2025 broker-cache ticks at a $10,000 simulated deposit; six months produced 18 completed trades and negative net expectancy. The newer M5/retest/fee/daily-budget source has **not** been natively compiled or proven profitable. A green GitHub Python test is not evidence of executable MQL5 correctness, reliable fills, or a positive trading edge.
