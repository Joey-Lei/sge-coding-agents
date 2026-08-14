# Data card

## Contents

The frozen artifact contains reviewer-safe derived rows, compact summaries, reference-DAG fragments, attrition ledgers, strict invalid-pair audits, figure inputs, and deterministic outputs. It contains no training dataset.

## Origin

The evidence was assembled from historical SGE experiments over public-repository coding tasks and SWE-bench-style identifiers. Exact source snapshots and pre-sanitization hashes are recorded in [source_provenance.json](../artifact/reviewer_snapshot/provenance/source_provenance.json). Where sanitization changed bytes, the sanitization report binds the original and packaged hashes.

## Transformations

- Machine-local paths were replaced with category placeholders.
- Runtime-session locators, internal agent labels, account identifiers, and emails were removed where present.
- Raw prompts, model messages, evaluator logs, generated workspaces, gold patches, and reference solutions were excluded.
- Quantitative values used by the paper were not altered by privacy sanitization.

## Intended use

- Recompute the paper's derived numerical claims.
- Audit positive, negative, and null evidence.
- Re-render evidence-governed figures.
- Inspect the annotation contract and graph-analysis implementation.

## Out-of-scope use

The package is not a benchmark release, training corpus, production telemetry sample, or complete recreation of live provider runs. Public task identifiers should not be interpreted as redistribution of the corresponding task text or evaluator assets.

## Integrity

The snapshot's manifest hashes every included file except the manifest itself and its text rendering. Reproduction verifies required files, restricted-family exclusion, text safety, invalid-pair null metrics, figure source/output hashes, geometry, embedded fonts, vector content, and accessibility previews.
