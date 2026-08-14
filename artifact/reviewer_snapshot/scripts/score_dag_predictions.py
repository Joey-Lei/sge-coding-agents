#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "datasets" / "dag_prediction_gpt55_high_20260707"
DEFAULT_PREDICTIONS = ROOT / "results" / "dag_prediction_gpt55_high_20260707" / "predictions"
DEFAULT_OUT = ROOT / "results" / "dag_prediction_gpt55_high_20260707" / "scoring"
WORD_RE = re.compile(r"[A-Za-z0-9_./-]+")
KIND_GROUPS = {
    "read": {"read", "shell"},
    "grep": {"grep", "read", "shell"},
    "shell": {"shell", "read", "grep", "test", "lint", "build"},
    "edit": {"edit", "patch", "patch_candidate"},
    "test": {"test", "targeted_test", "shell"},
    "lint": {"lint", "shell"},
    "build": {"build", "shell"},
    "diagnosis": {"diagnosis", "diagnosis_branch", "read", "grep"},
    "env_probe": {"env_probe", "shell"},
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def event_usage(meta: Dict[str, Any]) -> Dict[str, int]:
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    events_path = meta.get("events_path")
    if not events_path:
        return usage
    path = Path(events_path)
    if not path.exists():
        return usage
    with path.open() as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_usage_payload = event.get("usage") or {}
            for key in usage:
                usage[key] += int(event_usage_payload.get(key) or 0)
    return usage


def extract_json(text: str) -> Tuple[Dict[str, Any] | None, str]:
    raw = text.strip()
    if not raw:
        return None, "empty"
    fenced = re.search(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", raw, flags=re.S)
    if fenced:
        raw = fenced.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error:{exc}"
    if not isinstance(obj, dict):
        return None, "not_object"
    return obj, ""


def tokens(value: Any) -> set[str]:
    if isinstance(value, (list, tuple)):
        text = " ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value or "")
    return {tok.lower() for tok in WORD_RE.findall(text) if len(tok) > 1}


def pred_text(node: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("kind") or ""),
            str(node.get("intent") or ""),
            str(node.get("command_pattern") or ""),
            " ".join(str(x) for x in node.get("files", []) or []),
            " ".join(str(x) for x in node.get("expected_outputs", []) or []),
        ]
    )


def ref_text(node: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("kind") or ""),
            str(node.get("label") or ""),
            " ".join(str(x) for x in node.get("reads", []) or []),
            " ".join(str(x) for x in node.get("writes", []) or []),
            " ".join(str(x) for x in node.get("output_paths", []) or []),
        ]
    )


def kind_score(pred_kind: str, ref_kind: str) -> float:
    pred = (pred_kind or "").lower()
    ref = (ref_kind or "").lower()
    if pred == ref:
        return 1.0
    if pred in KIND_GROUPS and ref in KIND_GROUPS[pred]:
        return 0.65
    if ref in KIND_GROUPS and pred in KIND_GROUPS[ref]:
        return 0.65
    return 0.0


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def node_similarity(pred: Dict[str, Any], ref: Dict[str, Any]) -> float:
    pred_files = tokens(pred.get("files", []))
    ref_files = tokens([*(ref.get("reads", []) or []), *(ref.get("writes", []) or []), *(ref.get("output_paths", []) or [])])
    text_score = jaccard(tokens(pred_text(pred)), tokens(ref_text(ref)))
    file_score = jaccard(pred_files, ref_files)
    return 0.45 * kind_score(str(pred.get("kind") or ""), str(ref.get("kind") or "")) + 0.35 * file_score + 0.20 * text_score


def target_reference(reference: Dict[str, Any], mode: str, prefix_level: int | None, k: int | None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], set[str]]:
    nodes = reference["reference"]["nodes"]
    edges = reference["reference"]["edges"]
    if mode == "full":
        target = nodes
        prefix_ids: set[str] = set()
    else:
        assert prefix_level is not None and k is not None
        lo = prefix_level
        hi = prefix_level + k
        target = [node for node in nodes if lo <= int(node.get("level", 0)) < hi]
        prefix_ids = {str(node["id"]) for node in nodes if int(node.get("level", 0)) < lo}
    target_ids = {str(node["id"]) for node in target}
    target_edges = [edge for edge in edges if str(edge.get("src")) in target_ids and str(edge.get("dst")) in target_ids]
    return target, target_edges, prefix_ids


def greedy_match(pred_nodes: Sequence[Dict[str, Any]], ref_nodes: Sequence[Dict[str, Any]], threshold: float) -> List[Dict[str, Any]]:
    candidates: List[Tuple[float, int, int]] = []
    for pi, pred in enumerate(pred_nodes):
        for ri, ref in enumerate(ref_nodes):
            score = node_similarity(pred, ref)
            if score >= threshold:
                candidates.append((score, pi, ri))
    candidates.sort(reverse=True)
    used_pred: set[int] = set()
    used_ref: set[int] = set()
    matches: List[Dict[str, Any]] = []
    for score, pi, ri in candidates:
        if pi in used_pred or ri in used_ref:
            continue
        used_pred.add(pi)
        used_ref.add(ri)
        matches.append(
            {
                "pred_index": pi,
                "ref_index": ri,
                "pred_id": str(pred_nodes[pi].get("id") or f"pred_{pi}"),
                "ref_id": str(ref_nodes[ri].get("id")),
                "score": round(score, 4),
                "pred_kind": pred_nodes[pi].get("kind", ""),
                "ref_kind": ref_nodes[ri].get("kind", ""),
            }
        )
    return matches


def score_edges(pred_edges: Sequence[Dict[str, Any]], ref_edges: Sequence[Dict[str, Any]], matches: Sequence[Dict[str, Any]]) -> Tuple[int, int, int]:
    pred_to_ref = {str(match["pred_id"]): str(match["ref_id"]) for match in matches}
    ref_pairs = {(str(edge.get("src")), str(edge.get("dst"))) for edge in ref_edges}
    correct = 0
    considered = 0
    for edge in pred_edges:
        src = pred_to_ref.get(str(edge.get("src")))
        dst = pred_to_ref.get(str(edge.get("dst")))
        if not src or not dst:
            continue
        considered += 1
        if (src, dst) in ref_pairs:
            correct += 1
    return correct, considered, len(ref_pairs)


def closure_rate(reference: Dict[str, Any], ref_nodes: Sequence[Dict[str, Any]], matches: Sequence[Dict[str, Any]], prefix_ids: set[str]) -> float:
    matched = {str(match["ref_id"]) for match in matches}
    target_ids = {str(node["id"]) for node in ref_nodes}
    if not matched:
        return 0.0
    edges = reference["reference"]["edges"]
    ok = 0
    for node_id in matched:
        preds = [str(edge.get("src")) for edge in edges if str(edge.get("dst")) == node_id]
        if all(pred in prefix_ids or pred in matched or pred not in target_ids for pred in preds):
            ok += 1
    return ok / len(matched)


def phase_recall(pred_nodes: Sequence[Dict[str, Any]], ref_nodes: Sequence[Dict[str, Any]]) -> float:
    pred_kinds = {str(node.get("kind") or "").lower() for node in pred_nodes}
    ref_kinds = {str(node.get("kind") or "").lower() for node in ref_nodes}
    if not ref_kinds:
        return 0.0
    recalled = 0
    for ref in ref_kinds:
        if ref in pred_kinds or any(ref in KIND_GROUPS.get(pred, set()) for pred in pred_kinds):
            recalled += 1
    return recalled / len(ref_kinds)


def score_task(task_id: str, reference: Dict[str, Any], prediction_dir: Path, threshold: float) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any] | None]:
    last_message = prediction_dir / f"dag_prediction_gpt55_high_{task_id}_last_message.txt"
    meta_path = prediction_dir / f"dag_prediction_gpt55_high_{task_id}_meta.json"
    meta = load_json(meta_path) if meta_path.exists() else {}
    usage = event_usage(meta)
    obj, parse_error = extract_json(last_message.read_text() if last_message.exists() else "")
    mode = reference["mode"]
    prefix_level = reference.get("prefix_level")
    k = reference.get("k")
    ref_nodes, ref_edges, prefix_ids = target_reference(reference, mode, prefix_level, k)
    base = {
        "task_id": task_id,
        "case_id": reference["case_id"],
        "case_label": reference["case_label"],
        "mode": mode,
        "prefix_level": "" if prefix_level is None else prefix_level,
        "k": "" if k is None else k,
        "target_node_count": len(ref_nodes),
        "target_edge_count": len(ref_edges),
        "model": meta.get("model", ""),
        "reasoning_effort": meta.get("model_reasoning_effort", ""),
        "return_code": meta.get("return_code", ""),
        "wall_time_seconds": round(float(meta.get("wall_time") or 0.0), 4),
        "input_tokens": usage["input_tokens"],
        "cached_input_tokens": usage["cached_input_tokens"],
        "output_tokens": usage["output_tokens"],
        "reasoning_output_tokens": usage["reasoning_output_tokens"],
        "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        "parse_error": parse_error,
    }
    if obj is None:
        return {
            **base,
            "predicted_node_count": 0,
            "predicted_edge_count": 0,
            "matched_node_count": 0,
            "node_precision": 0.0,
            "node_recall": 0.0,
            "edge_precision": 0.0,
            "edge_recall": 0.0,
            "phase_recall": 0.0,
            "closure_rate": 0.0,
            "retained_reference_work_ratio": 0.0,
            "wasted_predicted_node_ratio": 1.0,
            "prediction_confidence": 0.0,
        }, [], obj
    pred_nodes = obj.get("nodes") if isinstance(obj.get("nodes"), list) else []
    pred_edges = obj.get("edges") if isinstance(obj.get("edges"), list) else []
    matches = greedy_match(pred_nodes, ref_nodes, threshold)
    correct_edges, considered_edges, ref_edge_count = score_edges(pred_edges, ref_edges, matches)
    ref_weight_by_id = {str(node["id"]): float(node.get("weight") or 1.0) for node in ref_nodes}
    matched_work = sum(ref_weight_by_id.get(str(match["ref_id"]), 0.0) for match in matches)
    total_work = sum(ref_weight_by_id.values())
    row = {
        **base,
        "predicted_node_count": len(pred_nodes),
        "predicted_edge_count": len(pred_edges),
        "matched_node_count": len(matches),
        "node_precision": round(len(matches) / len(pred_nodes), 4) if pred_nodes else 0.0,
        "node_recall": round(len(matches) / len(ref_nodes), 4) if ref_nodes else 0.0,
        "edge_precision": round(correct_edges / considered_edges, 4) if considered_edges else 0.0,
        "edge_recall": round(correct_edges / ref_edge_count, 4) if ref_edge_count else 0.0,
        "phase_recall": round(phase_recall(pred_nodes, ref_nodes), 4),
        "closure_rate": round(closure_rate(reference, ref_nodes, matches, prefix_ids), 4),
        "retained_reference_work_ratio": round(matched_work / total_work, 4) if total_work else 0.0,
        "wasted_predicted_node_ratio": round((len(pred_nodes) - len(matches)) / len(pred_nodes), 4) if pred_nodes else 1.0,
        "prediction_confidence": obj.get("confidence", 0.0),
    }
    match_rows = [{**base, **match} for match in matches]
    return row, match_rows, obj


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: Sequence[Dict[str, Any]], mode: str | None = None) -> Dict[str, Any]:
    selected = [row for row in rows if mode is None or row["mode"] == mode]
    if not selected:
        return {"mode": mode or "all", "n": 0}
    metrics = [
        "node_precision",
        "node_recall",
        "edge_precision",
        "edge_recall",
        "phase_recall",
        "closure_rate",
        "retained_reference_work_ratio",
        "wasted_predicted_node_ratio",
        "wall_time_seconds",
    ]
    out: Dict[str, Any] = {"mode": mode or "all", "n": len(selected)}
    for metric in metrics:
        out[f"{metric}_mean"] = round(mean(float(row.get(metric) or 0.0) for row in selected), 4)
    token_fields = [
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ]
    for field in token_fields:
        total = sum(int(float(row.get(field) or 0)) for row in selected)
        out[f"{field}_total"] = total
        out[f"{field}_mean"] = round(total / len(selected), 2)
    return out


def write_markdown(path: Path, rows: Sequence[Dict[str, Any]], summary_rows: Sequence[Dict[str, Any]]) -> None:
    lines = [
        "# GPT-5.5 High DAG Prediction Accuracy",
        "",
        "This report scores real GPT-5.5 high DAG predictions against hidden reference DAGs extracted from target traces.",
        "",
        "It is predictor accuracy and trace-grounded value estimation, not online measured acceleration.",
        "",
        "## Aggregate",
        "",
        "| Mode | N | Node P | Node R | Edge P | Edge R | Closure | Retained Work | Wasted Pred | Wall Time | Tokens / Call |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            "| {mode} | {n} | {np:.4f} | {nr:.4f} | {ep:.4f} | {er:.4f} | {cl:.4f} | {rw:.4f} | {ww:.4f} | {wall:.2f}s | {tok:.0f} |".format(
                mode=row["mode"],
                n=row["n"],
                np=float(row.get("node_precision_mean", 0.0)),
                nr=float(row.get("node_recall_mean", 0.0)),
                ep=float(row.get("edge_precision_mean", 0.0)),
                er=float(row.get("edge_recall_mean", 0.0)),
                cl=float(row.get("closure_rate_mean", 0.0)),
                rw=float(row.get("retained_reference_work_ratio_mean", 0.0)),
                ww=float(row.get("wasted_predicted_node_ratio_mean", 0.0)),
                wall=float(row.get("wall_time_seconds_mean", 0.0)),
                tok=float(row.get("total_tokens_mean", 0.0)),
            )
        )
    lines.extend(
        [
            "",
            "## Task Rows",
            "",
            "| Mode | Case | Prefix | k | Target Nodes | Pred Nodes | Node P | Node R | Closure | Retained Work | Wasted | Parse Error |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| {mode} | `{case}` | {prefix} | {k} | {tn} | {pn} | {np:.4f} | {nr:.4f} | {cl:.4f} | {rw:.4f} | {ww:.4f} | {err} |".format(
                mode=row["mode"],
                case=row["case_label"][:80],
                prefix=row["prefix_level"],
                k=row["k"],
                tn=row["target_node_count"],
                pn=row["predicted_node_count"],
                np=float(row["node_precision"]),
                nr=float(row["node_recall"]),
                cl=float(row["closure_rate"]),
                rw=float(row["retained_reference_work_ratio"]),
                ww=float(row["wasted_predicted_node_ratio"]),
                err=row["parse_error"],
            )
        )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--prediction-dir", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--match-threshold", type=float, default=0.27)
    args = parser.parse_args()
    dataset_dir = args.dataset_dir if args.dataset_dir.is_absolute() else ROOT / args.dataset_dir
    prediction_dir = args.prediction_dir if args.prediction_dir.is_absolute() else ROOT / args.prediction_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    references = load_json(dataset_dir / "references.json")
    rows: List[Dict[str, Any]] = []
    match_rows: List[Dict[str, Any]] = []
    for task_id, reference in references.items():
        row, matches, _ = score_task(task_id, reference, prediction_dir, args.match_threshold)
        rows.append(row)
        match_rows.extend(matches)
    full_rows = [row for row in rows if row["mode"] == "full"]
    local_rows = [row for row in rows if row["mode"] == "local"]
    summary_rows = [aggregate(rows, "full"), aggregate(rows, "local"), aggregate(rows, None)]
    write_csv(out_dir / "prediction_accuracy_all.csv", rows)
    write_csv(out_dir / "full_dag_prediction_accuracy.csv", full_rows)
    write_csv(out_dir / "local_dag_prediction_accuracy.csv", local_rows)
    write_csv(out_dir / "prediction_node_matches.csv", match_rows)
    write_csv(out_dir / "prediction_accuracy_summary.csv", summary_rows)
    write_markdown(out_dir / "full_vs_local_predictor_summary.md", rows, summary_rows)
    print(f"wrote={out_dir / 'full_vs_local_predictor_summary.md'}")


if __name__ == "__main__":
    main()
