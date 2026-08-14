# Offline recomputation summary

All values below were recomputed from the packaged derived evidence without network, model, or evaluator calls.

- Exact-duration action DAGs: 9 across 6 repositories; P=4 mean/median/max structural ceiling = 1.2138x / 1.1770x / 1.5297x.
- Duration-blind admission: 188 windows across 4 held-out repositories; Spearman = 0.9898, MAE = 0.0852x, MAPE = 5.65%.
- At 1.10x: rejected 131/135 observed-low windows and admitted 52/53 observed-high windows.
- Nontrivial sensitivity: 58 windows after removing 130 joint-unit windows; Spearman = 0.7649, MAE = 0.2762x, MAPE = 18.32%.
- Strict paired canaries: P007 and P018 are invalid and all formal paired metrics remain null.

These are structural, retrospective, local-mechanism, or historical functional observations. They do not establish a prospective end-to-end alpha_SGE.
