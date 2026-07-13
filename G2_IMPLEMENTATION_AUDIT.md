# G2 post-H5 implementation and reproducibility audit

**Scope:** objective implementation/runtime corrections only. This audit does
not amend H3, rerun H4, overwrite H4/H5 artifacts, or alter the PRAMA kernel,
parameters, thresholds, seeds, replicate counts, partitions, comparator family
or confirmatory decision rules.

**Checkpoint reviewed:**
`48a6c1d444f0192f8d50807ed9cc6e334c905f2b`.

## Runtime corrections

- The confirmatory runner now requires `outage_type` and fails closed when the
  column is absent. The general exploratory helper retains its historical
  permissive behavior unless `require_column=True` is requested.
- Automatic/forced filtering serializes counts before and after filtering and
  counts unrecognized normalized values.
- G2 NumPy buffers that may be combined, indexed or passed across Pandas/NumPy
  boundaries are explicit copies where mutability matters. Read-only-array
  regression tests cover the previously vulnerable paths.
- `constraints-g2.txt` pins the documented H4 environment and GitHub Actions
  runs `pytest -q` on Python 3.11 and 3.13. Licensed local data are not fetched;
  the corresponding reproduction test skips with an explicit reason.

## Objective analytical corrections

- Calibration comparator selection now admits only complete cascades with
  `last_t_out < 2011-01-01T00:00:00Z`. A cascade beginning before and ending at
  or after the cut belongs to neither calibration nor confirmatory evaluation.
- Hourly physical channels now require exactly timestamps `:00, :05, ..., :55`
  with zero seconds and microseconds. Twelve irregular timestamps are not a
  valid hour.
- Future final reports enumerate the outcomes actually constructed while the
  separately written gate record continues to state `outcomes_accessed=false`
  and an empty list. Historical H4/H5 artifacts and their hashes are unchanged.

## Real-data boundary audit

Command (audit only; no H4 execution):

```powershell
python scripts/audit_g2_boundary.py `
  data/dobson_nyiso/outagesNYISO.csv `
  --output results/g2_boundary_audit_post_h5.json
```

The safe aggregate JSON reports:

| Quantity | Count |
|---|---:|
| Total cascades | 6,152 |
| Complete calibration cascades | 1,153 |
| Evaluation cascades | 4,999 |
| Cross-boundary cascades | **0** |
| Outage rows before automatic/forced filter | 45,178 |
| Outage rows after filter | 9,600 |

No real cascade crossed the frozen cut and none entered the legacy
`calibration_rows`. Therefore the boundary correction has **no numerical
effect on historical G2 and does not require reconsideration of its
classification**. Because no cascade influenced H4, no influence incident is
appended to `ANOMALIES.md`.

## Statistical and claim-language clarification

The historical schema key `p_one_sided_prama_superior` is preserved. Its value
is the plus-one-corrected proportion of paired ordinary-bootstrap contrasts at
or below zero: a percentile-bootstrap tail proportion, not a test against a
bootstrap null distribution centered at zero. This clarification does not
recompute or reclassify G2.

`program_falsification_activated` records activation of the concrete rule
preregistered in H3 section 0 for the G2 incremental-value hypothesis. It is
not a claim of universal falsification of the aptadynamic formalism.

## Methodological changes explicitly not applied retroactively

No alternative bootstrap null, comparator selection rule, slot interpolation,
boundary reassignment, parameter change or relabeling of historical result
fields was introduced. Any such change would require a new prospective epoch,
not a repair of G2.
