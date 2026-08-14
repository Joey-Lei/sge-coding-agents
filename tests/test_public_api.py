from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import sge
from sge.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_example_exposes_parallel_headroom() -> None:
    row = sge.summarize_dag(ROOT / "examples" / "minimal_workgraph.json", workers=[1, 2, 4])
    assert row["node_count"] == 5
    assert math.isclose(row["serial_work_units"], 15.5)
    assert math.isclose(row["critical_path_units"], 12.0)
    assert row["workers_1_list_speedup"] == 1.0
    assert row["workers_2_list_speedup"] > 1.0
    assert row["workers_4_list_speedup"] <= row["average_parallelism"]


def test_cli_emits_boundary_and_machine_readable_output(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    assert main(
        [
            "analyze",
            str(ROOT / "examples" / "minimal_workgraph.json"),
            "--workers",
            "1,2,4",
            "--output",
            str(output),
        ]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "not measured end-to-end acceleration" in payload["claim_boundary"]
    assert payload["analysis"]["workers_4_list_speedup"] > 1.0


def test_cycle_is_rejected() -> None:
    nodes = [
        {"node_id": "a", "kind": "read", "duration": 1.0},
        {"node_id": "b", "kind": "test", "duration": 1.0},
    ]
    edges = [
        {"src": "a", "dst": "b", "edge_type": "dependency"},
        {"src": "b", "dst": "a", "edge_type": "dependency"},
    ]
    order, _, _, preds, succs = sge.build_graph(nodes, edges)
    with pytest.raises(ValueError, match="cyclic"):
        sge.topological_order(order, preds, succs)
