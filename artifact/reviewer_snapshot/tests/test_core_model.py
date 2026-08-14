from __future__ import annotations

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dag_speedup_estimator as estimator  # noqa: E402
import replay_trace_speculation as replay  # noqa: E402


def test_work_span_and_two_worker_schedule() -> None:
    nodes = [
        {"node_id": "a", "kind": "read", "duration": 2.0},
        {"node_id": "b", "kind": "read", "duration": 3.0},
        {"node_id": "c", "kind": "test", "duration": 1.0},
    ]
    edges = [
        {"src": "a", "dst": "c", "edge_type": "dependency"},
        {"src": "b", "dst": "c", "edge_type": "dependency"},
    ]
    order, _, durations, preds, succs = estimator.build_graph(nodes, edges)
    topo = estimator.topological_order(order, preds, succs)
    span, path, _, _ = estimator.critical_path(topo, durations, preds)
    priority = estimator.bottom_levels(topo, durations, succs)
    makespan, schedule = estimator.list_schedule_makespan(order, durations, preds, succs, priority, workers=2)

    assert math.isclose(sum(durations.values()), 6.0)
    assert math.isclose(span, 4.0)
    assert path == ["b", "c"]
    assert math.isclose(estimator.relaxed_bound_speedup(6.0, span, 2), 1.5)
    assert math.isclose(makespan, 4.0)
    assert set(schedule) == {"a", "b", "c"}


def test_temporal_edges_are_excluded_by_default() -> None:
    dag = {
        "nodes": [
            {"node_id": "a", "kind": "read", "duration": 1.0},
            {"node_id": "b", "kind": "read", "duration": 1.0},
        ],
        "edges": [{"src": "a", "dst": "b", "edge_type": "temporal"}],
    }
    assert estimator.dependency_edges(dag) == []
    assert estimator.dependency_edges(dag, include_temporal=True) == dag["edges"]
    assert math.isclose(replay.critical_path_time(dag["nodes"], dag["edges"]), 1.0)
