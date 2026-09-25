# 8. Live Trading Governance

## The Live Trading Boundary

In QTS, live trading with real capital is structurally locked behind formal governance protocols. Live trading is **never** accessible through UI toggles, configuration file flags, or automated threshold triggers.

$$\text{REAL\_CAPITAL\_EXPOSURE} \equiv \$0.00 \quad \text{(Invariant)}$$

---

## Governance Prerequisites for Live Consideration

Before live real-money execution can even be proposed for governance review, five mandatory operational layers must be satisfied with immutable cryptographic evidence:

### 1. Preregistered Research Validation
- The trading hypothesis must be preregistered before running against out-of-sample data.
- Must demonstrate a statistically significant edge after Deflated Sharpe Ratio (DSR) penalties and Holm multiple-testing adjustments.
- Must show parameter stability across walk-forward partitions without regime breakdown.

### 2. Forward Demo Execution Evidence
- Strategy must complete autonomous demo execution across liquid trading sessions.
- Realized execution costs (spread capture, slippage, latency) must fall within pre-registered policy assumptions.
- 100% clean reconciliation history with zero unexplainable drifts or missing positions.

### 3. Identity & Venue Pinning
- Broker account must be verified as a live account under the operator's legal identity.
- Venue credentials and terminal path must be cryptographically pinned and owner-confirmed.

### 4. Multi-Signature Authorization Artifact
- A formal cryptographic authorization artifact must be committed to the repository:
  - Specifying exact allowed symbols (`XAUUSD`).
  - Specifying hard maximum capital allocation and daily loss limits.
  - Specifying maximum allowed order sizes.
  - Signed by the account owner and risk supervisor.

---

## Authorization Revocation

Safety is additive and immutable:
- **Instant Revocation:** Any operator or risk officer can revoke execution authority at any time:
  ```bash
  qts demo revoke --reason "Operator manual revocation"
  ```
- **Sidecar Architecture:** Revocations write an append-only sidecar record with timestamps and signatures. Historical authorization artifacts are never deleted or modified in place, maintaining a clean audit trail.
