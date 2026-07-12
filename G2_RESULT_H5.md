# G2 H4/H5 — Confirmatory result register

**Status:** final confirmatory result under frozen H3. No further run is
authorized absent an append-only amendment for a demonstrated implementation
error. The successful execution used grid commit
`fdd4ce4e15cbf390db71afb9322d7dd3b77cf10e`, PRAMA commit
`717fce4ce1592f9fa15636d43fa047d7fdda9004`, and clean working trees.

## Frozen anchors and execution order

- H3 commit: `6672bdacf2f873c8c72870ceb86b9fb2aa993ef8`.
- H3 file SHA-256:
  `19edba6684f45bd746962ed11daf905d68cd209de44cf164f9c386fd9a63bf52`.
- Calibration: `nyiso_calib_G2_v1`, exclusive cut
  `2011-01-01T00:00:00Z`.
- Every evaluation-partition observation gate was computed and serialized
  before the outcome token opened. Cascade identifiers, severity and all
  contrasts were constructed only after CH-L passed both partitions.
- Frozen seeds and replicate counts were used: bootstrap 10,000 / 20260714;
  tie 20260715; alignment null 10,000 / 20260716; C4 1,000 / 20260717.

## Gate record

| Channel | Calibration | Evaluation | Confirmatory role |
|---|---|---|---|
| CH-L | PASS: C3 absolute; rho_I 0.786794; C4_D 2.850953; MEM 56.39 | PASS: C3 absolute; rho_I 0.780029; C4_D 1.602696; MEM 258.73 | Primary, admissible |
| CH-P | FAIL: C3 branch none; rho_I 0.174596; C4_D 14.322853 | FAIL: C3 relative passes, rho_I 0.078532 fails; C4_D 2.667890 | Secondary invalid |
| CH-F | FAIL: rho_I 0.010084 and C4_D 1.356986 | FAIL: rho_I 0.016608; C3 relative and C4_D 6.492938 pass | Continuity channel invalid |

CH-L therefore authorized outcome access. The frozen severe-cascade threshold
was 3 outages (`ceil(P95)` from complete calibration cascades). The common
evaluation cohort contained 4,590 cascades.

## Comparator selection and primary result

The comparator was selected only from calibration enrichment:

| Baseline | Calibration enrichment |
|---|---:|
| B-TRIV | 0.805141 |
| B-COMP | 0.725212 |
| B-VAR | 0.696400 |
| B-AC1 | 0.611898 |

The frozen rule selected **B-TRIV**. In evaluation:

- PRAMA risk difference: `0.0101253`;
- B-TRIV risk difference: `0.0597483`;
- primary contrast PRAMA minus B-TRIV: **`-0.0496230`**;
- one-sided bootstrap p: **`1.0`**.

The primary success criterion (`contrast > 0` and `p < 0.01`) was not met.
Classification: **`confirmatory_criterion_not_met`**.

Under the rule frozen in H3 section 7, failure of the primary criterion and
failure against B-TRIV activate the section 0 clause. The report therefore
records **`program_falsification_activated: true`**. This is not reclassified
as a local dataset or interface failure because the primary channel passed
every declared gate in both partitions.

## Secondary contrasts

| Comparator | Contrast | Raw one-sided p | Holm p |
|---|---:|---:|---:|
| B-VAR | +0.001321 | 0.459054 | 0.459054 |
| B-AC1 | +0.037987 | 0.002500 | 0.007499 |
| B-COMP | +0.017790 | 0.082192 | 0.164384 |

The positive B-AC1 secondary contrast is published explicitly. It does not
replace the single primary comparator selected by the calibration-only rule
and does not alter the exhaustive H3 classification. The circular alignment
null returned p = 0.179882.

## Registered implementation incidents

Four aborted invocations preceded the final execution and are append-only in
`ANOMALIES.md`:

1. non-finite C3 diagnostic, stopped before outcomes; fixed in `527f4c6`;
2. read-only Pandas 3 AC1 buffer, post-exposure but before comparator
   selection/statistics; fixed in `9ccfaa8`;
3. complete-case CSD windows had no support, post-exposure but before
   comparator selection/statistics; fixed in `30daef3`;
4. read-only common-valid mask, post-exposure but before comparator
   selection/statistics; fixed in `fdd4ce4`.

None changed an H3 threshold, partition, seed, replicate count, comparator
family, success rule or classification rule.

## Artifact hashes

- `results/g2_confirmatory_H4.json`:
  `79f37a277b15e3abd9ecd9efd031a5d7ac8f405df9419b66a6e27fb0641edb8f`;
- `results/g2_confirmatory_H4_gates.json`:
  `c9fe2ef863466aac3ab3481dc0be70c89ff846ea516f33c38ff5f3e1597c3cad`;
- `results/g2_confirmatory_H4.csv`:
  `7d1d31456de909794f2d8220e53483356a0d44e2a5f8bc94b3e03c138ae0cd53`.
