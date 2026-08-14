#!/usr/bin/env python3
"""Fail closed on common public-release and reviewer-artifact hazards."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "artifact" / "reviewer_snapshot"
IGNORED_PARTS = {".git", ".pytest_cache", "__pycache__", ".venv", "verification"}
TEXT_SUFFIXES = {".cff", ".csv", ".json", ".jsonl", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
FORBIDDEN_NAMES = {
    "auth.json",
    "events.jsonl",
    "history.jsonl",
    "model_last_message.txt",
    "run_candidate_dag_executor_v2.py",
    "run_canonical_dag_executor_family_smoke.py",
    "trace.jsonl",
}
REQUIRED = {
    "README.md",
    "LICENSE",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "src/sge/__init__.py",
    "src/sge/cli.py",
    "examples/minimal_workgraph.json",
    "artifact/README.md",
    "artifact/reviewer_snapshot/CLAIMS.md",
    "artifact/reviewer_snapshot/provenance/artifact_manifest.json",
}


def files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)
    )


def check_required() -> None:
    missing = sorted(relative for relative in REQUIRED if not (ROOT / relative).is_file())
    if missing:
        raise AssertionError(f"required public files missing: {missing}")


def check_forbidden_material(paths: list[Path]) -> int:
    findings: list[str] = []
    scanned = 0
    secret_patterns = [
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
        re.compile(
            r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[=:]\s*[\"'][^\"']{12,}[\"']",
            re.IGNORECASE,
        ),
    ]
    forbidden_literals = [
        "/Users" + "/joe/",
        "/home" + "/joe/",
        ".codex" + "/sessions",
    ]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if path.name in FORBIDDEN_NAMES:
            findings.append(f"{relative}: forbidden raw or non-release file")
        if path.stat().st_size > 25 * 1024 * 1024:
            findings.append(f"{relative}: file exceeds 25 MiB")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for literal in forbidden_literals:
            if literal in content:
                findings.append(f"{relative}: local runtime path")
        for pattern in secret_patterns:
            if pattern.search(content):
                findings.append(f"{relative}: credential-like token")
    if findings:
        raise AssertionError("public-release safety check failed: " + "; ".join(sorted(set(findings))))
    return scanned


def check_local_markdown_links(paths: list[Path]) -> int:
    checked = 0
    broken: list[str] = []
    pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    for path in paths:
        if path.suffix.lower() != ".md":
            continue
        content = path.read_text(encoding="utf-8")
        for raw_target in pattern.findall(content):
            target = raw_target.strip().split(" ", 1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative_target = unquote(target.split("#", 1)[0])
            if not relative_target:
                continue
            checked += 1
            if not (path.parent / relative_target).exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    if broken:
        raise AssertionError("broken local markdown links: " + "; ".join(broken))
    return checked


def check_artifact_manifest() -> None:
    subprocess.run(
        [sys.executable, "scripts/verify_artifact.py", "--check-manifest"],
        cwd=SNAPSHOT,
        check=True,
    )


def main() -> int:
    check_required()
    release_files = files()
    scanned = check_forbidden_material(release_files)
    links = check_local_markdown_links(release_files)
    check_artifact_manifest()
    print(
        json.dumps(
            {
                "status": "pass",
                "files_checked": len(release_files),
                "text_files_scanned": scanned,
                "local_links_checked": links,
                "artifact_manifest": "pass",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
