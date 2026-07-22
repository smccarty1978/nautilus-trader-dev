# Pre-Flip Semantic Renaming Migration Plan

1. Preserve every frozen artifact directory, binary, feature order, class order, threshold, and historical manifest.
2. Introduce `model_semantics_registry.json` as the semantic identity layer and `model_registry.py` as the compatibility resolver.
3. Deprecate legacy aliases. Keep them resolvable while emitting `DeprecationWarning`.
4. Treat `long` and `short` only as explicit trade-direction metadata; never as primary model identities.
5. Label the current Bullish Fade lineage unvalidated until a separate causal rebuild and target/direction reliability study clears it.
6. Retain Bearish Fade Top103 GBT V2 as production; retain other Bearish Fade artifacts as challenger/reference lineage.
7. Update active study reports, loaders, logs, CLI help, and configs opportunistically without rewriting immutable historical provenance.
8. Require `prediction_reproduction_report.json` to show `max_abs_prediction_diff == 0.0` for every alias before removing any legacy name.

The repository-required `repo-scout` and `contract-checker` roles were invoked but could not execute because their configured models were unsupported by the active account. Equivalent discovery and contract review were performed in the main session; this limitation does not relax prediction or causal audit gates.

