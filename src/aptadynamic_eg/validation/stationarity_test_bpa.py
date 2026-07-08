"""Stationarity test on BPA cascade statistics.

Splits the 19-year dataset into temporal windows and computes the same
metrics for each. If metrics drift monotonically, the system ages.
If they oscillate around a mean, the system is stationary.

Output: results/stationarity_analysis.txt
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def fit_zipf_csn(data):
    data = np.asarray(data, dtype=float)
    data = data[np.isfinite(data) & (data >= 1)]
    if len(data) < 30:
        return None
    unique_vals = np.sort(np.unique(data))
    best_alpha, best_ks = None, float("inf")
    candidates = unique_vals[:-min(10, len(unique_vals) // 3)] if len(unique_vals) > 5 else unique_vals
    for x_min in candidates:
        if x_min < 1:
            continue
        tail = data[data >= x_min]
        if len(tail) < 20:
            continue
        n = len(tail)
        s = np.sum(np.log(tail / (x_min - 0.5)))
        alpha = 1.0 + n / s
        if alpha <= 1 or not np.isfinite(alpha):
            continue
        sorted_tail = np.sort(tail)
        emp = np.arange(1, len(sorted_tail) + 1) / len(sorted_tail)
        theo = 1.0 - (sorted_tail / x_min) ** (1.0 - alpha)
        ks = float(np.max(np.abs(emp - theo)))
        if ks < best_ks:
            best_ks, best_alpha = ks, alpha
    return best_alpha


def hurst_dfa(series, min_window=10):
    series = np.asarray(series, dtype=float)
    n = len(series)
    if n < 100:
        return None
    max_window = n // 4
    y = np.cumsum(series - series.mean())
    windows = np.unique(np.logspace(np.log10(min_window), np.log10(max_window), 20).astype(int))
    windows = windows[(windows >= min_window) & (windows <= max_window)]
    if len(windows) < 3:
        return None
    fluctuations, valid = [], []
    for w in windows:
        n_chunks = n // w
        if n_chunks < 2:
            continue
        f2 = []
        for k in range(n_chunks):
            chunk = y[k * w:(k + 1) * w]
            t = np.arange(len(chunk))
            coeffs = np.polyfit(t, chunk, 1)
            detrended = chunk - np.polyval(coeffs, t)
            f2.append(np.mean(detrended ** 2))
        if f2:
            fluctuations.append(np.sqrt(np.mean(f2)))
            valid.append(w)
    if len(valid) < 3:
        return None
    H, _ = np.polyfit(np.log(valid), np.log(fluctuations), 1)
    return float(H)


def precursor_enrichment(df_window, top_pct=5.0, window_hours=24):
    """Enrichment ratio of outages in 24h preceding extreme cascades."""
    cascade_sizes = df_window.groupby("cascade_id").size()
    cascade_starts = df_window.groupby("cascade_id")["OutAbstime"].min()
    if len(cascade_sizes) < 20:
        return None
    threshold = np.percentile(cascade_sizes.values, 100 - top_pct)
    extreme_ids = cascade_sizes[cascade_sizes >= threshold].index
    if len(extreme_ids) == 0:
        return None
    window_sec = window_hours * 3600
    n_total = len(df_window)
    total_sec = df_window["OutAbstime"].max() - df_window["OutAbstime"].min()
    if total_sec == 0:
        return None
    baseline_rate = n_total / total_sec
    expected = baseline_rate * window_sec
    enrichments = []
    times = df_window["OutAbstime"].values
    for cid in extreme_ids:
        t = cascade_starts[cid]
        n_pre = int(((times >= t - window_sec) & (times < t)).sum())
        enrichments.append(n_pre / expected)
    return float(np.mean(enrichments))


def analyze_window(df_w, window_label):
    cascade_sizes = df_w.groupby("cascade_id").size().values
    n_cascades = len(cascade_sizes)
    if n_cascades == 0:
        return None
    
    duration_years = (df_w["OutDatetime"].max() - df_w["OutDatetime"].min()).days / 365.25
    if duration_years == 0:
        return None
    
    # Extreme threshold = top 5% size, computed within window
    top5_threshold = np.percentile(cascade_sizes, 95)
    extreme_mask = cascade_sizes >= top5_threshold
    n_extreme = int(extreme_mask.sum())
    extreme_sizes = cascade_sizes[extreme_mask]
    
    # Hourly count series for Hurst (in seconds, sum of cascade sizes per hour)
    df_sorted = df_w.sort_values("OutAbstime")
    t_min = df_sorted["OutAbstime"].min()
    t_max = df_sorted["OutAbstime"].max()
    n_hours = int((t_max - t_min) // 3600) + 1
    counts = np.zeros(n_hours, dtype=float)
    for cid, grp in df_sorted.groupby("cascade_id"):
        h = int((grp["OutAbstime"].min() - t_min) // 3600)
        if 0 <= h < n_hours:
            counts[h] += len(grp)
    
    return {
        "window": window_label,
        "duration_years": float(duration_years),
        "n_cascades": int(n_cascades),
        "cascades_per_year": float(n_cascades / duration_years),
        "mean_size": float(cascade_sizes.mean()),
        "max_size": int(cascade_sizes.max()),
        "p95_threshold": float(top5_threshold),
        "n_extreme_top5pct": n_extreme,
        "extremes_per_year": float(n_extreme / duration_years),
        "median_extreme_size": float(np.median(extreme_sizes)),
        "mean_extreme_size": float(extreme_sizes.mean()),
        "max_extreme_size": int(extreme_sizes.max()),
        "alpha_zipf": fit_zipf_csn(cascade_sizes),
        "hurst": hurst_dfa(counts),
        "precursor_1d_enrichment": precursor_enrichment(df_w),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("results/bpa_outages_with_cascades.csv"))
    parser.add_argument("--output", type=Path,
                        default=Path("results/stationarity_analysis.txt"))
    parser.add_argument("--n-windows", type=int, default=5,
                        help="Split dataset into N temporal windows")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df["OutDatetime"] = pd.to_datetime(df["OutDatetime"], errors="coerce")
    df["OutAbstime"] = pd.to_numeric(df["OutAbstime"], errors="coerce")
    df = df.dropna(subset=["OutAbstime", "cascade_id"]).sort_values("OutAbstime")
    df["cascade_id"] = df["cascade_id"].astype(int)
    df = df[df["cascade_id"] > 0]
    
    print(f"Loaded: {len(df):,} outages, {df['cascade_id'].nunique():,} cascades")
    print(f"Date range: {df['OutDatetime'].min()} to {df['OutDatetime'].max()}")
    print(f"Splitting into {args.n_windows} temporal windows...\n")

    # Split by time (equal-duration windows)
    t_min = df["OutAbstime"].min()
    t_max = df["OutAbstime"].max()
    edges = np.linspace(t_min, t_max, args.n_windows + 1)
    
    rows = []
    for i in range(args.n_windows):
        mask = (df["OutAbstime"] >= edges[i]) & (df["OutAbstime"] < edges[i + 1])
        df_w = df[mask].copy()
        if len(df_w) == 0:
            continue
        start_year = df_w["OutDatetime"].min().year
        end_year = df_w["OutDatetime"].max().year
        label = f"{start_year}-{end_year}"
        result = analyze_window(df_w, label)
        if result:
            rows.append(result)
            print(f"Window {i+1}/{args.n_windows} [{label}]: "
                  f"{result['n_cascades']:,} cascades, "
                  f"α={result['alpha_zipf']}, H={result['hurst']}")

    # Build report
    print("\n" + "=" * 90)
    print(f"{'Window':<12} {'years':>6} {'casc':>6} {'/year':>6} {'mean':>5} "
          f"{'max':>5} {'ext/yr':>7} {'med_ext':>8} {'α':>5} {'H':>5} {'E_1d':>5}")
    print("-" * 90)
    for r in rows:
        a = f"{r['alpha_zipf']:.2f}" if r['alpha_zipf'] else "  - "
        h = f"{r['hurst']:.2f}" if r['hurst'] else "  - "
        e = f"{r['precursor_1d_enrichment']:.2f}" if r['precursor_1d_enrichment'] else "  - "
        print(f"{r['window']:<12} {r['duration_years']:>6.1f} "
              f"{r['n_cascades']:>6} {r['cascades_per_year']:>6.0f} "
              f"{r['mean_size']:>5.2f} {r['max_size']:>5} "
              f"{r['extremes_per_year']:>7.1f} {r['median_extreme_size']:>8.1f} "
              f"{a:>5} {h:>5} {e:>5}")
    
    print("\n" + "=" * 90)
    print("STATIONARITY DIAGNOSTIC")
    print("=" * 90)
    
    # Compute trends
    def linreg(y_series):
        y = [r[y_series] for r in rows if r.get(y_series) is not None]
        if len(y) < 3:
            return None, None
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        # Coefficient of variation as stationarity proxy
        cv = float(np.std(y) / np.mean(y)) if np.mean(y) != 0 else None
        return float(slope), cv
    
    metrics = ["cascades_per_year", "extremes_per_year", "median_extreme_size",
               "max_size", "alpha_zipf", "hurst", "precursor_1d_enrichment"]
    
    print(f"\n{'Metric':<30} {'Slope':>10} {'CV':>8} {'Verdict':>15}")
    print("-" * 65)
    verdicts = []
    for m in metrics:
        slope, cv = linreg(m)
        if slope is None:
            print(f"{m:<30} {'-':>10} {'-':>8} {'insufficient':>15}")
            continue
        # Verdict: stationary if CV < 0.15 and |slope/mean| small
        y = [r[m] for r in rows if r.get(m) is not None]
        mean = np.mean(y) if y else 0
        rel_slope = abs(slope / mean) if mean != 0 else float("inf")
        if cv is None or cv > 0.30:
            v = "drift"
        elif rel_slope > 0.10:
            v = "trending"
        else:
            v = "stationary"
        verdicts.append(v)
        print(f"{m:<30} {slope:>10.4f} {cv:>8.3f} {v:>15}")
    
    print("\n" + "=" * 90)
    n_stat = verdicts.count("stationary")
    n_trend = verdicts.count("trending")
    n_drift = verdicts.count("drift")
    print(f"Summary: {n_stat} stationary, {n_trend} trending, {n_drift} drifting (of {len(verdicts)})")
    if n_stat >= len(verdicts) * 0.7:
        print("\n>>> CONCLUSION: BPA cascade statistics are STATIONARY across 19 years.")
        print(">>> PRAMA should sostener su régimen indefinidamente sin colapsar.")
        print(">>> El colapso del simulador es un bug arquitectónico, no un observable real.")
    elif n_trend + n_drift >= len(verdicts) * 0.5:
        print("\n>>> CONCLUSION: BPA cascade statistics show TEMPORAL DRIFT.")
        print(">>> PRAMA reproduces aging correctly; collapse is the accelerated version.")
        print(">>> Calibration should measure metrics during pre-collapse phase.")
    else:
        print("\n>>> CONCLUSION: Mixed evidence, deeper analysis needed.")
    
    # Write to file
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("BPA Stationarity Analysis\n")
        f.write("=" * 90 + "\n\n")
        f.write(f"Windows: {args.n_windows}\n\n")
        f.write(f"{'Window':<12} {'years':>6} {'casc':>6} {'/year':>6} {'mean':>5} "
                f"{'max':>5} {'ext/yr':>7} {'med_ext':>8} {'α':>5} {'H':>5} {'E_1d':>5}\n")
        for r in rows:
            a = f"{r['alpha_zipf']:.2f}" if r['alpha_zipf'] else "  - "
            h = f"{r['hurst']:.2f}" if r['hurst'] else "  - "
            e = f"{r['precursor_1d_enrichment']:.2f}" if r['precursor_1d_enrichment'] else "  - "
            f.write(f"{r['window']:<12} {r['duration_years']:>6.1f} "
                    f"{r['n_cascades']:>6} {r['cascades_per_year']:>6.0f} "
                    f"{r['mean_size']:>5.2f} {r['max_size']:>5} "
                    f"{r['extremes_per_year']:>7.1f} {r['median_extreme_size']:>8.1f} "
                    f"{a:>5} {h:>5} {e:>5}\n")
    print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()
