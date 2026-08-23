#!/usr/bin/env python3
"""Validate the reviewer bundle, privacy boundary, and package hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "provenance" / "artifact_manifest.json"
SUMS_PATH = ROOT / "SHA256SUMS"
REPORT_PATH = ROOT / "audit" / "verification_report.json"
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mplconfig"}
MANIFEST_EXCLUDES = {MANIFEST_PATH, SUMS_PATH}
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".py", ".txt", ".toml", ".yaml", ".yml"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path in MANIFEST_EXCLUDES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def required_files() -> list[str]:
    return [
        "README.md",
        "CLAIMS.md",
        "OPEN_SOURCE_SCOPE.md",
        "LICENSE_STATUS.md",
        "VENUE_POLICY.md",
        "supplement_manifest.json",
        "evidence/figure_contract.json",
        "provenance/source_provenance.json",
        "audit/sanitization_report.json",
        "audit/accessibility_manifest.json",
        "audit/figure_bundle_audit.json",
        "scripts/recompute_claims.py",
        "scripts/build_submission_visuals.py",
        "results/historical_same_trace_replay/summary.csv",
        "results/sge_p30_ac_overlay_v2_20260728/case_rows.json",
        "results/sge_c1_structural_validation_20260729/window_rows.json",
        "results/sge_p30_paired_scale_audit_20260728/P007/evidence_integration.json",
        "results/sge_p30_paired_scale_audit_20260728/P018/evidence_integration.json",
        "outputs/recomputed_claims.json",
        "outputs/figures/figure_manifest.json",
    ]


def validate_supplement_manifest() -> None:
    manifest = json.loads((ROOT / "supplement_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("items"), list):
        raise AssertionError("supplement_manifest.json has an invalid root schema")
    categories = {
        "reproducibility",
        "extended-results",
        "limitations",
        "proofs",
        "prompts",
        "code-artifact",
        "anonymity-audit",
    }
    statuses = {"none", "optional", "required"}
    actions = {"move-to-main", "keep-optional", "sanitize", "remove"}
    if manifest.get("review_status") not in statuses:
        raise AssertionError("supplement manifest has an invalid review_status")
    if manifest.get("main_text_self_contained_after_actions") is not True:
        raise AssertionError("main paper must remain self-contained")
    if not isinstance(manifest.get("anonymity_ready_after_actions"), bool):
        raise AssertionError("supplement manifest lacks the privacy-readiness gate")
    seen: set[str] = set()
    for item in manifest["items"]:
        for field in ("item_id", "categories", "title", "path", "action", "reason"):
            if field not in item:
                raise AssertionError(f"supplement item is missing {field}: {item!r}")
        if item["item_id"] in seen:
            raise AssertionError(f"duplicate supplement item: {item['item_id']}")
        seen.add(item["item_id"])
        if not isinstance(item["categories"], list) or any(value not in categories for value in item["categories"]):
            raise AssertionError(f"invalid supplement categories: {item['categories']}")
        if item["action"] not in actions:
            raise AssertionError(f"invalid supplement action: {item['action']}")
        if not (ROOT / item["path"]).exists():
            raise AssertionError(f"supplement item path does not exist: {item['path']}")


def validate_no_restricted_families() -> None:
    forbidden_names = {
        "auth.json",
        "history.jsonl",
        "trace.jsonl",
        "events.jsonl",
        "model_last_message.txt",
        "evaluator.stdout.log",
        "evaluator.stderr.log",
    }
    found = [path.relative_to(ROOT).as_posix() for path in package_files() if path.name in forbidden_names]
    if found:
        raise AssertionError(f"restricted raw artifact family included: {found}")


def validate_text_safety() -> int:
    forbidden_literals = [
        "/Users" + "/joe/",
        "/home" + "/joe/",
        ".codex" + "/sessions",
        "decentralized" + "black-maker",
    ]
    secret_patterns = [
        re.compile("sk" + r"-[A-Za-z0-9_-]{20,}"),
        re.compile("ghp" + r"_[A-Za-z0-9]{20,}"),
        re.compile("Bearer" + r"\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
        re.compile(r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[=:]\s*[\"'][^\"']{12,}[\"']", re.IGNORECASE),
    ]
    scanned = 0
    findings: list[str] = []
    for path in package_files():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        for literal in forbidden_literals:
            if literal in text:
                findings.append(f"{relative}: forbidden literal category")
        for pattern in secret_patterns:
            if pattern.search(text):
                findings.append(f"{relative}: credential-like token")
    if findings:
        raise AssertionError("reviewer-safety scan failed: " + "; ".join(sorted(set(findings))))
    return scanned


def validate_invalid_pairs() -> None:
    for case in ("P007", "P018"):
        path = ROOT / "results" / "sge_p30_paired_scale_audit_20260728" / case / "evidence_integration.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("terminal_status") != "invalid" or evidence.get("pair_validity") != "invalid":
            raise AssertionError(f"{case} failure evidence was weakened")
        metrics = evidence.get("paired_metrics", {})
        if not metrics or any(value is not None for value in metrics.values()):
            raise AssertionError(f"{case} formal paired metrics must remain null")


def validate_figure_governance() -> None:
    contract = json.loads((ROOT / "evidence" / "figure_contract.json").read_text(encoding="utf-8"))
    if contract.get("schema_version") != 2 or len(contract.get("figures", [])) != 5:
        raise AssertionError("figure contract must declare exactly five schema-v2 figures")
    for source in contract.get("source_artifacts", []):
        path = ROOT / source["path"]
        if not path.is_file() or sha256_file(path) != source["sha256"]:
            raise AssertionError(f"figure source hash mismatch: {source['path']}")
    preview_count = 0
    for figure in contract["figures"]:
        for artifact in figure.get("artifacts", []):
            path = ROOT / artifact["path"]
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise AssertionError(f"figure artifact hash mismatch: {artifact['path']}")
        for preview in figure.get("accessibility_outputs", []):
            path = ROOT / preview["path"]
            if not path.is_file():
                raise AssertionError(f"accessibility preview missing: {preview['path']}")
            preview_count += 1
    if preview_count != 20:
        raise AssertionError(f"expected 20 accessibility previews, observed {preview_count}")

    accessibility = json.loads((ROOT / "audit" / "accessibility_manifest.json").read_text(encoding="utf-8"))
    if accessibility.get("status") != "pass" or len(accessibility.get("figures", [])) != 5:
        raise AssertionError("accessibility manifest is incomplete")
    for figure in accessibility["figures"]:
        for output in figure.get("outputs", []):
            path = ROOT / output["path"]
            if not path.is_file() or sha256_file(path) != output["sha256"]:
                raise AssertionError(f"accessibility hash mismatch: {output['path']}")

    audit = json.loads((ROOT / "audit" / "figure_bundle_audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("issues"):
        raise AssertionError("figure bundle audit is not passing")


def build_manifest() -> dict[str, Any]:
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in package_files()
    ]
    return {
        "schema_version": 1,
        "root": ".",
        "hash_algorithm": "sha256",
        "self_excluded": ["provenance/artifact_manifest.json", "SHA256SUMS"],
        "file_count": len(entries),
        "files": entries,
    }


def write_manifests(manifest: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [f"{row['sha256']}  {row['path']}" for row in manifest["files"]]
    SUMS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_manifest(observed: dict[str, Any]) -> None:
    if not MANIFEST_PATH.is_file():
        raise AssertionError("artifact manifest is missing")
    expected = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if expected != observed:
        expected_map = {row["path"]: row["sha256"] for row in expected.get("files", [])}
        observed_map = {row["path"]: row["sha256"] for row in observed.get("files", [])}
        changed = sorted(path for path in set(expected_map) | set(observed_map) if expected_map.get(path) != observed_map.get(path))
        raise AssertionError(f"artifact manifest mismatch: {changed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write-manifest", action="store_true")
    mode.add_argument("--check-manifest", action="store_true")
    args = parser.parse_args()

    missing = [relative for relative in required_files() if not (ROOT / relative).is_file()]
    if missing:
        raise AssertionError(f"required reviewer files missing: {missing}")
    validate_supplement_manifest()
    validate_no_restricted_families()
    scanned = validate_text_safety()
    validate_invalid_pairs()
    validate_figure_governance()

    report = {
        "schema_version": 1,
        "status": "pass",
        "checks": [
            "required_files",
            "supplement_manifest_schema",
            "restricted_raw_family_exclusion",
            "machine_path_and_credential_scan",
            "invalid_pair_null_metric_preservation",
            "figure_source_output_hashes_and_accessibility",
            "figure_geometry_fonts_vector_audit",
        ],
        "text_files_scanned": scanned,
        "network_calls": 0,
        "model_calls": 0,
        "official_evaluator_calls": 0,
    }
    if args.write_manifest:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    observed = build_manifest()
    if args.write_manifest:
        write_manifests(observed)
    elif args.check_manifest:
        check_manifest(observed)
    print(json.dumps({**report, "manifest_file_count": observed["file_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
