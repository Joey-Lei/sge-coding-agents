# Evidence guide

## Result index

The public artifact is easiest to read from the positive, evidence-backed primitive outward:

| Result | Exact evidence | Interpretation |
| --- | --- | --- |
| Historical same-trace replay | 10 clean Web-Bench traces; aggregate unbounded/P=4 list ceilings 4.2690x/3.4058x | Zero-overhead structural headroom over observed action traces, not realized E2E acceleration |
| Topology-first admission | 188 windows; 52/53 observed-high admitted; 131/135 observed-low rejected at 1.10x | 98.1% high-window recall, 97.0% low-window rejection, and 92.9% precision among 56 admissions |
| Selective filtering | 132/188 windows rejected by the frozen screen | 70.2% of the retrospective candidate set is filtered before executor admission; this is not measured compute savings |
| Structural opportunity | 9 exact-duration DAGs across 6 repositories; P=4 mean/median/max 1.2138x/1.1770x/1.5297x | Action-layer work/span opportunity under the supplied graph and duration assumptions |
| Local mechanism | 10 windows; 8 closures; 49 completed node artifacts; 2 fallbacks; 0 deadlocks | Bounded local structured-artifact closure, not target continuation or whole-task acceleration |

The headline numbers above are recomputed by `artifact/reviewer_snapshot/scripts/recompute_claims.py` and cross-checked by the frozen release audit. The admission rows are nested windows from seven cases and four physical/audited repositories; they are not independent task replications.

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
