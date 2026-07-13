from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aptadynamic_eg.drivers import DRIVER_SPECS
from aptadynamic_eg.g2 import (
    causal_trailing_conditional_mean,
    context_codes,
    find_verification_cut,
    hourly_from_slots,
    normalize_and_project,
)


def test_complete_case_hourly_contracts():
    index = pd.date_range("2020-01-01T00:00:00Z", periods=24, freq="5min")
    load = pd.Series(np.arange(24, dtype=float), index=index)
    load_hourly = hourly_from_slots(load, "CH-L")
    assert load_hourly["ch-l_valid"].tolist() == [True, True]
    assert load_hourly["nyca_load_hourly"].iloc[0] == 5.5

    price = load.copy()
    price.iloc[3] = np.nan
    price_hourly = hourly_from_slots(price, "CH-P")
    assert price_hourly["ch-p_valid"].tolist() == [False, True]
    assert np.isnan(price_hourly["lbmp_intrahour_std"].iloc[0])
    assert price_hourly["lbmp_intrahour_std"].iloc[1] == np.std(
        np.arange(12, 24, dtype=float), ddof=1
    )


def test_hourly_slots_require_exact_five_minute_grid():
    correct = pd.Series(
        np.arange(12, dtype=float),
        index=pd.date_range("2020-01-01T00:00:00Z", periods=12, freq="5min"),
    )
    assert bool(hourly_from_slots(correct, "CH-L")["ch-l_valid"].iloc[0])

    missing = correct.drop(correct.index[4])
    assert not bool(hourly_from_slots(missing, "CH-L")["ch-l_valid"].iloc[0])

    duplicated = pd.concat([correct, correct.iloc[[0]]])
    with pytest.raises(ValueError, match="duplicate 5-minute timestamps"):
        hourly_from_slots(duplicated, "CH-L")

    irregular_index = pd.DatetimeIndex(
        [pd.Timestamp("2020-01-01T00:00:01Z") + pd.Timedelta(minutes=5 * i)
         for i in range(12)]
    )
    irregular = pd.Series(np.arange(12, dtype=float), index=irregular_index)
    assert not bool(hourly_from_slots(irregular, "CH-L")["ch-l_valid"].iloc[0])


def test_trailing_estimator_is_prefix_invariant_and_skips_invalid_rows():
    index = pd.date_range("2019-01-01T00:00:00Z", periods=1200, freq="h")
    values = (np.arange(len(index)) % 13).astype(float)
    context = context_codes(index, day_type=True)
    valid = np.ones(len(index), dtype=bool)
    valid[800] = False
    full = causal_trailing_conditional_mean(
        values, context, index, valid, min_context_count=2, min_hist=48
    )
    prefix = causal_trailing_conditional_mean(
        values[:900], context[:900], index[:900], valid[:900],
        min_context_count=2, min_hist=48,
    )
    assert np.array_equal(full[:900], prefix, equal_nan=True)
    assert np.isnan(full[800])


def test_trailing_estimator_accepts_read_only_arrays_without_mutation():
    index = pd.date_range("2019-01-01T00:00:00Z", periods=100, freq="h")
    values = np.arange(100, dtype=float)
    context = np.arange(100, dtype=np.int64) % 4
    valid = np.ones(100, dtype=bool)
    for array in (values, context, valid):
        array.flags.writeable = False
    observed = causal_trailing_conditional_mean(
        values, context, index, valid,
        min_context_count=1, min_hist=1, trailing_days=10,
    )
    assert len(observed) == 100
    assert not values.flags.writeable
    assert not context.flags.writeable
    assert not valid.flags.writeable


def test_verification_cut_is_mechanical():
    index = pd.date_range(
        "2008-11-02T13:00:00Z", "2011-02-01T00:00:00Z", freq="h",
        inclusive="left",
    )
    domain = pd.DataFrame(
        {
            "ch-l_valid": True,
            "ch-p_valid": True,
            "ch-f_valid": True,
        },
        index=index,
    )
    result = find_verification_cut(domain)
    assert [start.year for start, _ in result["cycles"]] == [2009, 2010]
    assert result["calibration_end_exclusive_utc"] == pd.Timestamp(
        "2011-01-01T00:00:00Z"
    )


def test_h2_projection_uses_validity_and_shared_sigma_op():
    index = pd.date_range("2008-01-01T00:00:00Z", periods=1800, freq="h")
    domain = pd.DataFrame(index=index)
    domain["nyca_load_hourly"] = 10_000.0 + np.sin(np.arange(len(index)) / 24)
    domain["lbmp_intrahour_std"] = 5.0 + np.cos(np.arange(len(index)) / 24)
    domain["outage_intensity"] = (np.arange(len(index)) % 17 == 0).astype(float)
    domain["ch-l_valid"] = True
    domain["ch-p_valid"] = True
    domain["ch-f_valid"] = True
    domain.loc[index[900], "ch-l_valid"] = False

    gamma, metadata = normalize_and_project(
        domain, "CH-L", calibration_end=index[1500]
    )
    assert metadata["epoch_id"] == "nyiso_chl_induction_v1"
    assert not gamma.loc[index[900], "valid"]
    assert gamma.loc[index[900], "delta"] == 0.0
    assert not gamma.loc[index[900], "sigma_op"]


def test_h2_drivers_are_registered_as_causal():
    assert DRIVER_SPECS["nyca_load_hourly"]["causal"] is True
    assert DRIVER_SPECS["lbmp_intrahour_std"]["causal"] is True
    assert DRIVER_SPECS["severity"]["causal"] is False


def test_h2_physical_channels_are_scale_invariant():
    index = pd.date_range("2008-01-01T00:00:00Z", periods=1800, freq="h")
    base = pd.DataFrame(index=index)
    base["nyca_load_hourly"] = 10_000.0 + 500.0 * np.sin(
        np.arange(len(index)) / 24
    )
    base["lbmp_intrahour_std"] = 5.0 + np.cos(np.arange(len(index)) / 24)
    base["outage_intensity"] = (np.arange(len(index)) % 17 == 0).astype(float)
    base["ch-l_valid"] = True
    base["ch-p_valid"] = True
    base["ch-f_valid"] = True
    calibration_end = index[1500]
    columns = ["delta", "xi", "lambda", "theta", "M", "G", "valid"]

    for channel, raw_column in (
        ("CH-L", "nyca_load_hourly"),
        ("CH-P", "lbmp_intrahour_std"),
    ):
        reference, _ = normalize_and_project(base, channel, calibration_end)
        scaled = base.copy()
        scaled[raw_column] *= 1000.0
        alternative, _ = normalize_and_project(scaled, channel, calibration_end)
        pd.testing.assert_frame_equal(
            reference[columns], alternative[columns], check_exact=False,
            rtol=0.0, atol=1e-9,
        )
