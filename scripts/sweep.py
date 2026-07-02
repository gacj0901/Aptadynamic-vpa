import sys, itertools, json
from aptadynamic_vpa import (load_bpa, automatic_only, cascades,
                             omega_series, project, precursor_enrichment)
from aptadynamic_vpa.projection import ProjectionConfig

df = automatic_only(load_bpa(sys.argv[1]))
ev = cascades(df)
om = omega_series(df)

rows = []
for ts, tm, hz in itertools.product([1.0, 2.0, 3.0, 5.0],
                                    [24*7, 24*14, 24*30],
                                    [12, 24, 72]):
    pr = project(om, ProjectionConfig(theta_scale=ts, tau_memory=tm))
    r = precursor_enrichment(pr, ev, large_q=0.99, horizon_bins=hz)
    strata = pr["stratum"].value_counts(normalize=True).round(3).to_dict()
    rows.append({"theta": ts, "tau": tm, "hz": hz,
                 "enrich": round(r["enrichment"], 2),
                 "n_large": r["n_large"], "strata": strata})

rows.sort(key=lambda x: -x["enrich"])
for r in rows[:10]:
    print(json.dumps(r))