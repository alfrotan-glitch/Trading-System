"""Research orchestration + evidence/report generation for the impulse study.

``run_impulse_research`` is the single entry point used by the CLI and by
tests. It is fail-closed at every step:

* no usable data version  -> ValueError with an honest message (never fabricates bars)
* unusable/empty bars     -> ValueError
* inadequate data         -> analysis still runs (mechanism validation) but ALL
                             real-market claims are blocked by the classifier
                             and every output is labeled accordingly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.data.bootstrap import classify_source
from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument
from qts.observability.lineage import code_version
from qts.research.impulse.adequacy import DataAdequacyReport, assess_data_adequacy
from qts.research.impulse.analysis import (
    ImpulseAnalysisResult,
    ImpulseResearchConfig,
    run_impulse_analysis,
)
from qts.research.impulse.conclusions import ResearchConclusion, classify_conclusion

MIN_FORWARD_OBSERVATIONS = 10


def _forward_evidence_available(evidence_dir: Path, *, instrument: str | None = None) -> bool:
    """Forward observation evidence must exist IN THE CANONICAL STORE with
    real-market provenance.

    The canonical source is the ForwardObservatory SQLite store; only ticks
    with DEMO/REAL provenance count (SYNTHETIC/PAPER/UNVERIFIED never do).
    The legacy ``demo_forward_observations.json`` export is deliberately NOT
    consulted: it once contained fabricated demo fills, and a derived file's
    existence must never satisfy a forward-evidence requirement (findings
    #5/#6/#22). Absence or any read error => False (fail closed).
    """
    try:
        from qts.observability.forward_observatory import ForwardObservatory

        obs = ForwardObservatory()
        # 10+ real-market-class observations, symbol-consistent when known.
        return obs.real_observation_count(symbol=instrument) >= MIN_FORWARD_OBSERVATIONS
    except Exception:  # noqa: BLE001 - absence of forward evidence must never crash research
        return False


def run_impulse_research(
    store: SqliteParquetDataStore,
    data_version: str | None = None,
    cfg: ImpulseResearchConfig | None = None,
    ledger_db_path: Path | str | None = None,
    partition_db_path: Path | str | None = None,
    evidence_dir: Path | str = "data/evidence",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the full pre-registered impulse event study and return evidence.

    Raises ValueError (fail-closed) when no usable data exists. Never
    fabricates bars, never substitutes synthetic data silently, never writes
    to promotion/kill-switch state, never connects to order submission.
    """
    now = now or datetime.now(UTC)
    cfg = cfg or ImpulseResearchConfig()

    if data_version is None:
        usable = store.list_usable_versions()
        if not usable:
            raise ValueError(
                "no usable data version (usable = manifest + curated parquet + readable bars). "
                "Run `qts data bootstrap` or ingest real data via `qts data ingest`. "
                "No data was fabricated and no research claim is made."
            )
        data_version = usable[-1]

    manifest = store.manifest(data_version)
    if manifest is None:
        raise ValueError(f"no manifest for version {data_version} — not usable, nothing fabricated")

    instrument = Instrument(symbol=manifest.instrument, venue=manifest.venue)
    bars = store.read_bars(instrument, manifest.timeframe, version=data_version)
    if not bars:
        raise ValueError(
            f"version {data_version} has a manifest but ZERO readable bars — not usable. "
            "Run `qts data bootstrap` to establish a usable dataset. Nothing was fabricated."
        )

    data_class = classify_source(manifest.source)
    provenance = {
        "data_version": manifest.version,
        "checksum": manifest.checksum,
        "instrument": manifest.instrument,
        "venue": manifest.venue,
        "timeframe": manifest.timeframe,
        "rows": manifest.rows,
        "bars_read": len(bars),
        "start": manifest.start.isoformat(),
        "end": manifest.end.isoformat(),
        "source_label": manifest.source,
        "source_file": manifest.source_file,
        "data_class": data_class,
        "timezone": manifest.timezone,
        "missing_data_stats": manifest.missing_data_stats,
        "code_version": code_version(),
    }

    analysis: ImpulseAnalysisResult = run_impulse_analysis(
        bars,
        data_version=manifest.version,
        provenance=provenance,
        cfg=cfg,
        ledger_db_path=ledger_db_path,
        data_root_db_path=partition_db_path,
    )

    # --- event counts for the adequacy gate (primary horizon, pooled) -------
    primary_pooled = [r for r in analysis.results if r.horizon == cfg.primary_horizon and r.split == "pooled"]
    ev_total = sum(r.n_measured for r in primary_pooled)
    ev_long = sum(int(r.direction_mix.get("LONG", 0)) for r in primary_pooled)
    ev_short = sum(int(r.direction_mix.get("SHORT", 0)) for r in primary_pooled)

    adequacy: DataAdequacyReport = assess_data_adequacy(
        bars,
        data_version=manifest.version,
        source_label=manifest.source,
        now=now,
        measured_events_total=ev_total,
        measured_events_long=ev_long,
        measured_events_short=ev_short,
    )

    conclusion: ResearchConclusion = classify_conclusion(
        results=analysis.results,
        primary_horizon=cfg.primary_horizon,
        adequacy_ok=adequacy.adequate_for_real_claims,
        adequacy_reasons=[
            f"{c.requirement_id}: {c.description} (minimum: {c.minimum}; observed: {c.observed})"
            for c in adequacy.unmet_requirements
        ],
        sensitivity=analysis.sensitivity,
        forward_evidence_available=_forward_evidence_available(Path(evidence_dir), instrument=manifest.instrument),
    )

    evidence: dict[str, Any] = {
        "research": "impulse_continuation",
        "generated_at": now.isoformat(),
        "mode": "MECHANISM_VALIDATION" if not adequacy.adequate_for_real_claims else "REAL_CLAIMS",
        "mode_note": (
            "Dataset failed the pre-registered data-adequacy gate. All numbers below describe "
            "the RESEARCH MECHANISM operating on this dataset, NOT real-market behavior. No "
            "real-market claim is permitted and nothing was promoted."
            if not adequacy.adequate_for_real_claims
            else "Dataset passed the data-adequacy gate; conclusions may reference real-market behavior."
        ),
        "hypothesis": (
            "When price begins an unusually strong directional movement, the conditional "
            "distribution of the next short horizon is sufficiently directional and persistent "
            "to create positive net expectancy after spread, commission, slippage, and latency."
        ),
        "hypothesis_specification": {
            "question": "Does an unusually strong directional movement predict positive net expectancy at the declared short horizons?",
            "mechanism": "short-horizon directional persistence after an impulse, rather than unconditional continuation",
            "measurable_prediction": "impulse events have higher continuation and net-return distributions than the matched non-event baseline after declared costs",
            "null_hypothesis": "impulse events have no incremental predictive value versus the matched baseline after costs and timing controls",
            "competing_explanations": [
                "selection or trial-count bias",
                "timestamp/look-ahead leakage",
                "single-regime or single-instrument artifact",
                "cost assumptions masking unavailable broker execution evidence",
            ],
            "falsification_criteria": [
                "chronological validation does not replicate the effect",
                "the effect disappears under declared cost or latency sensitivity",
                "the effect is not separated from baseline/placebo controls",
                "event counts or regime coverage remain insufficient for the claim",
            ],
            "required_data": [
                "immutable provenance-qualified OHLC history",
                "measured bid/ask or tick spread and execution-cost fields",
                "enough events per direction across multiple regimes",
                "untouched chronological validation and forward observation",
            ],
            "horizon": f"primary={cfg.primary_horizon} bars; sensitivity={list(cfg.horizons)}",
            "population": f"{manifest.instrument} {manifest.timeframe} bars from the declared venue/source",
            "regime": "all declared volatility regimes; no unmeasured regime may be silently excluded",
        },
        "provenance": provenance,
        "data_adequacy": adequacy.as_dict(),
        "analysis": analysis.as_dict(),
        "conclusion": conclusion.as_dict(),
        "safety": {
            "live_trading_enabled": False,
            "live_eligibility_modified": False,
            "order_submission_connected": False,
            "promotion_state_modified": False,
            "locked_test_partition_accessed": False,
            "trial_ledger_reset": False,
        },
    }
    return evidence


def render_markdown_report(evidence: dict[str, Any]) -> str:
    """Human-readable research report rendered from the evidence dict."""
    prov = evidence["provenance"]
    adq = evidence["data_adequacy"]
    an = evidence["analysis"]
    concl = evidence["conclusion"]
    lines: list[str] = []
    lines.append("# Impulse Continuation Research — Evidence Report")
    lines.append("")
    lines.append(f"Generated: {evidence['generated_at']}  ·  Mode: **{evidence['mode']}**")
    lines.append("")
    lines.append(f"> {evidence['mode_note']}")
    lines.append("")
    lines.append("## Hypothesis")
    lines.append(f"{evidence['hypothesis']}")
    lines.append("")
    lines.append("## Dataset provenance")
    lines.append(
        f"- version `{prov['data_version']}` · {prov['instrument']} {prov['timeframe']} · venue {prov['venue']}"
    )
    lines.append(f"- checksum `{prov['checksum']}` · rows {prov['rows']} · bars read {prov['bars_read']}")
    lines.append(f"- span {prov['start']} → {prov['end']} ({prov['timezone']})")
    lines.append(f"- source label `{prov['source_label']}` · **data class: {prov['data_class']}**")
    lines.append(f"- code version `{prov['code_version']}`")
    spec = evidence.get("hypothesis_specification", {})
    if spec:
        lines.append("")
        lines.append("## Falsifiable specification")
        for key in ("mechanism", "measurable_prediction", "null_hypothesis", "horizon", "population", "regime"):
            if spec.get(key):
                lines.append(f"- **{key.replace('_', ' ').title()}:** {spec[key]}")
        for key in ("competing_explanations", "falsification_criteria", "required_data"):
            values = spec.get(key) or []
            if values:
                lines.append(f"- **{key.replace('_', ' ').title()}:** " + "; ".join(str(v) for v in values))
    lines.append("")
    lines.append("## Data adequacy gate")
    lines.append(f"adequate_for_real_claims: **{adq['adequate_for_real_claims']}**")
    lines.append("")
    lines.append("| ID | Requirement | Minimum | Observed | Passed | Blocking |")
    lines.append("|----|-------------|---------|----------|--------|----------|")
    for c in adq["checks"]:
        lines.append(
            f"| {c['requirement_id']} | {c['description'][:80]} | {c['minimum']} | {c['observed'][:60]} "
            f"| {'PASS' if c['passed'] else 'FAIL'} | {'yes' if c['blocking_for_real_claims'] else 'no'} |"
        )
    lines.append("")
    lines.append("## Pre-registered design")
    cfgs = an["config_snapshot"]
    lines.append(
        f"- families: {len(cfgs['pre_registered_families'])} (5 definitions x 2 parameterizations, "
        "no data-driven search)"
    )
    lines.append(f"- horizons (bars): {cfgs['horizons']} (primary {cfgs['primary_horizon']})")
    lines.append(f"- warmup: {cfgs['warmup_bars']} bars · alpha: {cfgs['alpha']} · bootstrap: {cfgs['n_boot']}")
    lines.append(f"- declared cost assumptions (ESTIMATED): {cfgs['costs']}")
    lines.append(f"- splits: discovery/validation chronological; LOCKED partition untouched: {an['locked_untouched']}")
    t = an["totals"]
    lines.append(
        f"- events: detected {t['events_detected_total']}, measured {t['events_measured_total']}, "
        f"excluded (insufficient forward bars) {t['events_excluded_total']}, "
        f"discarded-in-locked {t['events_locked_discarded']}"
    )
    lines.append(
        f"- trials recorded in ledger: {t['trials_recorded']} · ledger total (never reset): "
        f"{an['ledger'].get('ledger_trials_total')} · DSR penalized with N={t.get('num_trials_for_dsr')}"
    )
    lines.append("")
    lines.append(f"## Results (primary horizon {cfgs['primary_horizon']} bars, pooled discovery+validation)")
    lines.append("")
    lines.append(
        "| Family | n | cont. rate | baseline | diff | p_raw | p_holm | gross bps | net bps | net CI | TTT hit | MFE | MAE | DSR |"
    )
    lines.append(
        "|--------|---|------------|----------|------|-------|--------|-----------|---------|--------|---------|-----|-----|-----|"
    )
    prim = [r for r in an["results"] if r["horizon"] == cfgs["primary_horizon"] and r["split"] == "pooled"]
    for r in sorted(prim, key=lambda x: x["family_id"]):
        dsr = f"{r['dsr_per_event']:.3f}" if r.get("dsr_per_event") is not None else "n/a"
        lines.append(
            f"| {r['family_id']} | {r['n_measured']} | {r['continuation_rate']:.3f} | "
            f"{r['baseline_continuation_rate']:.3f} | {r['diff_vs_baseline']:+.3f} | {r['p_raw']:.4f} | "
            f"{r['p_holm']:.4f} | {r['gross_mean_bps']:+.2f} | {r['net_mean_bps']:+.2f} | "
            f"[{r['net_ci'][0]:.2f},{r['net_ci'][1]:.2f}] | {r['target_hit_rate']:.2f} | "
            f"{r['mfe_mean_bps']:.1f} | {r['mae_mean_bps']:.1f} | {dsr} |"
        )
    lines.append("")
    lines.append("## Cost / spread / latency sensitivity (pooled net mean bps, primary horizon)")
    lines.append("")
    sens = an["sensitivity"]
    lines.append("| Family | cost 0.5x | 1x | 1.5x | 2x | spread 0.5x | 1x | 1.5x | 2x | latency 0 | 1 | 2 |")
    lines.append("|--------|-----------|----|------|----|-------------|----|------|----|-----------|---|---|")
    for fid in sorted(sens["cost_multiplier"]):
        cm, sm, lm = sens["cost_multiplier"][fid], sens["spread_multiplier"][fid], sens["latency_bars"][fid]
        lines.append(
            f"| {fid} | {cm.get('0.5x', 0):+.2f} | {cm.get('1.0x', 0):+.2f} | {cm.get('1.5x', 0):+.2f} | "
            f"{cm.get('2.0x', 0):+.2f} | {sm.get('0.5x', 0):+.2f} | {sm.get('1.0x', 0):+.2f} | "
            f"{sm.get('1.5x', 0):+.2f} | {sm.get('2.0x', 0):+.2f} | {lm.get('0', 0):+.2f} | "
            f"{lm.get('1', 0):+.2f} | {lm.get('2', 0):+.2f} |"
        )
    lines.append("")
    lines.append("## Conclusion")
    lines.append(f"**{concl['conclusion']}** — research GO/BLOCK: **{concl['go_block']}**")
    lines.append("")
    for reason in concl["reasons"]:
        lines.append(f"- {reason}")
    if concl["supporting_family_ids"]:
        lines.append(f"- families referenced by the classifier: {', '.join(concl['supporting_family_ids'])}")
    lines.append("")
    lines.append(f"Promotion: {concl['promotion']}")
    lines.append("")
    lines.append("## Safety invariants")
    for k, v in evidence["safety"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)
