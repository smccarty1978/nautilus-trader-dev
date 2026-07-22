# Long Strict Retrain — Deployment Decision Audit

This audit never fits, refits, calibrates, or mutates a model. It reloads the two
frozen `LONG_STRICT_*_v2` artifacts and scores the already frozen monthly
populations for 2024 and 2025. The statistical winner remains
`LONG_STRICT_TOP103_SELECTED`; deployment is decided independently.

Operating regions are frozen at top 1%, 2.5%, 5%, 7.5%, and 10% within each
year/model. Ties are included (`score >= quantile`), so selected counts may
slightly exceed the nominal fraction. Signals/day uses all Chicago dates with at
least one raw NQ bar during `[08:30,15:00)` CT, including zero-candidate days. Precision equals observed flip
rate; expected flip rate means this observed target rate. Lift divides precision
by the full-year positive prevalence. ECE/MCE use ten fixed equal-width
probability bins on [0,1]. Signal overlap compares row keys
`(regime_start_ns, observation_time)` at matched quantiles; rank correlation is
Spearman over the full common yearly population.

2025 is the frozen development population used for selection. 2024 was included
in model fitting and is therefore explicitly an in-sample retrospective
diagnostic, not independent evidence of temporal stability.

Native HGB gain and split counts are extracted read-only from persisted tree
nodes. SHAP uses deterministic 2025 sampling (`random_state=42`, maximum 5,000
rows) and `TreeExplainer`; it is descriptive and cannot alter either model or
threshold. No 2026 data are loaded or scored.

The deployment override requires every criterion: 2025 AUC gain < 0.01 and AP
gain < 0.02; top-5% precision gain < 0.02; top-5% row Jaccard >= 0.60; absolute
2025 ECE difference < 0.01; fewer than two independent evaluation years; feature
count ratio >= 3; runtime-calculation ratio >= 2; and feature-contract ratio >=
3 as the maintenance-burden gate. If any criterion fails, recommend Top103.
