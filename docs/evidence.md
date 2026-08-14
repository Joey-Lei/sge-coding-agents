# Evidence guide

## Reading order

1. Read the [claim-to-evidence map](../artifact/reviewer_snapshot/CLAIMS.md).
2. Inspect [the recomputed claims](../artifact/reviewer_snapshot/outputs/recomputed_claims.md).
3. Review the five PDFs or 300-DPI PNGs under <code>artifact/reviewer_snapshot/outputs/figures</code>.
4. Inspect P007 and P018 under <code>artifact/reviewer_snapshot/results/sge_p30_paired_scale_audit_20260728</code>.
5. Check [source provenance](../artifact/reviewer_snapshot/provenance/source_provenance.json) and the package manifest.

## Evidence classes

| Class | Interpretation |
| --- | --- |
| Structural ceiling | Work/span opportunity on audited action DAGs |
| Admission diagnostic | Whether a duration-blind screen separates low- and high-opportunity windows |
| Mechanism smoke | Whether local closure, fallback, and isolation mechanisms operated in bounded historical runs |
| Functional observation | Historical whole-prompt compatibility evidence that is not a prospective causal result |
| Invalid pair | A protocol failure whose formal paired metrics remain null |

The artifact includes positive, negative, and null evidence. Removing unfavorable cases would break both the manifest and the tests.

## Traceability

The figure contract pins each figure to hashed source artifacts, evidence class, denominator, visual semantics, geometry, and accessibility outputs. The package manifest hashes every included file except its own manifest files. Reproduction refreshes and then verifies these records.

No reviewer needs private infrastructure to audit the packaged claims. The tradeoff is deliberate: the release can validate the paper's reported offline calculations, but it cannot recreate live provider behavior from the sanitized snapshot.
