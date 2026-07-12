"""Frozen H4 helpers: gates first, outcomes only after primary admission."""

from __future__ import annotations

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


@dataclass(frozen=True)
class GateDecision:
    primary_channel: str
    all_primary_gates_passed: bool


def rolling_ac1(values: np.ndarray, window: int = 336) -> np.ndarray:
    """Causal rolling lag-1 correlation over a complete finite window."""

    series = pd.Series(np.asarray(values, dtype=float))
    left = series.shift(1)
    right = series
    pairs = window - 1
    sum_left = left.rolling(pairs, min_periods=pairs).sum()
    sum_right = right.rolling(pairs, min_periods=pairs).sum()
    sum_left2 = (left * left).rolling(pairs, min_periods=pairs).sum()
    sum_right2 = (right * right).rolling(pairs, min_periods=pairs).sum()
    sum_cross = (left * right).rolling(pairs, min_periods=pairs).sum()
    numerator = sum_cross - sum_left * sum_right / pairs
    denominator = np.sqrt(
        (sum_left2 - sum_left * sum_left / pairs)
        * (sum_right2 - sum_right * sum_right / pairs)
    )
    result = (numerator / denominator).to_numpy(dtype=float, copy=True)
    result[~np.isfinite(result)] = np.nan
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
    b_triv = intensity.rolling(12, min_periods=12).sum().to_numpy(dtype=float)
    residual = np.asarray(omega, dtype=float) - np.asarray(expected, dtype=float)
    b_var = pd.Series(residual).rolling(
        336, min_periods=336
    ).var(ddof=1).to_numpy(dtype=float)
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
    omega = part["omega"].to_numpy(dtype=float)
    expected = part["expected"].to_numpy(dtype=float)
    sigma_op = part["sigma_op"].to_numpy(dtype=bool)
    valid = part["valid"].to_numpy(dtype=bool)
    # The density diagnostic is partition-independent: its accumulator and
    # null both start at the partition boundary. The evaluated Γ itself is
    # never reset and remains the full causal trajectory.
    density_gamma = kernel_project(
        omega, expected, kernel_cfg, sigma_op=sigma_op
    )
    record = {
        "C3": check_degeneration(
            part["delta"].to_numpy(dtype=float)[valid],
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
