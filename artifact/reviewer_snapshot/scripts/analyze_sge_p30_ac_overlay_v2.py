#!/usr/bin/env python3
"""Versioned P30 A/C post-collection overlay analysis.

This driver extends, rather than edits, the frozen P30 analyzer.  It consumes:

* the immutable Stage-A duration/outcome/result-blind mapping;
* an ``effective_action_disposition_overlay_v1`` materialized before durations
  are opened;
* the audited Stage-B effective DAG; and
* the sealed source action-identity/duration ledger.

The four evidence layers (source trace, contiguous E2E phase, audited effective
DAG, and observed-duration join) are intentionally independent.  In
particular, positions 3 and 6 may enter the action/DAG layers but never the
contiguous E2E phase or paired-executor-D layers.

No command in this module can call a model, benchmark target, evaluator, or
network service.  Output is a transparent post-collection contract extension,
not a preregistered primary result.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_sge_primary_ac_p30 as base  # noqa: E402


SCHEMA_VERSION = "sge-p30-ac-post-collection-overlay-analysis-v2"
CASE_INDEX_SCHEMA_VERSION = "sge-p30-ac-overlay-v2-case-index-v1"
OVERLAY_SCHEMA_VERSION = "effective_action_disposition_overlay_v1"
CONTRACT_SCHEMA_VERSION = "sge-p30-ac-post-collection-contract-extension-v2"
CONTRACT_ID = "SGE-P30-AC-POST-COLLECTION-OVERLAY-20260728-V2"
RESULT_ROLE = "post_collection_contract_extension"
BASE_COMMIT = "f7e361b8c7e393770400367ac8d9929ad5ec81f4"
BASE_ANALYZER_PATH = ROOT / "scripts/analyze_sge_primary_ac_p30.py"
BASE_ANALYZER_SHA256 = (
    "3bdcfdcd6422b3ace8ce897a03c9864edc1bd57c9fa05c00bb6bdefd829a2d7d"
)
OWNER = (
    ROOT
    / "experiments/perfect_speculation_speedup_bound/direct_pair/"
    "trace_to_reference_dag/cohorts/sge_primary_scale_20260727"
)
CONTRACT_PATH = OWNER / "p30_ac_post_collection_contract_extension_v2.json"
CONTRACT_SHA256 = (
    "06b28dc0ddb10aacd7acdc9a5e0e7ca893750a266b5f376c70b3fedb135f6433"
)
CASE_INDEX_SCHEMA_PATH = OWNER / "p30_ac_overlay_v2_case_index.schema.json"
CASE_INDEX_SCHEMA_SHA256 = (
    "62d584feae86f485529dd1f08d9d855ab2c951b1ab8dbd7ebaefc0e0f4cc1773"
)
MANIFEST_PATH = OWNER / "p30_freeze/cohort_manifest.json"
PHASE_RECOVERY_ROOT = (
    ROOT / "results/sge_p30_post_collection_analyzer_contract_recovery_20260728"
)
PHASE_RECOVERY_SEAL_SHA256 = (
    "2329b5831a954a81073481fa38dc0e6d2b0ab80a6d4377498a4f818425d97462"
)
SOURCE_POSITIONS = frozenset(
    {
        3,
        6,
        7,
        8,
        9,
        10,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
    }
)
SOURCE_ATTRITION_POSITIONS = frozenset({1, 2, 4, 5, 11})
TARGET_ONLY_POSITIONS = frozenset({3, 6})
CONTIGUOUS_PHASE_POSITIONS = SOURCE_POSITIONS - TARGET_ONLY_POSITIONS
EXPECTED_SOURCE_ATTRITION = {
    1: "original_target_incomplete",
    2: "original_target_incomplete",
    4: "original_target_incomplete",
    5: "original_target_incomplete",
    11: "original_zero_dispatch_gitlink_failure",
}
HELD_OUT_REPOSITORIES = frozenset(base.HELD_OUT_REPOSITORIES)
ELIGIBILITY_FIELDS = (
    "source_trace",
    "contiguous_e2e_phase",
    "audited_effective_dag",
    "observed_duration_join",
    "paired_executor_D",
)
ROOT_FIELDS = {"root_id", "path", "seal_name", "seal_sha256"}
ARTIFACT_FIELDS = {"root_id", "path", "sha256"}
ROW_FIELDS = {
    "position",
    "case_id",
    "instance_id",
    "physical_repository",
    "base_commit",
    "eligibility",
    "retained_attrition_reasons",
    "sealed_roots",
    "artifacts",
}
INDEX_FIELDS = {
    "schema_version",
    "status",
    "scientific_result",
    "test_only",
    "fixture_or_synthetic",
    "contract_extension_sha256",
    "base_analyzer_sha256",
    "case_count",
    "rows",
}
REQUIRED_SOURCE_ARTIFACTS = {
    "source_identity",
    "observed_action_identity",
}
REQUIRED_DAG_ARTIFACTS = {
    *REQUIRED_SOURCE_ARTIFACTS,
    "projection_lineage",
    "stage_a_annotation",
    "stage_b_response",
    "effective_reference_dag",
    "effective_action_overlay",
    "stage_b_verification",
    "stage_b_independent_audit",
}
OUTPUT_DATA_FILES = (
    "extension_report.json",
    "case_rows.json",
    "action_duration_ledger.json",
    "c_candidate_rows.json",
)
OUTPUT_FILES = (*OUTPUT_DATA_FILES, "artifact_inventory.json")
SHA256_RE = base.SHA256_RE
COMMIT_RE = base.COMMIT_RE


class ExtensionError(RuntimeError):
    """Fatal contract, identity, containment, seal, or tamper error."""


class CaseIneligible(RuntimeError):
    """A preserved case cannot enter one downstream evidence layer."""

    def __init__(self, *reasons: str):
        normalized = tuple(sorted({str(value) for value in reasons if value}))
        self.reasons = normalized or ("unspecified_case_ineligibility",)
        super().__init__("; ".join(self.reasons))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExtensionError(message)


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
    require(path.is_file() and not path.is_symlink(), f"unsafe JSON: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExtensionError(f"invalid JSON {path}: {exc}") from exc


def read_json(path: Path) -> dict[str, Any]:
    value = read_json_value(path)
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def _safe_relative(value: Any, *, label: str) -> PurePosixPath:
    require(isinstance(value, str) and value, f"{label}: path required")
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and path.parts
        and "." not in path.parts
        and ".." not in path.parts
        and "\\" not in value,
        f"{label}: unsafe relative path",
    )
    return path


def _without_symlink(path: Path, containment: Path, *, label: str) -> Path:
    containment = containment.resolve()
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(containment)
    except ValueError as exc:
        raise ExtensionError(f"{label}: path escapes containment") from exc
    cursor = containment
    for part in relative.parts:
        cursor /= part
        require(not cursor.is_symlink(), f"{label}: symlink component forbidden")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(containment)
    except ValueError as exc:
        raise ExtensionError(f"{label}: resolved path escapes containment") from exc
    return resolved


def parse_seal(path: Path) -> dict[str, str]:
    require(path.is_file() and not path.is_symlink(), f"missing seal: {path}")
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        require(len(parts) == 2, f"{path}: malformed seal row")
        digest, raw_locator = parts[0], parts[1].strip()
        require(SHA256_RE.fullmatch(digest) is not None, f"{path}: bad digest")
        locator = _safe_relative(raw_locator, label=f"{path} entry").as_posix()
        require(locator not in rows, f"{path}: duplicate seal entry")
        rows[locator] = digest
    require(bool(rows), f"{path}: empty seal")
    return rows


def verify_index_seal(index_path: Path) -> str:
    rows = parse_seal(index_path.parent / "SHA256SUMS")
    require(
        rows.get(index_path.name) == sha256_file(index_path),
        "case index is not bound by sibling SHA256SUMS",
    )
    return sha256_file(index_path.parent / "SHA256SUMS")


class RootResolver:
    """Verify each sealed root once and resolve only seal-bound artifacts."""

    def __init__(self, index_path: Path, *, test_only: bool):
        self.index_path = index_path.resolve()
        self.test_only = test_only
        self._cache: dict[
            tuple[str, str, str], tuple[Path, dict[str, str]]
        ] = {}

    def root(
        self, descriptor: Mapping[str, Any], *, label: str
    ) -> tuple[Path, dict[str, str]]:
        require(set(descriptor) == ROOT_FIELDS, f"{label}: root field closure")
        root_id = str(descriptor.get("root_id") or "")
        raw_path = descriptor.get("path")
        seal_name = str(descriptor.get("seal_name") or "")
        seal_sha = str(descriptor.get("seal_sha256") or "")
        require(root_id, f"{label}: root id missing")
        require(
            seal_name in {"SHA256SUMS", "SOURCE_SHA256SUMS", "STAGE_A_SHA256SUMS"},
            f"{label}: unsupported seal name",
        )
        require(
            SHA256_RE.fullmatch(seal_sha) is not None,
            f"{label}: malformed seal digest",
        )
        candidate = Path(str(raw_path or ""))
        if candidate.is_absolute():
            require(self.test_only, f"{label}: absolute root allowed only in test")
            containment = self.index_path.parent.resolve()
            root = _without_symlink(candidate, containment, label=label)
        else:
            relative = _safe_relative(raw_path, label=label)
            containment = (
                self.index_path.parent.resolve() if self.test_only else ROOT.resolve()
            )
            anchor = self.index_path.parent if self.test_only else ROOT
            root = _without_symlink(
                anchor.joinpath(*relative.parts), containment, label=label
            )
        key = (str(root), seal_name, seal_sha)
        if key in self._cache:
            return self._cache[key]
        require(root.is_dir() and not root.is_symlink(), f"{label}: root missing")
        seal_path = root / seal_name
        require(
            sha256_file(seal_path) == seal_sha,
            f"{label}: root seal identity mismatch",
        )
        rows = parse_seal(seal_path)
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path != seal_path
        }
        require(actual == set(rows), f"{label}: root seal file closure mismatch")
        for locator, digest in rows.items():
            path = _without_symlink(
                root.joinpath(*PurePosixPath(locator).parts),
                root,
                label=f"{label}:{locator}",
            )
            require(
                path.is_file() and sha256_file(path) == digest,
                f"{label}: sealed artifact digest mismatch: {locator}",
            )
        self._cache[key] = (root, rows)
        return root, rows

    def artifacts(
        self, row: Mapping[str, Any]
    ) -> tuple[dict[str, Path], list[dict[str, Any]]]:
        raw_roots = row.get("sealed_roots")
        raw_artifacts = row.get("artifacts")
        require(isinstance(raw_roots, list), "sealed_roots must be an array")
        require(isinstance(raw_artifacts, Mapping), "artifacts must be an object")
        roots: dict[str, tuple[Path, dict[str, str]]] = {}
        evidence: list[dict[str, Any]] = []
        for ordinal, raw in enumerate(raw_roots, 1):
            require(isinstance(raw, Mapping), "malformed sealed root descriptor")
            root_id = str(raw.get("root_id") or "")
            require(root_id not in roots, f"duplicate root id: {root_id}")
            root, seal_rows = self.root(
                raw, label=f"position {row['position']} root {ordinal}"
            )
            roots[root_id] = (root, seal_rows)
            evidence.append(
                {
                    "root_id": root_id,
                    "path": str(root),
                    "seal_name": raw["seal_name"],
                    "seal_sha256": raw["seal_sha256"],
                    "sealed_file_count": len(seal_rows),
                }
            )
        resolved: dict[str, Path] = {}
        for role, raw in raw_artifacts.items():
            require(
                isinstance(role, str) and role and isinstance(raw, Mapping),
                "malformed artifact descriptor",
            )
            require(set(raw) == ARTIFACT_FIELDS, f"{role}: field closure mismatch")
            root_id = str(raw.get("root_id") or "")
            require(root_id in roots, f"{role}: unknown root id")
            relative = _safe_relative(raw.get("path"), label=f"{role} artifact")
            root, seal_rows = roots[root_id]
            locator = relative.as_posix()
            digest = str(raw.get("sha256") or "")
            require(
                seal_rows.get(locator) == digest
                and SHA256_RE.fullmatch(digest) is not None,
                f"{role}: artifact not identically bound by root seal",
            )
            path = _without_symlink(
                root.joinpath(*relative.parts), root, label=f"{role} artifact"
            )
            require(
                path.is_file() and sha256_file(path) == digest,
                f"{role}: artifact digest mismatch",
            )
            resolved[role] = path
        return resolved, sorted(evidence, key=lambda value: value["root_id"])


def validate_contract() -> dict[str, Any]:
    require(
        sha256_file(BASE_ANALYZER_PATH) == BASE_ANALYZER_SHA256,
        "immutable base analyzer bytes changed",
    )
    require(
        CONTRACT_PATH.is_file()
        and not CONTRACT_PATH.is_symlink()
        and sha256_file(CONTRACT_PATH) == CONTRACT_SHA256,
        "contract extension identity drift",
    )
    require(
        CASE_INDEX_SCHEMA_PATH.is_file()
        and not CASE_INDEX_SCHEMA_PATH.is_symlink()
        and sha256_file(CASE_INDEX_SCHEMA_PATH) == CASE_INDEX_SCHEMA_SHA256,
        "case-index schema identity drift",
    )
    contract = read_json(CONTRACT_PATH)
    require(
        contract.get("schema_version") == CONTRACT_SCHEMA_VERSION
        and contract.get("extension_id") == CONTRACT_ID
        and contract.get("status")
        == "implemented_no_model_pending_sealed_stage_a_stage_b_inputs"
        and contract.get("result_role") == RESULT_ROLE
        and contract.get("scientific_result") is False
        and contract.get("preregistered_primary") is False
        and contract.get("primary_result") is False
        and contract.get("execution_authorized_by_this_file") is False,
        "contract extension identity or claim boundary drift",
    )
    immutable = contract.get("immutable_base")
    require(
        isinstance(immutable, Mapping)
        and immutable.get("base_commit") == BASE_COMMIT
        and immutable.get("base_analyzer_sha256") == BASE_ANALYZER_SHA256
        and immutable.get("base_analyzer_modified_by_extension") is False
        and immutable.get("phase_recovery_result_seal_sha256")
        == PHASE_RECOVERY_SEAL_SHA256,
        "immutable base binding drift",
    )
    mapping = contract.get("mapping_layers")
    require(
        isinstance(mapping, Mapping)
        and mapping.get("stage_a_mapping", {}).get("analysis_mode")
        == "duration_outcome_result_blind"
        and mapping.get("effective_overlay", {}).get("schema_version")
        == OVERLAY_SCHEMA_VERSION
        and mapping.get("mixed_split_rule", {}).get("terminal_reason")
        == "blocked_mixed_semantic_envelope_split"
        and mapping.get("mixed_split_rule", {}).get(
            "duration_or_ratio_allocation_forbidden"
        )
        is True,
        "mapping-layer contract drift",
    )
    require(
        set(contract.get("C_validation", {}).get("held_out_repositories") or [])
        == HELD_OUT_REPOSITORIES,
        "C held-out repository contract drift",
    )
    require(
        sha256_file(PHASE_RECOVERY_ROOT / "SHA256SUMS")
        == PHASE_RECOVERY_SEAL_SHA256,
        "phase recovery result seal identity drift",
    )
    try:
        base.verify_post_collection_recovery_bundle(PHASE_RECOVERY_ROOT)
    except (base.AnalysisError, base.EvidenceIneligible) as exc:
        raise ExtensionError(f"phase recovery verification failed: {exc}") from exc
    return contract


def _phase_rows() -> dict[int, dict[str, Any]]:
    raw = read_json_value(PHASE_RECOVERY_ROOT / "recovered_phase_rows.json")
    require(isinstance(raw, list) and len(raw) == 30, "phase rows must cover P30")
    rows = {
        int(row["position"]): dict(row)
        for row in raw
        if isinstance(row, Mapping)
    }
    require(set(rows) == set(range(1, 31)), "phase position closure mismatch")
    observed = {
        position
        for position, row in rows.items()
        if row.get("whole_task_phase_composition_eligible") is True
    }
    require(
        observed == CONTIGUOUS_PHASE_POSITIONS,
        "phase eligibility differs from frozen 23-position set",
    )
    return rows


def validate_case_index(
    index_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, dict[str, Any]],
    str,
]:
    validate_contract()
    resolved = index_path.resolve()
    index = read_json(resolved)
    index_seal_sha = verify_index_seal(resolved)
    require(set(index) == INDEX_FIELDS, "case index field closure mismatch")
    require(
        index.get("schema_version") == CASE_INDEX_SCHEMA_VERSION
        and index.get("status") == "frozen_post_collection_input_index"
        and index.get("scientific_result") is False
        and index.get("contract_extension_sha256") == CONTRACT_SHA256
        and index.get("base_analyzer_sha256") == BASE_ANALYZER_SHA256
        and index.get("case_count") == 30,
        "case index identity drift",
    )
    test_only = index.get("test_only")
    fixture = index.get("fixture_or_synthetic")
    require(type(test_only) is bool and type(fixture) is bool, "test flags invalid")
    require(
        (test_only and fixture) or (not test_only and not fixture),
        "fixture/synthetic flag must equal test-only mode",
    )
    manifest = read_json(MANIFEST_PATH)
    manifest_cases = base.validate_manifest(manifest)
    rows = index.get("rows")
    require(isinstance(rows, list) and len(rows) == 30, "index must contain 30 rows")
    phase_rows = _phase_rows()
    normalized: list[dict[str, Any]] = []
    for position, (raw, frozen) in enumerate(zip(rows, manifest_cases), 1):
        require(
            isinstance(raw, Mapping) and set(raw) == ROW_FIELDS,
            f"position {position}: row field closure mismatch",
        )
        for field in (
            "position",
            "case_id",
            "instance_id",
            "physical_repository",
            "base_commit",
        ):
            require(
                type(raw.get(field)) is type(frozen.get(field))
                and raw.get(field) == frozen.get(field),
                f"position {position}: frozen identity drift: {field}",
            )
        eligibility = raw.get("eligibility")
        require(
            isinstance(eligibility, Mapping)
            and set(eligibility) == set(ELIGIBILITY_FIELDS)
            and all(type(eligibility[field]) is bool for field in ELIGIBILITY_FIELDS),
            f"position {position}: eligibility closure mismatch",
        )
        expected_source = position in SOURCE_POSITIONS
        expected_phase = position in CONTIGUOUS_PHASE_POSITIONS
        require(
            eligibility["source_trace"] is expected_source,
            f"position {position}: source-trace eligibility drift",
        )
        require(
            eligibility["contiguous_e2e_phase"] is expected_phase,
            f"position {position}: contiguous-phase eligibility drift",
        )
        require(
            eligibility["paired_executor_D"] is False,
            f"position {position}: this extension cannot admit D evidence",
        )
        require(
            not eligibility["audited_effective_dag"] or expected_source,
            f"position {position}: audited DAG without source trace",
        )
        require(
            not eligibility["observed_duration_join"]
            or eligibility["audited_effective_dag"],
            f"position {position}: observed join without audited DAG",
        )
        require(
            phase_rows[position]["whole_task_phase_composition_eligible"]
            is eligibility["contiguous_e2e_phase"],
            f"position {position}: phase index/recovery mismatch",
        )
        reasons = raw.get("retained_attrition_reasons")
        require(
            isinstance(reasons, list)
            and all(isinstance(value, str) and value for value in reasons)
            and len(reasons) == len(set(reasons)),
            f"position {position}: attrition reasons malformed",
        )
        if position in SOURCE_ATTRITION_POSITIONS:
            require(
                reasons == [EXPECTED_SOURCE_ATTRITION[position]],
                f"position {position}: source attrition reason drift",
            )
            require(
                not raw.get("sealed_roots") and not raw.get("artifacts"),
                f"position {position}: attrition row must not smuggle artifacts",
            )
        else:
            require(
                eligibility["audited_effective_dag"] or bool(reasons),
                f"position {position}: downstream DAG attrition must be retained",
            )
        artifacts = raw.get("artifacts")
        roots = raw.get("sealed_roots")
        require(
            isinstance(artifacts, Mapping) and isinstance(roots, list),
            f"position {position}: artifact containers malformed",
        )
        for role, descriptor in artifacts.items():
            require(
                isinstance(role, str)
                and role
                and isinstance(descriptor, Mapping)
                and set(descriptor) == ARTIFACT_FIELDS,
                f"position {position}: artifact descriptor malformed",
            )
        for descriptor in roots:
            require(
                isinstance(descriptor, Mapping)
                and set(descriptor) == ROOT_FIELDS,
                f"position {position}: root descriptor malformed",
            )
        if expected_source:
            require(
                REQUIRED_SOURCE_ARTIFACTS.issubset(artifacts),
                f"position {position}: source artifacts missing",
            )
        if eligibility["audited_effective_dag"]:
            require(
                REQUIRED_DAG_ARTIFACTS.issubset(artifacts),
                f"position {position}: audited DAG artifacts missing",
            )
        normalized.append(dict(raw))
    require(
        [row["position"] for row in normalized] == list(range(1, 31)),
        "case index position set/order drift",
    )
    return index, normalized, manifest_cases, phase_rows, index_seal_sha


def _mapping_rows(
    annotation: Mapping[str, Any], case_id: str
) -> tuple[list[dict[str, Any]], str]:
    try:
        return base.duration_blind_mapping_payload(annotation, case_id)
    except base.EvidenceIneligible as exc:
        raise CaseIneligible(*exc.reasons) from exc
    except base.AnalysisError as exc:
        raise ExtensionError(str(exc)) from exc


def _validate_stage_b_audit(
    *,
    case_id: str,
    response: Mapping[str, Any],
    response_sha256: str,
    effective_dag: Mapping[str, Any],
    effective_dag_sha256: str,
    verification: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    require(
        response.get("case_id") == case_id
        and effective_dag.get("case_id") == case_id
        and verification.get("case_id") == case_id
        and audit.get("case_id") == case_id,
        f"{case_id}: Stage-B case identity drift",
    )
    raw_candidate_sha = str(response.get("raw_candidate_sha256") or "")
    require(
        SHA256_RE.fullmatch(raw_candidate_sha) is not None
        and effective_dag.get("raw_candidate_sha256") == raw_candidate_sha,
        f"{case_id}: Stage-B raw-candidate binding drift",
    )
    require(
        str(verification.get("status") or "").lower() in {"pass", "passed"}
        and str(audit.get("status") or "").lower() in {"pass", "passed"},
        f"{case_id}: Stage-B verification/audit not passed",
    )
    require(
        verification.get("effective_reference_dag_sha256")
        == effective_dag_sha256
        and audit.get("effective_reference_dag_sha256")
        == effective_dag_sha256,
        f"{case_id}: effective DAG audit binding drift",
    )
    checks = audit.get("checks")
    require(
        isinstance(checks, Mapping)
        and checks.get("effective_dag_recomputation") is True
        and checks.get("verification_to_artifact_binding") is True,
        f"{case_id}: independent Stage-B audit closure missing",
    )
    raw_decisions = response.get("node_decisions")
    require(isinstance(raw_decisions, list), f"{case_id}: node decisions missing")
    decisions: dict[str, dict[str, Any]] = {}
    for raw in raw_decisions:
        require(isinstance(raw, Mapping), f"{case_id}: malformed node decision")
        node_id = str(raw.get("node_id") or "")
        decision = str(raw.get("decision") or "")
        envelope_raw = raw.get("envelope_id")
        envelope_id = str(envelope_raw) if envelope_raw is not None else None
        require(
            node_id
            and node_id not in decisions
            and decision in {"retain", "move_to_system_envelope"},
            f"{case_id}: invalid or duplicate node decision",
        )
        if decision == "retain":
            require(
                envelope_id in {None, ""},
                f"{case_id}: retained node has envelope id",
            )
            envelope_id = None
        else:
            require(bool(envelope_id), f"{case_id}: moved node lacks envelope id")
        decisions[node_id] = {
            "node_id": node_id,
            "decision": decision,
            "envelope_id": envelope_id,
            "stage_b_response_sha256": response_sha256,
        }
    return decisions


def _validate_overlay(
    *,
    case_id: str,
    overlay: Mapping[str, Any],
    annotation_sha256: str,
    mapping_rows: Sequence[Mapping[str, Any]],
    mapping_sha256: str,
    response_sha256: str,
    response_raw_candidate_sha256: str,
    effective_dag_sha256: str,
    stage_b_decisions: Mapping[str, Mapping[str, Any]],
    effective_node_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], bool]:
    expected_top = {
        "schema_version",
        "status",
        "scientific_result",
        "case_id",
        "claim_layers",
        "input_bindings",
        "attestations",
        "projected_action_count",
        "stage_b_moved_action_count",
        "rows",
        "counters",
    }
    require(set(overlay) == expected_top, f"{case_id}: overlay field closure")
    require(
        overlay.get("schema_version") == OVERLAY_SCHEMA_VERSION
        and overlay.get("status")
        == "materialized_pending_git_freeze_and_independent_verification"
        and overlay.get("scientific_result") is False
        and overlay.get("case_id") == case_id,
        f"{case_id}: overlay identity drift",
    )
    claims = overlay.get("claim_layers")
    require(
        isinstance(claims, Mapping)
        and claims.get("stage_a_mapping")
        == {
            "analysis_mode": "duration_outcome_result_blind",
            "outcome_adjudicated": False,
            "duration_visible": False,
            "mapping_sha256": mapping_sha256,
        }
        and claims.get("effective_overlay")
        == {
            "analysis_mode": (
                "outcome_adjudicated_effective_mapping_not_duration_blind"
            ),
            "outcome_adjudicated": True,
            "duration_visible": False,
        },
        f"{case_id}: overlay claim-layer drift",
    )
    require(
        overlay.get("input_bindings")
        == {
            "stage_a_annotation_sha256": annotation_sha256,
            "stage_a_mapping_sha256": mapping_sha256,
            "stage_b_response_sha256": response_sha256,
            "stage_b_raw_candidate_sha256": response_raw_candidate_sha256,
            "effective_reference_dag_sha256": effective_dag_sha256,
        },
        f"{case_id}: overlay input binding drift",
    )
    require(
        overlay.get("attestations")
        == {
            "stage_a_bytes_unchanged": True,
            "stage_a_mapping_rewritten": False,
            "effective_overlay_is_outcome_adjudicated": True,
            "effective_overlay_claimed_duration_blind": False,
            "duration_not_opened_until_overlay_commit": True,
            "duration_values_consumed": False,
            "moved_actions_remain_auditable": True,
        },
        f"{case_id}: overlay attestations drift",
    )
    require(
        overlay.get("counters")
        == {
            "benchmark_target_invocations": 0,
            "official_evaluator_invocations": 0,
            "provider_model_invocations": 0,
            "task_originated_network_calls": 0,
        },
        f"{case_id}: overlay side-effect counters drift",
    )
    expected_mapping = {
        str(row["projected_action_id"]): {
            "disposition": str(row["disposition"]),
            "semantic_node_ids": sorted(
                str(node_id) for node_id in row["semantic_node_ids"]
            ),
        }
        for row in mapping_rows
    }
    raw_rows = overlay.get("rows")
    require(
        isinstance(raw_rows, list)
        and len(raw_rows) == len(expected_mapping)
        and overlay.get("projected_action_count") == len(raw_rows),
        f"{case_id}: overlay row count drift",
    )
    rows: dict[str, dict[str, Any]] = {}
    mixed = False
    moved_action_count = 0
    expected_row_fields = {
        "projected_action_id",
        "stage_a_disposition",
        "stage_a_semantic_node_ids",
        "effective_disposition",
        "effective_semantic_node_ids",
        "stage_b_node_decision_provenance",
    }
    for raw in raw_rows:
        require(
            isinstance(raw, Mapping) and set(raw) == expected_row_fields,
            f"{case_id}: malformed overlay row",
        )
        action_id = str(raw.get("projected_action_id") or "")
        require(
            action_id in expected_mapping and action_id not in rows,
            f"{case_id}: overlay projected-action identity drift",
        )
        stage_a_disposition = str(raw.get("stage_a_disposition") or "")
        stage_a_ids = sorted(
            str(value) for value in raw.get("stage_a_semantic_node_ids") or []
        )
        require(
            expected_mapping[action_id]
            == {
                "disposition": stage_a_disposition,
                "semantic_node_ids": stage_a_ids,
            },
            f"{case_id}: overlay rewrote immutable Stage-A mapping",
        )
        raw_provenance = raw.get("stage_b_node_decision_provenance")
        require(isinstance(raw_provenance, list), f"{case_id}: provenance missing")
        provenance: dict[str, dict[str, Any]] = {}
        for value in raw_provenance:
            require(isinstance(value, Mapping), f"{case_id}: bad provenance row")
            node_id = str(value.get("node_id") or "")
            require(
                node_id in stage_b_decisions
                and node_id not in provenance
                and dict(value) == stage_b_decisions[node_id],
                f"{case_id}: Stage-B decision provenance drift",
            )
            provenance[node_id] = dict(value)
        require(
            set(provenance) == set(stage_a_ids),
            f"{case_id}: overlay provenance coverage mismatch",
        )
        retained = sorted(
            node_id
            for node_id, value in provenance.items()
            if value["decision"] == "retain"
        )
        moved = sorted(set(provenance) - set(retained))
        effective_ids = sorted(
            str(value) for value in raw.get("effective_semantic_node_ids") or []
        )
        require(
            effective_ids == retained and set(effective_ids).issubset(effective_node_ids),
            f"{case_id}: overlay effective target drift",
        )
        if stage_a_disposition in {
            "discard_redundant_exploration",
            "discard_tool_noise",
            "move_to_system_envelope",
        }:
            require(
                not stage_a_ids
                and not provenance
                and not effective_ids
                and raw.get("effective_disposition") == stage_a_disposition,
                f"{case_id}: nonsemantic overlay row drift",
            )
        else:
            expected_disposition = stage_a_disposition
            if not retained:
                expected_disposition = "move_to_system_envelope"
            elif moved:
                expected_disposition = (
                    "split_across_effective_semantic_nodes_and_system_envelope"
                )
                mixed = True
            require(
                raw.get("effective_disposition") == expected_disposition,
                f"{case_id}: effective disposition drift",
            )
        if moved:
            moved_action_count += 1
        rows[action_id] = {
            **dict(raw),
            "_provenance": provenance,
            "_retained_ids": retained,
            "_moved_ids": moved,
        }
    require(set(rows) == set(expected_mapping), f"{case_id}: overlay coverage drift")
    require(
        overlay.get("stage_b_moved_action_count") == moved_action_count,
        f"{case_id}: moved-action count drift",
    )
    retained_stage_b = {
        node_id
        for node_id, decision in stage_b_decisions.items()
        if decision["decision"] == "retain"
    }
    require(
        retained_stage_b == effective_node_ids,
        f"{case_id}: effective DAG differs from retained Stage-B node set",
    )
    return rows, mixed


def _projection_identity(
    *,
    case_id: str,
    projection: Mapping[str, Any],
    observed: Mapping[str, Any],
    mapping_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], float]:
    raw_projection = projection.get("node_projection")
    raw_observed = observed.get("rows")
    require(
        isinstance(raw_projection, list) and isinstance(raw_observed, list),
        f"{case_id}: projection/action identity rows missing",
    )
    projected: dict[str, str] = {}
    source_to_projected: dict[str, str] = {}
    for raw in raw_projection:
        require(isinstance(raw, Mapping), f"{case_id}: projection row malformed")
        action_id = str(raw.get("projected_action_id") or "")
        source_id = str(raw.get("source_node_id") or "")
        require(
            action_id
            and source_id
            and action_id not in projected
            and source_id not in source_to_projected,
            f"{case_id}: projection identity not exactly once",
        )
        projected[action_id] = source_id
        source_to_projected[source_id] = action_id
    mapping_ids = {str(row["projected_action_id"]) for row in mapping_rows}
    require(
        set(projected) == mapping_ids,
        f"{case_id}: Stage-A/projection action-set mismatch",
    )
    observed_by_source: dict[str, dict[str, Any]] = {}
    observed_ids: set[str] = set()
    duration_sum = 0.0
    for raw in raw_observed:
        require(isinstance(raw, Mapping), f"{case_id}: observed row malformed")
        source_id = str(raw.get("source_node_id") or "")
        observed_id = str(raw.get("observed_action_id") or "")
        duration = raw.get("duration_seconds")
        require(
            source_id
            and observed_id
            and source_id not in observed_by_source
            and observed_id not in observed_ids
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(float(duration))
            and float(duration) > 0,
            f"{case_id}: invalid or duplicate observed action",
        )
        observed_ids.add(observed_id)
        duration_sum += float(duration)
        observed_by_source[source_id] = {
            "source_node_id": source_id,
            "observed_action_id": observed_id,
            "duration_seconds": float(duration),
        }
    require(
        set(observed_by_source) == set(source_to_projected),
        f"{case_id}: observed/projection source-node set mismatch",
    )
    require(
        observed.get("action_count") == len(raw_observed)
        and math.isclose(
            float(observed.get("duration_sum_seconds", -1)),
            duration_sum,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        and float(observed.get("imputed_duration_seconds", -1)) == 0.0
        and float(observed.get("uncovered_duration_seconds", -1)) == 0.0,
        f"{case_id}: observed action ledger closure drift",
    )
    return {
        action_id: observed_by_source[source_id]
        for action_id, source_id in projected.items()
    }, duration_sum


def attach_effective_durations(
    *,
    case_id: str,
    dag: Mapping[str, Any],
    mapping_rows: Sequence[Mapping[str, Any]],
    overlay_rows: Mapping[str, Mapping[str, Any]],
    projected_observations: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, float], dict[str, Any]]:
    mapping = {
        str(row["projected_action_id"]): dict(row) for row in mapping_rows
    }
    require(
        set(mapping) == set(overlay_rows) == set(projected_observations),
        f"{case_id}: duration-join action set mismatch",
    )
    node_ids = {str(node["node_id"]) for node in dag["nodes"]}
    semantic: defaultdict[str, float] = defaultdict(float)
    envelope: defaultdict[str, float] = defaultdict(float)
    redundant = 0.0
    tool_noise = 0.0
    normalized_rows: list[dict[str, Any]] = []
    all_seconds = 0.0
    for action_id in sorted(mapping):
        stage_a = mapping[action_id]
        overlay = overlay_rows[action_id]
        observed = projected_observations[action_id]
        duration = float(observed["duration_seconds"])
        all_seconds += duration
        disposition = str(stage_a["disposition"])
        stage_a_ids = sorted(str(value) for value in stage_a["semantic_node_ids"])
        retained = list(overlay["_retained_ids"])
        moved = list(overlay["_moved_ids"])
        semantic_allocations: dict[str, float] = {}
        envelope_id = None
        category: str
        if disposition in {"retain", "merge_into_semantic_node"}:
            require(
                len(stage_a_ids) == 1,
                f"{case_id}: direct semantic action target drift",
            )
            if retained and moved:
                raise CaseIneligible("blocked_mixed_semantic_envelope_split")
            if retained:
                node_id = retained[0]
                require(node_id in node_ids, f"{case_id}: retained node absent")
                semantic[node_id] += duration
                semantic_allocations[node_id] = duration
                category = "effective_semantic_work"
            else:
                require(len(moved) == 1, f"{case_id}: moved target drift")
                envelope_id = str(
                    overlay["_provenance"][moved[0]]["envelope_id"]
                )
                envelope[envelope_id] += duration
                category = "system_envelope"
        elif disposition == "split_across_semantic_nodes":
            if retained and moved:
                # Frozen semantic decision: never allocate a single observed
                # action by duration, ratio, equal split, or later outcome.
                raise CaseIneligible("blocked_mixed_semantic_envelope_split")
            if retained:
                raise CaseIneligible(
                    "blocked_split_semantic_duration_allocation_missing"
                )
            require(bool(moved), f"{case_id}: split action has no disposition")
            envelope_ids = sorted(
                {
                    str(overlay["_provenance"][node_id]["envelope_id"])
                    for node_id in moved
                }
            )
            envelope_id = (
                envelope_ids[0]
                if len(envelope_ids) == 1
                else "multiple_stage_b_envelopes_unallocated"
            )
            envelope[envelope_id] += duration
            category = "system_envelope"
        elif disposition == "move_to_system_envelope":
            envelope_id = "stage_a_preclassified_system_envelope"
            envelope[envelope_id] += duration
            category = "system_envelope"
        elif disposition == "discard_redundant_exploration":
            redundant += duration
            category = "redundant_exploration"
        elif disposition == "discard_tool_noise":
            tool_noise += duration
            category = "tool_noise"
        else:
            raise ExtensionError(f"{case_id}: unknown Stage-A disposition")
        normalized_rows.append(
            {
                "projected_action_id": action_id,
                "observed_action_id": observed["observed_action_id"],
                "source_node_id": observed["source_node_id"],
                "duration_seconds": duration,
                "stage_a_disposition": disposition,
                "stage_a_semantic_node_ids": stage_a_ids,
                "effective_disposition": overlay["effective_disposition"],
                "effective_semantic_node_ids": list(
                    overlay["effective_semantic_node_ids"]
                ),
                "duration_partition_category": category,
                "semantic_allocations_seconds": semantic_allocations,
                "system_envelope_id": envelope_id,
            }
        )
    semantic_seconds = sum(semantic.values())
    envelope_seconds = sum(envelope.values())
    partition_sum = semantic_seconds + envelope_seconds + redundant + tool_noise
    require(
        math.isclose(partition_sum, all_seconds, rel_tol=1e-9, abs_tol=1e-9),
        f"{case_id}: action duration partition not conserved",
    )
    require(
        semantic and all(value > 0 for value in semantic.values()),
        f"{case_id}: no positive effective semantic work",
    )
    active = set(semantic)
    for edge in dag["edges"]:
        source, target = str(edge["src"]), str(edge["dst"])
        if target in active and source not in active:
            raise CaseIneligible(
                "blocked_active_effective_dag_predecessor_without_duration"
            )
    return dict(sorted(semantic.items())), {
        "case_id": case_id,
        "status": "pass",
        "mapping_claim_layers": {
            "stage_a_mapping": "duration_outcome_result_blind_immutable",
            "effective_mapping": "outcome_adjudicated_not_duration_blind",
        },
        "active_effective_semantic_node_ids": sorted(active),
        "inactive_effective_semantic_node_ids": sorted(node_ids - active),
        "duration_partition_seconds": {
            "effective_semantic_work": semantic_seconds,
            "system_envelope": envelope_seconds,
            "redundant_exploration": redundant,
            "tool_noise": tool_noise,
        },
        "system_envelope_by_id_seconds": dict(sorted(envelope.items())),
        "all_action_seconds": all_seconds,
        "conservation_delta_seconds": all_seconds - partition_sum,
        "imputed_duration_seconds": 0.0,
        "uncovered_duration_seconds": 0.0,
        "rows": normalized_rows,
    }


def _base_row(
    frozen: Mapping[str, Any],
    index_row: Mapping[str, Any],
    phase_row: Mapping[str, Any],
) -> dict[str, Any]:
    declared = dict(index_row["eligibility"])
    return {
        "position": frozen["position"],
        "case_id": frozen["case_id"],
        "instance_id": frozen["instance_id"],
        "physical_repository": frozen["physical_repository"],
        "base_commit": frozen["base_commit"],
        "difficulty": frozen.get("difficulty"),
        "repository_domain_family": frozen.get("repository_domain_family"),
        "declared_eligibility": declared,
        "source_trace_eligible": False,
        "contiguous_e2e_phase_eligible": declared["contiguous_e2e_phase"],
        "audited_effective_dag_eligible": False,
        "observed_duration_join_eligible": False,
        "paired_executor_D_eligible": False,
        "phase_composition": (
            phase_row.get("phase_composition")
            if declared["contiguous_e2e_phase"]
            else None
        ),
        "type_weighted_metrics": None,
        "observed_duration_metrics": None,
        "duration_partition": None,
        "stage_a_annotation_sha256": None,
        "stage_a_mapping_sha256": None,
        "effective_action_overlay_sha256": None,
        "effective_reference_dag_sha256": None,
        "attrition_reasons": list(index_row["retained_attrition_reasons"]),
        "input_root_evidence": [],
    }


def _validate_source_identity(
    case_id: str,
    frozen: Mapping[str, Any],
    source: Mapping[str, Any],
    observed_path: Path,
) -> None:
    require(
        source.get("case_id") == case_id
        and source.get("position") == frozen["position"]
        and source.get("instance_id") == frozen["instance_id"]
        and source.get("physical_repository") == frozen["physical_repository"]
        and source.get("base_commit") == frozen["base_commit"]
        and source.get("status") == "qualified_source_trace"
        and source.get("source_qualification_uses_quality_speedup_or_sign")
        is False,
        f"{case_id}: source identity drift",
    )
    observed_binding = source.get("observed_action_identity")
    require(
        isinstance(observed_binding, Mapping)
        and observed_binding.get("sha256") == sha256_file(observed_path)
        and observed_binding.get("imputed_duration_seconds") == 0.0
        and observed_binding.get("uncovered_duration_seconds") == 0.0,
        f"{case_id}: observed-action source binding drift",
    )


def _validate_c_labels(rows: Sequence[Mapping[str, Any]]) -> None:
    allowed = {
        "observed_at_or_above_1_10",
        "observed_below_1_10",
        "undefined_without_observed_duration_join",
    }
    for row in rows:
        require(
            row["physical_repository"] in HELD_OUT_REPOSITORIES,
            "C development-repository leakage",
        )
        observed = row.get("observed_ceiling")
        expected = (
            "undefined_without_observed_duration_join"
            if observed is None
            else (
                "observed_at_or_above_1_10"
                if float(observed) >= base.C_PRIMARY_THRESHOLD
                else "observed_below_1_10"
            )
        )
        require(
            row.get("bounded_validation_label") == expected
            and expected in allowed,
            "C bounded validation label drift",
        )


def build_analysis(
    case_index_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    (
        index,
        index_rows,
        manifest_cases,
        phase_rows,
        index_seal_sha,
    ) = validate_case_index(case_index_path)
    resolver = RootResolver(case_index_path, test_only=bool(index["test_only"]))
    rows: list[dict[str, Any]] = []
    ledger_cases: list[dict[str, Any]] = []
    c_rows: list[dict[str, Any]] = []
    for frozen, index_row in zip(manifest_cases, index_rows):
        position = int(frozen["position"])
        case_id = str(frozen["case_id"])
        row = _base_row(frozen, index_row, phase_rows[position])
        if position in SOURCE_ATTRITION_POSITIONS:
            rows.append(row)
            continue
        artifacts, root_evidence = resolver.artifacts(index_row)
        row["input_root_evidence"] = root_evidence
        source = read_json(artifacts["source_identity"])
        observed_identity = read_json(artifacts["observed_action_identity"])
        _validate_source_identity(
            case_id, frozen, source, artifacts["observed_action_identity"]
        )
        row["source_trace_eligible"] = True
        if not index_row["eligibility"]["audited_effective_dag"]:
            rows.append(row)
            continue
        annotation = read_json(artifacts["stage_a_annotation"])
        mapping_rows: list[dict[str, Any]]
        mapping_sha: str
        try:
            mapping_rows, mapping_sha = _mapping_rows(annotation, case_id)
        except CaseIneligible as exc:
            row["attrition_reasons"].extend(exc.reasons)
            row["attrition_reasons"] = sorted(set(row["attrition_reasons"]))
            rows.append(row)
            continue
        annotation_sha = sha256_file(artifacts["stage_a_annotation"])
        response = read_json(artifacts["stage_b_response"])
        response_sha = sha256_file(artifacts["stage_b_response"])
        effective_raw = read_json(artifacts["effective_reference_dag"])
        effective_sha = sha256_file(artifacts["effective_reference_dag"])
        verification = read_json(artifacts["stage_b_verification"])
        audit = read_json(artifacts["stage_b_independent_audit"])
        decisions = _validate_stage_b_audit(
            case_id=case_id,
            response=response,
            response_sha256=response_sha,
            effective_dag=effective_raw,
            effective_dag_sha256=effective_sha,
            verification=verification,
            audit=audit,
        )
        try:
            dag = base.normalize_dag(effective_raw, case_id)
        except base.AnalysisError as exc:
            raise ExtensionError(str(exc)) from exc
        overlay = read_json(artifacts["effective_action_overlay"])
        overlay_rows, has_mixed = _validate_overlay(
            case_id=case_id,
            overlay=overlay,
            annotation_sha256=annotation_sha,
            mapping_rows=mapping_rows,
            mapping_sha256=mapping_sha,
            response_sha256=response_sha,
            response_raw_candidate_sha256=str(
                response["raw_candidate_sha256"]
            ),
            effective_dag_sha256=effective_sha,
            stage_b_decisions=decisions,
            effective_node_ids={str(node["node_id"]) for node in dag["nodes"]},
        )
        row["stage_a_annotation_sha256"] = annotation_sha
        row["stage_a_mapping_sha256"] = mapping_sha
        row["effective_action_overlay_sha256"] = sha256_file(
            artifacts["effective_action_overlay"]
        )
        row["effective_reference_dag_sha256"] = effective_sha
        row["audited_effective_dag_eligible"] = True
        row["type_weighted_metrics"] = base.graph_metrics(
            dag, base.type_durations(dag)
        )
        observed_durations: dict[str, float] | None = None
        if index_row["eligibility"]["observed_duration_join"]:
            try:
                if has_mixed:
                    raise CaseIneligible(
                        "blocked_mixed_semantic_envelope_split"
                    )
                projection = read_json(artifacts["projection_lineage"])
                projected, expected_seconds = _projection_identity(
                    case_id=case_id,
                    projection=projection,
                    observed=observed_identity,
                    mapping_rows=mapping_rows,
                )
                observed_durations, ledger = attach_effective_durations(
                    case_id=case_id,
                    dag=dag,
                    mapping_rows=mapping_rows,
                    overlay_rows=overlay_rows,
                    projected_observations=projected,
                )
                require(
                    math.isclose(
                        ledger["all_action_seconds"],
                        expected_seconds,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    ),
                    f"{case_id}: joined duration differs from source ledger",
                )
                active_dag = base.induced_dag(dag, observed_durations)
                row["observed_duration_metrics"] = base.graph_metrics(
                    active_dag, observed_durations
                )
                row["duration_partition"] = ledger[
                    "duration_partition_seconds"
                ]
                row["observed_duration_join_eligible"] = True
                ledger.update(
                    {
                        "stage_a_annotation_sha256": annotation_sha,
                        "stage_a_mapping_sha256": mapping_sha,
                        "effective_action_overlay_sha256": row[
                            "effective_action_overlay_sha256"
                        ],
                        "effective_reference_dag_sha256": effective_sha,
                    }
                )
                ledger_cases.append(ledger)
            except CaseIneligible as exc:
                row["attrition_reasons"].extend(exc.reasons)
        c_rows.extend(
            base.build_c_candidates(
                case=frozen,
                dag=dag,
                observed_durations=observed_durations,
            )
        )
        row["attrition_reasons"] = sorted(set(row["attrition_reasons"]))
        rows.append(row)
    require(len(rows) == 30, "P30 denominator loss")
    c_rows = base.deduplicate_c_candidates(c_rows)
    base.validate_c_heldout_rows(c_rows)
    for c_row in c_rows:
        observed = c_row.get("observed_ceiling")
        c_row["bounded_validation_label"] = (
            "undefined_without_observed_duration_join"
            if observed is None
            else (
                "observed_at_or_above_1_10"
                if float(observed) >= base.C_PRIMARY_THRESHOLD
                else "observed_below_1_10"
            )
        )
        c_row["label_source"] = (
            "observed_duration_reference_only_not_quality_or_evaluator_outcome"
        )
        c_row["scientific_result"] = False
        c_row["preregistered_primary"] = False
    _validate_c_labels(c_rows)
    audited_count = sum(row["audited_effective_dag_eligible"] for row in rows)
    joined_count = sum(row["observed_duration_join_eligible"] for row in rows)
    source_count = sum(row["source_trace_eligible"] for row in rows)
    phase_count = sum(row["contiguous_e2e_phase_eligible"] for row in rows)
    partition_totals = {
        category: sum(
            float(row["duration_partition"][category])
            for row in rows
            if isinstance(row.get("duration_partition"), Mapping)
        )
        for category in (
            "effective_semantic_work",
            "system_envelope",
            "redundant_exploration",
            "tool_noise",
        )
    }
    recovery_report = read_json(PHASE_RECOVERY_ROOT / "recovery_report.json")
    report = {
        "schema_version": SCHEMA_VERSION,
        "extension_id": CONTRACT_ID,
        "status": RESULT_ROLE,
        "result_role": RESULT_ROLE,
        "scientific_result": False,
        "preregistered_primary": False,
        "primary_result": False,
        "test_only": bool(index["test_only"]),
        "fixture_or_synthetic": bool(index["fixture_or_synthetic"]),
        "design_id": base.DESIGN_ID,
        "campaign_id": base.CAMPAIGN_ID,
        "cohort_membership_sha256": base.COHORT_MEMBERSHIP_SHA256,
        "input_bindings": {
            "contract_extension_path": str(CONTRACT_PATH.resolve()),
            "contract_extension_sha256": CONTRACT_SHA256,
            "case_index_schema_path": str(CASE_INDEX_SCHEMA_PATH.resolve()),
            "case_index_schema_sha256": CASE_INDEX_SCHEMA_SHA256,
            "base_analyzer_path": str(BASE_ANALYZER_PATH.resolve()),
            "base_analyzer_sha256": BASE_ANALYZER_SHA256,
            "base_analyzer_modified_by_extension": False,
            "phase_recovery_result_path": str(PHASE_RECOVERY_ROOT.resolve()),
            "phase_recovery_result_seal_sha256": PHASE_RECOVERY_SEAL_SHA256,
            "case_index_path": str(case_index_path.resolve()),
            "case_index_sha256": sha256_file(case_index_path.resolve()),
            "case_index_seal_sha256": index_seal_sha,
            "extension_driver_sha256": sha256_file(Path(__file__).resolve()),
        },
        "eligibility_denominators": {
            "intention_to_measure": 30,
            "source_trace": source_count,
            "contiguous_e2e_phase": phase_count,
            "audited_effective_dag": audited_count,
            "observed_duration_join": joined_count,
            "paired_executor_D": 0,
            "target_only_action_layer_positions": [3, 6],
            "retained_source_attrition_positions": [1, 2, 4, 5, 11],
        },
        "attrition": {
            "case_rows_retained": 30,
            "reason_counts": dict(
                sorted(
                    Counter(
                        reason
                        for row in rows
                        for reason in row["attrition_reasons"]
                    ).items()
                )
            ),
        },
        "action_duration_partition": {
            "joined_case_count": joined_count,
            "seconds": partition_totals,
            "all_action_seconds": sum(partition_totals.values()),
            "exact_conservation_per_case_required": True,
            "imputed_duration_seconds": 0.0,
            "uncovered_duration_seconds": 0.0,
        },
        "experiment_A": {
            "whole_task_phase_composition": recovery_report[
                "whole_task_phase_composition"
            ],
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
        },
        "experiment_C": base._c_report(c_rows),
        "C_bounded_validation": {
            "held_out_repositories": sorted(HELD_OUT_REPOSITORIES),
            "primary_threshold": base.C_PRIMARY_THRESHOLD,
            "label_counts": dict(
                sorted(Counter(row["bounded_validation_label"] for row in c_rows).items())
            ),
            "quality_or_evaluator_outcome_used_for_labels": False,
        },
        "offline_analysis_delta": {
            "model_or_api_invocations": 0,
            "benchmark_target_invocations": 0,
            "official_evaluator_invocations": 0,
            "task_originated_network_calls": 0,
        },
        "claim_boundary": {
            "post_collection_extension_not_preregistered_primary": True,
            "fixtures_or_synthetic_as_scientific_result": False,
            "positions_003_006_whole_task_E2E_or_D_eligible": False,
            "online_acceleration_claim": False,
            "raw_v8_plan_or_results_rewritten": False,
        },
    }
    ledger = {
        "schema_version": "sge-p30-effective-action-duration-ledger-v2",
        "status": RESULT_ROLE,
        "scientific_result": False,
        "preregistered_primary": False,
        "case_count_intention": 30,
        "joined_case_count": len(ledger_cases),
        "duration_partition_categories": [
            "effective_semantic_work",
            "system_envelope",
            "redundant_exploration",
            "tool_noise",
        ],
        "mixed_split_rule": "blocked_mixed_semantic_envelope_split",
        "cases": sorted(ledger_cases, key=lambda value: value["case_id"]),
    }
    for row in rows:
        row["scientific_result"] = False
        row["preregistered_primary"] = False
    return report, rows, ledger, c_rows


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
        "schema_version": "sge-p30-ac-overlay-v2-artifact-inventory-v1",
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


def _publish_no_replace(source: Path, destination: Path) -> None:
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
            raise ExtensionError("result root already exists")
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
            raise ExtensionError("result root already exists")
        raise OSError(error, os.strerror(error), str(destination))
    raise ExtensionError("atomic no-replace publication unavailable")


def write_bundle(case_index_path: Path, result_root: Path) -> dict[str, Any]:
    require(not result_root.exists(), "result root already exists")
    payloads = build_analysis(case_index_path)
    parent = result_root.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{result_root.name}.tmp-", dir=parent))
    try:
        for name, value in zip(OUTPUT_DATA_FILES, payloads):
            _write_exclusive(temporary / name, pretty_bytes(value))
        _seal_output(temporary)
        _publish_no_replace(temporary, result_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return payloads[0]


def verify_output_seal(root: Path) -> None:
    require(root.is_dir() and not root.is_symlink(), "result root missing")
    rows = parse_seal(root / "SHA256SUMS")
    require(set(rows) == set(OUTPUT_FILES), "result seal file-set mismatch")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    require(actual == set(OUTPUT_FILES), "unsealed result artifact detected")
    for name, digest in rows.items():
        require(sha256_file(root / name) == digest, f"result tamper: {name}")
    inventory = read_json(root / "artifact_inventory.json")
    indexed = {
        str(row["path"]): (int(row["bytes"]), str(row["sha256"]))
        for row in inventory.get("artifacts") or []
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


def verify_bundle(result_root: Path) -> dict[str, Any]:
    root = result_root.resolve()
    verify_output_seal(root)
    stored = read_json(root / "extension_report.json")
    bindings = stored.get("input_bindings")
    require(isinstance(bindings, Mapping), "result input bindings missing")
    require(
        bindings.get("base_analyzer_sha256") == BASE_ANALYZER_SHA256
        and bindings.get("base_analyzer_modified_by_extension") is False
        and bindings.get("contract_extension_sha256") == CONTRACT_SHA256,
        "result immutable-base binding drift",
    )
    index_path = Path(str(bindings.get("case_index_path") or ""))
    require(
        sha256_file(index_path) == bindings.get("case_index_sha256"),
        "case index changed after analysis",
    )
    current = build_analysis(index_path)
    for name, value in zip(OUTPUT_DATA_FILES, current):
        require(
            read_json_value(root / name) == value,
            f"result no longer recomputes exactly: {name}",
        )
    return {
        "status": "passed",
        "result_role": RESULT_ROLE,
        "scientific_result": False,
        "preregistered_primary": False,
        "eligibility_denominators": current[0]["eligibility_denominators"],
        "sealed_artifact_count": len(OUTPUT_FILES),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect-index")
    inspect.add_argument("--case-index", type=Path, required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--case-index", type=Path, required=True)
    prepare.add_argument("--result-root", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "inspect-index":
            _, rows, _, _, seal_sha = validate_case_index(args.case_index)
            result = {
                "status": "passed",
                "case_count": len(rows),
                "source_trace": sum(
                    row["eligibility"]["source_trace"] for row in rows
                ),
                "contiguous_e2e_phase": sum(
                    row["eligibility"]["contiguous_e2e_phase"] for row in rows
                ),
                "audited_effective_dag_declared": sum(
                    row["eligibility"]["audited_effective_dag"] for row in rows
                ),
                "observed_duration_join_declared": sum(
                    row["eligibility"]["observed_duration_join"] for row in rows
                ),
                "paired_executor_D": 0,
                "case_index_seal_sha256": seal_sha,
            }
        elif args.command == "prepare":
            report = write_bundle(args.case_index, args.result_root)
            result = {
                "status": report["status"],
                "result_role": report["result_role"],
                "scientific_result": False,
                "preregistered_primary": False,
                "eligibility_denominators": report["eligibility_denominators"],
                "result_root": str(args.result_root),
            }
        else:
            result = verify_bundle(args.result_root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        ExtensionError,
        CaseIneligible,
        base.AnalysisError,
        base.EvidenceIneligible,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
