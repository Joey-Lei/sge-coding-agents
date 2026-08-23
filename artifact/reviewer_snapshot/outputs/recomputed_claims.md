# Offline recomputation summary

All values below were recomputed from the packaged derived evidence without network, model, or evaluator calls.

- Historical same-trace replay: 10 clean Web-Bench traces; aggregate unbounded/P=2/P=4/P=8 list ceiling = 4.2690x / 1.9836x / 3.4058x / 4.2690x; case median/max unbounded ceiling = 5.2293x / 6.4227x.
- Exact-duration action DAGs: 9 across 6 repositories; P=4 mean/median/max structural ceiling = 1.2138x / 1.1770x / 1.5297x.
- Duration-blind admission: 188 windows across 4 physical repositories; Spearman = 0.9898, MAE = 0.0852x, MAPE = 5.65%.
- At 1.10x: rejected 131/135 observed-low windows and admitted 52/53 observed-high windows.
- Nontrivial sensitivity: 58 windows after removing 130 joint-unit windows; Spearman = 0.7649, MAE = 0.2762x, MAPE = 18.32%.
- Strict paired canaries: P007 and P018 are invalid and all formal paired metrics remain null.

These are structural, retrospective, local-mechanism, or historical functional observations. They do not establish a prospective end-to-end alpha_SGE.
