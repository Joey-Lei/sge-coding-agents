# Limitations and non-claims

This page is normative: claims that cross these boundaries are unsupported by the released evidence.

## Not established

- No valid quality-equivalent prospective end-to-end SGE pair is included.
- No measured <code>alpha_SGE</code> is reported.
- The online controller over horizon, worker budget, and admission threshold remains proposed.
- The evidence does not establish SOTA performance, production readiness, monetary savings, or general cross-domain transfer.
- Structural ceilings and list schedules do not include every prediction, isolation, verification, and fallback cost.
- Historical Flex and Grid summaries are functional observations, not causal speedup estimates.

## Sources of overestimation

- Missing semantic dependency edges shorten the estimated critical path.
- Duration proxies can underweight expensive work or long-tail actions.
- Candidate hit rates may change under prospective execution.
- Worker startup, workspace creation, merge, and verifier latency are absent unless represented explicitly.
- Shared resources can invalidate the identical-worker assumption.

## Sources of underestimation

- Conservative extra edges serialize work that may actually be independent.
- Local windows can omit useful parallel work beyond the current horizon.
- A deterministic list schedule may be worse than a specialized online scheduler.

## Safety boundary

The public CLI analyzes graphs and converts local traces; it does not execute speculative tools. A real executor needs sandboxing, resource budgets, side-effect classification, cancellation, artifact isolation, merge validation, and rollback. The historical prototype runners are excluded because their private dependencies and operational assumptions are not suitable as a public safety contract.

## Data boundary

Only sanitized derived evidence and compact summaries are included. Raw runtime telemetry, session transcripts, model reasoning, account metadata, benchmark answers, gold patches, hidden evaluator assets, and unrestricted logs are excluded. Consequently, the artifact can recompute the reported derived claims but cannot reconstruct every upstream live run.
