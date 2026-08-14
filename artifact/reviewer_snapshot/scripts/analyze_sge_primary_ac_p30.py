#!/usr/bin/env python3
"""Offline A/C analysis for the frozen 30-case SGE primary bridge cohort.

The program never discovers cases by scanning result directories.  It consumes
exactly two sealed inputs:

* the frozen P30 cohort manifest; and
* a deterministic, 30-row case index whose rows point into sealed artifact
  roots.

Missing, failed, and ineligible cases remain in the intention-to-measure
denominator.  Test fixtures can exercise the implementation, but can never
produce a scientific result.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dag_speedup_estimator import (  # noqa: E402
    TYPE_WEIGHTS,
    bottom_levels,
    critical_path,
    list_schedule_makespan,
    topological_order,
)


SCHEMA_VERSION = "sge-primary-ac-p30-analysis-v1"
CASE_INDEX_SCHEMA_VERSION = "sge-primary-ac-p30-case-index-v1"
RUN_REPORT_SCHEMA_VERSION = "sge-p30-target-default-run-v1"
COLLECTION_PLAN_SCHEMA_VERSION = "sge-p30-collection-plan-v1"
AUTHORIZATION_SCHEMA_VERSION = "sge-p30-single-run-authorization-v2"
ANALYSIS_CONTRACT_ID = "SGE-PRIMARY-P30-AC-ANALYSIS-20260727-V1"
ANALYSIS_CONTRACT_PATH = (
    ROOT
    / "experiments/perfect_speculation_speedup_bound/direct_pair/"
    "trace_to_reference_dag/cohorts/sge_primary_scale_20260727/"
    "analysis_contract.json"
)
ANALYSIS_CONTRACT_SHA256 = (
    "b859310e41f8618eaf2495702035bd311e3054a33d4f224badd30721d75dca44"
)
ESTIMATOR_PATH = ROOT / "scripts/dag_speedup_estimator.py"
ESTIMATOR_SHA256 = (
    "f01c398c84a7d7896c1e2aaff27336fee8f4bb7276439811ba3081dccc8f5210"
)
RUNNER_PATH = ROOT / "scripts/sge_p30_swebench_runner.py"
REPLAY_HELPER_PATH = ROOT / "scripts/replay_trace_speculation.py"
REPLAY_HELPER_SHA256 = (
    "48fafec39a143e0d45b5c86efc234a43d68f1697d1e613984203f0f3c2382477"
)
TYPE_WEIGHTS_PAYLOAD_SHA256 = (
    "41d3ddb75592d96165d04dc3389822e354f08c4d0dfc5249d8e5ea38be587c27"
)
DATASET_ID = "SWE-bench/SWE-bench_Verified"
DATASET_SNAPSHOT = "91aa3ed51b709be6457e12d00300a6a596d4c6a3"
DATASET_ARROW_SHA256 = (
    "0d119efe73413554335bd410a04d82fd4a586bfd312cee677ee40af5de2ac46e"
)
HARNESS_VERSION = "3.0.17"
FROZEN_EVALUATOR_PYTHON_VERSION = "3.11.15"
FROZEN_EVALUATOR_PACKAGES = {
    "docker": "7.2.0",
    "pyarrow": "21.0.0",
    "swebench": HARNESS_VERSION,
}
FROZEN_EVALUATOR_ENTRYPOINTS = {
    "swebench.harness.constants": (
        "swebench/harness/constants/__init__.py"
    ),
    "swebench.harness.docker_utils": "swebench/harness/docker_utils.py",
    "swebench.harness.grading": "swebench/harness/grading.py",
    "swebench.harness.run_evaluation": (
        "swebench/harness/run_evaluation.py"
    ),
    "swebench.harness.test_spec.test_spec": (
        "swebench/harness/test_spec/test_spec.py"
    ),
}
EVALUATOR_DEPENDENCY_SCHEMA_VERSION = (
    "sge-p30-official-evaluator-dependency-manifest-v1"
)
FROZEN_CODEX_CLI_VERSION = "codex-cli 0.144.1"
AUTHORIZATION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "explicit_user_approval",
        "execution_authorized",
        "design_id",
        "campaign_id",
        "cohort_membership_sha256",
        "position",
        "case_id",
        "instance_id",
        "preflight_report_sha256",
        "prepared_packet_sha256",
        "dataset_arrow_sha256",
        "docker_image_key",
        "docker_image_id",
        "docker_image_repo_digest",
        "codex_linux_binary_sha256",
        "codex_linux_runtime_manifest_sha256",
        "codex_cli_version",
        "target_model",
        "reasoning_effort",
        "target_container_security_contract_sha256",
        "task_tool_network_policy",
        "official_evaluator_network_mode",
        "otel_provider_spans_required",
        "bundled_model_catalog_required",
        "benchmark_target_invocations_maximum",
        "provider_model_invocations_maximum",
        "official_evaluator_invocations_maximum",
        "task_originated_network_calls_maximum",
        "retry_count",
        "substitution_count",
        "run_id",
    }
)
FROZEN_TYPE_WEIGHTS = {
    "build": 6.0,
    "diagnosis_branch": 2.5,
    "edit": 3.0,
    "env_probe": 2.0,
    "fetch": 1.5,
    "grep": 1.2,
    "lint": 2.5,
    "patch_candidate": 4.0,
    "patch_sketch": 4.0,
    "read": 1.0,
    "shell": 0.8,
    "targeted_test": 4.0,
    "test": 5.0,
}
DESIGN_ID = "SGE-PRIMARY-SCALE-Q8-P30-P100-20260727"
CAMPAIGN_ID = "SGE-PRIMARY-P30-20260727-01"
COHORT_MEMBERSHIP_SHA256 = (
    "5473479e9bbf68a3953b3d796a44e5a409f60271ccd74b16089bfcab1cfb1f1e"
)
TARGET_MODEL = "gpt-5.5"
REASONING_EFFORT = "medium"
WORKERS = (1, 2, 4, 8)
C_PRIMARY_WORKERS = 4
C_DEPTHS: tuple[int | str, ...] = (1, 2, 3, "full")
C_WIDTHS = (1, 2, 4, 8)
C_THRESHOLDS = (1.05, 1.10, 1.25)
C_PRIMARY_THRESHOLD = 1.10
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = "sge-primary-p30-ac-bootstrap-20260727-v1"
HELD_OUT_REPOSITORIES = frozenset(
    {
        "scikit-learn/scikit-learn",
        "pydata/xarray",
        "django/django",
        "pytest-dev/pytest",
    }
)
OUTPUT_DATA_FILES = (
    "analysis_report.json",
    "a_case_rows.json",
    "observed_action_identity_ledger.json",
    "c_candidate_rows.json",
)
OUTPUT_FILES = (*OUTPUT_DATA_FILES, "artifact_inventory.json")
P30_OWNER_DIR = (
    ROOT
    / "experiments/perfect_speculation_speedup_bound/direct_pair/"
    "trace_to_reference_dag/cohorts/sge_primary_scale_20260727"
)
P30_V8_COLLECTION_PLAN_PATH = P30_OWNER_DIR / "p30_collection_plan_v8.json"
P30_V8_COLLECTION_PLAN_SHA256 = (
    "a3ffe2f892fcbc33920e974e6b7b2f7d9d21e49c611eaae13d6907661e011d1b"
)
P30_V8_ORIGINAL_ANALYZER_SHA256 = (
    "3c41a8483bda1ab2e34553580fb1ef9ff09c45b08d34972ea0eb5d4a68248c10"
)
P30_CONTRACT_FIXED_ANALYZER_SHA256 = (
    "e93ada797739fd833c81a8daf7ac74bfc36d1e9885991380f02015d4b44be9d0"
)
P30_CONTRACT_FIX_COMMIT = "4e5e0650b4d6126e6ed3b0283c7bda014acf90a9"
POST_COLLECTION_RECOVERY_SCHEMA_VERSION = (
    "sge-p30-post-collection-contract-recovery-amendment-v1"
)
POST_COLLECTION_RECOVERY_AMENDMENT_ID = (
    "SGE-P30-POST-COLLECTION-ANALYZER-CONTRACT-RECOVERY-20260728-V1"
)
POST_COLLECTION_RECOVERY_STATUS = "post_collection_contract_recovery"
POST_COLLECTION_RECOVERY_AMENDMENT_PATH = (
    P30_OWNER_DIR
    / "p30_post_collection_analyzer_contract_recovery_amendment.json"
)
POST_COLLECTION_RECOVERY_OUTPUT_DATA_FILES = (
    "recovery_report.json",
    "recovered_phase_rows.json",
)
POST_COLLECTION_RECOVERY_OUTPUT_FILES = (
    *POST_COLLECTION_RECOVERY_OUTPUT_DATA_FILES,
    "artifact_inventory.json",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,79}$")


class AnalysisError(RuntimeError):
    """Fatal input-integrity, identity, or output-verification error."""


class EvidenceIneligible(RuntimeError):
    """A sealed observation is real but cannot enter an analysis denominator."""

    def __init__(self, *reasons: str):
        normalized = tuple(sorted({str(reason) for reason in reasons if reason}))
        super().__init__("; ".join(normalized))
        self.reasons = normalized or ("unspecified_ineligibility",)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def require_exact_mapping(
    value: Any, expected: Mapping[str, Any], *, label: str
) -> None:
    require(isinstance(value, Mapping), f"{label}: object required")
    require(set(value) == set(expected), f"{label}: field closure mismatch")
    for field, expected_value in expected.items():
        actual = value.get(field)
        require(
            type(actual) is type(expected_value) and actual == expected_value,
            f"{label}: {field} drift",
        )


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _nonnegative(value: Any) -> bool:
    return _finite(value) and float(value) >= 0.0


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json_value(path: Path) -> Any:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe JSON: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise AnalysisError(f"invalid JSON {path}: {exc}") from exc
    return value


def read_json(path: Path) -> dict[str, Any]:
    value = read_json_value(path)
    require(isinstance(value, dict), f"{path}: JSON object required")
    return value


def _safe_relative(locator: str, *, label: str) -> PurePosixPath:
    require(isinstance(locator, str) and locator, f"{label}: locator required")
    value = PurePosixPath(locator)
    require(not value.is_absolute(), f"{label}: absolute locator forbidden")
    require(
        value.parts
        and "." not in value.parts
        and ".." not in value.parts,
        f"{label}: traversal locator forbidden",
    )
    return value


def _path_without_symlink(path: Path, containment: Path, *, label: str) -> Path:
    containment = containment.resolve()
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(containment)
    except ValueError as exc:
        raise AnalysisError(f"{label}: path escapes containment root") from exc
    cursor = containment
    for part in relative.parts:
        cursor /= part
        require(not cursor.is_symlink(), f"{label}: symlink component forbidden")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(containment)
    except ValueError as exc:
        raise AnalysisError(f"{label}: resolved path escapes containment root") from exc
    return resolved


def _absolute_directory_without_symlink(locator: Any, *, label: str) -> Path:
    require(isinstance(locator, str) and locator, f"{label}: path required")
    candidate = Path(locator)
    require(candidate.is_absolute(), f"{label}: absolute path required")
    require(
        "." not in candidate.parts and ".." not in candidate.parts,
        f"{label}: non-canonical path forbidden",
    )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AnalysisError(f"{label}: missing or unresolved path") from exc
    require(
        resolved == candidate and not candidate.is_symlink(),
        f"{label}: symlink component forbidden",
    )
    require(candidate.is_dir(), f"{label}: directory required")
    return resolved


def _read_utf8_text(path: Path, *, label: str) -> str:
    require(path.is_file() and not path.is_symlink(), f"{label}: file required")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AnalysisError(f"{label}: unreadable UTF-8 file") from exc


def _input_containment(index_path: Path) -> Path:
    resolved = index_path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return index_path.parent.resolve()
    return ROOT.resolve()


def parse_sha256s(path: Path) -> dict[str, str]:
    require(path.is_file() and not path.is_symlink(), f"missing seal: {path}")
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)", line)
        require(matched is not None, f"{path}: malformed SHA256SUMS row")
        digest, locator = matched.groups()
        safe = _safe_relative(locator, label=f"{path} seal")
        normalized = safe.as_posix()
        require(normalized not in rows, f"{path}: duplicate seal row {normalized}")
        rows[normalized] = digest
    require(bool(rows), f"{path}: empty seal")
    return rows


def verify_file_in_sibling_seal(path: Path) -> str:
    seal = path.parent / "SHA256SUMS"
    rows = parse_sha256s(seal)
    expected = rows.get(path.name)
    require(expected is not None, f"{path}: missing from sibling SHA256SUMS")
    require(sha256_file(path) == expected, f"{path}: sibling seal digest mismatch")
    return sha256_file(seal)


def verify_sealed_root(root: Path, expected_seal_sha256: str) -> dict[str, str]:
    require(
        isinstance(expected_seal_sha256, str)
        and SHA256_RE.fullmatch(expected_seal_sha256) is not None,
        f"{root}: seal SHA-256 required",
    )
    require(root.is_dir() and not root.is_symlink(), f"missing sealed root: {root}")
    seal_path = root / "SHA256SUMS"
    require(
        sha256_file(seal_path) == expected_seal_sha256,
        f"{root}: SHA256SUMS identity mismatch",
    )
    rows = parse_sha256s(seal_path)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != seal_path
    }
    require(actual == set(rows), f"{root}: sealed file set mismatch")
    for locator, expected in rows.items():
        path = root.joinpath(*PurePosixPath(locator).parts)
        require(not path.is_symlink(), f"{root}: sealed artifact is a symlink: {locator}")
        require(sha256_file(path) == expected, f"{root}: digest mismatch: {locator}")
    inventories = [
        name for name in ("artifact_inventory.json", "stage_a_artifact_inventory.json")
        if name in rows
    ]
    for inventory_name in inventories:
        inventory = read_json(root / inventory_name)
        raw_items = inventory.get("files", inventory.get("artifacts"))
        require(isinstance(raw_items, list), f"{root}: invalid artifact inventory")
        indexed: dict[str, tuple[int, str]] = {}
        for item in raw_items:
            require(isinstance(item, Mapping), f"{root}: malformed inventory row")
            locator = str(item.get("path") or "")
            require(
                locator in rows and locator != inventory_name,
                f"{root}: inventory path drift: {locator}",
            )
            require(locator not in indexed, f"{root}: duplicate inventory row: {locator}")
            artifact = root.joinpath(*PurePosixPath(locator).parts)
            indexed[locator] = (int(item.get("bytes", -1)), str(item.get("sha256") or ""))
            require(
                indexed[locator] == (artifact.stat().st_size, rows[locator]),
                f"{root}: inventory metadata drift: {locator}",
            )
        require(
            set(indexed) == set(rows) - {inventory_name},
            f"{root}: inventory coverage mismatch",
        )
    return rows


def membership_hash(cases: Sequence[Mapping[str, Any]]) -> str:
    rows = [
        {
            "position": row["position"],
            "case_id": row["case_id"],
            "instance_id": row["instance_id"],
            "physical_repository": row["physical_repository"],
            "base_commit": row["base_commit"],
            "repository_domain_family": row["repository_domain_family"],
            "selection_hash": row["selection_hash"],
        }
        for row in cases
    ]
    return sha256_bytes(canonical_bytes(rows))


def validate_analysis_contract() -> dict[str, Any]:
    require(
        ESTIMATOR_PATH.is_file()
        and not ESTIMATOR_PATH.is_symlink()
        and sha256_file(ESTIMATOR_PATH) == ESTIMATOR_SHA256,
        "frozen DAG estimator source SHA-256 drift",
    )
    require(
        dict(TYPE_WEIGHTS) == FROZEN_TYPE_WEIGHTS,
        "frozen type-weight map drift",
    )
    require(
        ANALYSIS_CONTRACT_PATH.is_file()
        and not ANALYSIS_CONTRACT_PATH.is_symlink(),
        "frozen A/C analysis contract missing or unsafe",
    )
    require(
        sha256_file(ANALYSIS_CONTRACT_PATH) == ANALYSIS_CONTRACT_SHA256,
        "frozen A/C analysis contract SHA-256 drift",
    )
    contract = read_json(ANALYSIS_CONTRACT_PATH)
    require(
        contract.get("contract_id") == ANALYSIS_CONTRACT_ID,
        "A/C analysis contract identity drift",
    )
    require(
        contract.get("status") == "frozen_before_P30_target_outcomes",
        "A/C analysis contract was not outcome-blind frozen",
    )
    require(
        contract.get("parent_design_id") == DESIGN_ID
        and contract.get("cohort_membership_sha256")
        == COHORT_MEMBERSHIP_SHA256
        and contract.get("case_count") == 30,
        "A/C analysis contract cohort binding drift",
    )
    a_contract = contract.get("A")
    c_contract = contract.get("C")
    bootstrap = contract.get("bootstrap")
    require(
        isinstance(a_contract, Mapping)
        and a_contract.get("primary_space_metric")
        == "observed_duration_S_infinity_equals_W_over_L"
        and a_contract.get("primary_prevalence_denominator")
        == "intention_to_measure_all_30_positions"
        and a_contract.get("finite_worker_primary") == 4
        and a_contract.get("finite_worker_sensitivity") == [1, 2, 8]
        and a_contract.get("phase_buckets")
        == [
            "model_decision",
            "real_action_excluding_build_test",
            "build_test",
            "explicit_wait",
            "integration_finalization_and_official_evaluator",
            "measured_residual",
        ]
        and a_contract.get("phase_conservation_required") is True
        and a_contract.get("imputed_seconds_required") == 0
        and a_contract.get("uncovered_seconds_required") == 0
        and a_contract.get("prevalence_thresholds") == [2.0, 3.0, 4.0],
        "frozen A analysis choices drift",
    )
    require(
        isinstance(c_contract, Mapping)
        and c_contract.get("primary_worker_count") == C_PRIMARY_WORKERS
        and c_contract.get("worker_sensitivity") == [2, 8]
        and set(c_contract.get("held_out_physical_repositories") or [])
        == HELD_OUT_REPOSITORIES
        and c_contract.get("primary_threshold") == C_PRIMARY_THRESHOLD
        and c_contract.get("sensitivity_thresholds") == [1.05, 1.25],
        "frozen C analysis choices drift",
    )
    require(
        c_contract.get("topology_window_hash_fields")
        == [
            "sorted_node_id_and_canonical_type",
            "sorted_semantic_edges",
            "sorted_schedule_guard_edges",
        ]
        and c_contract.get("topology_window_hash_excludes")
        == [
            "duration",
            "worker_count",
            "depth",
            "width",
            "wave",
            "quality_or_performance_outcome",
        ]
        and c_contract.get("duplicate_hash_value_consistency_required") is True
        and c_contract.get("undefined_resample_counts_must_be_reported") is True,
        "frozen C topology or resampling choices drift",
    )
    require(
        isinstance(bootstrap, Mapping)
        and bootstrap.get("unit") == "physical_repository_with_all_frozen_cases"
        and bootstrap.get("resamples") == BOOTSTRAP_RESAMPLES
        and bootstrap.get("confidence_level") == 0.95
        and bootstrap.get("seed_string") == BOOTSTRAP_SEED,
        "frozen bootstrap choices drift",
    )
    input_policy = contract.get("input_policy")
    require(
        isinstance(input_policy, Mapping)
        and input_policy.get("case_index_is_explicit_and_deterministic") is True
        and input_policy.get("result_directory_scanning_for_usable_cases") is False
        and input_policy.get("failed_and_missing_cases_retained") is True
        and input_policy.get("duration_or_outcome_imputation") is False
        and input_policy.get("fixture_or_synthetic_data_scientific_result")
        is False,
        "frozen A/C input policy drift",
    )
    require(
        contract.get("scientific_result_gate")
        == {
            "all_30_positions_present": True,
            "input_and_artifact_seals_verified": True,
            "attrition_preserved": True,
            "no_selection_by_result_availability_or_sign": True,
        },
        "frozen scientific-result gate drift",
    )
    return contract


def validate_manifest(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    require(manifest.get("design_id") == DESIGN_ID, "cohort design identity drift")
    require(manifest.get("campaign_id") == CAMPAIGN_ID, "cohort campaign identity drift")
    require(manifest.get("case_count") == 30, "P30 manifest must declare 30 cases")
    cases = manifest.get("cases")
    require(isinstance(cases, list) and len(cases) == 30, "P30 case list must contain 30 rows")
    require(
        [row.get("position") for row in cases] == list(range(1, 31)),
        "P30 positions must be exactly 1..30",
    )
    require(
        len({str(row.get("case_id")) for row in cases}) == 30,
        "P30 case ids must be unique",
    )
    computed = membership_hash(cases)
    require(computed == COHORT_MEMBERSHIP_SHA256, "computed P30 membership hash drift")
    require(
        manifest.get("cohort_membership_sha256") == computed,
        "manifest membership hash drift",
    )
    split = manifest.get("c_repository_split")
    require(isinstance(split, Mapping), "frozen C repository split missing")
    require(
        set(split.get("held_out_repositories") or []) == HELD_OUT_REPOSITORIES,
        "held-out physical repository split drift",
    )
    return [dict(row) for row in cases]


def _collection_plan_path(
    index: Mapping[str, Any], index_path: Path
) -> tuple[Path, str]:
    descriptor = index.get("collection_plan")
    require(
        isinstance(descriptor, Mapping),
        "non-test case index requires a collection-plan descriptor",
    )
    relative = _safe_relative(
        str(descriptor.get("path") or ""),
        label="collection-plan",
    )
    path = _path_without_symlink(
        index_path.parent.joinpath(*relative.parts),
        index_path.parent.resolve(),
        label="collection-plan",
    )
    expected = str(descriptor.get("sha256") or "")
    require(
        SHA256_RE.fullmatch(expected) is not None
        and path.is_file()
        and sha256_file(path) == expected,
        "collection-plan digest or locator mismatch",
    )
    seal_rows = parse_sha256s(index_path.parent / "SHA256SUMS")
    require(
        relative.as_posix() in seal_rows
        and seal_rows[relative.as_posix()] == expected,
        "collection-plan is not bound by the input seal",
    )
    return path, expected


def _package_metadata_identity(
    metadata_path: Path, *, package: str
) -> tuple[str, str]:
    values: dict[str, list[str]] = defaultdict(list)
    for line in _read_utf8_text(
        metadata_path, label=f"evaluator package metadata {package}"
    ).splitlines():
        if line[:1].isspace() or ":" not in line:
            continue
        field, raw_value = line.split(":", 1)
        if field in {"Name", "Version"}:
            values[field].append(raw_value.strip())
    require(
        len(values["Name"]) == 1 and len(values["Version"]) == 1,
        f"evaluator package metadata identity malformed: {package}",
    )
    return values["Name"][0], values["Version"][0]


def validate_evaluator_dependency_manifest(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the frozen evaluator environment without importing its code."""

    require(
        set(payload)
        == {
            "schema_version",
            "status",
            "scientific_result",
            "environment",
            "packages",
            "swebench_record",
            "entrypoint_sources",
            "verification_boundary",
        },
        "evaluator dependency manifest field closure mismatch",
    )
    for field, expected in {
        "schema_version": EVALUATOR_DEPENDENCY_SCHEMA_VERSION,
        "status": "frozen_before_first_P30_target_outcome",
        "scientific_result": False,
    }.items():
        actual = payload.get(field)
        require(
            type(actual) is type(expected) and actual == expected,
            f"evaluator dependency manifest drift: {field}",
        )

    environment = payload.get("environment")
    require(
        isinstance(environment, Mapping)
        and set(environment) == {"python", "venv_path"},
        "evaluator dependency environment field closure mismatch",
    )
    require(
        environment.get("python") == FROZEN_EVALUATOR_PYTHON_VERSION,
        "evaluator dependency Python contract drift",
    )
    venv_root = _absolute_directory_without_symlink(
        environment.get("venv_path"),
        label="evaluator dependency venv",
    )
    python_config = _path_without_symlink(
        venv_root / "pyvenv.cfg",
        venv_root,
        label="evaluator dependency Python configuration",
    )
    config_versions = []
    for line in _read_utf8_text(
        python_config, label="evaluator dependency Python configuration"
    ).splitlines():
        field, separator, raw_value = line.partition("=")
        if separator and field.strip() == "version":
            config_versions.append(raw_value.strip())
    require(
        config_versions == [FROZEN_EVALUATOR_PYTHON_VERSION],
        "evaluator dependency Python version drift",
    )
    major_minor = ".".join(FROZEN_EVALUATOR_PYTHON_VERSION.split(".")[:2])
    site_packages = _path_without_symlink(
        venv_root / "lib" / f"python{major_minor}" / "site-packages",
        venv_root,
        label="evaluator dependency site-packages",
    )
    require(
        site_packages.is_dir() and not site_packages.is_symlink(),
        "evaluator dependency site-packages missing or unsafe",
    )

    packages = payload.get("packages")
    require_exact_mapping(
        packages,
        FROZEN_EVALUATOR_PACKAGES,
        label="evaluator dependency packages",
    )
    package_evidence: dict[str, str] = {}
    for package, version in FROZEN_EVALUATOR_PACKAGES.items():
        distribution_name = f"{package}-{version}.dist-info"
        matching_distributions = sorted(
            path.name
            for path in site_packages.iterdir()
            if path.name.startswith(f"{package}-")
            and path.name.endswith(".dist-info")
        )
        require(
            matching_distributions == [distribution_name],
            f"evaluator installed package version drift: {package}",
        )
        distribution = _path_without_symlink(
            site_packages / distribution_name,
            site_packages,
            label=f"evaluator package directory {package}",
        )
        require(
            distribution.is_dir() and not distribution.is_symlink(),
            f"evaluator package directory missing or unsafe: {package}",
        )
        metadata_path = _path_without_symlink(
            distribution / "METADATA",
            site_packages,
            label=f"evaluator package metadata {package}",
        )
        metadata_name, metadata_version = _package_metadata_identity(
            metadata_path, package=package
        )
        require(
            metadata_name == package and metadata_version == version,
            f"evaluator package metadata drift: {package}",
        )
        package_evidence[package] = metadata_version

    record = payload.get("swebench_record")
    require(
        isinstance(record, Mapping)
        and set(record) == {"bytes", "locator", "sha256"},
        "evaluator SWE-bench RECORD field closure mismatch",
    )
    expected_record_locator = f"swebench-{HARNESS_VERSION}.dist-info/RECORD"
    require(
        record.get("locator") == expected_record_locator,
        "evaluator SWE-bench RECORD locator drift",
    )
    expected_record_bytes = record.get("bytes")
    expected_record_sha = record.get("sha256")
    require(
        type(expected_record_bytes) is int
        and expected_record_bytes > 0
        and isinstance(expected_record_sha, str)
        and SHA256_RE.fullmatch(expected_record_sha) is not None,
        "evaluator SWE-bench RECORD identity malformed",
    )
    record_relative = _safe_relative(
        expected_record_locator,
        label="evaluator SWE-bench RECORD",
    )
    record_path = _path_without_symlink(
        site_packages.joinpath(*record_relative.parts),
        site_packages,
        label="evaluator SWE-bench RECORD",
    )
    require(
        record_path.is_file()
        and not record_path.is_symlink()
        and record_path.stat().st_size == expected_record_bytes
        and sha256_file(record_path) == expected_record_sha,
        "evaluator SWE-bench RECORD bytes or digest drift",
    )

    raw_entrypoints = payload.get("entrypoint_sources")
    require(
        isinstance(raw_entrypoints, list)
        and len(raw_entrypoints) == len(FROZEN_EVALUATOR_ENTRYPOINTS),
        "evaluator entrypoint source set drift",
    )
    entrypoint_evidence: list[dict[str, str]] = []
    seen_modules: set[str] = set()
    for row in raw_entrypoints:
        require(
            isinstance(row, Mapping)
            and set(row) == {"module", "package_relative_path", "sha256"},
            "evaluator entrypoint source field closure mismatch",
        )
        module = row.get("module")
        relative_locator = row.get("package_relative_path")
        expected_sha = row.get("sha256")
        require(
            isinstance(module, str)
            and module in FROZEN_EVALUATOR_ENTRYPOINTS
            and module not in seen_modules
            and relative_locator == FROZEN_EVALUATOR_ENTRYPOINTS[module],
            "evaluator entrypoint module or path drift",
        )
        require(
            isinstance(expected_sha, str)
            and SHA256_RE.fullmatch(expected_sha) is not None,
            f"evaluator entrypoint SHA-256 malformed: {module}",
        )
        relative = _safe_relative(
            relative_locator,
            label=f"evaluator entrypoint {module}",
        )
        source_path = _path_without_symlink(
            site_packages.joinpath(*relative.parts),
            site_packages,
            label=f"evaluator entrypoint {module}",
        )
        require(
            source_path.is_file()
            and not source_path.is_symlink()
            and sha256_file(source_path) == expected_sha,
            f"evaluator entrypoint source digest drift: {module}",
        )
        seen_modules.add(module)
        entrypoint_evidence.append(
            {
                "module": module,
                "package_relative_path": relative.as_posix(),
                "sha256": expected_sha,
            }
        )
    require(
        seen_modules == set(FROZEN_EVALUATOR_ENTRYPOINTS),
        "evaluator entrypoint source set drift",
    )

    require_exact_mapping(
        payload.get("verification_boundary"),
        {
            "record_sha_is_not_sufficient_alone": True,
            "entrypoint_source_sha_recomputation_required": True,
            "official_harness_version_required": HARNESS_VERSION,
            "official_evaluator_network_mode": "none",
        },
        label="evaluator dependency verification boundary",
    )
    entrypoint_evidence.sort(key=lambda row: row["module"])
    return {
        "venv_path": str(venv_root),
        "python": FROZEN_EVALUATOR_PYTHON_VERSION,
        "packages": package_evidence,
        "swebench_record": {
            "bytes": expected_record_bytes,
            "locator": expected_record_locator,
            "sha256": expected_record_sha,
        },
        "entrypoint_sources": entrypoint_evidence,
        "official_evaluator_network_mode": "none",
    }


def validate_collection_plan(
    plan: Mapping[str, Any],
    manifest_cases: Sequence[Mapping[str, Any]],
    *,
    test_only: bool,
) -> list[dict[str, Any]]:
    expected = {
        "schema_version": COLLECTION_PLAN_SCHEMA_VERSION,
        "status": (
            "frozen_pre_outcome_campaign_intent_with_per_case_authorization_gate"
        ),
        "scientific_result": False,
        "outcomes_visible_at_freeze": False,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
        "case_count": 30,
        "target_model": TARGET_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "per_case_authorization_must_be_frozen_before_case_outcome": True,
    }
    for field, value in expected.items():
        require(plan.get(field) == value, f"collection-plan drift: {field}")
    require(
        plan.get("canary_positions") == [1, 2, 3, 4, 5, 6],
        "collection-plan canary positions drift",
    )
    bindings = plan.get("global_bindings")
    require(isinstance(bindings, Mapping), "collection-plan bindings missing")
    required_bindings = {
        "cohort_manifest_sha256": (
            "29d1525acfc24904005d08645385b5cae88c6473bbcdc086278e447f19baeb1f"
        ),
        "source_spec_sha256": (
            "382516841b46c31ee057014db515351cba0cc809934ce597329bfe5508b78675"
        ),
        "p30_freeze_seal_sha256": (
            "550c409f0b5fbf2a78d3db81ff3ec01ed1d82da5b9aca2a0617e7e2a38dac848"
        ),
        "analysis_contract_sha256": ANALYSIS_CONTRACT_SHA256,
        "estimator_sha256": ESTIMATOR_SHA256,
        "replay_helper_sha256": REPLAY_HELPER_SHA256,
        "type_weights_payload_sha256": TYPE_WEIGHTS_PAYLOAD_SHA256,
        "dataset_id": DATASET_ID,
        "dataset_snapshot": DATASET_SNAPSHOT,
        "dataset_arrow_sha256": DATASET_ARROW_SHA256,
        "official_harness_version": HARNESS_VERSION,
    }
    for field, value in required_bindings.items():
        require(
            bindings.get(field) == value,
            f"collection-plan global binding drift: {field}",
        )
    require(
        sha256_file(ESTIMATOR_PATH) == bindings["estimator_sha256"]
        and sha256_file(REPLAY_HELPER_PATH) == bindings["replay_helper_sha256"]
        and sha256_bytes(canonical_bytes(dict(TYPE_WEIGHTS)))
        == bindings["type_weights_payload_sha256"],
        "collection-plan analysis dependency drift",
    )
    if not test_only:
        require(
            bindings.get("runner_source_sha256") == sha256_file(RUNNER_PATH),
            "collection-plan runner source drift",
        )
        require(
            bindings.get("analyzer_source_sha256")
            == sha256_file(Path(__file__).resolve()),
            "collection-plan analyzer source drift",
        )
        dependency_manifest = bindings.get("official_evaluator_dependency_manifest")
        require(
            isinstance(dependency_manifest, Mapping)
            and set(dependency_manifest) == {"path", "sha256"},
            "collection-plan evaluator dependency manifest descriptor malformed",
        )
        dependency_relative = _safe_relative(
            str(dependency_manifest.get("path") or ""),
            label="official evaluator dependency manifest",
        )
        dependency_sha256 = dependency_manifest.get("sha256")
        require(
            isinstance(dependency_sha256, str)
            and SHA256_RE.fullmatch(dependency_sha256) is not None,
            "collection-plan evaluator dependency manifest digest malformed",
        )
        dependency_path = _path_without_symlink(
            ROOT.joinpath(*dependency_relative.parts),
            ROOT.resolve(),
            label="official evaluator dependency manifest",
        )
        require(
            dependency_path.is_file()
            and not dependency_path.is_symlink()
            and sha256_file(dependency_path)
            == dependency_sha256,
            "collection-plan evaluator dependency manifest drift",
        )
        dependency_payload = read_json(dependency_path)
        validate_evaluator_dependency_manifest(dependency_payload)
    raw_rows = plan.get("case_rows")
    require(
        isinstance(raw_rows, list) and len(raw_rows) == 30,
        "collection-plan must contain exactly 30 case rows",
    )
    rows: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    for position, (raw, frozen) in enumerate(
        zip(raw_rows, manifest_cases), 1
    ):
        require(
            isinstance(raw, Mapping)
            and isinstance(raw.get("binding_payload"), Mapping),
            f"collection-plan row {position} malformed",
        )
        payload = dict(raw["binding_payload"])
        identity = {
            "position": frozen["position"],
            "case_id": frozen["case_id"],
            "instance_id": frozen["instance_id"],
            "physical_repository": frozen["physical_repository"],
            "base_commit": frozen["base_commit"],
            "run_id": f"p30-20260727-{position:03d}",
            "preflight_root": (
                "results/sge_p30_target_default_scale_20260727/"
                f"preflight/position_{position:03d}"
            ),
            "prepared_root": (
                "results/sge_p30_target_default_scale_20260727/"
                f"prepared/position_{position:03d}"
            ),
            "authorization_path": (
                "experiments/perfect_speculation_speedup_bound/direct_pair/"
                "trace_to_reference_dag/cohorts/sge_primary_scale_20260727/"
                f"p30_authorizations/position_{position:03d}.json"
            ),
            "result_root": (
                "results/sge_p30_target_default_scale_20260727/"
                f"runs/position_{position:03d}"
            ),
        }
        for field, value in identity.items():
            require(
                payload.get(field) == value,
                f"collection-plan row {position} drift: {field}",
            )
        require(
            payload.get("authorization_binding")
            == "external_pre_outcome_file_at_declared_locator",
            f"collection-plan row {position}: authorization gate missing",
        )
        row_sha = str(raw.get("binding_payload_sha256") or "")
        require(
            row_sha == sha256_bytes(canonical_bytes(payload)),
            f"collection-plan row {position} binding digest drift",
        )
        require(
            payload["run_id"] not in run_ids,
            "collection-plan duplicate run_id",
        )
        run_ids.add(payload["run_id"])
        rows.append(
            {
                **payload,
                "binding_payload_sha256": row_sha,
            }
        )
    return rows


def _index_rows(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = index.get("rows", index.get("cases"))
    require(isinstance(rows, list) and len(rows) == 30, "case index must contain 30 rows")
    return [dict(row) for row in rows]


def validate_case_index(
    index: Mapping[str, Any],
    manifest_cases: Sequence[Mapping[str, Any]],
    index_path: Path,
) -> list[dict[str, Any]]:
    require(
        index.get("schema_version") == CASE_INDEX_SCHEMA_VERSION,
        "case-index schema mismatch",
    )
    require(index.get("design_id") == DESIGN_ID, "case-index design identity drift")
    require(index.get("campaign_id") == CAMPAIGN_ID, "case-index campaign identity drift")
    require(
        index.get("cohort_membership_sha256") == COHORT_MEMBERSHIP_SHA256,
        "case-index cohort membership drift",
    )
    require(index.get("case_count") == 30, "case-index count must be 30")
    require(type(index.get("test_only")) is bool, "case-index test_only must be boolean")
    require(
        type(index.get("scientific_result_requested", False)) is bool,
        "case-index scientific_result_requested must be boolean",
    )
    require(
        not (
            index.get("test_only") is True
            and index.get("scientific_result_requested") is True
        ),
        "test-only case index cannot request a scientific result",
    )
    test_only = bool(index["test_only"])
    plan_rows: list[dict[str, Any]] | None = None
    plan_sha256: str | None = None
    if not test_only:
        plan_path, plan_sha256 = _collection_plan_path(index, index_path)
        plan_rows = validate_collection_plan(
            read_json(plan_path),
            manifest_cases,
            test_only=False,
        )
    rows = _index_rows(index)
    for position, (row, frozen) in enumerate(zip(rows, manifest_cases), 1):
        for field in (
            "position",
            "case_id",
            "instance_id",
            "physical_repository",
        ):
            require(
                row.get(field) == frozen.get(field),
                f"case-index identity drift at position {position}: {field}",
            )
        reasons = row.get("attrition_reasons", [])
        require(
            isinstance(reasons, list)
            and all(isinstance(value, str) and value for value in reasons),
            f"position {position}: attrition_reasons must be strings",
        )
        require(
            isinstance(row.get("status", "unavailable"), str),
            f"position {position}: status must be a string",
        )
        if plan_rows is not None:
            plan_row = plan_rows[position - 1]
            for field in ("run_id", "result_root"):
                expected_field = (
                    field if field == "run_id" else "expected_result_root"
                )
                require(
                    row.get(expected_field) == plan_row[field],
                    f"position {position}: case-index plan drift: {expected_field}",
                )
            require(
                row.get("collection_plan_case_binding_sha256")
                == plan_row["binding_payload_sha256"],
                f"position {position}: case-index plan-row digest drift",
            )
            row["_collection_plan_sha256"] = plan_sha256
            row["_collection_plan_case_binding_sha256"] = plan_row[
                "binding_payload_sha256"
            ]
            row["_plan_authorization_path"] = plan_row["authorization_path"]
            row["_plan_result_root"] = plan_row["result_root"]
        roots = row.get("sealed_roots", [])
        require(
            isinstance(roots, (list, dict)),
            f"position {position}: sealed_roots must be list or object",
        )
        artifacts = row.get("artifacts", {})
        require(
            isinstance(artifacts, Mapping),
            f"position {position}: artifacts must be an object",
        )
        if plan_rows is not None and row.get("status") == (
            "completed_target_and_official_evaluator"
        ):
            require(
                SHA256_RE.fullmatch(str(row.get("authorization_sha256") or ""))
                is not None,
                f"position {position}: authorization digest missing",
            )
    return rows


def _root_descriptors(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("sealed_roots", [])
    if isinstance(raw, Mapping):
        return [
            {"root_id": str(root_id), **dict(descriptor)}
            for root_id, descriptor in raw.items()
            if isinstance(descriptor, Mapping)
        ]
    return [dict(value) for value in raw if isinstance(value, Mapping)]


def resolve_case_artifacts(
    row: Mapping[str, Any], case_index_path: Path
) -> tuple[dict[str, Path], dict[str, Any]]:
    containment = _input_containment(case_index_path)
    roots: dict[str, tuple[Path, dict[str, str]]] = {}
    root_evidence: list[dict[str, Any]] = []
    for descriptor in _root_descriptors(row):
        root_id = str(descriptor.get("root_id") or descriptor.get("id") or "")
        require(root_id and root_id not in roots, f"{row['case_id']}: duplicate root id")
        raw_path = str(descriptor.get("path") or descriptor.get("root") or "")
        relative = _safe_relative(raw_path, label=f"{row['case_id']} root")
        root = _path_without_symlink(
            case_index_path.parent.joinpath(*relative.parts),
            containment,
            label=f"{row['case_id']} root",
        )
        seal_sha = str(
            descriptor.get("seal_sha256")
            or descriptor.get("sha256s_sha256")
            or ""
        )
        seal_rows = verify_sealed_root(root, seal_sha)
        roots[root_id] = (root, seal_rows)
        root_evidence.append(
            {
                "root_id": root_id,
                "path": str(root),
                "seal_sha256": seal_sha,
                "sealed_file_count": len(seal_rows),
            }
        )
    aliases = {
        "run_report": ("run_report", "target_run_report", "target_default_report"),
        "reference_dag": ("reference_dag", "effective_reference_dag"),
        "dag_verification": ("dag_verification", "verification"),
        "independent_audit": ("independent_audit", "dag_independent_audit"),
        "action_ledger": (
            "observed_action_identity_ledger",
            "action_ledger",
            "duration_ledger",
        ),
        "duration_blind_annotation": (
            "duration_blind_annotation",
            "candidate_annotation",
            "duration_blind_mapping",
        ),
        "authorization": (
            "authorization",
            "single_run_authorization",
        ),
    }
    raw_artifacts = row.get("artifacts") or {}
    resolved: dict[str, Path] = {}
    artifact_evidence: dict[str, Any] = {}
    for canonical, candidates in aliases.items():
        value: Any = None
        supplied_role: str | None = None
        for candidate in candidates:
            if candidate in raw_artifacts:
                value = raw_artifacts[candidate]
                supplied_role = candidate
                break
        if value is None:
            continue
        require(
            isinstance(value, Mapping),
            f"{row['case_id']}: artifact descriptor for {canonical} must be object",
        )
        root_id = str(value.get("root_id") or value.get("root") or "")
        require(root_id in roots, f"{row['case_id']}: unknown artifact root {root_id}")
        locator = str(value.get("path") or value.get("relative_path") or "")
        relative = _safe_relative(locator, label=f"{row['case_id']} {canonical}")
        root, seal_rows = roots[root_id]
        normalized = relative.as_posix()
        require(
            normalized in seal_rows,
            f"{row['case_id']}: {canonical} is not sealed: {normalized}",
        )
        path = _path_without_symlink(
            root.joinpath(*relative.parts),
            root,
            label=f"{row['case_id']} {canonical}",
        )
        require(path.is_file(), f"{row['case_id']}: missing artifact {canonical}")
        expected = str(value.get("sha256") or seal_rows[normalized])
        require(
            expected == seal_rows[normalized] == sha256_file(path),
            f"{row['case_id']}: {canonical} digest drift",
        )
        resolved[canonical] = path
        artifact_evidence[canonical] = {
            "supplied_role": supplied_role,
            "root_id": root_id,
            "path": normalized,
            "sha256": expected,
        }
    return resolved, {
        "sealed_roots": sorted(root_evidence, key=lambda value: value["root_id"]),
        "artifacts": artifact_evidence,
    }


def _edge_kind(edge: Mapping[str, Any], default: str = "semantic") -> str:
    raw = str(
        edge.get("edge_kind")
        or edge.get("edge_type")
        or edge.get("kind")
        or ""
    ).lower()
    if (
        "guard" in raw
        or edge.get("guard_id") not in (None, "")
        or edge.get("condition_id") not in (None, "")
    ):
        return "schedule_guard"
    return default


def normalize_dag(raw: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    raw_nodes = raw.get("nodes")
    require(isinstance(raw_nodes, list) and raw_nodes, f"{case_id}: DAG nodes missing")
    nodes: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    for node in raw_nodes:
        require(isinstance(node, Mapping), f"{case_id}: malformed DAG node")
        node_id = str(node.get("node_id") or node.get("id") or "")
        canonical_type = str(
            node.get("canonical_type")
            or node.get("kind")
            or node.get("type")
            or ""
        )
        require(node_id and node_id not in seen_nodes, f"{case_id}: duplicate DAG node")
        require(
            canonical_type in TYPE_WEIGHTS,
            f"{case_id}: noncanonical node type {canonical_type!r}",
        )
        seen_nodes.add(node_id)
        nodes.append({"node_id": node_id, "canonical_type": canonical_type})
    edge_rows: list[dict[str, str]] = []
    if isinstance(raw.get("semantic_dependency_edges"), list):
        for edge in raw["semantic_dependency_edges"]:
            edge_rows.append(
                {
                    "src": str(edge.get("src") or edge.get("source") or ""),
                    "dst": str(edge.get("dst") or edge.get("target") or ""),
                    "edge_kind": "semantic",
                }
            )
    if isinstance(raw.get("schedule_guard_edges"), list):
        for edge in raw["schedule_guard_edges"]:
            edge_rows.append(
                {
                    "src": str(edge.get("src") or edge.get("source") or ""),
                    "dst": str(edge.get("dst") or edge.get("target") or ""),
                    "edge_kind": "schedule_guard",
                }
            )
    if not edge_rows and isinstance(raw.get("edges"), list):
        for edge in raw["edges"]:
            require(isinstance(edge, Mapping), f"{case_id}: malformed DAG edge")
            edge_rows.append(
                {
                    "src": str(edge.get("src") or edge.get("source") or ""),
                    "dst": str(edge.get("dst") or edge.get("target") or ""),
                    "edge_kind": _edge_kind(edge),
                }
            )
    if not edge_rows:
        for node in raw_nodes:
            target = str(node.get("node_id") or node.get("id") or "")
            for source in node.get("depends_on") or []:
                edge_rows.append(
                    {
                        "src": str(source),
                        "dst": target,
                        "edge_kind": "semantic",
                    }
                )
    seen_edges: set[tuple[str, str, str]] = set()
    edges: list[dict[str, str]] = []
    for edge in edge_rows:
        key = (edge["src"], edge["dst"], edge["edge_kind"])
        require(
            edge["src"] in seen_nodes
            and edge["dst"] in seen_nodes
            and edge["src"] != edge["dst"],
            f"{case_id}: dangling or self DAG edge {key}",
        )
        require(key not in seen_edges, f"{case_id}: duplicate DAG edge {key}")
        seen_edges.add(key)
        edges.append(edge)
    normalized = {
        "nodes": sorted(nodes, key=lambda value: value["node_id"]),
        "edges": sorted(
            edges,
            key=lambda value: (value["edge_kind"], value["src"], value["dst"]),
        ),
    }
    _graph_parts(
        normalized,
        {
            node["node_id"]: TYPE_WEIGHTS[node["canonical_type"]]
            for node in normalized["nodes"]
        },
    )
    return normalized


def topology_payload(dag: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "nodes": sorted(
            [
                {
                    "node_id": str(node["node_id"]),
                    "canonical_type": str(node["canonical_type"]),
                }
                for node in dag["nodes"]
            ],
            key=lambda value: (value["node_id"], value["canonical_type"]),
        ),
        "edges": sorted(
            [
                {
                    "edge_kind": str(edge["edge_kind"]),
                    "src": str(edge["src"]),
                    "dst": str(edge["dst"]),
                }
                for edge in dag["edges"]
                if edge["edge_kind"] in {"semantic", "schedule_guard"}
            ],
            key=lambda value: (
                value["edge_kind"],
                value["src"],
                value["dst"],
            ),
        ),
    }


def topology_sha256(dag: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(topology_payload(dag)))


def induced_dag(dag: Mapping[str, Any], node_ids: Iterable[str]) -> dict[str, Any]:
    chosen = set(node_ids)
    return {
        "nodes": [
            dict(node) for node in dag["nodes"] if str(node["node_id"]) in chosen
        ],
        "edges": [
            dict(edge)
            for edge in dag["edges"]
            if str(edge["src"]) in chosen and str(edge["dst"]) in chosen
        ],
    }


def _graph_parts(
    dag: Mapping[str, Any], durations: Mapping[str, float]
) -> tuple[
    list[str],
    dict[str, float],
    dict[str, list[str]],
    dict[str, list[str]],
    list[str],
]:
    node_order = [str(node["node_id"]) for node in dag["nodes"]]
    require(len(node_order) == len(set(node_order)), "graph node identity collision")
    require(set(node_order) == set(durations), "duration/node identity mismatch")
    values = {node_id: float(durations[node_id]) for node_id in node_order}
    require(
        all(math.isfinite(value) and value > 0 for value in values.values()),
        "active graph durations must be finite and positive",
    )
    preds = {node_id: [] for node_id in node_order}
    succs = {node_id: [] for node_id in node_order}
    pair_seen: set[tuple[str, str]] = set()
    for edge in dag["edges"]:
        source, target = str(edge["src"]), str(edge["dst"])
        require(source in preds and target in preds, "graph has dangling edge")
        pair = (source, target)
        if pair in pair_seen:
            continue
        pair_seen.add(pair)
        preds[target].append(source)
        succs[source].append(target)
    for node_id in node_order:
        preds[node_id].sort()
        succs[node_id].sort()
    try:
        topo = topological_order(node_order, preds, succs)
    except ValueError as exc:
        raise AnalysisError(str(exc)) from exc
    return node_order, values, preds, succs, topo


def graph_metrics(
    dag: Mapping[str, Any], durations: Mapping[str, float]
) -> dict[str, Any]:
    node_order, values, preds, succs, topo = _graph_parts(dag, durations)
    work = sum(values.values())
    span, critical_nodes, earliest_start, _ = critical_path(topo, values, preds)
    priority = bottom_levels(topo, values, succs)
    levels: dict[str, int] = {}
    for node_id in topo:
        levels[node_id] = max((levels[parent] for parent in preds[node_id]), default=0) + 1
    output: dict[str, Any] = {
        "W": work,
        "L": span,
        "S_infinity": work / span,
        "critical_path_nodes": critical_nodes,
        "node_count": len(node_order),
        "graph_depth": max(levels.values()),
        "max_ready_width": max(Counter(levels.values()).values()),
        "earliest_start": earliest_start,
        "finite_workers": {},
    }
    for workers in WORKERS:
        relaxed_makespan = max(span, work / workers)
        try:
            list_makespan, _ = list_schedule_makespan(
                node_order, values, preds, succs, priority, workers
            )
        except ValueError as exc:
            raise AnalysisError(str(exc)) from exc
        output["finite_workers"][f"P{workers}"] = {
            "relaxed_lower_bound_makespan": relaxed_makespan,
            "relaxed_ceiling_headroom": work / relaxed_makespan,
            "list_makespan": list_makespan,
            "list_headroom": work / list_makespan,
            "bound_to_list_tightness": relaxed_makespan / list_makespan,
        }
    return output


def type_durations(dag: Mapping[str, Any]) -> dict[str, float]:
    return {
        str(node["node_id"]): float(TYPE_WEIGHTS[str(node["canonical_type"])])
        for node in dag["nodes"]
    }


def duration_blind_mapping_payload(
    annotation: Mapping[str, Any], case_id: str
) -> tuple[list[dict[str, Any]], str]:
    reasons: list[str] = []
    if annotation.get("case_id") != case_id:
        raise AnalysisError(f"{case_id}: duration-blind annotation identity drift")
    if annotation.get("analysis_mode") != "duration_outcome_result_blind":
        reasons.append("duration_blind_annotation_mode_mismatch")
    if annotation.get("candidate_status") not in {
        "ready_for_deterministic_verification",
        "passed_deterministic_verification",
        "passed_independent_audit",
    }:
        reasons.append("duration_blind_annotation_not_ready")
    raw_rows = annotation.get("action_dispositions")
    if not isinstance(raw_rows, list) or not raw_rows:
        reasons.append("duration_blind_action_dispositions_missing")
        raw_rows = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_dispositions = {
        "retain",
        "merge_into_semantic_node",
        "split_across_semantic_nodes",
        "discard_redundant_exploration",
        "discard_tool_noise",
        "move_to_system_envelope",
    }
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            reasons.append("duration_blind_action_disposition_malformed")
            continue
        projected_action_id = str(raw.get("projected_action_id") or "")
        disposition = str(raw.get("disposition") or "")
        semantic_raw = raw.get("semantic_node_ids")
        if (
            not projected_action_id
            or projected_action_id in seen
            or disposition not in allowed_dispositions
            or not isinstance(semantic_raw, list)
            or any(not isinstance(value, str) or not value for value in semantic_raw)
            or len(semantic_raw) != len(set(semantic_raw))
        ):
            reasons.append("duration_blind_action_disposition_invalid")
            continue
        semantic_ids = sorted(semantic_raw)
        if disposition in {"retain", "merge_into_semantic_node"} and len(
            semantic_ids
        ) != 1:
            reasons.append("duration_blind_retained_action_target_invalid")
        if disposition == "split_across_semantic_nodes" and len(semantic_ids) < 2:
            reasons.append("duration_blind_split_action_target_invalid")
        if disposition in {
            "discard_redundant_exploration",
            "discard_tool_noise",
            "move_to_system_envelope",
        } and semantic_ids:
            reasons.append("duration_blind_nonsemantic_action_target_invalid")
        seen.add(projected_action_id)
        rows.append(
            {
                "projected_action_id": projected_action_id,
                "disposition": disposition,
                "semantic_node_ids": semantic_ids,
            }
        )
    if reasons:
        raise EvidenceIneligible(*reasons)
    rows.sort(key=lambda value: value["projected_action_id"])
    return rows, sha256_bytes(canonical_bytes(rows))


def validate_dag_audit(
    case_id: str,
    dag_path: Path,
    dag_raw: Mapping[str, Any],
    verification: Mapping[str, Any],
    audit: Mapping[str, Any],
    expected_raw_trace_sha256: str,
    expected_annotation_sha256: str,
    expected_mapping_sha256: str,
) -> str:
    dag_sha = sha256_file(dag_path)
    reasons: list[str] = []
    if dag_raw.get("case_id") != case_id:
        raise AnalysisError(f"{case_id}: DAG case identity drift")
    if verification.get("case_id") != case_id:
        raise AnalysisError(f"{case_id}: verification case identity drift")
    if audit.get("case_id") != case_id:
        raise AnalysisError(f"{case_id}: audit case identity drift")
    if str(verification.get("status") or "").lower() not in {"pass", "passed"}:
        reasons.append("dag_deterministic_verification_not_passed")
    if str(audit.get("status") or "").lower() not in {"pass", "passed"}:
        reasons.append("dag_independent_audit_not_passed")
    if verification.get("acyclic") is not True:
        reasons.append("dag_acyclic_attestation_missing_or_false")
    if verification.get("leakage_finding_count") != 0:
        reasons.append("dag_leakage_zero_attestation_missing_or_false")
    if audit.get("audit_role") != "independent_p30_trace_reference_dag":
        reasons.append("independent_audit_role_missing_or_invalid")
    if audit.get("auditor_independent_of_annotator") is not True:
        reasons.append("independent_auditor_separation_missing")
    for payload, label in ((verification, "verification"), (audit, "audit")):
        if payload.get("raw_trace_sha256") != expected_raw_trace_sha256:
            reasons.append(f"{label}_raw_trace_digest_missing_or_mismatch")
        if (
            payload.get("duration_blind_annotation_sha256")
            != expected_annotation_sha256
        ):
            reasons.append(
                f"{label}_duration_blind_annotation_digest_missing_or_mismatch"
            )
        if payload.get("duration_blind_mapping_sha256") != expected_mapping_sha256:
            reasons.append(
                f"{label}_duration_blind_mapping_digest_missing_or_mismatch"
            )
        freeze_commit = payload.get("duration_blind_freeze_commit")
        if not isinstance(freeze_commit, str) or COMMIT_RE.fullmatch(
            freeze_commit
        ) is None:
            reasons.append(f"{label}_duration_blind_freeze_commit_missing")
    if (
        verification.get("duration_blind_freeze_commit")
        != audit.get("duration_blind_freeze_commit")
    ):
        reasons.append("duration_blind_freeze_commit_mismatch")
    if (
        dag_raw.get("duration_blind_annotation_sha256")
        != expected_annotation_sha256
    ):
        reasons.append("DAG_duration_blind_annotation_digest_missing_or_mismatch")
    if dag_raw.get("duration_blind_mapping_sha256") != expected_mapping_sha256:
        reasons.append("DAG_duration_blind_mapping_digest_missing_or_mismatch")
    for payload, label in ((verification, "verification"), (audit, "audit")):
        bound = payload.get("effective_reference_dag_sha256")
        if bound != dag_sha:
            reasons.append(f"{label}_effective_DAG_digest_missing_or_mismatch")
    checks = audit.get("checks")
    if not isinstance(checks, Mapping):
        reasons.append("independent_audit_checks_missing")
    else:
        for field in (
            "effective_dag_recomputation",
            "root_seal_and_inventory",
            "verification_to_artifact_binding",
            "mapping_coverage_recomputed",
            "semantic_edge_closure_recomputed",
            "branch_guard_closure_recomputed",
            "leakage_audit_recomputed",
            "duration_blind_annotation_binding",
            "freeze_commit_binding",
        ):
            if checks.get(field) is not True:
                reasons.append(f"independent_audit_check_failed:{field}")
    if reasons:
        raise EvidenceIneligible(*reasons)
    return dag_sha


def _resolve_report_artifact(
    run_report_path: Path, locator: Any, *, label: str
) -> Path:
    if not isinstance(locator, str) or not locator:
        raise EvidenceIneligible(f"missing_{label}_locator")
    value = PurePosixPath(locator)
    if value.is_absolute() or ".." in value.parts or "." in value.parts:
        raise EvidenceIneligible(f"unsafe_{label}_locator")
    root = run_report_path.parent.resolve()
    path = root.joinpath(*value.parts)
    try:
        path = _path_without_symlink(path, root, label=label)
    except AnalysisError as exc:
        raise EvidenceIneligible(f"unsafe_{label}_locator") from exc
    if not path.is_file():
        raise EvidenceIneligible(f"missing_{label}_artifact")
    seal_rows = parse_sha256s(root / "SHA256SUMS")
    normalized = path.relative_to(root).as_posix()
    if normalized not in seal_rows or sha256_file(path) != seal_rows[normalized]:
        raise AnalysisError(f"{label}: referenced trace is not bound by run-root seal")
    return path


def _resolve_run_trace_bindings(report: Mapping[str, Any]) -> dict[str, Any]:
    report_path = Path(str(report["_run_report_path"]))
    target = report.get("target")
    if not isinstance(target, Mapping):
        raise EvidenceIneligible("target_trace_locators_missing")
    raw_path = _resolve_report_artifact(
        report_path,
        target.get("raw_trace_path"),
        label="raw_trace_path",
    )
    timestamped_path = _resolve_report_artifact(
        report_path,
        target.get("timestamped_trace_path"),
        label="timestamped_trace_path",
    )
    receipt_path = _resolve_report_artifact(
        report_path,
        target.get("stream_receipt_path"),
        label="stream_receipt_path",
    )
    return {
        "raw_trace_path": raw_path,
        "raw_trace_sha256": sha256_file(raw_path),
        "timestamped_trace_path": timestamped_path,
        "timestamped_trace_sha256": sha256_file(timestamped_path),
        "stream_receipt_path": receipt_path,
        "stream_receipt_sha256": sha256_file(receipt_path),
    }


def validate_run_identity(
    report: Mapping[str, Any],
    frozen: Mapping[str, Any],
    index_row: Mapping[str, Any],
) -> None:
    expected = {
        "schema_version": RUN_REPORT_SCHEMA_VERSION,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "position": frozen["position"],
        "case_id": frozen["case_id"],
        "instance_id": frozen["instance_id"],
        "repository": frozen["physical_repository"],
        "base_commit": frozen["base_commit"],
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
        "target_model": TARGET_MODEL,
        "reasoning_effort": REASONING_EFFORT,
    }
    if index_row.get("_collection_plan_sha256") is not None:
        expected.update(
            {
                "run_id": index_row.get("run_id"),
                "collection_plan_sha256": index_row.get(
                    "_collection_plan_sha256"
                ),
                "collection_plan_case_binding_sha256": index_row.get(
                    "_collection_plan_case_binding_sha256"
                ),
                "authorization_sha256": index_row.get(
                    "authorization_sha256"
                ),
                "canonical_result_root": index_row.get(
                    "_plan_result_root"
                ),
            }
        )
    for field, value in expected.items():
        require(
            report.get(field) == value,
            f"{frozen['case_id']}: run-report identity drift: {field}",
        )
    counters = report.get("counters")
    require(isinstance(counters, Mapping), f"{frozen['case_id']}: run counters missing")
    for field in (
        "benchmark_target_invocations",
        "provider_model_invocations",
        "official_evaluator_invocations",
    ):
        require(
            type(counters.get(field)) is int and counters[field] in (0, 1),
            f"{frozen['case_id']}: invalid invocation counter {field}",
        )
    for field, label in (
        ("retry_count", "retry"),
        ("substitution_count", "substitution"),
        ("task_originated_network_calls", "task network"),
    ):
        require(
            type(counters.get(field)) is int and counters[field] == 0,
            f"{frozen['case_id']}: {label} used or counter missing",
        )


def validate_run_authorization(
    authorization: Mapping[str, Any],
    frozen: Mapping[str, Any],
    index_row: Mapping[str, Any],
) -> str:
    authorization_sha256 = sha256_bytes(canonical_bytes(authorization))
    require(
        set(authorization) == AUTHORIZATION_KEYS,
        f"{frozen['case_id']}: authorization receipt field closure mismatch",
    )
    expected = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "status": "approved",
        "explicit_user_approval": True,
        "execution_authorized": True,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
        "position": frozen["position"],
        "case_id": frozen["case_id"],
        "instance_id": frozen["instance_id"],
        "run_id": index_row.get("run_id"),
        "dataset_arrow_sha256": DATASET_ARROW_SHA256,
        "codex_cli_version": FROZEN_CODEX_CLI_VERSION,
        "target_model": TARGET_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "task_tool_network_policy": (
            "codex_named_permissions_network_disabled"
        ),
        "official_evaluator_network_mode": "none",
        "otel_provider_spans_required": True,
        "bundled_model_catalog_required": True,
        "retry_count": 0,
        "substitution_count": 0,
        "task_originated_network_calls_maximum": 0,
        "benchmark_target_invocations_maximum": 1,
        "provider_model_invocations_maximum": 1,
        "official_evaluator_invocations_maximum": 1,
    }
    for field, value in expected.items():
        actual = authorization.get(field)
        require(
            type(actual) is type(value) and actual == value,
            f"{frozen['case_id']}: authorization identity drift: {field}",
        )
    require(
        RUN_ID_RE.fullmatch(str(authorization["run_id"])) is not None,
        f"{frozen['case_id']}: unsafe authorization run_id",
    )
    for field in (
        "preflight_report_sha256",
        "prepared_packet_sha256",
        "codex_linux_binary_sha256",
        "codex_linux_runtime_manifest_sha256",
        "target_container_security_contract_sha256",
    ):
        require(
            isinstance(authorization.get(field), str)
            and SHA256_RE.fullmatch(authorization[field]) is not None,
            f"{frozen['case_id']}: authorization identity malformed: {field}",
        )
    for field in (
        "docker_image_key",
        "docker_image_id",
        "docker_image_repo_digest",
    ):
        require(
            isinstance(authorization.get(field), str)
            and bool(authorization[field]),
            f"{frozen['case_id']}: authorization identity malformed: {field}",
        )
    require(
        authorization_sha256 == index_row.get("authorization_sha256"),
        f"{frozen['case_id']}: authorization canonical digest drift",
    )
    require(
        index_row.get("authorization_canonical_path")
        == index_row.get("_plan_authorization_path"),
        f"{frozen['case_id']}: authorization canonical locator drift",
    )
    return authorization_sha256


def _run_scientific_observation_errors(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    counters = report.get("counters")
    if not isinstance(counters, Mapping):
        return ["run_counters_missing"]
    for field in (
        "benchmark_target_invocations",
        "provider_model_invocations",
        "official_evaluator_invocations",
    ):
        if counters.get(field) != 1:
            errors.append(f"non_exact_{field}")
    scientific_expected = {
        "scientific_result": True,
        "synthetic_or_fixture_result": False,
        "fresh_trace_observation_scientific_eligible": True,
        "scientific_result_role": (
            "fresh_trace_observation_only_not_final_A_or_C_primary"
        ),
        "scientific_role": "fresh_trace_observation_source_only",
        "downstream_evidence_role": (
            "trace_source_pending_case_specific_DAG_audit"
        ),
        "downstream_dag_audited": False,
        "final_A_primary_result": False,
        "final_C_primary_result": False,
        "primary_cohort_result_eligible": False,
    }
    for field, value in scientific_expected.items():
        if report.get(field) != value:
            errors.append(f"run_scientific_role_drift:{field}")
    return errors


def _phase_category(name: str) -> str | None:
    exact = {
        "model_decision_explicit_provider_api": "model_decision",
        "real_action": "real_action_excluding_build_test",
        "build_test": "build_test",
        "explicit_wait": "explicit_wait",
        "concurrent_tool_activity": "measured_residual",
        "provider_tool_overlap_or_timestamp_uncertainty": (
            "measured_residual"
        ),
        "codex_process_unclassified_residual": "measured_residual",
        "measured_residual": "measured_residual",
        "overlap_contaminated_observed_activity_ineligible": None,
        "environment_packet_materialization": (
            "integration_finalization_and_official_evaluator"
        ),
        "target_finalization_integration": (
            "integration_finalization_and_official_evaluator"
        ),
        "pre_evaluator_handoff": (
            "integration_finalization_and_official_evaluator"
        ),
        "official_evaluator": "integration_finalization_and_official_evaluator",
        "terminal_recording_and_seal_residual": (
            "integration_finalization_and_official_evaluator"
        ),
    }
    if name in exact:
        return exact[name]
    if name in {
        "imputed_duration",
        "imputed_duration_seconds",
        "uncovered_duration",
        "uncovered_duration_seconds",
    }:
        return None
    return "__unknown__"


def _provider_evidence_errors(provider: Any) -> list[str]:
    if not isinstance(provider, Mapping):
        return ["missing_explicit_provider_span"]
    errors: list[str] = []
    requests = provider.get("api_requests")
    declared_count = provider.get("api_request_count")
    if (
        not isinstance(declared_count, int)
        or isinstance(declared_count, bool)
        or declared_count < 1
    ):
        errors.append("missing_explicit_provider_span")
    if not isinstance(requests, list) or not requests:
        errors.append("missing_explicit_provider_request_rows")
        requests = []
    elif declared_count != len(requests):
        errors.append("provider_request_count_mismatch")
    if provider.get("expected_attempt_value") != 0:
        errors.append("provider_expected_attempt_drift")
    if provider.get("expected_model") != TARGET_MODEL:
        errors.append("provider_expected_model_drift")
    if provider.get("errors") not in (None, []):
        errors.append("provider_reported_otel_error")
    summed_duration = 0.0
    for ordinal, request in enumerate(requests, 1):
        prefix = f"provider_request_{ordinal}"
        if not isinstance(request, Mapping):
            errors.append(f"{prefix}_malformed")
            continue
        if request.get("attempt") != 0:
            errors.append(f"{prefix}_attempt_not_zero")
        if request.get("model") != TARGET_MODEL:
            errors.append(f"{prefix}_model_mismatch")
        status = request.get("status")
        if (
            not isinstance(status, int)
            or isinstance(status, bool)
            or not 200 <= status <= 299
        ):
            errors.append(f"{prefix}_status_not_2xx")
        if request.get("success") is not True:
            errors.append(f"{prefix}_not_successful")
        if request.get("error_message") not in (None, ""):
            errors.append(f"{prefix}_has_error")
        retry_value = request.get("auth_retry_after_unauthorized")
        if retry_value not in (None, False, 0, "", "false", "False"):
            errors.append(f"{prefix}_auth_retry")
        duration = request.get("duration_seconds")
        start_epoch = request.get("start_epoch")
        end_epoch = request.get("end_epoch")
        start_monotonic = request.get("start_monotonic")
        end_monotonic = request.get("end_monotonic")
        if not _finite(duration) or float(duration) <= 0:
            errors.append(f"{prefix}_duration_invalid")
            continue
        summed_duration += float(duration)
        for label, start, end in (
            ("epoch", start_epoch, end_epoch),
            ("monotonic", start_monotonic, end_monotonic),
        ):
            if not _finite(start) or not _finite(end) or float(end) <= float(start):
                errors.append(f"{prefix}_{label}_interval_invalid")
            elif not math.isclose(
                float(end) - float(start),
                float(duration),
                rel_tol=1e-6,
                abs_tol=1e-6,
            ):
                errors.append(f"{prefix}_{label}_duration_mismatch")
    declared_duration = provider.get("provider_model_decision_seconds")
    if (
        not _finite(declared_duration)
        or not math.isclose(
            float(declared_duration),
            summed_duration,
            rel_tol=1e-6,
            abs_tol=1e-6,
        )
    ):
        errors.append("provider_duration_sum_mismatch")
    return errors


def _close_seconds(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
    return (
        _finite(left)
        and _finite(right)
        and math.isclose(
            float(left),
            float(right),
            rel_tol=1e-8,
            abs_tol=tolerance,
        )
    )


_EXCLUSIVE_ACTIVITY_BUCKETS = (
    "model_decision_explicit_provider_api",
    "real_action",
    "build_test",
    "explicit_wait",
    "concurrent_tool_activity",
    "provider_tool_overlap_or_timestamp_uncertainty",
)
_ACTIVITY_PARTITION_POLICY = (
    "single-category activity retains its category; concurrent tools "
    "and provider-tool overlap receive explicit exclusive buckets"
)


def _interval_overlap_seconds(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> float:
    return max(
        0.0,
        min(float(left["end_monotonic"]), float(right["end_monotonic"]))
        - max(
            float(left["start_monotonic"]),
            float(right["start_monotonic"]),
        ),
    )


def _exclusive_activity_partition(
    provider_intervals: Sequence[Mapping[str, Any]],
    tool_intervals: Sequence[Mapping[str, Any]],
    *,
    lower: float,
    upper: float,
) -> dict[str, Any]:
    """Independently reconstruct the runner's exclusive wall-time partition."""

    rows: list[dict[str, Any]] = []
    for interval in provider_intervals:
        rows.append(
            {
                "kind": "provider",
                "category": _EXCLUSIVE_ACTIVITY_BUCKETS[0],
                "start": max(lower, float(interval["start_monotonic"])),
                "end": min(upper, float(interval["end_monotonic"])),
            }
        )
    for interval in tool_intervals:
        rows.append(
            {
                "kind": "tool",
                "category": str(interval["category"]),
                "start": max(lower, float(interval["start_monotonic"])),
                "end": min(upper, float(interval["end_monotonic"])),
            }
        )
    rows = [row for row in rows if row["end"] > row["start"]]
    boundaries = sorted(
        {
            value
            for row in rows
            for value in (float(row["start"]), float(row["end"]))
        }
    )
    partitioned = {
        category: 0.0 for category in _EXCLUSIVE_ACTIVITY_BUCKETS
    }
    activity_state_seconds: defaultdict[str, float] = defaultdict(float)
    tool_concurrency_histogram_seconds: defaultdict[str, float] = defaultdict(
        float
    )
    classified_union_seconds = 0.0
    tool_wall_union_seconds = 0.0
    parallel_tool_wall_seconds = 0.0
    peak_tool_concurrency = 0
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        active = [
            row
            for row in rows
            if float(row["start"]) < end and float(row["end"]) > start
        ]
        if not active:
            continue
        duration = end - start
        active_categories = sorted(
            {str(row["category"]) for row in active}
        )
        classified_union_seconds += duration
        provider_count = sum(row["kind"] == "provider" for row in active)
        tool_count = sum(row["kind"] == "tool" for row in active)
        if tool_count:
            tool_wall_union_seconds += duration
        if tool_count > 1:
            parallel_tool_wall_seconds += duration
        peak_tool_concurrency = max(peak_tool_concurrency, tool_count)
        tool_concurrency_histogram_seconds[str(tool_count)] += duration
        activity_state_seconds["+".join(active_categories)] += duration
        if provider_count and tool_count:
            bucket = "provider_tool_overlap_or_timestamp_uncertainty"
        elif provider_count:
            bucket = "model_decision_explicit_provider_api"
        elif tool_count > 1:
            bucket = "concurrent_tool_activity"
        elif tool_count == 1:
            bucket = next(
                str(row["category"])
                for row in active
                if row["kind"] == "tool"
            )
        else:
            continue
        partitioned[bucket] += duration
    tool_work_seconds = sum(
        max(
            0.0,
            min(upper, float(row["end_monotonic"]))
            - max(lower, float(row["start_monotonic"])),
        )
        for row in tool_intervals
    )
    return {
        "wall_seconds_by_exclusive_bucket": partitioned,
        "classified_union_seconds": classified_union_seconds,
        "activity_state_seconds": dict(sorted(activity_state_seconds.items())),
        "partition_policy": _ACTIVITY_PARTITION_POLICY,
        "tool_work_seconds": tool_work_seconds,
        "tool_wall_union_seconds": tool_wall_union_seconds,
        "parallel_tool_wall_seconds": parallel_tool_wall_seconds,
        "peak_tool_concurrency": peak_tool_concurrency,
        "tool_concurrency_histogram_seconds": dict(
            sorted(tool_concurrency_histogram_seconds.items())
        ),
        "tool_work_to_wall_union_ratio": (
            tool_work_seconds / tool_wall_union_seconds
            if tool_wall_union_seconds > 0
            else None
        ),
    }


def _compare_numeric_mapping(
    actual: Any,
    expected: Mapping[str, float],
    *,
    label: str,
) -> list[str]:
    if not isinstance(actual, Mapping):
        return [f"{label}_missing"]
    errors: list[str] = []
    if set(actual) != set(expected):
        errors.append(f"{label}_field_set_mismatch")
    for field, expected_value in expected.items():
        if not _close_seconds(actual.get(field), expected_value):
            errors.append(f"{label}_mismatch:{field}")
    return errors


def _activity_partition_errors(
    actual: Any,
    expected: Mapping[str, Any],
) -> list[str]:
    if not isinstance(actual, Mapping):
        return ["telemetry_activity_partition_missing"]
    errors: list[str] = []
    if set(actual) != set(expected):
        errors.append("telemetry_activity_partition_field_set_mismatch")
    for field in (
        "classified_union_seconds",
        "tool_work_seconds",
        "tool_wall_union_seconds",
        "parallel_tool_wall_seconds",
    ):
        if not _close_seconds(actual.get(field), expected[field]):
            errors.append(f"telemetry_activity_partition_mismatch:{field}")
    for field in (
        "wall_seconds_by_exclusive_bucket",
        "activity_state_seconds",
        "tool_concurrency_histogram_seconds",
    ):
        errors.extend(
            _compare_numeric_mapping(
                actual.get(field),
                expected[field],
                label=f"telemetry_activity_partition:{field}",
            )
        )
    if actual.get("partition_policy") != expected["partition_policy"]:
        errors.append(
            "telemetry_activity_partition_mismatch:partition_policy"
        )
    peak = actual.get("peak_tool_concurrency")
    if (
        not isinstance(peak, int)
        or isinstance(peak, bool)
        or peak != expected["peak_tool_concurrency"]
    ):
        errors.append(
            "telemetry_activity_partition_mismatch:peak_tool_concurrency"
        )
    expected_ratio = expected["tool_work_to_wall_union_ratio"]
    actual_ratio = actual.get("tool_work_to_wall_union_ratio")
    if expected_ratio is None:
        if actual_ratio is not None:
            errors.append(
                "telemetry_activity_partition_mismatch:"
                "tool_work_to_wall_union_ratio"
            )
    elif not _close_seconds(actual_ratio, expected_ratio):
        errors.append(
            "telemetry_activity_partition_mismatch:"
            "tool_work_to_wall_union_ratio"
        )
    return errors


def _phase_recomputation(
    report: Mapping[str, Any],
    time_row: Mapping[str, Any],
    telemetry: Mapping[str, Any],
) -> tuple[dict[str, float], float, list[str]]:
    errors: list[str] = []
    provider = telemetry.get("provider")
    provider_rows = (
        provider.get("api_requests")
        if isinstance(provider, Mapping)
        else None
    )
    if not isinstance(provider_rows, list):
        provider_rows = []
    tool_rows = telemetry.get("tool_intervals")
    if not isinstance(tool_rows, list) or not tool_rows:
        errors.append("telemetry_tool_intervals_missing")
        tool_rows = []
    provider_intervals: list[dict[str, Any]] = []
    provider_seconds = 0.0
    for ordinal, raw in enumerate(provider_rows, 1):
        if not isinstance(raw, Mapping):
            errors.append(f"provider_interval_{ordinal}_malformed")
            continue
        start = raw.get("start_monotonic")
        end = raw.get("end_monotonic")
        duration = raw.get("duration_seconds")
        if (
            not _finite(start)
            or not _finite(end)
            or float(end) <= float(start)
            or not _close_seconds(float(end) - float(start), duration)
        ):
            errors.append(f"provider_interval_{ordinal}_invalid")
            continue
        provider_seconds += float(duration)
        provider_intervals.append(
            {
                "start_monotonic": float(start),
                "end_monotonic": float(end),
                "duration_seconds": float(duration),
            }
        )
    tool_work_seconds = {
        "real_action": 0.0,
        "build_test": 0.0,
        "explicit_wait": 0.0,
    }
    tool_intervals: list[dict[str, Any]] = []
    seen_tool_ids: set[str] = set()
    for ordinal, raw in enumerate(tool_rows, 1):
        if not isinstance(raw, Mapping):
            errors.append(f"tool_interval_{ordinal}_malformed")
            continue
        item_id = str(raw.get("item_id") or "")
        category = str(raw.get("category") or "")
        start = raw.get("start_monotonic")
        end = raw.get("end_monotonic")
        duration = raw.get("duration_seconds")
        if not item_id or item_id in seen_tool_ids:
            errors.append("telemetry_tool_interval_identity_invalid")
        seen_tool_ids.add(item_id)
        if category not in tool_work_seconds:
            errors.append(f"telemetry_tool_interval_category_invalid:{category}")
            continue
        if (
            not _finite(start)
            or not _finite(end)
            or float(end) <= float(start)
            or not _close_seconds(float(end) - float(start), duration)
        ):
            errors.append(f"tool_interval_{ordinal}_invalid")
            continue
        tool_work_seconds[category] += float(duration)
        tool_intervals.append(
            {
                "category": category,
                "start_monotonic": float(start),
                "end_monotonic": float(end),
                "duration_seconds": float(duration),
            }
        )
    boundaries = telemetry.get("boundaries")
    if not isinstance(boundaries, Mapping):
        errors.append("target_boundary_ledger_missing")
        boundaries = {}
    try:
        process_start = float(
            boundaries["provider_process_start"]["monotonic"]
        )
        process_end = float(boundaries["provider_process_end"]["monotonic"])
        patch_end = float(boundaries["patch_finalized"]["monotonic"])
    except (KeyError, TypeError, ValueError):
        errors.append("target_phase_boundaries_incomplete")
        process_start = process_end = patch_end = 0.0
    process_seconds = process_end - process_start
    if process_seconds <= 0:
        errors.append("target_process_interval_invalid")
        process_seconds = 0.0
    activity_partition = _exclusive_activity_partition(
        provider_intervals,
        tool_intervals,
        lower=process_start,
        upper=process_end,
    )
    partitioned = activity_partition["wall_seconds_by_exclusive_bucket"]
    classified_union_seconds = float(
        activity_partition["classified_union_seconds"]
    )
    residual = process_seconds - classified_union_seconds
    if residual < -0.001:
        errors.append("recomputed_negative_process_residual")
    residual = max(0.0, residual)
    if not _close_seconds(telemetry.get("codex_process_seconds"), process_seconds):
        errors.append("telemetry_codex_process_seconds_mismatch")
    errors.extend(
        _activity_partition_errors(
            telemetry.get("activity_partition"),
            activity_partition,
        )
    )
    errors.extend(
        _compare_numeric_mapping(
            telemetry.get("work_seconds"),
            {
                "model_decision_explicit_provider_api": provider_seconds,
                **tool_work_seconds,
            },
            label="telemetry_work_seconds",
        )
    )
    tool_tool_overlap = sum(
        _interval_overlap_seconds(left, right)
        for ordinal, left in enumerate(tool_intervals)
        for right in tool_intervals[ordinal + 1 :]
    )
    provider_provider_overlap = sum(
        _interval_overlap_seconds(left, right)
        for ordinal, left in enumerate(provider_intervals)
        for right in provider_intervals[ordinal + 1 :]
    )
    provider_tool_overlap = sum(
        _interval_overlap_seconds(provider_interval, tool_interval)
        for provider_interval in provider_intervals
        for tool_interval in tool_intervals
    )
    for field, expected_value in (
        ("tool_tool_overlap_seconds", tool_tool_overlap),
        ("provider_provider_overlap_seconds", provider_provider_overlap),
        ("provider_tool_overlap_seconds", provider_tool_overlap),
    ):
        if not _close_seconds(telemetry.get(field), expected_value):
            errors.append(f"telemetry_overlap_mismatch:{field}")
    if provider_provider_overlap > 0.001:
        errors.append("recomputed_provider_provider_overlap")
    for field in (
        "raw_tool_concurrency_allowed",
        "phase_bucket_partition_non_overlapping",
        "non_overlapping_phase_contract",
    ):
        if telemetry.get(field) is not True:
            errors.append(f"telemetry_partition_contract_drift:{field}")
    conservation_error = process_seconds - (
        classified_union_seconds + residual
    )
    if not _close_seconds(
        telemetry.get("codex_process_conservation_error_seconds"),
        conservation_error,
    ):
        errors.append("telemetry_process_conservation_mismatch")
    telemetry_buckets = telemetry.get("phase_buckets_seconds")
    expected_telemetry = {
        **partitioned,
        "overlap_contaminated_observed_activity_ineligible": 0.0,
        "codex_process_unclassified_residual": residual,
    }
    if not isinstance(telemetry_buckets, Mapping):
        errors.append("telemetry_phase_buckets_missing")
    else:
        if set(telemetry_buckets) != set(expected_telemetry):
            errors.append("telemetry_phase_bucket_field_set_mismatch")
        for field, expected in expected_telemetry.items():
            if not _close_seconds(telemetry_buckets.get(field), expected):
                errors.append(f"telemetry_phase_bucket_mismatch:{field}")
    canonical = time_row.get("canonical_boundaries")
    if not isinstance(canonical, Mapping):
        errors.append("canonical_phase_boundaries_missing")
        canonical = {}
    boundary_names = (
        "task_arrival",
        "task_dispatch",
        "artifact_ready",
        "evaluator_start",
        "evaluator_end",
        "task_terminal",
    )
    monotonic: dict[str, float] = {}
    for name in boundary_names:
        value = canonical.get(name)
        raw = (
            value.get("monotonic_seconds")
            if isinstance(value, Mapping)
            else None
        )
        if not _finite(raw):
            errors.append(f"canonical_phase_boundary_invalid:{name}")
        else:
            monotonic[name] = float(raw)
    if len(monotonic) == len(boundary_names):
        ordered = [monotonic[name] for name in boundary_names]
        if ordered != sorted(ordered):
            errors.append("canonical_phase_boundary_order_invalid")
        if not _close_seconds(monotonic["task_dispatch"], process_start):
            errors.append("canonical_task_dispatch_target_mismatch")
        if not _close_seconds(monotonic["artifact_ready"], patch_end):
            errors.append("canonical_artifact_ready_target_mismatch")
    else:
        monotonic = {name: 0.0 for name in boundary_names}
    evaluator = report.get("official_evaluator")
    evaluator_boundaries = (
        evaluator.get("boundaries")
        if isinstance(evaluator, Mapping)
        else None
    )
    if not isinstance(evaluator_boundaries, Mapping):
        errors.append("official_evaluator_boundary_ledger_missing")
    else:
        for source, destination in (
            ("official_evaluator_start", "evaluator_start"),
            ("official_evaluator_end", "evaluator_end"),
        ):
            value = evaluator_boundaries.get(source)
            raw = value.get("monotonic") if isinstance(value, Mapping) else None
            if not _finite(raw) or not _close_seconds(
                raw, monotonic[destination]
            ):
                errors.append(f"official_evaluator_boundary_mismatch:{source}")
    expected = {
        "environment_packet_materialization": max(
            0.0, monotonic["task_dispatch"] - monotonic["task_arrival"]
        ),
        **partitioned,
        "codex_process_unclassified_residual": residual,
        "overlap_contaminated_observed_activity_ineligible": 0.0,
        "target_finalization_integration": max(
            0.0, monotonic["artifact_ready"] - process_end
        ),
        "pre_evaluator_handoff": max(
            0.0,
            monotonic["evaluator_start"] - monotonic["artifact_ready"],
        ),
        "official_evaluator": max(
            0.0, monotonic["evaluator_end"] - monotonic["evaluator_start"]
        ),
        "terminal_recording_and_seal_residual": max(
            0.0, monotonic["task_terminal"] - monotonic["evaluator_end"]
        ),
    }
    e2e = max(
        0.0, monotonic["task_terminal"] - monotonic["task_arrival"]
    )
    reported_buckets = time_row.get("phase_buckets_seconds")
    if not isinstance(reported_buckets, Mapping):
        errors.append("phase_buckets_missing")
    else:
        if set(reported_buckets) != set(expected):
            errors.append("phase_bucket_field_set_mismatch")
        for field, expected_seconds in expected.items():
            if not _close_seconds(
                reported_buckets.get(field), expected_seconds
            ):
                errors.append(f"phase_bucket_recomputation_mismatch:{field}")
    for locator, value in (
        ("time_composition", time_row.get("operational_e2e_seconds")),
        ("run_report", report.get("operational_e2e_seconds")),
    ):
        if not _close_seconds(value, e2e):
            errors.append(f"operational_e2e_recomputation_mismatch:{locator}")
    if patch_end < process_end - 1e-6:
        errors.append("patch_finalized_before_provider_process_end")
    return expected, e2e, errors


def _raw_trace_lines(path: Path) -> list[bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceIneligible("raw_trace_unreadable") from exc
    if not raw:
        return []
    rows = raw.split(b"\n")
    if raw.endswith(b"\n"):
        rows.pop()
    return rows


def _timestamp_receipt_evidence(
    path: Path,
    raw_path: Path,
    stream_receipt_path: Path,
) -> dict[str, Any]:
    receipt_times: list[float] = []
    event_count = 0
    action_starts: dict[str, float] = {}
    action_completions: dict[str, float] = {}
    raw_lines = _raw_trace_lines(raw_path)
    raw_ends_with_newline = raw_path.read_bytes().endswith(b"\n")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceIneligible("timestamped_trace_unreadable") from exc
    if any(not line.strip() for line in lines):
        raise EvidenceIneligible("timestamped_trace_blank_line")
    if len(lines) != len(raw_lines):
        raise EvidenceIneligible("raw_timestamped_trace_line_count_mismatch")
    try:
        receipt_lines = stream_receipt_path.read_text(
            encoding="utf-8"
        ).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceIneligible("stream_receipt_unreadable") from exc
    if (
        any(not line.strip() for line in receipt_lines)
        or len(receipt_lines) != len(raw_lines)
    ):
        raise EvidenceIneligible("stream_receipt_line_count_mismatch")
    for sequence, (line, raw_line, receipt_line) in enumerate(
        zip(lines, raw_lines, receipt_lines)
    ):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceIneligible("timestamped_trace_malformed_json") from exc
        if not isinstance(row, Mapping):
            raise EvidenceIneligible("timestamped_trace_non_object_event")
        try:
            receipt = json.loads(receipt_line)
        except json.JSONDecodeError as exc:
            raise EvidenceIneligible("stream_receipt_malformed_json") from exc
        if not isinstance(receipt, Mapping):
            raise EvidenceIneligible("stream_receipt_non_object")
        raw_sha = sha256_bytes(raw_line)
        raw_bytes = len(raw_line)
        expected_identity = {
            "runner_receipt_sequence": sequence,
            "runner_raw_line_sha256": raw_sha,
            "runner_raw_line_bytes": raw_bytes,
            "line_sha256": raw_sha,
            "byte_length": raw_bytes,
        }
        for field, expected in expected_identity.items():
            if row.get(field) != expected or isinstance(row.get(field), bool):
                raise EvidenceIneligible(
                    f"timestamped_trace_raw_line_binding_mismatch:{field}"
                )
        receipt_identity = {
            "sequence": sequence,
            "raw_line_sha256": raw_sha,
            "raw_line_bytes": raw_bytes,
            "line_sha256": raw_sha,
            "byte_length": raw_bytes,
        }
        for field, expected in receipt_identity.items():
            if receipt.get(field) != expected or isinstance(
                receipt.get(field), bool
            ):
                raise EvidenceIneligible(
                    f"stream_receipt_raw_line_binding_mismatch:{field}"
                )
        expected_terminated = (
            sequence < len(raw_lines) - 1 or raw_ends_with_newline
        )
        if receipt.get("newline_terminated") is not expected_terminated:
            raise EvidenceIneligible(
                "stream_receipt_newline_termination_mismatch"
            )
        for field in ("received_wall_ns", "received_monotonic_ns"):
            if (
                type(row.get(field)) is not int
                or type(receipt.get(field)) is not int
                or row[field] != receipt[field]
            ):
                raise EvidenceIneligible(
                    f"stream_receipt_clock_binding_mismatch:{field}"
                )
        observed = row.get("runner_observed_monotonic_seconds")
        if not _finite(observed):
            raise EvidenceIneligible("timestamped_trace_missing_monotonic_receipt")
        expected_monotonic = row["received_monotonic_ns"] / 1_000_000_000
        expected_wall = row["received_wall_ns"] / 1_000_000_000
        for value, expected, label in (
            (observed, expected_monotonic, "timestamped_monotonic"),
            (
                row.get("runner_observed_at_epoch"),
                expected_wall,
                "timestamped_wall",
            ),
            (
                receipt.get("observed_monotonic_seconds"),
                expected_monotonic,
                "receipt_monotonic",
            ),
            (receipt.get("observed_at"), expected_wall, "receipt_wall"),
        ):
            if not _finite(value) or not math.isclose(
                float(value), expected, rel_tol=0.0, abs_tol=1e-9
            ):
                raise EvidenceIneligible(
                    f"stream_receipt_clock_binding_mismatch:{label}"
                )
        receipt_times.append(float(observed))
        event_count += 1
        item = row.get("item")
        event_type = row.get("type")
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            continue
        action_id = str(item["id"])
        item_type = str(item.get("type") or "")
        if (
            event_type == "item.started"
            and item_type not in {"agent_message", "reasoning"}
        ):
            if action_id in action_starts or action_id in action_completions:
                raise EvidenceIneligible("timestamped_trace_duplicate_action_start")
            action_starts[action_id] = float(observed)
        elif (
            event_type == "item.completed"
            and item_type not in {"agent_message", "reasoning"}
        ):
            if action_id not in action_starts or action_id in action_completions:
                raise EvidenceIneligible(
                    "timestamped_trace_unmatched_or_duplicate_action_completion"
                )
            action_completions[action_id] = float(observed)
    if receipt_times != sorted(receipt_times):
        raise EvidenceIneligible("timestamped_trace_receipts_not_monotonic")
    if len(set(receipt_times)) < 2:
        raise EvidenceIneligible("collapsed_timestamp_receipts")
    if set(action_starts) != set(action_completions):
        raise EvidenceIneligible("timestamped_trace_incomplete_action_lifecycle")
    if not action_completions:
        raise EvidenceIneligible("timestamped_trace_has_no_observed_actions")
    action_ids = sorted(action_completions)
    action_intervals = {
        action_id: {
            "start_monotonic_seconds": action_starts[action_id],
            "end_monotonic_seconds": action_completions[action_id],
            "duration_seconds": (
                action_completions[action_id] - action_starts[action_id]
            ),
        }
        for action_id in action_ids
    }
    if any(
        interval["duration_seconds"] <= 0
        for interval in action_intervals.values()
    ):
        raise EvidenceIneligible("timestamped_trace_nonpositive_action_duration")
    return {
        "event_count": event_count,
        "distinct_receipt_timestamp_count": len(set(receipt_times)),
        "observed_action_ids": action_ids,
        "observed_action_count": len(action_ids),
        "observed_action_set_sha256": sha256_bytes(canonical_bytes(action_ids)),
        "observed_action_intervals": action_intervals,
        "observed_action_duration_sum_seconds": sum(
            interval["duration_seconds"]
            for interval in action_intervals.values()
        ),
    }


def extract_phase_composition(
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    reasons: list[str] = _run_scientific_observation_errors(report)
    if report.get("terminal_state") != "completed_target_and_official_evaluator":
        reasons.append("target_or_official_evaluator_incomplete")
    time_row = report.get("time_composition")
    if not isinstance(time_row, Mapping):
        raise EvidenceIneligible("missing_time_composition")
    if time_row.get("A_phase_composition_eligible") is not True:
        reasons.extend(
            f"time:{value}"
            for value in time_row.get("eligibility_errors") or [
                "producer_phase_ineligible"
            ]
        )
    if time_row.get("non_overlapping_phase_contract") is not True:
        reasons.append("phase_partition_not_declared_nonoverlapping")
    if time_row.get("model_decision_derived_from_residual") is not False:
        reasons.append("model_decision_not_explicit")
    telemetry = ((report.get("target") or {}).get("telemetry_evidence") or {})
    if not isinstance(telemetry, Mapping):
        reasons.append("target_telemetry_missing")
        telemetry = {}
    if telemetry.get("eligible") is not True:
        reasons.extend(
            f"telemetry:{value}"
            for value in telemetry.get("eligibility_errors") or [
                "target_telemetry_ineligible"
            ]
        )
    if int(telemetry.get("distinct_receipt_timestamp_count") or 0) < 2:
        reasons.append("collapsed_timestamp_receipts")
    reasons.extend(_provider_evidence_errors(telemetry.get("provider")))
    raw_buckets, e2e, recomputation_errors = _phase_recomputation(
        report,
        time_row,
        telemetry,
    )
    reasons.extend(recomputation_errors)
    canonical = {
        "model_decision": 0.0,
        "real_action_excluding_build_test": 0.0,
        "build_test": 0.0,
        "explicit_wait": 0.0,
        "integration_finalization_and_official_evaluator": 0.0,
        "measured_residual": 0.0,
    }
    forbidden_unmeasured = 0.0
    for name, raw_value in raw_buckets.items():
        if not _nonnegative(raw_value):
            reasons.append(f"invalid_phase_bucket:{name}")
            continue
        category = _phase_category(str(name))
        if category is None:
            forbidden_unmeasured += float(raw_value)
        elif category not in canonical:
            reasons.append(f"unknown_phase_bucket:{name}")
        else:
            canonical[category] += float(raw_value)
    for field in (
        "unclassified_conservation_error_seconds",
        "imputed_duration_seconds",
        "uncovered_duration_seconds",
    ):
        if field not in time_row:
            reasons.append(f"missing_explicit_{field}")
            continue
        value = time_row[field]
        if not _finite(value) or abs(float(value)) > 1e-9:
            reasons.append(f"nonzero_or_invalid_{field}")
    if forbidden_unmeasured > 1e-9:
        reasons.append("nonzero_imputed_or_uncovered_phase_duration")
    if not _finite(e2e) or float(e2e) <= 0:
        reasons.append("invalid_operational_e2e")
        e2e = 0.0
    delta = float(e2e) - sum(canonical.values())
    if abs(delta) > max(1e-6, 1e-8 * float(e2e)):
        reasons.append("phase_conservation_failure")
    if reasons:
        raise EvidenceIneligible(*reasons)
    source_candidates: list[Path] = []
    target = report.get("target") or {}
    timestamped_path = _resolve_report_artifact(
        Path(str(report["_run_report_path"])),
        target.get("timestamped_trace_path"),
        label="timestamped_trace_path",
    )
    raw_path = _resolve_report_artifact(
        Path(str(report["_run_report_path"])),
        target.get("raw_trace_path"),
        label="raw_trace_path",
    )
    stream_receipt_path = _resolve_report_artifact(
        Path(str(report["_run_report_path"])),
        target.get("stream_receipt_path"),
        label="stream_receipt_path",
    )
    receipt_evidence = _timestamp_receipt_evidence(
        timestamped_path,
        raw_path,
        stream_receipt_path,
    )
    if receipt_evidence["event_count"] != telemetry.get("event_count"):
        raise EvidenceIneligible("timestamped_trace_event_count_mismatch")
    if (
        receipt_evidence["distinct_receipt_timestamp_count"]
        != telemetry.get("distinct_receipt_timestamp_count")
    ):
        reasons.append("timestamped_trace_receipt_count_mismatch")
    tool_rows = telemetry.get("tool_intervals")
    tool_by_id: dict[str, Mapping[str, Any]] = {}
    if isinstance(tool_rows, list):
        for value in tool_rows:
            if isinstance(value, Mapping):
                item_id = str(value.get("item_id") or "")
                if not item_id or item_id in tool_by_id:
                    reasons.append("telemetry_tool_interval_identity_invalid")
                else:
                    tool_by_id[item_id] = value
    if set(tool_by_id) != set(receipt_evidence["observed_action_ids"]):
        reasons.append("telemetry_trace_action_set_mismatch")
    for action_id, interval in receipt_evidence[
        "observed_action_intervals"
    ].items():
        telemetry_interval = tool_by_id.get(action_id)
        if not isinstance(telemetry_interval, Mapping):
            continue
        for telemetry_field, receipt_field in (
            ("start_monotonic", "start_monotonic_seconds"),
            ("end_monotonic", "end_monotonic_seconds"),
            ("duration_seconds", "duration_seconds"),
        ):
            if not _close_seconds(
                telemetry_interval.get(telemetry_field),
                interval.get(receipt_field),
            ):
                reasons.append(
                    f"telemetry_trace_action_interval_mismatch:{action_id}"
                )
                break
    if reasons:
        raise EvidenceIneligible(*reasons)
    source_candidates.append(timestamped_path)
    source_candidates.append(raw_path)
    source_hashes = {sha256_file(path) for path in source_candidates}
    timestamped_trace_sha256 = sha256_file(timestamped_path)
    raw_trace_sha256 = sha256_file(raw_path)
    return {
        "operational_e2e_seconds": float(e2e),
        "phase_seconds": canonical,
        "phase_fraction": {
            key: value / float(e2e) for key, value in canonical.items()
        },
        "phase_conservation_delta_seconds": delta,
        "source_trace_candidate_sha256s": sorted(source_hashes),
        "timestamped_trace_sha256": timestamped_trace_sha256,
        "raw_trace_sha256": raw_trace_sha256,
        "expected_observed_action_ids": receipt_evidence[
            "observed_action_ids"
        ],
        "expected_observed_action_count": receipt_evidence[
            "observed_action_count"
        ],
        "expected_observed_action_set_sha256": receipt_evidence[
            "observed_action_set_sha256"
        ],
        "expected_observed_action_intervals": receipt_evidence[
            "observed_action_intervals"
        ],
        "expected_observed_action_duration_sum_seconds": receipt_evidence[
            "observed_action_duration_sum_seconds"
        ],
    }, raw_trace_sha256


def _select_ledger_case(
    ledger: Mapping[str, Any], case_id: str
) -> Mapping[str, Any]:
    cases = ledger.get("cases")
    if isinstance(cases, list):
        matches = [
            value
            for value in cases
            if isinstance(value, Mapping) and value.get("case_id") == case_id
        ]
        if len(matches) != 1:
            raise EvidenceIneligible("action_ledger_case_identity_missing_or_duplicate")
        return matches[0]
    return ledger


def attach_observed_durations(
    *,
    case_id: str,
    ledger_raw: Mapping[str, Any],
    dag: Mapping[str, Any],
    expected_timestamped_trace_sha256: str,
    expected_observed_action_ids: set[str],
    expected_observed_action_intervals: Mapping[str, Mapping[str, float]],
    expected_annotation_sha256: str,
    expected_mapping_rows: Sequence[Mapping[str, Any]],
    expected_mapping_sha256: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    ledger = _select_ledger_case(ledger_raw, case_id)
    reasons: list[str] = []
    if "case_id" not in ledger or ledger.get("case_id") != case_id:
        raise AnalysisError(f"{case_id}: action-ledger identity drift")
    if "status" not in ledger or str(ledger.get("status") or "").lower() not in {
        "pass",
        "passed",
        "qualified",
    }:
        reasons.append("observed_action_ledger_not_passed")
    source_sha = str(ledger.get("source_trace_sha256") or "")
    if source_sha != expected_timestamped_trace_sha256:
        reasons.append("observed_action_source_trace_identity_mismatch")
    if (
        ledger.get("duration_blind_annotation_sha256")
        != expected_annotation_sha256
    ):
        reasons.append("duration_blind_annotation_ledger_binding_mismatch")
    if ledger.get("duration_blind_mapping_sha256") != expected_mapping_sha256:
        reasons.append("duration_blind_mapping_ledger_binding_mismatch")
    if ledger.get("duration_used_for_topology_or_semantic_selection") is not False:
        reasons.append("duration_blindness_not_attested")
    for field in ("imputed_duration_seconds", "uncovered_duration_seconds"):
        if field not in ledger:
            reasons.append(f"missing_explicit_{field}")
    for field in (
        "imputed_duration_seconds",
        "imputed_seconds",
        "uncovered_duration_seconds",
        "uncovered_seconds",
    ):
        if field in ledger:
            value = ledger[field]
            if value is None or not _finite(value) or abs(float(value)) > 1e-9:
                reasons.append(f"nonzero_or_missing_{field}")
    rows = ledger.get("rows", ledger.get("actions"))
    if not isinstance(rows, list) or not rows:
        reasons.append("observed_action_rows_missing")
        rows = []
    node_ids = {str(node["node_id"]) for node in dag["nodes"]}
    active_raw = ledger.get("active_semantic_node_ids")
    if not isinstance(active_raw, list):
        reasons.append("active_semantic_node_ids_missing")
        active: set[str] = set()
    else:
        active = {str(value) for value in active_raw}
        if len(active) != len(active_raw) or not active.issubset(node_ids):
            reasons.append("active_semantic_node_ids_invalid")
        for edge in dag["edges"]:
            source = str(edge["src"])
            target = str(edge["dst"])
            if target in active and source not in active:
                reasons.append(
                    f"active_subgraph_predecessor_not_active:{source}->{target}"
                )
    totals = {node_id: 0.0 for node_id in node_ids}
    seen_actions: set[str] = set()
    seen_projected_actions: set[str] = set()
    expected_mapping = {
        str(value["projected_action_id"]): {
            "disposition": str(value["disposition"]),
            "semantic_node_ids": sorted(
                str(node_id) for node_id in value["semantic_node_ids"]
            ),
        }
        for value in expected_mapping_rows
    }
    normalized_rows: list[dict[str, Any]] = []
    accounted = 0.0
    for ordinal, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            reasons.append("malformed_observed_action_row")
            continue
        action_id = str(
            row.get("observed_action_id")
            or row.get("opaque_action_id")
            or row.get("raw_item_id")
            or ""
        )
        if not action_id:
            reasons.append("observed_action_id_missing")
            action_id = f"invalid-{ordinal}"
        if action_id in seen_actions:
            reasons.append("observed_action_mapped_more_than_once")
        seen_actions.add(action_id)
        projected_action_id = str(row.get("projected_action_id") or "")
        if (
            not projected_action_id
            or projected_action_id in seen_projected_actions
            or projected_action_id not in expected_mapping
        ):
            reasons.append("projected_action_mapping_identity_invalid")
        else:
            seen_projected_actions.add(projected_action_id)
        if _finite(row.get("duration_seconds")):
            duration = float(row["duration_seconds"])
        elif type(row.get("duration_ns")) is int:
            duration = int(row["duration_ns"]) / 1_000_000_000
        else:
            duration = -1.0
        if not math.isfinite(duration) or duration <= 0:
            reasons.append("observed_action_duration_nonpositive")
            continue
        expected_interval = expected_observed_action_intervals.get(action_id)
        if (
            not isinstance(expected_interval, Mapping)
            or not _finite(expected_interval.get("duration_seconds"))
            or not math.isclose(
                duration,
                float(expected_interval["duration_seconds"]),
                rel_tol=1e-6,
                abs_tol=1e-6,
            )
        ):
            reasons.append("observed_action_duration_not_trace_derived")
        disposition = str(row.get("disposition") or "")
        semantic_ids = [str(value) for value in row.get("semantic_node_ids") or []]
        expected_disposition = expected_mapping.get(projected_action_id)
        if expected_disposition != {
            "disposition": disposition,
            "semantic_node_ids": sorted(semantic_ids),
        }:
            reasons.append("duration_blind_mapping_row_drift")
        if len(semantic_ids) != len(set(semantic_ids)) or not set(semantic_ids).issubset(node_ids):
            reasons.append("observed_action_semantic_target_invalid")
            continue
        allocations: dict[str, float] = {}
        if disposition in {"retain", "merge_into_semantic_node"}:
            if len(semantic_ids) != 1:
                reasons.append("retained_action_requires_one_semantic_target")
            else:
                allocations[semantic_ids[0]] = duration
        elif disposition == "split_across_semantic_nodes":
            raw_allocations = row.get("semantic_allocations_seconds")
            if not isinstance(raw_allocations, Mapping):
                reasons.append("split_action_allocation_missing")
            else:
                for node_id, value in raw_allocations.items():
                    if str(node_id) not in semantic_ids or not _nonnegative(value):
                        reasons.append("split_action_allocation_invalid")
                        continue
                    allocations[str(node_id)] = float(value)
                if (
                    set(allocations) != set(semantic_ids)
                    or not math.isclose(
                        sum(allocations.values()), duration, rel_tol=1e-9, abs_tol=1e-9
                    )
                ):
                    reasons.append("split_action_allocation_not_conserved")
        elif disposition in {
            "discard_redundant_exploration",
            "discard_tool_noise",
            "move_to_system_envelope",
        }:
            if semantic_ids:
                reasons.append("nonsemantic_disposition_has_semantic_target")
        else:
            reasons.append("unknown_action_disposition")
        for node_id, value in allocations.items():
            totals[node_id] += value
        accounted += duration
        normalized_rows.append(
            {
                "observed_action_id": action_id,
                "projected_action_id": projected_action_id,
                "duration_seconds": duration,
                "disposition": disposition,
                "semantic_node_ids": semantic_ids,
                "semantic_allocations_seconds": allocations,
            }
        )
    if any(totals[node_id] <= 0 for node_id in active):
        reasons.append("active_semantic_node_without_positive_duration")
    if any(totals[node_id] > 0 for node_id in node_ids - active):
        reasons.append("inactive_semantic_node_received_observed_duration")
    if not active:
        reasons.append("empty_active_semantic_subgraph")
    if seen_actions != expected_observed_action_ids:
        reasons.append("observed_action_set_not_exactly_covered")
    if seen_projected_actions != set(expected_mapping):
        reasons.append("duration_blind_projected_action_set_not_exactly_covered")
    expected_action_seconds = sum(
        float(row["duration_seconds"])
        for row in expected_observed_action_intervals.values()
        if isinstance(row, Mapping) and _finite(row.get("duration_seconds"))
    )
    if not math.isclose(
        accounted,
        expected_action_seconds,
        rel_tol=1e-6,
        abs_tol=1e-6,
    ):
        reasons.append("observed_action_duration_sum_not_conserved")
    if reasons:
        raise EvidenceIneligible(*reasons)
    durations = {node_id: totals[node_id] for node_id in sorted(active)}
    return durations, {
        "case_id": case_id,
        "status": "pass",
        "source_trace_sha256": source_sha,
        "duration_blind_annotation_sha256": expected_annotation_sha256,
        "duration_blind_mapping_sha256": expected_mapping_sha256,
        "observed_action_count": len(normalized_rows),
        "expected_observed_action_count": len(expected_observed_action_ids),
        "expected_observed_action_set_sha256": sha256_bytes(
            canonical_bytes(sorted(expected_observed_action_ids))
        ),
        "expected_observed_action_duration_sum_seconds": (
            expected_action_seconds
        ),
        "active_semantic_node_ids": sorted(active),
        "inactive_semantic_node_ids": sorted(node_ids - active),
        "inactive_nodes_may_have_zero_duration": True,
        "semantic_work_seconds": sum(durations.values()),
        "all_action_seconds": accounted,
        "imputed_duration_seconds": 0.0,
        "uncovered_duration_seconds": 0.0,
        "duration_used_for_topology_or_semantic_selection": False,
        "rows": normalized_rows,
    }


def topology_waves(
    dag: Mapping[str, Any],
) -> list[tuple[set[str], list[str]]]:
    unit = {str(node["node_id"]): 1.0 for node in dag["nodes"]}
    node_order, _, preds, _, _ = _graph_parts(dag, unit)
    completed: set[str] = set()
    waves: list[tuple[set[str], list[str]]] = []
    while len(completed) < len(node_order):
        ready = [
            node_id
            for node_id in node_order
            if node_id not in completed
            and all(parent in completed for parent in preds[node_id])
        ]
        require(bool(ready), "topology wave construction stalled")
        waves.append((set(completed), ready))
        completed.update(ready)
    return waves


def candidate_window(
    dag: Mapping[str, Any],
    completed_before: set[str],
    ready: Sequence[str],
    depth: int | str,
    width: int,
) -> list[str]:
    unit = {str(node["node_id"]): 1.0 for node in dag["nodes"]}
    node_order, _, preds, succs, _ = _graph_parts(dag, unit)
    order = {node_id: index for index, node_id in enumerate(node_order)}
    selected_roots = list(ready[:width])
    visible = set(selected_roots)
    frontier = set(selected_roots)
    remaining = None if depth == "full" else int(depth) - 1
    pending = set(node_order) - completed_before
    while frontier and (remaining is None or remaining > 0):
        following = {
            child
            for node_id in frontier
            for child in succs[node_id]
            if child in pending
        } - visible
        visible.update(following)
        frontier = following
        if remaining is not None:
            remaining -= 1
    changed = True
    while changed:
        changed = False
        for node_id in list(visible):
            if any(
                predecessor not in completed_before and predecessor not in visible
                for predecessor in preds[node_id]
            ):
                visible.remove(node_id)
                changed = True
    return sorted(visible, key=order.get)


def _candidate_value_signature(row: Mapping[str, Any]) -> tuple[float | None, ...]:
    fields = (
        "estimated_ceiling",
        "estimated_list_headroom",
        "observed_ceiling",
        "observed_list_headroom",
    )
    return tuple(
        None if row.get(field) is None else float(row[field]) for field in fields
    )


def deduplicate_c_candidates(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        key = (str(row["case_id"]), str(row["topology_window_sha256"]))
        if key not in grouped:
            row["source_configurations"] = [
                dict(value) for value in row.get("source_configurations") or []
            ]
            grouped[key] = row
            continue
        current = grouped[key]
        left, right = _candidate_value_signature(current), _candidate_value_signature(row)
        for first, second in zip(left, right):
            if (first is None) != (second is None) or (
                first is not None
                and not math.isclose(first, second, rel_tol=1e-12, abs_tol=1e-12)
            ):
                raise AnalysisError(
                    f"conflicting duplicate topology window: {key[0]}:{key[1]}"
                )
        if canonical_bytes(current.get("worker_sensitivity")) != canonical_bytes(
            row.get("worker_sensitivity")
        ):
            raise AnalysisError(
                f"conflicting duplicate worker sensitivity: {key[0]}:{key[1]}"
            )
        current["source_configurations"].extend(
            dict(value) for value in row.get("source_configurations") or []
        )
    output: list[dict[str, Any]] = []
    for row in grouped.values():
        configurations = {
            (
                int(value["wave"]),
                str(value["depth"]),
                int(value["width"]),
            ): value
            for value in row["source_configurations"]
        }
        row["source_configurations"] = [
            configurations[key] for key in sorted(configurations)
        ]
        row["configuration_count"] = len(row["source_configurations"])
        output.append(row)
    return sorted(
        output,
        key=lambda value: (
            int(value["position"]),
            str(value["topology_window_sha256"]),
        ),
    )


def build_c_candidates(
    *,
    case: Mapping[str, Any],
    dag: Mapping[str, Any],
    observed_durations: Mapping[str, float] | None,
) -> list[dict[str, Any]]:
    if case["physical_repository"] not in HELD_OUT_REPOSITORIES:
        return []
    # Candidate topology is always generated from the sealed audited DAG.  An
    # observed reference is attached only when every node in that candidate was
    # active on the realized path.  Thus an inactive conditional node may have
    # zero observed duration without letting outcome/duration alter selection.
    candidate_dag = dict(dag)
    typed = type_durations(candidate_dag)
    provisional: list[dict[str, Any]] = []
    for wave, (completed, ready) in enumerate(topology_waves(candidate_dag), 1):
        for depth in C_DEPTHS:
            for width in C_WIDTHS:
                node_ids = candidate_window(
                    candidate_dag, completed, ready, depth, width
                )
                if not node_ids:
                    continue
                window = induced_dag(candidate_dag, node_ids)
                hash_value = topology_sha256(window)
                estimate = graph_metrics(
                    window,
                    {node_id: typed[node_id] for node_id in node_ids},
                )
                reference = (
                    graph_metrics(
                        window,
                        {
                            node_id: float(observed_durations[node_id])
                            for node_id in node_ids
                        },
                    )
                    if observed_durations is not None
                    and set(node_ids).issubset(observed_durations)
                    else None
                )
                p4_estimate = estimate["finite_workers"]["P4"]
                p4_reference = (
                    reference["finite_workers"]["P4"] if reference else None
                )
                worker_sensitivity: dict[str, Any] = {}
                for worker_count in (2, 4, 8):
                    label = f"P{worker_count}"
                    estimated_worker = estimate["finite_workers"][label]
                    observed_worker = (
                        reference["finite_workers"][label] if reference else None
                    )
                    worker_sensitivity[label] = {
                        "estimated_ceiling": estimated_worker[
                            "relaxed_ceiling_headroom"
                        ],
                        "estimated_list_headroom": estimated_worker[
                            "list_headroom"
                        ],
                        "observed_ceiling": (
                            observed_worker["relaxed_ceiling_headroom"]
                            if observed_worker
                            else None
                        ),
                        "observed_list_headroom": (
                            observed_worker["list_headroom"]
                            if observed_worker
                            else None
                        ),
                    }
                provisional.append(
                    {
                        "case_id": case["case_id"],
                        "position": case["position"],
                        "physical_repository": case["physical_repository"],
                        "topology_window_sha256": hash_value,
                        "independent_unit": [case["case_id"], hash_value],
                        "node_ids": node_ids,
                        "node_count": len(node_ids),
                        "topology_payload": topology_payload(window),
                        "topology_selection_duration_blind": True,
                        "worker": C_PRIMARY_WORKERS,
                        "estimated_ceiling": p4_estimate[
                            "relaxed_ceiling_headroom"
                        ],
                        "estimated_list_headroom": p4_estimate["list_headroom"],
                        "observed_ceiling": (
                            p4_reference["relaxed_ceiling_headroom"]
                            if p4_reference
                            else None
                        ),
                        "observed_list_headroom": (
                            p4_reference["list_headroom"]
                            if p4_reference
                            else None
                        ),
                        "absolute_ceiling_error": (
                            abs(
                                p4_estimate["relaxed_ceiling_headroom"]
                                - p4_reference["relaxed_ceiling_headroom"]
                            )
                            if p4_reference
                            else None
                        ),
                        "absolute_percentage_ceiling_error": (
                            abs(
                                p4_estimate["relaxed_ceiling_headroom"]
                                - p4_reference["relaxed_ceiling_headroom"]
                            )
                            / p4_reference["relaxed_ceiling_headroom"]
                            if p4_reference
                            else None
                        ),
                        "worker_sensitivity": worker_sensitivity,
                        "source_configurations": [
                            {
                                "wave": wave,
                                "depth": depth,
                                "width": width,
                            }
                        ],
                    }
                )
    return deduplicate_c_candidates(provisional)


def validate_c_heldout_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    leaked = sorted(
        {
            str(row["physical_repository"])
            for row in rows
            if row["physical_repository"] not in HELD_OUT_REPOSITORIES
        }
    )
    require(not leaked, f"C development-repository leakage: {', '.join(leaked)}")
    units = [
        (str(row["case_id"]), str(row["topology_window_sha256"])) for row in rows
    ]
    require(len(units) == len(set(units)), "C duplicate independent-unit inflation")
    require(
        all(int(row["worker"]) == C_PRIMARY_WORKERS for row in rows),
        "C primary worker drift",
    )


def ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda value: (value[1], value[0]))
    output = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for original, _ in indexed[index:end]:
            output[original] = rank
        index = end
    return output


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_rank, right_rank = ranks(left), ranks(right)
    left_mean = statistics.fmean(left_rank)
    right_mean = statistics.fmean(right_rank)
    numerator = sum(
        (first - left_mean) * (second - right_mean)
        for first, second in zip(left_rank, right_rank)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left_rank)
        * sum((value - right_mean) ** 2 for value in right_rank)
    )
    return numerator / denominator if denominator else None


def nearest_rank(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def distribution(
    values: Sequence[float | None], *, intention_count: int
) -> dict[str, Any]:
    observed = sorted(float(value) for value in values if value is not None)
    return {
        "intention_count": intention_count,
        "observed_count": len(observed),
        "not_observed_count": intention_count - len(observed),
        "minimum": observed[0] if observed else None,
        "p25": nearest_rank(observed, 0.25),
        "median": nearest_rank(observed, 0.50),
        "p75": nearest_rank(observed, 0.75),
        "maximum": observed[-1] if observed else None,
        "mean": statistics.fmean(observed) if observed else None,
    }


def repository_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    threshold: float | None = None,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    repositories = sorted({str(row["physical_repository"]) for row in rows})
    require(bool(repositories), "repository bootstrap requires cohort rows")
    by_repository = {
        repository: [
            row for row in rows if str(row["physical_repository"]) == repository
        ]
        for repository in repositories
    }
    seed_material = f"{BOOTSTRAP_SEED}|A|{metric}|{threshold}"
    seed_sha = hashlib.sha256(seed_material.encode()).hexdigest()
    rng = random.Random(int(seed_sha, 16))
    medians: list[float] = []
    fractions: list[float] = []
    for _ in range(resamples):
        sampled = [
            repositories[rng.randrange(len(repositories))]
            for _ in repositories
        ]
        sampled_rows = [
            row for repository in sampled for row in by_repository[repository]
        ]
        observed = [
            float(row[metric])
            for row in sampled_rows
            if row.get(metric) is not None
        ]
        if observed:
            medians.append(statistics.median(observed))
        if threshold is not None and sampled_rows:
            fractions.append(
                sum(value >= threshold for value in observed) / len(sampled_rows)
            )
    point_observed = [
        float(row[metric]) for row in rows if row.get(metric) is not None
    ]
    output = {
        "bootstrap_unit": "physical_repository",
        "repository_count": len(repositories),
        "resamples": resamples,
        "seed_string": BOOTSTRAP_SEED,
        "metric_seed_sha256": seed_sha,
        "median_observed": {
            "point": statistics.median(point_observed) if point_observed else None,
            "ci95_lower": nearest_rank(medians, 0.025),
            "ci95_upper": nearest_rank(medians, 0.975),
            "valid_resamples": len(medians),
            "undefined_resamples": resamples - len(medians),
        },
    }
    if threshold is not None:
        output["fraction_at_least_threshold_over_intention"] = {
            "threshold": threshold,
            "point": (
                sum(value >= threshold for value in point_observed) / len(rows)
                if rows
                else None
            ),
            "ci95_lower": nearest_rank(fractions, 0.025),
            "ci95_upper": nearest_rank(fractions, 0.975),
            "valid_resamples": len(fractions),
            "undefined_resamples": resamples - len(fractions),
        }
    return output


def _metric_from_a_row(
    row: Mapping[str, Any], model: str, metric: str
) -> float | None:
    metrics = row.get(f"{model}_metrics")
    if not isinstance(metrics, Mapping):
        return None
    if metric in metrics:
        value = metrics[metric]
    elif metric.startswith("P"):
        value = ((metrics.get("finite_workers") or {}).get(metric) or {}).get(
            "list_headroom"
        )
    else:
        value = None
    return float(value) if _finite(value) else None


def summarize_graph_model(
    rows: Sequence[Mapping[str, Any]], model: str
) -> dict[str, Any]:
    metric_names = ("S_infinity", "P1", "P2", "P4", "P8")
    output: dict[str, Any] = {}
    for metric in metric_names:
        values = [_metric_from_a_row(row, model, metric) for row in rows]
        observed_rows = [
            (row, value)
            for row, value in zip(rows, values)
            if value is not None
        ]
        repo_means: list[float] = []
        for repository in sorted(
            {str(row["physical_repository"]) for row in rows}
        ):
            repo_values = [
                value
                for row, value in observed_rows
                if row["physical_repository"] == repository
            ]
            if repo_values:
                repo_means.append(statistics.fmean(repo_values))
        metric_summary: dict[str, Any] = {
            "distribution": distribution(values, intention_count=30),
            "case_weighted_mean": (
                statistics.fmean(value for _, value in observed_rows)
                if observed_rows
                else None
            ),
            "repository_macro_average": (
                statistics.fmean(repo_means) if repo_means else None
            ),
            "repository_count_observed": len(repo_means),
        }
        if metric == "S_infinity":
            work = sum(
                float(row[f"{model}_metrics"]["W"])
                for row, _ in observed_rows
            )
            span = sum(
                float(row[f"{model}_metrics"]["L"])
                for row, _ in observed_rows
            )
            metric_summary["pooled_duration_sumW_over_sumL"] = (
                work / span if span else None
            )
        else:
            makespans = sum(
                float(
                    row[f"{model}_metrics"]["finite_workers"][metric][
                        "list_makespan"
                    ]
                )
                for row, _ in observed_rows
            )
            work = sum(
                float(row[f"{model}_metrics"]["W"])
                for row, _ in observed_rows
            )
            metric_summary["pooled_duration_sumW_over_sum_makespan"] = (
                work / makespans if makespans else None
            )
        output[metric] = metric_summary
    return output


def phase_aggregation(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [
        row for row in rows if isinstance(row.get("phase_composition"), Mapping)
    ]
    phase_names = (
        "model_decision",
        "real_action_excluding_build_test",
        "build_test",
        "explicit_wait",
        "integration_finalization_and_official_evaluator",
        "measured_residual",
    )
    total_e2e = sum(
        float(row["phase_composition"]["operational_e2e_seconds"])
        for row in eligible
    )
    pooled_seconds = {
        phase: sum(
            float(row["phase_composition"]["phase_seconds"][phase])
            for row in eligible
        )
        for phase in phase_names
    }
    repositories = sorted(
        {str(row["physical_repository"]) for row in eligible}
    )
    repo_shares: dict[str, dict[str, float]] = {}
    for repository in repositories:
        selected = [
            row for row in eligible if row["physical_repository"] == repository
        ]
        repo_e2e = sum(
            float(row["phase_composition"]["operational_e2e_seconds"])
            for row in selected
        )
        repo_shares[repository] = {
            phase: sum(
                float(row["phase_composition"]["phase_seconds"][phase])
                for row in selected
            )
            / repo_e2e
            for phase in phase_names
        }
    return {
        "intention_count": 30,
        "eligible_count": len(eligible),
        "not_observed_count": 30 - len(eligible),
        "case_weighted_mean_fraction": {
            phase: (
                statistics.fmean(
                    float(row["phase_composition"]["phase_fraction"][phase])
                    for row in eligible
                )
                if eligible
                else None
            )
            for phase in phase_names
        },
        "pooled_duration": {
            "total_operational_e2e_seconds": total_e2e or None,
            "phase_seconds": pooled_seconds,
            "phase_fraction": {
                phase: pooled_seconds[phase] / total_e2e if total_e2e else None
                for phase in phase_names
            },
        },
        "repository_macro": {
            "repository_count": len(repositories),
            "repository_phase_fractions": repo_shares,
            "mean_fraction": {
                phase: (
                    statistics.fmean(
                        repo_shares[repository][phase]
                        for repository in repositories
                    )
                    if repositories
                    else None
                )
                for phase in phase_names
            },
        },
    }


def a_prevalence(
    rows: Sequence[Mapping[str, Any]], metric: str
) -> dict[str, Any]:
    values = [_metric_from_a_row(row, "observed_duration", metric) for row in rows]
    observed = [value for value in values if value is not None]
    thresholds: dict[str, Any] = {}
    for threshold in (2.0, 3.0, 4.0):
        count = sum(value >= threshold for value in observed)
        thresholds[str(int(threshold))] = {
            "count": count,
            "fraction_over_intention_30": count / 30,
            "fraction_over_observed_join": (
                count / len(observed) if observed else None
            ),
        }
    in_band = sum(3.0 <= value <= 4.0 for value in observed)
    return {
        "metric": metric,
        "intention_count": 30,
        "observed_count": len(observed),
        "not_observed_count": 30 - len(observed),
        "thresholds": thresholds,
        "three_to_four_count": in_band,
        "three_to_four_fraction_over_intention": in_band / 30,
        "three_to_four_fraction_over_observed": (
            in_band / len(observed) if observed else None
        ),
    }


def a_strata(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def summarize(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            "intention_count": len(selected),
            "observed_S_infinity": distribution(
                [
                    _metric_from_a_row(row, "observed_duration", "S_infinity")
                    for row in selected
                ],
                intention_count=len(selected),
            ),
            "observed_P4": distribution(
                [
                    _metric_from_a_row(row, "observed_duration", "P4")
                    for row in selected
                ],
                intention_count=len(selected),
            ),
        }

    def grouped(field: str) -> dict[str, Any]:
        return {
            value: summarize(
                [row for row in rows if str(row.get(field)) == value]
            )
            for value in sorted({str(row.get(field)) for row in rows})
        }

    audited = [
        row
        for row in rows
        if isinstance(row.get("type_weighted_metrics"), Mapping)
    ]
    shape_labels: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    size_labels: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in audited:
        metrics = row["type_weighted_metrics"]
        node_count = int(metrics["node_count"])
        width = int(metrics["max_ready_width"])
        size = "small" if node_count <= 6 else "medium" if node_count <= 12 else "large"
        shape = "serial" if width == 1 else "narrow" if width == 2 else "branching" if width <= 4 else "wide"
        size_labels[size].append(row)
        shape_labels[shape].append(row)
    return {
        "task_size_frozen_difficulty": grouped("difficulty"),
        "repository_domain_family": grouped("repository_domain_family"),
        "graph_node_count_bins": {
            label: summarize(selected)
            for label, selected in sorted(size_labels.items())
        },
        "graph_width_bins": {
            label: summarize(selected)
            for label, selected in sorted(shape_labels.items())
        },
    }


def threshold_metrics(
    rows: Sequence[Mapping[str, Any]], threshold: float
) -> dict[str, Any]:
    paired = [
        row
        for row in rows
        if row.get("estimated_ceiling") is not None
        and row.get("observed_ceiling") is not None
    ]
    predicted = [float(row["estimated_ceiling"]) >= threshold for row in paired]
    actual = [float(row["observed_ceiling"]) >= threshold for row in paired]
    true_positive = sum(left and right for left, right in zip(predicted, actual))
    false_positive = sum(left and not right for left, right in zip(predicted, actual))
    false_negative = sum(not left and right for left, right in zip(predicted, actual))
    true_negative = sum(not left and not right for left, right in zip(predicted, actual))
    actual_positive = true_positive + false_negative
    actual_negative = true_negative + false_positive
    predicted_positive = true_positive + false_positive
    return {
        "threshold": threshold,
        "unique_paired_window_count": len(paired),
        "admitted": predicted_positive,
        "rejected": true_negative + false_negative,
        "true_admission": true_positive,
        "false_admission": false_positive,
        "true_rejection": true_negative,
        "false_rejection": false_negative,
        "false_rejection_rate_over_actual_beneficial": (
            false_negative / actual_positive if actual_positive else None
        ),
        "false_admission_rate_over_predicted_admitted": (
            false_positive / predicted_positive if predicted_positive else None
        ),
        "false_admission_fraction_overall": (
            false_positive / len(paired) if paired else None
        ),
        "false_positive_rate_over_actual_low_benefit": (
            false_positive / actual_negative if actual_negative else None
        ),
        "low_benefit_window_rejection_fraction": (
            true_negative / actual_negative if actual_negative else None
        ),
        "overall_rejection_fraction": (
            (true_negative + false_negative) / len(paired)
            if paired
            else None
        ),
    }


def c_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]], *, resamples: int = BOOTSTRAP_RESAMPLES
) -> dict[str, Any]:
    paired = [
        row
        for row in rows
        if row.get("estimated_ceiling") is not None
        and row.get("observed_ceiling") is not None
    ]
    repositories = sorted(HELD_OUT_REPOSITORIES)
    by_repository = {
        repository: [
            row for row in paired if row["physical_repository"] == repository
        ]
        for repository in repositories
    }
    seed_material = f"{BOOTSTRAP_SEED}|C|P4|1.10"
    seed_sha = hashlib.sha256(seed_material.encode()).hexdigest()
    rng = random.Random(int(seed_sha, 16))
    correlations: list[float] = []
    false_rejections: list[float] = []
    low_benefit_rejections: list[float] = []
    for _ in range(resamples):
        sampled = [
            repositories[rng.randrange(len(repositories))]
            for _ in repositories
        ]
        selected = [
            row for repository in sampled for row in by_repository[repository]
        ]
        correlation = spearman(
            [float(row["estimated_ceiling"]) for row in selected],
            [float(row["observed_ceiling"]) for row in selected],
        )
        if correlation is not None:
            correlations.append(correlation)
        threshold = threshold_metrics(selected, C_PRIMARY_THRESHOLD)
        if threshold["false_rejection_rate_over_actual_beneficial"] is not None:
            false_rejections.append(
                threshold["false_rejection_rate_over_actual_beneficial"]
            )
        if threshold["low_benefit_window_rejection_fraction"] is not None:
            low_benefit_rejections.append(
                threshold["low_benefit_window_rejection_fraction"]
            )
    return {
        "bootstrap_unit": "held_out_physical_repository",
        "repository_count": len(repositories),
        "resamples": resamples,
        "seed_string": BOOTSTRAP_SEED,
        "metric_seed_sha256": seed_sha,
        "spearman": {
            "ci95_lower": nearest_rank(correlations, 0.025),
            "ci95_upper": nearest_rank(correlations, 0.975),
            "valid_resamples": len(correlations),
            "undefined_resamples": resamples - len(correlations),
        },
        "false_rejection_rate": {
            "ci95_lower": nearest_rank(false_rejections, 0.025),
            "ci95_upper": nearest_rank(false_rejections, 0.975),
            "valid_resamples": len(false_rejections),
            "undefined_resamples": resamples - len(false_rejections),
        },
        "low_benefit_rejection_fraction": {
            "ci95_lower": nearest_rank(low_benefit_rejections, 0.025),
            "ci95_upper": nearest_rank(low_benefit_rejections, 0.975),
            "valid_resamples": len(low_benefit_rejections),
            "undefined_resamples": resamples - len(low_benefit_rejections),
        },
    }


def c_depth_width_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for depth in C_DEPTHS:
        output[str(depth)] = {}
        for width in C_WIDTHS:
            selected = [
                row
                for row in rows
                if any(
                    str(config["depth"]) == str(depth)
                    and int(config["width"]) == width
                    for config in row["source_configurations"]
                )
                and row.get("observed_ceiling") is not None
            ]
            errors = [float(row["absolute_ceiling_error"]) for row in selected]
            percentage = [
                float(row["absolute_percentage_ceiling_error"]) for row in selected
            ]
            output[str(depth)][str(width)] = {
                "unique_paired_window_count": len(selected),
                "ceiling_mae": statistics.fmean(errors) if errors else None,
                "ceiling_mape": statistics.fmean(percentage) if percentage else None,
                "spearman": spearman(
                    [float(row["estimated_ceiling"]) for row in selected],
                    [float(row["observed_ceiling"]) for row in selected],
                ),
            }
    return output


def _case_base_row(
    frozen: Mapping[str, Any], index_row: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "position": frozen["position"],
        "case_id": frozen["case_id"],
        "instance_id": frozen["instance_id"],
        "physical_repository": frozen["physical_repository"],
        "base_commit": frozen["base_commit"],
        "difficulty": frozen.get("difficulty"),
        "repository_domain_family": frozen.get("repository_domain_family"),
        "index_status": index_row.get("status", "unavailable"),
        "index_attrition_reasons": list(index_row.get("attrition_reasons") or []),
        "run_report_present": False,
        "phase_composition_eligible": False,
        "audited_reference_dag_eligible": False,
        "observed_action_join_eligible": False,
        "phase_composition": None,
        "type_weighted_metrics": None,
        "observed_duration_metrics": None,
        "reference_dag_sha256": None,
        "topology_sha256": None,
        "source_trace_sha256": None,
        "raw_trace_sha256": None,
        "timestamped_trace_sha256": None,
        "attrition_reasons": list(index_row.get("attrition_reasons") or []),
    }


def build_case_rows(
    manifest_cases: Sequence[Mapping[str, Any]],
    index_rows: Sequence[Mapping[str, Any]],
    case_index_path: Path,
    *,
    test_only: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    ledger_cases: list[dict[str, Any]] = []
    c_rows: list[dict[str, Any]] = []
    for frozen, index_row in zip(manifest_cases, index_rows):
        case_id = str(frozen["case_id"])
        row = _case_base_row(frozen, index_row)
        artifacts, evidence = resolve_case_artifacts(index_row, case_index_path)
        row["input_artifact_evidence"] = evidence
        index_status = str(index_row.get("status") or "unavailable")
        complete_statuses = {"completed_target_and_official_evaluator"}
        if test_only:
            complete_statuses.add("complete_test_fixture")
        if index_status not in complete_statuses:
            row["attrition_reasons"].append(
                f"index_status_not_complete:{index_status}"
            )
            if artifacts:
                row["attrition_reasons"].append(
                    "index_noncomplete_artifacts_ignored"
                )
            row["attrition_reasons"] = sorted(set(row["attrition_reasons"]))
            output.append(row)
            continue
        if row["index_attrition_reasons"]:
            row["attrition_reasons"].append(
                "index_complete_status_conflicts_with_attrition_reasons"
            )
            row["attrition_reasons"] = sorted(set(row["attrition_reasons"]))
            output.append(row)
            continue
        report: dict[str, Any] | None = None
        run_report_complete = False
        phase: dict[str, Any] | None = None
        trace_bindings: dict[str, Any] | None = None
        if index_row.get("_collection_plan_sha256") is not None:
            if "authorization" not in artifacts:
                raise AnalysisError(
                    f"{case_id}: completed case authorization artifact missing"
                )
            validate_run_authorization(
                read_json(artifacts["authorization"]),
                frozen,
                index_row,
            )
        if "run_report" not in artifacts:
            row["attrition_reasons"].append("run_report_missing")
        else:
            report = read_json(artifacts["run_report"])
            if report.get("test_only") is True and not test_only:
                raise AnalysisError(f"{case_id}: test-only run in non-test case index")
            validate_run_identity(report, frozen, index_row)
            report = dict(report)
            report["_run_report_path"] = str(artifacts["run_report"])
            row["run_report_present"] = True
            run_observation_errors = _run_scientific_observation_errors(report)
            if report.get("terminal_state") != (
                "completed_target_and_official_evaluator"
            ):
                run_observation_errors.append(
                    "target_or_official_evaluator_incomplete"
                )
            if run_observation_errors:
                row["attrition_reasons"].extend(run_observation_errors)
            else:
                run_report_complete = True
            try:
                trace_bindings = _resolve_run_trace_bindings(report)
                row["raw_trace_sha256"] = trace_bindings[
                    "raw_trace_sha256"
                ]
                row["timestamped_trace_sha256"] = trace_bindings[
                    "timestamped_trace_sha256"
                ]
                row["source_trace_sha256"] = trace_bindings[
                    "raw_trace_sha256"
                ]
            except EvidenceIneligible as exc:
                row["attrition_reasons"].extend(exc.reasons)
            try:
                phase, default_source = extract_phase_composition(report)
                if trace_bindings is None:
                    raise EvidenceIneligible("sealed_source_trace_missing")
                if (
                    phase["raw_trace_sha256"]
                    != trace_bindings["raw_trace_sha256"]
                    or phase["timestamped_trace_sha256"]
                    != trace_bindings["timestamped_trace_sha256"]
                ):
                    raise EvidenceIneligible("phase_trace_binding_mismatch")
                row["phase_composition"] = phase
                row["phase_composition_eligible"] = True
                row["source_trace_sha256"] = default_source
            except EvidenceIneligible as exc:
                row["attrition_reasons"].extend(exc.reasons)
        dag: dict[str, Any] | None = None
        dag_raw: dict[str, Any] | None = None
        duration_blind_annotation_sha256: str | None = None
        duration_blind_mapping_sha256: str | None = None
        duration_blind_mapping_rows: list[dict[str, Any]] | None = None
        if not run_report_complete:
            row["attrition_reasons"].append(
                "audited_reference_dag_blocked_by_incomplete_run"
            )
        elif not all(
            role in artifacts
            for role in (
                "reference_dag",
                "dag_verification",
                "independent_audit",
                "duration_blind_annotation",
            )
        ):
            row["attrition_reasons"].append("audited_reference_dag_artifacts_missing")
        else:
            dag_raw = read_json(artifacts["reference_dag"])
            verification = read_json(artifacts["dag_verification"])
            audit = read_json(artifacts["independent_audit"])
            duration_blind_annotation = read_json(
                artifacts["duration_blind_annotation"]
            )
            if any(
                payload.get("test_only") is True
                for payload in (
                    dag_raw,
                    verification,
                    audit,
                    duration_blind_annotation,
                )
            ) and not test_only:
                raise AnalysisError(f"{case_id}: test-only DAG in non-test case index")
            try:
                if trace_bindings is None:
                    raise EvidenceIneligible(
                        "dag_source_trace_binding_missing"
                    )
                (
                    duration_blind_mapping_rows,
                    duration_blind_mapping_sha256,
                ) = duration_blind_mapping_payload(
                    duration_blind_annotation,
                    case_id,
                )
                duration_blind_annotation_sha256 = sha256_file(
                    artifacts["duration_blind_annotation"]
                )
                dag = normalize_dag(dag_raw, case_id)
                dag_sha = validate_dag_audit(
                    case_id,
                    artifacts["reference_dag"],
                    dag_raw,
                    verification,
                    audit,
                    trace_bindings["raw_trace_sha256"],
                    duration_blind_annotation_sha256,
                    duration_blind_mapping_sha256,
                )
                row["reference_dag_sha256"] = dag_sha
                row["topology_sha256"] = topology_sha256(dag)
                row["audited_reference_dag_eligible"] = True
                row["type_weighted_metrics"] = graph_metrics(
                    dag, type_durations(dag)
                )
            except EvidenceIneligible as exc:
                dag = None
                row["attrition_reasons"].extend(exc.reasons)
        observed: dict[str, float] | None = None
        if dag is not None:
            if "action_ledger" not in artifacts:
                row["attrition_reasons"].append("observed_action_identity_ledger_missing")
            elif not row["phase_composition_eligible"]:
                row["attrition_reasons"].append(
                    "observed_duration_blocked_by_invalid_target_telemetry"
                )
            else:
                ledger_raw = read_json(artifacts["action_ledger"])
                if ledger_raw.get("test_only") is True and not test_only:
                    raise AnalysisError(
                        f"{case_id}: test-only action ledger in non-test case index"
                    )
                try:
                    observed, normalized_ledger = attach_observed_durations(
                        case_id=case_id,
                        ledger_raw=ledger_raw,
                        dag=dag,
                        expected_timestamped_trace_sha256=phase[
                            "timestamped_trace_sha256"
                        ],
                        expected_observed_action_ids=set(
                            phase["expected_observed_action_ids"]
                        ),
                        expected_observed_action_intervals=phase[
                            "expected_observed_action_intervals"
                        ],
                        expected_annotation_sha256=(
                            duration_blind_annotation_sha256
                            or ""
                        ),
                        expected_mapping_rows=(
                            duration_blind_mapping_rows or []
                        ),
                        expected_mapping_sha256=(
                            duration_blind_mapping_sha256 or ""
                        ),
                    )
                    active_dag = induced_dag(dag, observed)
                    row["observed_duration_metrics"] = graph_metrics(
                        active_dag, observed
                    )
                    row["observed_action_join_eligible"] = True
                    ledger_cases.append(normalized_ledger)
                except EvidenceIneligible as exc:
                    row["attrition_reasons"].extend(exc.reasons)
            c_rows.extend(
                build_c_candidates(case=frozen, dag=dag, observed_durations=observed)
            )
        row["attrition_reasons"] = sorted(set(row["attrition_reasons"]))
        output.append(row)
    require(len(output) == 30, "internal P30 denominator loss")
    c_rows = deduplicate_c_candidates(c_rows)
    validate_c_heldout_rows(c_rows)
    ledger = {
        "schema_version": "sge-primary-p30-observed-action-identity-ledger-v1",
        "case_count_intention": 30,
        "joined_case_count": len(ledger_cases),
        "duration_blind_topology_contract": True,
        "inactive_conditional_nodes_may_have_zero_duration": True,
        "cases": sorted(ledger_cases, key=lambda value: value["case_id"]),
        "test_only": test_only,
        "scientific_result": False,
    }
    return output, ledger, c_rows


def _family_failure_gate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for family in sorted({str(row["repository_domain_family"]) for row in rows}):
        selected = [row for row in rows if row["repository_domain_family"] == family]
        failures = sum(not row["audited_reference_dag_eligible"] for row in selected)
        output[family] = {
            "intention_count": len(selected),
            "audit_failure_count": failures,
            "audit_failure_rate": failures / len(selected),
            "passes_maximum_0_4": failures / len(selected) <= 0.4,
        }
    return output


def c_worker_sensitivity_summary(
    rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for worker_count in (2, 4, 8):
        label = f"P{worker_count}"
        projected: list[dict[str, Any]] = []
        for row in rows:
            values = (row.get("worker_sensitivity") or {}).get(label)
            if not isinstance(values, Mapping):
                continue
            projected.append(
                {
                    **row,
                    "estimated_ceiling": values.get("estimated_ceiling"),
                    "estimated_list_headroom": values.get(
                        "estimated_list_headroom"
                    ),
                    "observed_ceiling": values.get("observed_ceiling"),
                    "observed_list_headroom": values.get(
                        "observed_list_headroom"
                    ),
                }
            )
        paired = [
            row for row in projected if row.get("observed_ceiling") is not None
        ]
        absolute_errors = [
            abs(
                float(row["estimated_ceiling"])
                - float(row["observed_ceiling"])
            )
            for row in paired
        ]
        percentage_errors = [
            error / float(row["observed_ceiling"])
            for row, error in zip(paired, absolute_errors)
        ]
        output[label] = {
            "role": "primary" if worker_count == 4 else "sensitivity",
            "unique_window_count": len(projected),
            "paired_observed_unique_window_count": len(paired),
            "ceiling_mae": (
                statistics.fmean(absolute_errors) if absolute_errors else None
            ),
            "ceiling_mape": (
                statistics.fmean(percentage_errors)
                if percentage_errors
                else None
            ),
            "spearman": spearman(
                [float(row["estimated_ceiling"]) for row in paired],
                [float(row["observed_ceiling"]) for row in paired],
            ),
            "thresholds": [
                threshold_metrics(projected, threshold)
                for threshold in C_THRESHOLDS
            ],
        }
    return output


def _c_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    paired = [row for row in rows if row.get("observed_ceiling") is not None]
    errors = [float(row["absolute_ceiling_error"]) for row in paired]
    percentage = [float(row["absolute_percentage_ceiling_error"]) for row in paired]
    repository_counts = Counter(
        str(row["physical_repository"]) for row in paired
    )
    return {
        "scope": "held_out_physical_repositories_only",
        "held_out_repositories": sorted(HELD_OUT_REPOSITORIES),
        "primary_worker": C_PRIMARY_WORKERS,
        "independent_unit": "(case_id, duration-blind topology_window_sha256)",
        "configuration_rows_are_not_independent_samples": True,
        "candidate_unique_window_count": len(rows),
        "paired_observed_unique_window_count": len(paired),
        "paired_observed_case_count": len({row["case_id"] for row in paired}),
        "paired_observed_repository_count": len(repository_counts),
        "paired_observed_windows_by_repository": dict(sorted(repository_counts.items())),
        "ceiling_mae": statistics.fmean(errors) if errors else None,
        "ceiling_mape": statistics.fmean(percentage) if percentage else None,
        "spearman_estimated_vs_observed_ceiling": spearman(
            [float(row["estimated_ceiling"]) for row in paired],
            [float(row["observed_ceiling"]) for row in paired],
        ),
        "thresholds": [
            threshold_metrics(rows, threshold) for threshold in C_THRESHOLDS
        ],
        "worker_sensitivity": c_worker_sensitivity_summary(rows),
        "depth_width": c_depth_width_summary(rows),
        "repository_cluster_bootstrap": c_cluster_bootstrap(rows),
        "formula_boundary": (
            "perfect ceiling and bound-first admission only; prediction "
            "accuracy, wasted work, fallback, and expected utility are excluded"
        ),
    }


def build_analysis(
    cohort_manifest_path: Path, case_index_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    analysis_contract = validate_analysis_contract()
    manifest_path = cohort_manifest_path.resolve()
    index_path = case_index_path.resolve()
    manifest = read_json(manifest_path)
    index = read_json(index_path)
    manifest_seal_sha = verify_file_in_sibling_seal(manifest_path)
    index_seal_sha = verify_file_in_sibling_seal(index_path)
    manifest_cases = validate_manifest(manifest)
    index_rows = validate_case_index(index, manifest_cases, index_path)
    test_only = bool(index["test_only"])
    collection_plan_path: Path | None = None
    collection_plan_sha256: str | None = None
    if not test_only:
        collection_plan_path, collection_plan_sha256 = _collection_plan_path(
            index, index_path
        )
    a_rows, identity_ledger, c_rows = build_case_rows(
        manifest_cases, index_rows, index_path, test_only=test_only
    )
    audited_count = sum(row["audited_reference_dag_eligible"] for row in a_rows)
    phase_count = sum(row["phase_composition_eligible"] for row in a_rows)
    observed_count = sum(row["observed_action_join_eligible"] for row in a_rows)
    observed_repositories = {
        row["physical_repository"]
        for row in a_rows
        if row["observed_action_join_eligible"]
    }
    family_gate = _family_failure_gate(a_rows)
    gates = {
        "exact_intention_denominator_30": len(a_rows) == 30,
        "audited_reference_DAG_minimum_24": audited_count >= 24,
        "observed_duration_join_minimum_21": observed_count >= 21,
        "observed_duration_physical_repositories_minimum_10": (
            len(observed_repositories) >= 10
        ),
        "maximum_systematic_failure_rate_per_task_family_0_4": all(
            value["passes_maximum_0_4"] for value in family_gate.values()
        ),
        "speedup_sign_controls_transition": False,
    }
    gates_pass = all(
        value is True
        for key, value in gates.items()
        if key != "speedup_sign_controls_transition"
    )
    # These are the four frozen scientific-result gates from
    # analysis_contract.json.  Reaching this point means every declared input
    # root and artifact has passed its seal, containment, and identity checks.
    # Missing/failed positions are evidence-bearing attrition rows, so they do
    # not make an otherwise sealed P30 bridge analysis non-scientific.  The
    # stricter gates above govern transition to P100/D, not whether P30
    # attrition and observed measurements may be reported.
    scientific_result_gates = {
        "all_30_positions_present": (
            len(a_rows) == 30
            and [row["position"] for row in a_rows] == list(range(1, 31))
        ),
        "input_and_artifact_seals_verified": True,
        "attrition_preserved": (
            len(a_rows) == 30
            and all(
                row["audited_reference_dag_eligible"]
                or bool(row["attrition_reasons"])
                for row in a_rows
            )
        ),
        "no_selection_by_result_availability_or_sign": (
            len(a_rows) == 30
            and gates["speedup_sign_controls_transition"] is False
        ),
    }
    require(
        scientific_result_gates
        == dict(analysis_contract["scientific_result_gate"]),
        "scientific-result gate implementation drift",
    )
    scientific_result = bool(
        index.get("scientific_result_requested")
        and not test_only
        and all(scientific_result_gates.values())
    )
    for row in a_rows:
        row["test_only"] = test_only
        row["scientific_result"] = scientific_result
    for row in c_rows:
        row["test_only"] = test_only
        row["scientific_result"] = scientific_result
    primary_bootstrap = repository_cluster_bootstrap(
        [
            {
                **row,
                "primary_S_infinity": _metric_from_a_row(
                    row, "observed_duration", "S_infinity"
                ),
            }
            for row in a_rows
        ],
        metric="primary_S_infinity",
        threshold=3.0,
    )
    median_gate = primary_bootstrap["median_observed"]["ci95_lower"]
    fraction_gate = primary_bootstrap[
        "fraction_at_least_threshold_over_intention"
    ]["ci95_lower"]
    common = (
        median_gate is not None
        and fraction_gate is not None
        and median_gate >= 3.0
        and fraction_gate >= 0.5
    )
    paired_c_rows = [
        row for row in c_rows if row.get("observed_ceiling") is not None
    ]
    paired_c_repositories = {
        str(row["physical_repository"]) for row in paired_c_rows
    }
    a_measurement_adequate = (
        audited_count >= 24
        and observed_count >= 21
        and len(observed_repositories) >= 10
        and all(
            value["passes_maximum_0_4"] for value in family_gate.values()
        )
    )
    c_measurement_adequate = (
        bool(paired_c_rows)
        and paired_c_repositories == HELD_OUT_REPOSITORIES
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
        "status": (
            "passed_frozen_p30_scale_transition_gates"
            if gates_pass
            else "completed_offline_analysis_with_retained_attrition"
        ),
        "test_only": test_only,
        "scientific_result_requested": bool(
            index.get("scientific_result_requested")
        ),
        "scientific_result": scientific_result,
        "primary_result": False,
        "scientific_result_interpretation": {
            "scope": "sealed_P30_intention_to_measure_and_retained_attrition_record",
            "does_not_imply_A_or_C_measurement_adequacy": True,
            "A_measurement_claim_adequate": a_measurement_adequate,
            "C_held_out_measurement_claim_adequate": c_measurement_adequate,
            "A_and_C_measurement_claims_adequate": (
                a_measurement_adequate and c_measurement_adequate
            ),
        },
        "input_bindings": {
            "analysis_contract_path": str(ANALYSIS_CONTRACT_PATH.resolve()),
            "analysis_contract_sha256": ANALYSIS_CONTRACT_SHA256,
            "analysis_contract_id": analysis_contract["contract_id"],
            "cohort_manifest_path": str(manifest_path),
            "cohort_manifest_sha256": sha256_file(manifest_path),
            "cohort_manifest_seal_sha256": manifest_seal_sha,
            "case_index_path": str(index_path),
            "case_index_sha256": sha256_file(index_path),
            "case_index_seal_sha256": index_seal_sha,
            "collection_plan_path": (
                None
                if collection_plan_path is None
                else str(collection_plan_path)
            ),
            "collection_plan_sha256": collection_plan_sha256,
            "analyzer_source_sha256": sha256_file(Path(__file__).resolve()),
            "estimator_source_sha256": ESTIMATOR_SHA256,
            "replay_helper_source_sha256": REPLAY_HELPER_SHA256,
            "type_weights_payload_sha256": TYPE_WEIGHTS_PAYLOAD_SHA256,
        },
        "offline_analysis_delta": {
            "model_or_api_invocations": 0,
            "benchmark_target_invocations": 0,
            "official_evaluator_invocations": 0,
            "task_originated_network_calls": 0,
        },
        "denominators": {
            "intention_to_measure": 30,
            "run_report_present": sum(row["run_report_present"] for row in a_rows),
            "phase_composition_eligible": phase_count,
            "DAG_audited": audited_count,
            "observed_duration_joined": observed_count,
            "observed_duration_physical_repositories": len(
                observed_repositories
            ),
            "C_unique_topology_windows": len(c_rows),
            "C_paired_observed_unique_topology_windows": sum(
                row["observed_ceiling"] is not None for row in c_rows
            ),
        },
        "attrition": {
            "case_rows_retained": 30,
            "reason_counts": dict(
                sorted(
                    Counter(
                        reason
                        for row in a_rows
                        for reason in row["attrition_reasons"]
                    ).items()
                )
            ),
            "systematic_failure_by_repository_domain_family": family_gate,
        },
        "scientific_result_gates": scientific_result_gates,
        "scale_transition_gates": gates,
        "scale_transition_gates_pass": gates_pass,
        "experiment_A": {
            "primary_space_metric": "observed-duration S_infinity = W / L",
            "finite_worker_primary_sensitivity": "P4 deterministic bottom-level list schedule",
            "finite_worker_additional_sensitivities": ["P1", "P2", "P8"],
            "phase_composition": phase_aggregation(a_rows),
            "type_weighted": summarize_graph_model(a_rows, "type_weighted"),
            "observed_duration": summarize_graph_model(
                a_rows, "observed_duration"
            ),
            "prevalence": {
                "S_infinity": a_prevalence(a_rows, "S_infinity"),
                "P4": a_prevalence(a_rows, "P4"),
            },
            "repository_cluster_bootstrap_primary_S_infinity": primary_bootstrap,
            "three_to_four_x_classification": (
                "common_under_frozen_gate"
                if common
                else "subset_or_best_case_not_common"
            ),
            "three_to_four_x_gate": {
                "repository_clustered_median_ci95_lower_minimum": 3.0,
                "repository_clustered_fraction_at_least_3x_ci95_lower_minimum": 0.5,
                "passed": common,
            },
            "strata": a_strata(a_rows),
            "claim_boundary": (
                "S_infinity and finite-worker headroom are action-layer "
                "execution-space diagnostics unless a complete augmented E2E "
                "DAG is separately established"
            ),
        },
        "experiment_C": _c_report(c_rows),
        "claim_boundary": {
            "P30_is_bridge_not_primary_population_result": True,
            "fixtures_or_synthetic_as_scientific_result": False,
            "missing_cases_silently_excluded": False,
            "C_uses_held_out_physical_repositories_only": True,
            "online_acceleration_claim": False,
        },
    }
    identity_ledger["scientific_result"] = scientific_result
    return report, a_rows, identity_ledger, c_rows


def _post_collection_recovery_policy() -> dict[str, Any]:
    return {
        "position_denominator": 30,
        "report_locator_source": "all_v8_plan_rows_in_frozen_order",
        "outcome_or_availability_selection_forbidden": True,
        "present_report_full_root_seal_required": True,
        "completed_report_phase_acceptance_required": True,
        "noncompleted_report_rejection_required": True,
        "missing_report_retention_required": True,
        "output_status": POST_COLLECTION_RECOVERY_STATUS,
        "preregistered_primary_claim_forbidden": True,
        "raw_v8_inputs_mutation_forbidden": True,
        "raw_phase_only_recovery": True,
        "DAG_A_C_extension_out_of_scope": True,
        "target_only_sidecars_out_of_scope_positions": [3, 6],
        "positions_003_006_contiguous_e2e_or_D_promotion_forbidden": True,
    }


def _recovery_repo_locator(path: Path, *, label: str) -> str:
    resolved = _path_without_symlink(
        path,
        ROOT.resolve(),
        label=label,
    )
    return resolved.relative_to(ROOT.resolve()).as_posix()


def _p30_collection_plans_by_sha256() -> dict[str, Path]:
    plans: dict[str, Path] = {}
    for path in sorted(P30_OWNER_DIR.glob("p30_collection_plan*.json")):
        require(
            path.is_file() and not path.is_symlink(),
            f"unsafe P30 collection plan candidate: {path}",
        )
        digest = sha256_file(path)
        require(
            digest not in plans,
            f"duplicate P30 collection plan bytes: {path}",
        )
        plans[digest] = path
    require(bool(plans), "P30 collection plan lineage missing")
    return plans


def build_post_collection_recovery_amendment() -> dict[str, Any]:
    """Build the deterministic all-locator post-outcome amendment payload."""

    require(
        P30_V8_COLLECTION_PLAN_PATH.is_file()
        and not P30_V8_COLLECTION_PLAN_PATH.is_symlink()
        and sha256_file(P30_V8_COLLECTION_PLAN_PATH)
        == P30_V8_COLLECTION_PLAN_SHA256,
        "v8 collection plan identity drift",
    )
    plan = read_json(P30_V8_COLLECTION_PLAN_PATH)
    plan_bindings = plan.get("global_bindings")
    require(
        isinstance(plan_bindings, Mapping)
        and plan_bindings.get("analyzer_source_sha256")
        == P30_V8_ORIGINAL_ANALYZER_SHA256,
        "v8 original analyzer binding drift",
    )
    manifest_path = P30_OWNER_DIR / "p30_freeze/cohort_manifest.json"
    verify_file_in_sibling_seal(manifest_path)
    manifest_cases = validate_manifest(read_json(manifest_path))
    plan_rows = validate_collection_plan(
        plan,
        manifest_cases,
        test_only=True,
    )
    plan_lineage = _p30_collection_plans_by_sha256()
    report_rows: list[dict[str, Any]] = []
    for plan_row, frozen in zip(plan_rows, manifest_cases):
        position = int(plan_row["position"])
        root_relative = _safe_relative(
            plan_row["result_root"],
            label=f"recovery amendment row {position} result root",
        )
        run_root = _path_without_symlink(
            ROOT.joinpath(*root_relative.parts),
            ROOT.resolve(),
            label=f"recovery amendment row {position} result root",
        )
        report_path = run_root / "run_report.json"
        present = report_path.is_file()
        source_plan_path: Path | None = None
        source_plan_sha256: str | None = None
        source_plan_row_sha256: str | None = None
        run_root_seal_sha256: str | None = None
        run_report_sha256: str | None = None
        terminal_state: str | None = None
        if present:
            run_root_seal_sha256 = sha256_file(run_root / "SHA256SUMS")
            seal_rows = verify_sealed_root(
                run_root,
                run_root_seal_sha256,
            )
            require(
                seal_rows.get("run_report.json") == sha256_file(report_path),
                f"recovery amendment row {position} report seal drift",
            )
            source_report = read_json(report_path)
            source_plan_sha256 = str(
                source_report.get("collection_plan_sha256") or ""
            )
            require(
                source_plan_sha256 in plan_lineage,
                f"recovery amendment row {position} source plan unknown",
            )
            source_plan_path = plan_lineage[source_plan_sha256]
            source_plan_payload = read_json(source_plan_path)
            require(
                (
                    source_plan_payload.get("global_bindings") or {}
                ).get("analyzer_source_sha256")
                == P30_V8_ORIGINAL_ANALYZER_SHA256,
                f"recovery amendment row {position} source analyzer "
                "binding drift",
            )
            source_plan_rows = validate_collection_plan(
                source_plan_payload,
                manifest_cases,
                test_only=True,
            )
            source_plan_row = source_plan_rows[position - 1]
            for field in (
                "position",
                "case_id",
                "instance_id",
                "physical_repository",
                "base_commit",
                "run_id",
                "result_root",
            ):
                require(
                    source_plan_row[field] == plan_row[field],
                    f"recovery amendment row {position} source-to-v8 "
                    f"projection drift: {field}",
                )
            source_plan_row_sha256 = source_plan_row[
                "binding_payload_sha256"
            ]
            require(
                source_report.get("collection_plan_case_binding_sha256")
                == source_plan_row_sha256,
                f"recovery amendment row {position} source plan-row drift",
            )
            run_report_sha256 = sha256_file(report_path)
            terminal_state = str(source_report.get("terminal_state") or "")
            require(
                bool(terminal_state),
                f"recovery amendment row {position} terminal missing",
            )
        else:
            require(
                not run_root.exists(),
                f"recovery amendment row {position} partial result root "
                "cannot be frozen",
            )
        report_rows.append(
            {
                "position": position,
                "case_id": frozen["case_id"],
                "instance_id": frozen["instance_id"],
                "physical_repository": frozen["physical_repository"],
                "base_commit": frozen["base_commit"],
                "run_id": plan_row["run_id"],
                "result_root": plan_row["result_root"],
                "report_path": f"{plan_row['result_root']}/run_report.json",
                "collection_plan_case_binding_sha256": plan_row[
                    "binding_payload_sha256"
                ],
                "source_collection_plan_path": (
                    _recovery_repo_locator(
                        source_plan_path,
                        label=f"recovery row {position} source plan",
                    )
                    if source_plan_path is not None
                    else None
                ),
                "source_collection_plan_sha256": source_plan_sha256,
                "source_collection_plan_case_binding_sha256": (
                    source_plan_row_sha256
                ),
                "presence_at_recovery_freeze": present,
                "run_root_seal_sha256": run_root_seal_sha256,
                "run_report_sha256": run_report_sha256,
                "terminal_state": terminal_state,
            }
        )
    return {
        "schema_version": POST_COLLECTION_RECOVERY_SCHEMA_VERSION,
        "amendment_id": POST_COLLECTION_RECOVERY_AMENDMENT_ID,
        "status": POST_COLLECTION_RECOVERY_STATUS,
        "result_role": POST_COLLECTION_RECOVERY_STATUS,
        "scientific_result": False,
        "preregistered_primary": False,
        "execution_authorized_by_this_file": False,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
        "source_bindings": {
            "collection_plan_path": _recovery_repo_locator(
                P30_V8_COLLECTION_PLAN_PATH,
                label="v8 collection plan",
            ),
            "collection_plan_sha256": P30_V8_COLLECTION_PLAN_SHA256,
            "original_frozen_analyzer_source_sha256": (
                P30_V8_ORIGINAL_ANALYZER_SHA256
            ),
            "contract_fixed_analyzer_source_sha256": (
                P30_CONTRACT_FIXED_ANALYZER_SHA256
            ),
            "contract_fix_commit": P30_CONTRACT_FIX_COMMIT,
            "recovery_driver_path": _recovery_repo_locator(
                Path(__file__).resolve(),
                label="recovery analyzer source",
            ),
            "recovery_driver_source_sha256": sha256_file(
                Path(__file__).resolve()
            ),
        },
        "recovery_policy": _post_collection_recovery_policy(),
        "report_rows": report_rows,
    }


def write_post_collection_recovery_amendment(output_path: Path) -> dict[str, Any]:
    resolved = output_path.resolve()
    require(
        resolved == POST_COLLECTION_RECOVERY_AMENDMENT_PATH.resolve(),
        "post-collection recovery amendment output locator drift",
    )
    require(
        not resolved.exists() and not resolved.is_symlink(),
        "post-collection recovery amendment output must not already exist",
    )
    payload = build_post_collection_recovery_amendment()
    require(
        all(row["presence_at_recovery_freeze"] for row in payload["report_rows"]),
        "all 30 v8 report locators must be present before formal amendment freeze",
    )
    _write_exclusive(resolved, pretty_bytes(payload))
    validate_post_collection_recovery_amendment(resolved)
    return payload


def validate_post_collection_recovery_amendment(
    amendment_path: Path,
) -> dict[str, Any]:
    """Validate the exact post-outcome bridge without weakening v8 itself."""

    resolved_amendment = amendment_path.resolve()
    require(
        resolved_amendment == POST_COLLECTION_RECOVERY_AMENDMENT_PATH.resolve(),
        "post-collection recovery amendment locator drift",
    )
    require(
        resolved_amendment.is_file() and not resolved_amendment.is_symlink(),
        "post-collection recovery amendment missing or unsafe",
    )
    amendment = read_json(resolved_amendment)
    expected_top_level = {
        "schema_version",
        "amendment_id",
        "status",
        "result_role",
        "scientific_result",
        "preregistered_primary",
        "execution_authorized_by_this_file",
        "design_id",
        "campaign_id",
        "cohort_membership_sha256",
        "source_bindings",
        "recovery_policy",
        "report_rows",
    }
    require(
        set(amendment) == expected_top_level,
        "post-collection recovery amendment field closure mismatch",
    )
    expected_identity = {
        "schema_version": POST_COLLECTION_RECOVERY_SCHEMA_VERSION,
        "amendment_id": POST_COLLECTION_RECOVERY_AMENDMENT_ID,
        "status": POST_COLLECTION_RECOVERY_STATUS,
        "result_role": POST_COLLECTION_RECOVERY_STATUS,
        "scientific_result": False,
        "preregistered_primary": False,
        "execution_authorized_by_this_file": False,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
    }
    for field, expected in expected_identity.items():
        actual = amendment.get(field)
        require(
            type(actual) is type(expected) and actual == expected,
            f"post-collection recovery amendment drift: {field}",
        )
    require_exact_mapping(
        amendment.get("recovery_policy"),
        _post_collection_recovery_policy(),
        label="post-collection recovery policy",
    )
    source_bindings = amendment.get("source_bindings")
    require(
        isinstance(source_bindings, Mapping)
        and set(source_bindings)
        == {
            "collection_plan_path",
            "collection_plan_sha256",
            "original_frozen_analyzer_source_sha256",
            "contract_fixed_analyzer_source_sha256",
            "contract_fix_commit",
            "recovery_driver_path",
            "recovery_driver_source_sha256",
        },
        "post-collection recovery source binding field closure mismatch",
    )
    expected_plan_locator = _recovery_repo_locator(
        P30_V8_COLLECTION_PLAN_PATH,
        label="v8 collection plan",
    )
    expected_driver_locator = _recovery_repo_locator(
        Path(__file__).resolve(),
        label="recovery analyzer source",
    )
    expected_source_bindings = {
        "collection_plan_path": expected_plan_locator,
        "collection_plan_sha256": P30_V8_COLLECTION_PLAN_SHA256,
        "original_frozen_analyzer_source_sha256": (
            P30_V8_ORIGINAL_ANALYZER_SHA256
        ),
        "contract_fixed_analyzer_source_sha256": (
            P30_CONTRACT_FIXED_ANALYZER_SHA256
        ),
        "contract_fix_commit": P30_CONTRACT_FIX_COMMIT,
        "recovery_driver_path": expected_driver_locator,
        "recovery_driver_source_sha256": sha256_file(
            Path(__file__).resolve()
        ),
    }
    require_exact_mapping(
        source_bindings,
        expected_source_bindings,
        label="post-collection recovery source bindings",
    )
    require(
        P30_V8_COLLECTION_PLAN_PATH.is_file()
        and not P30_V8_COLLECTION_PLAN_PATH.is_symlink()
        and sha256_file(P30_V8_COLLECTION_PLAN_PATH)
        == P30_V8_COLLECTION_PLAN_SHA256,
        "v8 collection plan identity drift",
    )
    plan = read_json(P30_V8_COLLECTION_PLAN_PATH)
    plan_bindings = plan.get("global_bindings")
    require(
        isinstance(plan_bindings, Mapping)
        and plan_bindings.get("analyzer_source_sha256")
        == P30_V8_ORIGINAL_ANALYZER_SHA256,
        "v8 original analyzer binding drift",
    )
    manifest_path = P30_OWNER_DIR / "p30_freeze/cohort_manifest.json"
    verify_file_in_sibling_seal(manifest_path)
    manifest_cases = validate_manifest(read_json(manifest_path))
    plan_rows = validate_collection_plan(
        plan,
        manifest_cases,
        test_only=True,
    )
    raw_report_rows = amendment.get("report_rows")
    require(
        isinstance(raw_report_rows, list) and len(raw_report_rows) == 30,
        "post-collection recovery must cover exactly 30 report locators",
    )
    expected_row_fields = {
        "position",
        "case_id",
        "instance_id",
        "physical_repository",
        "base_commit",
        "run_id",
        "result_root",
        "report_path",
        "collection_plan_case_binding_sha256",
        "source_collection_plan_path",
        "source_collection_plan_sha256",
        "source_collection_plan_case_binding_sha256",
        "presence_at_recovery_freeze",
        "run_root_seal_sha256",
        "run_report_sha256",
        "terminal_state",
    }
    normalized_rows: list[dict[str, Any]] = []
    for position, (raw, plan_row, frozen) in enumerate(
        zip(raw_report_rows, plan_rows, manifest_cases),
        1,
    ):
        require(
            isinstance(raw, Mapping) and set(raw) == expected_row_fields,
            f"post-collection recovery row {position} field closure mismatch",
        )
        expected_report_path = f"{plan_row['result_root']}/run_report.json"
        expected_row_identity = {
            "position": position,
            "case_id": frozen["case_id"],
            "instance_id": frozen["instance_id"],
            "physical_repository": frozen["physical_repository"],
            "base_commit": frozen["base_commit"],
            "run_id": plan_row["run_id"],
            "result_root": plan_row["result_root"],
            "report_path": expected_report_path,
            "collection_plan_case_binding_sha256": plan_row[
                "binding_payload_sha256"
            ],
        }
        for field, expected in expected_row_identity.items():
            actual = raw.get(field)
            require(
                type(actual) is type(expected) and actual == expected,
                f"post-collection recovery row {position} drift: {field}",
            )
        present = raw.get("presence_at_recovery_freeze")
        require(
            type(present) is bool,
            f"post-collection recovery row {position} presence must be boolean",
        )
        if present:
            for field in (
                "source_collection_plan_sha256",
                "source_collection_plan_case_binding_sha256",
                "run_root_seal_sha256",
                "run_report_sha256",
            ):
                value = raw.get(field)
                require(
                    isinstance(value, str)
                    and SHA256_RE.fullmatch(value) is not None,
                    f"post-collection recovery row {position} malformed {field}",
                )
            require(
                isinstance(raw.get("source_collection_plan_path"), str)
                and bool(raw["source_collection_plan_path"]),
                f"post-collection recovery row {position} source plan missing",
            )
            require(
                isinstance(raw.get("terminal_state"), str)
                and bool(raw["terminal_state"]),
                f"post-collection recovery row {position} terminal missing",
            )
        else:
            require(
                raw.get("source_collection_plan_path") is None
                and raw.get("source_collection_plan_sha256") is None
                and raw.get(
                    "source_collection_plan_case_binding_sha256"
                )
                is None
                and raw.get("run_root_seal_sha256") is None
                and raw.get("run_report_sha256") is None
                and raw.get("terminal_state") is None,
                f"post-collection recovery row {position} absence fields drift",
            )
        normalized_rows.append(dict(raw))
    require(
        [row["position"] for row in normalized_rows] == list(range(1, 31)),
        "post-collection recovery position set or order drift",
    )

    validated_rows: list[dict[str, Any]] = []
    for row, plan_row, frozen in zip(
        normalized_rows,
        plan_rows,
        manifest_cases,
    ):
        position = int(row["position"])
        root_relative = _safe_relative(
            str(row["result_root"]),
            label=f"recovery row {position} result root",
        )
        report_relative = _safe_relative(
            str(row["report_path"]),
            label=f"recovery row {position} report",
        )
        run_root = _path_without_symlink(
            ROOT.joinpath(*root_relative.parts),
            ROOT.resolve(),
            label=f"recovery row {position} result root",
        )
        report_path = _path_without_symlink(
            ROOT.joinpath(*report_relative.parts),
            ROOT.resolve(),
            label=f"recovery row {position} report",
        )
        if not row["presence_at_recovery_freeze"]:
            require(
                not run_root.exists() and not report_path.exists(),
                f"post-collection recovery row {position} availability drift",
            )
            validated_rows.append(
                {
                    **row,
                    "_run_root": run_root,
                    "_run_report_path": report_path,
                    "_run_report": None,
                }
            )
            continue
        source_plan_relative = _safe_relative(
            str(row["source_collection_plan_path"]),
            label=f"recovery row {position} source collection plan",
        )
        source_plan_path = _path_without_symlink(
            ROOT.joinpath(*source_plan_relative.parts),
            ROOT.resolve(),
            label=f"recovery row {position} source collection plan",
        )
        try:
            source_plan_path.relative_to(P30_OWNER_DIR.resolve())
        except ValueError as exc:
            raise AnalysisError(
                f"post-collection recovery row {position} source plan "
                "escapes P30 owner"
            ) from exc
        require(
            source_plan_path.is_file()
            and not source_plan_path.is_symlink()
            and source_plan_path.name.startswith("p30_collection_plan")
            and source_plan_path.suffix == ".json"
            and sha256_file(source_plan_path)
            == row["source_collection_plan_sha256"],
            f"post-collection recovery row {position} source plan drift",
        )
        source_plan_payload = read_json(source_plan_path)
        require(
            (
                source_plan_payload.get("global_bindings") or {}
            ).get("analyzer_source_sha256")
            == P30_V8_ORIGINAL_ANALYZER_SHA256,
            f"post-collection recovery row {position} source analyzer "
            "binding drift",
        )
        source_plan_rows = validate_collection_plan(
            source_plan_payload,
            manifest_cases,
            test_only=True,
        )
        source_plan_row = source_plan_rows[position - 1]
        for field in (
            "position",
            "case_id",
            "instance_id",
            "physical_repository",
            "base_commit",
            "run_id",
            "result_root",
        ):
            require(
                source_plan_row[field] == plan_row[field],
                f"post-collection recovery row {position} source-to-v8 "
                f"projection drift: {field}",
            )
        require(
            source_plan_row["binding_payload_sha256"]
            == row["source_collection_plan_case_binding_sha256"],
            f"post-collection recovery row {position} source plan-row drift",
        )
        seal_rows = verify_sealed_root(
            run_root,
            str(row["run_root_seal_sha256"]),
        )
        require(
            seal_rows.get("run_report.json") == row["run_report_sha256"]
            and sha256_file(report_path) == row["run_report_sha256"],
            f"post-collection recovery row {position} report digest drift",
        )
        report = read_json(report_path)
        require(
            report.get("terminal_state") == row["terminal_state"],
            f"post-collection recovery row {position} outcome drift",
        )
        validate_run_identity(
            report,
            frozen,
            {
                "_collection_plan_sha256": row[
                    "source_collection_plan_sha256"
                ],
                "run_id": plan_row["run_id"],
                "_collection_plan_case_binding_sha256": row[
                    "source_collection_plan_case_binding_sha256"
                ],
                "authorization_sha256": report.get("authorization_sha256"),
                "_plan_result_root": plan_row["result_root"],
            },
        )
        report["_run_report_path"] = str(report_path)
        validated_rows.append(
            {
                **row,
                "_run_root": run_root,
                "_run_report_path": report_path,
                "_run_report": report,
            }
        )
    return {
        "amendment": amendment,
        "amendment_path": resolved_amendment,
        "amendment_sha256": sha256_file(resolved_amendment),
        "collection_plan_path": P30_V8_COLLECTION_PLAN_PATH.resolve(),
        "collection_plan_sha256": P30_V8_COLLECTION_PLAN_SHA256,
        "rows": validated_rows,
    }


def build_post_collection_recovery(
    amendment_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validated = validate_post_collection_recovery_amendment(amendment_path)
    rows: list[dict[str, Any]] = []
    for source in validated["rows"]:
        report = source["_run_report"]
        phase: dict[str, Any] | None = None
        rejection_reasons: list[str] = []
        if report is None:
            disposition = "not_collected_at_recovery_freeze"
            rejection_reasons = ["report_not_present_at_recovery_freeze"]
        elif report.get("terminal_state") == (
            "completed_target_and_official_evaluator"
        ):
            try:
                phase, _ = extract_phase_composition(report)
            except EvidenceIneligible as exc:
                raise AnalysisError(
                    f"position {source['position']}: fixed analyzer rejected "
                    f"a completed sealed report: {exc}"
                ) from exc
            disposition = "accepted_completed_phase_composition"
        else:
            try:
                extract_phase_composition(report)
            except EvidenceIneligible as exc:
                rejection_reasons = list(exc.reasons)
            else:
                raise AnalysisError(
                    f"position {source['position']}: noncompleted report was "
                    "accepted by the fixed analyzer"
                )
            require(
                "target_or_official_evaluator_incomplete"
                in rejection_reasons,
                f"position {source['position']}: noncompleted report did not "
                "fail the whole-task completion gate",
            )
            disposition = "retained_noncompleted_report_rejection"
        rows.append(
            {
                "position": source["position"],
                "case_id": source["case_id"],
                "instance_id": source["instance_id"],
                "physical_repository": source["physical_repository"],
                "run_id": source["run_id"],
                "report_path": source["report_path"],
                "source_collection_plan_path": source[
                    "source_collection_plan_path"
                ],
                "source_collection_plan_sha256": source[
                    "source_collection_plan_sha256"
                ],
                "source_collection_plan_case_binding_sha256": source[
                    "source_collection_plan_case_binding_sha256"
                ],
                "source_run_root_seal_sha256": source[
                    "run_root_seal_sha256"
                ],
                "source_run_report_sha256": source["run_report_sha256"],
                "source_terminal_state": source["terminal_state"],
                "analysis_disposition": disposition,
                "whole_task_phase_composition_eligible": phase is not None,
                "phase_composition": phase,
                "rejection_reasons": rejection_reasons,
                "result_role": POST_COLLECTION_RECOVERY_STATUS,
                "scientific_result": False,
                "preregistered_primary": False,
            }
        )
    accepted = [
        row for row in rows if row["whole_task_phase_composition_eligible"]
    ]
    rejected = [
        row
        for row in rows
        if row["analysis_disposition"]
        == "retained_noncompleted_report_rejection"
    ]
    missing = [
        row
        for row in rows
        if row["analysis_disposition"]
        == "not_collected_at_recovery_freeze"
    ]
    report = {
        "schema_version": "sge-p30-post-collection-recovered-analysis-v1",
        "status": POST_COLLECTION_RECOVERY_STATUS,
        "result_role": POST_COLLECTION_RECOVERY_STATUS,
        "scientific_result": False,
        "preregistered_primary": False,
        "primary_result": False,
        "design_id": DESIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "cohort_membership_sha256": COHORT_MEMBERSHIP_SHA256,
        "provenance": {
            "amendment_path": _recovery_repo_locator(
                validated["amendment_path"],
                label="post-collection recovery amendment",
            ),
            "amendment_sha256": validated["amendment_sha256"],
            **dict(validated["amendment"]["source_bindings"]),
        },
        "recovery_policy": _post_collection_recovery_policy(),
        "coverage": {
            "v8_plan_positions": 30,
            "report_locators_covered": len(rows),
            "reports_present_at_recovery_freeze": len(accepted) + len(rejected),
            "reports_missing_at_recovery_freeze": len(missing),
            "completed_reports_accepted": len(accepted),
            "noncompleted_reports_rejected": len(rejected),
            "source_collection_plan_sha256s": sorted(
                {
                    str(row["source_collection_plan_sha256"])
                    for row in rows
                    if row["source_collection_plan_sha256"] is not None
                }
            ),
        },
        "whole_task_phase_composition": phase_aggregation(
            [
                {
                    "physical_repository": row["physical_repository"],
                    "phase_composition": row["phase_composition"],
                }
                for row in rows
            ]
        ),
        "known_evidence_boundaries": {
            "positions_003_006_have_separate_target_action_layer_sidecars": True,
            "positions_003_006_sidecars_consumed_by_this_recovery": False,
            "positions_003_006_whole_task_E2E_eligible": False,
            "positions_003_006_D_paired_evidence_eligible": False,
            "separately_versioned_target_action_layer_analyzer_required": True,
            "stage_A_duration_blind_mapping_consumed": False,
            "stage_B_disposition_overlay_consumed": False,
            "stage_B_moved_action_durations_accounted_as_system_envelope": False,
            "direct_effective_DAG_remap_forbidden": True,
            "separately_versioned_stage_A_stage_B_overlay_analyzer_required": (
                True
            ),
        },
        "offline_analysis_delta": {
            "model_or_api_invocations": 0,
            "benchmark_target_invocations": 0,
            "official_evaluator_invocations": 0,
            "task_originated_network_calls": 0,
        },
        "claim_boundary": {
            "post_collection_contract_recovery_not_preregistered_primary": True,
            "raw_v8_reports_or_plan_rewritten": False,
            "outcome_selected_subset": False,
            "online_acceleration_claim": False,
        },
    }
    require(
        len(rows) == 30
        and [row["position"] for row in rows] == list(range(1, 31)),
        "post-collection recovered output lost the frozen denominator",
    )
    return report, rows


def _write_exclusive(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, value)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _seal_output(root: Path) -> None:
    inventory = {
        "schema_version": "sge-primary-ac-p30-artifact-inventory-v1",
        "artifacts": [
            {
                "path": name,
                "bytes": (root / name).stat().st_size,
                "sha256": sha256_file(root / name),
            }
            for name in OUTPUT_DATA_FILES
        ],
    }
    _write_exclusive(root / "artifact_inventory.json", pretty_bytes(inventory))
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(root / name)}  {name}\n" for name in OUTPUT_FILES),
        encoding="utf-8",
    )


def _seal_post_collection_recovery_output(root: Path) -> None:
    inventory = {
        "schema_version": (
            "sge-p30-post-collection-recovery-artifact-inventory-v1"
        ),
        "artifacts": [
            {
                "path": name,
                "bytes": (root / name).stat().st_size,
                "sha256": sha256_file(root / name),
            }
            for name in POST_COLLECTION_RECOVERY_OUTPUT_DATA_FILES
        ],
    }
    _write_exclusive(root / "artifact_inventory.json", pretty_bytes(inventory))
    (root / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(root / name)}  {name}\n"
            for name in POST_COLLECTION_RECOVERY_OUTPUT_FILES
        ),
        encoding="utf-8",
    )


def _publish_directory_no_replace(source: Path, destination: Path) -> None:
    """Publish one prepared directory without ever replacing an existing path."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    renamex = getattr(libc, "renamex_np", None)
    if renamex is not None:
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex.restype = ctypes.c_int
        if renamex(source_raw, destination_raw, 0x00000004) == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise AnalysisError("result root must not already exist")
        raise OSError(error, os.strerror(error), str(destination))
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, source_raw, -100, destination_raw, 1) == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise AnalysisError("result root must not already exist")
        raise OSError(error, os.strerror(error), str(destination))
    raise AnalysisError(
        "atomic no-replace directory publication is unavailable; "
        "prepared source was preserved"
    )


def write_bundle(
    cohort_manifest_path: Path, case_index_path: Path, result_root: Path
) -> dict[str, Any]:
    require(not result_root.exists(), "result root must not already exist")
    report, a_rows, identity_ledger, c_rows = build_analysis(
        cohort_manifest_path, case_index_path
    )
    parent = result_root.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{result_root.name}.prepare-", dir=parent)
    )
    try:
        payloads = {
            "analysis_report.json": report,
            "a_case_rows.json": a_rows,
            "observed_action_identity_ledger.json": identity_ledger,
            "c_candidate_rows.json": c_rows,
        }
        for name, value in payloads.items():
            _write_exclusive(temporary / name, pretty_bytes(value))
        _seal_output(temporary)
        _publish_directory_no_replace(temporary, result_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def write_post_collection_recovery_bundle(
    amendment_path: Path,
    result_root: Path,
) -> dict[str, Any]:
    result_root = result_root.resolve()
    require(
        not result_root.exists() and not result_root.is_symlink(),
        "result root must not already exist",
    )
    report, rows = build_post_collection_recovery(amendment_path)
    result_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{result_root.name}.tmp-",
            dir=str(result_root.parent),
        )
    )
    try:
        _write_exclusive(
            temporary / "recovery_report.json",
            pretty_bytes(report),
        )
        _write_exclusive(
            temporary / "recovered_phase_rows.json",
            pretty_bytes(rows),
        )
        _seal_post_collection_recovery_output(temporary)
        _publish_directory_no_replace(temporary, result_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def verify_output_seal(root: Path) -> None:
    require(root.is_dir() and not root.is_symlink(), "result root missing or unsafe")
    rows = parse_sha256s(root / "SHA256SUMS")
    require(set(rows) == set(OUTPUT_FILES), "result seal file set mismatch")
    require(
        all(not path.is_symlink() for path in root.rglob("*")),
        "result root contains symlink",
    )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    require(actual == set(OUTPUT_FILES), "result root contains unsealed artifacts")
    for name, digest in rows.items():
        require(sha256_file(root / name) == digest, f"result tamper detected: {name}")
    inventory = read_json(root / "artifact_inventory.json")
    artifacts = inventory.get("artifacts")
    require(isinstance(artifacts, list), "result inventory malformed")
    indexed = {
        str(row["path"]): (int(row["bytes"]), str(row["sha256"]))
        for row in artifacts
        if isinstance(row, Mapping)
    }
    require(
        indexed
        == {
            name: ((root / name).stat().st_size, sha256_file(root / name))
            for name in OUTPUT_DATA_FILES
        },
        "result inventory mismatch",
    )


def verify_post_collection_recovery_output_seal(root: Path) -> None:
    require(root.is_dir() and not root.is_symlink(), "result root missing or unsafe")
    rows = parse_sha256s(root / "SHA256SUMS")
    require(
        set(rows) == set(POST_COLLECTION_RECOVERY_OUTPUT_FILES),
        "recovery result seal file set mismatch",
    )
    require(
        all(not path.is_symlink() for path in root.rglob("*")),
        "recovery result root contains symlink",
    )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    require(
        actual == set(POST_COLLECTION_RECOVERY_OUTPUT_FILES),
        "recovery result root contains unsealed artifacts",
    )
    for name, digest in rows.items():
        require(
            sha256_file(root / name) == digest,
            f"recovery result tamper detected: {name}",
        )
    inventory = read_json(root / "artifact_inventory.json")
    require(
        inventory.get("schema_version")
        == "sge-p30-post-collection-recovery-artifact-inventory-v1",
        "recovery result inventory schema drift",
    )
    artifacts = inventory.get("artifacts")
    require(isinstance(artifacts, list), "recovery result inventory malformed")
    indexed = {
        str(row["path"]): (int(row["bytes"]), str(row["sha256"]))
        for row in artifacts
        if isinstance(row, Mapping)
    }
    require(
        indexed
        == {
            name: ((root / name).stat().st_size, sha256_file(root / name))
            for name in POST_COLLECTION_RECOVERY_OUTPUT_DATA_FILES
        },
        "recovery result inventory mismatch",
    )


def verify_bundle(result_root: Path) -> dict[str, Any]:
    root = result_root.resolve()
    verify_output_seal(root)
    report = read_json(root / "analysis_report.json")
    bindings = report.get("input_bindings")
    require(isinstance(bindings, Mapping), "analysis input bindings missing")
    require(
        bindings.get("analysis_contract_path")
        == str(ANALYSIS_CONTRACT_PATH.resolve())
        and bindings.get("analysis_contract_sha256") == ANALYSIS_CONTRACT_SHA256
        and bindings.get("analysis_contract_id") == ANALYSIS_CONTRACT_ID,
        "analysis contract binding drift",
    )
    manifest_path = Path(str(bindings.get("cohort_manifest_path") or ""))
    index_path = Path(str(bindings.get("case_index_path") or ""))
    require(
        sha256_file(manifest_path) == bindings.get("cohort_manifest_sha256"),
        "cohort manifest changed after analysis",
    )
    require(
        sha256_file(index_path) == bindings.get("case_index_sha256"),
        "case index changed after analysis",
    )
    current = build_analysis(manifest_path, index_path)
    expected_payloads = {
        "analysis_report.json": current[0],
        "a_case_rows.json": current[1],
        "observed_action_identity_ledger.json": current[2],
        "c_candidate_rows.json": current[3],
    }
    for name, value in expected_payloads.items():
        require(
            read_json_value(root / name) == value,
            f"analysis artifact no longer recomputes exactly: {name}",
        )
    require(
        len(current[1]) == 30,
        "verified result lost intention-to-measure rows",
    )
    return {
        "status": "passed",
        "scientific_result": bool(current[0]["scientific_result"]),
        "intention_to_measure": 30,
        "DAG_audited": current[0]["denominators"]["DAG_audited"],
        "observed_duration_joined": current[0]["denominators"][
            "observed_duration_joined"
        ],
        "C_unique_topology_windows": current[0]["denominators"][
            "C_unique_topology_windows"
        ],
        "sealed_artifact_count": len(OUTPUT_FILES),
    }


def verify_post_collection_recovery_bundle(
    result_root: Path,
) -> dict[str, Any]:
    root = result_root.resolve()
    verify_post_collection_recovery_output_seal(root)
    stored_report = read_json(root / "recovery_report.json")
    provenance = stored_report.get("provenance")
    require(
        isinstance(provenance, Mapping),
        "recovery result provenance missing",
    )
    amendment_relative = _safe_relative(
        str(provenance.get("amendment_path") or ""),
        label="recovery result amendment",
    )
    amendment_path = _path_without_symlink(
        ROOT.joinpath(*amendment_relative.parts),
        ROOT.resolve(),
        label="recovery result amendment",
    )
    require(
        sha256_file(amendment_path) == provenance.get("amendment_sha256"),
        "recovery amendment changed after analysis",
    )
    current_report, current_rows = build_post_collection_recovery(
        amendment_path
    )
    require(
        read_json_value(root / "recovery_report.json") == current_report,
        "recovery report no longer recomputes exactly",
    )
    require(
        read_json_value(root / "recovered_phase_rows.json") == current_rows,
        "recovered phase rows no longer recompute exactly",
    )
    return {
        "status": "passed",
        "result_role": POST_COLLECTION_RECOVERY_STATUS,
        "scientific_result": False,
        "preregistered_primary": False,
        "report_locators_covered": current_report["coverage"][
            "report_locators_covered"
        ],
        "completed_reports_accepted": current_report["coverage"][
            "completed_reports_accepted"
        ],
        "noncompleted_reports_rejected": current_report["coverage"][
            "noncompleted_reports_rejected"
        ],
        "reports_missing_at_recovery_freeze": current_report["coverage"][
            "reports_missing_at_recovery_freeze"
        ],
        "sealed_artifact_count": len(
            POST_COLLECTION_RECOVERY_OUTPUT_FILES
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--cohort-manifest", type=Path, required=True)
    prepare.add_argument("--case-index", type=Path, required=True)
    prepare.add_argument("--result-root", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--result-root", type=Path, required=True)
    freeze_recovery = subparsers.add_parser(
        "freeze-recovery-amendment"
    )
    freeze_recovery.add_argument("--output", type=Path, required=True)
    recover = subparsers.add_parser("recover-v8")
    recover.add_argument("--amendment", type=Path, required=True)
    recover.add_argument("--result-root", type=Path, required=True)
    verify_recovery = subparsers.add_parser("verify-recovery")
    verify_recovery.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            report = write_bundle(
                args.cohort_manifest,
                args.case_index,
                args.result_root,
            )
            result = {
                "status": report["status"],
                "scientific_result": report["scientific_result"],
                "denominators": report["denominators"],
                "result_root": str(args.result_root),
            }
        elif args.command == "verify":
            result = verify_bundle(args.result_root)
        elif args.command == "freeze-recovery-amendment":
            amendment = write_post_collection_recovery_amendment(
                args.output
            )
            result = {
                "status": amendment["status"],
                "result_role": amendment["result_role"],
                "scientific_result": amendment["scientific_result"],
                "preregistered_primary": amendment[
                    "preregistered_primary"
                ],
                "report_locators_frozen": len(amendment["report_rows"]),
                "output": str(args.output),
            }
        elif args.command == "recover-v8":
            report = write_post_collection_recovery_bundle(
                args.amendment,
                args.result_root,
            )
            result = {
                "status": report["status"],
                "result_role": report["result_role"],
                "scientific_result": report["scientific_result"],
                "preregistered_primary": report["preregistered_primary"],
                "coverage": report["coverage"],
                "result_root": str(args.result_root),
            }
        else:
            result = verify_post_collection_recovery_bundle(
                args.result_root
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AnalysisError, EvidenceIneligible, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
