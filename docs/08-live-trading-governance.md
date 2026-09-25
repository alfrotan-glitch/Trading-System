# 8. Live Trading Governance

## The live boundary

Live trading with real money is locked.

- A config file cannot select `LIVE`. An unknown or live declaration fails closed.
- The desktop UI cannot write the mode, and it cannot place a live order.
- A DEMO authorization artifact cannot permit `LIVE`. `REAL_CAPITAL_EXPOSURE` must stay 0. Any other value invalidates the artifact.
- There is no multi-signature live-authorization artifact in this repository. Do not treat a document as that path.

The live readiness report (`qts.lifecycle.live_gate`) is fail-closed. A passing report is not an order, and it is not a validated edge. The product conclusion remains `NO_VALIDATED_EDGE`.

---

## What revocation actually does

`qts demo revoke --reason "..."` writes an additive revocation of the **DEMO** authorization. The original artifact is not edited. After revocation, DEMO execution is disabled by policy until a new DEMO artifact is recorded.

That command does not unlock live trading, and it does not create a live sidecar.

---

## What an operator can see

The Governance screen shows the live status returned by `/api/live/status`. Locked means locked. Eligibility, if the readiness report ever says the structural checks passed, is still not an order and still not real-money permission. Human approval is not inferred.
