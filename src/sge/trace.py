#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


READ_PATTERNS = [
    re.compile(r"\b(?:cat|sed|head|tail|nl|less|more)\b[^;&|]*?\s((?:[./\w-]+/)*[./\w-]+(?:\.[\w-]+)?)"),
    re.compile(r"\brg\b[^;&|]*?\s((?:[./\w-]+/)*[./\w-]+(?:\.[\w-]+)?)"),
]

WRITE_PATTERNS = [
    re.compile(r">\s*((?:[./\w-]+/)*[./\w-]+(?:\.[\w-]+)?)"),
    re.compile(r"\b(?:apply_patch|python3?\s+-c)\b"),
]

PATH_IN_OUTPUT = re.compile(r"(?<![\w./-])((?:[./\w-]+/)+[./\w-]+\.[A-Za-z0-9_+-]+)(?::\d+)?")


@dataclass
class DagNode:
    node_id: str
    kind: str
    label: str
    command: Optional[str]
    status: str
    exit_code: Optional[int]
    reads: List[str]
    writes: List[str]
    output_paths: List[str]
    output_chars: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None


@dataclass
class DagEdge:
    src: str
    dst: str
    edge_type: str
    reason: str


@dataclass
class TraceDag:
    source_trace: str
    model_usage: Dict[str, Any]
    nodes: List[DagNode]
    edges: List[DagEdge]
    speculative_candidates: List[Dict[str, Any]]


def load_events(path: Path) -> List[Dict[str, Any]]:
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def event_item(event: Dict[str, Any]) -> Dict[str, Any]:
    item = event.get("item") or {}
    if item:
        return item
    raw = event.get("raw_event") or event.get("event") or {}
    if isinstance(raw, dict):
        return raw.get("item") or {}
    return {}


def event_type(event: Dict[str, Any]) -> str:
    return event.get("type") or (event.get("raw_event") or {}).get("type") or ""


def event_usage(event: Dict[str, Any]) -> Dict[str, Any]:
    usage = event.get("usage")
    if isinstance(usage, dict):
        return usage
    raw = event.get("raw_event") or event.get("event") or {}
    if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
        return raw["usage"]
    return {}


def infer_kind(command: str) -> str:
    command = unwrap_shell(command)
    if re.search(r"\b(rg|grep)\b", command):
        return "grep"
    if re.search(r"\b(sed|cat|head|tail|nl)\b", command):
        return "read"
    if re.search(r"\b(pytest|npm test|cargo test|go test|mvn test)\b", command):
        return "test"
    if re.search(r"\b(mypy|ruff|eslint|flake8|pylint)\b", command):
        return "lint"
    if re.search(r"\b(make|npm run build|cargo build|go build)\b", command):
        return "build"
    if re.search(
        r"\b(npm install|npm ci|pnpm install|yarn install|pip install|poetry install|go mod download|go mod tidy|cargo fetch|bundle install)\b",
        command,
    ):
        return "env"
    if "apply_patch" in command:
        return "edit"
    return "shell"


def extract_reads(command: str) -> List[str]:
    command = unwrap_shell(command)
    token_reads = extract_read_tokens(command)
    if token_reads:
        return token_reads
    reads: List[str] = []
    for pattern in READ_PATTERNS:
        reads.extend(match.group(1) for match in pattern.finditer(command))
    return sorted(set(clean_path(path) for path in reads if not path.startswith("-")))


def extract_read_tokens(command: str) -> List[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if not tokens:
        return []
    tool = Path(tokens[0]).name
    if tool not in {"cat", "sed", "head", "tail", "nl", "less", "more", "rg", "grep"}:
        return []
    reads: List[str] = []
    for token in tokens[1:]:
        if token.startswith("-"):
            continue
        if re.fullmatch(r"\d+(?:,\d+)?p?", token):
            continue
        if token in {"|", "&&", ";"}:
            break
        if "/" in token or "." in token:
            reads.append(clean_path(token))
    return sorted(set(reads))


def extract_writes(command: str) -> List[str]:
    command = unwrap_shell(command)
    writes = []
    for pattern in WRITE_PATTERNS[:1]:
        writes.extend(match.group(1) for match in pattern.finditer(command))
    if WRITE_PATTERNS[1].search(command):
        writes.append("<unknown>")
    return sorted(set(clean_path(path) for path in writes))


def extract_output_paths(output: str) -> List[str]:
    return sorted(set(clean_path(match.group(1)) for match in PATH_IN_OUTPUT.finditer(output or "")))


def clean_path(path: str) -> str:
    path = path.strip("'\" ")
    while path.startswith("./"):
        path = path[2:]
    return path


def clean_event_path(path: str) -> str:
    path = clean_path(path)
    marker = "/projects/"
    if marker in path:
        return "projects/" + path.split(marker, 1)[1]
    return path


def unwrap_shell(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) >= 3 and parts[0].endswith("zsh") and parts[1] in {"-c", "-lc"}:
        return parts[2]
    if len(parts) >= 3 and parts[0].endswith("bash") and parts[1] in {"-c", "-lc"}:
        return parts[2]
    return command


def build_dag(path: Path) -> TraceDag:
    events = load_events(path)
    nodes: List[DagNode] = []
    usage: Dict[str, Any] = {}
    starts: Dict[str, float] = {}

    for event in events:
        etype = event_type(event)
        if etype == "turn.completed":
            usage = event_usage(event)
        item = event_item(event)
        if etype == "item.started" and item.get("type") in {"command_execution", "file_change"}:
            if event.get("observed_at") is not None:
                starts[item.get("id") or item.get("command") or str(len(starts))] = float(event["observed_at"])
            continue
        if etype != "item.completed":
            continue
        if item.get("type") == "command_execution":
            command = item.get("command") or ""
            output = item.get("aggregated_output") or ""
            item_id = item.get("id") or command
            start_time = starts.get(item_id)
            end_time = float(event["observed_at"]) if event.get("observed_at") is not None else None
            duration = None
            if start_time is not None and end_time is not None:
                duration = max(0.0, end_time - start_time)
            nodes.append(
                DagNode(
                    node_id=f"n{len(nodes)+1}",
                    kind=infer_kind(command),
                    label=short_label(command),
                    command=command,
                    status=item.get("status") or "unknown",
                    exit_code=item.get("exit_code"),
                    reads=extract_reads(command),
                    writes=extract_writes(command),
                    output_paths=extract_output_paths(output),
                    output_chars=len(output),
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                )
            )
        elif item.get("type") == "file_change":
            changes = item.get("changes") or []
            writes = sorted(
                {
                    clean_event_path(str(change.get("path") or ""))
                    for change in changes
                    if change.get("path")
                }
            )
            kinds = ",".join(
                sorted({str(change.get("kind") or "change") for change in changes})
            )
            item_id = item.get("id") or f"file_change_{len(nodes)+1}"
            start_time = starts.get(item_id)
            end_time = float(event["observed_at"]) if event.get("observed_at") is not None else None
            duration = None
            if start_time is not None and end_time is not None:
                duration = max(0.0, end_time - start_time)
            command = f"file_change {kinds}: " + ", ".join(writes)
            nodes.append(
                DagNode(
                    node_id=f"n{len(nodes)+1}",
                    kind="edit",
                    label=short_label(command),
                    command=command,
                    status=item.get("status") or "unknown",
                    exit_code=None,
                    reads=[],
                    writes=writes,
                    output_paths=[],
                    output_chars=0,
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                )
            )
    edges = infer_edges(nodes)
    return TraceDag(str(path), usage, nodes, edges, [])


def infer_edges(nodes: List[DagNode]) -> List[DagEdge]:
    edges: List[DagEdge] = []
    for prev, cur in zip(nodes, nodes[1:]):
        edges.append(DagEdge(prev.node_id, cur.node_id, "temporal", "observed execution order"))

    last_writer: Dict[str, str] = {}
    last_reader: Dict[str, str] = {}
    path_producer: Dict[str, str] = {}
    for node in nodes:
        for read_path in node.reads:
            if read_path in last_writer:
                edges.append(DagEdge(last_writer[read_path], node.node_id, "write-read", read_path))
            if read_path in path_producer:
                edges.append(DagEdge(path_producer[read_path], node.node_id, "reveal", read_path))
            last_reader[read_path] = node.node_id
        for write_path in node.writes:
            if write_path in last_reader:
                edges.append(DagEdge(last_reader[write_path], node.node_id, "read-write", write_path))
            last_writer[write_path] = node.node_id
        for output_path in node.output_paths:
            path_producer.setdefault(output_path, node.node_id)

    last_edit: Optional[str] = None
    for node in nodes:
        if node.kind == "edit":
            last_edit = node.node_id
        elif last_edit and node.kind in {"test", "lint", "build"}:
            edges.append(DagEdge(last_edit, node.node_id, "workflow", f"edit-to-{node.kind}"))

    for prev, cur in zip(nodes, nodes[1:]):
        if prev.kind == "grep" and cur.kind == "read":
            edges.append(DagEdge(prev.node_id, cur.node_id, "workflow", "grep-to-read"))
        if prev.kind == "edit" and cur.kind in {"test", "lint", "build"}:
            edges.append(DagEdge(prev.node_id, cur.node_id, "workflow", f"edit-to-{cur.kind}"))
        if prev.kind == "test" and cur.kind in {"grep", "read"}:
            edges.append(DagEdge(prev.node_id, cur.node_id, "workflow", f"test-to-{cur.kind}"))

    seen = set()
    unique = []
    for edge in edges:
        key = (edge.src, edge.dst, edge.edge_type, edge.reason)
        if key not in seen:
            unique.append(edge)
            seen.add(key)
    return unique


def short_label(command: str) -> str:
    command = unwrap_shell(command)
    return command if len(command) <= 80 else command[:77] + "..."


def write_markdown(dag: TraceDag, out: Path) -> None:
    lines = [
        "# Codex Trace DAG",
        "",
        f"- source trace: `{dag.source_trace}`",
        f"- input tokens: `{dag.model_usage.get('input_tokens', 0)}`",
        f"- cached input tokens: `{dag.model_usage.get('cached_input_tokens', 0)}`",
        f"- output tokens: `{dag.model_usage.get('output_tokens', 0)}`",
        f"- reasoning output tokens: `{dag.model_usage.get('reasoning_output_tokens', 0)}`",
        "",
        "## Observed Nodes",
        "",
        "| id | kind | label | reads | writes | output chars |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for node in dag.nodes:
        lines.append(
            f"| {node.node_id} | {node.kind} | `{node.label}` | {', '.join(node.reads) or '-'} | {', '.join(node.writes) or '-'} | {node.output_chars} |"
        )
    lines.extend(["", "## Edges", "", "| src | dst | type | reason |", "| --- | --- | --- | --- |"])
    for edge in dag.edges:
        lines.append(f"| {edge.src} | {edge.dst} | {edge.edge_type} | {edge.reason} |")
    lines.extend(
        [
            "",
            "## Projection Boundary",
            "",
            "This file contains observed actions and inferred observed dependencies only.",
            "Semantic reference-DAG projection and audit are separate Pilot stages.",
        ]
    )
    out.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    args = parser.parse_args()

    dag = build_dag(args.trace)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "source_trace": dag.source_trace,
                    "model_usage": dag.model_usage,
                    "nodes": [asdict(node) for node in dag.nodes],
                    "edges": [asdict(edge) for edge in dag.edges],
                    "speculative_candidates": dag.speculative_candidates,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(dag, args.md_out)
    if not args.json_out and not args.md_out:
        print(json.dumps({"nodes": len(dag.nodes), "edges": len(dag.edges)}, indent=2))


if __name__ == "__main__":
    main()
