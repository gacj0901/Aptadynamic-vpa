from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from prama_protokol import KernelConfig, project as kernel_project

from aptadynamic_eg.h4 import (
    GateDecision,
    baseline_signals,
    construct_cascade_outcomes,
    holm_adjust,
    partition_gates,
    rolling_ac1,
    unlock_outcomes,
)


def test_rolling_ac1_matches_direct_complete_window():
    rng = np.random.default_rng(7)
    values = rng.normal(size=500)
    observed = rolling_ac1(values, window=48)
    assert observed.flags.writeable
    for stop in (47, 48, 200, 499):
        if stop < 47:
            assert np.isnan(observed[stop])
        else:
            expected = np.corrcoef(
                values[stop - 47:stop], values[stop - 46:stop + 1]
            )[0, 1]
            assert observed[stop] == pytest.approx(expected, abs=1e-12)


def test_frozen_baselines_are_prefix_invariant_after_calibration():
    n = 1200
    split = 700
    intensity = (np.arange(n) % 17 == 0).astype(float)
    omega = np.sin(np.arange(n) / 23.0) + 2.0
    expected = np.roll(omega, 24)
    expected[:24] = np.nan
    full = baseline_signals(intensity, omega, expected, split)
    prefix = baseline_signals(
        intensity[:1000], omega[:1000], expected[:1000], split
    )
    for name in full:
        assert np.array_equal(full[name][:1000], prefix[name], equal_nan=True)


def test_outcome_construction_is_locked_until_primary_gates_pass():
    events = pd.DataFrame(
        {"t_out": [100, 200], "t_in": [150, 250], "duration_s": [50, 50]}
    )
    failed = GateDecision("CH-L", False)
    with pytest.raises(RuntimeError, match="outcomes are locked"):
        construct_cascade_outcomes(events, failed)

    record = {
        "C2": {"passed": True},
        "calibration": {"all_passed": True},
        "evaluation": {"all_passed": True},
        "N1": {"passed": True},
        "sigma_op": {"passed": True},
    }
    decision = unlock_outcomes("CH-L", record)
    assert decision.all_primary_gates_passed
    assert "cascade_id" in construct_cascade_outcomes(events, decision)


def test_holm_adjustment_is_step_down_and_monotone():
    adjusted = holm_adjust({"a": 0.01, "b": 0.03, "c": 0.02})
    assert adjusted == {"a": 0.03, "c": 0.04, "b": 0.04}


def test_partition_gate_rebuilds_a_consistent_density_accumulator():
    n = 1200
    omega = 2.0 + 0.3 * np.sin(np.arange(n) / 13.0)
    expected = np.roll(omega, 24)
    expected[:48] = np.nan
    sigma = np.ones(n, dtype=bool)
    gamma = kernel_project(omega, expected, KernelConfig(), sigma_op=sigma)
    gamma.loc[300:325, "valid"] = False
    gamma["omega"] = omega
    gamma["expected"] = expected
    gamma["sigma_op"] = sigma
    record = partition_gates(
        gamma, np.arange(n) % 24, 100, n,
        rho_band=(-1.0, 1.0), n_null=8, null_seed=11,
        f_star=0.0, min_memory_ratio=1.0,
    )
    assert record["C4"]["detail"].startswith("C4_D =")
    assert record["C4"]["passed"] is True
    assert record["MEM"]["passed"] is True
    assert np.isfinite(record["C3"]["r_degenerate"])
