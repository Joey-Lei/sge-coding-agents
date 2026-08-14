# Frozen reviewer artifact

This directory contains the self-contained, reviewer-safe evidence snapshot for the SGE workshop paper.

Run it from the repository root:

~~~bash
python3 reproduce.py
~~~

Or run the snapshot directly:

~~~bash
cd artifact/reviewer_snapshot
python3 reproduce.py
python3 -m pytest -q -p no:cacheprovider tests
~~~

The snapshot performs no network, model, benchmark-target, or official-evaluator calls. It recomputes the reported values, renders five figures and accessibility previews, preserves negative and invalid cases, scans the package boundary, and checks its SHA-256 manifest.

Start with:

1. [Claim-to-evidence map](reviewer_snapshot/CLAIMS.md)
2. [Recomputed claims](reviewer_snapshot/outputs/recomputed_claims.md)
3. [Artifact status](reviewer_snapshot/STATUS.md)
4. [Source provenance](reviewer_snapshot/provenance/source_provenance.json)

The historical live executor prototypes were deliberately omitted from this public repository: one depended on private runner infrastructure and one was not self-contained. Their compact, sanitized result summaries remain because they support the paper's bounded mechanism observations. They are not part of the public API or reproduction path.
