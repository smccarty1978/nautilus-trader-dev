# ML 5m Flip Prediction — Pipeline Spec (Implementation Doc)

> Companion to `concrete_pipeline_spec_feature_parity_nt.md` (the high-level
> spec). This doc tracks the actual implementation of the four-stage
> pipeline + parity harness for the v1 feature contract.

**Date:** April 2026
**Status:** Phase 1.1 complete (contract frozen). Phase 1.2 in progress.

---

## Pipeline stages

```
┌──────────────────────────────────────────────────────────────────────┐
│  Stage A: Dataset Builder                                            │
│  studies/1m_delayed_checkpoint_context/collector.py (v3)             │
│  studies/ml_5m_flip_prediction/build_dataset.py                      │
│  → ml_5m_flip_prediction_dataset.parquet                             │
├──────────────────────────────────────────────────────────────────────┤
│  Stage B: Trainer                                                    │
│  studies/ml_5m_flip_prediction/save_model_for_realtime.py            │
│  studies/ml_5m_flip_prediction/gen_approved_signals_walkforward.py   │
│  → models/ml_5m_flip/{model,feature_cols,threshold,                  │
│                       feature_contract,training_manifest}_YYYY       │
├──────────────────────────────────────────────────────────────────────┤
│  Stage C: Offline Scorer                                             │
│  studies/ml_5m_flip_prediction/build_2026_dataset_and_approve.py     │
│  → approved_signals_YYYY_*.parquet                                   │
│  → preds_YYYY_walk_forward.parquet                                   │
├──────────────────────────────────────────────────────────────────────┤
│  Stage D: NT Runtime Scorer / Executor                               │
│  backtests/realtime_ml_filtered_strategy.py                          │
│  Modes: execute | shadow | parity                                    │
│  → trades_YYYY_realtime_ml.parquet                                   │
│  → parity_capture_YYYY.parquet (parity mode)                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Locked-in design decisions (April 2026)

1. **Feature contract**: `models/ml_5m_flip/feature_contract_v1.json` —
   100 features, frozen as v1. Any change to names/definitions/null-policy/
   snap-timing requires bump to v2.
2. **Native technology**: Cython, in a separate package
   (`nt_features_native/`). Phase 2 work, not in NT core.
3. **Phased delivery**: Phase 1 = freeze contract + parity harness + fix
   Python realtime + prove parity. Phase 2 = move hot-path math to native.
4. **Strategy modes**: one strategy class with `mode = execute | shadow |
   parity`.
5. **Threshold rule**: fixed at saved value from training artifact;
   retrained annually.
6. **Decision-time semantics**:
   - `signal_time` = bar+1 close timestamp (ts_event of bar+1 + 60s)
   - `decision_time` = `signal_time + decision_checkpoint_s × 1e9`
   - `decision_fill_time` = `decision_time + 30s`
   - root features → snap at `signal_time` (in `_check_confirmation`)
   - `_T` features → snap at `decision_time` (in `_snap_checkpoint`)

---

## Parity tolerance categories

| Category | Tolerance | Used for |
|---|---|---|
| `bit_exact` | 1e-12 | Integer counts, regime states, flags |
| `tight` | 1e-9 | Single-step arithmetic (price ratios, ATR-norms) |
| `loose` | 1e-6 | EMA/SMA/accumulated stats |
| `looser` | 1e-4 | Compound ratios of accumulated stats |

Defaults are per-feature; can be overridden in the contract.

---

## Phase 1 — to-do checklist

- [x] **1.1** Freeze feature contract v1
  - `models/ml_5m_flip/feature_contract_v1.json` (100 entries, signed off)
- [ ] **1.2** Build parity harness
  - `studies/ml_5m_flip_prediction/parity/`
  - Sample 100 random + 20 edge-case events
  - Export offline rows / capture runtime rows / diff
- [ ] **1.3** Fix Python realtime reference
  - `backtests/realtime_ml_filtered_strategy.py` predictions ~0.93 → debug
    feature mapping; hit feature-parity tolerances on contract
- [ ] **1.4** Pass feature/score/decision parity
  - 100% agreement on sampled events
  - Reports: `feature_parity_report_2025.json`, `score_*`, `decision_*`

## Phase 2 — to-do checklist (deferred until Phase 1 passes)

- [ ] **2.1** Build `nt_features_native/` package skeleton (Cython)
- [ ] **2.2** Port indicator stack (RegimeState, EMA/SMA helpers, vol counters)
- [ ] **2.3** Port aggregation (1s→30s, 1m→5m)
- [ ] **2.4** Port snapshot assembler (returns feature struct)
- [ ] **2.5** Re-validate contract parity using native path
- [ ] **2.6** Measure runtime improvement (target: −80% Python time)

---

## Required pre-deployment checks

Pipeline is production-ready iff ALL true:

1. Feature parity passes (per-feature tolerance per contract)
2. Score parity passes (≤ 1e-6 absolute diff)
3. Decision parity passes (100% agreement)
4. Runtime inference mode matches approval-list mode economically
5. No unresolved NaN/default mismatches
6. Year-by-year backtests pass in runtime mode (2022-2026 OOS)
7. Model artifact loading is versioned and reproducible

---

## Versioning policy

Trigger for new contract version (v2):
- New feature added or removed
- Existing feature's name changes
- Feature definition changes (formula, source data, window)
- Null/default policy changes
- Snap-call-order anchor changes

NOT a trigger:
- Pure code refactor with byte-identical outputs
- Adding metadata/notes to existing entries
- Adding new tolerance categories that don't change existing assignments

When contract version changes:
- Save as `feature_contract_v2.json`
- Models trained against v1 remain pinned to v1 (don't overwrite manifests)
- New training runs reference v2 in `training_manifest_YYYY.json`
- Document delta in `models/ml_5m_flip/CONTRACT_CHANGELOG.md`
