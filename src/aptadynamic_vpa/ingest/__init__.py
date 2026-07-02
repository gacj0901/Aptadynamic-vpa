"""Ingesta BPA: CSV limpio (export de CFAREADBPA-10) → eventos canónicos.

Salida canónica por evento:
    t_out, t_in : segundos absolutos (OutAbstime/InAbstime, época Mathematica)
    duration_s  : t_in - t_out
    voltage_kv, length_mi, reactance
    outage_type : Auto | Plan | ...
    bus_a, bus_b: anonimizados (hash) — nunca exportar nombres reales
    outage_id
"""

from __future__ import annotations

import hashlib
import pandas as pd

REQUIRED_ANY = [
    ("OutAbstime", "InAbstime"),
    ("OutDatetime", "InDatetime"),
]

COLMAP = {
    "OutAbstime": "t_out",
    "InAbstime": "t_in",
    "Voltage": "voltage_kv",
    "Length": "length_mi",
    "Reactance": "reactance",
    "OutageType": "outage_type",
    "OutageID": "outage_id",
    "Duration": "duration_min",
}


def _anon(name: str) -> str:
    return hashlib.sha1(name.strip().lower().encode()).hexdigest()[:10]


def load_bpa(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={k: v for k, v in COLMAP.items() if k in df.columns})

    if "t_out" not in df.columns:
        if "OutDatetime" not in df.columns:
            raise ValueError(f"columnas de tiempo ausentes; presentes: {list(df.columns)}")
        df["t_out"] = pd.to_datetime(df["OutDatetime"]).astype("int64") // 10**9
        df["t_in"] = pd.to_datetime(df["InDatetime"]).astype("int64") // 10**9

    df["duration_s"] = (df["t_in"] - df["t_out"]).clip(lower=0)

    for col in ("BusNames", "bus_names"):
        if col in df.columns:
            buses = df[col].astype(str).str.strip("{}").str.split(",", n=1, expand=True)
            df["bus_a"] = buses[0].fillna("").map(_anon)
            df["bus_b"] = buses[1].fillna("").map(_anon) if buses.shape[1] > 1 else ""
            df = df.drop(columns=[col])
            break

    drop = [c for c in ("Name", "NameClean", "LineName") if c in df.columns]
    df = df.drop(columns=drop)

    df = df.sort_values("t_out").reset_index(drop=True)
    return df


def automatic_only(df: pd.DataFrame) -> pd.DataFrame:
    if "outage_type" not in df.columns:
        return df
    return df[df["outage_type"].astype(str).str.strip().str.lower() == "auto"].reset_index(drop=True)
