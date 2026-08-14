#!/usr/bin/env python3
"""Offline, sealed recomputation of Experiment C1 structural ceilings.

This analyzer deliberately implements only the type-weighted work/span ceiling
and threshold admission rule.  It cannot call a model, benchmark target,
official evaluator, or network service.  The observed-duration counterpart is
a structural reference ceiling, not realized executor speedup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "experiments/perfect_speculation_speedup_bound/ceiling_admission/"
    "structural_c1_20260729/analysis_contract.json"
)
DEFAULT_OUTPUT_ROOT = ROOT / "results/sge_c1_structural_validation_20260729"
OUTPUT_DATA_FILES = (
    "structural_validation_report.json",
    "window_rows.json",
    "attrition_ledger.json",
)
OUTPUT_FILES = (*OUTPUT_DATA_FILES, "artifact_inventory.json")
SCHEMA_VERSION = "sge-c1-structural-validation-result-v1"
CONTRACT_ID = "SGE-C1-STRUCTURAL-VALIDATION-20260729-V1"
RESULT_ROLE = "retrospective_supporting_structural_validation"
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
HELD_OUT_REPOSITORIES = frozenset(
    {
        "django/django",
        "pydata/xarray",
        "pytest-dev/pytest",
        "scikit-learn/scikit-learn",
    }
)
WORKERS = (2, 4, 8)
PRIMARY_WORKER = 4
THRESHOLDS = (1.05, 1.10, 1.25)
PRIMARY_THRESHOLD = 1.10
DEPTHS: tuple[int | str, ...] = (1, 2, 3, "full")
WIDTHS = (1, 2, 4, 8)
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = "sge-c1-structural-validation-20260729-v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class AnalysisError(RuntimeError):
    """A frozen input, formula, identity, or output invariant failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


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
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise AnalysisError(f"invalid JSON {path}: {exc}") from exc


def read_json_object(path: Path) -> dict[str, Any]:
    value = read_json_value(path)
    require(isinstance(value, dict), f"{path}: JSON object required")
    return value


def safe_relative(value: str, *, label: str) -> PurePosixPath:
    require(isinstance(value, str) and bool(value), f"{label}: path required")
    path = PurePosixPath(value)
    require(not path.is_absolute(), f"{label}: absolute path forbidden")
    require(
        all(part not in {"", ".", ".."} for part in path.parts),
        f"{label}: unsafe path",
    )
    return path


def parse_sha256s(path: Path) -> dict[str, str]:
    require(path.is_file() and not path.is_symlink(), f"missing seal: {path}")
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)", line)
        require(matched is not None, f"{path}: malformed SHA256SUMS row")
        digest, locator = matched.groups()
        normalized = safe_relative(locator, label=f"{path} row").as_posix()
        require(normalized not in rows, f"{path}: duplicate seal row {normalized}")
        rows[normalized] = digest
    require(bool(rows), f"{path}: empty seal")
    return rows


def validate_contract() -> dict[str, Any]:
    contract = read_json_object(CONTRACT_PATH)
    require(
        contract.get("schema_version") == "sge-c1-structural-analysis-contract-v1"
        and contract.get("contract_id") == CONTRACT_ID
        and contract.get("status") == "frozen_retrospective_supporting",
        "C1 analysis contract identity drift",
    )
    require(
        contract.get("type_weights") == FROZEN_TYPE_WEIGHTS,
        "frozen type-weight table drift",
    )
    require(
        contract.get("primary") == {
            "threshold": PRIMARY_THRESHOLD,
            "worker_count": PRIMARY_WORKER,
        },
        "C1 primary P/theta drift",
    )
    sensitivity = contract.get("sensitivity")
    require(
        isinstance(sensitivity, Mapping)
        and tuple(sensitivity.get("worker_counts") or []) == WORKERS
        and tuple(sensitivity.get("thresholds") or []) == THRESHOLDS
        and tuple(sensitivity.get("depths") or []) == DEPTHS
        and tuple(sensitivity.get("widths") or []) == WIDTHS,
        "C1 sensitivity grid drift",
    )
    require(
        frozenset(contract.get("held_out_repositories") or [])
        == HELD_OUT_REPOSITORIES,
        "held-out repository boundary drift",
    )
    bootstrap = contract.get("bootstrap")
    require(
        bootstrap
        == {
            "cluster_unit": "physical_repository",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed_string": BOOTSTRAP_SEED,
        },
        "repository bootstrap contract drift",
    )
    boundary = contract.get("claim_boundary")
    require(
        isinstance(boundary, Mapping)
        and boundary.get("result_role") == RESULT_ROLE
        and boundary.get("scientific_result") is False
        and boundary.get("prospective_primary") is False
        and boundary.get("expected_net_gain_modeled") is False
        and boundary.get("prediction_accuracy_modeled") is False
        and boundary.get("waste_modeled") is False
        and boundary.get("fallback_modeled") is False
        and boundary.get("actual_executor_speedup_claim") is False
        and boundary.get("observed_duration_reference_is_actual_executor_speedup")
        is False,
        "C1 claim boundary drift",
    )
    require(
        boundary.get("primary_result") is False
        and boundary.get("preregistered_primary") is False
        and boundary.get("online_acceleration_claim") is False
        and boundary.get("post_collection_extension_not_preregistered_primary")
        is True
        and boundary.get("structural_ceiling_is_necessary_not_sufficient")
        is True,
        "C1 primary/necessary-condition boundary drift",
    )
    lineage = contract.get("lineage")
    require(isinstance(lineage, Mapping), "C1 lineage missing")
    for path_field, sha_field in (
        ("frozen_type_weight_source", "frozen_type_weight_source_sha256"),
        ("window_extraction_contract", "window_extraction_contract_sha256"),
    ):
        relative = safe_relative(str(lineage.get(path_field) or ""), label=path_field)
        expected = str(lineage.get(sha_field) or "")
        require(SHA256_RE.fullmatch(expected) is not None, f"{sha_field}: digest required")
        path = ROOT.joinpath(*relative.parts)
        require(sha256_file(path) == expected, f"{path_field}: lineage digest drift")
    return contract


def verify_source_bundle(
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    source = contract.get("input")
    require(isinstance(source, Mapping), "C1 source binding missing")
    root_relative = safe_relative(str(source.get("root") or ""), label="input root")
    source_root = ROOT.joinpath(*root_relative.parts)
    require(
        source_root.is_dir() and not source_root.is_symlink(),
        "C1 sealed input root missing or unsafe",
    )
    seal_path = source_root / "SHA256SUMS"
    expected_seal = str(source.get("seal_sha256") or "")
    require(
        SHA256_RE.fullmatch(expected_seal) is not None
        and sha256_file(seal_path) == expected_seal,
        "C1 source seal identity drift",
    )
    rows = parse_sha256s(seal_path)
    expected_files = source.get("files")
    require(
        isinstance(expected_files, Mapping)
        and set(rows) == set(expected_files),
        "C1 source sealed file set drift",
    )
    actual_files = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and path != seal_path
    }
    require(actual_files == set(rows), "C1 source root has unsealed file drift")
    for locator, digest in rows.items():
        require(
            expected_files.get(locator) == digest
            and sha256_file(source_root.joinpath(*PurePosixPath(locator).parts))
            == digest,
            f"C1 source digest drift: {locator}",
        )
    extension = read_json_object(source_root / "extension_report.json")
    case_rows = read_json_value(source_root / "case_rows.json")
    ledger = read_json_object(source_root / "action_duration_ledger.json")
    candidates = read_json_value(source_root / "c_candidate_rows.json")
    require(isinstance(case_rows, list), "case_rows.json: array required")
    require(isinstance(candidates, list), "c_candidate_rows.json: array required")
    require(
        extension.get("status") == "post_collection_contract_extension"
        and extension.get("scientific_result") is False
        and extension.get("preregistered_primary") is False
        and extension.get("result_role") == "post_collection_contract_extension",
        "source evidence role drift",
    )
    return extension, case_rows, ledger, candidates


def topology_sha256(payload: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(payload))


def graph_summary(
    payload: Mapping[str, Any],
    durations: Mapping[str, float],
    *,
    workers: Sequence[int] = WORKERS,
) -> dict[str, Any]:
    require(
        set(payload) == {"nodes", "edges"}
        and isinstance(payload["nodes"], list)
        and bool(payload["nodes"])
        and isinstance(payload["edges"], list),
        "malformed topology payload",
    )
    node_types: dict[str, str] = {}
    for node in payload["nodes"]:
        require(
            isinstance(node, Mapping)
            and set(node) == {"node_id", "canonical_type"},
            "malformed topology node",
        )
        node_id = str(node["node_id"])
        node_type = str(node["canonical_type"])
        require(node_id and node_id not in node_types, "duplicate topology node")
        require(node_type in FROZEN_TYPE_WEIGHTS, f"unknown canonical type: {node_type}")
        node_types[node_id] = node_type
    require(set(durations) == set(node_types), "duration/node identity mismatch")
    values = {node_id: float(durations[node_id]) for node_id in node_types}
    require(
        all(math.isfinite(value) and value > 0.0 for value in values.values()),
        "node durations must be finite and positive",
    )
    predecessors = {node_id: [] for node_id in node_types}
    successors = {node_id: [] for node_id in node_types}
    edge_identities: set[tuple[str, str, str]] = set()
    dependency_pairs: set[tuple[str, str]] = set()
    for edge in payload["edges"]:
        require(
            isinstance(edge, Mapping)
            and set(edge) == {"edge_kind", "src", "dst"},
            "malformed topology edge",
        )
        src, dst = str(edge["src"]), str(edge["dst"])
        kind = str(edge["edge_kind"])
        identity = (src, dst, kind)
        require(
            src in node_types
            and dst in node_types
            and src != dst
            and kind in {"semantic", "schedule_guard"},
            "dangling, self, or non-contract topology edge",
        )
        require(identity not in edge_identities, "duplicate topology edge")
        edge_identities.add(identity)
        if (src, dst) not in dependency_pairs:
            dependency_pairs.add((src, dst))
            predecessors[dst].append(src)
            successors[src].append(dst)
    for node_id in node_types:
        predecessors[node_id].sort()
        successors[node_id].sort()
    indegree = {node_id: len(predecessors[node_id]) for node_id in node_types}
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    topological: list[str] = []
    while ready:
        node_id = ready.pop(0)
        topological.append(node_id)
        for child in successors[node_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    require(len(topological) == len(node_types), "topology is cyclic")
    longest_finish: dict[str, float] = {}
    parent: dict[str, str | None] = {}
    for node_id in topological:
        best_parent: str | None = None
        best_start = 0.0
        for predecessor in predecessors[node_id]:
            finish = longest_finish[predecessor]
            if finish > best_start:
                best_start = finish
                best_parent = predecessor
        longest_finish[node_id] = best_start + values[node_id]
        parent[node_id] = best_parent
    end = max(topological, key=lambda node_id: longest_finish[node_id])
    critical_path: list[str] = []
    cursor: str | None = end
    while cursor is not None:
        critical_path.append(cursor)
        cursor = parent[cursor]
    critical_path.reverse()
    work = sum(values.values())
    span = longest_finish[end]
    return {
        "W": work,
        "L": span,
        "S_infinity": work / span,
        "critical_path_node_ids": critical_path,
        "ceiling_by_worker": {
            f"P{worker}": work / max(span, work / worker) for worker in workers
        },
    }


def build_duration_maps(ledger: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    cases = ledger.get("cases")
    require(
        isinstance(cases, list)
        and ledger.get("joined_case_count") == len(cases),
        "duration ledger case count drift",
    )
    output: dict[str, dict[str, float]] = {}
    for case in cases:
        require(isinstance(case, Mapping), "malformed duration-ledger case")
        case_id = str(case.get("case_id") or "")
        require(case_id and case_id not in output, "duplicate duration-ledger case")
        require(
            case.get("status") == "pass"
            and float(case.get("imputed_duration_seconds", -1.0)) == 0.0
            and float(case.get("uncovered_duration_seconds", -1.0)) == 0.0
            and math.isclose(
                float(case.get("conservation_delta_seconds", math.inf)),
                0.0,
                abs_tol=1e-6,
            ),
            f"{case_id}: duration ledger is not exact/non-imputed",
        )
        active = [str(value) for value in case.get("active_effective_semantic_node_ids") or []]
        require(active and len(active) == len(set(active)), f"{case_id}: active-node drift")
        totals = {node_id: 0.0 for node_id in active}
        duration_total = 0.0
        category_totals: dict[str, float] = defaultdict(float)
        semantic_total = 0.0
        rows = case.get("rows")
        require(isinstance(rows, list) and bool(rows), f"{case_id}: duration rows missing")
        for row in rows:
            require(isinstance(row, Mapping), f"{case_id}: malformed duration row")
            duration = row.get("duration_seconds")
            require(
                finite_number(duration) and float(duration) > 0.0,
                f"{case_id}: nonpositive action duration",
            )
            duration = float(duration)
            duration_total += duration
            category = str(row.get("duration_partition_category") or "")
            require(bool(category), f"{case_id}: duration category missing")
            category_totals[category] += duration
            allocations = row.get("semantic_allocations_seconds")
            require(isinstance(allocations, Mapping), f"{case_id}: allocations missing")
            allocation_total = 0.0
            for node_id, value in allocations.items():
                node_id = str(node_id)
                require(
                    node_id in totals
                    and finite_number(value)
                    and float(value) >= 0.0,
                    f"{case_id}: invalid semantic allocation",
                )
                totals[node_id] += float(value)
                allocation_total += float(value)
            if allocations:
                require(
                    math.isclose(allocation_total, duration, rel_tol=1e-9, abs_tol=1e-9),
                    f"{case_id}: semantic allocation is not conserved",
                )
                semantic_total += allocation_total
        require(
            math.isclose(
                duration_total,
                float(case.get("all_action_seconds", math.inf)),
                rel_tol=1e-8,
                abs_tol=1e-6,
            ),
            f"{case_id}: all-action duration drift",
        )
        expected_categories = case.get("duration_partition_seconds")
        require(isinstance(expected_categories, Mapping), f"{case_id}: partition missing")
        require(
            set(category_totals).issubset(set(expected_categories))
            and all(
                math.isclose(
                    category_totals.get(str(key), 0.0),
                    float(expected_categories[key]),
                    rel_tol=1e-8,
                    abs_tol=1e-6,
                )
                for key in expected_categories
            ),
            f"{case_id}: duration partition drift",
        )
        require(
            math.isclose(
                semantic_total,
                float(expected_categories.get("effective_semantic_work", math.inf)),
                rel_tol=1e-8,
                abs_tol=1e-6,
            )
            and all(value > 0.0 for value in totals.values()),
            f"{case_id}: active semantic node coverage drift",
        )
        output[case_id] = totals
    return output


def close_enough(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return finite_number(left) and finite_number(right) and math.isclose(
        float(left), float(right), rel_tol=1e-11, abs_tol=1e-11
    )


def recompute_windows(
    candidates: Sequence[Mapping[str, Any]],
    case_rows: Sequence[Mapping[str, Any]],
    duration_maps: Mapping[str, Mapping[str, float]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: dict[str, Mapping[str, Any]] = {}
    require(len(case_rows) == 30, "C1 intention-to-measure denominator is not 30")
    for expected_position, case in enumerate(case_rows, 1):
        require(isinstance(case, Mapping), "malformed case-row input")
        case_id = str(case.get("case_id") or "")
        require(
            int(case.get("position", -1)) == expected_position
            and case_id
            and case_id not in cases,
            "case-row position or identity drift",
        )
        cases[case_id] = case
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []
    stored_drift_checks = 0
    for source in candidates:
        require(isinstance(source, Mapping), "malformed candidate row")
        case_id = str(source.get("case_id") or "")
        topology_hash = str(source.get("topology_window_sha256") or "")
        unit = (case_id, topology_hash)
        require(
            case_id in cases
            and SHA256_RE.fullmatch(topology_hash) is not None
            and unit not in seen,
            "candidate independent-unit identity drift",
        )
        seen.add(unit)
        case = cases[case_id]
        repository = str(source.get("physical_repository") or "")
        require(
            repository == case.get("physical_repository")
            and repository in HELD_OUT_REPOSITORIES,
            f"{case_id}: held-out repository leakage",
        )
        require(
            source.get("independent_unit") == [case_id, topology_hash]
            and source.get("topology_selection_duration_blind") is True,
            f"{case_id}: candidate duration-blind identity drift",
        )
        payload = source.get("topology_payload")
        require(isinstance(payload, Mapping), f"{case_id}: topology payload missing")
        require(
            topology_sha256(payload) == topology_hash,
            f"{case_id}: topology hash drift",
        )
        node_ids = [str(node["node_id"]) for node in payload["nodes"]]
        require(
            set(node_ids) == set(str(value) for value in source.get("node_ids") or [])
            and len(node_ids) == int(source.get("node_count", -1)),
            f"{case_id}: candidate node identity drift",
        )
        estimated = graph_summary(
            payload,
            {
                str(node["node_id"]): FROZEN_TYPE_WEIGHTS[
                    str(node["canonical_type"])
                ]
                for node in payload["nodes"]
            },
        )
        exact_case_durations = duration_maps.get(case_id)
        observed = (
            graph_summary(
                payload,
                {node_id: float(exact_case_durations[node_id]) for node_id in node_ids},
            )
            if exact_case_durations is not None
            and set(node_ids).issubset(exact_case_durations)
            else None
        )
        configurations = source.get("source_configurations")
        require(
            isinstance(configurations, list)
            and bool(configurations)
            and int(source.get("configuration_count", -1)) == len(configurations),
            f"{case_id}: source configuration drift",
        )
        normalized_configurations: list[dict[str, Any]] = []
        configuration_keys: set[tuple[int, str, int]] = set()
        for configuration in configurations:
            require(isinstance(configuration, Mapping), "malformed source configuration")
            depth = configuration.get("depth")
            width = configuration.get("width")
            wave = configuration.get("wave")
            require(
                depth in DEPTHS
                and type(width) is int
                and width in WIDTHS
                and type(wave) is int
                and wave > 0,
                f"{case_id}: source configuration outside frozen grid",
            )
            key = (wave, str(depth), width)
            require(key not in configuration_keys, f"{case_id}: duplicate configuration")
            configuration_keys.add(key)
            normalized_configurations.append(
                {"depth": depth, "wave": wave, "width": width}
            )
        normalized_configurations.sort(
            key=lambda value: (
                int(value["wave"]),
                str(value["depth"]),
                int(value["width"]),
            )
        )
        worker_metrics: dict[str, Any] = {}
        stored_worker = source.get("worker_sensitivity")
        require(isinstance(stored_worker, Mapping), f"{case_id}: stored worker audit missing")
        for worker in WORKERS:
            label = f"P{worker}"
            estimated_ceiling = estimated["ceiling_by_worker"][label]
            observed_ceiling = (
                observed["ceiling_by_worker"][label] if observed is not None else None
            )
            stored = stored_worker.get(label)
            require(
                isinstance(stored, Mapping)
                and close_enough(stored.get("estimated_ceiling"), estimated_ceiling)
                and close_enough(stored.get("observed_ceiling"), observed_ceiling),
                f"{case_id}: stored {label} value disagrees with independent recomputation",
            )
            stored_drift_checks += 2
            worker_metrics[label] = {
                "absolute_error": (
                    abs(estimated_ceiling - observed_ceiling)
                    if observed_ceiling is not None
                    else None
                ),
                "absolute_percentage_error": (
                    abs(estimated_ceiling - observed_ceiling) / observed_ceiling
                    if observed_ceiling is not None
                    else None
                ),
                "admit_at_primary_threshold": (
                    estimated_ceiling >= PRIMARY_THRESHOLD
                ),
                "estimated_ceiling": estimated_ceiling,
                "observed_duration_reference_ceiling": observed_ceiling,
            }
        require(
            close_enough(source.get("estimated_ceiling"), worker_metrics["P4"]["estimated_ceiling"])
            and close_enough(
                source.get("observed_ceiling"),
                worker_metrics["P4"]["observed_duration_reference_ceiling"],
            ),
            f"{case_id}: stored P4 summary drift",
        )
        stored_drift_checks += 2
        output.append(
            {
                "case_id": case_id,
                "configuration_count": len(normalized_configurations),
                "estimated_structure": {
                    key: estimated[key]
                    for key in ("L", "S_infinity", "W", "critical_path_node_ids")
                },
                "independent_unit": [case_id, topology_hash],
                "node_count": len(node_ids),
                "observed_duration_reference_structure": (
                    {
                        key: observed[key]
                        for key in ("L", "S_infinity", "W", "critical_path_node_ids")
                    }
                    if observed is not None
                    else None
                ),
                "physical_repository": repository,
                "position": int(source["position"]),
                "prospective_primary": False,
                "result_role": RESULT_ROLE,
                "scientific_result": False,
                "source_configurations": normalized_configurations,
                "topology_payload": payload,
                "topology_selection_duration_blind": True,
                "topology_window_sha256": topology_hash,
                "worker_metrics": worker_metrics,
            }
        )
    output.sort(
        key=lambda row: (int(row["position"]), str(row["topology_window_sha256"]))
    )
    return output, {
        "stored_value_comparisons": stored_drift_checks,
        "stored_value_mismatches": 0,
        "stored_values_role": "redundant_drift_check_only",
    }


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
    left_ranks, right_ranks = ranks(left), ranks(right)
    left_mean = statistics.fmean(left_ranks)
    right_mean = statistics.fmean(right_ranks)
    numerator = sum(
        (first - left_mean) * (second - right_mean)
        for first, second in zip(left_ranks, right_ranks)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left_ranks)
        * sum((value - right_mean) ** 2 for value in right_ranks)
    )
    return numerator / denominator if denominator else None


def nearest_rank(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def paired_rows(
    rows: Sequence[Mapping[str, Any]], worker: int
) -> list[Mapping[str, Any]]:
    label = f"P{worker}"
    return [
        row
        for row in rows
        if row["worker_metrics"][label][
            "observed_duration_reference_ceiling"
        ]
        is not None
    ]


def threshold_metrics(
    rows: Sequence[Mapping[str, Any]], *, worker: int, threshold: float
) -> dict[str, Any]:
    label = f"P{worker}"
    paired = paired_rows(rows, worker)
    predicted = [
        float(row["worker_metrics"][label]["estimated_ceiling"]) >= threshold
        for row in paired
    ]
    actual = [
        float(
            row["worker_metrics"][label][
                "observed_duration_reference_ceiling"
            ]
        )
        >= threshold
        for row in paired
    ]
    true_positive = sum(left and right for left, right in zip(predicted, actual))
    false_positive = sum(left and not right for left, right in zip(predicted, actual))
    false_negative = sum(not left and right for left, right in zip(predicted, actual))
    true_negative = sum(not left and not right for left, right in zip(predicted, actual))
    actual_positive = true_positive + false_negative
    actual_negative = true_negative + false_positive
    predicted_positive = true_positive + false_positive
    return {
        "admitted": predicted_positive,
        "false_admission": false_positive,
        "false_admission_fraction_overall": (
            false_positive / len(paired) if paired else None
        ),
        "false_admission_rate_over_predicted_admitted": (
            false_positive / predicted_positive if predicted_positive else None
        ),
        "false_positive_rate_over_actual_low_benefit": (
            false_positive / actual_negative if actual_negative else None
        ),
        "false_rejection": false_negative,
        "false_rejection_rate_over_actual_beneficial": (
            false_negative / actual_positive if actual_positive else None
        ),
        "low_benefit_window_rejection_fraction": (
            true_negative / actual_negative if actual_negative else None
        ),
        "overall_rejection_fraction": (
            (true_negative + false_negative) / len(paired) if paired else None
        ),
        "paired_window_count": len(paired),
        "rejected": true_negative + false_negative,
        "threshold": threshold,
        "true_admission": true_positive,
        "true_rejection": true_negative,
        "worker": worker,
    }


def worker_summary(
    rows: Sequence[Mapping[str, Any]], worker: int
) -> dict[str, Any]:
    label = f"P{worker}"
    paired = paired_rows(rows, worker)
    estimates = [
        float(row["worker_metrics"][label]["estimated_ceiling"]) for row in paired
    ]
    observed = [
        float(
            row["worker_metrics"][label][
                "observed_duration_reference_ceiling"
            ]
        )
        for row in paired
    ]
    errors = [abs(left - right) for left, right in zip(estimates, observed)]
    return {
        "candidate_case_count": len({str(row["case_id"]) for row in rows}),
        "candidate_window_count": len(rows),
        "ceiling_mae": statistics.fmean(errors) if errors else None,
        "ceiling_mape": (
            statistics.fmean(
                error / reference for error, reference in zip(errors, observed)
            )
            if errors
            else None
        ),
        "paired_case_count": len({str(row["case_id"]) for row in paired}),
        "paired_repository_count": len(
            {str(row["physical_repository"]) for row in paired}
        ),
        "paired_window_count": len(paired),
        "spearman_estimated_vs_observed_duration_reference": spearman(
            estimates, observed
        ),
        "thresholds": [
            threshold_metrics(rows, worker=worker, threshold=threshold)
            for threshold in THRESHOLDS
        ],
        "worker": worker,
    }


def depth_width_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for depth in DEPTHS:
        output[str(depth)] = {}
        for width in WIDTHS:
            selected = [
                row
                for row in rows
                if any(
                    str(configuration["depth"]) == str(depth)
                    and int(configuration["width"]) == width
                    for configuration in row["source_configurations"]
                )
            ]
            summary = worker_summary(selected, PRIMARY_WORKER)
            output[str(depth)][str(width)] = {
                key: summary[key]
                for key in (
                    "candidate_case_count",
                    "candidate_window_count",
                    "ceiling_mae",
                    "ceiling_mape",
                    "paired_case_count",
                    "paired_repository_count",
                    "paired_window_count",
                    "spearman_estimated_vs_observed_duration_reference",
                )
            }
    return output


def repository_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        repository: worker_summary(
            [
                row
                for row in rows
                if str(row["physical_repository"]) == repository
            ],
            PRIMARY_WORKER,
        )
        for repository in sorted(HELD_OUT_REPOSITORIES)
    }


def nontrivial_window_sensitivity(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    paired = paired_rows(rows, PRIMARY_WORKER)
    without_single_node = [
        row for row in paired if int(row["node_count"]) > 1
    ]
    without_joint_unit_ceiling = [
        row
        for row in paired
        if not (
            math.isclose(
                float(row["worker_metrics"]["P4"]["estimated_ceiling"]),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and math.isclose(
                float(
                    row["worker_metrics"]["P4"][
                        "observed_duration_reference_ceiling"
                    ]
                ),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
    ]
    return {
        "role": "post_hoc_sensitivity_not_primary",
        "all_paired_window_count": len(paired),
        "joint_estimated_and_reference_ceiling_1_0_count": (
            len(paired) - len(without_joint_unit_ceiling)
        ),
        "excluding_single_node_windows": worker_summary(
            without_single_node, PRIMARY_WORKER
        ),
        "excluding_joint_estimated_and_reference_ceiling_1_0": worker_summary(
            without_joint_unit_ceiling, PRIMARY_WORKER
        ),
    }


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    paired = paired_rows(rows, PRIMARY_WORKER)
    repositories = sorted({str(row["physical_repository"]) for row in paired})
    require(
        set(repositories) == set(HELD_OUT_REPOSITORIES),
        "paired repository set does not cover the frozen held-out set",
    )
    by_repository = {
        repository: [
            row
            for row in paired
            if str(row["physical_repository"]) == repository
        ]
        for repository in repositories
    }
    seed_sha256 = sha256_bytes(BOOTSTRAP_SEED.encode("utf-8"))
    rng = random.Random(int(seed_sha256, 16))
    correlations: list[float] = []
    maes: list[float] = []
    mapes: list[float] = []
    false_rejections: list[float] = []
    false_admissions: list[float] = []
    low_benefit_rejections: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sampled = [
            repositories[rng.randrange(len(repositories))]
            for _ in repositories
        ]
        selected = [
            row for repository in sampled for row in by_repository[repository]
        ]
        summary = worker_summary(selected, PRIMARY_WORKER)
        correlation = summary[
            "spearman_estimated_vs_observed_duration_reference"
        ]
        if correlation is not None:
            correlations.append(float(correlation))
        if summary["ceiling_mae"] is not None:
            maes.append(float(summary["ceiling_mae"]))
        if summary["ceiling_mape"] is not None:
            mapes.append(float(summary["ceiling_mape"]))
        threshold = threshold_metrics(
            selected, worker=PRIMARY_WORKER, threshold=PRIMARY_THRESHOLD
        )
        for target, field in (
            (
                false_rejections,
                "false_rejection_rate_over_actual_beneficial",
            ),
            (
                false_admissions,
                "false_admission_rate_over_predicted_admitted",
            ),
            (
                low_benefit_rejections,
                "low_benefit_window_rejection_fraction",
            ),
        ):
            value = threshold[field]
            if value is not None:
                target.append(float(value))

    def interval(values: Sequence[float]) -> dict[str, Any]:
        return {
            "ci95_lower": nearest_rank(values, 0.025),
            "ci95_upper": nearest_rank(values, 0.975),
            "undefined_resamples": BOOTSTRAP_RESAMPLES - len(values),
            "valid_resamples": len(values),
        }

    return {
        "bootstrap_unit": "physical_repository",
        "caution": (
            "exploratory interval only; four physical-repository clusters "
            "cannot support a precise population uncertainty claim"
        ),
        "ceiling_mae": interval(maes),
        "ceiling_mape": interval(mapes),
        "false_admission_rate_over_predicted_admitted": interval(
            false_admissions
        ),
        "false_rejection_rate_over_actual_beneficial": interval(
            false_rejections
        ),
        "low_benefit_window_rejection_fraction": interval(
            low_benefit_rejections
        ),
        "metric_seed_sha256": seed_sha256,
        "repository_count": len(repositories),
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed_string": BOOTSTRAP_SEED,
        "spearman": interval(correlations),
    }


def build_attrition_ledger(
    case_rows: Sequence[Mapping[str, Any]],
    window_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_counts = Counter(str(row["case_id"]) for row in window_rows)
    paired_counts = Counter(
        str(row["case_id"])
        for row in paired_rows(window_rows, PRIMARY_WORKER)
    )
    reasons: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for case in case_rows:
        case_reasons = sorted(str(value) for value in case.get("attrition_reasons") or [])
        reasons.update(case_reasons)
        case_id = str(case["case_id"])
        rows.append(
            {
                "audited_effective_dag_eligible": bool(
                    case.get("audited_effective_dag_eligible")
                ),
                "c1_candidate_case": candidate_counts[case_id] > 0,
                "c1_candidate_window_count": candidate_counts[case_id],
                "c1_paired_case": paired_counts[case_id] > 0,
                "c1_paired_window_count": paired_counts[case_id],
                "case_id": case_id,
                "in_frozen_held_out_repository_set": (
                    str(case["physical_repository"]) in HELD_OUT_REPOSITORIES
                ),
                "observed_duration_join_eligible": bool(
                    case.get("observed_duration_join_eligible")
                ),
                "physical_repository": str(case["physical_repository"]),
                "position": int(case["position"]),
                "retained_attrition_reasons": case_reasons,
            }
        )
    return {
        "candidate_case_count": sum(row["c1_candidate_case"] for row in rows),
        "candidate_window_count": sum(
            int(row["c1_candidate_window_count"]) for row in rows
        ),
        "intention_case_count": len(rows),
        "observed_duration_join_case_count": sum(
            row["observed_duration_join_eligible"] for row in rows
        ),
        "paired_case_count": sum(row["c1_paired_case"] for row in rows),
        "paired_repository_count": len(
            {
                row["physical_repository"]
                for row in rows
                if row["c1_paired_case"]
            }
        ),
        "paired_window_count": sum(
            int(row["c1_paired_window_count"]) for row in rows
        ),
        "reason_counts": dict(sorted(reasons.items())),
        "rows": rows,
        "schema_version": "sge-c1-structural-attrition-ledger-v1",
    }


def build_report(
    *,
    contract: Mapping[str, Any],
    extension: Mapping[str, Any],
    window_rows: Sequence[Mapping[str, Any]],
    attrition: Mapping[str, Any],
    drift_audit: Mapping[str, Any],
) -> dict[str, Any]:
    primary = worker_summary(window_rows, PRIMARY_WORKER)
    primary_threshold = next(
        value
        for value in primary["thresholds"]
        if value["threshold"] == PRIMARY_THRESHOLD
    )
    by_case = {
        case_id: worker_summary(
            [row for row in window_rows if str(row["case_id"]) == case_id],
            PRIMARY_WORKER,
        )
        for case_id in sorted({str(row["case_id"]) for row in window_rows})
    }
    source_c = extension.get("experiment_C")
    require(isinstance(source_c, Mapping), "source Experiment C report missing")
    require(
        source_c.get("candidate_unique_window_count") == len(window_rows)
        and source_c.get("paired_observed_unique_window_count")
        == attrition["paired_window_count"],
        "source report count disagrees with independent recomputation",
    )
    return {
        "claim_boundary": dict(contract["claim_boundary"]),
        "contract_id": CONTRACT_ID,
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "counters": {
            "benchmark_target_invocations": 0,
            "model_or_api_invocations": 0,
            "official_evaluator_invocations": 0,
            "task_originated_network_calls": 0,
        },
        "denominators": {
            "candidate_case_count": attrition["candidate_case_count"],
            "candidate_unique_window_count": len(window_rows),
            "configuration_rows_are_not_independent_samples": True,
            "held_out_repository_count": len(HELD_OUT_REPOSITORIES),
            "intention_case_count": attrition["intention_case_count"],
            "paired_case_count": attrition["paired_case_count"],
            "paired_repository_count": attrition["paired_repository_count"],
            "paired_unique_window_count": attrition["paired_window_count"],
            "window_rows_are_not_independent_cases": True,
        },
        "formula": dict(contract["formula"]),
        "input_verification": {
            "all_source_files_sha256_verified": True,
            "exact_non_imputed_duration_case_count": attrition[
                "observed_duration_join_case_count"
            ],
            "held_out_exact_non_imputed_duration_case_count": attrition[
                "paired_case_count"
            ],
            "source_bundle_seal_sha256": contract["input"]["seal_sha256"],
            "source_role_preserved": "post_collection_contract_extension",
            "topology_hashes_recomputed": len(window_rows),
            **dict(drift_audit),
        },
        "interpretation_guardrails": [
            "30 is the intention-to-measure case denominator, not an observed C1 case count",
            "221 topology windows are not 221 independent tasks",
            "188 paired windows arise from 7 cases in 4 physical repositories",
            "observed-duration reference ceilings are structural references, not realized executor speedups",
            "repository-cluster intervals are exploratory with only four clusters",
            "the effective overlay is post-collection and this result is not prospective primary evidence",
            "ExpectedNetGain, prediction error, waste, fallback, quality, and E2E realization are not modeled here"
        ],
        "prospective_primary": False,
        "result_role": RESULT_ROLE,
        "schema_version": SCHEMA_VERSION,
        "scientific_result": False,
        "status": "passed_retrospective_supporting_structural_validation",
        "structural_validation": {
            "by_case": by_case,
            "by_repository": repository_summary(window_rows),
            "depth_width_sensitivity": depth_width_summary(window_rows),
            "nontrivial_window_sensitivity": nontrivial_window_sensitivity(
                window_rows
            ),
            "primary_P4": primary,
            "primary_theta_1_10": primary_threshold,
            "repository_cluster_bootstrap": cluster_bootstrap(window_rows),
            "worker_sensitivity": {
                f"P{worker}": worker_summary(window_rows, worker)
                for worker in WORKERS
            },
        },
        "supporting_findings": {
            "estimated_ceiling_preserves_observed_reference_ordering": (
                primary[
                    "spearman_estimated_vs_observed_duration_reference"
                ]
            ),
            "estimated_ceiling_mean_absolute_error": primary["ceiling_mae"],
            "estimated_ceiling_mean_absolute_percentage_error": primary[
                "ceiling_mape"
            ],
            "theta_1_10_false_admission_count": primary_threshold[
                "false_admission"
            ],
            "theta_1_10_false_rejection_count": primary_threshold[
                "false_rejection"
            ],
            "theta_1_10_low_benefit_window_rejection_fraction": (
                primary_threshold["low_benefit_window_rejection_fraction"]
            ),
            "theta_1_10_overall_rejection_fraction": primary_threshold[
                "overall_rejection_fraction"
            ],
        },
    }


def build_bundle() -> dict[str, bytes]:
    contract = validate_contract()
    extension, case_rows, ledger, candidates = verify_source_bundle(contract)
    duration_maps = build_duration_maps(ledger)
    window_rows, drift_audit = recompute_windows(
        candidates, case_rows, duration_maps
    )
    attrition = build_attrition_ledger(case_rows, window_rows)
    require(
        len(case_rows) == 30
        and len(candidates) == len(window_rows) == 221
        and attrition["candidate_case_count"] == 9
        and attrition["paired_case_count"] == 7
        and attrition["paired_repository_count"] == 4
        and attrition["paired_window_count"] == 188
        and len(duration_maps) == 9,
        "sealed C1 denominator drift",
    )
    report = build_report(
        contract=contract,
        extension=extension,
        window_rows=window_rows,
        attrition=attrition,
        drift_audit=drift_audit,
    )
    files: dict[str, bytes] = {
        "structural_validation_report.json": pretty_bytes(report),
        "window_rows.json": pretty_bytes(window_rows),
        "attrition_ledger.json": pretty_bytes(attrition),
    }
    inventory = {
        "analyzer": {
            "path": "scripts/analyze_sge_c1_structural.py",
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "contract": {
            "path": CONTRACT_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(CONTRACT_PATH),
        },
        "files": [
            {
                "bytes": len(files[name]),
                "path": name,
                "sha256": sha256_bytes(files[name]),
            }
            for name in OUTPUT_DATA_FILES
        ],
        "schema_version": "sge-c1-structural-artifact-inventory-v1",
        "source_bundle": {
            "path": contract["input"]["root"],
            "seal_sha256": contract["input"]["seal_sha256"],
        },
    }
    files["artifact_inventory.json"] = pretty_bytes(inventory)
    seal = "".join(
        f"{sha256_bytes(files[name])}  {name}\n" for name in OUTPUT_FILES
    ).encode("utf-8")
    files["SHA256SUMS"] = seal
    return files


def verify_bundle(root: Path, expected: Mapping[str, bytes] | None = None) -> None:
    require(root.is_dir() and not root.is_symlink(), f"missing result root: {root}")
    actual_names = {
        path.name for path in root.iterdir() if path.is_file() and not path.is_symlink()
    }
    require(
        actual_names == set(OUTPUT_FILES) | {"SHA256SUMS"},
        "C1 output file set drift",
    )
    seal_rows = parse_sha256s(root / "SHA256SUMS")
    require(set(seal_rows) == set(OUTPUT_FILES), "C1 output seal file set drift")
    for name, digest in seal_rows.items():
        require(sha256_file(root / name) == digest, f"C1 output digest drift: {name}")
    if expected is not None:
        for name, content in expected.items():
            require(
                (root / name).read_bytes() == content,
                f"C1 output differs from deterministic recomputation: {name}",
            )
    report = read_json_object(root / "structural_validation_report.json")
    require(
        report.get("status")
        == "passed_retrospective_supporting_structural_validation"
        and report.get("scientific_result") is False
        and report.get("prospective_primary") is False
        and report.get("result_role") == RESULT_ROLE,
        "C1 output claim boundary drift",
    )


def write_bundle(root: Path, files: Mapping[str, bytes]) -> str:
    root = root.resolve()
    require(root != ROOT and root.parent != root, "unsafe output root")
    if root.exists():
        verify_bundle(root, files)
        return "already_current"
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{root.name}.", dir=str(root.parent))
    )
    try:
        for name, content in files.items():
            path = temporary / name
            with path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        verify_bundle(temporary, files)
        os.replace(temporary, root)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return "written"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="result bundle root",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the existing bundle against a fresh in-memory recomputation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        expected = build_bundle()
        if args.check:
            verify_bundle(args.output_root.resolve(), expected)
            action = "verified"
        else:
            action = write_bundle(args.output_root, expected)
        report = json.loads(expected["structural_validation_report.json"])
        primary = report["structural_validation"]["primary_P4"]
        threshold = report["structural_validation"]["primary_theta_1_10"]
        print(
            json.dumps(
                {
                    "action": action,
                    "candidate_cases": report["denominators"][
                        "candidate_case_count"
                    ],
                    "candidate_windows": report["denominators"][
                        "candidate_unique_window_count"
                    ],
                    "paired_cases": report["denominators"]["paired_case_count"],
                    "paired_repositories": report["denominators"][
                        "paired_repository_count"
                    ],
                    "paired_windows": report["denominators"][
                        "paired_unique_window_count"
                    ],
                    "p4_mae": primary["ceiling_mae"],
                    "p4_mape": primary["ceiling_mape"],
                    "p4_spearman": primary[
                        "spearman_estimated_vs_observed_duration_reference"
                    ],
                    "scientific_result": False,
                    "status": report["status"],
                    "theta_1_10_false_admission": threshold["false_admission"],
                    "theta_1_10_false_rejection": threshold["false_rejection"],
                    "theta_1_10_overall_rejection_fraction": threshold[
                        "overall_rejection_fraction"
                    ],
                },
                sort_keys=True,
            )
        )
    except AnalysisError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
