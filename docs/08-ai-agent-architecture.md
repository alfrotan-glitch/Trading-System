# 8 — AI / Agent Architecture

**Principle:** Do not add AI for marketing. Every AI component must have measurable uplift vs. non-AI baseline, with falsifiable evaluation.

## 8.1 Where AI Genuinely Helps (Evidence-Backed)

| Role | Task | Value | Evaluation |
|------|------|-------|------------|
| Research Assistant | Hypothesis generation from literature, lineage | Breadth, not missed ideas | Hypotheses that pass validation vs random |
| Feature Discovery | Propose features, then statistical test | Speed | Feature IC, leakage-free validation |
| Regime Research | Cluster/label regimes, test if tradable | Conditional edge | Regime-conditioned WFA uplift vs unconditional |
| Adversarial Review | Attack strategies, surface leakage/overfit patterns | Robustness | Bugs found before LIVE |
| Experiment Interpretation | Summarize validation reports, suggest next exp | Interpretability | Human time saved, correctness |
| Anomaly Detection | Data quality, execution anomalies | Safety | Precision/recall on injected anomalies |
| Code/Test Generation | Scaffolding, property tests | Velocity | Tests passing, review time |

Where AI does **not** help at v1: autonomous live trade decisions, black-box signal generation without interpretability, “AI picks parameters” bypassing validation.

## 8.2 Agent Roles — Minimal Viable Set

We prefer **single orchestrator + tool use** over many autonomous agents. Unnecessary multi-agent complexity is rejected.

### V1 (3 roles, orchestrated)

1. **ResearchAgent** — generates hypotheses from prompts + lineage + literature; outputs `Hypothesis` objects (not trades).
2. **AdversarialAgent** — given a `ValidationReport`, actively searches for leakage, fragile thresholds, cost sensitivity; outputs `AdversarialFindings`.
3. **MonitoringAgent** — watches audit log + metrics, diagnoses drift, suggests SUSPEND; outputs `AlertInterpretation`.

### Future (only if measured uplift)

- `DataAgent` — data quality triage.
- `ExecutionAgent` — routing optimization.
- `RiskAgent` — limit tuning (still human-approved).

All agents operate via **tools** (read-only unless explicitly approved):

```
Tools: read_hypothesis, propose_hypothesis, read_experiment, run_validation, read_audit, read_market_data (versioned), propose_experiment
No tool: submit_order, override_risk, promote_lifecycle (human-only)
```

## 8.3 Hypothesis Generation Loop

```
Human or Scheduler → ResearchAgent.propose(n=5) → Hypotheses
  → human curation (accept/reject) → Experiment planner → run → Validation
  → AdversarialAgent review → Validated or Rejected
  → lineage stored → next loop conditions on lineage (avoid repeats)
```

AI ideas are hypotheses, not truth. Every AI hypothesis carries `generated_by: "ResearchAgent vX"` + prompt + lineage refs for audit.

## 8.4 Feature Discovery

- AI proposes feature definitions (e.g. `"rsi_divergence_14"`).
- Feature Store computes them **only** on train slice, with `fit`/`transform` separation.
- Evaluation: IC, leakage test (feature at t uses only data ≤ t), stability across regimes. AI does not see test data.

## 8.5 Regime Intelligence as Hypothesis

Regime detectors (volatility quantile, HMM, clustering) are **empirical hypotheses**:

- Detector → labels → strategy conditioned on label → validation must show uplift vs unconditional.
- If no uplift → detector rejected, not deployed. Stored as `RegimeExperiment`.

## 8.6 Safety & Control

- AI never has broker credentials; never calls `BrokerAdapter`.
- AI outputs are versioned and logged; human approval gate before candidate promotion.
- Prompt injection defense: agent inputs are filtered to domain objects, not raw market narrative.
- Cost control: LLM calls budgeted per experiment; fallback to deterministic heuristics if budget exceeded.

## 8.7 Implementation

- `src/qts/research/agent.py` — `ResearchAgent` interface with `LocalLLMAgent` and `NullAgent` (deterministic baseline).
- At v1, `NullAgent` proposes simple hypotheses (SMA, RSI) for testing without LLM; `LocalLLMAgent` wraps any OpenAI-compatible API via config, optional.
- Evaluation harness: `qts research evaluate --agent null vs llm --trials 20` compares validation pass rate.

## 8.8 Memory

Agents read `ExperimentStore.lineage` to avoid repeating failed ideas. Repeatedly rediscovering failed hypotheses is a bug — agent must query memory before proposing.

## 8.9 Anti-Patterns Rejected

- Autonomous trader agent that emits OrderIntents.
- Opaque neural signal without feature attribution.
- Multi-agent debate without ground-truth validation.
- AI that rewrites risk limits.
