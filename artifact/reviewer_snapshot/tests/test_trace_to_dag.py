#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_trace_to_dag as trace_to_dag  # noqa: E402


def write_event(handle, payload: dict) -> None:
    handle.write(json.dumps(payload) + "\n")


def test_observed_actions_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        trace = Path(tmp) / "events.jsonl"
        with trace.open("w") as handle:
            write_event(
                handle,
                {
                    "type": "item.started",
                    "observed_at": 1.0,
                    "item": {
                        "id": "search",
                        "type": "command_execution",
                        "command": "rg target src tests",
                    },
                },
            )
            write_event(
                handle,
                {
                    "type": "item.completed",
                    "observed_at": 2.0,
                    "item": {
                        "id": "search",
                        "type": "command_execution",
                        "command": "rg target src tests",
                        "aggregated_output": "src/foo.py:1:target\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
            )
            write_event(
                handle,
                {
                    "type": "item.started",
                    "observed_at": 3.0,
                    "item": {"id": "edit", "type": "file_change"},
                },
            )
            write_event(
                handle,
                {
                    "type": "item.completed",
                    "observed_at": 4.0,
                    "item": {
                        "id": "edit",
                        "type": "file_change",
                        "status": "completed",
                        "changes": [{"path": "src/foo.py", "kind": "update"}],
                    },
                },
            )
            write_event(
                handle,
                {
                    "type": "item.started",
                    "observed_at": 5.0,
                    "item": {
                        "id": "test",
                        "type": "command_execution",
                        "command": "python3 -m pytest tests/test_foo.py",
                    },
                },
            )
            write_event(
                handle,
                {
                    "type": "item.completed",
                    "observed_at": 7.0,
                    "item": {
                        "id": "test",
                        "type": "command_execution",
                        "command": "python3 -m pytest tests/test_foo.py",
                        "aggregated_output": "1 passed\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
            )
            write_event(
                handle,
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            )

        dag = trace_to_dag.build_dag(trace)
        assert [node.kind for node in dag.nodes] == ["grep", "edit", "test"]
        assert dag.nodes[0].duration == 1.0
        assert dag.nodes[1].writes == ["src/foo.py"]
        assert any(
            edge.src == "n2" and edge.dst == "n3" and edge.edge_type == "workflow"
            for edge in dag.edges
        )
        assert dag.speculative_candidates == []
        assert dag.model_usage == {"input_tokens": 10, "output_tokens": 2}


def main() -> int:
    test_observed_actions_only()
    print("test_trace_to_dag.py: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
