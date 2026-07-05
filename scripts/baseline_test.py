import sys
import numpy as np
import pandas as pd
from aptadynamic_eg import (load_bpa, automatic_only, cascades,
                             omega_series, project, precursor_enrichment)
from aptadynamic_eg.projection import ProjectionConfig

df = automatic_only(load_bpa(sys.argv[1]))
ev = cascades(df)
om = omega_series(df)
pr = project(om, ProjectionConfig(tau_memory=720, driver="intensity"))

inten = om["intensity"].to_numpy()
frac = pr["stratum"].isin([2, 4]).mean()

print(f"{'hz':>4} {'PRAMA':>7} {'trivial':>8}")
for hz in (6, 12, 24, 48):
    e_p = precursor_enrichment(pr, ev, large_q=0.99, horizon_bins=hz)["enrichment"]

    recent = pd.Series(inten).rolling(12).mean().shift(1).fillna(0).to_numpy()
    thr = np.quantile(recent, 1 - frac)
    pt = pr.copy()
    pt["stratum"] = np.where(recent > thr, 2, 1)
    e_t = precursor_enrichment(pt, ev, large_q=0.99, horizon_bins=hz)["enrichment"]

    print(f"{hz:>4} {e_p:>7.2f} {e_t:>8.2f}")