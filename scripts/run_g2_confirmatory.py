#!/usr/bin/env python
"""Execute the frozen G2/H4 confirmatory path exactly once from clean trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import prama_protokol
from prama_protokol import KernelConfig
from prama_protokol.compliance import check_causality

from aptadynamic_eg import automatic_only, load_bpa
from aptadynamic_eg.evaluation import (
    apply_frozen_threshold,
    cascade_evaluation_rows,
    circular_shift_null,
    fit_frozen_budget_calibration,
    paired_cascade_bootstrap,
)
from aptadynamic_eg.g2 import (
    G2InterfaceConfig,
    build_hourly_domain,
    causal_trailing_conditional_mean,
    context_codes,
    normalize_and_project,
)
from aptadynamic_eg.h4 import (
    BASELINE_NAMES,
    baseline_signals,
    common_valid_mask,
    construct_cascade_outcomes,
    holm_adjust,
    partition_gates,
    unlock_outcomes,
)
from aptadynamic_eg.omega import expected_profile


H3_COMMIT = "6672bdacf2f873c8c72870ceb86b9fb2aa993ef8"
H3_FILE_SHA256 = "19edba6684f45bd746962ed11daf905d68cd209de44cf164f9c386fd9a63bf52"
CALIBRATION_ID = "nyiso_calib_G2_v1"
CALIBRATION_END = pd.Timestamp("2011-01-01T00:00:00Z")
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 20260714
TIE_SEED = 20260715
ALIGNMENT_N = 10_000
ALIGNMENT_SEED = 20260716
C4_N = 1_000
C4_SEED = 20260717
RHO_BANDS = {
    "CH-L": (0.10, 0.95),
    "CH-P": (0.10, 0.90),
    "CH-F": (0.10, 0.90),
}


def git_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def git_dirty(root: Path) -> bool:
    return bool(subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"], text=True
    ).strip())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def actual_causality_record(
    domain: pd.DataFrame,
    gamma: pd.DataFrame,
    channel: str,
    cfg: G2InterfaceConfig,
) -> dict:
    values = gamma["omega"].to_numpy(dtype=float)
    valid = gamma["sigma_valid"].to_numpy(dtype=bool)
    timestamps = domain.index
    day_type = channel != "CH-F"
    context = context_codes(timestamps, day_type=day_type)

    if channel in {"CH-L", "CH-P"}:
        def expectation_fn(prefix: np.ndarray) -> np.ndarray:
            n = len(prefix)
            return causal_trailing_conditional_mean(
                prefix, context[:n], timestamps[:n], valid[:n],
                min_context_count=cfg.min_context_count,
                min_hist=cfg.min_hist,
                trailing_days=cfg.trailing_days,
            )
    else:
        def expectation_fn(prefix: np.ndarray) -> np.ndarray:
            n = len(prefix)
            om = pd.DataFrame({
                "t": timestamps[:n].as_unit("s").asi8,
                "outage_intensity": prefix,
            })
            return expected_profile(
                om, driver="outage_intensity",
                min_context_count=cfg.min_context_count,
                min_hist=cfg.min_hist,
            )
    record = check_causality(expectation_fn, values, sample_points=8)
    expected = expectation_fn(values)
    record["matches_projected_expectation_exactly"] = bool(np.array_equal(
        expected, gamma["expected"].to_numpy(dtype=float), equal_nan=True
    ))
    record["passed"] = bool(
        record["passed"] and record["matches_projected_expectation_exactly"]
    )
    return record


def risk_enrichment(alert: np.ndarray, severe: np.ndarray) -> dict:
    alert = np.asarray(alert, dtype=bool)
    severe = np.asarray(severe, dtype=bool)
    p_in = float(severe[alert].mean()) if alert.any() else 0.0
    p_out = float(severe[~alert].mean()) if (~alert).any() else 0.0
    enrichment = p_in / p_out if p_out > 0 else None
    return {
        "n": int(len(severe)),
        "n_alert": int(alert.sum()),
        "p_severe_inside": p_in,
        "p_severe_outside": p_out,
        "enrichment": enrichment,
        "risk_difference": p_in - p_out,
    }


def rows_for_partition(
    projection: pd.DataFrame,
    events: pd.DataFrame,
    split_idx: int,
    evaluation: bool,
) -> pd.DataFrame:
    rows = cascade_evaluation_rows(projection, events)
    if evaluation:
        rows.loc[rows["evaluation_idx"] < split_idx, "in_range"] = False
    else:
        rows.loc[rows["evaluation_idx"] >= split_idx, "in_range"] = False
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outages", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    prama_root = root.parent / "PRAMA-Protokol"
    if prama_protokol.__version__ != "0.2.1":
        raise RuntimeError(f"H4 requires prama-protokol 0.2.1, found {prama_protokol.__version__}")
    if sha256(root / "PREREGISTRATION_G2.md") != H3_FILE_SHA256:
        raise RuntimeError("PREREGISTRATION_G2.md does not match frozen H3 hash")
    if not subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", H3_COMMIT, "HEAD"]
    ).returncode == 0:
        raise RuntimeError("frozen H3 commit is not an ancestor of the runner tree")
    start_dirty = {"grid": git_dirty(root), "prama": git_dirty(prama_root)}
    if any(start_dirty.values()):
        raise RuntimeError(f"H4 requires clean trees, got {start_dirty}")

    cfg = G2InterfaceConfig()
    kernel_cfg = KernelConfig()
    events_filtered = automatic_only(load_bpa(args.outages))
    # Observation construction uses timestamps/validity only. No cascade or
    # severity outcome exists before the gate token below is opened.
    domain = build_hourly_domain(args.cache, events_filtered)
    split_idx = int(domain.index.searchsorted(CALIBRATION_END, side="left"))
    if domain.index[split_idx] != CALIBRATION_END:
        raise RuntimeError("frozen calibration boundary is not on the G2 grid")

    projections: dict[str, pd.DataFrame] = {}
    metadata: dict[str, dict] = {}
    gates: dict[str, dict] = {}
    channel_records: dict[str, dict] = {}
    for channel in ("CH-L", "CH-P", "CH-F"):
        gamma, meta = normalize_and_project(domain, channel, CALIBRATION_END, cfg)
        projections[channel] = gamma
        metadata[channel] = meta
        context = np.asarray(meta["context"])
        c2 = actual_causality_record(domain, gamma, channel, cfg)
        calibration_gates = partition_gates(
            gamma, context, 0, split_idx, RHO_BANDS[channel],
            n_null=C4_N, null_seed=C4_SEED, kernel_cfg=kernel_cfg,
        )
        evaluation_gates = partition_gates(
            gamma, context, split_idx, len(gamma), RHO_BANDS[channel],
            n_null=C4_N, null_seed=C4_SEED, kernel_cfg=kernel_cfg,
        )
        n1 = {
            "check": "N1 scale invariance",
            "passed": True if channel in {"CH-L", "CH-P"} else None,
            "detail": (
                "physical-channel rescaling verified at atol=1e-9 by test_g2_h2.py"
                if channel in {"CH-L", "CH-P"}
                else "N/A: outage count is dimensionless with canonical scale"
            ),
            "test_commit": "9a6abe7169338105362686f557d1fb8a7483a8a3",
        }
        sigma_record = {
            "check": "sigma_op conformance",
            "passed": bool(np.all(
                gamma["sigma_op"].to_numpy(dtype=bool)
                <= gamma["sigma_valid"].to_numpy(dtype=bool)
            )),
            "detail": "sigma_op implies channel validity and uses frozen CH-L q_floor",
        }
        gates[channel] = {
            "C2": c2,
            "calibration": calibration_gates,
            "evaluation": evaluation_gates,
            "N1": n1,
            "sigma_op": sigma_record,
        }
        gates[channel]["all_passed"] = bool(
            c2["passed"]
            and calibration_gates["all_passed"]
            and evaluation_gates["all_passed"]
            and (n1["passed"] is True or channel == "CH-F")
            and sigma_record["passed"]
        )
        channel_records[channel] = {
            "schema_version": 2,
            "kernel_config": asdict(kernel_cfg),
            "interface_config": {
                "driver": meta["driver"],
                "normalization": meta["normalization"],
                "reference": format(meta["reference"], ".17g"),
                "q_floor": format(meta["q_floor"], ".17g"),
                "min_context_count": cfg.min_context_count,
                "min_hist": cfg.min_hist,
                "align_utc": True,
                "sigma_op_semantics": "valid_CH-L_and_load_above_calibration_q_floor",
                "trailing_days": cfg.trailing_days if channel != "CH-F" else None,
                "trailing_volatility_window": 1 if channel == "CH-P" else None,
            },
            "induction": {
                "epoch_id": meta["epoch_id"],
                "estimator": meta["estimator"],
                "regime": meta["regime"],
                "estimator_hash": meta["estimator_hash"],
            },
        }

    gate_payload = {
        "schema_version": 2,
        "run_mode": "confirmatory_H4_gate_stage",
        "outcomes_accessed": False,
        "outcome_columns_constructed": [],
        "order_rule": "evaluation gates completed before outcome-dependent statistics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "commits": {"grid": git_sha(root), "prama": git_sha(prama_root)},
        "h3": {"commit": H3_COMMIT, "file_sha256": H3_FILE_SHA256},
        "kernel_config": asdict(kernel_cfg),
        "seeds": {
            "bootstrap": BOOTSTRAP_SEED, "tie": TIE_SEED,
            "alignment": ALIGNMENT_SEED, "C4": C4_SEED,
        },
        "replicates": {
            "bootstrap": BOOTSTRAP_N, "alignment": ALIGNMENT_N, "C4": C4_N,
        },
        "channels": channel_records,
        "gates": gates,
    }
    gate_path = args.output_prefix.with_name(args.output_prefix.name + "_gates").with_suffix(".json")
    json_write(gate_path, gate_payload)

    decision = unlock_outcomes("CH-L", gates["CH-L"])
    if not decision.all_primary_gates_passed:
        failed = []
        for partition in ("calibration", "evaluation"):
            for name, record in gates["CH-L"][partition].items():
                if isinstance(record, dict) and record.get("passed") is False:
                    failed.append(f"{partition}:{name}")
        if gates["CH-L"]["C2"]["passed"] is False:
            failed.append("C2")
        if gates["CH-L"]["N1"]["passed"] is False:
            failed.append("N1")
        if gates["CH-L"]["sigma_op"]["passed"] is False:
            failed.append("sigma_op")
        result = {
            **gate_payload,
            "run_mode": "confirmatory_H4",
            "confirmatory_eligible": False,
            "outcomes_accessed": False,
            "classification": "invalid_for_confirmatory_claim_" + "_and_".join(failed) + "_failed",
            "stopped_before_outcomes": True,
        }
        json_write(args.output_prefix.with_suffix(".json"), result)
        print(json.dumps({"classification": result["classification"], "outcomes_accessed": False}, indent=2))
        return 2

    # The gate token is the only path into cascade/severity construction.
    events = construct_cascade_outcomes(events_filtered, decision)
    cut_epoch = int(CALIBRATION_END.timestamp())
    grouped = events.groupby("cascade_id")
    calibration_cascades = pd.DataFrame({
        "size": grouped.size(), "last_t_out": grouped["t_out"].max(),
    })
    calibration_cascades = calibration_cascades[
        calibration_cascades["last_t_out"] < cut_epoch
    ]
    p95 = float(np.quantile(
        calibration_cascades["size"].to_numpy(dtype=float), 0.95, method="linear"
    ))
    severity_threshold = int(np.ceil(p95))

    primary = projections["CH-L"].copy()
    signals = baseline_signals(
        domain["outage_intensity"].to_numpy(dtype=float),
        primary["omega"].to_numpy(dtype=float),
        primary["expected"].to_numpy(dtype=float),
        split_idx,
    )
    common_valid = common_valid_mask(
        primary["valid"].to_numpy(dtype=bool), signals
    )
    primary["valid"] = common_valid
    primary["t"] = domain.index.as_unit("s").asi8

    calibrations = {
        name: fit_frozen_budget_calibration(
            signal, primary["latent_collapse"].to_numpy(dtype=bool),
            common_valid, split_idx, CALIBRATION_ID, TIE_SEED,
        )
        for name, signal in signals.items()
    }
    calibration_rows = rows_for_partition(primary, events, split_idx, evaluation=False)
    eligible_cal = calibration_rows[
        calibration_rows["in_range"] & calibration_rows["valid"]
    ]
    cal_idx = eligible_cal["evaluation_idx"].to_numpy(dtype=int)
    cal_severe = eligible_cal["size"].to_numpy(dtype=int) >= severity_threshold
    calibration_metrics = {}
    for name in BASELINE_NAMES:
        alert = apply_frozen_threshold(signals[name], cal_idx, calibrations[name])
        calibration_metrics[name] = risk_enrichment(alert, cal_severe)
    comparator = max(
        BASELINE_NAMES,
        key=lambda name: (
            calibration_metrics[name]["enrichment"]
            if calibration_metrics[name]["enrichment"] is not None else -np.inf,
            -BASELINE_NAMES.index(name),
        ),
    )

    evaluation_rows = rows_for_partition(primary, events, split_idx, evaluation=True)
    eligible_eval = evaluation_rows[
        evaluation_rows["in_range"] & evaluation_rows["valid"]
    ]
    eval_idx = eligible_eval["evaluation_idx"].to_numpy(dtype=int)
    eval_severe = eligible_eval["size"].to_numpy(dtype=int) >= severity_threshold
    contrasts = {}
    for name in BASELINE_NAMES:
        alerts = apply_frozen_threshold(signals[name], eval_idx, calibrations[name])
        contrasts[name] = paired_cascade_bootstrap(
            evaluation_rows, alerts, severity_threshold,
            n_bootstrap=BOOTSTRAP_N, seed=BOOTSTRAP_SEED,
        )
    secondary_names = [name for name in BASELINE_NAMES if name != comparator]
    adjusted = holm_adjust({
        name: contrasts[name]["p_one_sided_prama_superior"]
        for name in secondary_names
    })
    for name in secondary_names:
        contrasts[name]["holm_adjusted_p"] = adjusted[name]
    contrasts[comparator]["holm_adjusted_p"] = None
    contrasts[comparator]["role"] = "primary_comparator"

    alignment_null = circular_shift_null(
        primary["latent_collapse"].to_numpy(dtype=bool),
        eval_idx, eval_severe, n_permutations=ALIGNMENT_N,
        seed=ALIGNMENT_SEED, min_shift=24,
    )
    selected = contrasts[comparator]
    primary_success = bool(
        selected["observed_contrast"] > 0
        and selected["p_one_sided_prama_superior"] < 0.01
    )
    btriv = contrasts["B-TRIV"]
    btriv_success = bool(
        btriv["observed_contrast"] > 0
        and btriv["p_one_sided_prama_superior"] < 0.01
    )
    classification = (
        "confirmatory_success" if primary_success
        else "confirmatory_criterion_not_met"
    )
    falsification = bool(not primary_success and not btriv_success)

    report = {
        **gate_payload,
        "run_mode": "confirmatory_H4",
        "confirmatory_eligible": True,
        "outcomes_accessed": True,
        "outcome_access_started_after_gate_stage_file": str(gate_path),
        "working_tree_dirty_at_start": start_dirty,
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "prama_protokol": prama_protokol.__version__,
        },
        "calibration": {
            "id": CALIBRATION_ID,
            "end_exclusive_utc": CALIBRATION_END.isoformat(),
            "n_bins": split_idx,
            "n_complete_cascades": int(len(calibration_cascades)),
            "severity_p95": p95,
            "severity_threshold_ceil": severity_threshold,
        },
        "baseline_budget_calibrations": calibrations,
        "comparator_selection": {
            "rule": "maximum calibration severity enrichment; fixed name order breaks exact ties",
            "calibration_metrics": calibration_metrics,
            "selected": comparator,
        },
        "evaluation": {
            "n_common_valid_cascades": int(len(eligible_eval)),
            "contrasts": contrasts,
            "alignment_null": alignment_null,
        },
        "classification": classification,
        "program_falsification_activated": falsification,
        "classification_rule": (
            "success iff selected contrast > 0 and p_one_sided < 0.01; "
            "falsification iff criterion also fails against B-TRIV"
        ),
    }
    json_write(args.output_prefix.with_suffix(".json"), report)
    pd.DataFrame([
        {
            "baseline": name,
            "role": "primary" if name == comparator else "secondary",
            "calibration_enrichment": calibration_metrics[name]["enrichment"],
            "observed_contrast": contrasts[name]["observed_contrast"],
            "p_one_sided": contrasts[name]["p_one_sided_prama_superior"],
            "holm_adjusted_p": contrasts[name]["holm_adjusted_p"],
        }
        for name in BASELINE_NAMES
    ]).to_csv(args.output_prefix.with_suffix(".csv"), index=False)
    print(json.dumps({
        "classification": classification,
        "program_falsification_activated": falsification,
        "selected_comparator": comparator,
        "observed_contrast": selected["observed_contrast"],
        "p_one_sided": selected["p_one_sided_prama_superior"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
