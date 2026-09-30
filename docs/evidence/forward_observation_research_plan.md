# FO-R1 — research-grade forward market observation

**Design version:** 1.0, 2026-09-18. **Baseline inspected:** `56079627014fa3c1edd13786baba2c2094a5d87a`.

**Status: DESIGN BASELINE / campaign specification.** This document does not start a collector, implement instrumentation, change a gate, create a hypothesis/strategy or grant execution permission. Numeric thresholds below are proposed, preregisterable design choices, not measured achievements or universal sample-size guarantees.

The acquisition-prerequisite table below is retained as the original FO-R1
design baseline. The repository's current engineering closure is recorded in
[`forward_observation_status.md`](forward_observation_status.md): the storage,
acquisition-accounting, snapshot and integrity blockers listed there are closed
in code. A real Windows/MT5 observation session has **not** yet been run, so
research-grade collection remains an operator milestone rather than a completed
result.

## 1. Objective and non-negotiable boundary

Build an immutable, broker-specific dataset of **sampled MT5 bid/ask observations**, acquisition outcomes and contemporaneous context. Its purpose is descriptive market measurement followed by separately governed generation and falsification of hypotheses. No trading strategy, profitability objective, edge claim, signal generation, hypothetical order or fill belongs in FO-R1.

- Keep **DEMO execution DISABLED and LIVE LOCKED**, risk gates and acknowledgements unchanged. Never call `/api/demo/enable`, an execution engine, promotion transition or order-submission API.
- Use only the existing readiness-gated **Start Observation (No Orders)** path. Its current 14-check readiness includes a demo account. Passing readiness is not execution permission. Resolve and record an explicitly order-free `DEMO_FORWARD` observation mode; do not select `DEMO_EXECUTION` or `LIVE`.
- “Real MT5 market data” describes the acquisition source. Under the current collector, the provenance enum is **DEMO** because the source is a demo account. Do not relabel it REAL or switch to a real-money account. The data represents that broker's demo quote feed, not the entire gold market or necessarily the broker's live-account quotes.
- The earlier `FS-5a9542` artifact is a verified **pipeline/structural audit**, not a research sample, a completeness certificate or an execution qualification. Exclude it from FO-R1's preregistered sample and holdouts.
- Keep all session signal counts zero. The observation store must have no order tables. These store declarations, source-code order-free checks and operator terminal checks are different evidence layers; artifact verification alone does not prove terminal-wide zero orders.

## 2. What the current collector can and cannot measure

Source inspection: `observability/demo_collector.py`, `forward_observatory.py`, `session_export.py`, `adapters/mt5_adapter.py`, `adapters/market_data.py`, and API `/api/observe/*` wiring.

The default loop polls the **latest quote**, waits 1.0 s after processing, then polls again. It is not a broker tick stream, and its actual interval includes retrieval, persistence and manifest work. Duplicate standing quotes are skipped. The result undercounts broker quote changes and cannot support quote-arrival intensity, full tick counts, order flow, queue position, true tick OHLC, subsecond microstructure or execution-latency claims.

Keep a **1.0 s requested interval** for the main cohort; capture actual cadence. More frequent polling does not convert this into complete tick history. Broker tick-history acquisition, if ever added, must be a separately versioned source with availability/completeness audits and must not silently backfill this forward cohort.

The validated path currently rejects future timestamps beyond 1 s, quotes older than 5 s, and spreads above 100 bps, alongside price/symbol/availability checks. The collector defaults to stopping after 30 consecutive retrieval/validation failures. **Do not widen or bypass those checks.** Accepted quotes are a censored sample: omitted stale/extreme-spread observations can be market-state dependent. Durable rejection metadata is therefore necessary, especially around news and rollover. Missing or rejected is never equivalent to zero market activity.

### Acquisition prerequisites — required before the research clock starts

| Priority | Observed limitation | Required next engineering work / acceptance test |
|---|---|---|
| BLOCKER | Tick IDs are `OT-` plus six random hexadecimal characters; writes use `INSERT OR REPLACE`. | Use collision-resistant full record identity and append-only/conflict-detecting writes. Exact retries may be idempotent only when complete payloads agree; conflicting IDs must refuse/quarantine, never replace. Preserve old records and test migration, cross-session collisions, retries and attempted overwrites. Keep v1 session IDs compatible or version the contract explicitly; session ID collisions must also never replace sessions. |
| BLOCKER | No durable record of each acquisition attempt, skipped quote, rejection or missed polling slot. Runtime counters are not complete source evidence. | Add an append-only acquisition journal, explicit sequence/monotonic times and an independently computed coverage ledger. Reconcile stored rows to successful attempts after restarts. Preserve structured rejection reasons separately without admitting invalid quotes into canonical accepted data. Test disconnects, repeats, changed payloads at identical stamps, missed polls and ledger/row disagreement. |
| BLOCKER | Storage/manifest exceptions occur outside the retrieval exception handler; a thread can fail without a trustworthy terminal lifecycle state. | Test and handle disk-full/write/manifest exceptions and process interruption; persist failure/recovery status, detect dead thread vs OBSERVING state and preserve unresolved attempts. Restore must not resume silently into the old session. |
| BLOCKER | A recovered retrieval error can remain as `last_error`; normal stop passes it to an ENDED session, which the hardened verifier correctly refuses as contradictory. | Separate recovered incidents from terminal failure, with durable incident history and truthful lifecycle status. Test transient failure → recovery → normal stop → evidence verification. Do not delete historical errors or relax the verifier. |
| BLOCKER | v1 evidence exports all row projections but only ten default full payloads; prices and most original raw stamp pairs are not hash-bound/exported. | Create a separately versioned private full-data snapshot/export contract and manifest that bind complete payloads, session metadata and acquisition ledger. Retain the existing v1 audit unchanged; do not inject extra fields into its strict schema or pretend it is a research dataset. |
| REQUIRED | Offset measurement details, host clock health, broker symbol specification, configuration and terminal identity are not all durably captured. | Add versioned private run metadata/clock journal and a stable privacy-preserving source identity. Validate before/after snapshots and changes. No credentials in logs or exports. |
| REQUIRED | Periodic manifest generation scans accumulated ticks; large-store behavior is not demonstrated. | Benchmark retrieval/persistence/manifest latency, disk growth, read snapshots and memory on a representative **synthetic stress store** plus a live order-free soak. Bound or isolate derived aggregation without dropping raw writes; never count synthetic stress rows as market evidence. |

An isolated synthetic storage probe confirmed that two writes with the same current ID leave only the second payload. With a uniform 24-bit ID space, collision probability reaches roughly 50% by **4,823 generated IDs** (birthday approximation). That is an engineering calculation, **not evidence that the earlier Desktop session suffered a collision**. Consistent exports cannot recover silently overwritten records or prove they never existed. Do not begin a multi-million-row campaign on this storage behavior.

All instrumentation above is **proposed, not implemented by this design**. A console status snapshot or operator log is useful operational evidence but cannot substitute for missing durable poll accounting. Until prerequisites pass, existing runs remain engineering-only.

## 3. Duration, number of sessions and stopping rule

### Recommended campaign

| Stage | Scope | Purpose / permitted conclusion |
|---|---|---|
| Engineering qualification | At least **5 market days**, including one ≥20-hour broker-open soak, transitions and safe restart/failure drills | Demonstrate persistence, coverage measurement, clocks, rejection accounting, recovery and resource behavior. Keep separate from statistical partitions. Failure drills use isolated test fixtures or controlled order-free outages. |
| Initial descriptive checkpoint | **20 usable distinct trading days over ≥4 calendar weeks**, ≥240 eligible observation hours | Describe this feed's observed time-of-day, spread and variability distributions with day-level uncertainty. No validation/edge claim. |
| Main FO-R1 campaign | **60 preassigned broker trading-day slots**, approximately **12–13 calendar weeks**, targeting 60 usable days and ≥1,000 eligible hours | Several weekday/monthly cycles, meaningful daily replication and forward partitions. Still not a multi-year or all-regime dataset. |
| Release floor for the main descriptive cohort | **≥48 usable distinct days**, ≥900 eligible hours; partition floors below and all coverage/quality requirements | Permission to assess research adequacy, not automatic hypothesis validation. |

Collect approximately **20 broker-open hours per scheduled day**, preferably all practical broker-open hours, rather than selecting visually interesting sessions. Actual broker availability and maintenance take precedence; do not assume 24/7 operation or invent missing hours. At 1 s, 900 hours represents about **3.24 million nominal polling slots**, not guaranteed unique ticks or independent observations. Stored quote counts are reported, not targeted by accelerating collection or counting duplicates.

A research day is a preregistered broker trading date, not an `FS-*` record count. Prefer one uninterrupted runtime session per daily open segment, gracefully bounded by scheduled maintenance. Breaks, crashes and restarts may create multiple immutable FS sessions mapped to the same logical day. Thus **about 60 daily collection units, possibly more than 60 FS IDs**; ten restarts are not ten independent sessions. No parallel collectors on the same feed to inflate sample size.

Preassign actual trading dates and UTC windows before launch using the broker calendar. Default chronological partitions are **days 1–30 discovery, 31–45 validation, 46–60 locked confirmation**; minimum usable days **24 / 12 / 12**. All scheduled days, including failed/closed/short days, remain in the ledger. Unexpected closures and holidays do not silently renumber already assigned partitions. Publish the exclusion/coverage table as well as the accepted dataset.

At the last scheduled day, evaluate the frozen quality/coverage rules, not market results. If a floor fails, label the affected release/scope **INSUFFICIENT_DATA**. A documented extension may add future dates under a new plan version, but must not replace unfavorable days, redraw an inspected holdout or repeatedly inspect confirmation results until significant. No automatic “collect until an edge appears.” A prospective second tranche is preferable to quietly altering the first.

## 4. Required time-window and regime coverage

These are reproducible sampling strata, not claims about exact exchange opens for a broker-specific OTC instrument. Store UTC and the applicable IANA timezone/version. Do not hardcode “London = UTC+1” or a fixed New York offset across daylight-saving transitions.

| Stratum | Preregistered window | Main-cohort coverage floor |
|---|---|---|
| Asian hours | 00:00–06:00 UTC | ≥40 distinct days with complete blocks |
| London morning | 08:00–11:00 `Europe/London` | ≥40 distinct days |
| US morning | 08:00–11:00 `America/New_York` | ≥40 distinct days |
| London/US overlap proxy | 13:00–16:00 `Europe/London`; also label actual concurrent local hours | ≥30 distinct days |
| Later US hours | 13:00–16:00 `America/New_York` | ≥20 distinct days |
| Broker rollover/maintenance boundary | 30 minutes before closing and 30 after reopening, using documented broker schedule | ≥10 boundaries; open-side data and scheduled closure separately counted |
| Weekly reopen and pre-weekend close | First/last 60 broker-open minutes | ≥8 occurrences of each |
| Weekdays | Broker trading-date weekday | ≥8 usable days of each weekday |

Overlapping labels are allowed, but **hours and independent samples are counted once**. A complete time-window block requires ≥95% eligible one-minute bins and no unexplained open-market gap >60 s. The longer Asian window consequently needs ≥342 eligible minutes. Planned closed intervals are excluded only using a calendar frozen in advance, not inferred from absent rows. Rollover is an explicit discontinuous boundary stratum; never compute a return across the closed segment as an ordinary intraday return.

### Scheduled events and controls

Record official release/policy calendars, source URLs, retrieval time, original timezone, announced event time and later revisions. Freeze the acquisition schedule before releases. Include scheduled US employment, inflation and monetary-policy events that actually occur, plus documented broker holidays/short days. Do not invent future event dates or surprise magnitudes.

Capture **T−60 to T+120 minutes** around scheduled events where the broker is open; assign an event ID and type. Target **≥6 distinct event days spanning ≥3 types** and ≥12 time/weekday-matched non-event blocks, without treating overlapping releases as independent. If missing, event research remains ineligible even if ordinary-hours research is usable. Six events is coverage for description, **not sufficient power for event-specific conclusions**. Three months may contain very few policy decisions; rare shocks and crises cannot be guaranteed or inferred from this plan.

### Observed market-state descriptors

Preserve continuous measurements; optionally label low/medium/high variability and spread conditions, directional/dispersed paths and transitions. Use only prior completed, eligible one-minute observations at each feature timestamp; for example, lagged 60-minute sampled-mid variability and path-efficiency descriptors with ≥45 valid source minutes. Mark inadequate warm-up/missing support unavailable. Freeze exact formulas and bin cutoffs from discovery only before applying them forward. Full-discovery cutoffs may describe discovery retrospectively, but cannot masquerade as causal training labels in discovery backtests.

For any coarse regime cell claimed in a descriptive comparison, require **≥20 nonoverlapping one-hour blocks on ≥10 distinct days** and disclose autocorrelation. Do not force membership to reach quotas or multiply small cells into dozens of apparently independent tests. Missing states mean narrower claims or more prospective collection, not synthetic augmentation. Twelve weeks does not establish structural/bull/bear/crisis-regime generality.

## 5. Data contract and provenance

Separate **raw accepted quotes**, **acquisition/quality diagnostics**, **run metadata**, and **derived analytical data**. Link them by immutable campaign/day/run/session/attempt IDs and manifest hashes. The journal is not an order/signal table and rejected observations never become accepted pricing data.

| Layer | Required fields | Current status / boundary |
|---|---|---|
| Accepted quote | Collision-safe record ID; session ID; instrument mapping; exact-decimal bid/ask; mid/spread; normalized broker event time; raw MT5 `time` and `time_msc`; local receipt; offset and basis; full available tick provenance; DEMO class | Many fields exist in SQLite today; safe identity and complete export binding require work. Preserve original units/precision/nulls. |
| Acquisition attempt | Monotonic sequence; scheduled slot; poll start/end UTC and monotonic clock; actual interval; connection/run ID; outcome; linked record ID or duplicate key; structured rejection/error; persistence outcome; heartbeat/recovery marker | **New durable journal required.** Repeated standing quotes and missing polls must be distinguishable. Never label quote event age as network or submission latency. |
| Runtime/source | Full code SHA, schema/exporter/config hashes, requested/actual sampling policy, validation thresholds, readiness report, order-free mode, account class, pseudonymous broker/server/feed identity, terminal/adapter/OS versions, symbol-spec snapshot and version | Some session metadata exists; versioned additions needed. No login, password, token or unredacted machine/user paths in transferable data. |
| Symbol contract | Canonical symbol, exact broker symbol (baseline `XAUUSD@` only if verified), digits, tick size, quote currency, contract/session specification and effective time | Read from broker metadata; do not assume XAUUSD suffixes or specs are equivalent. |
| Clock/offset journal | Host synchronization source/status, offset/uncertainty estimate, last sync, clock steps; measured broker offset, measurement time/method/evidence reference, cache age; UTC timezone library version | Needed before time-sensitive research. Broker-normalized labels alone do not authenticate offset measurement or broker-clock accuracy. |
| Calendar/context | Trading-date mapping, open/closed intervals, holidays, DST rules, scheduled events with as-of/source/revision records | Versioned sidecar required; unavailable fields stay null with reason. |
| Optional raw market fields | Last, tick flags, broker volume/type, size/depth, if genuinely available and separately captured | Current observation payload does not establish these. Use `UNAVAILABLE`, never zero or synthetic substitutes. Broker tick volume is not centralized gold trade volume. |
| Derived tables | Resampling/feature version, source hashes, source availability time, eligible coverage, exclusions and reasons, trailing-window support, frozen regime labels, partition membership | Newly built reproducible research views; never overwrite raw fields or stamp derived values as directly measured. |

No fills, slippage, execution success or submission/ack latency can be measured with zero orders. Do not populate them with simulated zeros. Display absent session/regime classifications as unavailable until derived; existing default `unknown` is not an observed regime.

## 6. Sufficiency and quality rules

### Three separate outcomes

1. **Artifact structurally consistent:** hardened v1 verification passes. This is necessary audit evidence, never enough for research completeness.
2. **Dataset usable for a declared descriptive scope:** acquisition prerequisites, quality, coverage and comparability criteria pass for that scope.
3. **Hypothesis-specific statistical sufficiency:** later assessed for a preregistered estimand, material effect size, dependence structure and uncertainty target. There is no universal minimum number of quotes that proves an effect.

### Operational definitions — freeze after the engineering pilot

- Anchor nominal 1 s slots to a monotonic schedule with a documented UTC mapping. A slot is serviced if an attempt starts in it; multiple calls in one slot count once. Measure scheduled slots, serviced slots, validated responses (including unchanged valid quotes), rejected responses, errors and missed slots separately. A missing slot is not a zero-price-change observation.
- An eligible minute requires ≥90% of its nominal broker-open slots serviced **and** ≥90% with validated responses, no unresolved identity/clock/integrity fault and no within-minute unobserved polling gap >5 s. Validated repeats count for acquisition coverage, not unique-quote count. Fewer than 60 broker-open seconds is a boundary minute and is reported separately, not silently padded.
- A usable day has ≥12 eligible open hours and ≥95% eligible minutes across its preregistered planned-open collection interval; report every excluded interval. A full campaign still requires ≥900 eligible hours, ≥48 distinct usable days, 24/12/12 partition floors and relevant stratum quotas. Hours alone cannot replace missing days or time windows.
- Primary time-aligned analyses require a documented **measured** offset throughout included intervals; assumed-UTC fallback remains archived in a flagged secondary cohort and cannot silently enter that primary view. For the primary clock-QA cohort, target an independently evidenced host-clock error/uncertainty ≤100 ms at start/end and at least every 15 minutes, with no unexplained steps. Missing clock evidence fails time-aligned eligibility, not permission to fabricate corrections. This does not bound the broker clock: report negative ages separately; unresolved cross-clock offset precludes precise event alignment/latency claims. Broader receipt-time descriptions may be released with an explicit narrower scope.
- Zero tolerance for unaccounted lost/overwritten accepted records, conflicting duplicate identities, sample/accessor disagreement, unrecognized schema changes, mixed source identities, credential leakage, unexplained payload/digest mismatch or signals/orders in the observation path. Quarantine affected sessions/intervals; do not erase them from the campaign ledger.

Coverage thresholds are **measurement-quality rules, not execution gates**. If the pilot shows they are impractical, revise and freeze the plan **before** starting research partitions. Never tune them using subsequent market relationships or desired significance.

### Reconciliation and integrity checks

Before/after each session and at daily release:

1. Verify readiness and order-free mode; separately record authoritative DEMO-disabled and LIVE-locked state. Check no other automation/EA/manual trading is running on the dedicated observation terminal. Do not claim artifact counters prove terminal-wide behavior.
2. Reconcile the mutually exclusive completed-attempt outcomes: `stored_unique + duplicate_skip + validation_reject + retrieval_error + storage_error + unresolved = attempts`. Separately reconcile missed slots, journal sequence continuity and stored unique IDs/payloads. Unresolved attempts block a primary release until reconciled. Detect reconnect replay and same raw stamps with different quote payloads; never silently discard conflicts.
3. Validate source identity, positive finite bid/ask, ask ≥ bid, tick-size/decimal consistency, midpoint/spread arithmetic and payload/accessor agreement. Retain true accepted extremes; do not winsorize merely because a move is large.
4. Examine **arrival/persistence order** and broker-time order separately. v1 sorts export rows, so its monotonicity result is not proof of monotonic arrival. Diagnose offset changes, equal stamps, clock jumps and broker revisits without hiding them by sorting.
5. Report distributions of actual cadence, quote age, negative ages, accepted/rejected/stale responses, spread censoring, gaps and uptime by time window/event/regime. Show how included and excluded periods differ; accepted-only spread statistics must be labelled conditional on validation. If censoring dominates stress windows, stress inference is blocked, not “cleaned” into a calm sample.
6. Run SQLite integrity/foreign-identity checks on the actual source/snapshot; take a consistent backup through SQLite backup/checkpoint-safe tooling, not a naive copy of a live DB without its WAL. Verify restoration and row-count/hash agreement.
7. Independently verify full-data hashes, counts, ordering and complete payload relationships. Continue v1 verification for the session audit, but use a new full-data manifest for research. Its private aggregate hash may be independently anchored or signed to detect later edits; that still does not authenticate physical MT5 origin.
8. Persist inclusion/exclusion decisions and reasons, operator interventions and abnormal termination/recovery. No unexplained hole is called a market closure; no short session is counted as a full day.

## 7. Session-to-session comparability and dataset construction

Freeze one broker/server/account-class feed, one symbol/specification, one collector version, one sampling policy and one set of validation thresholds for a cohort. Record resolved configuration hashes, not merely file names. A code/feed/specification/interval/offset-method change starts a new cohort or explicitly documented segment. A necessary safety fix may stop collection; it does not justify pooling incompatible measurements. Preserve all earlier data unchanged and compare on common support before any pooling.

Primary analysis unit: the **trading day**, with declared nonoverlapping within-day blocks. Compare like local-time windows and event strata. Report per-day statistics plus day/block uncertainty rather than letting active days with more quotes dominate by row count. Broker/feed changes are not market effects. Days and weeks can remain serially dependent; block length and effective sample size must be justified later, not assumed from the 1 s cadence.

Construct primary one-minute and secondary five-/fifteen-minute views from immutable accepted quotes **plus coverage diagnostics**. Record both broker event time and information-availability/receipt time. At any analytical cutoff use only data available by then; a delayed quote is not retroactively known earlier. Label outputs **sampled-quote aggregates**, not complete trade bars or exact market highs/lows. Do not create trade volume.

For a minute endpoint, require an actually observed valid quote within the permitted age bound and valid acquisition coverage. A repeatedly validated unchanged quote may support a zero change; an unobserved interval may not. Keep missing minutes explicitly missing; no fabricated OHLC, interpolation, raw-price forward fill or returns bridging disconnections, closures or cohort changes. Reset trailing-feature support after gaps. Time-weighted spread descriptions require the journal's observed quote-duration support; deduplicated rows alone cannot establish full holding times.

Dataset identity includes source/session inventory, complete file hashes, schema and preprocessing versions, code/config/calendar versions, field availability, provenance, trading-day and split manifests, quality/exclusion reports and lineage. Publish scope-limited readiness, not one generic “research-ready” score.

## 8. From observations to falsifiable research — later, not a strategy now

1. **Data audit and description:** discovery partition only. Summarize field quality, missingness/censoring, distributions, temporal dependence and repeatability by preregistered window. Keep an observation notebook separating directly measured facts from interpretations. No P&L, return-optimized ranking, entry/exit rules or trading signals.
2. **Bounded hypothesis generation:** only after the descriptive floor passes. A later approved batch may contain at most **six** distinct, explicitly motivated hypotheses. Each must name its source observations/manifests, mechanism conjecture, population, exact estimand, null, material effect size, lookback/horizon, allowed inputs and availability time, exclusions, uncertainty method, falsifier and necessary data. Log discarded ideas and all variants; this phase does not select any hypothesis now.
3. **Sufficiency assessment before testing:** estimate variance and dependence using discovery only. Use day/multiday-block resampling or suitable cluster methods; check sensitivity to block length. Define a precision target or power/MDE calculation appropriate to the eventual question (e.g. 80% power at a prespecified family-adjusted error rate, if defensible). Quote count is not effective sample size. Twelve validation/confirmation days may be too few; record `INSUFFICIENT_EVIDENCE` rather than lowering the target. Small event/regime cells remain descriptive only.
4. **Falsification on discovery:** test alternative explanations including sampling cadence, clock shifts, feed changes, event concentration, spread censoring and missingness. Prespecify null/negative-control transformations that preserve time-of-day and serial structure; do not randomly shuffle ticks as if independent. Any resampling frequency sensitivity is a logged analysis variant, not a search for a favorable result.
5. **Validation:** freeze definitions/transformations/cutoffs before opening the validation partition. Use chronological/block-aware validation, not random-row train/test splits. Any purge/embargo must cover the maximum feature lookback, outcome horizon and dependence overlap. Validation-informed revisions are new logged trials; validation is not repeatedly reusable unseen evidence.
6. **Locked confirmation:** the final 15 scheduled days remain access-controlled. Operational QA may inspect only predefined integrity/coverage diagnostics; no candidate outcome plots or effect estimates. Reuse existing locked-partition/access-log governance, but create a **new forward-dataset partition manifest**, never reuse the old synthetic 300/100/100 split. Confirm data-access controls through tests before calling it locked. One registered analysis after final freeze; an accidental peek invalidates that confirmation and requires genuinely future data, not relabelling.
7. **Decision record:** `FALSIFIED`, `INCONCLUSIVE/INSUFFICIENT_EVIDENCE`, or a narrowly qualified `REPLICATED_DESCRIPTIVE_RELATIONSHIP` with effect size, uncertainty, scope and failures. Distinguish evidence against a meaningful effect from mere failure to reject a null. Control the declared hypothesis family (for example Holm family-wise adjustment) and preserve cumulative trial accounting, including negative results. No outcome creates a strategy, establishes economic edge or authorizes trading.

Existing strategy-oriented campaign templates, Sharpe/DSR rankings and promotion paths are **not invoked** for FO-R1. Later strategy/execution research would need a separately authorized design, additional evidence and all unchanged gates; spread observations alone do not measure slippage or fills. Observation acquisition never becomes a shortcut around those boundaries.

## 9. Delivery, privacy and launch checklist

Private artifacts per daily unit: consistent source snapshot, full accepted-quote export, acquisition journal, run/clock/calendar metadata, v1 session audit, full-data manifest, quality/exclusion report and partition assignment. Weekly deliverables contain scheduled vs actual coverage, unresolved faults, source changes and scope-limited sufficiency—not performance scores. At campaign close freeze a versioned release and independent reproducibility report.

Keep raw SQLite, full quotes, rejects and session evidence out of Git/public issues. Use access-controlled encrypted storage/transfer, a separate verified backup and retention/access rules approved for the broker's data license. The repository may contain protocol, schema/tests, hashes and appropriately sanitized aggregate findings, never the raw dataset. The prior artifact's removed branch ancestry does not guarantee erasure from GitHub caches/clones; do not reuse that public upload route.

**Before any FO-R1 research collection:**

- [ ] Collision-safe append-only storage and session identity tests pass; no historical data silently rewritten.
- [ ] Durable attempt/rejection/missed-slot journal, source metadata and clocks implemented and verified.
- [ ] Restart, transient-error recovery, disk/write failure, disconnect and large-store soak tests pass.
- [ ] Full-payload research snapshot/export and independent verification exist, separate from v1.
- [ ] Dedicated terminal is order-free; fresh readiness passes without enabling DEMO; DEMO authority remains disabled and LIVE locked.
- [ ] Five-day engineering qualification passed and retained separately.
- [ ] Actual broker schedule, timezone/event calendar sources, collection dates, coverage rules and immutable splits preregistered.
- [ ] Private storage/backup/licensing and analyst access controls approved.
- [ ] Protocol/code/config hashes frozen. Any unmet item means **NOT STARTED / ENGINEERING ONLY**, not research-grade collection.

**Historical baseline recommendation:** implement and test the observation-storage and acquisition-accounting prerequisites in a separate zero-order engineering task. Those engineering prerequisites are now closed in the repository; this sentence is retained to preserve the original design history.

**Current next action:** on a real Windows/MT5 operator machine, run the existing readiness-gated zero-order observation protocol and retain its canonical evidence. Do not treat the absence of a real session as solved by structural tests, and do not start a multi-week research campaign until the current scope, licensing, coverage and quality criteria are explicitly reviewed.
