# Recommended open-source boundary

## Publish in the first clean release

1. **Core model and estimators**
   - DAG work/span and finite-worker ceiling calculations.
   - Rolling trace replay and local-window construction.
   - Trace-to-semantic-DAG conversion.

2. **Auditable research contract**
   - Annotation and adjudication prompts.
   - JSON schemas and effective-action disposition rules.
   - Definitions separating structural ceiling, historical functional observation, local closure, and prospective E2E performance.

3. **Reproduction and analysis**
   - Structural/admission analyzers and sensitivity analysis.
   - Strict paired-gate verification, including invalid-case handling. Live provider runners remain outside this reviewer package.
   - Figure generation, offline claim recomputation, tests, environment pins, provenance, and SHA-256 manifests.

4. **Reviewer-safe derived evidence**
   - Aggregated CSV/JSON rows needed to recalculate paper numbers.
   - Attrition ledgers and failed-gate evidence.
   - Minimal historical functional summaries for Flex and Grid.

Keeping negative and null results is part of the release contract. P007/P018 and the command-heavy fallback smoke must not be removed simply because they weaken the headline.

## Publish only after a separate rights/privacy review

- Full raw telemetry transformed into a documented public schema.
- Benchmark task packets or evaluator material whose redistribution rights are confirmed.
- Container images, vendored fixtures, or third-party code with complete notices.
- Live provider adapters and full paired runners after removing machine-, account-, and service-specific bindings.
- Production executor integrations after they have a stable safety and rollback contract.

## Do not publish

- Credentials, auth files, cookies, provider headers, account identifiers, or reusable secret values.
- Runtime session history, raw model reasoning, internal agent transcripts, or model last-message files.
- Raw OTEL containing account metadata.
- Hidden evaluator assets, gold patches, reference solutions, or benchmark answers.
- Temporary workspaces, private absolute paths, unrestricted raw logs, or unrelated repository state.

## Do not mislabel as implemented

The dynamic online controller over horizon, worker budget, and admission threshold remains proposed. The public code should present that component as an interface or research direction until an integrated predictor–executor–verifier evaluation exists.

## Suggested public repository shape

```text
sge/
  README.md
  LICENSE
  CITATION.cff
  sge/                  # reusable model / scheduler library
  contracts/            # schemas and annotation protocol
  analysis/             # paper analyzers
  artifact/             # reviewer-safe derived evidence
  tests/
  docs/claims.md
  docs/data_card.md
```

The public repository now covers the `analysis`, `contracts`, `artifact`, and stable reviewer-safe library API under `src/sge/`. Live provider adapters, historical executor prototypes, and production integrations remain outside the release boundary.
