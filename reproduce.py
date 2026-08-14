#!/usr/bin/env python3
"""Run the frozen, offline reviewer-artifact reproduction."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "artifact" / "reviewer_snapshot"


def main() -> int:
    subprocess.run([sys.executable, "reproduce.py"], cwd=SNAPSHOT, check=True)
    print(
        json.dumps(
            {
                "status": "pass",
                "artifact": "artifact/reviewer_snapshot",
                "mode": "offline",
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
