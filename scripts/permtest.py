import sys
import numpy as np
from aptadynamic_vpa import (load_bpa, automatic_only, cascades,
                             omega_series, project, precursor_enrichment)
from aptadynamic_vpa.projection import ProjectionConfig

df = automatic_only(load_bpa(sys.argv[1]))
ev = cascades(df)
om = omega_series(df)
pr = project(om, ProjectionConfig(theta_scale=1.0, tau_memory=168))

real = precursor_enrichment(pr, ev, large_q=0.99, horizon_bins=12)["enrichment"]

rng = np.random.default_rng(0)
null = []
strat = pr["stratum"].to_numpy().copy()
for _ in range(200):
    shift = rng.integers(1000, len(strat) - 1000)
    pr["stratum"] = np.roll(strat, shift)
    null.append(precursor_enrichment(pr, ev, large_q=0.99, horizon_bins=12)["enrichment"])

null = np.array(null)
p = (null >= real).mean()
print(f"real={real:.2f}  null_mean={null.mean():.2f}  null_p95={np.quantile(null, .95):.2f}  p={p:.3f}")