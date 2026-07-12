"""Aptadynamic electrical-grid observation package.

The domain code builds observable outage streams. Projection is delegated to
the universal ``prama_protokol`` kernel so kernel identity stays auditable.
"""

from .ingest import automatic_only, load_bpa
from .drivers import DRIVER_SPECS
from .omega import cascades, cascade_sizes, expected_profile, omega_series
from .projection import ProjectionConfig, project, stratify
from .validation import precursor_enrichment, zipf_alpha

__all__ = [
    "ProjectionConfig",
    "DRIVER_SPECS",
    "automatic_only",
    "cascade_sizes",
    "cascades",
    "expected_profile",
    "load_bpa",
    "omega_series",
    "precursor_enrichment",
    "project",
    "stratify",
    "zipf_alpha",
]
