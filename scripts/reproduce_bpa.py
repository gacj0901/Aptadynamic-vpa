"""Single reproducible BPA/NYISO causal evaluation path."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import prama_protokol
from prama_protokol.compliance import (
    check_degeneration,
    check_density,
    check_inductive_ratio,
    check_memory_ratio,
)

from aptadynamic_eg import automatic_only, cascades, load_bpa, omega_series
from aptadynamic_eg.evaluation import (
    apply_frozen_threshold, cascade_evaluation_rows, circular_shift_null,
    fit_frozen_budget_calibration, occurrence_labels, paired_cascade_bootstrap,
    severity_statistics,
)
from aptadynamic_eg.projection import ProjectionConfig, project
from aptadynamic_eg.omega import expected_profile


def git_sha(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_dirty(path: Path) -> bool | None:
    try:
        return bool(
            subprocess.check_output(
                ["git", "-C", str(path), "status", "--porcelain"], text=True
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def estimator_source_hash() -> str:
    """Hash only estimator source; estimator parameters live in interface_config."""

    return hashlib.sha256(
        inspect.getsource(expected_profile).encode("utf-8")
    ).hexdigest()


def evaluate_mode(
    om, events, cfg, mode, n_permutations, seed, calibration_end_idx,
    calibration_id, severe_size_threshold, tie_seed, n_bootstrap, bootstrap_seed,
):
    projection = project(om, cfg, sigma_op_mode=mode)
    rows = cascade_evaluation_rows(projection, events)
    rows.loc[rows["evaluation_idx"] < calibration_end_idx, "in_range"] = False
    eligible = rows[rows["in_range"] & rows["valid"]].copy()
    stats = severity_statistics(rows, size_threshold=severe_size_threshold)
    occurrence = occurrence_labels(events, projection)
    occ = occurrence[occurrence["valid"] & (occurrence["idx"] >= calibration_end_idx)]
    occ_idx = occ["idx"].to_numpy(dtype=int)
    occ_alert = projection["latent_collapse"].to_numpy(dtype=bool)[occ_idx]
    recent_all = om["intensity"].rolling(12, min_periods=1).mean().shift(1).to_numpy()
    calibration = fit_frozen_budget_calibration(
        recent_all,
        projection["latent_collapse"].to_numpy(dtype=bool),
        projection["valid"].to_numpy(dtype=bool),
        calibration_end_idx,
        calibration_id,
        tie_seed,
    )
    occ_baseline = apply_frozen_threshold(recent_all, occ_idx, calibration)
    occurrence_metrics = {}
    for horizon in (6, 12, 24, 48):
        y = occ[f"event_within_{horizon}h"].to_numpy(dtype=bool)
        def rates(alert):
            return {
                "tpr": float(alert[y].mean()) if y.any() else None,
                "fpr": float(alert[~y].mean()) if (~y).any() else None,
            }
        occurrence_metrics[f"{horizon}h"] = {
            "event_rate": float(y.mean()), "prama": rates(occ_alert),
            "causal_baseline": rates(occ_baseline),
        }

    if eligible.empty:
        baseline = {"method": "frozen calibration cohort", "calibration": calibration,
                    "metrics": None}
        null = None
    else:
        idx = eligible["evaluation_idx"].to_numpy(dtype=int)
        b_alert = apply_frozen_threshold(recent_all, idx, calibration)
        b_rows = eligible.copy(); b_rows["prama_alert"] = b_alert
        baseline = {
            "method": "causal 12-bin trailing intensity; immutable threshold from frozen cohort",
            "calibration": calibration,
            "metrics": severity_statistics(b_rows, size_threshold=severe_size_threshold),
        }
        severe = eligible["size"].to_numpy() >= severe_size_threshold
        null = circular_shift_null(
            projection["latent_collapse"].to_numpy(), idx, severe,
            n_permutations=n_permutations, seed=seed, min_shift=max(24, cfg.g_smooth),
        )
        paired = paired_cascade_bootstrap(
            rows, b_alert, severe_size_threshold,
            n_bootstrap=n_bootstrap, seed=bootstrap_seed,
        )

    if eligible.empty:
        paired = None

    return projection, rows, {
        "mode": mode, "observation_operator": {
            "activity": "sigma_op = intensity > 0",
            "always_valid": "sigma_op = causal expectation is valid",
        }[mode],
        "severity": stats, "baseline": baseline, "null": null,
        "paired_cascade_bootstrap": paired,
        "occurrence_all_eligible_bins": occurrence_metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--domain", choices=("BPA", "NYISO"), default="BPA")
    parser.add_argument("--output-prefix", type=Path, default=Path("results/reproduction_bpa"))
    parser.add_argument("--n-permutations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260711)
    parser.add_argument("--n-bootstrap", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260712)
    parser.add_argument("--tie-seed", type=int, default=20260711)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "allow a non-frozen kernel version for a non-confirmatory operational check"
        ),
    )
    parser.add_argument("--induction-epoch",
                        help="C7 identifier; defaults to the domain's frozen G1 epoch")
    parser.add_argument("--diagnostic-n-null", type=int, default=200,
                        help="permutations for informational C4 density")
    parser.add_argument("--calibration-end", required=True,
                        help="Frozen calendar-year UTC boundary (exclusive)")
    parser.add_argument("--calibration-id", required=True,
                        help="Immutable/versioned cohort identifier, e.g. bpa_calib_v1")
    args = parser.parse_args()
    if args.n_permutations < 1:
        parser.error("--n-permutations must be positive (10,000 minimum for final results)")
    if args.n_bootstrap < 1:
        parser.error("--n-bootstrap must be positive (10,000 default)")
    if min(args.seed, args.bootstrap_seed, args.tie_seed) < 0:
        parser.error("all seeds must be non-negative integers")
    if args.diagnostic_n_null < 1:
        parser.error("--diagnostic-n-null must be positive")
    frozen_kernel = "0.2.1"
    # Per amendment G1-A1. Smoke mode remains explicitly non-confirmatory.
    version_allowed = prama_protokol.__version__ == frozen_kernel or args.smoke_test
    if not version_allowed:
        raise RuntimeError(
            f"requires prama-protokol {frozen_kernel}; --smoke-test permits a "
            f"non-frozen version, found {prama_protokol.__version__}"
        )

    events_raw = load_bpa(args.dataset)
    events_filtered = automatic_only(events_raw)
    events = cascades(events_filtered)
    # G1 frozen semantics — see ANOMALIES.md (a).
    om = omega_series(events_filtered, align_utc=False)
    cfg = ProjectionConfig()  # fixed universal defaults; never outcome-tuned here
    calibration_end = pd.Timestamp(args.calibration_end)
    if calibration_end.tzinfo is None:
        calibration_end = calibration_end.tz_localize("UTC")
    else:
        calibration_end = calibration_end.tz_convert("UTC")
    if not (calibration_end.month == 1 and calibration_end.day == 1
            and calibration_end.hour == 0 and calibration_end.minute == 0
            and calibration_end.second == 0):
        parser.error("--calibration-end must be a January 1 00:00:00 UTC calendar boundary")
    calibration_end_epoch = int(
        (calibration_end - pd.Timestamp(0, tz="UTC")) // pd.Timedelta("1s")
    )
    calibration_end_idx = int(np.searchsorted(
        om["t"].to_numpy(dtype=np.int64), calibration_end_epoch, side="left"
    ))
    split_rule = f"complete period strictly before {calibration_end.isoformat()}"
    if not 24 <= calibration_end_idx < len(om):
        parser.error("--calibration-end must leave at least 24 calibration bins and a non-empty evaluation period")
    calibration_start = pd.to_datetime(om["t"].iloc[0], unit="s", utc=True)
    if calibration_end - calibration_start < pd.Timedelta(days=365 * 2):
        parser.error("calibration must contain at least two complete annual cycles")
    calibration_context = pd.to_datetime(
        om["t"].iloc[:calibration_end_idx], unit="s", utc=True
    ).to_frame(name="timestamp")
    calibration_context["month"] = calibration_context["timestamp"].dt.month
    calibration_context["hour"] = calibration_context["timestamp"].dt.hour
    min_context_observations = int(
        calibration_context.groupby(["month", "hour"]).size().min()
    )
    if min_context_observations < cfg.min_context_count:
        parser.error("calibration does not populate every month-hour context sufficiently")

    cascade_groups = events.groupby("cascade_id")
    calibration_cascades = pd.DataFrame({
        "size": cascade_groups.size(),
        "last_t_out": cascade_groups["t_out"].max(),
    })
    calibration_cascades = calibration_cascades[
        calibration_cascades["last_t_out"] < calibration_end_epoch
    ]
    if len(calibration_cascades) < 20:
        parser.error("calibration partition has too few complete cascades for P95 severity")
    calibration_p95 = float(np.quantile(
        calibration_cascades["size"].to_numpy(dtype=float), 0.95, method="linear"
    ))
    severe_size_threshold = int(np.ceil(calibration_p95))

    analyses, csv_rows = {}, []
    last_projection = None
    for mode in ("activity", "always_valid"):
        last_projection, rows, result = evaluate_mode(
            om, events, cfg, mode, args.n_permutations, args.seed,
            calibration_end_idx, args.calibration_id, severe_size_threshold,
            args.tie_seed, args.n_bootstrap, args.bootstrap_seed,
        )
        analyses[mode] = result
        flat = {"domain": args.domain, "sigma_op_mode": mode, **result["severity"]}
        flat["baseline_enrichment"] = (
            result["baseline"]["metrics"] or {}
        ).get("enrichment")
        flat["null_p_corrected"] = (result["null"] or {}).get("p_corrected")
        csv_rows.append(flat)

    occurrence = occurrence_labels(events, last_projection)
    eligible_occurrence = occurrence[
        occurrence["valid"] & (occurrence["idx"] >= calibration_end_idx)
    ]
    occurrence_summary = {
        c: float(eligible_occurrence[c].mean())
        for c in eligible_occurrence if c.startswith("event_within_")
    }
    root = Path(__file__).resolve().parents[1]
    prama_root = root.parent / "PRAMA-Protokol"
    first_rows = cascade_evaluation_rows(last_projection, events)
    first_rows.loc[first_rows["evaluation_idx"] < calibration_end_idx, "in_range"] = False
    discarded = int((~(first_rows["in_range"] & first_rows["valid"])).sum())
    c3_calibration = check_degeneration(
        last_projection["delta"].to_numpy()[:calibration_end_idx],
        om[cfg.driver].to_numpy(dtype=float)[:calibration_end_idx],
    )
    c3_evaluation = check_degeneration(
        last_projection["delta"].to_numpy()[calibration_end_idx:],
        om[cfg.driver].to_numpy(dtype=float)[calibration_end_idx:],
    )
    observed = om[cfg.driver].to_numpy(dtype=float)
    expected = expected_profile(
        om,
        driver=cfg.driver,
        min_context_count=cfg.min_context_count,
        min_hist=cfg.min_hist,
    )
    timestamps = pd.to_datetime(om["t"], unit="s", utc=True)
    induction_context = (
        timestamps.dt.month.to_numpy(dtype=np.int16) * 100
        + timestamps.dt.hour.to_numpy(dtype=np.int16)
    )
    kernel_cfg = cfg.kernel_config()
    induction_epoch = args.induction_epoch or f"{args.domain.lower()}_induction_v1"
    informational_diagnostics = {
        "status": "informational_no_preregistered_thresholds",
        "induction_epoch": induction_epoch,
        "RHO_I": {
            "calibration": check_inductive_ratio(
                observed[:calibration_end_idx], expected[:calibration_end_idx]
            ),
            "evaluation": check_inductive_ratio(
                observed[calibration_end_idx:], expected[calibration_end_idx:]
            ),
        },
        "C4": check_density(
            last_projection.iloc[:calibration_end_idx],
            kernel_cfg,
            context=induction_context[:calibration_end_idx],
            n_null=args.diagnostic_n_null,
            seed=args.seed,
        ),
        "MEM": check_memory_ratio(kernel_cfg, calibration_end_idx),
    }
    primary_bootstrap = analyses["activity"]["paired_cascade_bootstrap"]
    c3_both_pass = bool(c3_calibration["passed"] and c3_evaluation["passed"])
    if args.smoke_test:
        claim_classification = "smoke_test_non_confirmatory"
    elif not c3_both_pass:
        claim_classification = "invalid_for_confirmatory_claim_C3_gate_failed"
    elif (primary_bootstrap["observed_contrast"] > 0.0
          and primary_bootstrap["p_one_sided_prama_superior"] < 0.01):
        claim_classification = "confirmatory_success"
    else:
        claim_classification = "confirmatory_criterion_not_met"
    report = {
        "schema_version": 2, "domain": args.domain,
        "run_mode": "smoke_test" if args.smoke_test else "confirmatory",
        "confirmatory_eligible": not args.smoke_test,
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "prama_protokol": prama_protokol.__version__},
        "commits": {"electrical_grid": git_sha(root), "prama_protokol": git_sha(prama_root)},
        "working_tree_dirty": {
            "electrical_grid": git_dirty(root),
            "prama_protokol": git_dirty(prama_root),
        },
        "kernel_config": asdict(kernel_cfg),
        "interface_config": {
            "driver": cfg.driver,
            "normalization": "identity on hourly outage intensity",
            "min_context_count": cfg.min_context_count,
            "min_hist": cfg.min_hist,
            "align_utc": False,
            "sigma_op_semantics": "sigma_semantics_v1_activity",
            "sensitivity_sigma_op_semantics": "always_valid",
            "noncausal_driver": bool(last_projection["noncausal_driver"].iloc[0]),
        },
        # Kernel API remains run_all(induction_epoch=...); only the report
        # mapping is named induction.epoch_id under schema v2.
        "induction": {
            "epoch_id": induction_epoch,
            "estimator": "causal_conditional_mean(month_utc x hour_utc)",
            "regime": "expanding",
            "estimator_hash": estimator_source_hash(),
        },
        "seed": args.seed,
        "n_permutations": args.n_permutations,
        "n_bootstrap": args.n_bootstrap,
        "bootstrap_seed": args.bootstrap_seed,
        "tie_seed": args.tie_seed,
        "calibration_split_definition": {
            "id": args.calibration_id, "rule": split_rule,
            "start_inclusive_utc": calibration_start.isoformat(),
            "end_exclusive_utc": calibration_end.isoformat(),
            "end_idx_exclusive": calibration_end_idx,
            "n_calibration_bins": calibration_end_idx,
            "n_evaluation_bins": len(om) - calibration_end_idx,
            "policy": "disjoint frozen calibration; no threshold refit during evaluation",
            "warmup_policy": "PRAMA warm-up is consumed inside calibration only",
            "minimum_complete_annual_cycles": 2,
            "minimum_month_hour_cell_count": min_context_observations,
        },
        "event_filter_definition": {
            "loader": "load_bpa canonical timestamp conversion",
            "filter": "automatic_only: keep outage_type in {auto, forced}; keep all if column absent",
            "cascade_input": "all filtered outage starts, including their first hour",
        },
        "severity_calibration": {
            "rule": "severe iff cascade size >= ceil(P95) of complete calibration cascades",
            "quantile_method": "numpy linear",
            "n_complete_calibration_cascades": int(len(calibration_cascades)),
            "calibration_p95_raw": calibration_p95,
            "frozen_integer_threshold": severe_size_threshold,
            "outcome_use": "evaluation outcomes never enter threshold estimation",
        },
        "counts": {"events_raw": len(events_raw), "events_filtered": len(events_filtered),
                   "cascades": int(events["cascade_id"].nunique()),
                   "cascades_eligible": int((first_rows["in_range"] & first_rows["valid"]).sum()),
                   "discarded_calibration_warmup_or_idx_minus_one": discarded},
        "cascade_definition": "new cascade iff gap between outage starts > 3600 seconds",
        "severity_definition": f"cascade outage count >= frozen calibration-derived threshold {severe_size_threshold}",
        "evaluation_definition": "strictly evaluation_idx = cascade_start_idx - 1; valid post-calibration rows only",
        "C3": {
            "confirmatory_gate": "must pass independently in calibration and evaluation",
            "calibration": c3_calibration,
            "evaluation": c3_evaluation,
            "both_pass": c3_both_pass,
        },
        "informational_diagnostics": informational_diagnostics,
        "primary_claim": {
            "mode": "activity",
            "sensitivity_mode": "always_valid",
            "statistic": "paired cascade bootstrap contrast in risk differences",
            "success_rule": "observed_contrast > 0 and one-sided p < 0.01, conditional on C3 passing in calibration and evaluation",
            "multiplicity": "one primary test per domain; always_valid is sensitivity only",
            "three_way_classification": claim_classification,
        },
        "sensitivity_analyses": analyses,
        "occurrence_experiment": {"population": "all causally eligible bins",
                                  "future_horizons_hours": [6, 12, 24, 48],
                                  "event_rates": occurrence_summary},
    }
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    pd.DataFrame(csv_rows).to_csv(args.output_prefix.with_suffix(".csv"), index=False)


if __name__ == "__main__":
    main()
