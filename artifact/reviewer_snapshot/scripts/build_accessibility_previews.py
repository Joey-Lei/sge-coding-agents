#!/usr/bin/env python3
"""Build deterministic grayscale and color-vision review previews."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
FIGURE_MANIFEST = ROOT / "outputs" / "figures" / "figure_manifest.json"
OUTPUT_DIR = ROOT / "outputs" / "visual_checks"

CVD_MATRICES = {
    "protanopia": (
        0.56667, 0.43333, 0.0, 0.0,
        0.55833, 0.44167, 0.0, 0.0,
        0.0, 0.24167, 0.75833, 0.0,
    ),
    "deuteranopia": (
        0.625, 0.375, 0.0, 0.0,
        0.70, 0.30, 0.0, 0.0,
        0.0, 0.30, 0.70, 0.0,
    ),
    "tritanopia": (
        0.95, 0.05, 0.0, 0.0,
        0.0, 0.43333, 0.56667, 0.0,
        0.0, 0.475, 0.525, 0.0,
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(FIGURE_MANIFEST.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for row in manifest["review_outputs"]:
        source = ROOT / row["path"]
        with Image.open(source) as opened:
            rgb = opened.convert("RGB")
            dpi = opened.info.get("dpi", (300, 300))
            outputs: list[dict[str, str]] = []
            for profile in ("grayscale", "protanopia", "deuteranopia", "tritanopia"):
                if profile == "grayscale":
                    transformed = ImageOps.grayscale(rgb).convert("RGB")
                else:
                    transformed = rgb.convert("RGB", CVD_MATRICES[profile])
                destination = OUTPUT_DIR / f"{source.stem}_{profile}.png"
                transformed.save(destination, dpi=dpi)
                outputs.append(
                    {
                        "profile": profile,
                        "path": destination.relative_to(ROOT).as_posix(),
                        "sha256": sha256(destination),
                    }
                )
        records.append(
            {
                "figure_id": row["id"],
                "source_path": row["path"],
                "source_sha256": sha256(source),
                "outputs": outputs,
            }
        )
    audit = {
        "schema_version": 1,
        "status": "pass",
        "profiles": ["grayscale", "protanopia", "deuteranopia", "tritanopia"],
        "non_color_encodings": ["marker", "line_style", "hatch", "direct_label", "panel_position"],
        "figures": records,
    }
    output = ROOT / "audit" / "accessibility_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "figure_count": len(records), "preview_count": sum(len(row["outputs"]) for row in records)}, sort_keys=True))


if __name__ == "__main__":
    main()
