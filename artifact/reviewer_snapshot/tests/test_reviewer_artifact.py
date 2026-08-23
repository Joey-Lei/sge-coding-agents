from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_recompute_claims_from_packaged_rows(tmp_path: Path) -> None:
    output = tmp_path / "claims.json"
    markdown = tmp_path / "claims.md"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "recompute_claims.py"),
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=ROOT,
        check=True,
    )
    claims = json.loads(output.read_text(encoding="utf-8"))["claims"]
    historical = claims["historical_same_trace_replay"]
    assert historical["case_count"] == 10
    assert historical["aggregate_unbounded_speedup"] == pytest.approx(4.268974222446017)
    assert historical["aggregate_workers_4_list_speedup"] == pytest.approx(3.405822357036705)
    assert claims["exact_duration_structural_ceiling"]["exact_duration_action_dag_count"] == 9
    assert claims["duration_blind_admission"]["window_count"] == 188
    assert claims["duration_blind_admission"]["nontrivial_window_count"] == 58
    assert claims["local_executor_smoke"]["local_closures"] == 8


def test_invalid_canaries_remain_invalid_and_null() -> None:
    for case in ("P007", "P018"):
        path = ROOT / "results" / "sge_p30_paired_scale_audit_20260728" / case / "evidence_integration.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        assert evidence["terminal_status"] == "invalid"
        assert evidence["pair_validity"] == "invalid"
        assert all(value is None for value in evidence["paired_metrics"].values())


def test_submission_figures_render_from_packaged_sources(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = "0"
    env["MPLCONFIGDIR"] = str(tmp_path / "mpl")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    output_dir = tmp_path / "figures"
    manifest = output_dir / "manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_submission_visuals.py"),
            "--workspace-root",
            str(ROOT),
            "--p30-source-root",
            str(ROOT),
            "--output-dir",
            str(output_dir),
            "--manifest-output",
            str(manifest),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(payload["outputs"]) == 5
    assert all((output_dir / Path(row["path"]).name).is_file() for row in payload["outputs"])


def test_artifact_safety_and_manifest() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_artifact.py"), "--check-manifest"],
        cwd=ROOT,
        check=True,
    )
