"""Aptadynamic electrical-grid observation package.

The domain code builds observable outage streams. Projection is delegated to
the universal ``prama_protokol`` kernel so kernel identity stays auditable.
"""

from .ingest import automatic_only, automatic_only_with_audit, load_bpa
from .drivers import DRIVER_SPECS
from .g2 import (
    G2InterfaceConfig,
    build_hourly_domain,
    causal_trailing_conditional_mean,
    context_codes,
    find_verification_cut,
    normalize_and_project,
)
from .omega import cascades, cascade_sizes, expected_profile, omega_series
from .projection import ProjectionConfig, project, stratify
from .validation import precursor_enrichment, zipf_alpha

__all__ = [
    "ProjectionConfig",
    "DRIVER_SPECS",
    "G2InterfaceConfig",
    "automatic_only",
    "automatic_only_with_audit",
    "build_hourly_domain",
    "cascade_sizes",
    "cascades",
    "causal_trailing_conditional_mean",
    "context_codes",
    "expected_profile",
    "find_verification_cut",
    "load_bpa",
    "normalize_and_project",
    "omega_series",
    "precursor_enrichment",
    "project",
    "stratify",
    "zipf_alpha",
]
