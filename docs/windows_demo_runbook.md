# Windows DEMO runbook

**Audience:** the operator, on the Windows machine with the MetaTrader5 DEMO
terminal.
**Mode:** `DEMO_EXECUTION` only. `LIVE_LOCKED`. **No strategy is promoted by
anything in this document.**

This runbook exists so that a Windows session produces *evidence*, not
surprises. Every step before the last one is read-only. Nothing here submits an
order automatically, and nothing should ever be submitted "to generate test
evidence" — the commands below are designed so that you never have to.

---

## 0. Before you start

```bat
cd C:\path\to\Trading-System
python -c "import MetaTrader5; print(MetaTrader5.__version__)"
```

If that fails, stop: the package is Windows-only and needs a running terminal.
Nothing below will work and nothing below will fake it.

Open the MetaTrader 5 DEMO terminal and confirm it is connected and logged in.
QTS does not start the terminal for you.

---

## 1. Measure the history depth — the question the 15m audit is blocked on

**Read-only. Submits nothing.**

```bat
qts data mt5-depth --json-out data\evidence\mt5_depth_probe.json
```

This answers, in seconds, the question that has been blocking the frozen
benchmark audit:

* **M15 bar depth**, read positionally with `copy_rates_from_pos`. Bars are
  what the frozen candidates need — and this has never been measured on any
  terminal. If it reports ≥ 5,000 bars, the depth blocker is gone.
* **Tick depth**, probed as several small one-hour windows at increasing age.

Why it asks two different questions: the old evidence said "30 days". That
number came from *one* `copy_ticks_range` call per window, and the 365-day call
failed. An oversized request failing is what a **request-size limit** looks
like; it is **not** a retention limit. The probe separates them on purpose.

> **Recorded correction:** the previous phase-3 report treated that 30-day
> figure as a proven retention ceiling and concluded broker history could not
> be obtained in sufficient quantity. That conclusion was too strong. The
> evidence file itself says "not the maximum retention boundary", and the
> acquisition layer already assumes the difference — it chunks at 24h and
> halves on failure. The correct status is **UNKNOWN until this command is
> run**.

Copy `data\evidence\mt5_depth_probe.json` back into the repository and commit
it.

---

## 2. Connectivity, identity, symbol, quote — Stage 1

**Read-only. Submits nothing.**

```bat
qts demo connectivity --pin --json-out data\evidence\demo_connectivity.json
qts demo connectivity --confirm-pin
```

Confirms: terminal reachable · account is **DEMO** · server/company identity ·
`XAUUSD` → `XAUUSD@` mapping resolves and is tradable · quote is fresh ·
order_check dry-run passes.

`STAGE_1_READY: True` must print. If `identity.is_demo` is `None`, that means
UNKNOWN and the gate fails closed — it is not a pass.

---

## 3. Prove cost capture will work — before any order

**Read-only. Submits nothing.**

```bat
qts demo cost-check --json-out data\evidence\demo_cost_check.json
```

This is the step that makes the rest safe. It reports whether the broker's
commission, swap and fee can actually be observed, and blocks with a named
reason when they cannot:

| Check | Blocks | Why it matters |
|:---|:---|:---|
| `terminal-reachable` | yes | nothing works without the terminal |
| `account-is-demo` | yes | `None` means UNKNOWN, and fails closed |
| `deposit-currency-known` | yes | MT5 reports money in the deposit currency; an unknown currency must never be read as USD |
| `server-offset-measured` | yes | must be MEASURED, not `assumed-utc-fallback`, or every captured deal time is wrong by the server's offset (3h on this broker) |
| `evidence-chain-verifies` | yes | an existing log that fails integrity is not evidence |
| `evidence-store-writable` | yes | proven with a throwaway probe file that is then deleted |
| `deal-history-readable` | no | informational |
| `cost-fields-present` | no | informational — which cost fields recent deals expose |

`READY_FOR_COST_CAPTURE: True` must print before you go further.

### Measuring cost without trading at all

If the account already has deals, this is the cheapest honest measurement
available — **no new order required**:

```bat
qts demo cost-check --record --json-out data\evidence\demo_cost_check.json
```

Backfills the sampled historical deals into the evidence store, tagged
`source=mt5.history_deals_get.backfill` so they stay distinguishable from
deals captured on a QTS submission (which are attributable to an order this
system sent). **Prefer this over placing a trade to see what it costs.**

---

## 4. Arm — explicit confirmation required

```bat
qts demo arm --stage 1 --confirm --risk-ack
qts demo arm --stage 2 --confirm --risk-ack
```

Each stage demands `--confirm` and `--risk-ack` explicitly. `LIVE_LOCKED` is
untouched; there is no stage that unlocks it.

---

## 5. Verify the evidence, then review it

```bat
qts demo reverify --confirm --risk-ack
```

Review what was actually recorded:

```bat
qts edge readiness --data-version <version>
```

**Do not place an order at this point.** Everything measurable so far has been
measured read-only. A DEMO order is a separate, deliberate decision by you —
it is not a step in collecting evidence.

---

## 6. Only if you choose to trade

```bat
qts demo preflight --side BUY --lots 0.01 --stop-loss 3995.00
qts demo order --side BUY --lots 0.01 --stop-loss 3995.00
```

`preflight` refuses before the order if any gate fails. The order command is
the one and only place an order can be sent, and it is never automated by this
runbook.

After a fill, confirm the charges were captured:

```bat
qts demo journal --limit 5
```

The evidence log (`data/evidence/demo_cost_evidence.jsonl`) is **machine-local
and deliberately gitignored** — committing a log that looks like it came from a
broker, when it came from a simulation, would be worse than having no log at
all. Export summaries, not the log.

---

## Failure messages and what to do

| Message | Meaning | Action |
|:---|:---|:---|
| `MT5_PACKAGE_UNAVAILABLE` | not on Windows, or no terminal | run on the Windows machine |
| `MT5 initialize failed` | terminal not connected | open the terminal and log in |
| `account-is-demo: is_demo=None` | identity UNKNOWN | fails closed by design; do not proceed |
| `deposit-currency-known: currency unavailable` | `account_info().currency` unreadable | do not treat amounts as USD |
| `server-offset-measured: assumed-utc-fallback` | offset could not be measured | captured times would be wrong; fix before trading |
| `evidence-store-writable: PermissionError` | state dir not writable | set `QTS_STATE_ROOT` to a writable path |
| `cost-fields-present: commission=0` | broker deals lack the field | costs stay UNAVAILABLE, never zero |

Every one of these fails **closed**. None of them can be overridden with a
flag.

---

## What this runbook must never do

* submit an order to produce test evidence (step 3 exists precisely so this is
  never necessary);
* unlock LIVE, or touch `LIVE_LOCKED`;
* edit `data/evidence/demo_execution_authorization_2026-09-23.json` or
  recompute its `integrity.content_sha256`;
* withdraw or loosen a risk limit;
* promote a strategy on the strength of anything in this document.

A strategy is promoted only on reproducible out-of-sample results measured
after real costs — and none of that exists yet.
