# 4. Operating QTS

## Operator Mental Model

QTS is designed to be operated with clarity and confidence. The system evaluates the fail-closed pre-trade gate, tracks broker state, and says what is happening and what to do next. It does not claim a validated trading edge.

---

## 1. Reading the Home Screen

When opening the QTS Workstation (`#/home`), the first screen answers five essential operational questions in plain language:

1. **What is happening?**
   - **System status and account:** The hero states the overall state in plain language (e.g. *Ready*, *Connect your Demo account to get started*, *Trading is temporarily stopped*), and the Demo account card shows whether MetaTrader 5 is connected. Gold appears on the Market page only when fresh — otherwise it says *Current price unavailable*.
2. **Is there an opportunity?**
   - **Trading opportunity:** Reports whether a validated strategy exists. QTS is certified `NO_VALIDATED_EDGE`, so Home reads *“No validated trading opportunity right now.”* — nothing is invented.
3. **Can QTS trade right now?**
   - **Status and next action:** The hero action points at the single required step (e.g. *Connect account*, *Continue setup*, *Start a trade*). The full readiness checklist and verbatim authority state live on the Trading page under Technical details.
4. **Is any real money at risk?**
   - **Your money:** Always *“Not at risk”* — Demo account only, Live stays locked, `REAL_CAPITAL_EXPOSURE = 0`.
5. **What should I do next?**
   - **One primary action** in the hero, always reflecting the current state.

Engineering internals (raw guide snapshot, stage/authority state, diagnostics) remain reachable under **Advanced** and the **Technical details** disclosures — they inform, but never override what the backend enforces.

---

## 2. Daily Operating Workflows

### Workflow A: Market Observation (Zero Risk)
1. Navigate to **Advanced $\rightarrow$ Recorded observations** (`#/advanced/data-observations`).
2. Click **Start Observation**.
3. Accepted quotes are stored in the machine-local observatory database under the state root (`data/sqlite/forward_observatory.db`), not in the repository checkout. A manifest is written beside the other state artifacts.
4. Observation cannot submit an order. Starting it does not grant trading permission.

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
5. Inspect active positions and order journals via the web workstation at **Advanced $\rightarrow$ Order history** (`#/advanced/trading-history`).

---

## 3. Emergency Stops & Recovery

### Raising the Kill Switch
If unexpected broker behavior, latency spikes, or network anomalies occur, raise the durable kill switch:
- **Web UI:** Header button **Stop trading**. It asks for confirmation, then calls `POST /api/demo/kill`. If the request fails, the screen says the stop was not confirmed. It does not close an open broker position.
- **CLI:**
  ```bash
  qts demo kill --reason "Operator manual intervention"
  ```
The stage machine halts, preventing further order submissions. Closing an open position is a separate command (`qts demo close`).

### Clearing the Kill Switch
Clearing the kill switch requires deliberate explanation and confirmation:
```bash
qts demo clear-kill --reason "Investigated and cleared" --confirm
```
Note: Clearing the kill switch leaves the stage in `HALTED`. To resume trading, explicit re-arming (`qts demo arm`) is mandatory.
