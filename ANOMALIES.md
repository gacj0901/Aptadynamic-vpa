# Anomaly Register

## 2026-07-11 — G1 bin grid was not aligned to UTC hours

`omega_series` anchored bins at `min(t_out)` without rounding to an hourly
boundary, while `expected_profile` labeled each left edge by its UTC month and
hour. The implemented expectation was therefore E[omega | month, offset-hour],
not the declared E[omega | month, UTC-hour]. The estimator remained causal and
context-consistent, so G1 is closed and its run classifications do not change.
Correct UTC alignment recomputes every index, including the calibration cut,
and therefore opens induction epoch v2.

## 2026-07-11 — A non-causal driver was selectable

The `severity` column places voltage-weighted log duration in the outage START
bin even though duration becomes known only at restoration. G1 used
`driver="intensity"`, so no G1 evaluation used this future information. The v2
interface introduces a driver registry and blocks non-causal or conditionally
causal drivers from evaluation unless an explicitly labeled exploratory escape
hatch is used.

## 2026-07-11 — README memory-scale inconsistency

The README stated tau=720 h and attributed it to an outcome-exposed sweep from
the 0.1.0 era. The G1 preregistration and executable configuration freeze
tau=336 h, and no G1 run used 720 h. Documentation now treats the old sweep as
historical, non-revalidated provenance and reports 336 h as the operative
memory scale.

## 2026-07-11 — Historical sigma_op derogation

G1 used `sigma_op = intensity > 0`, which does not represent continuity of
operation under Deployment O_D v0.2 section 9.7. G1 is permanently labeled
with historical semantics `sigma_semantics_v1_activity`. This transitional
derogation does not alter G1 evidence and expires when induction epoch v2 is
opened. Epoch v2 must redesign `sigma_op` or record a new, explicitly justified
derogation; silence cannot renew it.

## 2026-07-12 — H4 gate record rejected a non-finite C3 diagnostic

The first H4 invocation aborted while serializing the gate-stage record,
before the outcome-access token was opened. Invalid interface rows had been
passed to `check_degeneration` as NaNs. Its canonical running-mean reference
uses a cumulative sum, so one invalid row propagated a non-finite
`r_degenerate`; the strict JSON writer correctly refused that record. No
cascade identifiers, severity threshold, outcome statistic, comparator or
classification were constructed. The correction filters C3 to the channel's
valid rows, which is the population on which its correlation is defined; C4
continues to retain invalid temporal bins as zero-Delta kernel steps. A
regression test with an explicit invalid-row gap now requires finite C3 output.
All frozen H3 thresholds, partitions, seeds and replicate counts are unchanged.

## 2026-07-12 — H4 rolling-AC1 buffer was read-only under Pandas 3

The second H4 invocation completed and serialized every observation gate;
CH-L passed both partitions and the outcome token opened. Cascade identifiers
and the calibration severity P95 were then constructed, so this incident is
explicitly post-exposure. Before comparator selection or any evaluation
statistic, `rolling_ac1` attempted to replace non-finite values in a NumPy
view returned read-only by Pandas 3 and raised `ValueError: assignment
destination is read-only`. No comparator, bootstrap, alignment null,
evaluation contrast or classification was computed or written. The gate-stage
record was valid and reported `outcomes_accessed: false` because it predates
the token; its SHA-256 was
`e28c2e337b3b054c214acdd85f05329c5fa1d749cd1f82e57caaf87644283e0c`.
The correction requests an explicit writable copy from `to_numpy`; a
regression assertion now requires that buffer to be writable. This is a
runtime-compatibility fix only. All H3 thresholds, algorithms, partitions,
seeds and replicate counts remain unchanged.
