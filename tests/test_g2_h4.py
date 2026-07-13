from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from prama_protokol import KernelConfig, project as kernel_project

from aptadynamic_eg.h4 import (
    GateDecision,
    baseline_signals,
    cascade_boundary_audit,
    cascade_boundary_table,
    common_valid_mask,
    construct_cascade_outcomes,
    holm_adjust,
    outcome_access_record,
    partition_gates,
    rolling_ac1,
    restrict_rows_to_cascade_partition,
    unlock_outcomes,
)
from aptadynamic_eg.evaluation import fit_frozen_budget_calibration


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


def test_rolling_ac1_uses_pairwise_complete_hours_without_imputation():
    rng = np.random.default_rng(17)
    values = rng.normal(size=200)
    values[[70, 73, 101]] = np.nan
    observed = rolling_ac1(values, window=48)
    stop = 110
    window = values[stop - 47:stop + 1]
    left, right = window[:-1], window[1:]
    valid = np.isfinite(left) & np.isfinite(right)
    expected = np.corrcoef(left[valid], right[valid])[0, 1]
    assert observed[stop] == pytest.approx(expected, abs=1e-12)


def test_frozen_baselines_are_prefix_invariant_after_calibration():
    n = 1200
    split = 700
    intensity = (np.arange(n) % 17 == 0).astype(float)
    omega = np.sin(np.arange(n) / 23.0) + 2.0
    expected = np.roll(omega, 24)
    expected[:24] = np.nan
    expected[np.arange(n) % 97 == 0] = np.nan
    full = baseline_signals(intensity, omega, expected, split)
    prefix = baseline_signals(
        intensity[:1000], omega[:1000], expected[:1000], split
    )
    for name in full:
        assert np.array_equal(full[name][:1000], prefix[name], equal_nan=True)
    assert np.isfinite(full["B-VAR"][split - 1])
    assert np.isfinite(full["B-AC1"][split - 1])


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


def test_common_valid_mask_is_writable_with_pandas_backed_input():
    source = pd.Series([True, True, False]).to_numpy(dtype=bool)
    result = common_valid_mask(source, {"x": np.array([1.0, np.nan, 2.0])})
    assert result.flags.writeable
    assert result.tolist() == [True, False, False]


def test_frozen_budget_handles_read_only_inputs_without_mutation():
    signal = np.arange(100, dtype=float)
    alert = signal % 10 == 0
    valid = np.ones(100, dtype=bool)
    for array in (signal, alert, valid):
        array.flags.writeable = False
    record = fit_frozen_budget_calibration(
        signal, alert, valid, 80, "readonly", 7
    )
    assert record["n_valid_calibration_bins"] == 80
    assert not signal.flags.writeable
    assert not alert.flags.writeable
    assert not valid.flags.writeable


def test_cross_boundary_cascade_belongs_to_neither_partition():
    cut = 1_000
    events = pd.DataFrame(
        {
            "cascade_id": [1, 1, 2, 2, 3],
            "t_out": [100, 200, 900, 1_100, 2_000],
        }
    )
    table = cascade_boundary_table(events, cut)
    assert table.loc[1, "complete_calibration"]
    assert table.loc[2, "crosses_boundary"]
    assert table.loc[3, "evaluation"]

    rows = pd.DataFrame(
        {
            "cascade_id": [1, 2, 3],
            "in_range": [True, True, True],
        }
    )
    calibration = restrict_rows_to_cascade_partition(
        rows, events, cut, "calibration"
    )
    evaluation = restrict_rows_to_cascade_partition(
        rows, events, cut, "evaluation"
    )
    assert calibration["in_range"].tolist() == [True, False, False]
    assert evaluation["in_range"].tolist() == [False, False, True]

    audit = cascade_boundary_audit(events, cut)
    assert audit["n_total_cascades"] == 3
    assert audit["n_complete_calibration_cascades"] == 1
    assert audit["n_evaluation_cascades"] == 1
    assert audit["n_cross_boundary_cascades"] == 1
    assert audit["any_cross_boundary_in_legacy_calibration_rows"] is True
    assert len(audit["cross_boundary_cascade_sha256"][0]) == 64


def test_outcome_report_metadata_cannot_contradict_access_state():
    assert outcome_access_record(False) == {
        "outcomes_accessed": False,
        "outcome_columns_constructed": [],
    }
    final = outcome_access_record(True)
    assert final["outcomes_accessed"] is True
    assert final["outcome_columns_constructed"] == [
        "cascade_id", "cascade_size", "severe_cascade"
    ]


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
