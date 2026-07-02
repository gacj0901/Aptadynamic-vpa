"""Validación: ¿G<0 sostenido precede cascadas grandes?

α y H son propiedades del dato (referencias: Zipf α≈2.87, H≈0.63, Dobson).
No son targets de calibración. El único test de PRAMA es predictivo:
enrichment = P(cascada grande | S₂∪S₄ previo) / P(cascada grande).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def zipf_alpha(sizes: pd.Series, min_size: int = 2) -> float:
    x = np.sort(sizes[sizes >= min_size].to_numpy())[::-1]
    if len(x) < 10:
        return float("nan")
    rank = np.arange(1, len(x) + 1)
    slope, _ = np.polyfit(np.log(rank), np.log(x), 1)
    b = -slope
    return 1.0 + 1.0 / b if b > 0 else float("nan")
    

def precursor_enrichment(
    proj: pd.DataFrame,
    events: pd.DataFrame,
    large_q: float = 0.95,
    horizon_bins: int = 24,
    bin_s: int = 3600,
) -> dict:
    sizes = events.groupby("cascade_id").size()
    t_start = events.groupby("cascade_id")["t_out"].min()
    thr = sizes.quantile(large_q)
    large_t = t_start[sizes >= thr].to_numpy()

    t0 = proj["t"].iloc[0]
    idx_large = np.clip(((large_t - t0) // bin_s).astype(int), 0, len(proj) - 1)

    stressed = proj["stratum"].isin([2, 4]).to_numpy()

    hits = 0
    for i in idx_large:
        lo = max(0, i - horizon_bins)
        if stressed[lo:i].mean() > 0.5 if i > lo else False:
            hits += 1

    p_cond = hits / max(len(idx_large), 1)
    p_base = stressed.mean()
    return {
        "n_large": int(len(idx_large)),
        "size_threshold": float(thr),
        "p_precursor_given_large": p_cond,
        "p_stressed_baseline": p_base,
        "enrichment": p_cond / max(p_base, 1e-12),
        "zipf_alpha_data": zipf_alpha(sizes),
    }
