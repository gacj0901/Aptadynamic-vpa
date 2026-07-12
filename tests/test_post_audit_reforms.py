from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aptadynamic_eg.omega import expected_profile, omega_series
from aptadynamic_eg.projection import ProjectionConfig, project


ROOT = Path(__file__).resolve().parents[1]


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "t_out": [1_577_838_600, 1_577_925_000],  # 00:30 UTC on adjacent days
            "t_in": [1_577_844_600, 1_577_930_400],
            "duration_s": [6_000, 5_400],
            "voltage_kv": [230.0, 230.0],
        }
    )


def test_utc_alignment_and_legacy_bin_semantics():
    aligned = omega_series(_events(), align_utc=True)
    legacy = omega_series(_events(), align_utc=False)
    assert np.all(aligned["t"].to_numpy(dtype=np.int64) % 3600 == 0)
    assert int(legacy["t"].iloc[0]) == int(_events()["t_out"].min())

    # On the aligned grid, the second day's same UTC-hour cell sees the first
    # day's value through the strict-past conditional mean.
    expected = expected_profile(aligned, min_context_count=1, min_hist=10_000)
    hours = pd.to_datetime(aligned["t"], unit="s", utc=True).dt.hour
    second_day = int(np.flatnonzero((aligned["t"] - aligned["t"].iloc[0]) == 24 * 3600)[0])
    assert hours.iloc[0] == hours.iloc[second_day] == 0
    assert expected[second_day] == aligned["intensity"].iloc[0]


def test_expected_profile_is_prefix_invariant():
    n = 2000
    om = pd.DataFrame(
        {
            "t": 1_577_836_800 + np.arange(n, dtype=np.int64) * 3600,
            "intensity": (np.arange(n) % 7).astype(float),
        }
    )
    full = expected_profile(om, min_context_count=2, min_hist=48)
    for stop in (1, 47, 48, 731, n):
        prefix = expected_profile(om.iloc[:stop], min_context_count=2, min_hist=48)
        assert np.array_equal(full[:stop], prefix, equal_nan=True)


def test_driver_registry_blocks_future_information_and_labels_escape_hatch():
    om = omega_series(_events(), align_utc=True)
    with pytest.raises(ValueError, match=r"ANOMALIES.md \(b\)"):
        project(om, ProjectionConfig(driver="severity", min_hist=1))
    with pytest.raises(ValueError, match=r"ANOMALIES.md \(b\)"):
        project(om, ProjectionConfig(driver="load", min_hist=1))

    causal = project(om, ProjectionConfig(driver="intensity", min_hist=1))
    assert not causal["noncausal_driver"].any()
    exploratory = project(
        om,
        ProjectionConfig(
            driver="severity",
            min_hist=1,
            allow_noncausal_exploratory=True,
        ),
    )
    assert exploratory["noncausal_driver"].all()


def test_tau_is_consistent_across_code_readme_and_frozen_g1():
    assert ProjectionConfig().tau_memory == 336
    assert "tau_memory=336" in (ROOT / "PREREGISTRATION_G1.md").read_text(encoding="utf-8")
    assert "τ = 336 h" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_schema_v2_and_g1_evidence_reproduction(tmp_path):
    dataset = ROOT / "data" / "dobson_bpa" / "outagesBPA.csv"
    evidence = ROOT / "evidence" / "BPA" / "2026-07-11T08-52-49Z.csv"
    if not dataset.exists():
        pytest.skip("licensed/local BPA dataset is not present")

    output = tmp_path / "legacy_bpa_smoke"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reproduce_bpa.py"),
            str(dataset),
            "--domain", "BPA",
            "--calibration-id", "bpa_calib_1999_2003_v1",
            "--calibration-end", "2004-01-01T00:00:00Z",
            "--n-permutations", "20",
            "--n-bootstrap", "20",
            "--diagnostic-n-null", "20",
            "--smoke-test",
            "--output-prefix", str(output),
        ],
        cwd=ROOT,
        check=True,
    )

    report = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 2
    assert report["run_mode"] == "smoke_test"
    assert report["confirmatory_eligible"] is False
    assert report["interface_config"]["align_utc"] is False
    assert report["interface_config"]["noncausal_driver"] is False
    assert report["induction"]["epoch_id"] == "bpa_induction_v1"
    assert report["induction"]["regime"] == "expanding"
    assert report["induction"]["estimator_hash"] == hashlib.sha256(
        inspect.getsource(expected_profile).encode("utf-8")
    ).hexdigest()
    assert set(report["kernel_config"]) == {
        "tau_memory", "lambda_eq", "lambda_recovery", "lambda_min",
        "theta_scale", "g_smooth", "kappa",
    }

    observed = pd.read_csv(output.with_suffix(".csv"))
    frozen = pd.read_csv(evidence)
    deterministic = [column for column in frozen.columns if column != "null_p_corrected"]
    pd.testing.assert_frame_equal(
        observed[deterministic],
        frozen[deterministic],
        check_exact=True,
        check_dtype=False,
    )
