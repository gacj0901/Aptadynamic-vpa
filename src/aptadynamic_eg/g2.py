"""G2 multichannel observation contracts for the NYISO domain.

This module implements only the observation and induction side of H2.  It
never constructs cascades or reads evaluation outcomes.
"""

from __future__ import annotations

import inspect
import hashlib
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from prama_protokol import KernelConfig, project as kernel_project

from .omega import expected_profile


NYISO_ZONES = (
    "CAPITL", "CENTRL", "DUNWOD", "GENESE", "HUD VL", "LONGIL",
    "MHK VL", "MILLWD", "N.Y.C.", "NORTH", "WEST",
)

CHANNEL_ARCHIVES = {
    "CH-L": ("pal", "{date}pal_csv.zip", "pal.csv", "Load"),
    "CH-P": (
        "realtime", "{date}realtime_zone_csv.zip", "realtime_zone.csv",
        "LBMP ($/MWHr)",
    ),
}


@dataclass(frozen=True)
class G2InterfaceConfig:
    min_context_count: int = 10
    min_hist: int = 720
    trailing_days: int = 1096
    bin_seconds: int = 3600
    load_floor_fraction: float = 0.05


def estimator_source_hash(function) -> str:
    return hashlib.sha256(inspect.getsource(function).encode("utf-8")).hexdigest()


def month_range(start: str, end: str) -> list[pd.Timestamp]:
    return [period.to_timestamp() for period in pd.period_range(start, end, freq="M")]


def archive_path(cache: Path, channel: str, month: pd.Timestamp) -> Path:
    _, template, _, _ = CHANNEL_ARCHIVES[channel]
    return cache / channel / template.format(date=month.strftime("%Y%m01"))


def local_to_utc(frame: pd.DataFrame, channel: str) -> pd.Series:
    """Convert published NYISO local timestamps with explicit DST handling."""

    naive = pd.to_datetime(frame["Time Stamp"], errors="coerce")
    if channel == "CH-L":
        offsets = frame["Time Zone"].map({"EDT": 4, "EST": 5})
        return (naive + pd.to_timedelta(offsets, unit="h")).dt.tz_localize("UTC")

    result = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[us, UTC]")
    for _, indices in frame.groupby("Name", sort=False).groups.items():
        result.loc[indices] = (
            naive.loc[indices]
            .dt.tz_localize(
                "America/New_York", ambiguous="infer", nonexistent="shift_forward"
            )
            .dt.tz_convert("UTC")
        )
    return result


def hourly_from_slots(slot_values: pd.Series, channel: str) -> pd.DataFrame:
    """Apply the H2 complete-case 12-slot hourly aggregation rule."""

    if not isinstance(slot_values.index, pd.DatetimeIndex):
        raise TypeError("slot_values must use a DatetimeIndex")
    if slot_values.index.tz is None:
        raise ValueError("slot_values timestamps must be timezone-aware")
    slot_values = slot_values.sort_index()
    if slot_values.index.has_duplicates:
        raise ValueError("duplicate 5-minute timestamps in channel stream")

    hour_index = slot_values.index.floor("h")
    grouped = slot_values.groupby(hour_index)
    count = grouped.count()
    expected_minutes = frozenset(range(0, 60, 5))
    slot_geometry = pd.DataFrame(
        {
            "hour": hour_index,
            "minute": slot_values.index.minute,
            "seconds_zero": (
                (slot_values.index.second == 0)
                & (slot_values.index.microsecond == 0)
            ),
        }
    ).groupby("hour", sort=True).agg(
        n_timestamps=("minute", "size"),
        minutes=("minute", lambda values: frozenset(int(v) for v in values)),
        seconds_zero=("seconds_zero", "all"),
    )
    exact_grid = (
        slot_geometry["n_timestamps"].eq(12)
        & slot_geometry["minutes"].eq(expected_minutes)
        & slot_geometry["seconds_zero"]
    )
    if channel == "CH-L":
        value = grouped.mean()
        name = "nyca_load_hourly"
    elif channel == "CH-P":
        value = grouped.std(ddof=1)
        name = "lbmp_intrahour_std"
    else:
        raise ValueError(f"unsupported G2 source channel: {channel}")
    valid = count.eq(12) & exact_grid.reindex(count.index, fill_value=False) & value.notna()
    value = value.where(valid)
    return pd.DataFrame({name: value, f"{channel.lower()}_valid": valid})


def load_hourly_channel(
    cache: Path,
    channel: str,
    start: str = "2008-11",
    end: str = "2020-12",
) -> pd.DataFrame:
    """Read cached NYISO archives and construct one H2 hourly channel."""

    _, _, member_suffix, value_column = CHANNEL_ARCHIVES[channel]
    slot_parts: list[pd.Series] = []
    for month in month_range(start, end):
        path = archive_path(cache, channel, month)
        if not path.exists():
            raise FileNotFoundError(f"missing H2 source archive: {path}")
        with zipfile.ZipFile(path) as zipped:
            members = sorted(
                name for name in zipped.namelist() if name.endswith(member_suffix)
            )
            for member in members:
                with zipped.open(member) as handle:
                    frame = pd.read_csv(handle)
                frame["utc"] = local_to_utc(frame, channel)
                internal = frame[frame["Name"].isin(NYISO_ZONES)].copy()
                table = internal.pivot(
                    index="utc", columns="Name", values=value_column
                ).reindex(columns=NYISO_ZONES)
                complete = table.notna().all(axis=1)
                if channel == "CH-L":
                    slot = table.sum(axis=1, min_count=len(NYISO_ZONES))
                else:
                    slot = table.mean(axis=1, skipna=False)
                slot_parts.append(slot.where(complete))

    slots = pd.concat(slot_parts).sort_index()
    if slots.index.has_duplicates:
        duplicates = int(slots.index.duplicated().sum())
        raise ValueError(f"{channel} contains {duplicates} duplicate slot timestamps")
    return hourly_from_slots(slots, channel)


def build_hourly_domain(
    cache: Path,
    outages: pd.DataFrame,
    start: str = "2008-11",
    end: str = "2020-12",
) -> pd.DataFrame:
    """Build the hourly triple-coverage grid without outcome construction."""

    load = load_hourly_channel(cache, "CH-L", start=start, end=end)
    price = load_hourly_channel(cache, "CH-P", start=start, end=end)

    outage_start = pd.to_datetime(outages["t_out"].min(), unit="s", utc=True).ceil("h")
    # Only bins fully contained in the outage record are included.
    outage_end_exclusive = pd.to_datetime(
        outages["t_in"].max(), unit="s", utc=True
    ).floor("h")
    start_utc = max(outage_start, load.index.min(), price.index.min())
    end_exclusive = min(
        outage_end_exclusive, load.index.max() + pd.Timedelta(hours=1),
        price.index.max() + pd.Timedelta(hours=1),
    )
    grid = pd.date_range(
        start_utc, end_exclusive - pd.Timedelta(hours=1), freq="h", tz="UTC"
    )
    domain = load.reindex(grid).join(price.reindex(grid), how="left")
    domain.index.name = "time_utc"
    domain["ch-l_valid"] = domain["ch-l_valid"].fillna(False).astype(bool)
    domain["ch-p_valid"] = domain["ch-p_valid"].fillna(False).astype(bool)

    starts = pd.to_datetime(outages["t_out"], unit="s", utc=True).dt.floor("h")
    counts = starts.value_counts().reindex(grid, fill_value=0).sort_index()
    domain["outage_intensity"] = counts.to_numpy(dtype=float, copy=True)
    domain["ch-f_valid"] = True
    return domain


def context_codes(index: pd.DatetimeIndex, day_type: bool = True) -> np.ndarray:
    """Encode H2 context: UTC month/hour and optional New York day type."""

    month = index.month.to_numpy(dtype=np.int16, copy=True)
    hour = index.hour.to_numpy(dtype=np.int16, copy=True)
    code = month * 100 + hour
    if day_type:
        weekend = (index.tz_convert("America/New_York").dayofweek >= 5).astype(np.int16)
        code = code * 10 + weekend
    return np.asarray(code)


def causal_trailing_conditional_mean(
    values: np.ndarray,
    context: np.ndarray,
    timestamps: pd.DatetimeIndex,
    valid: np.ndarray,
    min_context_count: int = 10,
    min_hist: int = 720,
    trailing_days: int = 1096,
) -> np.ndarray:
    """Strict-past conditional mean with an H2 trailing per-cell window.

    Invalid observations neither receive an expectation nor update any
    statistic. ``min_hist`` is a global warm-up gate, not a fallback
    estimator: a row is defined only when the global gate and its own
    trailing context-count gate have both opened.
    """

    values = np.asarray(values, dtype=float)
    context = np.asarray(context)
    valid = np.asarray(valid, dtype=bool) & np.isfinite(values)
    if not (len(values) == len(context) == len(timestamps) == len(valid)):
        raise ValueError("values, context, timestamps and valid must align")

    expected = np.full(len(values), np.nan)
    histories: dict[int, deque] = defaultdict(deque)
    sums: dict[int, float] = defaultdict(float)
    global_count = 0
    window = pd.Timedelta(days=trailing_days)

    for i, value in enumerate(values):
        if not valid[i]:
            continue
        key = int(context[i])
        cutoff = timestamps[i] - window
        history = histories[key]
        while history and history[0][0] < cutoff:
            _, expired = history.popleft()
            sums[key] -= expired
        if global_count >= min_hist and len(history) >= min_context_count:
            expected[i] = sums[key] / len(history)
        history.append((timestamps[i], float(value)))
        sums[key] += float(value)
        global_count += 1
    return expected


def find_verification_cut(
    domain: pd.DataFrame,
    warmup_valid_hours: int = 720,
) -> dict:
    """Apply H2 Verification 1's mechanical annual-cycle cut rule."""

    if domain.empty:
        raise ValueError("empty G2 domain")
    valid_load = domain.index[domain["ch-l_valid"]]
    if len(valid_load) < warmup_valid_hours:
        raise ValueError("CH-L does not contain the required 720 valid warm-up hours")
    start = domain.index[0]
    end_exclusive = domain.index[-1] + pd.Timedelta(hours=1)
    warmup_end = valid_load[warmup_valid_hours - 1] + pd.Timedelta(hours=1)

    cycles: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for year in range(start.year, end_exclusive.year + 1):
        cycle_start = pd.Timestamp(f"{year}-01-01T00:00:00Z")
        cycle_end = pd.Timestamp(f"{year + 1}-01-01T00:00:00Z")
        if cycle_start >= warmup_end and cycle_start >= start and cycle_end <= end_exclusive:
            cycles.append((cycle_start, cycle_end))
    if len(cycles) < 2:
        raise ValueError("triple coverage does not contain two post-warm-up annual cycles")
    selected = cycles[:2]
    return {
        "start_utc": start,
        "end_exclusive_utc": end_exclusive,
        "warmup_end_exclusive_utc": warmup_end,
        "cycles": selected,
        "calibration_end_exclusive_utc": selected[-1][1],
    }


def normalize_and_project(
    domain: pd.DataFrame,
    channel: str,
    calibration_end: pd.Timestamp,
    cfg: G2InterfaceConfig | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Normalize, induce and project one H2 channel using calibration only."""

    if cfg is None:
        cfg = G2InterfaceConfig()
    calibration = domain.index < calibration_end
    if channel == "CH-L":
        raw = domain["nyca_load_hourly"].to_numpy(dtype=float, copy=True)
        valid = domain["ch-l_valid"].to_numpy(dtype=bool, copy=True) & (raw > 0)
        reference = float(np.median(raw[calibration & valid]))
        omega = raw / reference
        context = context_codes(domain.index, day_type=True)
        expected = causal_trailing_conditional_mean(
            omega, context, domain.index, valid,
            min_context_count=cfg.min_context_count,
            min_hist=cfg.min_hist,
            trailing_days=cfg.trailing_days,
        )
        driver = "nyca_load_hourly"
        epoch = "nyiso_chl_induction_v1"
        estimator = causal_trailing_conditional_mean
        normalization = "L(t) / median_calibration_valid_L"
    elif channel == "CH-P":
        raw = domain["lbmp_intrahour_std"].to_numpy(dtype=float, copy=True)
        valid = domain["ch-p_valid"].to_numpy(dtype=bool, copy=True)
        reference = float(np.median(raw[calibration & valid]))
        omega = np.log1p(raw / reference)
        context = context_codes(domain.index, day_type=True)
        expected = causal_trailing_conditional_mean(
            omega, context, domain.index, valid,
            min_context_count=cfg.min_context_count,
            min_hist=cfg.min_hist,
            trailing_days=cfg.trailing_days,
        )
        driver = "lbmp_intrahour_std"
        epoch = "nyiso_chp_induction_v1"
        estimator = causal_trailing_conditional_mean
        normalization = "log1p(s(t) / median_calibration_valid_s)"
    elif channel == "CH-F":
        raw = domain["outage_intensity"].to_numpy(dtype=float, copy=True)
        valid = domain["ch-f_valid"].to_numpy(dtype=bool, copy=True)
        reference = 1.0
        omega = raw.copy()
        context = context_codes(domain.index, day_type=False)
        om = pd.DataFrame({"t": domain.index.as_unit("s").asi8, "outage_intensity": omega})
        expected = expected_profile(
            om, driver="outage_intensity",
            min_context_count=cfg.min_context_count, min_hist=cfg.min_hist,
        )
        driver = "outage_intensity"
        epoch = "nyiso_chf_induction_v2"
        estimator = expected_profile
        normalization = "identity on hourly outage-start count"
    else:
        raise ValueError(f"unknown G2 channel: {channel}")

    kernel_omega = np.where(valid, omega, 0.0)
    expected = np.where(valid, expected, np.nan)
    load_cal = calibration & domain["ch-l_valid"].to_numpy(dtype=bool, copy=True)
    q_floor = cfg.load_floor_fraction * float(
        np.median(domain["nyca_load_hourly"].to_numpy(dtype=float, copy=True)[load_cal])
    )
    sigma_op = (
        domain["ch-l_valid"].to_numpy(dtype=bool, copy=True)
        & (domain["nyca_load_hourly"].to_numpy(dtype=float, copy=True) > q_floor)
        & valid
    )
    kernel_cfg = KernelConfig()
    gamma = kernel_project(kernel_omega, expected, kernel_cfg, sigma_op=sigma_op)
    gamma.index = domain.index
    gamma["omega"] = kernel_omega
    gamma["expected"] = expected
    gamma["sigma_valid"] = valid
    gamma["sigma_op"] = sigma_op
    metadata = {
        "channel": channel,
        "driver": driver,
        "epoch_id": epoch,
        "normalization": normalization,
        "reference": reference,
        "q_floor": q_floor,
        "context": context,
        "estimator": estimator.__name__,
        "estimator_hash": estimator_source_hash(estimator),
        "regime": "trailing_1096_days_per_cell" if channel != "CH-F" else "expanding",
    }
    return gamma, metadata
