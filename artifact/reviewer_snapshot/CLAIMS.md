# Claim-to-evidence map

The main paper must remain self-contained: reviewers are not required to read this optional artifact. This map makes the supporting computations inspectable and states the boundary for each result.

| Claim | Packaged evidence | Offline check | Boundary |
| --- | --- | --- | --- |
| Nine exact-duration action DAGs from six repositories have P=4 mean/median/max ceilings of 1.2138x / 1.1770x / 1.5297x. | `results/sge_p30_ac_overlay_v2_20260728/case_rows.json` | `scripts/recompute_claims.py` aggregates only `observed_duration_join_eligible` rows. | Structural action-layer ceiling; not realized whole-task speedup. |
| The duration-blind screen covers 188 windows from seven cases and four held-out repositories; pooled Spearman is 0.9898, MAE 0.0852x, MAPE 5.65%. | `results/sge_c1_structural_validation_20260729/window_rows.json` | Ranks, absolute errors, and percentage errors are recomputed from per-window P=4 values. | Oracle/audited topology with duration-blind weights; not future-topology prediction. Windows are clustered, not independent task replications. |
| At 1.10x, the screen rejects 131/135 observed-low windows and admits 52/53 observed-high windows. | Same 188 rows plus `structural_validation_report.json`. | Threshold confusion counts are recomputed row by row. | Ceiling classification, not observed utility or quality. |
| After removing 130 joint-unit windows, 58 nontrivial windows yield Spearman 0.7649, MAE 0.2762x, MAPE 18.32%. | Same 188 rows and `attrition_ledger.json`. | Joint-unit filtering and metrics are recomputed independently. | This sensitivity must accompany the stronger pooled correlation. |
| Depth-two/depth-three rolling windows retain 94.89%/98.57% and 98.54%/99.96% of full-graph P=4 opportunity in the two legacy cohorts. | Two `aggregate_by_k.csv` files. | Values are selected by cohort and `k`. | Mixed-duration extracted-DAG sensitivity; not exact-duration performance. |
| A five-case full-graph predictor diagnostic reports 40.38% node recall, 8.11% edge recall, and 55.8% retained type-weighted work. | `results/dag_prediction_gpt55_high_20260707/scoring/prediction_accuracy_summary.csv` | The sealed `mode=full` row is parsed. | Predictor-only pilot; no runtime speedup claim. |
| A ten-run command-heavy smoke accepts zero artifacts and falls back ten times, with 35.28% latency and 22.97% token overhead under fallback accounting. | `corrected_outcome_summary.json` under `candidate_dag_executor_eval_20260708/`. | Counts and corrected ratios are checked. | Negative mechanism evidence; not a matched causal abstraction study. |
| A ten-window local executor smoke closes eight windows, emits 49 artifacts, needs two fallbacks, has zero deadlocks, mean max concurrency 2.6, and wall/ideal-W4 1.0021. | Historical `summary.json` and extracted registry record. | Summary and correction record are cross-checked. | Stops at local structured artifacts; no target continuation or official evaluator. The private-dependency runner is not distributed. |
| Flex and Grid preserve equal official scores across arms (19/19 and 24/24), with recorded E2E ratios 1.6442x and 1.0578x and total-token ratios 0.3546 and 0.5022. | Minimal metrics/result/audit/reference-DAG files for both cases. | Scores and ratios are checked together with `performance_claim_eligible=false`. | Historical whole-prompt functional observations with partial semantic realization; `R_hist`, not `alpha_SGE`. |
| P007 and P018 are invalid and all formal paired metrics are null. | Both `evidence_integration.json` files plus machine and independent audits. | Artifact verification fails if either status changes or any paired metric becomes non-null. | Protocol-validity evidence, not acceleration evidence. |

## Explicitly unsupported claims

- No valid quality-equivalent prospective full-E2E SGE pair is present.
- The cold-start online reinforcement-learning controller is proposed architecture, not an integrated evaluated system.
- No result supports “first,” “only,” SOTA, production-ready, or general cross-domain performance language.
- Raw diagnostic ratios from invalid or partially realized pairs cannot be promoted to causal SGE speedups.
