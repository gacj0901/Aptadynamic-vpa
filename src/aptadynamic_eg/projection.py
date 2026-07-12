"""Electrical-grid adapter for the universal PRAMA projection kernel."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from prama_protokol import KernelConfig, project as prama_project, stratify

from .drivers import driver_spec
from .omega import expected_profile


@dataclass
class ProjectionConfig:
    tau_memory: float = 24 * 14
    lambda_eq: float = 1.0
    lambda_recovery: float = 0.005
    lambda_min: float = 0.1
    theta_scale: float = 2.0
    g_smooth: int = 24
    kappa: float = 0.05
    driver: str = "intensity"
    min_context_count: int = 10
    min_hist: int = 24 * 30
    allow_noncausal_exploratory: bool = False

    def kernel_config(self) -> KernelConfig:
        return KernelConfig(
            tau_memory=self.tau_memory,
            lambda_eq=self.lambda_eq,
            lambda_recovery=self.lambda_recovery,
            lambda_min=self.lambda_min,
            theta_scale=self.theta_scale,
            g_smooth=self.g_smooth,
            kappa=self.kappa,
        )


def project(
    omega: pd.DataFrame,
    cfg: ProjectionConfig | None = None,
    sigma_op_mode: str = "activity",
) -> pd.DataFrame:
    """Project omega with an explicit observation-operator validity mode.

    ``activity`` preserves the historical ``intensity > 0`` operator. At a
    cascade-start bin this was tautological; evaluation now occurs at ``idx-1``,
    where it requires activity in the preceding hour. ``always_valid`` sets
    sigma_op true exactly where a causal expectation exists.
    """

    if cfg is None:
        cfg = ProjectionConfig()
    if omega.empty:
        raise ValueError("cannot project an empty omega series")
    if cfg.driver not in omega.columns:
        raise ValueError(f"driver {cfg.driver!r} not present in omega columns: {list(omega.columns)}")
    spec = driver_spec(cfg.driver)
    noncausal_driver = spec["causal"] is not True
    if noncausal_driver and not cfg.allow_noncausal_exploratory:
        raise ValueError(
            f"driver {cfg.driver!r} is not unconditionally causal and is blocked "
            "from evaluation; see ANOMALIES.md (b). Set "
            "allow_noncausal_exploratory=True only for labeled exploratory use."
        )

    obs = omega[cfg.driver].to_numpy(dtype=float)
    expected = expected_profile(
        omega,
        driver=cfg.driver,
        min_context_count=cfg.min_context_count,
        min_hist=cfg.min_hist,
    )
    valid_expectation = ~np.isnan(expected)
    if sigma_op_mode == "activity":
        sigma_op = omega["intensity"].to_numpy(dtype=float) > 0
    elif sigma_op_mode == "always_valid":
        sigma_op = valid_expectation
    else:
        raise ValueError("sigma_op_mode must be 'activity' or 'always_valid'")
    gamma = prama_project(obs, expected, cfg.kernel_config(), sigma_op=sigma_op)

    out = omega.copy()
    for col in ("delta", "xi", "lambda", "theta", "M", "G", "latent_collapse", "stratum", "valid"):
        out[col] = gamma[col].to_numpy()
    out["driver"] = cfg.driver
    out["noncausal_driver"] = noncausal_driver
    out["sigma_op_mode"] = sigma_op_mode
    return out
