#!/usr/bin/env python3
"""Run the complete offline SGE reviewer-artifact reproduction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(args: list[str], env: dict[str, str]) -> None:
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> None:
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
    print(json.dumps({"status": "pass", "mode": "offline", "network_calls": 0, "model_calls": 0, "evaluator_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
