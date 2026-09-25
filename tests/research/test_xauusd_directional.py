"""H-DIR-01 synthetic mechanisms, strict cutoff, independent view authority.

No test reads the canonical archive or its held-out 40%.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from qts.research.xauusd_directional import (
    ALPHA,
    BLOCK_ANCHORS,
    CUTOFF,
    GAP_MS,
    HORIZONS,
    LOOKBACK,
    MIN_EFFECT_DOLLARS,
    MIN_N,
    N_BOOT,
    N_SHUFFLE,
    PRIMARY,
    SEED,
    STABILITY,
    DirectionalScan,
    DiscoveryDataError,
    DiscoveryIdentity,
    EventTable,
    LockedSpanRefused,
    _cells,
    block_bootstrap,
    evaluate,
    sign_shuffle,
)
from qts.research.xauusd_directional_view import (
    AUTHORITY_SCHEMA,
    VIEW_SCHEMA,
    ViewAccessBlocked,
    preflight_view,
    scan_attested_view,
)


def _quotes(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bid = np.full(n, 99.89)
    ask = bid + 0.22
    stamp = np.arange(n, dtype=np.int64) * 1000
    return bid, ask, stamp


def _set_mid(bid: np.ndarray, ask: np.ndarray, row: int, mid: float, spread: float = 0.22) -> None:
    bid[row] = mid - spread / 2
    ask[row] = mid + spread / 2


def _events_for_test() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bid, ask, stamp = _quotes(3300)
    # Primary: global anchor 274 is high-up. Entry at 275, exit at 531.
    _set_mid(bid, ask, 274, 100.20)
    _set_mid(bid, ask, 275, 100.20, 0.30)
    _set_mid(bid, ask, 531, 100.70, 0.40)
    # Primary: global anchor 548 is low-up. Entry 549, exit 805.
    _set_mid(bid, ask, 548, 100.10)
    _set_mid(bid, ask, 549, 100.10)
    _set_mid(bid, ask, 805, 99.70)
    # Stability: global anchor 1042 is high-down. Entry 1043, exit 2067.
    _set_mid(bid, ask, 1042, 99.80)
    _set_mid(bid, ask, 1043, 99.80)
    _set_mid(bid, ask, 2067, 99.10)
    return bid, ask, stamp


def test_preregistration_cuts_horizons_and_cost_are_frozen() -> None:
    assert (PRIMARY, STABILITY) == (256, 1024)
    assert HORIZONS == (256, 1024)
    assert LOOKBACK == 16 and BLOCK_ANCHORS == 1024
    assert GAP_MS == 3_600_000 and MIN_N == 1000
    assert (N_BOOT, N_SHUFFLE, SEED, ALPHA) == (9999, 1999, 20260923, 0.01)
    assert CUTOFF == 1_764_563_969_254
    assert MIN_EFFECT_DOLLARS == 0.05
    text = Path("docs/xauusd_directional_next_step_2026-09-23.md").read_text(encoding="utf-8")
    for value in ("H-DIR-01", "256", "1024", "one-quote", "Holm-Bonferroni", "NOT TESTED"):
        assert value in text


def test_primary_sign_and_two_endpoint_spreads_use_delayed_entry() -> None:
    bid, ask, stamp = _events_for_test()
    scan = DirectionalScan(0, 6_600_000)
    scan.add_batch(bid, ask, stamp)
    primary, longer = scan.events(PRIMARY), scan.events(STABILITY)
    assert primary.anchor[:2].tolist() == [274, 548]
    assert primary.state[:2].tolist() == [1, 0]
    assert primary.sign[:2].tolist() == [1, 1]
    assert primary.gross[0] == pytest.approx(0.50)
    assert primary.net[0] == pytest.approx(0.50 - (0.30 + 0.40) / 2 - 0.02)
    assert primary.gross[1] == pytest.approx(-0.40)
    assert primary.net[1] == pytest.approx(-0.64)
    assert longer.anchor[0] == 1042
    assert longer.sign[0] == -1 and longer.state[0] == 1
    assert longer.gross[0] == pytest.approx(0.70)
    assert scan.exclusions[PRIMARY]["anchors"] >= len(primary)
    # Each horizon's full lookback/outcome windows cannot share a quote.
    for h in HORIZONS:
        anchors = scan.events(h).anchor
        assert not np.any(np.diff(anchors) < h + 18)


def test_exact_10_and_20_cent_state_boundaries_and_zero_exclusion() -> None:
    bid, ask, stamp = _quotes(1400)
    for i, mid in ((274, 100.20), (548, 100.10), (1096, 100.0)):
        _set_mid(bid, ask, i, mid)
    _set_mid(bid, ask, 822, 100.105, 0.21)  # half-cent mid from a cent-grid quote
    scan = DirectionalScan(0, 3_000_000)
    scan.add_batch(bid, ask, stamp)
    assert scan.events(PRIMARY).anchor.tolist() == [274, 548]
    assert scan.events(PRIMARY).state.tolist() == [1, 0]
    assert scan.exclusions[PRIMARY]["middle_state"] >= 1
    assert scan.exclusions[PRIMARY]["zero_sign"] >= 1


def test_chunk_boundaries_preserve_global_anchors_gap_and_prices() -> None:
    bid, ask, stamp = _events_for_test()
    stamp[300:] += GAP_MS  # one raw gap in the first 256-quote outcome window
    cutoff = 8_000_000
    whole = DirectionalScan(0, cutoff)
    chunks = DirectionalScan(0, cutoff)
    whole.add_batch(bid, ask, stamp)
    for start, end in ((0, 100), (100, 263), (263, 532), (532, 1040), (1040, 2200), (2200, len(stamp))):
        chunks.add_batch(bid[start:end], ask[start:end], stamp[start:end])
    for h in HORIZONS:
        a, b = whole.events(h), chunks.events(h)
        for field in EventTable.__dataclass_fields__:
            np.testing.assert_array_equal(getattr(a, field), getattr(b, field))
        assert whole.exclusions[h] == chunks.exclusions[h]
    assert whole.blocks == chunks.blocks
    assert whole.events(PRIMARY).gap_clear[0] == 0
    assert whole.events(PRIMARY).gap_clear[1] == 1
    assert len(whole.events(PRIMARY)) == len(chunks.events(PRIMARY))


def test_locked_stamp_refused_before_touching_any_quote_or_lookahead() -> None:
    class Poison:
        def __array__(self, *_args, **_kwargs):
            raise AssertionError("bid/ask should never be read")

    scan = DirectionalScan(0, 100)
    with pytest.raises(LockedSpanRefused):
        scan.add_batch(Poison(), Poison(), np.array([0, 10, 100]))
    assert scan.rows == 0 and scan.last_stamp is None
    # Never bridge the cutoff to finish a 256-quote forward window.
    bid, ask, stamp = _events_for_test()
    prefix = DirectionalScan(0, 500)
    prefix.add_batch(bid[:1], ask[:1], stamp[:1])
    with pytest.raises(LockedSpanRefused):
        prefix.add_batch(Poison(), Poison(), np.array([500]))
    assert prefix.rows == 1


def test_invalid_quote_timestamp_and_grid_fail_without_repair() -> None:
    bid, ask, stamp = _quotes(3)
    stamp[2] = stamp[1] - 1
    with pytest.raises(DiscoveryDataError, match="decreasing"):
        DirectionalScan(0, 100_000).add_batch(bid, ask, stamp)
    bid, ask, stamp = _quotes(3)
    ask[1] = bid[1] - 0.01
    with pytest.raises(DiscoveryDataError, match="inverted"):
        DirectionalScan(0, 100_000).add_batch(bid, ask, stamp)
    bid, ask, stamp = _quotes(3)
    bid[1] += 0.001
    with pytest.raises(DiscoveryDataError, match="one-cent"):
        DirectionalScan(0, 100_000).add_batch(bid, ask, stamp)


def _table(rows: list[tuple[int, int, int, int, int, float, float]]) -> EventTable:
    arr = np.array(rows, dtype=float)
    return EventTable(
        arr[:, 0].astype(np.int64),
        arr[:, 1].astype(np.int8),
        arr[:, 2].astype(np.int64),
        arr[:, 3].astype(np.int8),
        arr[:, 4].astype(np.int8),
        arr[:, 5],
        arr[:, 6],
        np.full(len(rows), 0.22),
        np.full(len(rows), 0.22),
        np.ones(len(rows), dtype=bool),
    )


def _balanced_tables() -> tuple[EventTable, set[tuple[int, int]]]:
    rows = []
    blocks = set()
    for t in range(3):
        for b in range(4):
            blocks.add((t, b))
            for sign in (1, -1):
                # High: sign-aligned future move; low: no alignment.
                rows.append((274 * (t * 4 + b + 1), t, b, 1, sign, 0.60, 0.36))
                rows.append((274 * (t * 4 + b + 1), t, b, 0, sign, 0.00, -0.24))
    return _table(rows), blocks


def test_balancing_bootstrap_and_shuffle_are_fixed_and_reproducible() -> None:
    events, blocks = _balanced_tables()
    stats = _cells(events)
    assert stats["T1_high_net"] == pytest.approx(0.36)
    assert stats["T2_high_minus_low_gross"] == pytest.approx(0.60)
    bootstrap = block_bootstrap(events, blocks, draws=49)
    assert bootstrap == block_bootstrap(events, blocks, draws=49)
    assert bootstrap is not None
    assert bootstrap["T1"]["lower_99"] == pytest.approx(0.36)
    shuffled = sign_shuffle(events, draws=99)
    assert shuffled == sign_shuffle(events, draws=99)
    assert shuffled is not None
    assert shuffled["T1_p"] > 0
    assert shuffled["T2_p"] > 0


def test_placebo_without_within_block_sign_variation_is_inconclusive() -> None:
    events, _ = _balanced_tables()
    for block in range(4):
        events.sign[events.block == block] = 1 if block % 2 else -1
    assert sign_shuffle(events, draws=9) is None


def test_sign_balancing_and_mirror_gate_cannot_select_a_winning_side(monkeypatch: pytest.MonkeyPatch) -> None:
    events, blocks = _balanced_tables()

    class FixtureScan:
        time_min, cutoff, rows = 0, 300, 500
        exclusions = {h: {"zero_sign": 0, "middle_state": 0, "anchors": 48} for h in HORIZONS}

        def __init__(self, primary: EventTable):
            self.primary = primary
            self.blocks = blocks

        def events(self, h: int) -> EventTable:
            return self.primary

        def boundary_exclusions(self, _h: int) -> int:
            return 0

    monkeypatch.setattr(
        "qts.research.xauusd_directional.block_bootstrap",
        lambda *_args, **_kwargs: {"T1": {"p": 0.00001, "lower_99": 0.12}, "T2": {"p": 0.00001, "lower_99": 0.12}},
    )
    monkeypatch.setattr(
        "qts.research.xauusd_directional.sign_shuffle",
        lambda *_args, **_kwargs: {"T1_p": 0.00001, "T2_p": 0.00001},
    )
    good = evaluate(FixtureScan(events), complete_rows=500, min_n=1, min_blocks=1)
    assert good["hypotheses"]["H-DIR-01"]["status"] == "SURVIVED_DISCOVERY_ONLY"
    assert good["decision"] == "INCONCLUSIVE"
    assert good["strategy_promoted"] is False and good["held_out_span_opened"] is False
    assert all(p == pytest.approx(0.00004) for p in good["measured"]["inference"]["p_holm"].values())

    costly = events.take(np.ones(len(events), dtype=bool))
    # Make the down sign unprofitable despite the up sign compensating.
    costly.net[costly.sign == -1] = -0.05
    failed = evaluate(FixtureScan(costly), complete_rows=500, min_n=1, min_blocks=1)
    assert failed["hypotheses"]["H-DIR-01"]["status"] == "REJECTED"
    assert failed["measured"]["gates"]["material_T1_and_T2"] is True
    assert failed["measured"]["gates"]["mirrors_terciles_1024_and_spacing"] is False

    no_identity = evaluate(FixtureScan(events), complete_rows=501, min_n=1, min_blocks=1)
    assert no_identity["hypotheses"]["H-DIR-01"]["status"] == "INCONCLUSIVE"
    assert no_identity["measured"]["inference"] is None

    too_small = events.take(np.ones(len(events), dtype=bool))
    too_small.net[(too_small.state == 1)] = 0.02
    below_floor = evaluate(FixtureScan(too_small), complete_rows=500, min_n=1, min_blocks=1)
    assert below_floor["hypotheses"]["H-DIR-01"]["status"] == "REJECTED"
    assert below_floor["measured"]["gates"]["material_T1_and_T2"] is False

    monkeypatch.setattr(
        "qts.research.xauusd_directional.sign_shuffle",
        lambda *_args, **_kwargs: {"T1_p": 0.4, "T2_p": 0.4},
    )
    unresolved = evaluate(FixtureScan(events), complete_rows=500, min_n=1, min_blocks=1)
    assert unresolved["hypotheses"]["H-DIR-01"]["status"] == "INCONCLUSIVE"
    assert unresolved["measured"]["gates"]["material_T1_and_T2"] is True
    assert unresolved["measured"]["gates"]["four_holm_p_below_0_01"] is False


def _view(tmp_path: Path, times: list[int], *, statistics: bool = True) -> tuple[Path, dict, DiscoveryIdentity]:
    root = tmp_path / "view"
    (root / "parts").mkdir(parents=True)
    path = root / "parts" / "part-000000.parquet"
    pq.write_table(
        pa.table(
            {"time_msc": pa.array(times, type=pa.int64()), "bid": [100.0] * len(times), "ask": [100.22] * len(times)}
        ),
        path,
        row_group_size=2,
        write_statistics=statistics,
    )
    identity = DiscoveryIdentity(
        time_min=0, cutoff=1000, rows=len(times), source_rows=10, zip_sha256="a" * 64, dataset_sha256="b" * 64
    )
    manifest = {
        "schema": VIEW_SCHEMA,
        "status": "COMPLETE_DISCOVERY_ONLY",
        "source_zip_sha256": identity.zip_sha256,
        "source_dataset_sha256": identity.dataset_sha256,
        "cutoff_time_msc": identity.cutoff,
        "time_msc_min": identity.time_min,
        "discovery_rows": identity.rows,
        "source_rows": identity.source_rows,
        "parts": [
            {
                "part": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "first_global_row": 0,
                "rows": len(times),
                "min_time_msc": min(times),
                "max_time_msc": max(times),
            }
        ],
    }
    data = json.dumps(manifest).encode("utf-8")
    (root / "manifest.json").write_bytes(data)
    authority = {
        "schema": AUTHORITY_SCHEMA,
        "view_manifest_sha256": hashlib.sha256(data).hexdigest(),
        "source_zip_sha256": identity.zip_sha256,
        "source_dataset_sha256": identity.dataset_sha256,
        "cutoff_time_msc": identity.cutoff,
        "discovery_rows": identity.rows,
    }
    return root, authority, identity


def test_attested_view_reads_only_discovery_and_is_not_a_real_result(tmp_path: Path) -> None:
    view, auth, identity = _view(tmp_path, [0, 100, 200, 300])
    paths, _ = preflight_view(view, auth, identity=identity)
    assert len(paths) == 1
    result = scan_attested_view(view, auth, identity=identity)
    assert result["hypotheses"]["H-DIR-01"]["status"] == "INCONCLUSIVE"
    assert result["window"]["held_out_rows_read"] == 0
    assert result["window"]["discovery_rows_read"] == 4
    assert result["view"]["view_manifest_sha256"] == auth["view_manifest_sha256"]


def test_crossing_row_group_rejected_before_any_part_hash_or_quote_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, auth, identity = _view(tmp_path, [0, 100, 200, 1000])
    from qts.research import xauusd_directional_view as module

    hash_original = module._sha256
    accessed: list[str] = []

    def spy(path: Path) -> str:
        accessed.append(path.name)
        if path.suffix == ".parquet":
            raise AssertionError("mixed part must not be hashed/read")
        return hash_original(path)

    monkeypatch.setattr(module, "_sha256", spy)
    with pytest.raises(ViewAccessBlocked, match="locked span"):
        preflight_view(view, auth, identity=identity)
    assert accessed == ["manifest.json"]  # the pinned manifest alone was enough

    # Even an independently pinned manifest whose own bounds *lie* is refused
    # by the Parquet footer, still before hashing the part or reading prices.
    altered = json.loads((view / "manifest.json").read_text())
    altered["parts"][0]["max_time_msc"] = 300
    payload = json.dumps(altered).encode()
    (view / "manifest.json").write_bytes(payload)
    auth["view_manifest_sha256"] = hashlib.sha256(payload).hexdigest()
    accessed.clear()
    with pytest.raises(ViewAccessBlocked, match="locked span"):
        preflight_view(view, auth, identity=identity)
    assert accessed == ["manifest.json"]


def test_unpinned_or_incomplete_view_refused_before_quote_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, auth, identity = _view(tmp_path, [0, 100, 200, 300])
    from qts.research import xauusd_directional_view as module

    def no_parquet(*_args, **_kwargs):
        raise AssertionError("Parquet must not be opened before manifest authorization")

    monkeypatch.setattr(module.pq, "ParquetFile", no_parquet)
    wrong = {**auth, "view_manifest_sha256": "0" * 64}
    with pytest.raises(ViewAccessBlocked, match="not independently pinned"):
        preflight_view(view, wrong, identity=identity)
    with pytest.raises(ViewAccessBlocked, match="authority"):
        preflight_view(view, {}, identity=identity)


def test_missing_rowgroup_stats_and_manifest_hole_are_refused(tmp_path: Path) -> None:
    no_stats, auth, identity = _view(tmp_path, [0, 100, 200, 300], statistics=False)
    with pytest.raises(ViewAccessBlocked, match="row group"):
        preflight_view(no_stats, auth, identity=identity)
    manifest = json.loads((no_stats / "manifest.json").read_text())
    manifest["parts"][0]["first_global_row"] = 1
    data = json.dumps(manifest).encode()
    (no_stats / "manifest.json").write_bytes(data)
    auth["view_manifest_sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ViewAccessBlocked, match="discontinuous"):
        preflight_view(no_stats, auth, identity=identity)


def test_cli_without_approved_view_reports_not_run_without_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import run_xauusd_directional as script

    monkeypatch.setattr(script, "AUTHORITY", tmp_path / "not-registered.json")
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    assert script.main(["--output", str(output), "--markdown", str(markdown), "--view-dir", str(tmp_path)]) == 2
    payload = json.loads(output.read_text())
    assert payload["hypotheses"]["H-DIR-01"]["status"] == "NOT RUN"
    assert payload["held_out_span_opened"] is False
    assert payload["window"]["held_out_rows_read"] == 0
    assert "CLOSED" in markdown.read_text()
    with pytest.raises(SystemExit):
        script.main(["--zip", "full-archive.zip"])


def test_cli_invalidates_a_misleading_view_instead_of_claiming_closed_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qts.research.xauusd_directional_view import ViewBoundaryViolation
    from scripts import run_xauusd_directional as script

    pinned = tmp_path / "authority.json"
    pinned.write_text("{}")
    monkeypatch.setattr(script, "AUTHORITY", pinned)
    monkeypatch.setattr(script, "preflight_view", lambda *_args: None)

    def violation(*_args):
        raise ViewBoundaryViolation("unexpected locked timestamp in synthetic view")

    monkeypatch.setattr(script, "scan_attested_view", violation)
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    assert script.main(["--output", str(output), "--markdown", str(markdown), "--view-dir", str(tmp_path)]) == 2
    payload = json.loads(output.read_text())
    assert payload["hypotheses"]["H-DIR-01"]["status"] == "INVALIDATED"
    assert payload["held_out_span_opened"] is True
    assert "VIOLATED" in markdown.read_text()
