#!/usr/bin/env python3
"""Run the complete offline SGE reviewer-artifact reproduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIGURE_IDS = {
    "F-task-layer-map",
    "F-workgraph-case",
    "F-rolling-atlas",
    "F-admission",
    "F-evidence-boundary",
}


def run(args: list[str], env: dict[str, str]) -> None:
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_identical(observed: Path, expected: Path) -> None:
    if observed.read_bytes() != expected.read_bytes():
        raise AssertionError(f"portable recomputation differs from sealed output: {expected.relative_to(ROOT)}")


def validate_temporary_figures(manifest_path: Path, output_dir: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise AssertionError("temporary figure manifest has an unexpected schema version")
    for key, suffix in (("outputs", ".pdf"), ("review_outputs", ".png")):
        rows = manifest.get(key, [])
        if len(rows) != len(FIGURE_IDS) or {row.get("id") for row in rows} != FIGURE_IDS:
            raise AssertionError(f"temporary figure manifest has an unexpected {key} set")
        for row in rows:
            path = output_dir / Path(str(row.get("path", ""))).name
            if path.suffix != suffix or not path.is_file():
                raise AssertionError(f"temporary figure output is missing or malformed: {path}")
            if sha256_file(path) != row.get("sha256"):
                raise AssertionError(f"temporary figure hash mismatch: {path}")


def portable_reproduction(runtime_root: Path, env: dict[str, str]) -> None:
    """Recompute into scratch space, then validate the untouched sealed bundle."""
    claims_dir = runtime_root / "claims"
    figures_dir = runtime_root / "figures"
    claims_dir.mkdir()
    figures_dir.mkdir()
    claims_json = claims_dir / "recomputed_claims.json"
    claims_markdown = claims_dir / "recomputed_claims.md"
    figure_manifest = runtime_root / "figure_manifest.json"

    run(
        [
            sys.executable,
            "scripts/recompute_claims.py",
            "--output",
            str(claims_json),
            "--markdown-output",
            str(claims_markdown),
        ],
        env,
    )
    require_identical(claims_json, ROOT / "outputs" / "recomputed_claims.json")
    require_identical(claims_markdown, ROOT / "outputs" / "recomputed_claims.md")

    run(
        [
            sys.executable,
            "scripts/build_submission_visuals.py",
            "--workspace-root",
            str(ROOT),
            "--p30-source-root",
            str(ROOT),
            "--output-dir",
            str(figures_dir),
            "--manifest-output",
            str(figure_manifest),
        ],
        env,
    )
    validate_temporary_figures(figure_manifest, figures_dir)
    run([sys.executable, "scripts/verify_artifact.py", "--check-manifest"], env)


def refresh_reproduction(env: dict[str, str]) -> None:
    """Regenerate the platform-bound canonical renderings and package hashes."""
    run([sys.executable, "scripts/recompute_claims.py"], env)
    run(
        [
            sys.executable,
            "scripts/build_submission_visuals.py",
            "--workspace-root",
            str(ROOT),
            "--p30-source-root",
            str(ROOT),
            "--output-dir",
            str(ROOT / "outputs" / "figures"),
            "--manifest-output",
            str(ROOT / "outputs" / "figures" / "figure_manifest.json"),
        ],
        env,
    )
    run([sys.executable, "scripts/build_accessibility_previews.py"], env)
    run([sys.executable, "scripts/verify_artifact.py", "--write-manifest"], env)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rewrite canonical figures, accessibility previews, and package hashes",
    )
    args = parser.parse_args()

    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = "0"
    with tempfile.TemporaryDirectory(prefix="sge-reviewer-runtime-") as runtime_dir:
        runtime_root = Path(runtime_dir)
        mpl_dir = runtime_root / "matplotlib"
        cache_dir = runtime_root / "cache"
        mpl_dir.mkdir()
        cache_dir.mkdir()
        # Matplotlib and its fontconfig dependency both need a writable cache.
        # Keep HOME unchanged so user- or environment-installed Python packages
        # remain visible inside reviewer sandboxes.
        env["MPLCONFIGDIR"] = str(mpl_dir)
        env["XDG_CACHE_HOME"] = str(cache_dir)
        env["MPLBACKEND"] = "Agg"
        if args.refresh:
            refresh_reproduction(env)
        else:
            portable_reproduction(runtime_root, env)

    print(
        json.dumps(
            {
                "status": "pass",
                "mode": "offline-refresh" if args.refresh else "offline-portable",
                "network_calls": 0,
                "model_calls": 0,
                "evaluator_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
