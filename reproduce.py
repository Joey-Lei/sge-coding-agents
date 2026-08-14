#!/usr/bin/env python3
"""Run the frozen, offline reviewer-artifact reproduction."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "artifact" / "reviewer_snapshot"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rewrite the platform-bound canonical artifact renderings and hashes",
    )
    args = parser.parse_args()
    command = [sys.executable, "reproduce.py"]
    if args.refresh:
        command.append("--refresh")
    subprocess.run(command, cwd=SNAPSHOT, check=True)
    print(
        json.dumps(
            {
                "status": "pass",
                "artifact": "artifact/reviewer_snapshot",
                "mode": "offline-refresh" if args.refresh else "offline-portable",
                "network_calls": 0,
                "model_calls": 0,
                "evaluator_calls": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
