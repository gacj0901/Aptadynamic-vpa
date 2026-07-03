# Aptadynamic-VPA (Viability Power Administration)
// G.A.C.J. | ORCID: 0009-0009-5649-1359
// Copyright © 2026 G.A.C.J.  Released under AGPL -3.0

Implementation of the Aptadynamic PRAMA-Protokol over Bonneville Power Administration
transmission outage data. First empirical validation of the aptadynamic
framework on a real-world domain.

## Framework

Aptadynamics models viability of systems under perturbation, historical
accumulation, and endogenous threshold deformation. Its object is the
trajectory, not the state. PRAMA is a domain-independent projection
protocol: it operates exclusively on observables Ω and never models
domain internals.

Core magnitudes (see APTADINAMIA logical-mathematical corpus: https://doi.org/10.5281/zenodo.20369325):

- Δ(t) — structural decoupling, projected from observed outage intensity
- Ξ(t) = ∫ K(t−τ) Δ(τ) dτ — accumulated tension, genuinely non-Markovian
- λ(t) — historical permissivity; erosion by Ξ, bounded recovery that
  never erases memory
- Θ(λ) — endogenous viability threshold, contractive with history
- M(t) = Θ(λ) − Ξ — viability margin
- G(t) = D⁺M — structural generation power

Latent collapse: observable output persists while M ≥ 0 and G < 0.
Regime stratification S₁–S₄ is defined on the (M, G) plane:
S₁ viable, S₂ tension, S₃ critical, S₄ collapse.

## Pipeline
ingest  →  omega  →  projection  →  validation

- **ingest**: cleaned BPA outage records → canonical events; bus names
  anonymized by hash in all outputs
- **omega**: events → observables Ω (intensity, load, severity; cascade
  grouping by 1h gap) with no assumption about outage mechanism
- **projection**: Ω → (Δ, Ξ, λ, Θ, M, G), stratification, latent-collapse
  detection
- **validation**: precursor enrichment against real cascades; Zipf α and
  Hurst H are treated as properties of the data, never calibration targets

## Results (BPA 1999–2017)

- Zipf exponent of cascade sizes: α = 2.99 (reference: Dobson, α ≈ 2.87)
- Stratification on (M, G) with intensity-driven Δ enriches prediction of
  large cascades (99th percentile) ×1.9 at 12h horizon
- Significance: circular permutation test preserving autocorrelation,
  p < 0.005

  ## Replication (NYISO 2008–2021)

Negative: latent collapse does not discriminate conditional cascade
severity in NYISO (ratio 0.55, both weekly and monthly memory).
Sparse forced-outage stream (~2 events/day) leaves Ξ uninformative.
This delimits the protocol's applicability rather than refuting it:
projection requires minimum observable density.

## Usage
pip install -e .
python scripts/run_pipeline.py <path-to-outagesBPA.csv>
python scripts/sweep.py <path>      # parameter sweep
python scripts/permtest.py <path>   # significance test

## Data

Cleaned BPA outage data courtesy of  Dr. Ian Dobson Sandbulte Professor
Electrical and Computer Engineering (Iowa State University).
Data files are not distributed with this repository. Bus names are
anonymized in every output.

The analysis and any conclusions are strictly those of the authors and
not of Bonneville Power Administration.

- License

This project is released under the GNU Affero General Public License v3.0 (AGPL-3.0).

Commercial licensing and research collaborations may be available separately.
