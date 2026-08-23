#!/usr/bin/env python3
"""Recompute the quantitative claims exposed in the SGE reviewer artifact."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]


def read_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def read_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for index, _ in indexed[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_norm = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_norm = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Spearman correlation is undefined for a constant vector")
    return numerator / (left_norm * right_norm)


def spearman(left: list[float], right: list[float]) -> float:
    return pearson(average_ranks(left), average_ranks(right))


def mean_absolute_error(estimated: Iterable[float], observed: Iterable[float]) -> float:
    pairs = list(zip(estimated, observed))
    return statistics.fmean(abs(x - y) for x, y in pairs)


def mean_absolute_percentage_error(estimated: Iterable[float], observed: Iterable[float]) -> float:
    pairs = list(zip(estimated, observed))
    return statistics.fmean(abs(x - y) / abs(y) for x, y in pairs)


def select_k(rows: list[dict[str, str]], k: int) -> dict[str, str]:
    return next(row for row in rows if int(row["k"]) == k)


def close(actual: float, expected: float, tolerance: float = 1e-12) -> None:
    if not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f"recomputed value {actual!r} does not match sealed expectation {expected!r}")


def recompute() -> dict[str, Any]:
    historical_rows = read_csv("results/historical_same_trace_replay/summary.csv")
    historical_work = [float(row["serial_work_units"]) for row in historical_rows]
    historical_span = [float(row["critical_path_units"]) for row in historical_rows]
    historical_p2 = [float(row["workers_2_list_makespan_units"]) for row in historical_rows]
    historical_p4 = [float(row["workers_4_list_makespan_units"]) for row in historical_rows]
    historical_p8 = [float(row["workers_8_list_makespan_units"]) for row in historical_rows]
    historical = {
        "case_count": len(historical_rows),
        "aggregate_unbounded_speedup": sum(historical_work) / sum(historical_span),
        "aggregate_workers_2_list_speedup": sum(historical_work) / sum(historical_p2),
        "aggregate_workers_4_list_speedup": sum(historical_work) / sum(historical_p4),
        "aggregate_workers_8_list_speedup": sum(historical_work) / sum(historical_p8),
        "case_median_unbounded_speedup": statistics.median(
            work / span for work, span in zip(historical_work, historical_span)
        ),
        "case_max_unbounded_speedup": max(
            work / span for work, span in zip(historical_work, historical_span)
        ),
    }

    case_rows = read_json("results/sge_p30_ac_overlay_v2_20260728/case_rows.json")
    exact = [row for row in case_rows if row.get("observed_duration_join_eligible")]
    p4 = [float(row["observed_duration_metrics"]["finite_workers"]["P4"]["list_headroom"]) for row in exact]
    structural = {
        "exact_duration_action_dag_count": len(p4),
        "physical_repository_count": len({row["physical_repository"] for row in exact}),
        "p4_mean_ceiling": statistics.fmean(p4),
        "p4_median_ceiling": statistics.median(p4),
        "p4_max_ceiling": max(p4),
    }

    candidate_windows = read_json("results/sge_c1_structural_validation_20260729/window_rows.json")
    windows = [
        row
        for row in candidate_windows
        if row["worker_metrics"]["P4"]["observed_duration_reference_ceiling"] is not None
    ]
    estimated = [float(row["worker_metrics"]["P4"]["estimated_ceiling"]) for row in windows]
    observed = [float(row["worker_metrics"]["P4"]["observed_duration_reference_ceiling"]) for row in windows]
    threshold = 1.10
    predicted_high = [value >= threshold for value in estimated]
    observed_high = [value >= threshold for value in observed]
    joint_unit = [math.isclose(x, 1.0) and math.isclose(y, 1.0) for x, y in zip(estimated, observed)]
    nontrivial_estimated = [x for x, is_unit in zip(estimated, joint_unit) if not is_unit]
    nontrivial_observed = [y for y, is_unit in zip(observed, joint_unit) if not is_unit]
    admission = {
        "window_count": len(windows),
        "case_count": len({row["case_id"] for row in windows}),
        "held_out_repository_count": len({row["physical_repository"] for row in windows}),
        "spearman": spearman(estimated, observed),
        "mae": mean_absolute_error(estimated, observed),
        "mape": mean_absolute_percentage_error(estimated, observed),
        "threshold": threshold,
        "rejected_total": sum(not value for value in predicted_high),
        "admitted_total": sum(predicted_high),
        "observed_below_total": sum(not value for value in observed_high),
        "observed_at_or_above_total": sum(observed_high),
        "observed_below_rejected": sum((not p) and (not o) for p, o in zip(predicted_high, observed_high)),
        "observed_at_or_above_admitted": sum(p and o for p, o in zip(predicted_high, observed_high)),
        "joint_unit_count": sum(joint_unit),
        "nontrivial_window_count": len(nontrivial_estimated),
        "nontrivial_spearman": spearman(nontrivial_estimated, nontrivial_observed),
        "nontrivial_mae": mean_absolute_error(nontrivial_estimated, nontrivial_observed),
        "nontrivial_mape": mean_absolute_percentage_error(nontrivial_estimated, nontrivial_observed),
    }

    verified = read_csv("results/local_rolling_dag_ablation_swe_verified_local_10_20260707/aggregate_by_k.csv")
    swe_pro = read_csv("results/local_rolling_dag_ablation_swe_pro_campaign_clean_20260707/aggregate_by_k.csv")
    locality = {
        "swe_verified_case_count": int(select_k(verified, 2)["cases"]),
        "swe_verified_k2_retention": float(select_k(verified, 2)["local_retention_vs_global_mean"]),
        "swe_verified_k3_retention": float(select_k(verified, 3)["local_retention_vs_global_mean"]),
        "swe_pro_case_count": int(select_k(swe_pro, 2)["cases"]),
        "swe_pro_k2_retention": float(select_k(swe_pro, 2)["local_retention_vs_global_mean"]),
        "swe_pro_k3_retention": float(select_k(swe_pro, 3)["local_retention_vs_global_mean"]),
    }

    predictor_row = next(
        row for row in read_csv("results/dag_prediction_gpt55_high_20260707/scoring/prediction_accuracy_summary.csv")
        if row["mode"] == "full"
    )
    predictor = {
        "case_count": int(predictor_row["n"]),
        "node_recall": float(predictor_row["node_recall_mean"]),
        "edge_recall": float(predictor_row["edge_recall_mean"]),
        "retained_reference_work_ratio": float(predictor_row["retained_reference_work_ratio_mean"]),
        "wall_seconds_per_call": float(predictor_row["wall_time_seconds_mean"]),
        "tokens_per_call": float(predictor_row["total_tokens_mean"]),
    }

    command = read_json(
        "results/candidate_dag_executor_eval_20260708/"
        "executor_v2_branch_isolated_rerun_20260708/corrected_outcome_summary.json"
    )
    command_heavy = {
        "runs": int(command["runs"]),
        "accepted_artifact_count": int(command["accepted_artifact_count"]),
        "abort_fallback_count": int(command["abort_fallback_count"]),
        "latency_overhead_ratio_if_abort_then_fallback": float(command["latency_overhead_ratio_if_abort_then_fallback"]),
        "extra_token_cost_ratio_if_abort_then_fallback": float(command["extra_token_cost_ratio_if_abort_then_fallback"]),
    }

    executor_summary = read_json("results/canonical_dag_executor_family_smoke_20260708/summary.json")
    executor_record = read_json("results/canonical_dag_executor_family_smoke_20260708/registry_record.json")
    executor_metrics = executor_record["metrics"]
    local_executor = {
        "window_count": int(executor_summary["case_count"]),
        "local_closures": int(executor_summary["local_dag_execution_success"]),
        "completed_node_artifacts": int(executor_summary["accepted_local_artifacts"]),
        "fallback_required": int(executor_summary["fallback_required"]),
        "deadlocks": int(executor_summary["deadlock"]),
        "mean_actual_max_concurrency": float(executor_metrics["mean_actual_max_concurrency"]),
        "executor_wall_over_ideal_w4_wall": float(executor_metrics["actual_executor_wall_over_ideal_w4_wall"]),
    }

    functional: dict[str, Any] = {}
    for name, result_dir in {
        "flex": "psb_paired_webbench_flex_gmin_revalidation_20260719",
        "grid": "psb_gmin_historical_chain_revalidation_grid_20260719",
    }.items():
        metrics = read_json(f"results/{result_dir}/metrics.json")
        evidence = read_json(f"results/{result_dir}/audit/evidence_integration.json")
        if name == "flex":
            scores = evidence["revalidation_observation"]["official_evaluator"]
            default_score = scores["default_score"]
            conditioned_score = scores["perfect_dag_score"]
        else:
            facts = evidence["recorded_facts"]
            default_score = facts["default_official_evaluator_score"]
            conditioned_score = facts["perfect_official_evaluator_score"]
        functional[name] = {
            "default_score": int(default_score),
            "conditioned_score": int(conditioned_score),
            "unconditioned_over_conditioned_e2e_ratio": float(metrics["diagnostic_e2e_speedup"]),
            "conditioned_over_unconditioned_total_token_ratio": float(metrics["reported_total_token_ratio"]),
            "performance_claim_eligible": bool(metrics["performance_claim_eligible"]),
            "timing_claim_scope": metrics["timing_claim_scope"],
        }

    invalid_pairs: dict[str, Any] = {}
    for case in ("P007", "P018"):
        evidence = read_json(f"results/sge_p30_paired_scale_audit_20260728/{case}/evidence_integration.json")
        invalid_pairs[case] = {
            "terminal_status": evidence["terminal_status"],
            "pair_validity": evidence["pair_validity"],
            "failed_gates": evidence["failed_gates"],
            "paired_metrics": evidence["paired_metrics"],
        }

    result = {
        "schema_version": 1,
        "execution_mode": "offline_recomputation_from_packaged_derived_evidence",
        "claims": {
            "historical_same_trace_replay": historical,
            "exact_duration_structural_ceiling": structural,
            "duration_blind_admission": admission,
            "rolling_locality_sensitivity": locality,
            "full_graph_predictor_diagnostic": predictor,
            "command_heavy_negative_smoke": command_heavy,
            "local_executor_smoke": local_executor,
            "historical_functional_observations": functional,
            "strict_pair_rejections": invalid_pairs,
        },
        "claim_boundaries": [
            "Historical same-trace replay is a zero-overhead structural ceiling over observed action traces.",
            "Structural ceilings are not realized end-to-end speedups.",
            "Rolling locality values use mixed-duration extracted DAGs.",
            "Flex and Grid are historical whole-prompt functional observations with partial semantic realization.",
            "P007 and P018 are invalid pairs; formal paired speedup, token, and cost metrics remain null.",
            "No valid prospective quality-equivalent alpha_SGE is packaged.",
        ],
    }
    validate_sealed_expectations(result)
    return result


def validate_sealed_expectations(result: dict[str, Any]) -> None:
    claims = result["claims"]
    historical = claims["historical_same_trace_replay"]
    assert historical["case_count"] == 10
    close(historical["aggregate_unbounded_speedup"], 4.268974222446017)
    close(historical["aggregate_workers_2_list_speedup"], 1.9835817427018552)
    close(historical["aggregate_workers_4_list_speedup"], 3.405822357036705)
    close(historical["aggregate_workers_8_list_speedup"], 4.268974222446017)
    close(historical["case_median_unbounded_speedup"], 5.229280734405555)
    close(historical["case_max_unbounded_speedup"], 6.422651933701657)

    structural = claims["exact_duration_structural_ceiling"]
    assert structural["exact_duration_action_dag_count"] == 9
    assert structural["physical_repository_count"] == 6
    close(structural["p4_mean_ceiling"], 1.2138015292373572)
    close(structural["p4_median_ceiling"], 1.1770400775418222)
    close(structural["p4_max_ceiling"], 1.5297149853671081)

    admission = claims["duration_blind_admission"]
    assert admission["window_count"] == 188
    assert admission["case_count"] == 7
    assert admission["held_out_repository_count"] == 4
    close(admission["spearman"], 0.9897596758463504)
    close(admission["mae"], 0.08519728170300245)
    close(admission["mape"], 0.05652374175610231)
    assert admission["observed_below_rejected"] == 131
    assert admission["observed_below_total"] == 135
    assert admission["observed_at_or_above_admitted"] == 52
    assert admission["observed_at_or_above_total"] == 53
    assert admission["joint_unit_count"] == 130
    assert admission["nontrivial_window_count"] == 58
    close(admission["nontrivial_spearman"], 0.764917822861404)
    close(admission["nontrivial_mae"], 0.2761567062097321)
    close(admission["nontrivial_mape"], 0.18321488707150405)

    locality = claims["rolling_locality_sensitivity"]
    close(locality["swe_verified_k2_retention"], 0.9489)
    close(locality["swe_verified_k3_retention"], 0.9857)
    close(locality["swe_pro_k2_retention"], 0.9854)
    close(locality["swe_pro_k3_retention"], 0.9996)

    command = claims["command_heavy_negative_smoke"]
    assert command["runs"] == 10
    assert command["accepted_artifact_count"] == 0
    assert command["abort_fallback_count"] == 10
    close(command["latency_overhead_ratio_if_abort_then_fallback"], 0.3528, tolerance=1e-4)
    close(command["extra_token_cost_ratio_if_abort_then_fallback"], 0.2297, tolerance=1e-4)

    executor = claims["local_executor_smoke"]
    assert executor == {
        "window_count": 10,
        "local_closures": 8,
        "completed_node_artifacts": 49,
        "fallback_required": 2,
        "deadlocks": 0,
        "mean_actual_max_concurrency": 2.6,
        "executor_wall_over_ideal_w4_wall": 1.0021,
    }

    functional = claims["historical_functional_observations"]
    assert functional["flex"]["default_score"] == functional["flex"]["conditioned_score"] == 19
    assert functional["grid"]["default_score"] == functional["grid"]["conditioned_score"] == 24
    assert not functional["flex"]["performance_claim_eligible"]
    assert not functional["grid"]["performance_claim_eligible"]

    for case in ("P007", "P018"):
        pair = claims["strict_pair_rejections"][case]
        assert pair["terminal_status"] == "invalid"
        assert pair["pair_validity"] == "invalid"
        assert all(value is None for value in pair["paired_metrics"].values())


def markdown(result: dict[str, Any]) -> str:
    c = result["claims"]
    h = c["historical_same_trace_replay"]
    s = c["exact_duration_structural_ceiling"]
    a = c["duration_blind_admission"]
    lines = [
        "# Offline recomputation summary",
        "",
        "All values below were recomputed from the packaged derived evidence without network, model, or evaluator calls.",
        "",
        f"- Historical same-trace replay: {h['case_count']} clean Web-Bench traces; aggregate unbounded/P=2/P=4/P=8 list ceiling = {h['aggregate_unbounded_speedup']:.4f}x / {h['aggregate_workers_2_list_speedup']:.4f}x / {h['aggregate_workers_4_list_speedup']:.4f}x / {h['aggregate_workers_8_list_speedup']:.4f}x; case median/max unbounded ceiling = {h['case_median_unbounded_speedup']:.4f}x / {h['case_max_unbounded_speedup']:.4f}x.",
        f"- Exact-duration action DAGs: {s['exact_duration_action_dag_count']} across {s['physical_repository_count']} repositories; P=4 mean/median/max structural ceiling = {s['p4_mean_ceiling']:.4f}x / {s['p4_median_ceiling']:.4f}x / {s['p4_max_ceiling']:.4f}x.",
        f"- Duration-blind admission: {a['window_count']} windows across {a['held_out_repository_count']} physical repositories; Spearman = {a['spearman']:.4f}, MAE = {a['mae']:.4f}x, MAPE = {100*a['mape']:.2f}%.",
        f"- At 1.10x: rejected {a['observed_below_rejected']}/{a['observed_below_total']} observed-low windows and admitted {a['observed_at_or_above_admitted']}/{a['observed_at_or_above_total']} observed-high windows.",
        f"- Nontrivial sensitivity: {a['nontrivial_window_count']} windows after removing {a['joint_unit_count']} joint-unit windows; Spearman = {a['nontrivial_spearman']:.4f}, MAE = {a['nontrivial_mae']:.4f}x, MAPE = {100*a['nontrivial_mape']:.2f}%.",
        "- Strict paired canaries: P007 and P018 are invalid and all formal paired metrics remain null.",
        "",
        "These are structural, retrospective, local-mechanism, or historical functional observations. They do not establish a prospective end-to-end alpha_SGE.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "recomputed_claims.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "outputs" / "recomputed_claims.md")
    args = parser.parse_args()
    result = recompute()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"status": "pass", "output": str(args.output), "markdown_output": str(args.markdown_output)}, sort_keys=True))


if __name__ == "__main__":
    main()
