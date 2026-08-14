#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from dag_speedup_estimator import (
    TYPE_WEIGHTS,
    bottom_levels,
    build_graph,
    case_id_from_dag,
    dependency_edges,
    list_schedule_makespan,
    node_weight,
    short_label,
    topological_order,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "local_rolling_dag_ablation"
DURATION_MODELS = ("observed", "type_weighted", "shape_unit")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


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


def is_clean_return(meta: Dict[str, Any]) -> bool:
    value = meta.get("return_code")
    return str(value) == "0"


def parse_csv_ints(value: str) -> List[int]:
    out: List[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        parsed = int(item)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("values must be positive integers")
        out.append(parsed)
    if not out:
        raise argparse.ArgumentTypeError("at least one value is required")
    return sorted(dict.fromkeys(out))


def pct_error(estimate: float, reference: float) -> float:
    if reference <= 0.0:
        return 0.0
    return 100.0 * (estimate - reference) / reference


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


def dependency_levels(topo: Sequence[str], preds: Dict[str, List[str]]) -> Dict[str, int]:
    levels: Dict[str, int] = {}
    for node_id in topo:
        levels[node_id] = 0 if not preds[node_id] else 1 + max(levels[pred] for pred in preds[node_id])
    return levels


def schedule_whole(
    node_order: Sequence[str],
    durations: Dict[str, float],
    preds: Dict[str, List[str]],
    succs: Dict[str, List[str]],
    workers: int,
) -> float:
    priority = bottom_levels(node_order, durations, succs)
    makespan, _ = list_schedule_makespan(node_order, durations, preds, succs, priority, workers)
    return makespan


def subgraph_edges(node_ids: set[str], succs: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for src in node_ids:
        for dst in succs[src]:
            if dst in node_ids:
                out.append((src, dst))
    return out


def local_region_makespan(
    region_nodes: Sequence[str],
    durations: Dict[str, float],
    preds: Dict[str, List[str]],
    succs: Dict[str, List[str]],
    workers: int,
) -> float:
    region_set = set(region_nodes)
    region_preds = {node_id: [pred for pred in preds[node_id] if pred in region_set] for node_id in region_nodes}
    region_succs = {node_id: [succ for succ in succs[node_id] if succ in region_set] for node_id in region_nodes}
    priority = bottom_levels(region_nodes, durations, region_succs)
    makespan, _ = list_schedule_makespan(region_nodes, durations, region_preds, region_succs, priority, workers)
    return makespan


def rolling_schedule(
    node_order: Sequence[str],
    durations: Dict[str, float],
    preds: Dict[str, List[str]],
    succs: Dict[str, List[str]],
    levels: Dict[str, int],
    k: int,
    workers: int,
) -> Tuple[float, List[Dict[str, Any]]]:
    if not node_order:
        return 0.0, []
    max_level = max(levels.values())
    total = 0.0
    regions: List[Dict[str, Any]] = []
    for start_level in range(0, max_level + 1, k):
        end_level = start_level + k
        region_nodes = [node_id for node_id in node_order if start_level <= levels[node_id] < end_level]
        if not region_nodes:
            continue
        node_set = set(region_nodes)
        edges = subgraph_edges(node_set, succs)
        work = sum(durations[node_id] for node_id in region_nodes)
        makespan = local_region_makespan(region_nodes, durations, preds, succs, workers)
        total += makespan
        regions.append(
            {
                "start_level": start_level,
                "end_level_exclusive": end_level,
                "node_count": len(region_nodes),
                "edge_count": len(edges),
                "work_units": work,
                "makespan_units": makespan,
                "speedup": work / makespan if makespan else 0.0,
            }
        )
    return total, regions


def model_metrics(dag: Dict[str, Any], duration_model: str, workers: int, k_values: Sequence[int]) -> Dict[str, Any]:
    nodes = dag.get("nodes", [])
    deps = dependency_edges(dag, include_temporal=False)
    node_order, node_by_id, durations, preds, succs = build_graph(nodes, deps, duration_model=duration_model)
    topo = topological_order(node_order, preds, succs)
    serial_work = sum(durations.values())
    global_makespan = schedule_whole(topo, durations, preds, succs, workers)
    levels = dependency_levels(topo, preds)
    level_widths: Dict[int, int] = {}
    for node_id, level in levels.items():
        level_widths[level] = level_widths.get(level, 0) + 1

    local: Dict[int, Dict[str, Any]] = {}
    for k in k_values:
        local_makespan, regions = rolling_schedule(topo, durations, preds, succs, levels, k, workers)
        local[k] = {
            "makespan_units": local_makespan,
            "speedup": serial_work / local_makespan if local_makespan else 0.0,
            "region_count": len(regions),
            "regions": regions,
            "avg_region_nodes": mean([r["node_count"] for r in regions]) if regions else 0.0,
            "max_region_nodes": max([r["node_count"] for r in regions], default=0),
            "avg_region_edges": mean([r["edge_count"] for r in regions]) if regions else 0.0,
            "max_region_edges": max([r["edge_count"] for r in regions], default=0),
        }

    return {
        "duration_model": duration_model,
        "serial_work_units": serial_work,
        "global_makespan_units": global_makespan,
        "global_speedup": serial_work / global_makespan if global_makespan else 0.0,
        "max_dependency_level": max(levels.values()) if levels else 0,
        "level_count": len(set(levels.values())),
        "peak_level_width": max(level_widths.values(), default=0),
        "avg_level_width": mean(level_widths.values()) if level_widths else 0.0,
        "critical_path_preview": " -> ".join(short_label(node_by_id[node_id], 30) for node_id in topo[:5]),
        "local": local,
    }


def summarize_case(path: Path, workers: int, k_values: Sequence[int]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    dag = load_json(path)
    meta = meta_for_dag(path)
    nodes = dag.get("nodes", [])
    deps = dependency_edges(dag, include_temporal=False)
    observed = model_metrics(dag, "observed", workers, k_values)
    type_weighted = model_metrics(dag, "type_weighted", workers, k_values)
    shape = model_metrics(dag, "shape_unit", workers, k_values)

    base: Dict[str, Any] = {
        "case_id": case_id_from_dag(path),
        "dag_path": str(path),
        "model": meta.get("model", "unknown"),
        "return_code": meta.get("return_code", "unknown"),
        "sandbox": meta.get("sandbox", "unknown"),
        "observed_target_wall_seconds": round(float(meta.get("wall_time") or 0.0), 4),
        "node_count": len(nodes),
        "dependency_edge_count": len(deps),
        "max_dependency_level": observed["max_dependency_level"],
        "level_count": observed["level_count"],
        "peak_level_width": observed["peak_level_width"],
        "avg_level_width": round(observed["avg_level_width"], 4),
        "observed_global_w4_speedup": round(observed["global_speedup"], 4),
        "type_global_w4_speedup": round(type_weighted["global_speedup"], 4),
        "shape_global_w4_speedup": round(shape["global_speedup"], 4),
        "type_global_error_pct": round(pct_error(type_weighted["global_speedup"], observed["global_speedup"]), 4),
        "shape_global_error_pct": round(pct_error(shape["global_speedup"], observed["global_speedup"]), 4),
    }

    window_rows: List[Dict[str, Any]] = []
    formula_rows: List[Dict[str, Any]] = []
    for k in k_values:
        obs_local = observed["local"][k]
        type_local = type_weighted["local"][k]
        shape_local = shape["local"][k]
        retention = obs_local["speedup"] / observed["global_speedup"] if observed["global_speedup"] else 0.0
        compression_avg = obs_local["avg_region_nodes"] / len(nodes) if nodes else 0.0
        compression_max = obs_local["max_region_nodes"] / len(nodes) if nodes else 0.0
        row = {
            **base,
            "k": k,
            "region_count": obs_local["region_count"],
            "avg_region_nodes": round(obs_local["avg_region_nodes"], 4),
            "max_region_nodes": obs_local["max_region_nodes"],
            "avg_region_edges": round(obs_local["avg_region_edges"], 4),
            "max_region_edges": obs_local["max_region_edges"],
            "avg_region_node_fraction": round(compression_avg, 4),
            "max_region_node_fraction": round(compression_max, 4),
            "observed_local_w4_speedup": round(obs_local["speedup"], 4),
            "local_retention_vs_global": round(retention, 4),
            "type_local_w4_speedup": round(type_local["speedup"], 4),
            "shape_local_w4_speedup": round(shape_local["speedup"], 4),
            "type_local_error_pct": round(pct_error(type_local["speedup"], obs_local["speedup"]), 4),
            "shape_local_error_pct": round(pct_error(shape_local["speedup"], obs_local["speedup"]), 4),
            "local_extra_makespan_vs_global_pct": round(
                pct_error(obs_local["makespan_units"], observed["global_makespan_units"]), 4
            ),
        }
        window_rows.append(row)
        formula_rows.append(
            {
                "case_id": base["case_id"],
                "k": k,
                "reference_observed_local_w4_speedup": row["observed_local_w4_speedup"],
                "type_estimated_local_w4_speedup": row["type_local_w4_speedup"],
                "type_signed_error_pct": row["type_local_error_pct"],
                "type_abs_error_pct": round(abs(row["type_local_error_pct"]), 4),
                "shape_estimated_local_w4_speedup": row["shape_local_w4_speedup"],
                "shape_signed_error_pct": row["shape_local_error_pct"],
                "shape_abs_error_pct": round(abs(row["shape_local_error_pct"]), 4),
            }
        )
    return base, window_rows, formula_rows


def aggregate_by_k(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_k: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        by_k.setdefault(int(row["k"]), []).append(row)
    out: List[Dict[str, Any]] = []
    for k, group in sorted(by_k.items()):
        type_errors = [float(row["type_local_error_pct"]) for row in group]
        type_abs = [abs(value) for value in type_errors]
        shape_errors = [float(row["shape_local_error_pct"]) for row in group]
        shape_abs = [abs(value) for value in shape_errors]
        out.append(
            {
                "k": k,
                "cases": len(group),
                "observed_global_w4_speedup_mean": round(mean(float(row["observed_global_w4_speedup"]) for row in group), 4),
                "observed_local_w4_speedup_mean": round(mean(float(row["observed_local_w4_speedup"]) for row in group), 4),
                "local_retention_vs_global_mean": round(mean(float(row["local_retention_vs_global"]) for row in group), 4),
                "region_count_mean": round(mean(float(row["region_count"]) for row in group), 4),
                "avg_region_nodes_mean": round(mean(float(row["avg_region_nodes"]) for row in group), 4),
                "max_region_nodes_mean": round(mean(float(row["max_region_nodes"]) for row in group), 4),
                "avg_region_node_fraction_mean": round(mean(float(row["avg_region_node_fraction"]) for row in group), 4),
                "max_region_node_fraction_mean": round(mean(float(row["max_region_node_fraction"]) for row in group), 4),
                "type_local_error_pct_mean": round(mean(type_errors), 4),
                "type_local_abs_error_pct_mean": round(mean(type_abs), 4),
                "type_local_abs_error_pct_p50": round(percentile(type_abs, 0.50), 4),
                "type_local_abs_error_pct_p90": round(percentile(type_abs, 0.90), 4),
                "shape_local_error_pct_mean": round(mean(shape_errors), 4),
                "shape_local_abs_error_pct_mean": round(mean(shape_abs), 4),
                "shape_local_abs_error_pct_p50": round(percentile(shape_abs, 0.50), 4),
                "shape_local_abs_error_pct_p90": round(percentile(shape_abs, 0.90), 4),
                "peak_level_width_mean": round(mean(float(row["peak_level_width"]) for row in group), 4),
                "level_count_mean": round(mean(float(row["level_count"]) for row in group), 4),
            }
        )
    return out


def mechanism_rows(case_rows: Sequence[Dict[str, Any]], window_rows: Sequence[Dict[str, Any]], k_values: Sequence[int]) -> List[Dict[str, Any]]:
    by_case_k = {(row["case_id"], int(row["k"])): row for row in window_rows}
    out: List[Dict[str, Any]] = []
    for case in case_rows:
        row: Dict[str, Any] = {
            "case_id": case["case_id"],
            "return_code": case["return_code"],
            "node_count": case["node_count"],
            "dependency_edge_count": case["dependency_edge_count"],
            "level_count": case["level_count"],
            "peak_level_width": case["peak_level_width"],
            "avg_level_width": case["avg_level_width"],
            "observed_global_w4_speedup": case["observed_global_w4_speedup"],
        }
        for k in k_values:
            item = by_case_k[(case["case_id"], k)]
            row[f"k{k}_local_speedup"] = item["observed_local_w4_speedup"]
            row[f"k{k}_retention"] = item["local_retention_vs_global"]
            row[f"k{k}_avg_region_nodes"] = item["avg_region_nodes"]
            row[f"k{k}_max_region_node_fraction"] = item["max_region_node_fraction"]
            row[f"k{k}_type_abs_error_pct"] = abs(float(item["type_local_error_pct"]))
        out.append(row)
    return out


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_markdown(
    path: Path,
    dataset_label: str,
    workers: int,
    k_values: Sequence[int],
    input_count: int,
    skipped_count: int,
    case_rows: Sequence[Dict[str, Any]],
    aggregate_rows: Sequence[Dict[str, Any]],
) -> None:
    lines = [
        "# Local Rolling DAG Ablation",
        "",
        f"Dataset: `{dataset_label}`.",
        f"Workers: `W{workers}`.",
        f"k values: `{','.join(str(k) for k in k_values)}`.",
        "",
        "This report uses existing target-model trace DAGs. It does not call a model.",
        "",
        "Definition: full-DAG is a hindsight scheduler over the complete extracted dependency DAG. Local rolling splits the same reference DAG into dependency-level windows of depth `k`; windows execute sequentially, while nodes inside each window use the same W4 list scheduler. This is an oracle/local-structure ablation, not online measured acceleration and not GPT predictor accuracy.",
        "",
        "## Dataset",
        "",
        f"- DAG inputs found: `{input_count}`",
        f"- DAGs included: `{len(case_rows)}`",
        f"- DAGs skipped: `{skipped_count}`",
        "",
        "## Aggregate By k",
        "",
        "| k | Local W4 mean | Full W4 mean | Retention | Avg regions | Avg region nodes | Max region node frac | Type abs err mean | Type abs err p90 | Shape abs err mean |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in aggregate_rows:
        lines.append(
            "| {k} | {local:.4f}x | {global_:.4f}x | {ret:.4f} | {regions:.2f} | {avg_nodes:.2f} | {max_frac:.4f} | {type_err:.2f}% | {type_p90:.2f}% | {shape_err:.2f}% |".format(
                k=row["k"],
                local=float(row["observed_local_w4_speedup_mean"]),
                global_=float(row["observed_global_w4_speedup_mean"]),
                ret=float(row["local_retention_vs_global_mean"]),
                regions=float(row["region_count_mean"]),
                avg_nodes=float(row["avg_region_nodes_mean"]),
                max_frac=float(row["max_region_node_fraction_mean"]),
                type_err=float(row["type_local_abs_error_pct_mean"]),
                type_p90=float(row["type_local_abs_error_pct_p90"]),
                shape_err=float(row["shape_local_abs_error_pct_mean"]),
            )
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Return | Nodes | Dep edges | Levels | Peak width | Full W4 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in case_rows:
        lines.append(
            f"| `{row['case_id']}` | {row['return_code']} | {row['node_count']} | {row['dependency_edge_count']} | {row['level_count']} | {row['peak_level_width']} | {float(row['observed_global_w4_speedup']):.4f}x |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- Full-DAG numbers represent a hindsight whole-graph oracle and should be treated as a prediction-burden baseline, not the proposed runtime.",
            "- Local rolling numbers answer how much of the full-DAG scheduling benefit survives when speculation is limited to a local `k`-deep region.",
            "- Type-weighted error is evaluated against observed-duration local rolling W4 speedup. Large local-window error means the current formula is not stable enough for local benefit gating at that `k`.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dag-dir", type=Path, action="append", default=[])
    parser.add_argument("--dag", type=Path, action="append", default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dataset-label", default="local_rolling_dag_ablation")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--k", type=parse_csv_ints, default=parse_csv_ints("1,2,3,4,6"))
    parser.add_argument("--clean-only", action="store_true")
    args = parser.parse_args()

    if args.workers <= 0:
        raise SystemExit("--workers must be positive")
    dag_dirs = [path if path.is_absolute() else ROOT / path for path in args.dag_dir]
    dags = [path if path.is_absolute() else ROOT / path for path in args.dag]
    dag_paths = collect_dag_paths(dag_dirs, dags)
    if not dag_paths:
        raise SystemExit("No DAG files found")
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    case_rows: List[Dict[str, Any]] = []
    window_rows: List[Dict[str, Any]] = []
    formula_rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for dag_path in dag_paths:
        meta = meta_for_dag(dag_path)
        if args.clean_only and not is_clean_return(meta):
            skipped.append(
                {
                    "dag_path": str(dag_path),
                    "reason": "return_code_not_zero",
                    "return_code": meta.get("return_code", "unknown"),
                }
            )
            continue
        case, windows, formulas = summarize_case(dag_path, args.workers, args.k)
        case_rows.append(case)
        window_rows.extend(windows)
        formula_rows.extend(formulas)

    aggregate_rows = aggregate_by_k(window_rows)
    mech_rows = mechanism_rows(case_rows, window_rows, args.k) if case_rows else []

    write_csv(out_dir / "case_summary.csv", case_rows)
    write_csv(out_dir / "local_window_metrics.csv", window_rows)
    write_csv(out_dir / "formula_error_by_k.csv", formula_rows)
    write_csv(out_dir / "aggregate_by_k.csv", aggregate_rows)
    write_csv(out_dir / "mechanism_summary.csv", mech_rows)
    write_json(
        out_dir / "run_summary.json",
        {
            "schema_version": "local-rolling-dag-ablation-v1",
            "dataset_label": args.dataset_label,
            "workers": args.workers,
            "k_values": args.k,
            "clean_only": args.clean_only,
            "dag_inputs": [str(path) for path in dag_paths],
            "input_count": len(dag_paths),
            "included_count": len(case_rows),
            "skipped_count": len(skipped),
            "skipped": skipped,
            "outputs": {
                "case_summary": str(out_dir / "case_summary.csv"),
                "local_window_metrics": str(out_dir / "local_window_metrics.csv"),
                "formula_error_by_k": str(out_dir / "formula_error_by_k.csv"),
                "aggregate_by_k": str(out_dir / "aggregate_by_k.csv"),
                "mechanism_summary": str(out_dir / "mechanism_summary.csv"),
                "markdown": str(out_dir / "local_vs_global_dag_ablation.md"),
            },
        },
    )
    write_markdown(
        out_dir / "local_vs_global_dag_ablation.md",
        args.dataset_label,
        args.workers,
        args.k,
        len(dag_paths),
        len(skipped),
        case_rows,
        aggregate_rows,
    )
    print(f"wrote={out_dir / 'local_vs_global_dag_ablation.md'}")


if __name__ == "__main__":
    main()
