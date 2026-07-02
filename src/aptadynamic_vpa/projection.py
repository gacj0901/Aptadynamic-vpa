"""Proyección aptadinámica sobre Ω (Corpus §4).

    Δ(t)  = desacoplamiento observable (severity normalizada sobre baseline)
    Ξ(t)  = ∫ K(t-τ) Δ(τ) dτ, kernel exponencial con memoria genuina
    λ(t)  = permisividad histórica: erosión por Ξ, recuperación acotada
            (sin reincarnación markoviana: recuperación nunca borra Ξ)
    Θ(λ)  = umbral endógeno, contractivo con la historia
    M(t)  = Θ(λ) - Ξ         margen de viabilidad
    G(t)  = D⁺M              potencia de generación estructural
Colapso latente: O(t) > 0 ∧ M ≥ 0 ∧ G < 0.

Estratificación S₁–S₄ sobre (M, G): geometría en el plano margen-potencia,
no cortes rectangulares — frontera por curvas de nivel de M·sign(G) y ‖(M,G)‖.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ProjectionConfig:
    tau_memory: float = 24 * 14        # bins (h): memoria de Ξ, ~2 semanas
    lambda_eq: float = 1.0
    lambda_erosion: float = 0.02
    lambda_recovery: float = 0.005
    lambda_min: float = 0.1
    theta_scale: float = 1.0
    baseline_win: int = 24 * 90        # bins: baseline móvil de Δ, ~90 días
    g_smooth: int = 24                 # suavizado de D⁺M
    #driver: str = "load"
    #driver: str = "intensity"
    driver: str = "severity"

def project(omega: pd.DataFrame, cfg: ProjectionConfig = ProjectionConfig()) -> pd.DataFrame:
    s = omega[cfg.driver].to_numpy(dtype=float)
    n = len(s)

    nz = s[s > 0]
    scale = np.median(nz) if len(nz) else 1.0
    delta = s / max(scale, 1e-9)

    a = np.exp(-1.0 / cfg.tau_memory)
    xi = np.zeros(n)
    lam = np.full(n, cfg.lambda_eq)
    for i in range(1, n):
        xi[i] = a * xi[i - 1] + (1 - a) * delta[i]
        erosion = cfg.lambda_erosion * xi[i]
        recovery = cfg.lambda_recovery * (cfg.lambda_eq - lam[i - 1])
        lam[i] = np.clip(lam[i - 1] - erosion + recovery, cfg.lambda_min, cfg.lambda_eq)

    theta = cfg.theta_scale * lam
    m = theta - xi

    g = np.gradient(pd.Series(m).rolling(cfg.g_smooth, min_periods=1).mean().to_numpy())

    out = omega.copy()
    out["delta"] = delta
    out["xi"] = xi
    out["lambda"] = lam
    out["theta"] = theta
    out["M"] = m
    out["G"] = g
    out["latent_collapse"] = (omega["intensity"].to_numpy() > 0) & (m >= 0) & (g < 0)
    out["stratum"] = stratify(m, g)
    return out


def stratify(m: np.ndarray, g: np.ndarray) -> np.ndarray:
    s = np.ones(len(m), dtype=int)
    s[(m > 0) & (g < 0)] = 2
    s[(m <= 0) & (g >= 0)] = 3
    s[(m <= 0) & (g < 0)] = 4
    return s
