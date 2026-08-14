#!/usr/bin/env python3
"""Remove machine-local and account-identifying strings from reviewer files.

The allowlist deliberately excludes raw traces and logs.  This pass handles the
remaining path-valued provenance fields without changing scientific numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".py", ".txt", ".toml", ".yaml", ".yml"}
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def replacements() -> list[tuple[str, re.Pattern[str], str]]:
    local_home = re.compile(r"/(?:Users|home)/[^/\s\"'<>]+")
    runtime_evidence = re.compile(
        r"<LOCAL_HOME>/\.codex/(?:sessions/[^\s\"'<>]+|history\.jsonl)"
    )
    private_tmp = re.compile("/private" + r"/tmp/[^\s\"'<>]+")
    internal_agent = re.compile(r"/root/[A-Za-z0-9_.\-/]+")
    email = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
    account = re.compile("decentralized" + "black-maker", re.IGNORECASE)
    return [
        ("local_home", local_home, "<LOCAL_HOME>"),
        ("runtime_session_evidence", runtime_evidence, "<REDACTED_RUNTIME_EVIDENCE>"),
        ("private_tmp", private_tmp, "<TEMP_ROOT>"),
        ("internal_agent", internal_agent, "<INTERNAL_VERIFIER>"),
        ("account_name", account, "<REDACTED_ACCOUNT>"),
        ("email", email, "<REDACTED_EMAIL>"),
    ]


def candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        if relative.parts and relative.parts[0] in {"scripts", "tests", "outputs"}:
            continue
        if path == ROOT / "audit" / "sanitization_report.json":
            continue
        files.append(path)
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write sanitized text and the audit report")
    args = parser.parse_args()

    changes: list[dict[str, object]] = []
    totals: dict[str, int] = {name: 0 for name, _, _ in replacements()}
    for path in candidate_files():
        before = path.read_bytes()
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError:
            continue
        file_counts: dict[str, int] = {}
        revised = text
        for name, pattern, replacement in replacements():
            revised, count = pattern.subn(replacement, revised)
            if count:
                file_counts[name] = count
                totals[name] += count
        if revised == text:
            continue
        after = revised.encode("utf-8")
        changes.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "before_sha256": sha256_bytes(before),
                "after_sha256": sha256_bytes(after),
                "replacements": file_counts,
            }
        )
        if args.apply:
            path.write_bytes(after)

    output = ROOT / "audit" / "sanitization_report.json"
    prior_changes: list[dict[str, object]] = []
    prior_totals: dict[str, int] = {name: 0 for name, _, _ in replacements()}
    if args.apply and output.is_file():
        prior = json.loads(output.read_text(encoding="utf-8"))
        prior_changes = list(prior.get("changed_files", []))
        for name, count in prior.get("replacement_totals", {}).items():
            if name in prior_totals:
                prior_totals[name] = int(count)
    known = {
        (str(row.get("path")), str(row.get("before_sha256")), str(row.get("after_sha256")))
        for row in prior_changes
    }
    merged_changes = prior_changes + [
        row
        for row in changes
        if (str(row.get("path")), str(row.get("before_sha256")), str(row.get("after_sha256"))) not in known
    ]
    merged_totals = {name: prior_totals.get(name, 0) + totals.get(name, 0) for name in prior_totals}
    report = {
        "schema_version": 1,
        "status": "applied" if args.apply else "dry-run",
        "policy": "machine-local paths, runtime-session locators, internal agent names, account names, and emails only; scientific numeric values are unchanged",
        "changed_file_count": len(merged_changes) if args.apply else len(changes),
        "replacement_totals": merged_totals if args.apply else totals,
        "changed_files": merged_changes if args.apply else changes,
    }
    if args.apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
