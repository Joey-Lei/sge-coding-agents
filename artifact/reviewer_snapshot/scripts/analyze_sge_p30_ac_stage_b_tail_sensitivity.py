#!/usr/bin/env python3
"""Recompute P30 A/C with and without the preselected Stage-B tail.

This companion never changes the frozen case index or the base analyzer.  It
first verifies the sealed A/C bundle, then treats positions 26--30 as
unobserved at the Stage-B DAG/join layers for the breaker-compliant stratum.
Source-trace and whole-task phase evidence remain unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from scripts import analyze_sge_p30_ac_overlay_v2 as overlay  # noqa: E402


SCHEMA_VERSION = "sge-p30-ac-stage-b-tail-sensitivity-v1"
OVERLAY_SCHEMA_VERSION = "sge-p30-ac-stage-b-tail-eligibility-overlay-v1"
INVENTORY_SCHEMA_VERSION = "sge-p30-ac-stage-b-tail-sensitivity-inventory-v1"
TAIL_POSITIONS = (26, 27, 28, 29, 30)
TAIL_CASE_IDS = (
    "swebench_verified_pylint-dev_pylint-4661",
    "swebench_verified_pytest-dev_pytest-5809",
    "swebench_verified_scikit-learn_scikit-learn-12973",
    "swebench_verified_sphinx-doc_sphinx-10435",
    "swebench_verified_sympy_sympy-19954",
)
EXCLUSION_REASON = "excluded_post_breaker_continuation_tail"
EXPECTED_AUTHORIZATION_SHA256 = (
    "138f6fc177e94212d7d58d30c00a8b5d8da2824f7fdc390381cb8acdb4589798"
)
EXPECTED_STAGE_B_SEAL_SHA256 = (
    "a90610306b9d70dc1c3e79cf995fd03112ccefde2158d23eb6b7cfb47bba12a8"
)
EXPECTED_BREAKER_WAVE_SHA256 = (
    "67a50773eb78db24d15a30bb1786c2d520fff4c313f7f908bf02be4290c5d3bd"
)
EXPECTED_CONTINUATION_WAVE_SHA256 = (
    "73ac769bba47511e284eea916b72cf79ee7318ea3b6c528ab1abc841245e4a6d"
)
EXPECTED_STAGE_B_SUMMARY_SHA256 = (
    "c2acc436408a0cf5e0d53c69bf681da80f03f309af9807e175315dee173bd80b"
)
DATA_FILES = (
    "sensitivity_report.json",
    "case_eligibility_overlay.json",
    "artifact_inventory.json",
)


class SensitivityError(RuntimeError):
    """A frozen input, transformation, output, or seal is invalid."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SensitivityError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def read_json_value(path: Path) -> Any:
    require(path.is_file() and not path.is_symlink(), f"unsafe JSON: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SensitivityError(f"invalid JSON {path}: {exc}") from exc


def read_object(path: Path) -> dict[str, Any]:
    value = read_json_value(path)
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def repository_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise SensitivityError(f"input must be inside repository: {path}") from exc


def resolve_repository_path(locator: Any) -> Path:
    require(isinstance(locator, str) and locator, "input locator missing")
    candidate = Path(locator)
    require(
        not candidate.is_absolute()
        and "." not in candidate.parts
        and ".." not in candidate.parts,
        f"unsafe input locator: {locator}",
    )
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SensitivityError(f"input escapes repository: {locator}") from exc
    require(not resolved.is_symlink(), f"input symlink forbidden: {locator}")
    return resolved


def verify_stage_b_inputs(
    stage_b_root: Path, authorization_path: Path
) -> dict[str, Any]:
    root = stage_b_root.resolve()
    authorization = authorization_path.resolve()
    require(root.is_dir() and not root.is_symlink(), "Stage-B root missing")
    require(
        sha256_file(root / "SHA256SUMS") == EXPECTED_STAGE_B_SEAL_SHA256,
        "Stage-B root seal identity drift",
    )
    require(
        sha256_file(authorization) == EXPECTED_AUTHORIZATION_SHA256,
        "continuation authorization identity drift",
    )
    breaker_path = root / "run_waves/wave_002.json"
    continuation_path = root / "run_waves/wave_003.json"
    summary_path = root / "p30_stage_b_campaign_summary.json"
    require(
        sha256_file(breaker_path) == EXPECTED_BREAKER_WAVE_SHA256,
        "breaker wave identity drift",
    )
    require(
        sha256_file(continuation_path) == EXPECTED_CONTINUATION_WAVE_SHA256,
        "continuation wave identity drift",
    )
    require(
        sha256_file(summary_path) == EXPECTED_STAGE_B_SUMMARY_SHA256,
        "Stage-B summary identity drift",
    )
    auth = read_object(authorization)
    wave = read_object(continuation_path)
    require(
        auth.get("held_positions") == list(TAIL_POSITIONS)
        and auth.get("held_case_ids") == list(TAIL_CASE_IDS)
        and auth.get("continue_all_held_cases_regardless_of_case_outcome") is True
        and auth.get("original_breaker_compliant_primary_record_preserved") is True
        and auth.get("scientific_role")
        == "preselected_tail_coverage_extension_with_mandatory_breaker_exclusion_sensitivity",
        "continuation authorization contract drift",
    )
    require(
        wave.get("wave_ordinal") == 3
        and wave.get("continuation_input_case_ids") == list(TAIL_CASE_IDS)
        and wave.get("original_breaker_compliant_primary_record_preserved")
        is True
        and wave.get("scientific_inclusion_label")
        == "pooled_A_C_only_with_collection_phase_label_and_breaker_exclusion_sensitivity",
        "continuation wave contract drift",
    )
    return {
        "stage_b_root": repository_relative(root),
        "stage_b_seal_sha256": EXPECTED_STAGE_B_SEAL_SHA256,
        "continuation_authorization": repository_relative(authorization),
        "continuation_authorization_sha256": EXPECTED_AUTHORIZATION_SHA256,
        "breaker_wave_sha256": EXPECTED_BREAKER_WAVE_SHA256,
        "continuation_wave_sha256": EXPECTED_CONTINUATION_WAVE_SHA256,
        "stage_b_summary_sha256": EXPECTED_STAGE_B_SUMMARY_SHA256,
    }


def eligibility_denominators(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "intention_to_measure": len(rows),
        "source_trace": sum(bool(row["source_trace_eligible"]) for row in rows),
        "contiguous_e2e_phase": sum(
            bool(row["contiguous_e2e_phase_eligible"]) for row in rows
        ),
        "audited_effective_dag": sum(
            bool(row["audited_effective_dag_eligible"]) for row in rows
        ),
        "observed_duration_join": sum(
            bool(row["observed_duration_join_eligible"]) for row in rows
        ),
        "paired_executor_D": sum(
            bool(row["paired_executor_D_eligible"]) for row in rows
        ),
    }


def duration_partition(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    categories = (
        "effective_semantic_work",
        "system_envelope",
        "redundant_exploration",
        "tool_noise",
    )
    totals = {
        category: sum(
            float(row["duration_partition"][category])
            for row in rows
            if isinstance(row.get("duration_partition"), Mapping)
        )
        for category in categories
    }
    return {
        "joined_case_count": sum(
            isinstance(row.get("duration_partition"), Mapping) for row in rows
        ),
        "seconds": totals,
        "all_action_seconds": sum(totals.values()),
        "exact_conservation_per_case_required": True,
        "imputed_duration_seconds": 0.0,
        "uncovered_duration_seconds": 0.0,
    }


def experiment_a(
    rows: Sequence[Mapping[str, Any]], phase: Mapping[str, Any]
) -> dict[str, Any]:
    base = overlay.base
    return {
        "whole_task_phase_composition": copy.deepcopy(phase),
        "type_weighted": base.summarize_graph_model(rows, "type_weighted"),
        "observed_duration": base.summarize_graph_model(
            rows, "observed_duration"
        ),
        "prevalence": {
            "S_infinity": base.a_prevalence(rows, "S_infinity"),
            "P4": base.a_prevalence(rows, "P4"),
        },
        "strata": base.a_strata(rows),
        "claim_boundary": (
            "action-layer execution-space diagnostics; system-envelope, "
            "redundant, and tool-noise seconds are conserved but excluded "
            "from effective semantic-DAG W/L"
        ),
    }


def bounded_c(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "held_out_repositories": sorted(overlay.HELD_OUT_REPOSITORIES),
        "primary_threshold": overlay.base.C_PRIMARY_THRESHOLD,
        "label_counts": dict(
            sorted(
                Counter(
                    str(row["bounded_validation_label"]) for row in rows
                ).items()
            )
        ),
        "quality_or_evaluator_outcome_used_for_labels": False,
    }


def attrition(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "case_rows_retained": len(rows),
        "reason_counts": dict(
            sorted(
                Counter(
                    reason
                    for row in rows
                    for reason in row.get("attrition_reasons", [])
                ).items()
            )
        ),
    }


def exclude_tail(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output = copy.deepcopy(list(rows))
    require(
        [int(row["position"]) for row in output] == list(range(1, 31)),
        "base case rows lost P30 order",
    )
    observed_tail = tuple(
        str(output[position - 1]["case_id"]) for position in TAIL_POSITIONS
    )
    require(observed_tail == TAIL_CASE_IDS, "tail membership or order drift")
    for position in TAIL_POSITIONS:
        row = output[position - 1]
        row["audited_effective_dag_eligible"] = False
        row["observed_duration_join_eligible"] = False
        row["type_weighted_metrics"] = None
        row["observed_duration_metrics"] = None
        row["duration_partition"] = None
        row["attrition_reasons"] = sorted(
            set(row.get("attrition_reasons", [])) | {EXCLUSION_REASON}
        )
    return output


def case_overlay(
    included: Sequence[Mapping[str, Any]],
    excluded: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = []
    for current, sensitivity in zip(included, excluded):
        position = int(current["position"])
        rows.append(
            {
                "position": position,
                "case_id": current["case_id"],
                "preselected_tail": position in TAIL_POSITIONS,
                "including_post_breaker_tail": {
                    "source_trace": current["source_trace_eligible"],
                    "contiguous_e2e_phase": current[
                        "contiguous_e2e_phase_eligible"
                    ],
                    "audited_effective_dag": current[
                        "audited_effective_dag_eligible"
                    ],
                    "observed_duration_join": current[
                        "observed_duration_join_eligible"
                    ],
                    "paired_executor_D": current["paired_executor_D_eligible"],
                    "attrition_reasons": current["attrition_reasons"],
                },
                "breaker_compliant_excluding_tail": {
                    "source_trace": sensitivity["source_trace_eligible"],
                    "contiguous_e2e_phase": sensitivity[
                        "contiguous_e2e_phase_eligible"
                    ],
                    "audited_effective_dag": sensitivity[
                        "audited_effective_dag_eligible"
                    ],
                    "observed_duration_join": sensitivity[
                        "observed_duration_join_eligible"
                    ],
                    "paired_executor_D": sensitivity[
                        "paired_executor_D_eligible"
                    ],
                    "attrition_reasons": sensitivity["attrition_reasons"],
                },
            }
        )
    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "scientific_result": False,
        "preregistered_primary": False,
        "primary_result": False,
        "case_count": 30,
        "tail_positions": list(TAIL_POSITIONS),
        "tail_case_ids": list(TAIL_CASE_IDS),
        "rows": rows,
    }


def build_payloads(
    base_result_root: Path,
    stage_b_root: Path,
    authorization_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_root = base_result_root.resolve()
    try:
        verified = overlay.verify_bundle(base_root)
    except (overlay.ExtensionError, overlay.CaseIneligible) as exc:
        raise SensitivityError(f"base A/C verification failed: {exc}") from exc
    require(verified.get("status") == "passed", "base A/C bundle not verified")
    bindings = verify_stage_b_inputs(stage_b_root, authorization_path)
    report = read_object(base_root / "extension_report.json")
    rows_value = read_json_value(base_root / "case_rows.json")
    c_value = read_json_value(base_root / "c_candidate_rows.json")
    require(
        isinstance(rows_value, list) and len(rows_value) == 30,
        "base case rows invalid",
    )
    require(isinstance(c_value, list), "base C rows invalid")
    rows = [dict(row) for row in rows_value if isinstance(row, Mapping)]
    c_rows = [dict(row) for row in c_value if isinstance(row, Mapping)]
    require(len(rows) == 30 and len(c_rows) == len(c_value), "base row malformed")
    included_denominators = eligibility_denominators(rows)
    require(
        included_denominators
        == {
            "intention_to_measure": 30,
            "source_trace": 25,
            "contiguous_e2e_phase": 23,
            "audited_effective_dag": 20,
            "observed_duration_join": 9,
            "paired_executor_D": 0,
        },
        "included denominator drift",
    )
    require(
        report["eligibility_denominators"]["observed_duration_join"] == 9
        and report["experiment_C"]["candidate_unique_window_count"] == 221
        and report["experiment_C"]["paired_observed_unique_window_count"] == 188,
        "base report summary drift",
    )

    excluded_rows = exclude_tail(rows)
    excluded_c_rows = [
        row for row in c_rows if int(row["position"]) not in TAIL_POSITIONS
    ]
    excluded_denominators = eligibility_denominators(excluded_rows)
    require(
        excluded_denominators
        == {
            "intention_to_measure": 30,
            "source_trace": 25,
            "contiguous_e2e_phase": 23,
            "audited_effective_dag": 16,
            "observed_duration_join": 8,
            "paired_executor_D": 0,
        },
        "excluded denominator drift",
    )
    phase = report["experiment_A"]["whole_task_phase_composition"]
    excluded_a = experiment_a(excluded_rows, phase)
    excluded_c = overlay.base._c_report(excluded_c_rows)
    require(
        excluded_c["candidate_unique_window_count"] == 180
        and excluded_c["paired_observed_unique_window_count"] == 147
        and excluded_c["paired_observed_case_count"] == 6
        and excluded_c["paired_observed_repository_count"] == 4,
        "excluded C count drift",
    )
    require(
        excluded_a["prevalence"]["S_infinity"]["three_to_four_count"] == 0
        and excluded_a["prevalence"]["P4"]["three_to_four_count"] == 0,
        "excluded prevalence drift",
    )
    require(
        pretty_bytes(excluded_a["whole_task_phase_composition"])
        == pretty_bytes(phase),
        "tail exclusion changed whole-task phase composition",
    )
    require(
        all(
            int(row["position"]) not in TAIL_POSITIONS
            for row in excluded_c_rows
        ),
        "tail C row survived exclusion",
    )

    sensitivity_report = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed_post_breaker_tail_sensitivity",
        "scientific_result": False,
        "preregistered_primary": False,
        "primary_result": False,
        "sensitivity_axis": (
            "preselected Stage-B positions 26-30 included versus treated as "
            "unobserved after the original breaker"
        ),
        "tail_selection_uses_outcome_or_ceiling": False,
        "tail_positions": list(TAIL_POSITIONS),
        "tail_case_ids": list(TAIL_CASE_IDS),
        "input_bindings": {
            "base_result_root": repository_relative(base_root),
            "base_result_seal_sha256": sha256_file(base_root / "SHA256SUMS"),
            **bindings,
        },
        "including_post_breaker_tail": {
            "eligibility_denominators": included_denominators,
            "attrition": copy.deepcopy(report["attrition"]),
            "action_duration_partition": copy.deepcopy(
                report["action_duration_partition"]
            ),
            "experiment_A": copy.deepcopy(report["experiment_A"]),
            "experiment_C": copy.deepcopy(report["experiment_C"]),
            "C_bounded_validation": copy.deepcopy(
                report["C_bounded_validation"]
            ),
        },
        "breaker_compliant_excluding_tail": {
            "eligibility_denominators": excluded_denominators,
            "attrition": attrition(excluded_rows),
            "action_duration_partition": duration_partition(excluded_rows),
            "experiment_A": excluded_a,
            "experiment_C": excluded_c,
            "C_bounded_validation": bounded_c(excluded_c_rows),
        },
        "delta": {
            "audited_effective_dag": 4,
            "observed_duration_join": 1,
            "C_candidate_unique_windows": 41,
            "C_paired_observed_unique_windows": 41,
            "C_paired_observed_cases": 1,
        },
        "claim_boundary": {
            "post_collection_extension_not_preregistered_primary": True,
            "continuation_tail_is_sensitivity_stratum": True,
            "online_acceleration_claim": False,
            "paired_executor_D_claim": False,
        },
        "offline_analysis_delta": {
            "model_or_api_invocations": 0,
            "benchmark_target_invocations": 0,
            "official_evaluator_invocations": 0,
            "task_originated_network_calls": 0,
        },
    }
    overlay_payload = case_overlay(rows, excluded_rows)
    return sensitivity_report, overlay_payload


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(pretty_bytes(value))


def build_inventory(root: Path) -> dict[str, Any]:
    rows = []
    for name in ("sensitivity_report.json", "case_eligibility_overlay.json"):
        path = root / name
        rows.append(
            {
                "path": name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "file_count": len(rows),
        "files": rows,
    }


def write_seal(root: Path) -> None:
    lines = [
        f"{sha256_file(root / name)}  {name}\n" for name in sorted(DATA_FILES)
    ]
    (root / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")


def prepare(
    base_result_root: Path,
    stage_b_root: Path,
    authorization_path: Path,
    result_root: Path,
) -> dict[str, Any]:
    destination = result_root.resolve()
    require(not destination.exists(), "result root already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.tmp-", dir=destination.parent
        )
    )
    try:
        report, case_rows = build_payloads(
            base_result_root, stage_b_root, authorization_path
        )
        write_json(temporary / "sensitivity_report.json", report)
        write_json(temporary / "case_eligibility_overlay.json", case_rows)
        write_json(temporary / "artifact_inventory.json", build_inventory(temporary))
        write_seal(temporary)
        os.rename(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def parse_seal(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        require(len(parts) == 2, "malformed output seal")
        digest, name = parts
        require(
            len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest),
            "bad output seal digest",
        )
        require(name not in rows, "duplicate output seal row")
        rows[name] = digest
    return rows


def verify(result_root: Path) -> dict[str, Any]:
    root = result_root.resolve()
    require(root.is_dir() and not root.is_symlink(), "result root missing")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    require(
        actual == set(DATA_FILES) | {"SHA256SUMS"},
        "output file closure mismatch",
    )
    seal = parse_seal(root / "SHA256SUMS")
    require(set(seal) == set(DATA_FILES), "output seal closure mismatch")
    for name, digest in seal.items():
        require(sha256_file(root / name) == digest, f"output tamper: {name}")
    report = read_object(root / "sensitivity_report.json")
    case_rows = read_object(root / "case_eligibility_overlay.json")
    inventory = read_object(root / "artifact_inventory.json")
    require(
        inventory == build_inventory(root), "output inventory mismatch"
    )
    bindings = report.get("input_bindings")
    require(isinstance(bindings, Mapping), "input bindings missing")
    base_root = resolve_repository_path(bindings.get("base_result_root"))
    stage_b_root = resolve_repository_path(bindings.get("stage_b_root"))
    authorization = resolve_repository_path(
        bindings.get("continuation_authorization")
    )
    current_report, current_rows = build_payloads(
        base_root, stage_b_root, authorization
    )
    require(
        pretty_bytes(report) == pretty_bytes(current_report),
        "sensitivity report no longer recomputes",
    )
    require(
        pretty_bytes(case_rows) == pretty_bytes(current_rows),
        "case sensitivity overlay no longer recomputes",
    )
    excluded = report["breaker_compliant_excluding_tail"]
    pooled = excluded["experiment_A"]["observed_duration"]["S_infinity"][
        "pooled_duration_sumW_over_sumL"
    ]
    require(
        isinstance(pooled, (int, float))
        and math.isclose(float(pooled), 1.1414, rel_tol=5e-5),
        "excluded pooled observed S-infinity drift",
    )
    return {
        "status": "passed",
        "scientific_result": False,
        "preregistered_primary": False,
        "primary_result": False,
        "including_denominators": report["including_post_breaker_tail"][
            "eligibility_denominators"
        ],
        "excluding_denominators": excluded["eligibility_denominators"],
        "including_C_paired_windows": report["including_post_breaker_tail"][
            "experiment_C"
        ]["paired_observed_unique_window_count"],
        "excluding_C_paired_windows": excluded["experiment_C"][
            "paired_observed_unique_window_count"
        ],
        "sealed_artifact_count": len(DATA_FILES),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--base-result-root", type=Path, required=True)
    prepare_parser.add_argument("--stage-b-root", type=Path, required=True)
    prepare_parser.add_argument(
        "--continuation-authorization", type=Path, required=True
    )
    prepare_parser.add_argument("--result-root", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            report = prepare(
                args.base_result_root,
                args.stage_b_root,
                args.continuation_authorization,
                args.result_root,
            )
            result = {
                "status": report["status"],
                "including_denominators": report[
                    "including_post_breaker_tail"
                ]["eligibility_denominators"],
                "excluding_denominators": report[
                    "breaker_compliant_excluding_tail"
                ]["eligibility_denominators"],
                "result_root": str(args.result_root),
            }
        else:
            result = verify(args.result_root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        SensitivityError,
        overlay.ExtensionError,
        overlay.CaseIneligible,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
