"""Observation operator O_D for electrical-grid outage events."""

from __future__ import annotations

import numpy as np
import pandas as pd

GAP_S = 3600
BIN_S = 3600


def cascades(df: pd.DataFrame, gap_s: int = GAP_S) -> pd.DataFrame:
    """Assign cascade ids by temporal gaps between outage starts."""

    if df.empty:
        out = df.copy()
        out["cascade_id"] = pd.Series(dtype=int)
        return out
    out = df.sort_values("t_out").reset_index(drop=True).copy()
    t = out["t_out"].to_numpy()
    new = np.concatenate([[True], np.diff(t) > gap_s])
    out["cascade_id"] = np.cumsum(new)
    return out


def cascade_sizes(df: pd.DataFrame) -> pd.Series:
    return df.groupby("cascade_id").size()


def omega_series(
    df: pd.DataFrame,
    bin_s: int = BIN_S,
    align_utc: bool = True,
) -> pd.DataFrame:
    """Convert outage events to hourly observable streams.

    ``intensity`` counts outage starts, ``load`` counts active outages, and
    ``severity`` accumulates voltage-weighted log duration in each start bin.
    """

    if df.empty:
        raise ValueError("cannot build omega series from an empty event frame")

    ev = df.sort_values("t_out").reset_index(drop=True).copy()
    ev["t_in"] = ev["t_in"].fillna(ev["t_out"])

    if align_utc:
        t0 = (int(ev["t_out"].min()) // bin_s) * bin_s
        t1 = -((-int(ev["t_in"].max())) // bin_s) * bin_s
        # Keep a full bin when the final event/restoration lies exactly on an
        # aligned boundary; every observable event must belong to one bin.
        edges = np.arange(t0, t1 + bin_s + 1, bin_s)
    else:
        # G1 frozen semantics — see ANOMALIES.md (a).
        t0 = int(ev["t_out"].min())
        t1 = int(ev["t_in"].max())
        edges = np.arange(t0, t1 + bin_s + 1, bin_s)
    n = len(edges) - 1

    intensity = np.zeros(n)
    severity = np.zeros(n)
    load = np.zeros(n)

    idx = np.clip(((ev["t_out"].to_numpy() - t0) // bin_s).astype(int), 0, n - 1)
    np.add.at(intensity, idx, 1.0)

    volt = ev.get("voltage_kv", pd.Series(1.0, index=ev.index)).fillna(0.0).to_numpy()
    dur = ev["duration_s"].fillna(0.0).clip(lower=0).to_numpy()
    np.add.at(severity, idx, volt * np.log1p(dur))

    i0 = idx
    i1 = np.clip(((ev["t_in"].to_numpy() - t0) // bin_s).astype(int), 0, n - 1)
    for start, end in zip(i0, i1):
        load[start : end + 1] += 1.0

    return pd.DataFrame(
        {
            "t": edges[:-1],
            "intensity": intensity,
            "load": load,
            "severity": severity,
        }
    )


def expected_profile(
    om: pd.DataFrame,
    driver: str = "intensity",
    min_context_count: int = 10,
    min_hist: int = 24 * 30,
) -> np.ndarray:
    """Strictly causal E[driver | month, hour] with global warm-up fallback."""

    if driver not in om.columns:
        raise ValueError(f"driver {driver!r} not present in omega columns: {list(om.columns)}")

    t = pd.to_datetime(om["t"], unit="s", utc=True)
    hour = t.dt.hour.to_numpy()
    month = t.dt.month.to_numpy()
    values = om[driver].to_numpy(dtype=float)

    expected = np.empty(len(values))
    sums = np.zeros((12, 24))
    counts = np.zeros((12, 24))
    global_sum, global_n = 0.0, 0

    for i, value in enumerate(values):
        h, mo = hour[i], month[i] - 1
        if counts[mo, h] >= min_context_count:
            expected[i] = sums[mo, h] / counts[mo, h]
        elif global_n >= min_hist:
            expected[i] = global_sum / global_n
        else:
            expected[i] = np.nan
        sums[mo, h] += value
        counts[mo, h] += 1
        global_sum += value
        global_n += 1

    return expected
