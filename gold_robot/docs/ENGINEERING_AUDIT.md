# QTS Gold Robot - Initial Development: engineering status

The canonical EA is `mt5_robot/QTS_Gold_Robot.mq5`; its receipt policy is in
`ExecutionPolicy.mqh`. The single root installer deploys both transactionally.
The former duplicate package is preserved only as `evidence/legacy_package_20261024.zip`.

The confirmed incident is reproduced in the pre-change MT5 journal: at
2026-01-06 10:15, a BUY LIMIT at 4453.95 returned `sent=1, retcode=10009,
order=2, deal=0`. The old EA latched a rejection and immediately cancelled it.
The corrected policy accepts 10008/10009/10010 with a valid order ticket,
classifies explicit ticket-free rejections separately, and treats timeouts or
contradictory replies as unresolved. A receipt never increments a fill count.
Twelve native MQL policy cases passed. Native execution evidence is in the
performance report and `evidence/native/`.

New controls include a flushed write-ahead submission marker, bounded
cross-chart protective retries, terminal-book/history reconciliation for
cancellation races, residual partial-close management, broker-deal replay on
restart/reconnection, isolated tester ledgers, and reconstruction of realized
daily losses before creating a missing daily baseline. Daily and peak risk
latches remain durable. Unknown submissions never get automatically replayed.

Limits remain: no verified historic midnight floating equity when first attached
late; no guarantee against gap losses; one terminal and an isolated DEMO account
are required. Shared manual/netting exposure can race with a pending fill.
Broker corrections to existing historical deal rows require comparison against
broker statements. A restart/disconnect/partial-fill fault-injection campaign on
a connected demo broker has not been completed. No fill-probability or queue
model is certified. Pending prices are intentionally immutable: changed signals
wait for expiry/cancellation rather than chasing the market or widening stops.

The strategy-evidence gate currently permits research only inside Strategy
Tester. It is separate from DEMO-only enforcement and cannot be bypassed with
EnableDemoOrders. Fifteen strategy families have failed the evidence gate; see PERFORMANCE_REPORT.md for independent follow-up and sample limitations.
Read PERFORMANCE_REPORT.md before interpreting engineering progress as an edge.

Official contracts used for the execution fix:
- https://www.mql5.com/en/docs/trading/ordersend
- https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
- https://www.mql5.com/en/docs/event_handlers/ontradetransaction

