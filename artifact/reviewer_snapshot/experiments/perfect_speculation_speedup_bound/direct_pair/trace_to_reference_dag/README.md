# Trace-to-Conditional-Reference-DAG Contract

```text
contract_id = PSB-TRACE-REFERENCE-DAG-V4
status = v4_golden_audited_pending_user_case_acceptance
golden_qualification_case = web_bench_flex_task1_5
scale_campaign = SGE-TRACE-DAG-SCALE30-01
scale_approval = accepted_2026-07-26
```

This contract freezes a process and evidence boundary, not the historical
Flex topology. Every case must derive its own conditional semantic reference
DAG from a source selected before any paired speedup is visible.

V2 preserved the V1 blind topology candidate and added a separate,
outcome-only adjudication stage. The raw candidate is never rewritten. This
separation prevents private validation outcomes from shaping the initial
semantic topology while still allowing case-specific conditional work to be
retained, revised, or contracted into the system envelope.

The first V2 development-golden adjudication failed its semantic compatibility
gate: it materialized `13` nodes, `21` edges, and one branch instead of the
approved `15/24/1` projection. The raw response and failure remain sealed.
The failure showed that an outcome class alone was insufficient to distinguish
role-specific recovery input from system-envelope diagnosis.

V3 therefore derives a coarse, duration/outcome/performance-blind action and
resource-role row for every raw node before Stage B. The derivation is
deterministic and hash-bound to the sealed Stage-A projection, lineage, and
authoritative observed DAG. Only coarse roles enter the model view; raw
commands, paths, outputs, outcomes, durations, and performance remain private.
The V3 contract is explicitly calibrated on the Flex development golden. That
golden is a regression gate, not an independent validation case.

The sealed V3 call then made the intended semantic decisions—retain
`15` nodes and move the entire post-budget continuation—but its raw moved-branch
row retained a now-moot trigger and one activating routing value. Strict V3
finalization correctly rejected that response without rewriting it. V4 leaves
V3 packets strict and immutable, while deterministically canonicalizing only
those execution fields when the branch semantic decision is
`move_to_system_envelope` and every raw activated node is already moved. Node
decisions, branch semantic decisions, rationales, and raw response bytes remain
unchanged. Replaying the exact sealed V3 response under this V4 postprocessing
is a no-model development regression, not a new model observation, independent
validation case, or sufficient live golden gate. A V4 development-golden packet
must producer-report one fresh dispatch and bind the V4 prompt, input seal,
reconstructed command/stdin, attempt intent, raw response, event stream,
stderr, accounting, and the single agent message before campaign canary
execution. This is trusted-local-runner anti-stale evidence, not cryptographic
attestation that a remote provider served the call.

The V4 provenance sequence is mandatory and deliberately avoids a
self-referential commit:

```text
runner commit
  -> prepare packet
  -> prepared-packet commit + rollback tag
  -> exactly one adjudicator call
  -> deterministic finalize + golden verification
  -> evidence commit
  -> independent audit
  -> audit commit
  -> campaign golden/canary gate
```

The runner commit freezes the Stage-B, campaign, and qualification scripts plus
the adjudicator prompt and response schema by Git blob identity. The prepared
packet commit freezes every input, its input seal, and the prepare report before
dispatch. The evidence commit freezes every finalized pre-audit artifact,
including its then-current inventory and seal. The independent audit is added
after that commit; the external audit commit then freezes the complete
post-audit root. Campaign gates require that final commit and verify it descends
from the evidence commit. A local reseal, standalone report, partial SHA, or
uncommitted artifact tree cannot unlock execution.

The fresh V4 development-golden observation completed this sequence on
2026-07-26. It used exactly one `gpt-5.6-sol / ultra` Stage-B request, zero
retry, and zero tool calls; the audited effective graph is `15/24/1` and its
semantic projection matches the approved Flex overlay. The model response was
already execution-canonical, so deterministic V4 normalization applied to one
moved branch but changed zero fields. The Git chain is:

```text
runner   fbfebf5d36dbc131d045dec42fadf48248899fc3
packet   09d3096caff4ed9f3451cfeb7913a9cbeaec7431
evidence b858004df1d5539c4ef0fc96cfffbcd9e3924d90
audit    1145d6dab2ca646f62ee6fa85acc11729580eff5
```

The case-level calibration records are not part of the reviewer-safe public
allowlist. This contract preserves the method boundary but does not expose
private runner packets or model-call records. The development case is not an
independent performance sample.

## Transformation

```text
preselected sealed Target-Default trace
  -> deterministic observed-action DAG
  -> duration/outcome/result-blind action projection
  -> one structured semantic annotation call
  -> observed node and edge disposition ledgers
  -> immutable raw conditional semantic DAG candidate
  -> deterministic identity/coverage/acyclicity/leakage checks
  -> sealed coarse action/resource-role derivation
  -> sealed trace-derived private validation episodes
  -> deterministic outcome-class normalization
  -> one isolated outcome adjudication call
  -> persist the immutable raw adjudicator response
  -> deterministic V4 moved-branch execution-field canonicalization
  -> deterministic non-overwriting effective-DAG materialization
  -> seal the complete V4 result root
  -> independent reconstruction of event/response/accounting/DAG lineage
  -> reseal with the independent audit
  -> user/oracle freeze
  -> duration attachment and W/L/finite-worker analysis
```

The annotator receives the common task contract and the blind projection only.
It must not receive the historical reference DAG, Perfect-arm prompt or trace,
Default/Perfect latency, token/cost data, official evaluator result, final
answer, or any speedup result. Raw commands, exact paths, patches, outputs,
timestamps, durations, exit codes, and local outcomes are removed by the
projection.

The Stage-B adjudicator receives exactly three evidence roles: the raw
candidate's semantic view with coarse blind node roles, the same task contract,
and normalized outcome classes. It cannot receive trace-originated raw commands
or outputs, exact trace paths, historical/reference DAGs, Perfect-arm material,
durations, evaluator facts, tokens, cost, speedup, or an approved golden
overlay. The common task contract may contain task-declared commands or paths
that are identical for both future arms. Positive outcome witnesses must be
derived from the sealed Stage-A lineage and a hash-pinned source trace;
hand-authored or synthetic validation episodes are inadmissible.

## What is frozen

The reusable object is the transformation contract:

- exactly one authoritative source trace selected before outcome comparison;
- immutable source identities and SHA-256 digests;
- deterministic blind projection;
- one declared annotator model, effort, prompt, schema, and attempt;
- one declared adjudicator model, effort, prompt, schema, and attempt;
- full 40-hex runner, prepared-packet, evidence, and audit commit identities;
- exact Git blob identities for critical runner files and every packet/evidence/
  audit artifact;
- an exact allowlist for deterministic blind-role classifier inputs;
- exactly-once dispositions for every observed node and extractor edge;
- provenance for every semantic node, edge, and conditional branch;
- leakage, graph, coverage, and seal verification;
- an immutable raw candidate plus a separately sealed effective overlay;
- an explicit user/oracle freeze decision.

The following are not frozen across cases:

- node or edge count;
- Flex node identifiers or its width-eight read frontier;
- presence of an environment-recovery branch;
- a particular critical path, depth, width, or speedup.

## Dispositions

Every observed action has exactly one disposition:

```text
retain
merge_into_semantic_node
split_across_semantic_nodes
discard_redundant_exploration
discard_tool_noise
move_to_system_envelope
```

Every extractor edge has exactly one disposition:

```text
retain_causal
replace_by_semantic_edge
drop_incidental_temporal
drop_resource_serialization
merge_internal
move_to_system_envelope
reject_extractor_false_positive
```

Removing redundant work and false or incidental dependency edges is a
first-class Perfect-Speculation mechanism. It is reported separately from
finite-worker concurrency and overhead; it is not treated as a confound.

## Public and private views

`reference_dag.json` is the only view eligible for a future Perfect arm. It may
contain semantic intent, canonical kind, coarse dependencies, artifact/risk
classes, batchability, and generic observable guards.

Under V4, the equivalent treatment-eligible object is
`effective_reference_dag.json` only after Stage-B verification and independent
audit. The Stage-A `raw_reference_dag.json` remains the immutable method output
used to measure adjudication drift and attrition.

The source evidence, blind input, mapping/edge/branch ledgers, raw traces,
duration joins, comparison DAGs, evaluator facts, and performance results stay
private to qualification and audit. They must never be copied into the
treatment.

## Qualification gates

A case candidate fails closed unless:

1. all source and comparison identities resolve to the recorded bytes;
2. the annotator made exactly one call with zero tool calls and no retry;
3. every projected observed node and edge has exactly one disposition;
4. every semantic node and edge has non-empty provenance;
5. canonical node kinds match `GOLDEN_RULES.md`;
6. the semantic graph has no dangling endpoints, self edges, duplicate edges,
   or cycles;
7. every branch has an observable guard, activated set, provenance, and
   explicit else/fallback behavior;
8. the treatment view contains no command, exact path, patch, output, result,
   evaluator fact, answer, duration, token, cost, or speedup leakage;
9. output seals and deterministic verification pass; and
10. an independent semantic audit and explicit user/oracle freeze follow.

V3 adds machine-enforced anti-drift gates:

- an effective runner-recovery branch retains exactly one bounded
  revalidation and terminates at it;
- non-mutating role-specific recovery inputs that supply that revalidation
  cannot be moved solely because the runner outcome failed;
- a moved `working_source` read is post-mutation, precedes no later mutation,
  and reaches retained semantic work only through at least one `join`
  boundary; and
- a continuation triggered after the retained revalidation moves as one
  post-budget envelope branch rather than becoming a second semantic branch.

V4 adds one narrowly versioned deterministic rule. For a branch already
semantically moved to the system envelope whose raw activated nodes are all
moved, its execution-only fields canonicalize to a null trigger and terminal,
an empty activated set, zero attempt budget, skip routing for known outcomes,
and fail-closed routing for ambiguity. A non-moved branch remains fully strict,
and no branch with a retained activated node qualifies. Verification records
the raw response SHA-256, the normalization count, and preservation of node and
branch semantic decisions.

For the approved 30-case campaign, the following additional order is
mandatory:

1. materialize exactly 30 preselected source traces and freeze their Git blobs;
2. pass all no-model unit, mutation, resume, leakage, and source-binding gates;
3. freeze the exact runner files in a runner commit; prepare the V4 packet,
   create its commit and rollback tag, and verify runner-to-packet ancestry plus
   every packet blob before any intent or dispatch;
4. retain the sealed, non-retryable V3 development-golden failure; verify
   offline that V4 deterministically materializes its exact raw response as the
   approved Flex `15/24/1` semantic projection without rewriting it; then run
   one producer-reported fresh, exactly-once V4 development-golden dispatch and
   require the same compatibility result, while recording that both checks are
   calibration rather than independent validation and that local lineage is not
   remote-provider attestation;
5. finalize and golden-verify, create the evidence commit, independently audit
   that exact committed pre-audit tree, then create the post-audit commit;
6. run and fully adjudicate the first cohort case as a one-worker canary;
7. require complete sealed golden and canary Stage-B result roots, with each
   report and independent audit at its canonical in-root path, before the
   remaining 29 cases can start; standalone JSON reports cannot unlock either
   gate; and
8. run with at most three concurrent annotators, one attempt per stage, zero
   retry, zero tool calls, and a three-failure circuit breaker.

Golden or canary failure stops scale. Failed, blocked, and ambiguous cases
remain in the frozen 30-case denominator and are never replaced.

Historical Flex remains an incomplete-lineage observation. This prospective
qualification may calibrate the new method against it, but must not claim to
retroactively reconstruct the missing historical mapping/edge ledger.

## Benefit decomposition

For a Default execution and a frozen semantic graph, report these separately:

```text
work reduction                  = Delta W
critical-path compression       = Delta L
finite-worker concurrency gain
prediction/scheduling/validation/merge/fallback overhead
```

Type-weighted `W` and `L` are estimator diagnostics. Observed-duration `W` and
`L` remain null when complete provider/model/action/evaluator coverage is
missing. A type-weighted delta must never be described as measured wall time.

The scale campaign can establish method completion/attrition, raw and
effective topology distributions, mapping and edge closure, treatment
leakage, adjudication drift, and type-weighted structural headroom. It cannot
by itself establish observed-duration whole-task headroom, predictor accuracy,
online SGE acceleration, direct-pair speedup, or a realized `3–4x` claim.
