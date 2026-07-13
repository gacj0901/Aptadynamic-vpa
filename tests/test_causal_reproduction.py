from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aptadynamic_eg.ingest import (
    _epoch_seconds,
    automatic_only,
    automatic_only_with_audit,
    load_bpa,
)
from aptadynamic_eg.evaluation import (
    apply_frozen_threshold, cascade_evaluation_rows, circular_shift_null,
    fit_frozen_budget_calibration, paired_cascade_bootstrap,
)


def test_epoch_seconds_preserves_missing_and_drops_invalid(tmp_path):
    values = pd.Series(["2020-01-01T00:00:00Z", "not-a-date", "2020-01-01T01:00:00Z"])
    out = _epoch_seconds(values)
    assert str(out.dtype) == "Int64"
    assert out.iloc[0] == 1577836800
    assert out.iloc[1] is pd.NA
    assert out.iloc[2] == 1577840400
    assert -9223372037 not in out.dropna().tolist()
    path = tmp_path / "events.csv"
    pd.DataFrame({"OutDatetime": values, "InDatetime": values}).to_csv(path, index=False)
    loaded = load_bpa(path)
    assert len(loaded) == 2
    assert loaded["t_out"].max() - loaded["t_out"].min() == 3600


def test_mathematica_absolute_time_is_converted_to_unix_epoch():
    values = pd.Series([3124217220, 3124217280])
    out = _epoch_seconds(values, numeric_epoch="mathematica_1900")
    assert out.tolist() == [915228420, 915228480]
    assert pd.to_datetime(out.iloc[0], unit="s", utc=True).year == 1999


def test_confirmatory_outage_filter_fails_closed_without_type_column():
    events = pd.DataFrame({"t_out": [1, 2]})
    with pytest.raises(ValueError, match="requires outage_type"):
        automatic_only(events, require_column=True)
    # Exploratory behavior remains explicitly backward compatible.
    assert automatic_only(events).equals(events.reset_index(drop=True))


def test_outage_filter_excludes_and_counts_unrecognized_values():
    events = pd.DataFrame(
        {"outage_type": ["Auto", " forced ", "planned", "mystery", None]}
    )
    filtered, record = automatic_only_with_audit(events, require_column=True)
    assert filtered["outage_type"].tolist() == ["Auto", " forced "]
    assert record["n_before"] == 5
    assert record["n_after"] == 2
    assert record["n_excluded"] == 3
    assert record["unrecognized_value_counts"] == {
        "<missing>": 1,
        "mystery": 1,
        "planned": 1,
    }


def test_evaluation_is_strictly_pre_cascade_and_valid_only():
    proj = pd.DataFrame({"t": np.arange(8) * 3600, "valid": [False, True, True, True, True, True, True, True],
                         "latent_collapse": [False, False, True, False, True, False, False, False]})
    events = pd.DataFrame({"cascade_id": [1, 2, 2], "t_out": [2*3600, 5*3600, 5*3600]})
    rows = cascade_evaluation_rows(proj, events)
    assert np.array_equal(rows["evaluation_idx"], rows["start_idx"] - 1)
    assert rows["evaluation_idx"].tolist() == [1, 4]
    assert rows["prama_alert"].tolist() == [False, True]


def test_frozen_baseline_never_refits_on_evaluation_data():
    x = np.arange(100, dtype=float)
    alert = (x % 10) == 0
    valid = np.ones(100, dtype=bool)
    calibration = fit_frozen_budget_calibration(x, alert, valid, 40, "calib_test", 17)
    changed = x.copy(); changed[40:] = -999
    calibration_changed = fit_frozen_budget_calibration(changed, alert, valid, 40, "calib_test", 17)
    assert calibration == calibration_changed
    assert np.array_equal(
        apply_frozen_threshold(x, np.array([40, 60, 90]), calibration),
        x[[40, 60, 90]] >= calibration["threshold"],
    )


def test_boundary_ties_are_seeded_and_match_expected_budget():
    x = np.array([0.0] * 50 + [1.0] * 50)
    alert = np.zeros(100, dtype=bool); alert[:25] = True
    calibration = fit_frozen_budget_calibration(
        x, alert, np.ones(100, dtype=bool), 100, "ties_v1", 123
    )
    assert calibration["threshold"] == 1.0
    assert calibration["boundary_accept_probability"] == 0.5
    idx = np.arange(100)
    a = apply_frozen_threshold(x, idx, calibration)
    b = apply_frozen_threshold(x, idx[::-1], calibration)[::-1]
    assert np.array_equal(a, b)
    assert a.sum() == calibration["target_alert_count"] == 25


def test_paired_bootstrap_preserves_row_pairing():
    rows = pd.DataFrame({
        "in_range": [True] * 8, "valid": [True] * 8,
        "size": [1, 5, 1, 5, 1, 5, 1, 5],
        "prama_alert": [False, True, False, True, False, True, False, True],
    })
    baseline = np.array([False, False, True, True, False, False, True, True])
    a = paired_cascade_bootstrap(rows, baseline, 4, 100, 9)
    b = paired_cascade_bootstrap(rows, baseline, 4, 100, 9)
    assert a == b
    assert a["unit"] == "cascade"
    assert "not a centered bootstrap null test" in (
        a["p_one_sided_prama_superior_semantics"]
    )


def test_circular_null_is_seeded_and_reports_corrected_p():
    latent = np.tile([False, False, True, True], 40)
    idx = np.arange(24, 140, 5)
    severe = (idx % 3) == 0
    a = circular_shift_null(latent, idx, severe, 100, seed=7, min_shift=8)
    b = circular_shift_null(latent, idx, severe, 100, seed=7, min_shift=8)
    assert a == b
    assert 1/101 <= a["p_corrected"] <= 1
    assert all(k in a for k in ("null_p90", "null_p95", "null_p99", "shift_rule"))
