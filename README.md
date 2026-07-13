# Aptadynamic-Electrical-Grid

Electrical-domain implementation of the PRAMA observation and projection
protocol. The repository tests whether a fixed universal kernel adds useful
discrimination of severe cascading-outage states beyond simpler causal
baselines.

## Current empirical status

The final preregistered NYISO G2 experiment is complete. It is a valid
confirmatory **negative result**, not a successful validation of incremental
PRAMA value.

- Frozen preregistration: [`PREREGISTRATION_G2.md`](PREREGISTRATION_G2.md),
  commit `6672bda`.
- Final register: [`G2_RESULT_H5.md`](G2_RESULT_H5.md), commit `3f75697`.
- Classification: `confirmatory_criterion_not_met`.
- Frozen program rule: `program_falsification_activated: true`.
- Primary observation channel CH-L passed every gate independently in
  calibration and evaluation. The negative result is therefore not classified
  as an observation-interface failure.
- Calibration selected B-TRIV, a trailing outage-intensity baseline, as the
  primary comparator. In evaluation, the PRAMA-minus-B-TRIV risk-difference
  contrast was `-0.0496230` with one-sided bootstrap `p = 1.0`.
- PRAMA did outperform the secondary B-AC1 comparator (`+0.037987`, raw
  `p = 0.00250`, Holm-adjusted `p = 0.00750`). This secondary result is
  reported in full, but it does not replace the single primary comparison or
  change the frozen classification.

Plain-language interpretation: the multichannel measurement instrument worked,
but PRAMA did not justify its additional complexity against the simple baseline
chosen before evaluation.

This repository does **not** support claims that PRAMA is empirically validated
on the grid, predicts blackouts, or provides an operational early-warning
system.

## BPA and NYISO records

The two records have different statuses and must not be conflated.

| Record | Current status |
|---|---|
| BPA G1 | `invalid_for_confirmatory_claim_C3_gate_failed`. The outage-intensity interface did not decouple sufficiently from raw activity in evaluation (`separation approximately 0.008 < 0.01`). This does not establish either PRAMA superiority or defeat. |
| NYISO G1 | Historical/exploratory only; the sparse intensity interface was not a valid basis for a current confirmatory claim. |
| NYISO G2 | Valid confirmatory experiment on the CH-L load channel. Primary criterion not met; frozen program-falsification rule activated. |

BPA was not included in G2 because no coextensive physical-channel preflight
was committed for it. Reopening BPA would require a new observation epoch,
physical data preflight, contracts and preregistration. Re-tuning the old
outage-intensity channel is not a valid substitute.

## Scientific question

The evaluation does not forecast whether an outage cascade will begin. It asks:

> At the hour before an independently defined cascade begins, does the PRAMA
> state discriminate severe from non-severe final cascade sizes better than
> causal reference methods evaluated at the same points?

Outcomes are cascade-level and evaluated at `idx - 1`. The repository makes no
alert-horizon or early-warning claim.

## Architecture

```text
        O_D                     pi
Domain ----> Observables Omega ----> Gamma(t) = (Delta, Xi, lambda, Theta, M, G)
      domain-specific          fixed universal kernel
```

The PRAMA kernel is imported from `prama-protokol==0.2.1`. Domain-specific
choices belong to the electrical observation layer: source channels,
normalization, causal expectation, validity and operational-state semantics.

The gate record distinguishes two kinds of negative result:

1. **interface invalidity** — a channel fails a declared observation gate, so
   no confirmatory performance claim is allowed for that channel;
2. **criterion not met** — the primary channel passes its gates, outcomes are
   unlocked, and PRAMA fails the preregistered comparison.

G2 produced the second result on CH-L. It is not legitimate to reinterpret it
as a kernel-parameter or local-data problem after the fact.

## G2 observation channels

| Channel | Observable | Status |
|---|---|---|
| CH-L, primary | Hourly mean of total NYCA load, summed from 11 internal zones and normalized by the frozen calibration median | Passed all calibration and evaluation gates |
| CH-P, secondary | Within-hour standard deviation of mean zonal real-time LBMP | Invalid: failed calibration C3 and evaluation inductive-ratio gate |
| CH-F, continuity | Hourly automatic-outage starts on the aligned G2 clock | Invalid: failed inductive-ratio gates and calibration density gate |

The G2 clock uses aligned UTC hours. Source slots are valid only when all 11
internal NYISO zones are present. An hour requires all twelve five-minute slots;
there is no interpolation, forward fill or synthetic replacement.

For CH-L and CH-P, the causal expectation uses UTC month, UTC hour and local
New York weekday/weekend type with a trailing 1096-day per-context window. The
primary operational indicator is based on valid load above a calibration-frozen
floor, not the historical `intensity > 0` activity proxy.

## Fixed kernel magnitudes

| Magnitude | Definition | Role |
|---|---|---|
| Delta(t) | `abs(omega - expected) / (expected + 1)` | Deviation from the strictly causal channel expectation |
| Xi(t) | Exponential causal accumulation of Delta, `τ = 336 h` | Memory/tension accumulator |
| lambda(t) | Eroded by excess over Theta, with bounded recovery | Remaining permissivity |
| Theta(lambda) | `theta_scale * lambda` | Endogenous threshold |
| M(t) | `Theta - Xi` | Viability margin |
| G(t) | `G[0] = 0`; then backward difference of trailing-smoothed M | Strictly causal margin trend |

The arithmetic of this kernel was not tuned for G2 and is bit-certified across
Python and Rust by the PRAMA repository's golden vectors.

## Confirmatory design and results

H3 froze the complete design before evaluation outcomes were accessed:

- calibration ID `nyiso_calib_G2_v1`;
- exclusive cut `2011-01-01T00:00:00Z`;
- primary channel CH-L;
- severe cascade threshold `ceil(P95)` from complete calibration cascades;
- B-TRIV, B-VAR, B-AC1 and B-COMP comparator family;
- comparator selected by maximum calibration enrichment;
- one primary paired cascade-bootstrap comparison;
- 10,000 bootstrap replicates, seed `20260714`;
- tie seed `20260715`;
- 10,000 circular-alignment replicates, seed `20260716`;
- 1,000 stratified C4 nulls, seed `20260717`.

CH-L gate values:

| Gate | Calibration | Evaluation |
|---|---:|---:|
| C3 | PASS, absolute branch | PASS, absolute branch |
| Inductive ratio | 0.786794 | 0.780029 |
| C4 density | 2.850953 | 1.602696 |
| Memory ratio | 56.39 | 258.73 |

Primary evaluation used 4,590 common-valid cascades and a frozen severe-size
threshold of 3 outages:

| Comparator | Role | PRAMA-minus-comparator contrast | Raw p | Holm p |
|---|---|---:|---:|---:|
| B-TRIV | Primary | -0.049623 | 1.000000 | n/a |
| B-VAR | Secondary | +0.001321 | 0.459054 | 0.459054 |
| B-AC1 | Secondary | +0.037987 | 0.002500 | 0.007499 |
| B-COMP | Secondary | +0.017790 | 0.082192 | 0.164384 |

The circular alignment null returned `p = 0.179882`.

The historical field `p_one_sided_prama_superior` is retained for schema
compatibility. It is the plus-one-corrected proportion of ordinary paired
bootstrap contrasts at or below zero (a percentile-bootstrap tail
proportion); it is **not** a p-value from a bootstrap null distribution
centered at zero. This terminology clarification does not recalculate or
reclassify G2.

Likewise, `program_falsification_activated: true` means that the concrete rule
frozen in H3 section 0 was activated for the G2 hypothesis of incremental
PRAMA value. It does not claim a universal falsification of the aptadynamic
formalism.

## Evidence and audit trail

The current result is self-contained in:

- [`G2_DATA_PREFLIGHT.md`](G2_DATA_PREFLIGHT.md) — sources, coverage, gaps
  and data-use boundary;
- [`G2_OD_CONTRACTS_H2.md`](G2_OD_CONTRACTS_H2.md) — channel contracts;
- [`G2_VERIFICATION_1.md`](G2_VERIFICATION_1.md) — mechanical split;
- [`G2_H2_MEASUREMENTS.json`](G2_H2_MEASUREMENTS.json) — calibration-only
  diagnostics;
- [`PREREGISTRATION_G2.md`](PREREGISTRATION_G2.md) — frozen H3;
- [`results/g2_confirmatory_H4_gates.json`](results/g2_confirmatory_H4_gates.json)
  — gates serialized before outcome statistics;
- [`results/g2_confirmatory_H4.json`](results/g2_confirmatory_H4.json) — full
  confirmatory report;
- [`results/g2_confirmatory_H4.csv`](results/g2_confirmatory_H4.csv) — compact
  comparator table;
- [`G2_RESULT_H5.md`](G2_RESULT_H5.md) — final classification and artifact
  hashes;
- [`G2_IMPLEMENTATION_AUDIT.md`](G2_IMPLEMENTATION_AUDIT.md) — post-H5
  runtime/analytical audit without an H4 rerun;
- [`results/g2_boundary_audit_post_h5.json`](results/g2_boundary_audit_post_h5.json)
  — safe aggregate confirming zero cascades across the frozen cut;
- [`ANOMALIES.md`](ANOMALIES.md) — append-only implementation incident
  register.

The successful H4 run started from clean grid and PRAMA trees. Four aborted
invocations are preserved in `ANOMALIES.md`; none changed a frozen threshold,
partition, seed, replicate count, comparator family or decision rule.

## Historical 0.1.0 results — provenance only

Older README versions reported BPA enrichment `28.75x` and exploratory NYISO
enrichment `2.44x`. Those figures came from superseded, outcome-exposed or
otherwise non-confirmatory procedures. They are retained in Git history and
the anomaly record as provenance, but they are **not current empirical claims**
and must not be used to describe the present status.

## Data

Raw data are not distributed with this repository.

- The BPA outage record and its cleaning documentation originated with Ian
  Dobson and collaborators at Iowa State University.
- The NYISO outage record is locally ingested from the Dobson-format dataset.
- G2 CH-L and CH-P use official NYISO five-minute load and real-time zonal LBMP
  archives. Raw NYISO archives remain outside Git under the source's legal-use
  boundary; the repository commits URLs, code and aggregate inventories only.
- Bus identifiers are anonymized in outputs. No complete sensitive cascade
  sequence is published.

See `G2_DATA_PREFLIGHT.md` for exact source patterns, coverage and the corrected
64-character inventory SHA-256.

## Installation and verification

```powershell
pip install -c constraints-g2.txt ..\PRAMA-Protokol\PRAMA-Protokol-py
pip install -c constraints-g2.txt -e .
pip install -c constraints-g2.txt pytest
$env:PYTHONPATH='src;..\PRAMA-Protokol\PRAMA-Protokol-py\src'
pytest -q
```

The pins in `constraints-g2.txt` reproduce the final documented H4 runtime
(Python 3.11, NumPy 2.4.6, Pandas 3.0.3 and `prama-protokol==0.2.1`). CI runs
the same constraints on Python 3.11 and 3.13. Tests that need licensed local
outage data skip explicitly when those files are absent; raw licensed data are
never fetched or committed by CI.

The committed H4 result is final. Do not rerun it merely to seek a different
classification. Re-execution is permitted only for a demonstrated
implementation error registered append-only under the H3 rules.

Legacy G1 reproduction remains available for audit and is not a G2
confirmatory command:

```powershell
python scripts/reproduce_bpa.py data/dobson_bpa/outagesBPA.csv --domain BPA `
  --calibration-id bpa_calib_1999_2003_v1 `
  --induction-epoch bpa_induction_v1 `
  --calibration-end 2004-01-01T00:00:00Z `
  --output-prefix results/reproduction_bpa
```

## Foundations

The kernel implements the aptadynamic formalism of structural viability with a
causal memory accumulator and history-dependent threshold. Mathematical theory
and empirical performance are separate claims: the confirmatory negative result
reported here constrains the hypothesis of incremental empirical value in this
NYISO confrontation; it is neither erased by the formalism nor converted into
a successful validation of it.

The mathematical corpus is available on Zenodo:
https://doi.org/10.5281/zenodo.21270506.

## Citation and acknowledgments

See [`CITATION.cff`](CITATION.cff).

The BPA and outage-record work builds on the cascading-failure research of Ian
Dobson and collaborators. NYISO G2 additionally relies on official NYISO load
and real-time LBMP archives. Data providers do not endorse this analysis or its
conclusions.

## Disclaimer

The analysis and conclusions are strictly those of the authors and not of
Bonneville Power Administration, NYISO, Iowa State University or any data
provider.
