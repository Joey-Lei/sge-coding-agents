# Annotation contracts

The public contract separates two views:

- **Observed-action DAG:** deterministic extraction from local action events.
- **Conditional semantic reference DAG:** a blinded, independently auditable projection governed by annotation, adjudication, and schema gates.

The [trace-to-reference-DAG contract](trace_to_reference_dag/README.md) includes the prompts and JSON schemas needed to inspect the projection protocol. Private runner packets, raw model responses, runtime traces, outcomes, durations, account data, and performance results are intentionally absent.

These contracts make a method inspectable; they do not make the historical model calls reproducible and do not constitute an online predictor implementation.
