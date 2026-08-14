#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]


KIND_COST = {
    "read": 0.2,
    "grep": 0.3,
    "fetch": 0.5,
    "test": 1.5,
    "lint": 0.8,
    "build": 2.0,
    "edit": 3.0,
    "shell": 0.5,
    "failure_localization": 0.5,
    "targeted_test": 1.2,
    "patch_sketch": 1.0,
    "diagnosis_branch": 0.8,
    "env_probe": 0.5,
}

KIND_DURATION = {
    "read": 0.8,
    "grep": 1.2,
    "fetch": 2.0,
    "test": 5.0,
    "lint": 2.0,
    "build": 6.0,
    "edit": 3.0,
    "shell": 1.0,
    "failure_localization": 1.4,
    "targeted_test": 2.2,
    "patch_sketch": 2.4,
    "diagnosis_branch": 1.8,
    "env_probe": 1.2,
}

KIND_PRIORITY = {
    "patch_sketch": 1.15,
    "diagnosis_branch": 0.9,
    "read": 0.8,
    "grep": 0.8,
    "failure_localization": 0.55,
    "targeted_test": 0.55,
    "env_probe": 0.4,
}


def load_dag(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def node_duration(node: Dict[str, Any]) -> float:
    duration = node.get("duration")
    if isinstance(duration, (int, float)) and duration >= 0.05:
        return float(duration)
    return KIND_DURATION.get(node.get("kind"), 1.0)


def candidate_cost(candidate: Dict[str, Any]) -> float:
    cost = candidate.get("estimated_cost")
    if isinstance(cost, (int, float)):
        return float(cost)
    return KIND_COST.get(candidate.get("kind"), 0.5)


def candidate_saved(candidate: Dict[str, Any]) -> float:
    saved = candidate.get("estimated_latency_saved")
    if isinstance(saved, (int, float)):
        return float(saved)
    return KIND_DURATION.get(candidate.get("kind"), 1.0)


def critical_path_time(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> float:
    durations = {node["node_id"]: node_duration(node) for node in nodes}
    preds: Dict[str, List[str]] = {node["node_id"]: [] for node in nodes}
    for edge in edges:
        if edge.get("edge_type") == "temporal":
            continue
        src = edge.get("src")
        dst = edge.get("dst")
        if src in preds and dst in preds:
            preds[dst].append(src)
    memo: Dict[str, float] = {}

    def visit(node_id: str) -> float:
        if node_id in memo:
            return memo[node_id]
        prior = max((visit(pred) for pred in preds.get(node_id, [])), default=0.0)
        memo[node_id] = prior + durations.get(node_id, 0.0)
        return memo[node_id]

    return max((visit(node["node_id"]) for node in nodes), default=0.0)


def replay_policy(
    dag: Dict[str, Any],
    policy: str,
    budget: int,
    tau: float,
    cost_lambda: float,
    max_extra_cost_ratio: float = 0.15,
) -> Dict[str, Any]:
    nodes = dag.get("nodes", [])
    edges = dag.get("edges", [])
    candidates = [
        c
        for c in dag.get("speculative_candidates", [])
        if c.get("evaluation_scope", "historical_candidate") == "historical_candidate"
    ]
    observed_serial = sum(node_duration(node) for node in nodes)
    static_time = critical_path_time(nodes, edges) or observed_serial
    static_cost = sum(KIND_COST.get(node.get("kind"), 0.5) for node in nodes)

    eligible = [c for c in candidates if c.get("side_effect_risk", 0.0) == 0.0 and c.get("p_hit", 0.0) >= tau]
    if policy == "oracle":
        selected = sorted(
            [c for c in eligible if c.get("actual_used_later")],
            key=lambda c: (-candidate_saved(c), candidate_cost(c)),
        )
    elif policy == "heuristic":
        selected = sorted(
            eligible,
            key=lambda c: -(
                c.get("p_hit", 0.0) * candidate_saved(c)
                - cost_lambda * candidate_cost(c)
                - 2.0 * c.get("side_effect_risk", 0.0)
            ),
        )
    elif policy == "cost_aware":
        ranked = sorted(
            eligible,
            key=lambda c: -(
                c.get("p_hit", 0.0)
                * candidate_saved(c)
                * KIND_PRIORITY.get(c.get("kind"), 0.75)
                - cost_lambda * candidate_cost(c)
                - 2.0 * c.get("side_effect_risk", 0.0)
            ),
        )
        selected = []
        cost_cap = static_cost * max_extra_cost_ratio
        running_cost = 0.0
        for candidate in ranked:
            cost = candidate_cost(candidate)
            if running_cost + cost > cost_cap:
                continue
            selected.append(candidate)
            running_cost += cost
            if 0 <= budget <= len(selected):
                break
    elif policy == "random":
        rng = random.Random(stable_seed(dag.get("source_trace", ""), str(budget), str(tau)))
        selected = list(eligible)
        rng.shuffle(selected)
    elif policy == "static":
        selected = []
    else:
        raise ValueError(f"unknown policy: {policy}")

    selected = selected[:budget] if budget >= 0 else selected
    hits = [c for c in selected if c.get("actual_used_later")]
    misses = [c for c in selected if not c.get("actual_used_later")]
    saved = sum(candidate_saved(c) for c in hits)
    oracle_cap = max(0.0, static_time - max(critical_path_time(nodes, [e for e in edges if e.get("edge_type") != "temporal"]), 0.0))
    effective_saved = min(saved, max(static_time * 0.35, oracle_cap, 0.0))
    replay_time = max(0.01, static_time - effective_saved)
    extra_cost = sum(candidate_cost(c) for c in selected)
    wasted_cost = sum(candidate_cost(c) for c in misses)
    total_cost = static_cost + extra_cost
    return {
        "source_trace": dag.get("source_trace"),
        "policy": policy,
        "budget": budget,
        "tau": tau,
        "cost_lambda": cost_lambda,
        "max_extra_cost_ratio": max_extra_cost_ratio,
        "observed_serial_time": round(observed_serial, 4),
        "static_dag_time": round(static_time, 4),
        "replay_time": round(replay_time, 4),
        "speedup_vs_static": round(static_time / replay_time, 4) if replay_time else 0.0,
        "static_cost": round(static_cost, 4),
        "total_cost": round(total_cost, 4),
        "extra_cost_ratio": round(extra_cost / static_cost, 4) if static_cost else 0.0,
        "wasted_cost_ratio": round(wasted_cost / static_cost, 4) if static_cost else 0.0,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "hit_count": len(hits),
        "hit_rate": round(len(hits) / len(selected), 4) if selected else 0.0,
        "selected_kinds": ",".join(sorted(c.get("kind", "unknown") for c in selected)),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "token_input": dag.get("model_usage", {}).get("input_tokens", 0),
        "token_cached_input": dag.get("model_usage", {}).get("cached_input_tokens", 0),
        "token_output": dag.get("model_usage", {}).get("output_tokens", 0),
        "token_reasoning_output": dag.get("model_usage", {}).get("reasoning_output_tokens", 0),
    }


def stable_seed(*parts: str) -> int:
    import hashlib

    return int(hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:8], 16)


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_policy: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_policy.setdefault(row["policy"], []).append(row)
    out = []
    for policy, policy_rows in sorted(by_policy.items()):
        out.append(
            {
                "policy": policy,
                "n": len(policy_rows),
                "speedup_vs_static": mean(policy_rows, "speedup_vs_static"),
                "extra_cost_ratio": mean(policy_rows, "extra_cost_ratio"),
                "wasted_cost_ratio": mean(policy_rows, "wasted_cost_ratio"),
                "hit_rate": mean(policy_rows, "hit_rate"),
                "candidate_count": mean(policy_rows, "candidate_count"),
                "selected_count": mean(policy_rows, "selected_count"),
                "node_count": mean(policy_rows, "node_count"),
                "edge_count": mean(policy_rows, "edge_count"),
                "token_input": mean(policy_rows, "token_input"),
                "token_output": mean(policy_rows, "token_output"),
            }
        )
    return out


def mean(rows: Sequence[Dict[str, Any]], key: str) -> float:
    vals = [float(row.get(key, 0) or 0) for row in rows]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def write_markdown(path: Path, rows: Sequence[Dict[str, Any]], summary: Sequence[Dict[str, Any]]) -> None:
    lines = [
        "# Trace Replay Metrics",
        "",
        "## Aggregate",
        "",
        "| Policy | N | Speedup | Extra Cost | Wasted Cost | Hit Rate | Avg Candidates | Avg Nodes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary:
        lines.append(
            "| {policy} | {n} | {speedup:.2f}x | {extra:.1%} | {waste:.1%} | {hit:.1%} | {cand:.1f} | {nodes:.1f} |".format(
                policy=row["policy"],
                n=int(row["n"]),
                speedup=row["speedup_vs_static"],
                extra=row["extra_cost_ratio"],
                waste=row["wasted_cost_ratio"],
                hit=row["hit_rate"],
                cand=row["candidate_count"],
                nodes=row["node_count"],
            )
        )
    lines.extend(["", "## Notes", "", "- Replay speedup is an opportunity estimate, not online measured acceleration.", "- Extra and wasted cost use normalized tool costs in phase 1."])
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dag", nargs="*", type=Path)
    parser.add_argument("--dag-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=2)
    parser.add_argument("--tau", type=float, default=0.5)
    parser.add_argument("--cost-lambda", type=float, default=0.5)
    parser.add_argument("--max-extra-cost-ratio", type=float, default=0.15)
    args = parser.parse_args()

    dag_paths = list(args.dag)
    if args.dag_dir:
        dag_paths.extend(sorted(args.dag_dir.glob("*_dag.json")))
    if not dag_paths:
        raise SystemExit("No DAG files provided")

    rows: List[Dict[str, Any]] = []
    for dag_path in dag_paths:
        dag = load_dag(dag_path)
        for policy in ["static", "random", "heuristic", "cost_aware", "oracle"]:
            rows.append(
                replay_policy(
                    dag,
                    policy,
                    args.budget,
                    args.tau,
                    args.cost_lambda,
                    args.max_extra_cost_ratio,
                )
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "trace_replay_metrics.csv", rows)
    summary = aggregate(rows)
    write_csv(args.out_dir / "trace_replay_summary.csv", summary)
    write_markdown(args.out_dir / "trace_replay_summary.md", rows, summary)
    print(f"wrote={args.out_dir / 'trace_replay_summary.md'}")


if __name__ == "__main__":
    main()
