"""Public API for Speculative Graph Execution analysis utilities."""

from .graph import (
    bottom_levels,
    build_graph,
    critical_path,
    dependency_edges,
    list_schedule_makespan,
    relaxed_bound_speedup,
    summarize_dag,
    topological_order,
)
from .replay import critical_path_time, replay_policy
from .trace import DagEdge, DagNode, TraceDag, build_dag

__all__ = [
    "DagEdge",
    "DagNode",
    "TraceDag",
    "bottom_levels",
    "build_dag",
    "build_graph",
    "critical_path",
    "critical_path_time",
    "dependency_edges",
    "list_schedule_makespan",
    "relaxed_bound_speedup",
    "replay_policy",
    "summarize_dag",
    "topological_order",
]

__version__ = "0.1.0"
