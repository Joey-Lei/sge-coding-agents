"""Command-line interface for the reviewer-safe SGE analysis core."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .graph import parse_duration_model, parse_workers, summarize_dag
from .trace import build_dag


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sge",
        description="Analyze task-layer WorkGraphs without executing tools or calling models.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Compute work/span and finite-worker scheduling estimates for one DAG.",
    )
    analyze.add_argument("dag", type=Path)
    analyze.add_argument("--workers", type=parse_workers, default=parse_workers("1,2,4"))
    analyze.add_argument("--duration-model", type=parse_duration_model, default="observed")
    analyze.add_argument("--include-temporal", action="store_true")
    analyze.add_argument("--output", type=Path)

    trace = subparsers.add_parser(
        "trace-to-dag",
        help="Convert a local JSONL action trace into an observed-action DAG.",
    )
    trace.add_argument("trace", type=Path)
    trace.add_argument("--output", type=Path, required=True)
    return parser


def analyze_command(args: argparse.Namespace) -> dict:
    row = summarize_dag(
        args.dag,
        workers=args.workers,
        include_temporal=args.include_temporal,
        duration_model=args.duration_model,
    )
    row["dag_path"] = args.dag.as_posix()
    return {
        "schema_version": 1,
        "analysis": row,
        "claim_boundary": (
            "Scheduling opportunity over an annotated WorkGraph; this is not measured "
            "end-to-end acceleration."
        ),
    }


def trace_command(args: argparse.Namespace) -> dict:
    dag = build_dag(args.trace)
    payload = {
        "source_trace": args.trace.as_posix(),
        "model_usage": dag.model_usage,
        "nodes": [asdict(node) for node in dag.nodes],
        "edges": [asdict(edge) for edge in dag.edges],
        "speculative_candidates": dag.speculative_candidates,
        "projection_boundary": (
            "Observed actions and inferred observed dependencies only; semantic reference-DAG "
            "projection requires the separate annotation contract."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "pass",
        "nodes": len(dag.nodes),
        "edges": len(dag.edges),
        "output": args.output.as_posix(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        payload = analyze_command(args)
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    if args.command == "trace-to-dag":
        print(json.dumps(trace_command(args), sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
