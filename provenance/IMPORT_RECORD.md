# Public repository import record

The clean repository was assembled on 2026-08-14 from the sealed, reviewer-verified SGE artifact revision <code>9a2bb6256d3d2a32df915beca105f0eb93f1d231</code>.

The import was allowlist-based. It did not copy the source repository's Git history, raw telemetry, runtime sessions, provider credentials, evaluator assets, generated task workspaces, or unrestricted logs.

Two historical executor scripts were removed from the public snapshot:

- <code>run_candidate_dag_executor_v2.py</code>, because its imported dependency was absent;
- <code>run_canonical_dag_executor_family_smoke.py</code>, because it launched live agent processes and depended on non-public datasets and scoring infrastructure.

Their sanitized compact result summaries remain as bounded historical evidence. The public package exposes only offline graph analysis, replay, trace conversion, annotation contracts, evidence recomputation, and release audits.
