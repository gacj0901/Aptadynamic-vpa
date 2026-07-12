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
