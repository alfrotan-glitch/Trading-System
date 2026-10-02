# Running the QTS test suite

This repo has 1479 collected tests across 95 files. Measured on CI hardware
class (2-core sandbox used for these measurements; GitHub Actions
`ubuntu-latest` typically has more cores, so CI is faster than these numbers):

| Command | What it runs | Measured time |
|---|---|---|
| `pytest tests/unit -q` | Fast developer loop: pure logic, no I/O-heavy fixtures | ~2s |
| `pytest tests/unit tests/adversarial -q` | Unit + safety/authorization boundary tests | ~45s |
| `pytest -q -m "not slow"` | Everything except Hypothesis/property-based tests | ~95s (parallel) |
| `pytest -q -n auto --dist loadscope` | **Full suite, parallelized (recommended default)** | ~100s (2 cores) / 951s sequential |
| `pytest -q` | Full suite, sequential (CI's old behaviour, still correct) | ~800-950s |
| `pytest tests/ui/test_browser.py -q` | Real-browser E2E (Playwright) | skipped unless `pip install playwright && playwright install chromium` |

## Fast developer loop (seconds)

Run only what's relevant to the file you're changing. Pytest's own path/`-k`
targeting is the mechanism — no custom tooling needed:

```bash
# Just the tests for the module you touched:
pytest tests/unit/test_risk.py -q

# Everything whose name matches a keyword:
pytest -q -k "kill_switch"

# A whole fast layer:
pytest tests/unit -q
```

## Normal local verification (under a minute)

```bash
pytest -q -m "not slow" -n auto --dist loadscope
```

Excludes the Hypothesis/property-based layer (`tests/property/test_properties.py`,
marked `slow` — see below) and runs everything else in parallel.

## Full suite (what CI runs)

```bash
pytest -q -n auto --dist loadscope
```

Runs all 1479 tests, including the `slow`-marked property-based layer. This
is the suite CI gates on; nothing is skipped by default — `--dist loadscope`
only changes which worker process runs a given test file, not what runs.

`--dist loadscope` groups every test in the same file onto the same worker.
This is deliberately more conservative than the default `--dist load` (which
freely interleaves individual test items across workers): two real
cross-test hazards were found and fixed while making this suite
parallel-safe (see `QTS_PROJECT_CONTROL.md` and the architecture test
`tests/test_architecture_boundaries.py`), and keeping a whole file on one
worker is a standing safety margin against any hazard like them that isn't
caught yet, at negligible cost (`loadscope` measured *faster* than `load` in
this repo — 98-106s vs 222s — because `load`'s finer-grained interleaving
pays module-import/fixture-setup costs repeatedly across workers).

## Exhaustive / release verification

```bash
pytest -q --run-integration -n auto --dist loadscope
pip install playwright && playwright install chromium
pytest tests/ui/test_browser.py -q
```

`--run-integration` exists for historical reasons (`tests/integration/`
already runs by default; the flag's original purpose — opting a test in via
`@pytest.mark.integration` — currently has zero tests using that marker, so
today it is a no-op kept for backward CLI compatibility). The browser suite
requires Playwright + a Chromium install, which is why it is not a dev
dependency: it is the `VERY SLOW` / real-browser tier, run on demand or in a
release-verification job, not every PR.

## Layers (by directory, evidence from `--durations=0`)

| Directory | Tests | Measured `call`-time sum | What it is |
|---|---|---|---|
| `tests/unit/` | 113 | 1.8s | Pure component logic |
| `tests/property/` | 6 | 7.0s | Hypothesis property-based (`test_properties.py`, 3 tests, marked `slow`) + 3 fast property tests on impulse detection (not marked — measured 0.3-0.9s each, genuinely fast) |
| `tests/integration/` | 148 | 9.9s | Multi-component workflows (session wiring, autopilot loop, CLI) |
| `tests/adversarial/` | 353 | 10.6s | Security/authorization/safety boundary tests — the largest single category |
| `tests/ui/` | 23 (+ `test_browser.py`, 0 collected without Playwright) | 10.3s | JS unit tests invoked from Python (`test_ui_logic.py`) + browser E2E |
| `tests/research/` | 204 | 17.5s | Research pipeline / hypothesis-specific modules |
| `tests/` (flat, ~38 files) | 632 | 44.6s | Mixed: CLI, MT5 history, encoding, DB lifecycle, architecture guards |

The flat `tests/` directory is the largest bucket by test count (632 of
1479) but is NOT where the suite's slowness came from — see
`QTS_PROJECT_CONTROL.md` for the actual root cause (a per-test teardown hook
with unbounded, never-pruned state, costing 810 of 945 measured seconds
before the fix). Only 18 of 1479 tests individually take ≥1.0s; the problem
was never "some slow tests," it was fixed per-test overhead × test count,
which parallelization is the correct, proportionate answer to.

## Markers

- `slow` — individually expensive (property-based/Hypothesis). Excluded by
  `-m "not slow"`. Applied once, to `tests/property/test_properties.py`
  (measured 6-7s combined), based on actual timing data — not applied
  suite-wide or to the whole `tests/property/` directory, because the other
  3 property tests in that directory measured 0.3-0.9s each and are not
  slow.
- `integration` — registered for backward CLI compatibility
  (`--run-integration`); no test currently uses it, since `tests/integration/`
  already runs by default (see `tests/conftest.py`'s
  `pytest_collection_modifyitems` docstring for why a keyword-based skip was
  removed).

No other markers were introduced. The directory structure already encodes a
reasonable fast/medium/slow boundary (see table above); adding markers on
top of it for every test would be marker proliferation for no measured
benefit.
