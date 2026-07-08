"""
scripts/analysis/memory_analysis_bpa.py
========================================

Three analyses of the BPA cascade dataset that distinguish memory-based
dynamics from Markovian (branching-process) dynamics:

  1. Refined Zipf fit using Clauset-Shalizi-Newman (CSN) MLE method,
     with optimal x_min selection via Kolmogorov-Smirnov distance.

  2. Hurst exponent of the outage time series via R/S and DFA methods.
     H = 0.5 means no long-range memory (Markovian).
     H > 0.5 means positive persistence (long-range memory).
     H < 0.5 means anti-persistence.

  3. Characterization of extreme events: cascades in the top 1% of size
     and their precursor patterns (outage counts in 24h, 72h, 1 week
     before the event).

Reads from: results/bpa_outages_with_cascades.csv
Writes to: results/memory_analysis_summary.txt
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# 1. Refined Zipf fit (Clauset-Shalizi-Newman method)
# ----------------------------------------------------------------------

def mle_alpha(data: np.ndarray, x_min: float) -> float:
    """MLE alpha for power-law tail above x_min (discrete data approximation)."""
    tail = data[data >= x_min]
    if len(tail) < 2:
        return float("nan")
    n = len(tail)
    s = np.sum(np.log(tail / (x_min - 0.5)))
    return 1.0 + n / s


def ks_distance(data: np.ndarray, x_min: float, alpha: float) -> float:
    """Kolmogorov-Smirnov distance between empirical CDF and fitted power law."""
    tail = np.sort(data[data >= x_min])
    if len(tail) < 2:
        return float("inf")
    empirical_cdf = np.arange(1, len(tail) + 1) / len(tail)
    # Theoretical CDF: 1 - (x/x_min)^(1-alpha) for x >= x_min
    theoretical_cdf = 1.0 - (tail / x_min) ** (1.0 - alpha)
    return float(np.max(np.abs(empirical_cdf - theoretical_cdf)))


def fit_zipf_csn(data: np.ndarray) -> dict:
    """Fit power law using Clauset-Shalizi-Newman method.
    
    Selects x_min that minimizes KS distance, then fits alpha by MLE
    on the tail x >= x_min.
    """
    data = np.asarray(data, dtype=float)
    data = data[np.isfinite(data) & (data >= 1)]
    
    unique_vals = np.sort(np.unique(data))
    best = {"x_min": None, "alpha": None, "ks": float("inf"), "n_tail": 0}
    
    # Search over candidate x_min values (skip top few to keep tail >= 50)
    candidates = unique_vals[: -min(10, len(unique_vals) // 3)] if len(unique_vals) > 5 else unique_vals
    
    for x_min in candidates:
        if x_min < 1:
            continue
        n_tail = int(np.sum(data >= x_min))
        if n_tail < 50:
            continue
        alpha = mle_alpha(data, x_min)
        if not np.isfinite(alpha) or alpha <= 1:
            continue
        ks = ks_distance(data, x_min, alpha)
        if ks < best["ks"]:
            best = {"x_min": float(x_min), "alpha": float(alpha),
                    "ks": ks, "n_tail": n_tail}
    
    return best


# ----------------------------------------------------------------------
# 2. Hurst exponent (R/S analysis)
# ----------------------------------------------------------------------

def hurst_rs(series: np.ndarray, min_window: int = 10, max_window: int = None) -> dict:
    """Compute Hurst exponent via rescaled range (R/S) analysis.
    
    Splits the series into chunks of varying length n, computes the
    rescaled range R(n)/S(n) for each, then fits log(R/S) ~ H * log(n).
    """
    series = np.asarray(series, dtype=float)
    n = len(series)
    if max_window is None:
        max_window = n // 4
    
    # Window sizes: log-spaced
    windows = np.unique(np.logspace(
        np.log10(min_window), np.log10(max_window), 20
    ).astype(int))
    windows = windows[windows >= min_window]
    
    rs_values = []
    valid_windows = []
    
    for w in windows:
        n_chunks = n // w
        if n_chunks < 2:
            continue
        
        rs_in_chunks = []
        for k in range(n_chunks):
            chunk = series[k * w:(k + 1) * w]
            mean_chunk = chunk.mean()
            deviations = chunk - mean_chunk
            cumulative = np.cumsum(deviations)
            R = cumulative.max() - cumulative.min()
            S = chunk.std()
            if S > 0:
                rs_in_chunks.append(R / S)
        
        if len(rs_in_chunks) > 0:
            rs_values.append(np.mean(rs_in_chunks))
            valid_windows.append(w)
    
    if len(valid_windows) < 3:
        return {"hurst": None, "n_windows": len(valid_windows)}
    
    log_n = np.log(valid_windows)
    log_rs = np.log(rs_values)
    H, intercept = np.polyfit(log_n, log_rs, 1)
    
    # Compute R^2 for goodness of fit
    fit_line = H * log_n + intercept
    ss_res = np.sum((log_rs - fit_line) ** 2)
    ss_tot = np.sum((log_rs - log_rs.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    
    return {
        "hurst": float(H),
        "intercept": float(intercept),
        "r_squared": float(r_squared),
        "n_windows": len(valid_windows),
        "windows_used": valid_windows,
        "rs_values": rs_values,
    }


def hurst_dfa(series: np.ndarray, min_window: int = 10, max_window: int = None) -> dict:
    """Compute Hurst exponent via Detrended Fluctuation Analysis (DFA).
    
    More robust than R/S to non-stationarity. The DFA exponent equals the
    Hurst exponent for fractional Brownian motion processes.
    """
    series = np.asarray(series, dtype=float)
    n = len(series)
    if max_window is None:
        max_window = n // 4
    
    # Cumulative deviation from mean (integrated series)
    y = np.cumsum(series - series.mean())
    
    windows = np.unique(np.logspace(
        np.log10(min_window), np.log10(max_window), 20
    ).astype(int))
    windows = windows[(windows >= min_window) & (windows <= max_window)]
    
    fluctuations = []
    valid_windows = []
    
    for w in windows:
        n_chunks = n // w
        if n_chunks < 2:
            continue
        
        f2_chunks = []
        for k in range(n_chunks):
            chunk = y[k * w:(k + 1) * w]
            t = np.arange(len(chunk))
            # Linear detrending
            coeffs = np.polyfit(t, chunk, 1)
            trend = np.polyval(coeffs, t)
            detrended = chunk - trend
            f2_chunks.append(np.mean(detrended ** 2))
        
        if f2_chunks:
            fluctuations.append(np.sqrt(np.mean(f2_chunks)))
            valid_windows.append(w)
    
    if len(valid_windows) < 3:
        return {"hurst": None, "n_windows": len(valid_windows)}
    
    log_n = np.log(valid_windows)
    log_f = np.log(fluctuations)
    H, intercept = np.polyfit(log_n, log_f, 1)
    
    fit_line = H * log_n + intercept
    ss_res = np.sum((log_f - fit_line) ** 2)
    ss_tot = np.sum((log_f - log_f.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    
    return {
        "hurst": float(H),
        "intercept": float(intercept),
        "r_squared": float(r_squared),
        "n_windows": len(valid_windows),
    }


def build_hourly_series(df: pd.DataFrame) -> np.ndarray:
    """Convert the outage list into an hourly count series.
    
    Returns array of length (num_hours) with the number of outages
    that started in each hour, ordered chronologically.
    """
    times = pd.to_datetime(df["OutDatetime"]).dropna().sort_values()
    if len(times) == 0:
        return np.array([])
    
    t_min = times.min().floor("h")
    t_max = times.max().ceil("h")
    hours = pd.date_range(t_min, t_max, freq="h")
    
    # Count outages per hour
    bins = pd.cut(times, bins=hours, include_lowest=True)
    counts = bins.value_counts().sort_index().values
    return counts.astype(float)


# ----------------------------------------------------------------------
# 3. Extreme event characterization
# ----------------------------------------------------------------------

def characterize_extreme_events(df: pd.DataFrame, top_pct: float = 1.0) -> dict:
    """Find top X% of cascades by size and characterize their precursors."""
    # Cascade size distribution
    cascade_sizes = df.groupby("cascade_id").size()
    threshold = np.percentile(cascade_sizes, 100 - top_pct)
    extreme_ids = cascade_sizes[cascade_sizes >= threshold].index.tolist()
    
    df = df.copy()
    df["OutDatetime"] = pd.to_datetime(df["OutDatetime"])
    df = df.sort_values("OutAbstime").reset_index(drop=True)
    
    extreme_events = []
    for cid in extreme_ids:
        cascade_rows = df[df["cascade_id"] == cid]
        if len(cascade_rows) == 0:
            continue
        
        t_start = cascade_rows["OutAbstime"].min()
        t_start_dt = cascade_rows["OutDatetime"].min()
        size = len(cascade_rows)
        n_generations = cascade_rows["generation"].nunique()
        duration_minutes = (
            cascade_rows["OutAbstime"].max() - cascade_rows["OutAbstime"].min()
        ) / 60
        
        # Count preceding outages in windows
        for window_label, window_seconds in [
            ("1d", 86400),
            ("3d", 86400 * 3),
            ("7d", 86400 * 7),
        ]:
            precursor_mask = (
                (df["OutAbstime"] >= t_start - window_seconds) &
                (df["OutAbstime"] < t_start)
            )
            n_precursors = int(precursor_mask.sum())
        
        # Build precursor data
        precursors = {}
        for window_label, window_seconds in [
            ("1d", 86400),
            ("3d", 86400 * 3),
            ("7d", 86400 * 7),
        ]:
            mask = (
                (df["OutAbstime"] >= t_start - window_seconds) &
                (df["OutAbstime"] < t_start)
            )
            precursors[f"precursors_{window_label}"] = int(mask.sum())
        
        # Get the dominant causes in this cascade
        causes = cascade_rows["DispatcherCause"].value_counts().head(2).to_dict()
        
        extreme_events.append({
            "cascade_id": int(cid),
            "start_time": str(t_start_dt),
            "size": int(size),
            "n_generations": int(n_generations),
            "duration_minutes": float(duration_minutes),
            **precursors,
            "top_cause": list(causes.keys())[0] if causes else "",
        })
    
    # Sort by size descending
    extreme_events.sort(key=lambda e: -e["size"])
    
    # Compute baseline precursor rates (typical 1-day window across whole dataset)
    n_total = len(df)
    total_hours = (df["OutAbstime"].max() - df["OutAbstime"].min()) / 3600
    baseline_rate_per_day = n_total / (total_hours / 24)
    
    return {
        "extreme_events": extreme_events,
        "n_extreme": len(extreme_events),
        "size_threshold": int(threshold),
        "baseline_outages_per_day": float(baseline_rate_per_day),
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("results/bpa_outages_with_cascades.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}")
        print(f"Run explore_bpa_dataset.py first to generate it.")
        return 1
    
    print(f"Loading {args.input}...")
    df = pd.read_csv(args.input)
    df["OutDatetime"] = pd.to_datetime(df["OutDatetime"], errors="coerce")
    df["OutAbstime"] = pd.to_numeric(df["OutAbstime"], errors="coerce")
    df = df.dropna(subset=["OutAbstime", "cascade_id"])
    print(f"  Loaded {len(df):,} outages, {df['cascade_id'].max():,} cascades")
    
    # =================================================================
    # 1. Refined Zipf fit
    # =================================================================
    print("\n" + "=" * 70)
    print("1. REFINED ZIPF FIT (Clauset-Shalizi-Newman method)")
    print("=" * 70)
    
    cascade_sizes = df.groupby("cascade_id").size().values
    n_generations = df.groupby("cascade_id")["generation"].nunique().values
    
    print("\nFitting on cascade sizes (number of line outages per cascade)...")
    fit_sizes = fit_zipf_csn(cascade_sizes)
    if fit_sizes["alpha"]:
        print(f"  Optimal x_min:             {fit_sizes['x_min']:.0f}")
        print(f"  Power-law exponent alpha:  {fit_sizes['alpha']:.3f}")
        print(f"  KS distance:               {fit_sizes['ks']:.4f}")
        print(f"  Samples in tail:           {fit_sizes['n_tail']:,}")
    else:
        print("  Fit failed.")
    
    print("\nFitting on number of generations per cascade (Dobson's metric)...")
    fit_gens = fit_zipf_csn(n_generations.astype(float))
    if fit_gens["alpha"]:
        print(f"  Optimal x_min:             {fit_gens['x_min']:.0f}")
        print(f"  Power-law exponent alpha:  {fit_gens['alpha']:.3f}")
        print(f"  KS distance:               {fit_gens['ks']:.4f}")
        print(f"  Samples in tail:           {fit_gens['n_tail']:,}")
        print(f"  Dobson 2018 BPA reported:  alpha ≈ 3.02")
    else:
        print("  Fit failed (try wider data).")
    
    # =================================================================
    # 2. Hurst exponent
    # =================================================================
    print("\n" + "=" * 70)
    print("2. HURST EXPONENT (long-range memory)")
    print("=" * 70)
    print("\nBuilding hourly outage count time series...")
    hourly_counts = build_hourly_series(df)
    print(f"  Series length:             {len(hourly_counts):,} hours")
    print(f"  Mean count/hour:           {hourly_counts.mean():.3f}")
    print(f"  Non-zero hours:            {(hourly_counts > 0).sum():,} ({(hourly_counts > 0).mean() * 100:.1f}%)")
    print(f"  Max count in any hour:     {hourly_counts.max():.0f}")
    
    print("\nComputing Hurst exponent via R/S analysis...")
    rs_result = hurst_rs(hourly_counts)
    if rs_result["hurst"] is not None:
        print(f"  H (R/S):                   {rs_result['hurst']:.3f}")
        print(f"  Fit R-squared:             {rs_result['r_squared']:.3f}")
        print(f"  Number of window scales:   {rs_result['n_windows']}")
    
    print("\nComputing Hurst exponent via Detrended Fluctuation Analysis (DFA)...")
    dfa_result = hurst_dfa(hourly_counts)
    if dfa_result["hurst"] is not None:
        print(f"  H (DFA):                   {dfa_result['hurst']:.3f}")
        print(f"  Fit R-squared:             {dfa_result['r_squared']:.3f}")
        print(f"  Number of window scales:   {dfa_result['n_windows']}")
    
    print("\nInterpretation:")
    print("  H = 0.5  : no long-range memory (Markovian, branching-process compatible)")
    print("  H > 0.5  : long-range positive correlations (persistent memory)")
    print("  H < 0.5  : anti-persistence (mean-reverting)")
    
    H_main = dfa_result.get("hurst") or rs_result.get("hurst")
    if H_main is not None:
        if H_main > 0.55:
            print(f"\n  >>> H = {H_main:.3f} indicates LONG-RANGE MEMORY <<<")
            print(f"  >>> Markovian models are INSUFFICIENT for this dataset <<<")
        elif H_main < 0.45:
            print(f"\n  >>> H = {H_main:.3f} indicates anti-persistence <<<")
        else:
            print(f"\n  >>> H = {H_main:.3f} is consistent with Markovian dynamics <<<")
    
    # =================================================================
    # 3. Extreme events
    # =================================================================
    print("\n" + "=" * 70)
    print("3. EXTREME EVENT CHARACTERIZATION (top 1% of cascades)")
    print("=" * 70)
    
    ext = characterize_extreme_events(df, top_pct=1.0)
    print(f"\nCascades in top 1% by size:  {ext['n_extreme']}")
    print(f"Size threshold (top 1%):      >= {ext['size_threshold']} lines")
    print(f"Baseline rate:                {ext['baseline_outages_per_day']:.2f} outages/day")
    
    print(f"\nTop 10 largest cascades and their precursor patterns:")
    print(f"  {'Date':<19} {'Size':>5} {'Gens':>5} {'Dur(min)':>10} {'Prec1d':>7} {'Prec3d':>7} {'Prec7d':>7}  Top cause")
    print(f"  {'-' * 19} {'-' * 5} {'-' * 5} {'-' * 10} {'-' * 7} {'-' * 7} {'-' * 7}  {'-' * 20}")
    for ev in ext["extreme_events"][:10]:
        print(f"  {ev['start_time']:<19} "
              f"{ev['size']:>5} "
              f"{ev['n_generations']:>5} "
              f"{ev['duration_minutes']:>10.1f} "
              f"{ev['precursors_1d']:>7} "
              f"{ev['precursors_3d']:>7} "
              f"{ev['precursors_7d']:>7}  "
              f"{ev['top_cause']}")
    
    # Compute precursor enrichment
    n_extreme = len(ext["extreme_events"])
    if n_extreme > 0:
        mean_prec_1d = np.mean([ev["precursors_1d"] for ev in ext["extreme_events"]])
        mean_prec_3d = np.mean([ev["precursors_3d"] for ev in ext["extreme_events"]])
        mean_prec_7d = np.mean([ev["precursors_7d"] for ev in ext["extreme_events"]])
        
        expected_1d = ext["baseline_outages_per_day"] * 1
        expected_3d = ext["baseline_outages_per_day"] * 3
        expected_7d = ext["baseline_outages_per_day"] * 7
        
        print(f"\nPrecursor enrichment ratio (observed / expected from baseline):")
        print(f"  1 day before extreme:     {mean_prec_1d / expected_1d:.2f}x")
        print(f"  3 days before extreme:    {mean_prec_3d / expected_3d:.2f}x")
        print(f"  7 days before extreme:    {mean_prec_7d / expected_7d:.2f}x")
        
        if mean_prec_3d / expected_3d > 1.5:
            print(f"\n  >>> Extreme events are PRECEDED by elevated outage rates <<<")
            print(f"  >>> This is consistent with friction accumulation / echo phase <<<")
    
    # =================================================================
    # Save summary
    # =================================================================
    print("\n" + "=" * 70)
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_txt = args.output_dir / "memory_analysis_summary.txt"
    
    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    
    # Recompute and print to buffer for saving
    print("MEMORY ANALYSIS — BPA OUTAGE DATASET")
    print("=" * 70)
    print(f"\nDataset: {len(df):,} outages, {int(df['cascade_id'].max()):,} cascades")
    print(f"\n--- ZIPF FIT (cascade sizes) ---")
    if fit_sizes["alpha"]:
        print(f"alpha = {fit_sizes['alpha']:.3f}, x_min = {fit_sizes['x_min']:.0f}, "
              f"KS = {fit_sizes['ks']:.4f}, n_tail = {fit_sizes['n_tail']}")
    print(f"\n--- ZIPF FIT (number of generations) ---")
    if fit_gens["alpha"]:
        print(f"alpha = {fit_gens['alpha']:.3f}, x_min = {fit_gens['x_min']:.0f}, "
              f"KS = {fit_gens['ks']:.4f}, n_tail = {fit_gens['n_tail']}")
    print(f"Dobson 2018 BPA reported: alpha ≈ 3.02")
    print(f"\n--- HURST EXPONENT ---")
    if rs_result["hurst"] is not None:
        print(f"H (R/S):  {rs_result['hurst']:.3f}  (R² = {rs_result['r_squared']:.3f})")
    if dfa_result["hurst"] is not None:
        print(f"H (DFA):  {dfa_result['hurst']:.3f}  (R² = {dfa_result['r_squared']:.3f})")
    print(f"\n--- EXTREME EVENTS ---")
    print(f"Top 1% threshold: >= {ext['size_threshold']} lines")
    print(f"Number of extreme cascades: {ext['n_extreme']}")
    if n_extreme > 0:
        print(f"Precursor enrichment 1d/3d/7d: "
              f"{mean_prec_1d / expected_1d:.2f}x / "
              f"{mean_prec_3d / expected_3d:.2f}x / "
              f"{mean_prec_7d / expected_7d:.2f}x")
    
    sys.stdout = old_stdout
    out_txt.write_text(buf.getvalue(), encoding="utf-8")
    print(f"\nSummary saved: {out_txt}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
