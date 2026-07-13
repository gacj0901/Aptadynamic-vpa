"""Frozen H4 helpers: gates first, outcomes only after primary admission."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd
from prama_protokol import KernelConfig, project as kernel_project
from prama_protokol.compliance import (
    check_degeneration,
    check_density,
    check_inductive_ratio,
    check_memory_ratio,
)

from .omega import cascades


BASELINE_NAMES = ("B-TRIV", "B-VAR", "B-AC1", "B-COMP")
OUTCOME_COLUMNS_CONSTRUCTED = (
    "cascade_id",
    "cascade_size",
    "severe_cascade",
)


@dataclass(frozen=True)
class GateDecision:
    primary_channel: str
    all_primary_gates_passed: bool


def outcome_access_record(accessed: bool) -> dict:
    """Return internally consistent outcome-access report metadata."""

    return {
        "outcomes_accessed": bool(accessed),
        "outcome_columns_constructed": (
            list(OUTCOME_COLUMNS_CONSTRUCTED) if accessed else []
        ),
    }


def cascade_boundary_table(events: pd.DataFrame, cut_epoch: int) -> pd.DataFrame:
    """Summarize cascade membership relative to an exclusive UTC cut."""

    required = {"cascade_id", "t_out"}
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"cascade boundary audit missing columns: {sorted(missing)}")
    grouped = events.groupby("cascade_id", sort=True)["t_out"]
    table = grouped.agg(first_t_out="min", last_t_out="max", size="size")
    table["complete_calibration"] = table["last_t_out"] < int(cut_epoch)
    table["evaluation"] = table["first_t_out"] >= int(cut_epoch)
    table["crosses_boundary"] = (
        (table["first_t_out"] < int(cut_epoch))
        & (table["last_t_out"] >= int(cut_epoch))
    )
    return table


def restrict_rows_to_cascade_partition(
    rows: pd.DataFrame,
    events: pd.DataFrame,
    cut_epoch: int,
    partition: str,
) -> pd.DataFrame:
    """Exclude incomplete or cross-boundary cascades from a frozen partition."""

    table = cascade_boundary_table(events, cut_epoch)
    if partition == "calibration":
        allowed = table.index[table["complete_calibration"]]
    elif partition == "evaluation":
        allowed = table.index[table["evaluation"]]
    else:
        raise ValueError("partition must be 'calibration' or 'evaluation'")
    result = rows.copy()
    result.loc[~result["cascade_id"].isin(allowed), "in_range"] = False
    return result


def cascade_boundary_audit(events: pd.DataFrame, cut_epoch: int) -> dict:
    """Build the reproducible, privacy-safe G2 cut-boundary audit payload."""

    table = cascade_boundary_table(events, cut_epoch)
    crossing = table[table["crosses_boundary"]]
    hashes = []
    for cascade_id, row in crossing.iterrows():
        identity = (
            f"{cascade_id}|{int(row['first_t_out'])}|"
            f"{int(row['last_t_out'])}|{int(row['size'])}"
        )
        hashes.append(hashlib.sha256(identity.encode("utf-8")).hexdigest())
    # The pre-audit runner admitted calibration rows by their pre-cascade
    # evaluation index. Every crossing cascade starts before the cut and was
    # therefore selected by that legacy partition rule before validity masks.
    legacy_crossing = crossing[crossing["first_t_out"] < int(cut_epoch)]
    return {
        "cut_epoch": int(cut_epoch),
        "cut_utc": pd.Timestamp(int(cut_epoch), unit="s", tz="UTC").isoformat(),
        "n_total_cascades": int(len(table)),
        "n_complete_calibration_cascades": int(table["complete_calibration"].sum()),
        "n_evaluation_cascades": int(table["evaluation"].sum()),
        "n_cross_boundary_cascades": int(table["crosses_boundary"].sum()),
        "cross_boundary_cascade_sha256": sorted(hashes),
        "n_cross_boundary_selected_by_legacy_calibration_rule": int(
            len(legacy_crossing)
        ),
        "any_cross_boundary_in_legacy_calibration_rows": bool(len(legacy_crossing)),
        "corrected_partition_rule": (
            "calibration requires last_t_out < cut; evaluation requires "
            "first_t_out >= cut; crossing cascades belong to neither"
        ),
    }


def common_valid_mask(
    projection_valid: np.ndarray,
    signals: dict[str, np.ndarray],
) -> np.ndarray:
    """Return a writable same-points mask for PRAMA and every comparator."""

    result = np.array(projection_valid, dtype=bool, copy=True)
    for signal in signals.values():
        result &= np.isfinite(signal)
    return result


def rolling_ac1(values: np.ndarray, window: int = 336) -> np.ndarray:
    """Causal rolling lag-1 correlation using pairwise-complete clock hours."""

    series = pd.Series(np.asarray(values, dtype=float))
    left = series.shift(1)
    right = series
    pairs = window - 1
    pair_valid = left.notna() & right.notna()
    count = pair_valid.astype(float).rolling(pairs, min_periods=1).sum()
    pair_left = left.where(pair_valid, 0.0)
    pair_right = right.where(pair_valid, 0.0)
    sum_left = pair_left.rolling(pairs, min_periods=1).sum()
    sum_right = pair_right.rolling(pairs, min_periods=1).sum()
    sum_left2 = (pair_left * pair_left).rolling(pairs, min_periods=1).sum()
    sum_right2 = (pair_right * pair_right).rolling(pairs, min_periods=1).sum()
    sum_cross = (pair_left * pair_right).rolling(pairs, min_periods=1).sum()
    numerator = sum_cross - sum_left * sum_right / count
    denominator = np.sqrt(
        (sum_left2 - sum_left * sum_left / count)
        * (sum_right2 - sum_right * sum_right / count)
    )
    result = (numerator / denominator).to_numpy(dtype=float, copy=True)
    result[(count.to_numpy(copy=True) < 2) | ~np.isfinite(result)] = np.nan
    return result


def frozen_ecdf(values: np.ndarray, calibration: np.ndarray) -> np.ndarray:
    """Map values to a calibration-frozen right-continuous empirical rank."""

    values = np.asarray(values, dtype=float)
    calibration = np.sort(np.asarray(calibration, dtype=float))
    calibration = calibration[np.isfinite(calibration)]
    if len(calibration) == 0:
        raise ValueError("cannot freeze an ECDF without calibration values")
    result = np.full(len(values), np.nan)
    valid = np.isfinite(values)
    result[valid] = np.searchsorted(
        calibration, values[valid], side="right"
    ) / len(calibration)
    return result


def baseline_signals(
    outage_intensity: np.ndarray,
    omega: np.ndarray,
    expected: np.ndarray,
    calibration_end_idx: int,
) -> dict[str, np.ndarray]:
    """Build the four causal, H3-frozen baseline signals."""

    intensity = pd.Series(np.asarray(outage_intensity, dtype=float))
    b_triv = intensity.rolling(12, min_periods=12).sum().to_numpy(
        dtype=float, copy=True
    )
    residual = np.asarray(omega, dtype=float) - np.asarray(expected, dtype=float)
    b_var = pd.Series(residual).rolling(
        336, min_periods=2
    ).var(ddof=1).to_numpy(dtype=float, copy=True)
    b_ac1 = rolling_ac1(residual, window=336)
    cal = slice(0, calibration_end_idx)
    rank_var = frozen_ecdf(b_var, b_var[cal])
    rank_ac1 = frozen_ecdf(b_ac1, b_ac1[cal])
    b_comp = (rank_var + rank_ac1) / 2.0
    return {
        "B-TRIV": b_triv,
        "B-VAR": b_var,
        "B-AC1": b_ac1,
        "B-COMP": b_comp,
    }


def partition_gates(
    gamma: pd.DataFrame,
    context: np.ndarray,
    start: int,
    stop: int,
    rho_band: tuple[float, float],
    n_null: int,
    null_seed: int,
    f_star: float = 1.5,
    min_memory_ratio: float = 20.0,
    kernel_cfg: KernelConfig | None = None,
) -> dict:
    """Compute H3 observation gates on one independent partition."""

    if kernel_cfg is None:
        kernel_cfg = KernelConfig()
    part = gamma.iloc[start:stop]
    omega = part["omega"].to_numpy(dtype=float, copy=True)
    expected = part["expected"].to_numpy(dtype=float, copy=True)
    sigma_op = part["sigma_op"].to_numpy(dtype=bool, copy=True)
    valid = part["valid"].to_numpy(dtype=bool, copy=True)
    # The density diagnostic is partition-independent: its accumulator and
    # null both start at the partition boundary. The evaluated Γ itself is
    # never reset and remains the full causal trajectory.
    density_gamma = kernel_project(
        omega, expected, kernel_cfg, sigma_op=sigma_op
    )
    record = {
        "C3": check_degeneration(
            part["delta"].to_numpy(dtype=float, copy=True)[valid],
            omega[valid], r_star=0.5, s_min=0.01,
        ),
        "RHO_I": check_inductive_ratio(omega, expected, band=rho_band),
        "C4": check_density(
            density_gamma,
            kernel_cfg,
            context=np.asarray(context)[start:stop],
            n_null=n_null,
            seed=null_seed,
            f_star=f_star,
        ),
        "MEM": check_memory_ratio(
            kernel_cfg, n_cal=stop - start, min_ratio=min_memory_ratio
        ),
    }
    record["all_passed"] = all(item["passed"] is True for item in record.values())
    return record


def unlock_outcomes(primary_channel: str, gate_record: dict) -> GateDecision:
    """Create the only token that permits construction of cascade outcomes."""

    required = ("C2", "calibration", "evaluation", "N1", "sigma_op")
    complete = all(key in gate_record for key in required)
    passed = complete and all(
        (
            gate_record[key].get("all_passed", False)
            if key in {"calibration", "evaluation"}
            else gate_record[key].get("passed") is True
        )
        for key in required
    )
    return GateDecision(primary_channel, passed)


def construct_cascade_outcomes(
    events: pd.DataFrame,
    decision: GateDecision,
) -> pd.DataFrame:
    """Construct outcome rows only after every primary observation gate passes."""

    if not decision.all_primary_gates_passed:
        raise RuntimeError(
            "evaluation outcomes are locked because primary observation gates failed"
        )
    return cascades(events)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjustment with monotonicity restoration."""

    ordered = sorted(p_values, key=lambda name: (p_values[name], name))
    total = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, name in enumerate(ordered):
        candidate = min(1.0, (total - rank) * float(p_values[name]))
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted
