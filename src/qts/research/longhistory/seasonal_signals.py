"""Calendar-seasonality signal families: session, trading day-of-week, payrolls.

Preregistration: ``docs/research/preregistration_longhistory_seasonal_2026-10-14.md``
(``LH-XAUUSD-SES-2026-10-14``). Every constant used by a builder is module- or
argument-level and mirrored in that document; nothing here is searched on data.

Contract (same as :mod:`qts.research.longhistory.signals`, checked by
:mod:`qts.research.longhistory.checks`):

* every value at bar ``t`` depends only on information available at ``t`` —
  in particular every ``target[t]`` is computed from the stamp of bar ``t``
  itself (the next bar's schedule is calendar, not data) and from statistics
  over occurrences that completed strictly earlier, so the truncation check
  (causality) passes at every cut;
* a :class:`Plan` written at close ``t`` executes at the OPEN of ``t+1``
  (the engine's next-available-open fill; a missing bar shifts the fill to the
  next existing row, as in every parent family);
* ``target`` is a position state (+1/-1/0) or NaN for "no change"; ``size`` is
  the no-stop vol-target convention of the parent cycles; there are no stops.

Mechanisms (public literature, stated ex ante in the preregistration):

* ``session_drift``   — liquidity/order-flow cycles anchored to the Asian
  physical market, London fix hours and the COMEX/US session can carry a
  persistent signed component inside fixed UTC windows.
* ``weekday_drift``   — calendar-driven flows (rolls, rebalancing programs,
  weekend risk repricing) can tilt particular trading days.
* ``nfp_drift``       — scheduled macro announcements are followed by slow
  information diffusion (post-payrolls drift). The direction never uses the
  current release: it comes only from earlier events.

Bar stamp semantics (open stamps) are established by
``data/evidence/longhistory/stamp_basis_probe.json``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory.daily import trading_day_label
from qts.research.longhistory.signals import Plan, _plan, size_vol_target

# ------------------------------------------------------------------ frozen knobs
#: Standard FX session taxonomy in UTC: (name, start hour inclusive, end exclusive).
SESSION_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("asia", 0, 7),
    ("europe", 7, 13),
    ("us", 13, 21),
)
#: PLACEBO control windows: fixed +3h rotation of the taxonomy inside [03:00, 21:00)
#: with the last window trimmed to keep [21:00, 24:00) flat for the control too.
PLACEBO_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("asia_c", 3, 10),
    ("europe_c", 10, 16),
    ("us_c", 16, 21),
)
#: [21:00, 24:00) UTC is maintenance halt + rollover: the session family never trades it.
FLAT_START_HOUR = 21
#: |t| floor for a direction to be tradeable, and warm-up counts.
T_FLOOR = 2.0
MIN_OCCURRENCES = 250
MIN_NFP_EVENTS = 48
#: Payrolls release: first Friday of the month at 08:30 ET (US DST rule).
NFP_LOCAL_HOUR = 8
NFP_LOCAL_MINUTE = 30
STEP = pd.Timedelta(minutes=15)


def _t_stat(mean: float, std: float, n: int) -> float:
    """Student t of an expanding mean; 0 when undetermined, +-inf when std == 0."""
    if n < 2:
        return 0.0
    if std > 0:
        return float(mean * np.sqrt(n) / std)
    if mean > 0:
        return float(np.inf)
    if mean < 0:
        return float(-np.inf)
    return 0.0


def _direction(mean: float, t_stat: float, n: int, min_occ: int, t_floor: float) -> float:
    """Frozen sign rule: sign(mean) only when |t| >= t_floor and n >= min_occ."""
    if not np.isfinite(mean) or n < min_occ or not (abs(t_stat) >= t_floor):
        return 0.0
    return float(np.sign(mean))


def _expanding_inclusive(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Row-wise (mean, t, n) over ``values[0..i]`` inclusive. Causal by construction."""
    n = len(values)
    mean = np.empty(n)
    std = np.empty(n)
    count = np.arange(1, n + 1, dtype=float)
    run_sum = 0.0
    # Welford for stable expanding variance
    m2 = 0.0
    cur_mean = 0.0
    for i, v in enumerate(values):
        run_sum += float(v)
        delta = float(v) - cur_mean
        cur_mean += delta / (i + 1)
        m2 += delta * (float(v) - cur_mean)
        mean[i] = cur_mean
        std[i] = np.sqrt(m2 / i) if i >= 1 else 0.0
    t = np.zeros(n)
    for i in range(n):
        t[i] = _t_stat(mean[i], std[i], i + 1)
    return mean, t, count


class _OccurrenceTable:
    """Occurrences of one family: sorted keys with inclusive expanding statistics.

    ``lookup_before(key)`` returns (mean, t, n) over all rows with key strictly
    before ``key`` — the exact information set of a decision taken before that
    occurrence, and identical on any chronological prefix (truncation-safe).
    """

    def __init__(self, keys: np.ndarray, values: np.ndarray) -> None:
        order = np.argsort(keys, kind="stable")
        self.keys = np.asarray(keys)[order]
        self.values = np.asarray(values, dtype=float)[order]
        self.mean, self.t, self.n = _expanding_inclusive(self.values)

    def __len__(self) -> int:
        return len(self.keys)

    def lookup_before(self, key: object) -> tuple[float, float, int]:
        pos = int(np.searchsorted(self.keys, np.datetime64(str(key)), side="left"))
        if pos == 0:
            return 0.0, 0.0, 0
        return float(self.mean[pos - 1]), float(self.t[pos - 1]), int(self.n[pos - 1])


# ------------------------------------------------------------------ session drift
def _session_occurrences(
    idx: pd.DatetimeIndex, bars: pd.DataFrame, windows: tuple[tuple[str, int, int], ...]
) -> dict[str, _OccurrenceTable]:
    """Per-window occurrence table with ``r = close[L]/open[F] - 1`` per date.

    An occurrence exists only when the window's first and last bar stamps are
    present (gaps stay gaps). Middle gaps do not delete an occurrence.
    """
    hour = idx.hour.to_numpy()
    close = bars["close"].to_numpy(dtype=float)
    opens = bars["open"].to_numpy(dtype=float)
    out: dict[str, _OccurrenceTable] = {}
    for name, h0, h1 in windows:
        rows = np.flatnonzero((hour >= h0) & (hour < h1))
        if rows.size == 0:
            out[name] = _OccurrenceTable(np.array([], dtype="datetime64[ns]"), np.array([]))
            continue
        dates = idx[rows].normalize()
        starts = np.flatnonzero(np.concatenate([[True], dates[1:] != dates[:-1]]))
        ends = np.concatenate([starts[1:], [len(rows)]])
        keys: list[pd.Timestamp] = []
        vals: list[float] = []
        for s_raw, e_raw in zip(starts, ends, strict=False):
            s, e = int(s_raw), int(e_raw)
            first_row = int(rows[s])
            last_row = int(rows[e - 1])
            if idx[first_row] != pd.Timestamp(dates[s]) + pd.Timedelta(hours=h0):
                continue  # first bar of the window missing: no occurrence
            keys.append(pd.Timestamp(dates[s]))
            vals.append(float(close[last_row] / opens[first_row] - 1.0))
        if keys:
            out[name] = _OccurrenceTable(np.array(keys, dtype="datetime64[ns]"), np.array(vals))
        else:
            out[name] = _OccurrenceTable(np.array([], dtype="datetime64[ns]"), np.array([]))
    return out


def session_drift(
    df: pd.DataFrame,
    strongest: bool,
    t_floor: float = T_FLOOR,
    min_occ: int = MIN_OCCURRENCES,
    ann: int = 23184,
    vol_n: int = 5520,
    windows: tuple[tuple[str, int, int], ...] = SESSION_WINDOWS,
) -> Plan:
    """Signed session-window drift; ``strongest`` trades only the top window per day."""
    idx = pd.DatetimeIndex(df.index)
    n = len(df)
    hour = idx.hour.to_numpy()
    stamps = idx.to_numpy()
    tables = _session_occurrences(idx, df, windows)
    starts = {h0: name for name, h0, _ in windows}
    ends = {h1 - 1 for _, _, h1 in windows}  # last minute stamp of a window
    in_window = np.zeros(n, dtype=bool)
    for _, h0, h1 in windows:
        in_window |= (hour >= h0) & (hour < h1)

    def decision(stamp: pd.Timestamp) -> tuple[float, bool]:
        """target for the bar whose stamp is ``stamp``: (value, is_decision)."""
        nxt = stamp + STEP
        nh = int(nxt.hour)
        if nh in starts and nxt.minute == 0:
            w = starts[nh]
            d = pd.Timestamp(nxt.normalize())
            if strongest:
                best_t, best_name, best_mean, best_n = 0.0, "", 0.0, 0
                for wname, _, _ in windows:
                    m, t, nn = tables[wname].lookup_before(d)
                    if abs(t) > best_t:
                        best_t, best_name, best_mean, best_n = abs(t), wname, m, nn
                if best_name != w or best_t < t_floor:
                    return 0.0, True
                return _direction(best_mean, best_t, best_n, min_occ, t_floor), True
            m, t, nn = tables[w].lookup_before(d)
            return _direction(m, t, nn, min_occ, t_floor), True
        return 0.0, False

    target = np.full(n, np.nan)
    size = size_vol_target(df, vol_n, ann)
    stop = np.full(n, np.nan)
    for i in range(n):
        stamp = pd.Timestamp(stamps[i])
        nxt = stamp + STEP
        nxt_starts_window = int(nxt.hour) in starts and nxt.minute == 0
        ends_window = int(stamp.hour) in ends and stamp.minute == 45
        if nxt_starts_window:
            # decision bar: the stamp 15 minutes before a scheduled window start
            target[i] = decision(stamp)[0]
        elif ends_window:
            target[i] = 0.0  # scheduled window end -> flat at the next open
        elif in_window[i]:
            target[i] = np.nan  # state persists inside a window
        else:
            target[i] = 0.0  # flat hours: explicit flat, never a trade
    params: dict[str, float | int | bool | str] = {
        "strongest": bool(strongest),
        "t_floor": t_floor,
        "min_occurrences": min_occ,
        "windows_utc": ",".join(f"{name}:{h0}-{h1}" for name, h0, h1 in windows),
        "flat_utc": f"{FLAT_START_HOUR}-24",
        "entry_rule": "decision at the last bar before the scheduled window start; fill at next open",
    }
    return _plan(df, "session_drift", params, target, size, stop)


# ------------------------------------------------------------------ weekday drift
def _weekday_expanding(
    idx: pd.DatetimeIndex, labels: pd.DatetimeIndex, opens: np.ndarray
) -> dict[int, _OccurrenceTable]:
    first_rows: dict[pd.Timestamp, int] = {}
    for i, lab in enumerate(labels):
        first_rows.setdefault(pd.Timestamp(lab), i)
    days = sorted(first_rows)
    by_wd: dict[int, tuple[list[pd.Timestamp], list[float]]] = {}
    for a, b in zip(days[:-1], days[1:], strict=False):
        wd = int(pd.Timestamp(a).dayofweek)
        by_wd.setdefault(wd, ([], []))[0].append(a)
        by_wd[wd][1].append(float(opens[first_rows[b]] / opens[first_rows[a]] - 1.0))
    out: dict[int, _OccurrenceTable] = {}
    for wd, (keys, vals) in by_wd.items():
        out[wd] = _OccurrenceTable(np.array(keys, dtype="datetime64[ns]"), np.array(vals))
    return out


def weekday_drift(
    df: pd.DataFrame,
    permuted: bool = False,
    t_floor: float = T_FLOOR,
    min_occ: int = MIN_OCCURRENCES,
    ann: int = 23184,
    vol_n: int = 5520,
) -> Plan:
    """Signed trading day-of-week drift; ``permuted`` builds the control.

    The control takes each weekday's direction from the NEXT weekday's
    statistics (fixed relabeling Mon<-Tue, ..., Fri<-Mon): same machinery,
    misaligned calendar anchor.
    """
    idx = pd.DatetimeIndex(df.index)
    n = len(df)
    labels = trading_day_label(idx)
    tables = _weekday_expanding(idx, labels, df["open"].to_numpy(dtype=float))

    def direction_for(day: pd.Timestamp) -> float:
        wd = int(day.dayofweek)
        if permuted:
            wd = wd + 1 if wd < 4 else 0  # Mon..Thu <- next day; Fri <- Mon
        table = tables.get(wd)
        if table is None:
            return 0.0
        m, t, nn = table.lookup_before(day)
        return _direction(m, t, nn, min_occ, t_floor)

    target = np.full(n, np.nan)
    size = size_vol_target(df, vol_n, ann)
    stop = np.full(n, np.nan)
    rebalance = np.zeros(n, dtype=bool)
    lab_arr = np.asarray(labels)
    for i in range(n - 1):
        # Decision at the last bar of trading day D-1 for day D: the label of
        # the NEXT ROW (a stamp, i.e. session calendar — never future data)
        # differs from this row's label. Reading the next row's *stamp* keeps
        # the weekly gap correct (Friday's close decides Monday) and, because
        # only the final bar of a truncated frame has no next row, the parent
        # truncation check's final-bar rebalance exemption covers exactly that
        # bar (see checks.truncation_check).
        nxt_label = pd.Timestamp(lab_arr[i + 1])
        if nxt_label == pd.Timestamp(lab_arr[i]):
            continue  # same trading day: state persists (NaN)
        target[i] = direction_for(nxt_label)  # enter/rotate at the next open
        rebalance[i] = True  # flag the decision (exemption + daily resize)
    params: dict[str, float | int | bool | str] = {
        "permuted_control": bool(permuted),
        "t_floor": t_floor,
        "min_occurrences": min_occ,
        "occurrence": "open_first[D+1]/open_first[D]-1",
        "weekday_basis": "trading-day label",
        "decision_rule": "label(next row) != label(row); decision bars carry rebalance=True",
    }
    return _plan(df, "weekday_drift", params, target, size, stop, rebalance=rebalance)


# ------------------------------------------------------------------ payrolls drift
def nfp_release_index(year_start: int, year_end: int) -> list[pd.Timestamp]:
    """First-Friday 08:30 ET releases as naive UTC timestamps (US DST rule)."""
    releases: list[pd.Timestamp] = []
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            d = pd.Timestamp(year=year, month=month, day=1)
            friday = int((d + pd.Timedelta(days=(4 - d.dayofweek) % 7)).day)
            local = pd.Timestamp(year=year, month=month, day=friday, hour=NFP_LOCAL_HOUR, minute=NFP_LOCAL_MINUTE)
            utc = local.tz_localize("America/New_York").tz_convert("UTC").tz_localize(None)
            releases.append(pd.Timestamp(utc))
    return releases


def nfp_drift(
    df: pd.DataFrame,
    hold_bars: int,
    t_floor: float = T_FLOOR,
    min_events: int = MIN_NFP_EVENTS,
    ann: int = 23184,
    vol_n: int = 5520,
) -> Plan:
    """Post-payrolls continuation: decision at the reaction bar's close, enter at
    the next open, hold ``hold_bars``, exit at the following open.

    Statistics use only *valid earlier occurrences* (contiguous windows of
    ``hold_bars + 1`` rows after the reaction bar, so ``r`` is computable);
    an event whose window is not contiguous contributes no occurrence. The
    decision itself depends only on those past statistics — never on the
    current event's future bars — so the plan is truncation-safe.
    """
    idx = pd.DatetimeIndex(df.index)
    n = len(df)
    target = np.zeros(n)
    size = size_vol_target(df, vol_n, ann)
    stop = np.full(n, np.nan)
    opens = df["open"].to_numpy(dtype=float)

    stamp_to_pos = {pd.Timestamp(ts): i for i, ts in enumerate(idx)}
    # running expanding statistics over valid occurrences (mean, std via Welford, count)
    count = 0
    cur_mean = 0.0
    m2 = 0.0

    for release in nfp_release_index(int(idx[0].year), int(idx[-1].year)):
        r_pos = stamp_to_pos.get(release)
        if r_pos is None:
            continue  # no bar at the release stamp (holiday/gap): no trade, no occurrence
        entry = r_pos + 1
        exitp = r_pos + 1 + hold_bars
        # decision from past statistics only (lag by one event: update after)
        std = float(np.sqrt(m2 / (count - 1))) if count >= 2 else 0.0
        t_stat = _t_stat(cur_mean, std, count)
        direction = _direction(cur_mean, t_stat, count, min_events, t_floor)
        if direction != 0.0:
            target[r_pos] = direction  # entry at the open of bar r_pos+1
            if r_pos + hold_bars < n:
                target[r_pos + hold_bars] = 0.0  # exit at the open of bar exitp
                for j in range(r_pos + 1, r_pos + hold_bars):
                    if j < n:
                        target[j] = np.nan  # hold: state persists
        # occurrence validity: contiguous window fully inside the series
        if exitp >= n:
            continue
        contiguous = idx[entry] == release + STEP and all(
            idx[entry + k] == idx[entry] + k * STEP for k in range(hold_bars + 1)
        )
        if not contiguous:
            continue  # missing bars inside the window: no occurrence
        r = float(opens[exitp] / opens[entry] - 1.0)
        count += 1
        delta = r - cur_mean
        cur_mean += delta / count
        m2 += delta * (r - cur_mean)

    params: dict[str, float | int | bool | str] = {
        "hold_bars": int(hold_bars),
        "t_floor": t_floor,
        "min_events": int(min_events),
        "release": "first Friday 08:30 ET (US DST)",
        "entry": "open of reaction bar + 1",
    }
    return _plan(df, "nfp_drift", params, target, size, stop)
