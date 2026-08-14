#!/usr/bin/env python3
"""Render submission-grade, evidence-governed figures for the SGE workshop draft.

All empirical values are loaded from pinned source artifacts.  The script fails
closed if an input hash changes and records output hashes in a companion manifest.
It never generates synthetic science data or turns structural ceilings into E2E
speedups.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
os.environ["MPLBACKEND"] = "Agg"

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


BLUE = "#0072B2"
VERMILLION = "#D55E00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
GRAY = "#5C5C5C"
MID_GRAY = "#9A9A9A"
LIGHT_GRAY = "#F1F1F1"
LIGHT_BLUE = "#EAF3F8"
LIGHT_RED = "#FBEDE8"
LIGHT_GREEN = "#EAF6F1"
BLACK = "#222222"
FIGURE_WIDTH_PT = 396.0
FIGURE_WIDTH_IN = FIGURE_WIDTH_PT / 72.0

P30_FILES = {
    "p30-extension-report": (
        "results/sge_p30_ac_overlay_v2_20260728/extension_report.json",
        "12f84479a40a94d912ce1555b12a062836634c2f1f71c5a47d3544e05aa64d77",
    ),
    "p30-case-rows": (
        "results/sge_p30_ac_overlay_v2_20260728/case_rows.json",
        "f77eca5e40ad2170474c5a98660ad2ab11ea3a13547410f9b15550e74a14665c",
    ),
    "p30-candidate-windows": (
        "results/sge_p30_ac_overlay_v2_20260728/c_candidate_rows.json",
        "2f20df86ce6a69237c874e4bf7ba1a8f99981fbe5aa3e28df731a4461cc699ed",
    ),
    "p30-action-duration-ledger": (
        "results/sge_p30_ac_overlay_v2_20260728/action_duration_ledger.json",
        "db9aa1195b69585eb359863e9390461cc72520108eea67fac27c199f9c746d57",
    ),
    "sklearn-25973-effective-workgraph": (
        "results/sge_p30_trace_reference_dag_20260728/stage_b/cases/"
        "swebench_verified_scikit-learn_scikit-learn-25973/adjudication/"
        "effective_reference_dag.json",
        "7fbf4a167e4fa53ce30f9e09e431de5d6fd6b9628bffd6387eaa7a621bf9c8b6",
    ),
}

WORKSPACE_FILES = {
    "legacy-verified-locality": (
        "results/local_rolling_dag_ablation_swe_verified_local_10_20260707/aggregate_by_k.csv",
        "38381a55f7a28b580e80fd0307d8592574680ec9efd0ae909c57917e3832b812",
    ),
    "legacy-swepro-locality": (
        "results/local_rolling_dag_ablation_swe_pro_campaign_clean_20260707/aggregate_by_k.csv",
        "fc42bbc0f1a6581b61387fbbc9664977fa2b1cb1941e7f799ffabe5b04768397",
    ),
    "global-predictor-diagnostic": (
        "results/dag_prediction_gpt55_high_20260707/scoring/prediction_accuracy_summary.csv",
        "5ce5e93e0db03d40b6e9289dc559995c933dfec838b58b7648701f0c06fa73a3",
    ),
    "canonical-local-executor": (
        "results/canonical_dag_executor_family_smoke_20260708/summary.json",
        "07f1088c3c73a4277a66f57cbde25acf151343b3c8f449c7727a3f51efca4465",
    ),
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    observed = file_hash(path)
    if observed != expected:
        raise ValueError(f"sealed input hash mismatch for {path}: {observed} != {expected}")
    return observed


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
            "font.size": 8.1,
            "axes.titlesize": 8.6,
            "axes.labelsize": 8.0,
            "xtick.labelsize": 7.4,
            "ytick.labelsize": 7.4,
            "legend.fontsize": 7.2,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.linewidth": 0.8,
        }
    )


def save(fig, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the declared 396 pt canvas.  Tight bounding boxes silently change
    # the final scale and invalidate the font-size portion of the figure contract.
    fig.savefig(output)
    fig.savefig(output.with_suffix(".png"), dpi=300)
    plt.close(fig)


def case_label(row: dict[str, Any]) -> str:
    repo = str(row["physical_repository"]).split("/")[-1]
    repo = {"scikit-learn": "sklearn", "matplotlib": "mpl", "pytest": "pytest"}.get(repo, repo)
    issue = str(row["instance_id"]).rsplit("-", 1)[-1]
    return f"{repo} {issue}"


def panel_title(ax, text: str) -> None:
    ax.set_title(text, loc="left", pad=7, fontweight="bold")


def build_task_layer_map(report: dict[str, Any], output: Path) -> None:
    """Render the paper's orientation figure from a conceptual layer map and real phases."""
    configure_style()
    fig = plt.figure(figsize=(FIGURE_WIDTH_IN, 2.62))
    fig.text(0.05, 0.955, "a. SGE releases and schedules task work", fontsize=8.6, fontweight="bold", va="top")
    fig.text(0.57, 0.955, "b. Whole-task time exceeds model decisions", fontsize=8.6, fontweight="bold", va="top")

    ax = fig.add_axes([0.05, 0.25, 0.43, 0.61])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    layers = [
        (0.77, "token output drafts", GRAY, LIGHT_GRAY, "lower layer"),
        (0.56, "future plans / actions", GRAY, LIGHT_GRAY, "lower layer"),
        (0.35, "tentative tool calls", GRAY, LIGHT_GRAY, "lower layer"),
        (0.07, "semantic WorkGraph\nrelease · admit · realize · verify", VERMILLION, LIGHT_RED, "SGE"),
    ]
    for y, label, edge, face, tag in layers:
        hatch = "//" if tag == "SGE" else None
        box = FancyBboxPatch(
            (0.08, y), 0.66, 0.13 if tag != "SGE" else 0.16,
            boxstyle="round,pad=0.012,rounding_size=0.022",
            facecolor=face, edgecolor=edge, linewidth=1.15,
            linestyle="--" if tag == "SGE" else "-", hatch=hatch,
        )
        ax.add_patch(box)
        ax.text(0.41, y + (0.08 if tag == "SGE" else 0.065), label, ha="center", va="center", fontsize=7.9)
        ax.text(0.78, y + (0.08 if tag == "SGE" else 0.065), tag, ha="left", va="center", fontsize=6.9, color=edge, fontweight="bold")
    for y in (0.76, 0.56, 0.36):
        ax.add_patch(FancyArrowPatch((0.41, y), (0.41, y - 0.07), arrowstyle="-|>", mutation_scale=10, color=MID_GRAY, linewidth=0.85))
    fig.text(0.05, 0.105, "SGE operates at task release and scheduling; it can compose with lower-layer speculation.", fontsize=6.5, color=GRAY)

    ax = fig.add_axes([0.58, 0.43, 0.37, 0.36])
    phases = report["experiment_A"]["whole_task_phase_composition"]["case_weighted_mean_fraction"]
    rows = [
        ("integration / finalization / evaluator", phases["integration_finalization_and_official_evaluator"], PURPLE, "//"),
        ("measured residual", phases["measured_residual"], "#A6A6A6", ".."),
        ("real action", phases["real_action_excluding_build_test"], VERMILLION, "xx"),
        ("model decision", phases["model_decision"], BLUE, "--"),
        ("build / test", phases["build_test"], GREEN, "++"),
    ]
    left = 0.0
    for label, value, color, hatch in rows:
        width = 100 * float(value)
        bar = ax.barh([0], [width], left=[left], height=0.38, color=color, edgecolor="white", linewidth=0.9)
        bar[0].set_hatch(hatch)
        if width >= 7.5:
            ax.text(left + width / 2, 0, f"{width:.1f}%", ha="center", va="center", fontsize=7.0, color="white" if color in {GRAY, VERMILLION, BLUE} else BLACK, fontweight="bold")
        left += width
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.46, 0.48)
    ax.set_yticks([])
    ax.set_xlabel("case-weighted share of operational E2E time", labelpad=2)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", color="#E7E7E7", linewidth=0.55, zorder=0)
    handles = [Rectangle((0, 0), 1, 1, facecolor=color, edgecolor=BLACK if color == "#A6A6A6" else color, hatch=hatch, linewidth=0.55) for _, _, color, hatch in rows]
    legend_labels = ["integrate / finalize / eval.", "measured residual", "real action", "model decision", "build / test"]
    fig.legend(handles, legend_labels, loc="lower left", bbox_to_anchor=(0.57, 0.145, 0.41, 0.19), ncol=2, frameon=False, handlelength=0.9, handletextpad=0.25, columnspacing=0.6, borderaxespad=0.0, fontsize=6.5)
    fig.text(0.58, 0.055, "23 records / 10 repositories; descriptive only.", fontsize=6.5, color=GRAY)
    save(fig, output)


def node_duration_map(ledger: dict[str, Any], case_id: str) -> dict[str, float]:
    case = next(item for item in ledger["cases"] if item["case_id"] == case_id)
    durations: dict[str, float] = {}
    for row in case["rows"]:
        for node_id, seconds in row.get("semantic_allocations_seconds", {}).items():
            durations[node_id] = durations.get(node_id, 0.0) + float(seconds)
    return durations


def build_case_workgraph(
    case_rows: list[dict[str, Any]], ledger: dict[str, Any], dag: dict[str, Any], output: Path
) -> None:
    """Render the audited scikit-learn WorkGraph and its structural P=4 ceiling."""
    configure_style()
    case_id = "swebench_verified_scikit-learn_scikit-learn-25973"
    metrics_row = next(row for row in case_rows if row["case_id"] == case_id)
    metrics = metrics_row["observed_duration_metrics"]
    durations = node_duration_map(ledger, case_id)
    if abs(sum(durations.values()) - float(metrics["W"])) > 1e-6:
        raise ValueError("node-duration aggregation does not match audited W")
    critical = set(metrics["critical_path_nodes"])

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_IN, 3.0))
    fig.subplots_adjust(left=0.03, right=0.985, top=0.98, bottom=0.05)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.0, 0.98, "Audited action-layer WorkGraph: scikit-learn-25973", va="top", fontsize=8.8, fontweight="bold")
    ax.text(0.0, 0.915, "Eight semantic nodes; thick black edges identify the critical path. Node labels show observed action-layer duration.", va="top", fontsize=7.2, color=GRAY)

    layout = {
        "n_target_search": (0.07, 0.60),
        "n_project_inventory": (0.07, 0.29),
        "n_secondary_search": (0.28, 0.67),
        "n_primary_context": (0.30, 0.37),
        "n_secondary_context": (0.48, 0.61),
        "n_documentation_review": (0.30, 0.14),
        "n_patch_candidate": (0.66, 0.47),
        "n_behavior_validation": (0.86, 0.47),
    }
    labels = {
        "n_target_search": "target\nsearch",
        "n_project_inventory": "project\ninventory",
        "n_secondary_search": "secondary\nsearch",
        "n_primary_context": "primary\ncontext",
        "n_secondary_context": "secondary\ncontext",
        "n_documentation_review": "documentation\nreview",
        "n_patch_candidate": "patch\ncandidate",
        "n_behavior_validation": "behavior\nvalidation",
    }
    node_by_id = {node["node_id"]: node for node in dag["nodes"]}

    def center(node_id: str) -> tuple[float, float]:
        return layout[node_id][0] + 0.055, layout[node_id][1] + 0.062

    for edge in dag["edges"]:
        source, target = edge["src"], edge["dst"]
        is_critical = source in critical and target in critical
        ax.add_patch(
            FancyArrowPatch(
                center(source), center(target), arrowstyle="-|>", mutation_scale=10,
                linewidth=1.8 if is_critical else 0.85,
                linestyle="-" if is_critical else "--",
                color=BLACK if is_critical else MID_GRAY,
                shrinkA=13, shrinkB=13, connectionstyle="arc3,rad=0.0",
                zorder=1,
            )
        )

    for node_id, (x, y) in layout.items():
        kind = node_by_id[node_id]["kind"]
        if kind in {"grep", "read"}:
            edge, face, linestyle, hatch = BLUE, LIGHT_BLUE, "-", None
        elif kind == "patch_candidate":
            edge, face, linestyle, hatch = VERMILLION, LIGHT_RED, "--", "//"
        elif kind == "test":
            edge, face, linestyle, hatch = GREEN, LIGHT_GREEN, "-", "++"
        else:
            edge, face, linestyle, hatch = GRAY, LIGHT_GRAY, "-", None
        box = FancyBboxPatch((x, y), 0.11, 0.125, boxstyle="round,pad=0.009,rounding_size=0.014", facecolor=face, edgecolor=edge, linewidth=1.1, linestyle=linestyle, hatch=hatch, zorder=2)
        ax.add_patch(box)
        ax.text(x + 0.055, y + 0.079, labels[node_id], ha="center", va="center", fontsize=6.8, zorder=3)
        ax.text(x + 0.055, y + 0.020, f"{durations[node_id]:.2f} s", ha="center", va="center", fontsize=6.5, color=GRAY, zorder=3)

    ax.plot([0.49, 0.57], [0.83, 0.83], color=BLACK, linewidth=1.8)
    ax.text(0.59, 0.83, "thick edge = critical path", va="center", fontsize=6.8)

    cards = [
        (0.05, 0.00, 0.21, "total work $W$", f"{float(metrics['W']):.3f} s", BLUE),
        (0.29, 0.00, 0.21, "critical-path span $L$", f"{float(metrics['L']):.3f} s", BLACK),
        (0.53, 0.00, 0.42, "$P=4$ structural ceiling", f"{float(metrics['finite_workers']['P4']['list_headroom']):.3f}×", VERMILLION),
    ]
    for x, y, width, label, value, edge in cards:
        box = FancyBboxPatch((x, y), width, 0.10, boxstyle="round,pad=0.008,rounding_size=0.01", facecolor="white", edgecolor=edge, linewidth=1.0, hatch="//" if edge == VERMILLION else None)
        ax.add_patch(box)
        ax.text(x + 0.012, y + 0.066, label, va="center", fontsize=6.7, color=GRAY)
        ax.text(x + width - 0.012, y + 0.031, value, va="center", ha="right", fontsize=8.2, fontweight="bold", color=edge)
    save(fig, output)


def build_rolling_atlas(
    predictor: list[dict[str, str]], verified: list[dict[str, str]], pro: list[dict[str, str]], case_rows: list[dict[str, Any]], output: Path
) -> None:
    configure_style()
    fig = plt.figure(figsize=(FIGURE_WIDTH_IN, 3.60))

    ax = fig.add_axes([0.09, 0.60, 0.34, 0.27])
    panel_title(ax, "a. Full future-DAG prediction")
    full = next(row for row in predictor if row["mode"] == "full")
    labels = ["node\nrecall", "edge\nrecall", "work\nretained"]
    values = [100 * float(full["node_recall_mean"]), 100 * float(full["edge_recall_mean"]), 100 * float(full["retained_reference_work_ratio_mean"])]
    colors = [BLUE, GRAY, VERMILLION]
    hatches = ["//", "xx", "\\\\"]
    bars = ax.bar(range(3), values, color=colors, edgecolor="white", width=0.68)
    for bar, value, hatch in zip(bars, values, hatches):
        bar.set_hatch(hatch)
        ax.text(bar.get_x() + bar.get_width() / 2, value + 3.0, f"{value:.1f}%", ha="center", va="bottom", fontsize=7.2, fontweight="bold")
    ax.set_xticks(range(3), labels)
    ax.set_ylim(0, 73)
    ax.set_ylabel("reference coverage")
    ax.grid(axis="y", color="#E8E8E8", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.97, 0.95, f"5 cases\n{float(full['wall_time_seconds_mean']):.1f} s/call\n{float(full['total_tokens_mean']) / 1000:.1f}k tokens/call", transform=ax.transAxes, ha="right", va="top", fontsize=6.5, color=GRAY, bbox=dict(facecolor="white", edgecolor="#DADADA", pad=1.5))

    ax = fig.add_axes([0.59, 0.60, 0.34, 0.27])
    panel_title(ax, "b. Rolling WorkGraph horizons")
    series = [
        ("SWE Verified (10)", verified, BLUE, "o", "-"),
        ("SWE-Pro clean (5)", pro, VERMILLION, "D", "--"),
    ]
    for label, rows, color, marker, linestyle in series:
        selected = [row for row in rows if int(row["k"]) <= 3]
        xs = [int(row["k"]) for row in selected]
        ys = [100 * float(row["local_retention_vs_global_mean"]) for row in selected]
        ax.plot(xs, ys, marker=marker, markersize=5.2, color=color, markerfacecolor="white" if marker == "D" else color, linewidth=1.5, linestyle=linestyle, label=label)
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.9, f"{y:.1f}", ha="center", va="bottom", fontsize=6.6)
    ax.axhline(100, color=MID_GRAY, linestyle=":", linewidth=0.9)
    ax.set_xlim(0.8, 3.2)
    ax.set_ylim(81, 102.6)
    ax.set_xticks([1, 2, 3])
    ax.set_xlabel("local horizon depth $k$")
    ax.set_ylabel("full-graph opportunity retained")
    ax.set_yticks([85, 90, 95, 100], ["85%", "90%", "95%", "100%"])
    ax.grid(color="#E8E8E8", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", frameon=False, handlelength=1.7, handletextpad=0.35, fontsize=6.3)

    fig.text(0.20, 0.485, "c. Exact-duration action-layer structural ceilings ($P=4$)", fontsize=8.6, fontweight="bold", va="top")
    ax = fig.add_axes([0.22, 0.12, 0.72, 0.29])
    observed = [row for row in case_rows if row.get("observed_duration_join_eligible")]
    observed.sort(key=lambda row: float(row["observed_duration_metrics"]["finite_workers"]["P4"]["list_headroom"]))
    ys = list(range(len(observed)))
    values = [float(row["observed_duration_metrics"]["finite_workers"]["P4"]["list_headroom"]) for row in observed]
    ax.hlines(ys, 1.0, values, color="#D9D9D9", linewidth=1.25, zorder=1)
    ax.scatter(values, ys, marker="D", s=31, color=VERMILLION, edgecolor="white", linewidth=0.5, zorder=3, label="$P=4$ ceiling")
    ax.axvline(sum(values) / len(values), color=BLUE, linestyle="--", linewidth=1.0, label="mean 1.214×")
    ax.axvline(1.0, color=BLACK, linewidth=0.8)
    ax.set_yticks(ys, [case_label(row) for row in observed], fontsize=7.0)
    ax.set_xlim(0.96, 1.60)
    ax.set_xticks([1.0, 1.2, 1.4, 1.6], ["1.0×", "1.2×", "1.4×", "1.6×"])
    ax.set_xlabel("observed-duration action-layer ceiling")
    ax.grid(axis="x", color="#E8E8E8", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.02, 1.02, "9 DAGs · 6 repositories · maximum 1.530×", transform=ax.transAxes, fontsize=6.6, color=GRAY)
    ax.text(0.98, 0.05, "dashed: mean 1.214×", transform=ax.transAxes, ha="right", va="bottom", fontsize=6.5, color=BLUE)
    save(fig, output)


def classify_windows(rows: list[dict[str, Any]], threshold: float) -> dict[str, list[tuple[float, float]]]:
    groups = {"reject-low": [], "admit-high": [], "false-admit": [], "false-reject": []}
    for row in rows:
        if row.get("observed_ceiling") is None:
            continue
        estimated, observed = float(row["estimated_ceiling"]), float(row["observed_ceiling"])
        if estimated < threshold and observed < threshold:
            groups["reject-low"].append((estimated, observed))
        elif estimated >= threshold and observed >= threshold:
            groups["admit-high"].append((estimated, observed))
        elif estimated >= threshold:
            groups["false-admit"].append((estimated, observed))
        else:
            groups["false-reject"].append((estimated, observed))
    return groups


def rank_correlation(xs: list[float], ys: list[float]) -> float:
    def ranks(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda item: item[1])
        result = [0.0] * len(values)
        start = 0
        while start < len(indexed):
            end = start + 1
            while end < len(indexed) and indexed[end][1] == indexed[start][1]:
                end += 1
            rank = (start + 1 + end) / 2.0
            for index, _ in indexed[start:end]:
                result[index] = rank
            start = end
        return result
    rx, ry = ranks(xs), ranks(ys)
    mean_x, mean_y = sum(rx) / len(rx), sum(ry) / len(ry)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(rx, ry))
    denom_x = sum((x - mean_x) ** 2 for x in rx) ** 0.5
    denom_y = sum((y - mean_y) ** 2 for y in ry) ** 0.5
    return numerator / (denom_x * denom_y)


def build_admission_figure(rows: list[dict[str, Any]], output: Path) -> None:
    configure_style()
    threshold = 1.10
    paired = [row for row in rows if row.get("observed_ceiling") is not None]
    nontrivial = [row for row in paired if not (abs(float(row["estimated_ceiling"]) - 1.0) < 1e-12 and abs(float(row["observed_ceiling"]) - 1.0) < 1e-12)]
    if len(paired) != 188 or len(nontrivial) != 58:
        raise ValueError(f"unexpected structural-window counts: paired={len(paired)}, nontrivial={len(nontrivial)}")
    groups = classify_windows(paired, threshold)
    if {key: len(value) for key, value in groups.items()} != {"reject-low": 131, "admit-high": 52, "false-admit": 4, "false-reject": 1}:
        raise ValueError("frozen threshold counts do not match source windows")
    xs = [float(row["estimated_ceiling"]) for row in nontrivial]
    ys = [float(row["observed_ceiling"]) for row in nontrivial]
    rho = rank_correlation(xs, ys)
    mape = 100 * sum(abs(x - y) / y for x, y in zip(xs, ys)) / len(xs)
    mae = sum(abs(x - y) for x, y in zip(xs, ys)) / len(xs)

    fig = plt.figure(figsize=(FIGURE_WIDTH_IN, 3.00))
    ax = fig.add_axes([0.08, 0.27, 0.48, 0.64])
    panel_title(ax, "a. Nontrivial windows retain a useful ordering signal")
    styles = {
        "reject-low": dict(edgecolors=BLUE, facecolors="none", marker="o", linewidths=0.8, s=27, label="correct reject"),
        "admit-high": dict(color=VERMILLION, marker="D", linewidths=0.3, s=29, label="correct admit"),
        "false-admit": dict(color=GRAY, marker="x", linewidths=1.25, s=33, label="false admit"),
        "false-reject": dict(edgecolors=BLACK, facecolors="white", marker="^", linewidths=1.0, s=36, label="false reject"),
    }
    for name, style in styles.items():
        points = [(x, y) for x, y in groups[name] if not (abs(x - 1.0) < 1e-12 and abs(y - 1.0) < 1e-12)]
        if points:
            ax.scatter([x for x, _ in points], [y for _, y in points], zorder=3 if "false" in name else 2, **style)
    lo, hi = 0.96, 4.0
    ax.plot([lo, hi], [lo, hi], color=MID_GRAY, linestyle=(0, (4, 2)), linewidth=0.9, zorder=0)
    ax.axvline(threshold, color=GRAY, linestyle=":", linewidth=0.9)
    ax.axhline(threshold, color=GRAY, linestyle=":", linewidth=0.9)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("type-weighted $P=4$ ceiling (×)")
    ax.set_ylabel("observed-duration $P=4$ ceiling (×)")
    ax.grid(color="#E8E8E8", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.03, 0.96, f"58 nontrivial windows\n$\\rho$={rho:.3f} · MAE={mae:.3f}× · MAPE={mape:.1f}%", transform=ax.transAxes, ha="left", va="top", fontsize=7.0, bbox=dict(facecolor="white", edgecolor="#DADADA", pad=2.0))
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.09, 0.005, 0.48, 0.105), ncol=2, frameon=False, handletextpad=0.35, columnspacing=0.8, borderaxespad=0.0, fontsize=6.5)

    ax = fig.add_axes([0.71, 0.35, 0.24, 0.48])
    panel_title(ax, "b. Frozen 1.10× screen")
    cells = [
        (0, 0, 131, BLUE, "//", "correct\nreject"),
        (1, 0, 4, GRAY, "xx", "false\nadmit"),
        (0, 1, 1, "white", "..", "false\nreject"),
        (1, 1, 52, VERMILLION, "\\\\", "correct\nadmit"),
    ]
    for x, y, count, color, hatch, label in cells:
        edge = BLACK if color == "white" else color
        patch = Rectangle((x, y), 1, 1, facecolor=color, edgecolor=edge, linewidth=0.95, hatch=hatch)
        ax.add_patch(patch)
        text_color = "white" if color in {BLUE, VERMILLION, GRAY} else BLACK
        ax.text(x + 0.5, y + 0.60, str(count), ha="center", va="center", fontsize=13.5, fontweight="bold", color=text_color)
        ax.text(x + 0.5, y + 0.30, label, ha="center", va="center", fontsize=7.0, color=text_color)
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.set_aspect("equal")
    ax.set_xticks([0.5, 1.5], ["reject", "admit"])
    ax.set_yticks([0.5, 1.5], ["< 1.10×", "≥ 1.10×"])
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.text(0.71, 0.105, "188 duration-blind windows\n4 held-out repositories\n130 joint unit-ceiling windows\nappear only in this matrix.", fontsize=6.5, color=GRAY)
    save(fig, output)


def build_evidence_boundary(report: dict[str, Any], executor: dict[str, Any], output: Path) -> None:
    configure_style()
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_IN, 1.72))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.0, 0.98, "Current evidence boundary", va="top", fontsize=8.8, fontweight="bold")
    boxes = [
        (0.01, "STRUCTURAL\nCEILING", "9 audited DAGs\nmax $P=4$: 1.530×", VERMILLION, LIGHT_RED, "//"),
        (0.26, "BOUND-FIRST\nADMISSION", "188 blind windows\n131 / 135 low rejected", BLUE, LIGHT_BLUE, "//"),
        (0.51, "LOCAL\nCLOSURE", f"{executor['case_count']} local windows\n{executor['local_dag_execution_success']} closures; {executor['deadlock']} deadlocks", GREEN, LIGHT_GREEN, "++"),
        (0.76, "PROSPECTIVE\nE2E SGE GAIN", "no valid\nfull-E2E pair", GRAY, LIGHT_GRAY, "xx"),
    ]
    for x, title, body, edge, face, hatch in boxes:
        box = FancyBboxPatch((x, 0.20), 0.225, 0.56, boxstyle="round,pad=0.012,rounding_size=0.018", facecolor=face, edgecolor=edge, linewidth=1.05, linestyle="--" if edge == GRAY else "-", hatch=hatch)
        ax.add_patch(box)
        ax.text(x + 0.1125, 0.61, title, ha="center", va="center", fontsize=6.5, fontweight="bold", color=edge, linespacing=1.05, bbox=dict(facecolor="white", edgecolor="none", alpha=0.88, pad=0.35))
        ax.text(x + 0.1125, 0.37, body, ha="center", va="center", fontsize=6.5, linespacing=1.05, bbox=dict(facecolor="white", edgecolor="none", alpha=0.84, pad=0.25))
    ax.text(0.01, 0.06, "Structural ceilings, retrospective evidence, and local closures remain distinct from measured end-to-end SGE gain.", fontsize=6.5, color=GRAY)
    save(fig, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--p30-source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    workspace_root = args.workspace_root.resolve()
    p30_root = args.p30_source_root.resolve()
    output_dir = args.output_dir.resolve()

    def display_path(path: Path) -> str:
        for root in (workspace_root, p30_root):
            try:
                return path.relative_to(root).as_posix()
            except ValueError:
                continue
        return path.name

    source_manifest: list[dict[str, str]] = []
    paths: dict[str, Path] = {}
    for source_id, (relative, expected) in P30_FILES.items():
        path = p30_root / relative
        source_manifest.append({"id": source_id, "path": display_path(path), "sha256": require_hash(path, expected)})
        paths[source_id] = path
    for source_id, (relative, expected) in WORKSPACE_FILES.items():
        path = workspace_root / relative
        source_manifest.append({"id": source_id, "path": display_path(path), "sha256": require_hash(path, expected)})
        paths[source_id] = path

    report = read_json(paths["p30-extension-report"])
    case_rows = read_json(paths["p30-case-rows"])
    window_rows = read_json(paths["p30-candidate-windows"])
    ledger = read_json(paths["p30-action-duration-ledger"])
    dag = read_json(paths["sklearn-25973-effective-workgraph"])
    predictor = read_csv(paths["global-predictor-diagnostic"])
    verified = read_csv(paths["legacy-verified-locality"])
    pro = read_csv(paths["legacy-swepro-locality"])
    executor = read_json(paths["canonical-local-executor"])

    outputs = {
        "F-task-layer-map": output_dir / "task_layer_map_and_envelope.pdf",
        "F-workgraph-case": output_dir / "workgraph_case_ceiling.pdf",
        "F-rolling-atlas": output_dir / "rolling_evidence_atlas.pdf",
        "F-admission": output_dir / "admission_calibration_nontrivial.pdf",
        "F-evidence-boundary": output_dir / "evidence_maturity_boundary.pdf",
    }
    build_task_layer_map(report, outputs["F-task-layer-map"])
    build_case_workgraph(case_rows, ledger, dag, outputs["F-workgraph-case"])
    build_rolling_atlas(predictor, verified, pro, case_rows, outputs["F-rolling-atlas"])
    build_admission_figure(window_rows, outputs["F-admission"])
    build_evidence_boundary(report, executor, outputs["F-evidence-boundary"])

    manifest = {
        "schema_version": 1,
        "classification": "evidence-governed manuscript figures; no synthetic scientific values",
        "source_artifacts": source_manifest,
        "outputs": [
            {"id": figure_id, "path": display_path(path), "sha256": file_hash(path)}
            for figure_id, path in outputs.items()
        ],
        "review_outputs": [
            {
                "id": figure_id,
                "path": display_path(path.with_suffix(".png")),
                "sha256": file_hash(path.with_suffix(".png")),
                "dpi": 300,
            }
            for figure_id, path in outputs.items()
        ],
        "notes": {
            "structural_ceiling": "Action-layer WorkGraph ceilings are not measured whole-task alpha_SGE.",
            "locality": "Legacy rolling-local values are mixed-duration structural sensitivity.",
            "admission": "The principal scatter shows the nontrivial sensitivity; the matrix reports all paired windows.",
            "prospective_alpha": "No valid quality-equivalent full-E2E pair is reported.",
        },
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "outputs": manifest["outputs"], "manifest": str(args.manifest_output)}, sort_keys=True))


if __name__ == "__main__":
    main()
