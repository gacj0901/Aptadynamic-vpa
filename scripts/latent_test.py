import sys
import numpy as np
import pandas as pd
from aptadynamic_vpa import load_bpa, automatic_only, cascades, omega_series, project
from aptadynamic_vpa.projection import ProjectionConfig

BIN_S = 3600

df = automatic_only(load_bpa(sys.argv[1]))
print(f"--- CONTROL DE CONTAMINACIÓN: Eventos tras filtrar = {len(df)} ---")
ev = cascades(df)
om = omega_series(df)
pr = project(om, ProjectionConfig(tau_memory=720, driver="intensity"))

sizes = ev.groupby("cascade_id").size()
t_start = ev.groupby("cascade_id")["t_out"].min()
t0 = pr["t"].iloc[0]
idx = np.clip(((t_start.to_numpy() - t0) // BIN_S).astype(int), 0, len(pr) - 1)

latent = pr["latent_collapse"].to_numpy()
in_latent = latent[idx]

s = sizes.to_numpy()
a, b = s[in_latent], s[~in_latent]

rng = np.random.default_rng(0)
diff = a.mean() - b.mean()
null = []
lab = in_latent.copy()
for _ in range(1000):
    rng.shuffle(lab)
    null.append(s[lab].mean() - s[~lab].mean())
p = (np.array(null) >= diff).mean()

print(f"cascadas en latente: {len(a)}  fuera: {len(b)}")
print(f"tamaño medio | latente: {a.mean():.2f}  fuera: {b.mean():.2f}")
print(f"p(size>=4)   | latente: {(a>=4).mean():.3f}  fuera: {(b>=4).mean():.3f}")
print(f"diff={diff:.3f}  p={p:.4f}")

inten = om["intensity"].to_numpy()
recent = pd.Series(inten).rolling(12).mean().shift(1).fillna(0).to_numpy()
thr = np.quantile(recent, 1 - latent.mean())
triv = (recent > thr)[idx]
ta, tb = s[triv], s[~triv]
print(f"trivial p(size>=4) | alerta: {(ta>=4).mean():.3f}  fuera: {(tb>=4).mean():.3f}")

null_r = []
lab2 = in_latent.copy()
for _ in range(1000):
    rng.shuffle(lab2)
    x, y = s[lab2], s[~lab2]
    null_r.append(((x >= 4).mean() + 1e-9) / ((y >= 4).mean() + 1e-9))
r_prama = (a >= 4).mean() / (b >= 4).mean()
r_triv = (ta >= 4).mean() / (tb >= 4).mean()
print(f"ratio PRAMA={r_prama:.2f} trivial={r_triv:.2f} null_p95={np.quantile(null_r, .95):.2f}")

both = in_latent & triv
only_latent = in_latent & ~triv
only_triv = ~in_latent & triv
neither = ~in_latent & ~triv
for name, mask in [("ambos", both), ("solo_latente", only_latent),
                   ("solo_trivial", only_triv), ("ninguno", neither)]:
    x = s[mask]
    print(f"{name:>13}: n={len(x):5d}  p(size>=4)={(x>=4).mean():.3f}")