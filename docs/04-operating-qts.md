# 4. Operating QTS

## Operator Mental Model

QTS is designed to be operated with clarity and confidence. The system evaluates the fail-closed pre-trade gate, tracks broker state, and says what is happening and what to do next. It does not claim a validated trading edge.

---

## 1. Reading the Executive Dashboard

When opening the QTS Workstation (`#/overview`), the first screen answers five essential operational questions:

1. **What is happening?**
   - **Market Status:** Indicates whether the MetaTrader 5 IPC link is active and quotes are arriving.
   - **Quote Freshness:** Honest age of the latest broker event.
2. **Is there an opportunity?**
   - **Opportunity Status:** Summarizes whether an automated strategy candidate has passed validation. If data is incomplete or research gates are unproven, it reports `NO VALIDATED EDGE`.
3. **Can QTS trade right now?**
   - **Execution Permission:** Reports whether the stage machine is armed and authority is active (`ENABLED` vs `DISABLED`).
4. **Is any real money at risk?**
   - **Capital Exposure:** Always shows `$0.00 — LOCKED` in development, paper, and demo modes. Real capital exposure is impossible without live governance clearance.
5. **What should I do next?**
   - **Recommended Action:** A prominent action button pointing directly to the required step (e.g. *Inspect Setup*, *Start Observation*, *Review Demo Session*).

---

## 2. Daily Operating Workflows

### Workflow A: Market Observation (Zero Risk)
1. Navigate to **Market $\rightarrow$ Observations** (`#/market/observations`).
2. Click **Start Observation**.
3. The observation collector streams live venue ticks into `data/evidence/` with full provenance (bid, ask, spread, broker timestamp).
4. No orders are ever submitted during observation (`ORDERS_POSSIBLE = False`).

### Workflow B: Autonomous Demo Trading
1. Ensure the process is in `DEMO_EXECUTION` mode:
   ```bash
   qts mode declare demo_execution
   ```
2. Verify broker identity and pin the account:
   ```bash
   qts demo connectivity --pin
   qts demo connectivity --confirm-pin
   ```
3. Arm Stage 1 (Connectivity) and Stage 2 (Min-Size Orders):
   ```bash
   qts demo arm --stage 1 --confirm --risk-ack
   qts demo arm --stage 2 --confirm --risk-ack
   ```
4. Run autonomous demo execution:
   ```bash
   qts demo run --strategy DEMO-EXECPROBE-XAUUSD-V1 --confirm --risk-ack
   ```
5. Inspect active positions and order journals via the web workstation at **Trading $\rightarrow$ Execution** (`#/trading/execution`).

---

## 3. Emergency Stops & Recovery

### Raising the Kill Switch
If unexpected broker behavior, latency spikes, or network anomalies occur, trigger an immediate halt:
- **Web UI:** Click the emergency stop icon in the header or on the dashboard.
- **CLI:**
  ```bash
  qts demo kill --reason "Operator manual intervention"
  ```
The stage machine halts instantly, preventing all further order submissions.

### Clearing the Kill Switch
Clearing the kill switch requires deliberate explanation and confirmation:
```bash
qts demo clear-kill --reason "Investigated and cleared" --confirm
```
Note: Clearing the kill switch leaves the stage in `HALTED`. To resume trading, explicit re-arming (`qts demo arm`) is mandatory.
