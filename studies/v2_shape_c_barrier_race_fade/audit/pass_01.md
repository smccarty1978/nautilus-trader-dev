# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-02 · **Scope** `compiled_plan.json`, `study.yaml`, `research_workflow/host/{mux,strategy,outcomes}.py`,
`research_workflow/grammar/compiler.py` (score-mode compilation), `research_workflow/model_artifacts.py`,
`studies/model_registry/a9878a0315768882e490721dae261b2c5d666ae9f642963b2980630d359058a1.json`
**Scope hash (audited composite)** `b7792ad8515f0dd6f1f74a7546db9a9c86fba2ae90345cf27498600ac384b443`
**Lint** preflight CLEAR (0 critical/warning); readiness overall PASS · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 · Note: 2

## Checks performed
- **No barrier/label column in candidates (extra Q1).** `compiled_plan.json:columns.features` is the 13-feature causal surface only; `target_tp1_sl{0_5,1_0,1_5}_{label,disposition,censor_reason,resolution_seconds}` and `target_flip_within_horizon`/`disposition`/etc. exist only under `columns.observation` (lines 393-419). `preflight.json.leaked_outcome_columns=[]` confirms independently.
- **`relation: fade` (H1/H4).** `direction_sign: -1` in the compiled outcome (line 843) — `LabelOutcomeKernel.open()` computes `p.direction = int(direction) * direction_sign`, so a `regime_1m.dir=-1` (bearish) candidate races barriers in the `+1` (long) direction, matching `model.models[].subset.regime_direction:-1 → name:LONG_*`. Consistent, traced end to end.
- **ATR `through_decision_ts` (given as sealed, not re-derived).** Traced the mechanism anyway: `_emit_candidate` defers `kernel.open()` via `self._deferred_opens`; `_flush_deferred_opens(before_ts)` resolves `atr = resolve(atr_ref, epoch)` only once a **later** bar (`ts_init > T`) arrives, and only reads the live `regime_1m.atr` at that moment — never a bar with `ts_init > T`. This bounds the ATR strictly to state as of `T` inclusive (the coincident 1m close), never beyond — matches the described target-authority semantics exactly.
- **Barrier resolution (H1-H4).** `on_bar` uses `bar.high/low` for touches (H1), entry price = next bar's `open` (H4), entry_ts = that bar's `ts_event` (open time, H2 consistent with 1s-resolution monitoring since `outcome_stream` defaults to the 1s epoch stream). `same_bar_rule: ambiguous_censor` → simultaneous favorable+adverse touch is `CENSORED`/`AMBIGUOUS_SAME_BAR_TOUCH`, not silently resolved either way — the conservative choice.
- **Six frozen models (extra Q2).** `model.mode: score` compiles each `m.label` against `known_labels = {label_column} ∪ {arm.prefix_label}` (`compiler.py:878-883`) — fails closed if a model is bound to a non-existent label, but does **not** itself check each model's input feature list against `columns.features` at compile time; that binding happens at score time via `score_preserved_model(...)` selecting `frame[rec["ordered_model_inputs"]]` from the model-registry record. Spot-checked one of the six (`a9878a03...`, `LONG_SL0_5_C22_fold_2022`): `ordered_model_inputs` is exactly the 13-feature causal surface, same names/order as `columns.features` — no observation/label column present. Did not exhaustively re-verify the other five (same target authority `21d598a8...`, same architecture family) within budget.
- **Chronology (C3).** train=[2021], dev=[2022] (OOS-gated), prohibited=[2023-2026], smoke=2021-01-05 — matches required table.

## Warnings
### [A4/B9] `research_workflow/host/mux.py:159-192` — same 1m-context causal-order reliance as the sibling Shape A study
**Failure path:** identical closure/composite to `v2_shape_a_flip_180s` (`b7792ad8515f...`): `nq_1m` is `role: "execution"` (default), so `assert_epoch_visibility` permits it up to and including `T` rather than enforcing `strictly_before`; correctness for `prior_1m/5m_regime_*`, `ema_slope`, and the `excursion`/qualify gate at the ~1/12 of epochs landing on a 1m boundary depends entirely on `add_bars_causal_order` continuing to be called correctly in `backtests/nt_runtime/engine_builder.py:240` (confirmed present). `lifecycle_v2.readiness()` has no bounded real-sample callback-order re-proof for this plan. Not re-raised in detail — see `v2_shape_a_flip_180s/audit/pass_01.md` for the full trace; identical mechanism, identical risk.
**Smallest fix:** same as Shape A — add a bounded `verify_callback_causal_order` readiness check, or declare `nq_1m`/`nq_5m` `role: context`.

## Notes
- `reuse_status: PERMITTED` / `scientific_status: UNASSESSED` on the reused model records is a model-integrity/governance declaration, not a causal question.
- Model-input-surface conformance is enforced by column selection at score time (`frame[ordered_model_inputs]`), not by a compile-time cross-check against `columns.features`; benign here (verified inputs are clean) but structurally would not fail closed if a future registry record listed a leaked column name.

## Referred to contract-checker
- Frozen-model reuse governance (`reuse_status`/`scientific_status`/target-authority `21d598a8...` provenance) — contract/model-integrity scope, not causal.

## Clean checks
A1-A5, B1-B7, B10, C1-C3, F1-F4, G1-G4, H1-H4 clean.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_c_barrier_race_fade", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "b7792ad8515f0dd6f1f74a7546db9a9c86fba2ae90345cf27498600ac384b443", "critical": 0, "warning": 1, "note": 2}
<!-- AUDIT_SUMMARY_V2_END -->
