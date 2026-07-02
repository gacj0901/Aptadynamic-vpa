import sys, json
from aptadynamic_vpa import (load_bpa, automatic_only, cascades,
                             omega_series, project, precursor_enrichment)

df = load_bpa(sys.argv[1])
auto = automatic_only(df)
ev = cascades(auto)
om = omega_series(auto)
pr = project(om)
res = precursor_enrichment(pr, ev)

pr.to_csv("results/projection.csv", index=False)
print(json.dumps(res, indent=2))
print("strata %:", (pr["stratum"].value_counts(normalize=True) * 100).round(1).to_dict())
print("latent collapse bins:", int(pr["latent_collapse"].sum()))
