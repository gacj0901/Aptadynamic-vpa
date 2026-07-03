
# Aptadynamic-Electrical-Grid (Viability Power Administration)
# Aptadynamic-VPA (Viability Power Administration)

**G.A.C.J.** | ORCID: 0009-0009-5649-1359
Copyright © 2026 G.A.C.J.
Released under the **GNU Affero General Public License v3.0 (AGPL-3.0)**

---
Implementation of the PRAMA Protokol over Bonneville Power Administration
transmission outage data. First empirical validation of the aptadynamic
framework on a real-world domain.

## Architecture

```
        O_D                     π
Domain ────► Observables Ω ────► Γ(t) = (Δ, Ξ, λ, Θ, M, G) ────► Regime / Alerts
      (domain-specific,       (fixed kernel,
       strictly causal)        identical across domains)
```

The projection kernel π never models the phenomenon: no grid topology,
propagation mechanism, or weather causation enters it. Only the observation
operator O_D is domain-specific.

## Projected magnitudes

| Magnitude | Definition | Role |
|---|---|---|
| Δ(t) | \|O − Ô\| / (Ô + 1), Ô = causal E[intensity \| hour, month] | Structural decoupling — never raw intensity |
| Ξ(t) | ∫ K(t−τ) Δ(τ) dτ, exponential causal kernel | Non-Markovian tension accumulator |
| λ(t) | eroded by accumulated excess (Ξ−Θ)⁺, bounded recovery that never erases Ξ | Historical permissivity |
| Θ(λ) | strictly increasing in λ | Endogenous threshold, contracts with history |
| M(t) | Θ(λ) − Ξ | Viability margin |
| G(t) | D⁺M | Margin generation power |

**Latent collapse:** O(t) > 0 ∧ M ≥ 0 ∧ G < 0 — the system operates normally
while consuming its margin. Regime stratification on the (M, G) plane:
S₁ viable · S₂ tension · S₃ critical · S₄ collapse.

## Empirical Results

### BPA (1999–2017, 14,258 automatic outages)

- Zipf exponent of cascade sizes: α = 2.99 (external consistency check;
  published reference ≈ 2.87). Never used as a calibration target.
- Conditional severity: P(size ≥ 4 | cascade occurs) = 0.091 inside
  latent-collapse periods vs 0.006 outside — **ratio 16.0**
  (label-shuffle permutation, p < 0.001; null 95th percentile 1.16).
- Causal Markovian baseline (trailing intensity, equal alert budget): 3.16.
- Independence partition: latent-only periods retain P(size ≥ 4) = 0.081
  vs 0.006 where neither signal is present (~13×).
- Occurrence forecasting remains Markovian: the trailing-intensity baseline
  outperforms the projection at all horizons (6–48 h).

### NYISO (2008–2021, 9,600 forced outages)

- Initial negative result (ratio 0.55) traced to a degenerate Δ based on
  raw intensity — a failure of the observation operator, not the kernel.
- With Δ as genuine causal decoupling: **ratio 1.90**, above the permutation
  null (95th percentile 1.26). Same kernel, unchanged.

## Pipeline

```
ingest → omega → projection → validation
```

- **ingest**: outage records → canonical events; bus names anonymized by hash
- **omega**: events → observables (intensity, load, severity; cascades by
  1-hour gap) with no mechanism assumption
- **projection**: Ω → Γ, stratification, latent-collapse detection
- **validation**: conditional severity vs causal Markovian baseline;
  α and H treated as data properties, never calibration targets

## Data

Data files are not distributed with this repository.

1. Obtain the cleaned BPA data (courtesy of Ian Dobson, Iowa State University):
   `outagesBPA.txt` and its cleaning documentation `CFAREADBPA-10.pdf` from
   https://iandobson.ece.iastate.edu/
2. Place them in `data/dobson_bpa/` and export to CSV (Mathematica script
   `export_bpa_to_csv.wls`, or equivalent).
3. For NYISO: place `outagesNYISO.txt` in `data/dobson_nyiso/` and run
   `python scripts/convert_nyiso_to_csv.py data/dobson_nyiso/outagesNYISO.txt data/dobson_nyiso/outagesNYISO.csv`

Bus names are anonymized in every output. The analysis and any conclusions
are strictly those of the authors and not of Bonneville Power Administration.

## Usage

```
pip install -e .

python scripts/run_pipeline.py  data/dobson_bpa/outagesBPA.csv   # full pipeline
python scripts/latent_test.py   data/dobson_bpa/outagesBPA.csv   # conditional severity + independence partition
python scripts/baseline_test.py data/dobson_bpa/outagesBPA.csv   # horizon curve vs Markovian baseline
python scripts/permtest.py      data/dobson_bpa/outagesBPA.csv   # permutation significance
python scripts/sweep.py         data/dobson_bpa/outagesBPA.csv   # parameter sweep
```

## Methodological discipline

- All baselines strictly causal; a future-leaking baseline discovered
  mid-analysis was corrected before any comparison was retained.
- Negative results reported as found; no parameter reversal to force
  conclusions.
- Kernel parameters fixed across domains; per-domain diagnosis targets
  O_D fidelity only.

## Foundations

π implements the aptadynamic framework: a formal theory of structural
viability generalizing Aubin viability theory with a genuine memory kernel
and an endogenous, history-contracted threshold. Full axiomatization in the
mathematical corpus (https://doi.org/10.5281/zenodo.20369325). Its conceptual
origin is a published ontological work; none of it is required to run or
extend this repository.

## Acknowledgments

Cleaned BPA outage data and NYISO data courtesy of Ian Dobson (Iowa State
University), whose foundational work on cascading failure statistics made
this validation possible:

- Dobson, Carreras, Lynch, Newman. *Complex systems analysis of series of
  blackouts.* Chaos 17(2):026103, 2007.
- Ren, Dobson. *Using transmission line outage data to estimate cascading
  failure propagation.* IEEE TCAS-II 55(9), 2008.
- Dobson. *Estimating the propagation and extent of cascading line outages
  with a branching process.* IEEE TPS 27(4), 2012.

The analysis and any conclusions are strictly those of the authors and not
of Bonneville Power Administration.


---

# License

This project is released under the **GNU Affero General Public License v3.0 (AGPL-3.0).**
Commercial licensing, industrial collaborations and academic research partnerships may be available separately.

