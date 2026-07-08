"""
scripts/analysis/explore_bpa_dataset.py
========================================

First exploratory analysis of Dobson's BPA outage dataset.

Loads the CSV, validates types, reconstructs cascades following the
Carrington et al. (NAPS 2021) protocol, and produces basic empirical
statistics: cascade size distribution, Zipf exponent, inter-arrival
times, cause breakdown.

Output is printed to stdout and a summary saved to:
  results/bpa_exploratory_summary.txt
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


def load_bpa_csv(path: Path) -> pd.DataFrame:
    """Load BPA CSV and convert types correctly."""
    df = pd.read_csv(path)
    
    # Parse timestamps
    df["OutDatetime"] = pd.to_datetime(df["OutDatetime"], errors="coerce")
    df["InDatetime"] = pd.to_datetime(df["InDatetime"], errors="coerce")
    
    # Numeric coercion
    df["Voltage"] = pd.to_numeric(df["Voltage"], errors="coerce")
    df["Length"] = pd.to_numeric(df["Length"], errors="coerce")
    df["Duration"] = pd.to_numeric(df["Duration"], errors="coerce")
    df["OutAbstime"] = pd.to_numeric(df["OutAbstime"], errors="coerce")
    df["InAbstime"] = pd.to_numeric(df["InAbstime"], errors="coerce")
    df["Reactance"] = pd.to_numeric(df["Reactance"], errors="coerce")
    
    # Sort by start time
    df = df.sort_values("OutAbstime").reset_index(drop=True)
    
    return df


def reconstruct_cascades(
    df: pd.DataFrame,
    cascade_gap_seconds: int = 3600,
    generation_gap_seconds: int = 60,
) -> pd.DataFrame:
    """Group outages into cascades and generations per Carrington et al. (2021).
    
    An outage starting more than `cascade_gap_seconds` after the previous one
    starts a new cascade. Within a cascade, outages within `generation_gap_seconds`
    of each other belong to the same generation.
    """
    df = df.copy().sort_values("OutAbstime").reset_index(drop=True)
    
    cascade_id = np.zeros(len(df), dtype=int)
    generation = np.zeros(len(df), dtype=int)
    
    current_cascade = 0
    current_generation = 0
    last_outage_time = None
    last_generation_start_time = None
    
    for i, t in enumerate(df["OutAbstime"].values):
        if pd.isna(t):
            cascade_id[i] = -1
            continue
        
        if last_outage_time is None:
            current_cascade = 1
            current_generation = 1
            last_generation_start_time = t
        else:
            gap = t - last_outage_time
            if gap > cascade_gap_seconds:
                current_cascade += 1
                current_generation = 1
                last_generation_start_time = t
            elif gap > generation_gap_seconds:
                current_generation += 1
                last_generation_start_time = t
            # else: same generation
        
        cascade_id[i] = current_cascade
        generation[i] = current_generation
        last_outage_time = t
    
    df["cascade_id"] = cascade_id
    df["generation"] = generation
    return df


def fit_zipf_exponent(sizes: np.ndarray) -> tuple:
    """Fit Zipf distribution to cascade sizes using MLE for power-law.
    
    Returns (exponent, n_samples). The MLE estimator for s is:
        s_hat = 1 + n / sum(ln(x_i / x_min))
    where x_min is the minimum observed size.
    """
    sizes = sizes[sizes >= 1]
    if len(sizes) < 10:
        return (None, len(sizes))
    
    x_min = sizes.min()
    n = len(sizes)
    s_hat = 1 + n / np.sum(np.log(sizes / x_min))
    return (float(s_hat), n)


def analyze(df: pd.DataFrame) -> dict:
    """Compute basic empirical statistics."""
    summary = {}
    
    # Date range
    summary["n_outages"] = len(df)
    summary["date_min"] = df["OutDatetime"].min()
    summary["date_max"] = df["OutDatetime"].max()
    summary["years_covered"] = (
        (df["OutDatetime"].max() - df["OutDatetime"].min()).days / 365.25
    )
    
    # Voltage distribution
    summary["voltage_counts"] = df["Voltage"].value_counts().sort_index().to_dict()
    
    # Cause distribution (top 10 dispatcher causes)
    summary["top_dispatcher_causes"] = (
        df["DispatcherCause"].value_counts().head(10).to_dict()
    )
    summary["top_field_causes"] = (
        df["FieldCause"].value_counts().head(10).to_dict()
    )
    
    # Reconstruct cascades
    df_c = reconstruct_cascades(df)
    
    cascade_groups = df_c.groupby("cascade_id")
    cascade_sizes = cascade_groups.size().values
    n_generations_per_cascade = (
        df_c.groupby("cascade_id")["generation"].nunique().values
    )
    
    summary["n_cascades"] = int(df_c["cascade_id"].max())
    summary["cascade_sizes"] = {
        "min": int(cascade_sizes.min()),
        "max": int(cascade_sizes.max()),
        "mean": float(cascade_sizes.mean()),
        "median": float(np.median(cascade_sizes)),
    }
    
    # Distribution of cascade sizes (line counts)
    size_counts = Counter(cascade_sizes.tolist())
    summary["cascade_size_distribution"] = dict(sorted(size_counts.items()))
    
    # Distribution of number of generations
    gen_counts = Counter(n_generations_per_cascade.tolist())
    summary["generations_per_cascade"] = dict(sorted(gen_counts.items()))
    
    # Zipf fit on number of generations (this is what Dobson reports)
    zipf_s, zipf_n = fit_zipf_exponent(n_generations_per_cascade.astype(float))
    summary["zipf_exponent_generations"] = zipf_s
    summary["zipf_n_samples"] = zipf_n
    
    # Zipf fit on total cascade size in lines
    zipf_size_s, zipf_size_n = fit_zipf_exponent(cascade_sizes.astype(float))
    summary["zipf_exponent_sizes"] = zipf_size_s
    
    # Inter-arrival times between cascades (in hours)
    cascade_start_times = (
        df_c.groupby("cascade_id")["OutAbstime"].first().values
    )
    cascade_start_times = np.sort(cascade_start_times)
    inter_arrivals_hours = np.diff(cascade_start_times) / 3600
    
    summary["inter_arrival_hours"] = {
        "mean": float(inter_arrivals_hours.mean()),
        "median": float(np.median(inter_arrivals_hours)),
        "std": float(inter_arrivals_hours.std()),
        "min": float(inter_arrivals_hours.min()),
        "max": float(inter_arrivals_hours.max()),
    }
    
    return summary, df_c


def print_summary(summary: dict) -> None:
    """Print a readable summary to stdout."""
    print("=" * 70)
    print("BPA Outage Dataset — Exploratory Analysis")
    print("=" * 70)
    
    print(f"\nDataset coverage:")
    print(f"  Total automatic outages:   {summary['n_outages']:,}")
    print(f"  Date range:                {summary['date_min']} to {summary['date_max']}")
    print(f"  Years covered:             {summary['years_covered']:.1f}")
    print(f"  Outages per year:          {summary['n_outages'] / summary['years_covered']:.0f}")
    
    print(f"\nVoltage distribution (kV):")
    for kv, n in summary['voltage_counts'].items():
        print(f"  {kv:>7.0f} kV  →  {n:>6,} outages ({n / summary['n_outages'] * 100:.1f}%)")
    
    print(f"\nTop dispatcher causes:")
    total = sum(summary['top_dispatcher_causes'].values())
    for cause, n in summary['top_dispatcher_causes'].items():
        print(f"  {cause[:40]:<40}  {n:>6,} ({n / summary['n_outages'] * 100:.1f}%)")
    
    print(f"\nTop field causes:")
    for cause, n in summary['top_field_causes'].items():
        print(f"  {str(cause)[:40]:<40}  {n:>6,} ({n / summary['n_outages'] * 100:.1f}%)")
    
    print(f"\nCascade statistics (1h cascade gap, 1min generation gap):")
    print(f"  Total cascades:            {summary['n_cascades']:,}")
    print(f"  Cascades per year:         {summary['n_cascades'] / summary['years_covered']:.0f}")
    print(f"  Cascade size (lines):")
    cs = summary['cascade_sizes']
    print(f"    min/median/mean/max:     {cs['min']} / {cs['median']:.1f} / {cs['mean']:.2f} / {cs['max']}")
    
    print(f"\nCascade size distribution (top sizes):")
    sizes = summary['cascade_size_distribution']
    for size in sorted(sizes.keys())[:15]:
        n = sizes[size]
        pct = n / summary['n_cascades'] * 100
        bar = "█" * min(50, int(pct))
        print(f"  size {size:>3}:  {n:>6,} cascades  ({pct:>5.1f}%)  {bar}")
    
    if max(sizes.keys()) > 15:
        large_sizes = {k: v for k, v in sizes.items() if k > 15}
        n_large = sum(large_sizes.values())
        print(f"  size >15:  {n_large:>6,} cascades  (largest: size {max(large_sizes):,})")
    
    print(f"\nGenerations per cascade (Carrington/Dobson metric):")
    gens = summary['generations_per_cascade']
    for ng in sorted(gens.keys())[:10]:
        n = gens[ng]
        pct = n / summary['n_cascades'] * 100
        bar = "█" * min(50, int(pct))
        print(f"  {ng:>3} gens:  {n:>6,} cascades  ({pct:>5.1f}%)  {bar}")
    
    print(f"\nZipf distribution fit (MLE):")
    if summary['zipf_exponent_generations']:
        print(f"  Exponent (generations):     s = {summary['zipf_exponent_generations']:.3f}")
        print(f"    (Dobson 2018 BPA reported: s ≈ 3.02)")
    if summary['zipf_exponent_sizes']:
        print(f"  Exponent (line counts):     s = {summary['zipf_exponent_sizes']:.3f}")
    
    print(f"\nInter-arrival times between cascades (hours):")
    ia = summary['inter_arrival_hours']
    print(f"  mean / median:             {ia['mean']:.2f} / {ia['median']:.2f}")
    print(f"  std:                       {ia['std']:.2f}")
    print(f"  range:                     {ia['min']:.2f} to {ia['max']:.0f}")
    
    print("\n" + "=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/dobson_bpa/outagesBPA.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}")
        return 1
    
    print(f"Loading {args.input}...")
    df = load_bpa_csv(args.input)
    print(f"  Loaded {len(df):,} outages, {len(df.columns)} columns")
    
    summary, df_with_cascades = analyze(df)
    print_summary(summary)
    
    # Save processed dataframe with cascade IDs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.output_dir / "bpa_outages_with_cascades.csv"
    df_with_cascades.to_csv(out_csv, index=False)
    print(f"\nSaved processed dataset (with cascade IDs): {out_csv}")
    
    # Save summary as text
    out_txt = args.output_dir / "bpa_exploratory_summary.txt"
    import io
    buf = io.StringIO()
    sys.stdout = buf
    print_summary(summary)
    sys.stdout = sys.__stdout__
    out_txt.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Saved text summary: {out_txt}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
