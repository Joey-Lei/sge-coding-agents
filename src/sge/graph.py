#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import heapq
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .replay import node_duration


ROOT = Path(__file__).resolve().parents[1]


TYPE_WEIGHTS = {
    "shell": 0.8,
    "read": 1.0,
    "grep": 1.2,
    "fetch": 1.5,
    "lint": 2.5,
    "env_probe": 2.0,
    "diagnosis_branch": 2.5,
    "edit": 3.0,
    "patch_sketch": 4.0,
    "patch_candidate": 4.0,
    "targeted_test": 4.0,
    "test": 5.0,
    "build": 6.0,
}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def case_id_from_dag(path: Path) -> str:
    name = path.name
    for suffix in ("_dag.json", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def trace_id_from_dag(path: Path) -> str:
    return case_id_from_dag(path)


def case_label(case_id: str) -> str:
    marker = "_web_bench_"
    if marker in case_id:
        tail = case_id.split(marker, 1)[1]
        if "_task" in tail:
            return tail.split("_task", 1)[0]
    return case_id


def meta_for_dag(path: Path) -> Dict[str, Any]:
    meta_path = path.with_name(path.name.removesuffix("_dag.json") + "_meta.json")
    if not meta_path.exists():
        return {}
    return load_json(meta_path)


def collect_dag_paths(dag_dirs: Sequence[Path], dags: Sequence[Path]) -> List[Path]:
    paths: List[Path] = []
    for dag_dir in dag_dirs:
        paths.extend(sorted(dag_dir.glob("*_dag.json")))
    paths.extend(dags)
    unique = {str(path): path for path in paths}
    return sorted(unique.values(), key=lambda p: str(p))


def dependency_edges(dag: Dict[str, Any], include_temporal: bool = False) -> List[Dict[str, Any]]:
    out = []
    for edge in dag.get("edges", []):
        if edge.get("edge_type") == "temporal" and not include_temporal:
            continue
        out.append(edge)
    return out


def node_weight(node: Dict[str, Any], duration_model: str) -> float:
    if duration_model == "shape_unit":
        return 1.0
    if duration_model == "type_weighted":
        return TYPE_WEIGHTS.get(str(node.get("kind") or "unknown"), 1.0)
    if duration_model == "observed":
        return node_duration(node)
    raise ValueError(f"unknown duration model: {duration_model}")


def build_graph(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
    duration_model: str = "observed",
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, float], Dict[str, List[str]], Dict[str, List[str]]]:
    node_order = [str(node["node_id"]) for node in nodes]
    node_by_id = {str(node["node_id"]): node for node in nodes}
    durations = {node_id: node_weight(node_by_id[node_id], duration_model) for node_id in node_order}
    preds = {node_id: [] for node_id in node_order}
    succs = {node_id: [] for node_id in node_order}
    seen_edges: set[Tuple[str, str]] = set()
    for edge in edges:
        src = str(edge.get("src") or "")
        dst = str(edge.get("dst") or "")
        if src not in node_by_id or dst not in node_by_id or src == dst:
            continue
        key = (src, dst)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        preds[dst].append(src)
        succs[src].append(dst)
    return node_order, node_by_id, durations, preds, succs


def topological_order(
    node_order: Sequence[str],
    preds: Dict[str, List[str]],
    succs: Dict[str, List[str]],
) -> List[str]:
    order_index = {node_id: idx for idx, node_id in enumerate(node_order)}
    indegree = {node_id: len(preds[node_id]) for node_id in node_order}
    ready = [(order_index[node_id], node_id) for node_id in node_order if indegree[node_id] == 0]
    heapq.heapify(ready)
    out: List[str] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        out.append(node_id)
        for succ in succs[node_id]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                heapq.heappush(ready, (order_index[succ], succ))
    if len(out) != len(node_order):
        cyclic = [node_id for node_id in node_order if indegree[node_id] > 0]
        raise ValueError(f"dependency graph is cyclic or incomplete around nodes: {', '.join(cyclic[:20])}")
    return out


def critical_path(
    topo: Sequence[str],
    durations: Dict[str, float],
    preds: Dict[str, List[str]],
) -> Tuple[float, List[str], Dict[str, float], Dict[str, float]]:
    longest_finish: Dict[str, float] = {}
    earliest_start: Dict[str, float] = {}
    parent: Dict[str, str | None] = {}
    for node_id in topo:
        best_pred = None
        best_start = 0.0
        for pred in preds[node_id]:
            if longest_finish[pred] > best_start:
                best_start = longest_finish[pred]
                best_pred = pred
        earliest_start[node_id] = best_start
        longest_finish[node_id] = best_start + durations[node_id]
        parent[node_id] = best_pred
    if not topo:
        return 0.0, [], earliest_start, longest_finish
    end_node = max(topo, key=lambda node_id: longest_finish[node_id])
    path: List[str] = []
    cur: str | None = end_node
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return longest_finish[end_node], path, earliest_start, longest_finish


def bottom_levels(
    topo: Sequence[str],
    durations: Dict[str, float],
    succs: Dict[str, List[str]],
) -> Dict[str, float]:
    levels: Dict[str, float] = {}
    for node_id in reversed(topo):
        levels[node_id] = durations[node_id] + max((levels[succ] for succ in succs[node_id]), default=0.0)
    return levels


def relaxed_bound_speedup(serial_work: float, span: float, workers: int) -> float:
    if serial_work <= 0.0 or span <= 0.0 or workers <= 0:
        return 0.0
    lower_bound = max(span, serial_work / workers)
    return serial_work / lower_bound if lower_bound else 0.0


def list_schedule_makespan(
    node_order: Sequence[str],
    durations: Dict[str, float],
    preds: Dict[str, List[str]],
    succs: Dict[str, List[str]],
    priority: Dict[str, float],
    workers: int,
) -> Tuple[float, Dict[str, Tuple[float, float, int]]]:
    if workers <= 0:
        raise ValueError("workers must be positive")
    order_index = {node_id: idx for idx, node_id in enumerate(node_order)}
    remaining_preds = {node_id: len(preds[node_id]) for node_id in node_order}
    ready = [(-priority[node_id], order_index[node_id], node_id) for node_id in node_order if remaining_preds[node_id] == 0]
    heapq.heapify(ready)
    free_workers = list(range(workers))
    heapq.heapify(free_workers)
    running: List[Tuple[float, int, str]] = []
    schedule: Dict[str, Tuple[float, float, int]] = {}
    completed: set[str] = set()
    now = 0.0

    while len(completed) < len(node_order):
        while ready and free_workers:
            _, _, node_id = heapq.heappop(ready)
            worker = heapq.heappop(free_workers)
            start = now
            finish = start + durations[node_id]
            schedule[node_id] = (start, finish, worker)
            heapq.heappush(running, (finish, worker, node_id))
        if not running:
            missing = [node_id for node_id in node_order if node_id not in completed]
            raise ValueError(f"list scheduling stalled around nodes: {', '.join(missing[:20])}")
        now = running[0][0]
        finished_now: List[Tuple[float, int, str]] = []
        while running and running[0][0] <= now + 1e-12:
            finished_now.append(heapq.heappop(running))
        for _, worker, node_id in finished_now:
            completed.add(node_id)
            heapq.heappush(free_workers, worker)
            for succ in succs[node_id]:
                remaining_preds[succ] -= 1
                if remaining_preds[succ] == 0:
                    heapq.heappush(ready, (-priority[succ], order_index[succ], succ))
    return now, schedule


def peak_asap_parallelism(earliest_start: Dict[str, float], earliest_finish: Dict[str, float]) -> int:
    events: List[Tuple[float, int]] = []
    for node_id, start in earliest_start.items():
        finish = earliest_finish[node_id]
        events.append((start, 1))
        events.append((finish, -1))
    active = 0
    peak = 0
    # End events before start events at the same timestamp avoid boundary-only overlap.
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return peak


def edge_counts(edges: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for edge in edges:
        kind = str(edge.get("edge_type") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def node_kind_counts(nodes: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for node in nodes:
        kind = str(node.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def format_counts(counts: Dict[str, int]) -> str:
    return ",".join(f"{key}:{value}" for key, value in sorted(counts.items()))


def short_label(node: Dict[str, Any], limit: int = 60) -> str:
    label = str(node.get("label") or node.get("command") or node.get("node_id") or "")
    label = " ".join(label.split())
    return label if len(label) <= limit else label[: limit - 3] + "..."


def summarize_dag(
    path: Path,
    workers: Sequence[int],
    include_temporal: bool = False,
    duration_model: str = "observed",
) -> Dict[str, Any]:
    dag = load_json(path)
    meta = meta_for_dag(path)
    nodes = dag.get("nodes", [])
    edges = dag.get("edges", [])
    deps = dependency_edges(dag, include_temporal=include_temporal)
    node_order, node_by_id, durations, preds, succs = build_graph(nodes, deps, duration_model=duration_model)
    topo = topological_order(node_order, preds, succs)
    serial_work = sum(durations.values())
    span, cp_nodes, earliest_start, earliest_finish = critical_path(topo, durations, preds)
    blevels = bottom_levels(topo, durations, succs)
    observed_wall = float(meta.get("wall_time") or 0.0)
    case_id = case_id_from_dag(path)
    row: Dict[str, Any] = {
        "case_id": case_id,
        "case_label": case_label(case_id),
        "duration_model": duration_model,
        "trace_id": trace_id_from_dag(path),
        "dag_path": str(path),
        "model": meta.get("model", "unknown"),
        "sandbox": meta.get("sandbox", "unknown"),
        "return_code": meta.get("return_code", "unknown"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "dependency_edge_count": len(dependency_edges(dag, include_temporal=False)),
        "temporal_edge_count": edge_counts(edges).get("temporal", 0),
        "scheduled_edge_count": len(deps),
        "serial_work_units": round(serial_work, 4),
        "critical_path_units": round(span, 4),
        "critical_path_fraction": round(span / serial_work, 4) if serial_work else 0.0,
        "average_parallelism": round(serial_work / span, 4) if span else 0.0,
        "peak_asap_parallel_nodes": peak_asap_parallelism(earliest_start, earliest_finish),
        "critical_path_node_count": len(cp_nodes),
        "critical_path_nodes": "->".join(cp_nodes),
        "critical_path_kinds": "->".join(str(node_by_id[node_id].get("kind") or "unknown") for node_id in cp_nodes),
        "critical_path_labels": " -> ".join(short_label(node_by_id[node_id]) for node_id in cp_nodes),
        "node_kinds": format_counts(node_kind_counts(nodes)),
        "edge_kinds": format_counts(edge_counts(edges)),
        "observed_target_wall_seconds": round(observed_wall, 4),
        "scaled_unbounded_wall_seconds": round(observed_wall * span / serial_work, 4) if observed_wall and serial_work else 0.0,
    }
    for worker_count in workers:
        relaxed_speed = relaxed_bound_speedup(serial_work, span, worker_count)
        makespan, _ = list_schedule_makespan(node_order, durations, preds, succs, blevels, worker_count)
        speed = serial_work / makespan if makespan else 0.0
        row[f"workers_{worker_count}_relaxed_bound_speedup"] = round(relaxed_speed, 4)
        row[f"workers_{worker_count}_list_makespan_units"] = round(makespan, 4)
        row[f"workers_{worker_count}_list_speedup"] = round(speed, 4)
        row[f"workers_{worker_count}_list_efficiency"] = round(speed / worker_count, 4)
        row[f"workers_{worker_count}_scaled_list_wall_seconds"] = (
            round(observed_wall * makespan / serial_work, 4) if observed_wall and serial_work else 0.0
        )
    return row


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def aggregate(rows: Sequence[Dict[str, Any]], workers: Sequence[int]) -> Dict[str, Any]:
    total_serial = sum(float(row["serial_work_units"]) for row in rows)
    total_span = sum(float(row["critical_path_units"]) for row in rows)
    total_wall = sum(float(row["observed_target_wall_seconds"]) for row in rows)
    speeds = [float(row["average_parallelism"]) for row in rows]
    out: Dict[str, Any] = {
        "duration_model": rows[0].get("duration_model", "unknown") if rows else "unknown",
        "cases": len(rows),
        "nodes": sum(int(row["node_count"]) for row in rows),
        "dependency_edges": sum(int(row["dependency_edge_count"]) for row in rows),
        "serial_work_units": round(total_serial, 4),
        "critical_path_units_sum": round(total_span, 4),
        "critical_path_fraction": round(total_span / total_serial, 4) if total_serial else 0.0,
        "unbounded_speedup": round(total_serial / total_span, 4) if total_span else 0.0,
        "observed_target_wall_seconds": round(total_wall, 4),
        "scaled_unbounded_wall_seconds": round(sum(float(row["scaled_unbounded_wall_seconds"]) for row in rows), 4),
        "case_speedup_mean": round(sum(speeds) / len(speeds), 4) if speeds else 0.0,
        "case_speedup_min": round(min(speeds), 4) if speeds else 0.0,
        "case_speedup_p25": round(percentile(speeds, 0.25), 4),
        "case_speedup_median": round(percentile(speeds, 0.50), 4),
        "case_speedup_p75": round(percentile(speeds, 0.75), 4),
        "case_speedup_max": round(max(speeds), 4) if speeds else 0.0,
    }
    for worker_count in workers:
        bound_makespan = sum(
            max(float(row["critical_path_units"]), float(row["serial_work_units"]) / worker_count)
            for row in rows
        )
        list_makespan = sum(float(row[f"workers_{worker_count}_list_makespan_units"]) for row in rows)
        scaled_list_wall = sum(float(row[f"workers_{worker_count}_scaled_list_wall_seconds"]) for row in rows)
        out[f"workers_{worker_count}_per_case_relaxed_bound_speedup"] = (
            round(total_serial / bound_makespan, 4) if bound_makespan else 0.0
        )
        out[f"workers_{worker_count}_list_speedup"] = round(total_serial / list_makespan, 4) if list_makespan else 0.0
        out[f"workers_{worker_count}_list_makespan_units"] = round(list_makespan, 4)
        out[f"workers_{worker_count}_scaled_list_wall_seconds"] = round(scaled_list_wall, 4)
        out[f"workers_{worker_count}_wall_speedup_estimate"] = round(total_wall / scaled_list_wall, 4) if scaled_list_wall else 0.0
    return out


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_markdown(path: Path, rows: Sequence[Dict[str, Any]], stats: Dict[str, Any], workers: Sequence[int], dataset_label: str) -> None:
    lines = [
        "# DAG Speedup Estimator",
        "",
        f"Dataset: `{dataset_label}`.",
        f"Duration model: `{stats.get('duration_model', 'unknown')}`.",
        "",
        "This report uses existing target-model trace DAGs. It does not call a model.",
        "",
        "Algorithm: work-span / critical-path analysis plus bottom-level-priority list scheduling on finite identical workers.",
        "",
        "## Aggregate",
        "",
        f"- cases: `{stats['cases']}`",
        f"- nodes: `{stats['nodes']}`",
        f"- dependency edges: `{stats['dependency_edges']}`",
        f"- serial work T1: `{stats['serial_work_units']:.4f}` normalized units",
        f"- summed span Tinf: `{stats['critical_path_units_sum']:.4f}` normalized units",
        f"- critical-path fraction: `{stats['critical_path_fraction']:.4f}`",
        f"- unbounded work-span speedup T1/Tinf: `{stats['unbounded_speedup']:.4f}x`",
        f"- observed target wall time: `{stats['observed_target_wall_seconds']:.4f}s`",
        f"- scaled unbounded wall estimate: `{stats['scaled_unbounded_wall_seconds']:.4f}s`",
        "",
        "## Worker Estimates",
        "",
        "| Workers | Relaxed bound | List-schedule speedup | List makespan | Scaled wall estimate | Wall speedup estimate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for worker_count in workers:
        lines.append(
            "| {workers} | {bound:.4f}x | {speed:.4f}x | {makespan:.4f} | {wall:.4f}s | {wall_speed:.4f}x |".format(
                workers=worker_count,
                bound=stats[f"workers_{worker_count}_per_case_relaxed_bound_speedup"],
                speed=stats[f"workers_{worker_count}_list_speedup"],
                makespan=stats[f"workers_{worker_count}_list_makespan_units"],
                wall=stats[f"workers_{worker_count}_scaled_list_wall_seconds"],
                wall_speed=stats[f"workers_{worker_count}_wall_speedup_estimate"],
            )
        )
    lines.extend(
        [
            "",
            "## Case Distribution",
            "",
            f"- mean unbounded speedup: `{stats['case_speedup_mean']:.4f}x`",
            f"- min: `{stats['case_speedup_min']:.4f}x`",
            f"- p25: `{stats['case_speedup_p25']:.4f}x`",
            f"- median: `{stats['case_speedup_median']:.4f}x`",
            f"- p75: `{stats['case_speedup_p75']:.4f}x`",
            f"- max: `{stats['case_speedup_max']:.4f}x`",
            "",
            "## Cases",
            "",
        ]
    )
    header_cells = ["Case", "Nodes", "Dep Edges", "T1", "Tinf", "CP Frac", "Sinf", "Peak Parallel", "CP Nodes"]
    sep_cells = ["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---"]
    for worker_count in workers:
        header_cells.append(f"W{worker_count} list")
        sep_cells.append("---:")
    lines.extend(["| " + " | ".join(header_cells) + " |", "| " + " | ".join(sep_cells) + " |"])
    for row in rows:
        case_cells = [
            str(row["case_label"]),
            str(row["node_count"]),
            str(row["dependency_edge_count"]),
            f"{row['serial_work_units']:.4f}",
            f"{row['critical_path_units']:.4f}",
            f"{row['critical_path_fraction']:.4f}",
            f"{row['average_parallelism']:.4f}x",
            str(row["peak_asap_parallel_nodes"]),
            f"`{row['critical_path_nodes']}`",
        ]
        for worker_count in workers:
            case_cells.append(f"{row[f'workers_{worker_count}_list_speedup']:.4f}x")
        lines.append("| " + " | ".join(case_cells) + " |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `T1` is total normalized node work. `Tinf` is the longest dependency chain over non-temporal edges.",
            "- `Sinf = T1 / Tinf` is the unbounded-worker work-span upper bound.",
            "- Finite-worker relaxed bound uses `T1 / max(Tinf, T1 / workers)` per case.",
            "- List scheduling uses bottom-level priority, i.e. nodes with larger remaining critical-path work run first.",
            "- These are scheduling estimates over extracted DAGs, not online measured acceleration.",
            "- Dependency edges are automatically extracted; missed edges overestimate speedup and extra edges underestimate it.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def parse_workers(value: str) -> List[int]:
    workers = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        workers.append(int(item))
    if not workers:
        raise argparse.ArgumentTypeError("at least one worker count is required")
    if any(worker <= 0 for worker in workers):
        raise argparse.ArgumentTypeError("worker counts must be positive")
    return sorted(dict.fromkeys(workers))


def parse_duration_model(value: str) -> str:
    allowed = {"observed", "type_weighted", "shape_unit"}
    if value not in allowed:
        raise argparse.ArgumentTypeError(f"duration model must be one of: {', '.join(sorted(allowed))}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--dag-dir", type=Path, action="append")
    inputs.add_argument("--dag", type=Path, action="append")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dataset-label", default="")
    parser.add_argument("--workers", type=parse_workers, default=parse_workers("2,4,8"))
    parser.add_argument("--duration-model", type=parse_duration_model, default="observed")
    parser.add_argument("--include-temporal", action="store_true")
    args = parser.parse_args()

    dag_dirs = args.dag_dir or []
    dag_paths = collect_dag_paths(dag_dirs, args.dag or [])
    if not dag_paths:
        raise SystemExit(f"No DAG files found in {', '.join(str(path) for path in dag_dirs)}")

    rows = [
        summarize_dag(path, args.workers, include_temporal=args.include_temporal, duration_model=args.duration_model)
        for path in dag_paths
    ]
    stats = aggregate(rows, args.workers)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "dag_speedup_estimates.csv", rows)
    write_csv(args.out_dir / "dag_speedup_aggregate.csv", [stats])
    write_json(
        args.out_dir / "critical_paths.json",
        [
            {
                "case_id": row["case_id"],
                "critical_path_nodes": row["critical_path_nodes"].split("->") if row["critical_path_nodes"] else [],
                "critical_path_kinds": row["critical_path_kinds"].split("->") if row["critical_path_kinds"] else [],
                "critical_path_labels": row["critical_path_labels"].split(" -> ") if row["critical_path_labels"] else [],
            }
            for row in rows
        ],
    )
    dataset_label = args.dataset_label or ",".join(str(path) for path in dag_dirs)
    write_markdown(args.out_dir / "dag_speedup_estimator.md", rows, stats, args.workers, dataset_label)
    print(f"wrote={args.out_dir / 'dag_speedup_estimator.md'}")


if __name__ == "__main__":
    main()
