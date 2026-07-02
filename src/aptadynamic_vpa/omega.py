"""Ω: proyección de eventos BPA a observables. Sin presunción de mecanismo.

Observables:
    intensity(t)   : conteo de outages por bin
    load(t)        : outages simultáneamente activos por bin (presión estructural)
    severity(t)    : suma ponderada (voltage · duración) por bin
    cascades       : agrupación por gap temporal (Dobson: gap = 1 h)

Ω es entrada de projection/. Nada aquí interpreta causas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GAP_S = 3600
BIN_S = 3600


def cascades(df: pd.DataFrame, gap_s: int = GAP_S) -> pd.DataFrame:
    t = df["t_out"].to_numpy()
    new = np.concatenate([[True], np.diff(t) > gap_s])
    df = df.copy()
    df["cascade_id"] = np.cumsum(new)
    return df


def cascade_sizes(df: pd.DataFrame) -> pd.Series:
    return df.groupby("cascade_id").size()


def omega_series(df: pd.DataFrame, bin_s: int = BIN_S) -> pd.DataFrame:
    
    df = df.copy()
    df["t_in"] = df["t_in"].fillna(df["t_out"])
    t0 = int(df["t_out"].min())
    t1 = int(df["t_in"].max())
   

    edges = np.arange(t0, t1 + bin_s, bin_s)
    n = len(edges) - 1

    intensity = np.zeros(n)
    severity = np.zeros(n)
    load = np.zeros(n)

    idx = np.clip(((df["t_out"].to_numpy() - t0) // bin_s).astype(int), 0, n - 1)
    np.add.at(intensity, idx, 1.0)

    volt = df.get("voltage_kv", pd.Series(1.0, index=df.index)).fillna(0).to_numpy()
    dur = df["duration_s"].to_numpy()
    np.add.at(severity, idx, volt * np.log1p(dur))

    i0 = np.clip(((df["t_out"].to_numpy() - t0) // bin_s).astype(int), 0, n - 1)
    i1 = np.clip(((df["t_in"].to_numpy() - t0) // bin_s).astype(int), 0, n - 1)
    for a, b in zip(i0, i1):
        load[a : b + 1] += 1.0

    return pd.DataFrame(
        {
            "t": edges[:-1],
            "intensity": intensity,
            "load": load,
            "severity": severity,
        }
    )
