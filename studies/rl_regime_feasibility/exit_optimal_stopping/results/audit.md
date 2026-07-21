# Look-Ahead & Timestamp Audit

**Date:** 2026-07-05
**Scope:** build_exit_atlas.py, build_exit_features.py, build_exit_targets.py, train_models.py, run_replay.py, results/exit_feature_contract.json
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 0
- Note: 2

---

## CHECK 1 — PASS

`build_exit_atlas.py:105` computes `total_pnl_hold_regime = unrealized_pnl_raw + base__pnl_regime` inside `build_positioned_checkpoints()`. Neither `total_pnl_hold_regime` nor `base__pnl_regime` appears in the 57-entry `exit_feature_contract.json` feature list. Both columns flow to `exit_features.parquet` in the `id_cols` block (labeled "Forward labels — for target computation and replay") and are used only as evaluation baselines or model targets, never as model inputs.

---

## CHECK 2 — PASS

`build_exit_atlas.py:73`: `trade_mfe_atr` is computed with `groupby("episode_id")["unrealized_pnl_atr"].transform("cummax")` on a DataFrame already sorted by `seconds_since_entry` — strictly causal. The suffix-max computation (`compute_retrospective_outcomes`, lines 123–135) produces `remaining_mfe_atr` and `max_future_giveback_atr` only; these are explicitly retrospective and are confirmed absent from `exit_feature_contract.json`. None of `remaining_mfe_atr`, `max_future_giveback_atr`, `hold_advantage`, `q_hold`, `v_star`, or `hazard_terminal` appear as feature names in the contract.

---

## CHECK 3 — PASS

`build_exit_targets.py:57`: the backward induction loop is `for i in range(len(df) - 1, -1, -1)`, iterating from the last row to index 0. Each non-terminal step reads `v_star[i+1]` (already computed in the backward pass). `hold_advantage` is added only to the local `df` and saved to `exit_targets.parquet` (line 186). It is absent from `id_cols` and `exit_feats` in `build_exit_features.py`, confirming it is not injected into `exit_features.parquet`.

---

## CHECK 4 — PASS

`train_models.py:208–212`: `train_mask = df["period"] == "train"` and `val_mask = df["period"] == "val"`. All five models (M1–M5) call `train_model(X_tr, y_tr, X_va, y_va, ...)` with `X_tr` and target vectors masked on `train_mask`. `StandardScaler.fit_transform` is called on `X_tr` only; `X_va` uses `.transform`. Thresholds for M1 (line 227), M3 (line 246), and M4 (line 258) are passed `df[val_mask]` and `X_va` exclusively — no train or test data enters threshold selection.

---

## CHECK 5 — PASS

`run_replay.py:63–67` (`build_episode_base`): `first = df.sort_values("seconds_since_entry").groupby("episode_id").first()`, then `regime_pnl = first["total_pnl_hold_regime"]`. This is the entry-time checkpoint value (smallest `seconds_since_entry` per episode), correctly representing the total trade PnL from entry to regime end. `exit_now_pnl` used in `first_signal_per_episode` (line 89) is taken at the checkpoint where the signal first fires; it is `unrealized_pnl_raw - COMMISSION` computed from current checkpoint prices only — no future data involved.

---

## Notes

### [N1] `build_exit_features.py:369–384` — retrospective targets co-located with features in saved parquet

`exit_features.parquet` contains both the 57 contract features and retrospective targets (`remaining_mfe_atr`, `max_future_giveback_atr`, `hold_advantage` is not present but other oracle quantities are). Any future reader who does not filter by the contract could accidentally use these as model inputs. The safeguard is that `train_models.py` loads features strictly via `contract["features"]`. Consider moving retrospective columns to a separate file or asserting their absence from the feature matrix at train time.

### [N2] `run_replay.py:67` — no-signal fallback uses forward-looking `total_pnl_hold_regime`

For model-based policies (E3–E7), episodes where no exit signal fires fall back to `regime_pnl = first["total_pnl_hold_regime"]`, which is a realized (oracle) quantity. This is the same value used by the E0 baseline, so no artificial lift is introduced relative to E0 — the no-signal episodes are treated identically for all policies. The approximation is documented and benign for a research study evaluating policy value, but it means reported EV for partially-signaling policies blends oracle and model outcomes for different subsets of episodes.

---

## Clean Checks

- B1: No `center=True` in any rolling computation
- B2/B4: No `.shift(-N)` or negative-lag operations in feature path; suffix-max is confined to retrospective targets
- C3: Train/val/test split is strictly temporal (date-based cuts, not random)
- C4: Threshold selection uses val period only; test period is never seen during training or threshold selection
- D1: Features in contract match what replay uses (`df[feats]` from same contract JSON)
- H3: No re-entry logic issues; each episode is a single observation

---

*Audit complete. Findings reflect read-only static analysis. Scope: 5 specified files + feature contract JSON.*
