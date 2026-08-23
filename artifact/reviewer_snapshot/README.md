# Speculative Graph Execution: reviewer artifact

This package is the smallest reviewer-facing slice of the SGE research repository that can recompute selected workshop-paper results without exposing private runtime data.

SGE is a task-layer execution design for coding agents. It continuously reconstructs a small local semantic WorkGraph, estimates whether the ready frontier has enough structural headroom to justify speculation, releases dependency-ready work, and verifies or falls back before committing artifacts. The research object is this rolling **predict → bound → admit → execute → verify** loop—not token-level decoding speculation and not unrestricted parallel shell execution.

## What this artifact establishes

- Historical same-trace structural replay over ten clean Web-Bench traces, including aggregate unbounded and finite-worker list ceilings.
- Exact-duration structural ceilings for nine audited action DAGs.
- Offline recalculation of the 188-window duration-blind admission study, including the harder 58-window nontrivial sensitivity.
- Mixed-duration rolling-locality sensitivity and a predictor-only diagnostic.
- A command-heavy negative smoke and a ten-window local executor smoke.
- Two historical whole-prompt functional observations (Flex and Grid), explicitly kept outside prospective performance claims.
- Symmetric rejection evidence for P007 and P018, with formal paired metrics left null.

It does **not** establish a valid prospective end-to-end `alpha_SGE`, a learned online controller, local-over-global superiority, monetary savings, SOTA performance, cross-domain generalization, or production readiness.

## Fast path

From this directory:

```bash
python3 -m pip install -r environment/requirements.txt
python3 reproduce.py
python3 -m pytest -q -p no:cacheprovider tests/test_reviewer_artifact.py tests/test_core_model.py tests/test_trace_to_dag.py
```

`reproduce.py` is offline. It makes no network, model, benchmark-target, or official-evaluator calls. Its portable default recalculates the quantitative claims and renders five evidence-governed PDF/PNG pairs in temporary storage, compares the claims with the sealed outputs, scans the package for restricted paths and credential-like material, and checks the canonical SHA-256 manifest without changing tracked files.

The sealed figure bytes depend on the platform's Matplotlib/font stack. Maintainers may intentionally regenerate those files, their accessibility previews, and all package hashes with:

```bash
python3 reproduce.py --refresh
```

Sealed outputs checked by the portable path (and regenerated only by `--refresh`):

- `outputs/recomputed_claims.json` and `outputs/recomputed_claims.md`
- `outputs/figures/*.pdf`, 300-DPI review PNGs, and `outputs/figures/figure_manifest.json`
- grayscale/protanopia/deuteranopia/tritanopia previews under `outputs/visual_checks/`
- `audit/verification_report.json`
- `evidence/figure_contract.json`, `audit/figure_bundle_audit.json`, and `audit/accessibility_manifest.json`
- `provenance/artifact_manifest.json` and `SHA256SUMS`

## Reviewer reading order

1. Read `CLAIMS.md` for the claim-to-evidence map and interpretation boundaries.
2. Run `python3 reproduce.py`.
3. Inspect `outputs/recomputed_claims.md` and the five PDFs in `outputs/figures/`.
4. Inspect P007/P018 under `results/sge_p30_paired_scale_audit_20260728/` to see why favorable and unfavorable raw ratios are both rejected.
5. Use `OPEN_SOURCE_SCOPE.md` to distinguish the clean public candidate from restricted research inputs.

## Layout

- `scripts/`: estimators, trace-to-DAG conversion, analyzers, audit code, executor smokes, figure builder, and package checks.
- `experiments/.../trace_to_reference_dag/`: annotation/adjudication prompts and JSON schemas.
- `results/`: allowlisted derived evidence and compact audit outputs; no raw session traces or evaluator logs.
- `tests/`: artifact tests plus selected upstream unit tests.
- `provenance/` and `audit/`: source lineage, sanitization evidence, package hashes, and verification status.
- `evidence/figure_contract.json`: figure-level source hashes, evidence classes, denominators, semantic styles, final-size thresholds, and accessibility outputs.

## Distribution status

This snapshot is distributed as part of the public SGE repository under the repository-root MIT License. See `LICENSE_STATUS.md` and `THIRD_PARTY_NOTICES.md` for the release boundary.

The full upstream integration suite is intentionally not bundled: it requires frozen cohort trees, live-runner contracts, and raw Stage-B inputs outside the reviewer-safe allowlist. Historical live executor prototypes are also omitted because they were not self-contained public interfaces. The packaged tests exercise the core work/span model, trace conversion, quantitative recomputation, figure rendering, privacy boundary, and invalid-pair preservation.
