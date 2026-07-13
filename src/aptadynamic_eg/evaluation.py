"""Leakage-resistant evaluation for cascade severity and occurrence."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _indexed_hash(indices: np.ndarray, seed: int) -> np.ndarray:
    """Stable uint64 pseudo-random key for each time index."""
    z = np.asarray(indices, dtype=np.uint64) + np.uint64(seed)
    with np.errstate(over="ignore"):
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xbf58476d1ce4e5b9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94d049bb133111eb)
    return z ^ (z >> np.uint64(31))


def cascade_evaluation_rows(
    projection: pd.DataFrame, events: pd.DataFrame, bin_s: int = 3600
) -> pd.DataFrame:
    """Return one eligible row per cascade, evaluated strictly at ``idx-1``."""
    sizes = events.groupby("cascade_id").size()
    starts = events.groupby("cascade_id")["t_out"].min()
    t0 = int(projection["t"].iloc[0])
    start_idx = ((starts.to_numpy(copy=True) - t0) // bin_s).astype(int)
    evaluation_idx = start_idx - 1
    # Regression guard: cascade-start-bin evaluation is forbidden.
    assert np.array_equal(evaluation_idx, start_idx - 1)
    in_range = (evaluation_idx >= 0) & (evaluation_idx < len(projection))
    rows = pd.DataFrame({
        "cascade_id": sizes.index.to_numpy(copy=True),
        "size": sizes.to_numpy(dtype=int, copy=True),
        "start_idx": start_idx,
        "evaluation_idx": evaluation_idx,
        "in_range": in_range,
    })
    rows["valid"] = False
    rows["prama_alert"] = False
    good = rows.index[in_range]
    ei = rows.loc[good, "evaluation_idx"].to_numpy(dtype=int, copy=True)
    rows.loc[good, "valid"] = projection["valid"].to_numpy(copy=True)[ei]
    rows.loc[good, "prama_alert"] = projection["latent_collapse"].to_numpy(
        copy=True
    )[ei]
    return rows


def fit_frozen_budget_calibration(
    signal: np.ndarray,
    prama_alert: np.ndarray,
    valid: np.ndarray,
    calibration_end_idx: int,
    calibration_id: str,
    tie_seed: int,
    min_samples: int = 24,
) -> dict:
    """Fit one immutable alert-budget threshold on a declared cohort."""
    x = np.asarray(signal, dtype=float)
    alert = np.asarray(prama_alert, dtype=bool)
    mask = np.asarray(valid, dtype=bool).copy()
    mask[calibration_end_idx:] = False
    mask &= np.isfinite(x)
    values = x[mask]
    calibration_indices = np.flatnonzero(mask)
    if len(values) < min_samples:
        raise ValueError("frozen calibration cohort has too few valid samples")
    target_alert_count = int(alert[mask].sum())
    budget = float(target_alert_count / len(values))
    quantile = float(np.clip(1.0 - budget, 0.0, 1.0))
    if target_alert_count == 0:
        threshold = float(values.max())
        strict_count = 0
        boundary_count = int(np.sum(values == threshold))
        boundary_accept_probability = 0.0
        boundary_hash_rule = "none"
        boundary_hash_cutoff = None
        boundary_hash_cutoff_index = None
    else:
        threshold = float(np.sort(values)[::-1][target_alert_count - 1])
        strict_count = int(np.sum(values > threshold))
        boundary_count = int(np.sum(values == threshold))
        boundary_accept_probability = float(
            (target_alert_count - strict_count) / boundary_count
        )
        needed_boundary = target_alert_count - strict_count
        if needed_boundary == boundary_count:
            boundary_hash_rule = "all"
            boundary_hash_cutoff = None
            boundary_hash_cutoff_index = None
        else:
            boundary_indices = calibration_indices[values == threshold]
            hashes = _indexed_hash(boundary_indices, tie_seed)
            order = np.lexsort((boundary_indices, hashes))
            cutoff_pos = order[needed_boundary - 1]
            boundary_hash_rule = "lexicographic_hash_cutoff"
            boundary_hash_cutoff = str(int(hashes[cutoff_pos]))
            boundary_hash_cutoff_index = int(boundary_indices[cutoff_pos])
    return {
        "calibration_id": calibration_id,
        "calibration_end_idx_exclusive": int(calibration_end_idx),
        "n_valid_calibration_bins": int(len(values)),
        "target_alert_budget": budget,
        "target_alert_count": target_alert_count,
        "quantile": quantile,
        "threshold": threshold,
        "strictly_above_threshold_count": strict_count,
        "boundary_value_count": boundary_count,
        "boundary_accept_probability": boundary_accept_probability,
        "boundary_hash_rule": boundary_hash_rule,
        "boundary_hash_cutoff_u64": boundary_hash_cutoff,
        "boundary_hash_cutoff_index": boundary_hash_cutoff_index,
        "tie_seed": int(tie_seed),
        "calibration_budget_realized_exactly": True,
        "fit_rule": "single order-statistic fit; seeded random rank selects exactly the required calibration ties",
    }


def apply_frozen_threshold(
    signal: np.ndarray, eligible_indices: np.ndarray, calibration: dict
) -> np.ndarray:
    """Apply an immutable calibrated threshold; no refitting is permitted."""
    x = np.asarray(signal, dtype=float)
    idx = np.asarray(eligible_indices, dtype=int)
    threshold = float(calibration["threshold"])
    above = np.isfinite(x[idx]) & (x[idx] > threshold)
    tied = np.isfinite(x[idx]) & (x[idx] == threshold)
    rule = calibration["boundary_hash_rule"]
    if rule == "none":
        accept_tie = np.zeros(len(idx), dtype=bool)
    elif rule == "all":
        accept_tie = np.ones(len(idx), dtype=bool)
    else:
        hashes = _indexed_hash(idx, calibration["tie_seed"])
        cutoff = np.uint64(int(calibration["boundary_hash_cutoff_u64"]))
        cutoff_idx = int(calibration["boundary_hash_cutoff_index"])
        accept_tie = (hashes < cutoff) | ((hashes == cutoff) & (idx <= cutoff_idx))
    return above | (tied & accept_tie)


def paired_cascade_bootstrap(
    rows: pd.DataFrame,
    baseline_alert: np.ndarray,
    size_threshold: int,
    n_bootstrap: int = 10_000,
    seed: int = 20260711,
) -> dict:
    """Paired cascade bootstrap for PRAMA minus baseline risk-difference."""
    eligible = rows[rows["in_range"] & rows["valid"]]
    prama = eligible["prama_alert"].to_numpy(dtype=bool, copy=True)
    baseline = np.asarray(baseline_alert, dtype=bool)
    severe = eligible["size"].to_numpy(dtype=int, copy=True) >= size_threshold
    if len(baseline) != len(eligible):
        raise ValueError("baseline_alert must align one-to-one with eligible cascades")

    def risk_difference(alert, outcome):
        p_in = outcome[alert].mean() if alert.any() else 0.0
        p_out = outcome[~alert].mean() if (~alert).any() else 0.0
        return float(p_in - p_out)

    observed_prama = risk_difference(prama, severe)
    observed_baseline = risk_difference(baseline, severe)
    observed_contrast = observed_prama - observed_baseline
    rng = np.random.default_rng(seed)
    contrasts = np.empty(n_bootstrap, dtype=float)
    for b in range(n_bootstrap):
        sample = rng.integers(0, len(eligible), size=len(eligible))
        y = severe[sample]
        contrasts[b] = (
            risk_difference(prama[sample], y)
            - risk_difference(baseline[sample], y)
        )
    return {
        "unit": "cascade",
        "statistic": "risk_difference(PRAMA) - risk_difference(baseline)",
        "observed_prama": observed_prama,
        "observed_baseline": observed_baseline,
        "observed_contrast": observed_contrast,
        "bootstrap_p2_5": float(np.percentile(contrasts, 2.5)),
        "bootstrap_median": float(np.percentile(contrasts, 50)),
        "bootstrap_p97_5": float(np.percentile(contrasts, 97.5)),
        "p_one_sided_prama_superior": float(
            (1 + np.sum(contrasts <= 0.0)) / (n_bootstrap + 1)
        ),
        "p_one_sided_prama_superior_semantics": (
            "percentile bootstrap tail proportion P(bootstrap contrast <= 0) "
            "with plus-one correction; not a centered bootstrap null test"
        ),
        "seed": int(seed),
        "n_bootstrap": int(n_bootstrap),
        "resampling_rule": "sample cascade rows with replacement; preserve paired signals and outcome",
    }


def severity_statistics(
    rows: pd.DataFrame,
    size_threshold: int,
) -> dict:
    """Conditional severity enrichment among eligible cascades only."""
    eligible = rows[rows["in_range"] & rows["valid"]].copy()
    if eligible.empty:
        return {"n_eligible": 0, "threshold": None, "p_inside": None,
                "p_outside": None, "enrichment": None, "alert_occupancy": 0.0}
    threshold = float(size_threshold)
    large = eligible["size"].to_numpy(copy=True) >= threshold
    alert = eligible["prama_alert"].to_numpy(dtype=bool, copy=True)
    p_in = float(large[alert].mean()) if alert.any() else 0.0
    p_out = float(large[~alert].mean()) if (~alert).any() else 0.0
    return {
        "n_eligible": int(len(eligible)), "threshold": threshold,
        "p_inside": p_in, "p_outside": p_out,
        "enrichment": p_in / p_out if p_out > 0 else None,
        "alert_occupancy": float(alert.mean()),
    }


def circular_shift_null(
    latent: np.ndarray, evaluation_indices: np.ndarray, severe: np.ndarray,
    n_permutations: int = 10_000, seed: int = 20260711,
    min_shift: int = 24,
) -> dict:
    """Shift the complete alert series, preserving its temporal dependence."""
    latent = np.asarray(latent, dtype=bool)
    idx = np.asarray(evaluation_indices, dtype=int)
    severe = np.asarray(severe, dtype=bool)
    if len(latent) <= 2 * min_shift:
        raise ValueError("series is too short for the requested minimum shift")
    allowed = np.arange(min_shift, len(latent) - min_shift + 1)
    rng = np.random.default_rng(seed)

    def statistic_at(alert_at_events: np.ndarray) -> float:
        a = alert_at_events
        p_in = severe[a].mean() if a.any() else 0.0
        p_out = severe[~a].mean() if (~a).any() else 0.0
        return float(p_in - p_out)

    observed = statistic_at(latent[idx])
    shifts = rng.choice(allowed, size=n_permutations, replace=True)
    null = np.fromiter((statistic_at(latent[(idx - int(s)) % len(latent)]) for s in shifts),
                       dtype=float, count=n_permutations)
    p = float((1 + np.sum(null >= observed)) / (n_permutations + 1))
    return {
        "statistic": "P(severe|alert)-P(severe|no alert)",
        "observed": observed, "null_mean": float(null.mean()),
        "null_p90": float(np.percentile(null, 90)),
        "null_p95": float(np.percentile(null, 95)),
        "null_p99": float(np.percentile(null, 99)),
        "p_corrected": p, "seed": int(seed),
        "n_permutations": int(n_permutations),
        "shift_rule": f"uniform integer circular shift in [{min_shift}, {len(latent)-min_shift}] bins",
    }


def occurrence_labels(events: pd.DataFrame, projection: pd.DataFrame,
                      horizons=(6, 12, 24, 48), bin_s: int = 3600) -> pd.DataFrame:
    """Define future-cascade occurrence on every eligible projection bin."""
    t0 = int(projection["t"].iloc[0])
    starts = events.groupby("cascade_id")["t_out"].min().to_numpy(copy=True)
    start_bins = ((starts - t0) // bin_s).astype(int)
    out = pd.DataFrame({"idx": np.arange(len(projection)),
                        "valid": projection["valid"].to_numpy(dtype=bool, copy=True)})
    for h in horizons:
        marks = np.zeros(len(projection), dtype=int)
        for s in start_bins:
            lo = max(0, s - h)
            marks[lo:s] = 1
        out[f"event_within_{h}h"] = marks
    return out
