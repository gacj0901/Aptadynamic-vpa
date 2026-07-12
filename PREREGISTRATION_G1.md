# PREREGISTRATION G1 — Causal grid evaluation

**Status:** confirmatory specification, frozen before the G1 BPA/NYISO rerun.
**Kernel:** `prama-protokol==0.2.0`, with causal `G[0]=0` and
`G[t]=smooth_M[t]-smooth_M[t-1]`.

## Fixed design

The event filter retains automatic/forced outages when an outage-type field is
available; otherwise it retains all canonical events. Cascades are formed from
all outage starts, including their first hour, and split only when the gap is
strictly greater than 3600 seconds. Severity is cascade outage count.

The universal kernel is not tuned by domain or outcome:
`tau_memory=336`, `lambda_eq=1`, `lambda_recovery=0.005`,
`lambda_min=0.1`, `theta_scale=2`, `g_smooth=24`, `kappa=0.05`.
Expectation is the strictly causal mean of intensity by UTC month × hour, with
`min_context_count=10` and `min_hist=720`.

## Frozen temporal partitions

Calibration and evaluation are disjoint. PRAMA warm-up is consumed only inside
calibration. Thresholds are fitted once and never updated during evaluation.

| Domain | Calibration ID | Calibration end, exclusive | Evaluation |
|---|---|---|---|
| BPA | `bpa_calib_1999_2003_v1` | `2004-01-01T00:00:00Z` | boundary onward |
| NYISO | `nyiso_calib_2008_2010_v1` | `2011-01-01T00:00:00Z` | boundary onward |

Each calibration partition must contain at least two annual cycles, the full
720-hour warm-up, and at least 10 observations in every month-hour cell. A
violation invalidates the confirmatory run.

## Frozen outcomes and alert budget

The severity rule is declared before evaluation: compute P95 of cascade sizes
using only cascades completely contained in calibration, with NumPy's linear
quantile, then freeze `ceil(P95)` as the integer threshold. Historical values
4 (BPA) and 3 (NYISO) are expectations only; the calibration-derived integers
govern regardless of whether they differ.

The baseline uses causal 12-hour trailing intensity. Its alert count is matched
to PRAMA's calibration occupancy only. A fixed order-statistic threshold is
fitted once. If the threshold has mass, seeded random ranking of time indices
selects exactly the required number of calibration ties; the resulting hash
cutoff is frozen for evaluation. Tie seed: `20260711`.

## Primary claim, tests and multiplicity

The primary observation-operator mode is `activity`
(`sigma_op = intensity > 0`). `always_valid` is a prespecified sensitivity and
does not carry the confirmatory claim. There is one primary test per domain;
the two sensitivity analyses do not expand the primary family.

All cascades are evaluated at `evaluation_idx = start_idx - 1`, only after the
calibration boundary and only where the kernel is valid. PRAMA and baseline are
compared on identical cascades with a paired cascade bootstrap
(`n=10,000`, seed `20260712`). The statistic is
`risk_difference(PRAMA) - risk_difference(baseline)`. Confirmatory success
requires observed contrast > 0 and one-sided p < 0.01.

The primary claim is additionally gated on C3 passing independently in both
calibration and evaluation. The three exhaustive classifications are:

1. `confirmatory_success`: both C3 checks pass and the bootstrap criterion passes;
2. `confirmatory_criterion_not_met`: both C3 checks pass but the criterion fails;
3. `invalid_for_confirmatory_claim_C3_gate_failed`: either C3 check fails.

The circular-shift null remains a temporal-dependence test with 10,000 shifts,
seed `20260711`, and minimum shift 24 bins. Occurrence analyses at 6/12/24/48 h
and `always_valid` results are secondary and must be labeled as such. Negative
and invalid results are reported without changing this specification.
