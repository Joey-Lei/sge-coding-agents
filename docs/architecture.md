# Architecture and invariants

## System boundary

SGE is a task-layer control loop for coding agents. It sits between an agent's evolving action trace and isolated tool execution:

1. **Predict:** construct a small local semantic WorkGraph around the current frontier.
2. **Bound:** estimate total work, dependency span, and finite-worker headroom.
3. **Admit:** release only dependency-ready, side-effect-safe candidates when expected utility clears a threshold.
4. **Execute:** run admitted candidates in isolated workspaces with explicit resource limits.
5. **Verify:** validate outputs before commitment; otherwise discard and fall back.

This repository provides inspectable implementations of the graph analysis, list scheduling, replay utilities, observed-action trace conversion, annotation contract, and offline evidence pipeline. It does not provide a production provider adapter or an online learned admission controller.

## WorkGraph model

A WorkGraph is a directed acyclic graph <code>G = (V, E)</code>. Each node represents an effective task-layer action with a duration or duration proxy. Non-temporal edges encode semantic dependencies. Pure observation order is represented separately as a temporal edge and is excluded from scheduling by default.

For work <code>T1</code>, span <code>Tinf</code>, and <code>P</code> identical workers, the relaxed speedup ceiling is:

<code>T1 / max(Tinf, T1 / P)</code>

The implementation also runs a deterministic bottom-level-priority list schedule. Both quantities are opportunity estimates over the supplied graph. They do not include prediction error, execution overhead, verification cost, or fallback cost unless those costs are explicitly represented as nodes.

## Safety invariants

- Temporal adjacency is not silently promoted to semantic dependency.
- Cyclic dependency graphs fail closed.
- Side-effecting candidates require a separate isolation and rollback contract.
- Speculative output is not a committed artifact until verification succeeds.
- Invalid paired experiments keep formal paired metrics null.
- Raw runtime traces, credentials, model reasoning, gold patches, and hidden evaluator assets are outside the public evidence boundary.
- Structural ceilings are never relabeled as observed end-to-end speedups.

## Public modules

- <code>sge.graph</code>: work/span analysis, critical paths, relaxed bounds, and finite-worker list scheduling.
- <code>sge.replay</code>: deterministic offline replay of historical candidate policies.
- <code>sge.trace</code>: conversion of local JSONL action events into observed-action DAGs.
- <code>sge.cli</code>: reviewer-safe CLI for graph analysis and local trace conversion.

Semantic reference-DAG projection is governed by [the annotation contract](../contracts/trace_to_reference_dag/README.md), not inferred automatically by the CLI.
