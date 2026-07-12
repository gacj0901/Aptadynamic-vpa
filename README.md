# Aptadynamic-Electrical-Grid

Detection of **latent structural degradation** in electric power transmission,
before catastrophic manifestation. First empirical validation of the PRAMA
Protokol on a real-world domain.

The domain implementation is internally named **VPA** (Viability Power
Administration). BPA and NYISO are the first two records analyzed, not the
scope of the domain.

## What this does

Given a stream of transmission outages, the method projects it onto a small set
of dimensionless viability variables and asks a question distinct from
occurrence forecasting: **given that a cascade occurs, is the system in a state
where it is more likely to become severe?**

Occurrence — *whether* a cascade happens — is largely Markovian and plausibly
weather-driven on this record; a trailing-intensity baseline beats the
projection at it. Conditional severity — *how large* it becomes once it starts —
is substantially non-Markovian, and that is what this method captures.

## Architecture

```
        O_D                     π
Domain ────► Observables Ω ────► Γ(t) = (Δ, Ξ, λ, Θ, M, G) ────► Latent-collapse flag
      (domain-specific,       (fixed kernel,
       strictly causal)        identical across domains)
```

The projection kernel π never models the phenomenon: no grid topology,
propagation mechanism, loading, or weather covariate enters it. Only the
observation operator O_D is domain-specific. When a domain underperforms, the
diagnosis targets O_D fidelity — never kernel parameters. The kernel is imported
unchanged from the PRAMA Protokol reference, not reimplemented here.

## Projected magnitudes

| Magnitude | Definition | Role |
|---|---|---|
| Δ(t) | \|ω − ω̂\| / (ω̂ + 1), ω̂ = strictly causal E[intensity \| month × hour] | Structural decoupling — deviation from the system's own expected activity, never raw intensity |
| Ξ(t) | Σ K(t−s) Δ(s), exponential causal kernel, τ = 336 h | Non-Markovian tension accumulator |
| λ(t) | eroded by excess (Ξ−Θ)⁺, bounded recovery; recovery never reduces Ξ | Remaining absorption capacity |
| Θ(λ) | θ_s · λ, contracts as excess accumulates | Endogenous threshold, not a fixed cutoff |
| M(t) | Θ − Ξ | Viability margin |
| G(t) | trailing mean of M, then G[0]=0 and G[t]=smooth_M[t]-smooth_M[t-1] | Strictly causal margin trend |

**Latent collapse:** ω(t) > 0 ∧ M ≥ 0 ∧ G < 0 — the system operates with
positive but shrinking margin. A direction-based flag, not a level exceedance.
This is the state whose severity-conditioning power the analysis evaluates.

## Historical results from 0.1.0 — not causally revalidated

The figures below are retained only as provenance. They used the 0.1.0 batch
kernel and/or superseded evaluation procedures and are not current empirical
claims. Regenerate `results/reproduction_*.json` with 0.2.1 before reporting
new figures.

### BPA (1999–2017, 14,258 automatic outages)

- Conditional severity: P(size ≥ 4 | cascade occurs) = **0.096** inside
  latent-collapse periods vs **0.003** outside — **enrichment ratio 28.75**
  (historical iid label shuffle; superseded by the circular-shift null).
- Causal Markovian baseline (trailing intensity, matched alert budget): **3.16**.
- Historical 0.1.0 provenance: an outcome-exposed sweep over {168, 336, 720} h
  reported increasing enrichment with memory. It has not been causally
  revalidated and does not select the current scale. G1 freezes τ = 336 h; see
  `ANOMALIES.md` (README memory-scale inconsistency).
- Independence partition: periods flagged only by the projection retain
  P(size ≥ 4) = **0.086** vs **0.003** where neither signal fires (~29×). At this
  memory scale every baseline alert falls inside a projection-flagged period,
  while 89% of projection-flagged cascades carry no baseline alert.
- Occurrence forecasting remains Markovian: the trailing-intensity baseline
  outperforms the projection at all horizons (6–48 h).
- External consistency: the pipeline recovers a Zipf exponent of ≈2.99 for
  cascade sizes, used as a downstream check, never as a calibration target.

### NYISO (2008–2021, 9,600 forced outages)

- With the causal decoupling Δ: **enrichment ratio 2.44**, above the
  permutation null (95th percentile 1.26). Reported as exploratory, not
  confirmatory (the observation layer and τ were adjusted after outcome exposure
  during development).
- Ablation: replacing Δ with raw normalized intensity (Ô held constant) inverts
  the result to **0.55**, isolating the failure to the observation layer — the
  kernel is untouched. On denser BPA the same degeneration only weakens the
  result (28.75 → 4.95) rather than inverting it.

## Pipeline

```
ingest → omega → projection → validation
```

- **ingest**: outage records → canonical events; bus identifiers anonymized by hash
- **omega**: events → observables (intensity, load; cascades by 1-hour gap) with
  no mechanism assumption
- **projection**: Ω → Γ, latent-collapse detection
- **validation**: conditional severity vs causal Markovian baseline; α treated as
  a data property, never a target

## Data

Data files are not distributed with this repository.

1. Obtain the cleaned BPA data (courtesy of Ian Dobson, Iowa State University):
   `outagesBPA.txt` and its cleaning documentation (CFAREADBPA-10) from
   https://iandobson.ece.iastate.edu/
2. Place in `data/dobson_bpa/` and export to CSV.
3. NYISO: place `outagesNYISO.txt` in `data/dobson_nyiso/` and run
   `python scripts/convert_nyiso_to_csv.py data/dobson_nyiso/outagesNYISO.txt data/dobson_nyiso/outagesNYISO.csv`

Bus identifiers are anonymized in every output. No complete or sensitive details
of particular cascading sequences are reported.

## Usage

```
pip install -e .

python scripts/reproduce_bpa.py data/dobson_bpa/outagesBPA.csv --domain BPA --calibration-id bpa_calib_1999_2003_v1 --induction-epoch bpa_induction_v1 --calibration-end 2004-01-01T00:00:00Z --output-prefix results/reproduction_bpa
python scripts/reproduce_bpa.py data/dobson_nyiso/outagesNYISO.csv --domain NYISO --calibration-id nyiso_calib_2008_2010_v1 --induction-epoch nyiso_induction_v1 --calibration-end 2011-01-01T00:00:00Z --output-prefix results/reproduction_nyiso
```

## Methodological discipline

- Evaluation is strictly at the hour before cascade start (`idx-1`) and only on
  valid post-calibration rows. The baseline threshold is fitted once on an
  externally declared, frozen, versioned cohort; it never drifts during evaluation.
- Mass at the fixed threshold is handled by a seeded, index-stable randomized
  tie rule whose acceptance probability exactly closes the calibration budget.
- PRAMA and baseline are compared with a paired cascade bootstrap at the same
  evaluation indices and under the same fixed instrument.
- Both `activity` and `always_valid` sigma modes are reported as a prespecified
  sensitivity analysis; neither is selected by enrichment.
- The primary temporal null circularly shifts the complete alert series (10,000
  seeded replicates by default), preserving autocorrelation and alert blocks.
- Negative results reported as found (occurrence stays Markovian; the NYISO
  degeneration and its ablation are reported in full).
- Kernel parameters fixed across domains; per-domain diagnosis targets O_D
  fidelity only.
- NYISO is exploratory: a confirmatory study with τ and the observation layer
  fixed before data exposure, on an independent record, is the appropriate
  next step.

## Foundations

π implements the aptadynamic framework: a formal theory of structural viability
generalizing Aubin viability theory with a genuine memory kernel and an
endogenous, history-contracted threshold. The mathematical corpus is public
(Zenodo, DOI https://doi.org/10.5281/zenodo.21270506); the normative protocol specification and
the discipline overview live in the project's root repositories. None of the
underlying theory is required to run or extend this repository.

## Citing

See `CITATION.cff` (GitHub's "Cite this repository").

## Acknowledgments

Cleaned BPA outage data and processed NYISO data courtesy of Ian Dobson (Iowa
State University), whose foundational work on cascading-failure statistics made
this validation possible, and whose caveats — the unknown weather/cascading
proportion, and the preference for a Zipf over a branching-process description —
materially shaped the design and interpretation:

- Dobson, Carreras, Lynch, Newman. *Complex systems analysis of series of
  blackouts.* Chaos 17(2):026103, 2007.
- Carreras, Newman, Dobson, Poole. *Evidence for self-organized criticality in
  a time series of electric power system blackouts.* IEEE TCAS-I 51(9), 2004.
- Ren, Dobson. *Using transmission line outage data to estimate cascading
  failure propagation.* IEEE TCAS-II 55(9), 2008.
- Dobson. *Estimating the propagation and extent of cascading line outages with
  a branching process.* IEEE TPS 27(4), 2012.

## Disclaimer

The analysis and any conclusions are strictly those of the authors and not of
Bonneville Power Administration.
