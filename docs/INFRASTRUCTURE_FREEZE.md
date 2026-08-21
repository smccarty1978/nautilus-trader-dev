# Infrastructure Freeze & Regression Evidence Card

## Status: FROZEN

- **Study Factory Layer:** `STUDY_FACTORY_MVP_FROZEN`
- **NT Generic Runner Layer:** `NT_RUNNER_COLLECT_MVP_FROZEN`
- **Acceptance Verdict:** `GENERIC_RUNNER_CANONICAL_PARITY`
- **Parity Status:** `LEGACY_REFERENCE_SEMANTICS_DRIFT_DOCUMENTED`

---

## 1. Frozen Infrastructure Components

| Layer | Component | File Path | Status |
|---|---|---|---|
| **Study Factory** | Scaffolder | `scripts/create_study.py` | FROZEN |
| **Study Factory** | Compiler & Validator | `scripts/compile_study.py` | FROZEN |
| **Study Factory** | Specification Schema | `scripts/study_spec.py` | FROZEN |
| **Execution Runtime** | Causal Bar Loader | `utils/runner/data.py` (`CausalDataLoader`) | FROZEN |
| **Execution Runtime** | Causal Stream Registration | `utils/causal_registration.py` (`add_bars_causal_order`) | FROZEN |
| **Execution Runtime** | Data / Catalog Plan Resolver | `backtests/nt_runtime/data_plan.py` | FROZEN |
| **Execution Runtime** | Engine Builder | `backtests/nt_runtime/engine_builder.py` | FROZEN |
| **Execution Runtime** | Output Manager | `backtests/nt_runtime/output_manager.py` | FROZEN |
| **Execution Runtime** | Telemetry & Profiler | `backtests/nt_runtime/telemetry.py` | FROZEN |
| **Execution Runtime** | Generic Collect Runner | `backtests/run_nt_study.py` | FROZEN |
| **Strategy Scaffolding** | Event-Loop Collect Strategy | `strategies/flip_prediction_collector.py` | FROZEN |
| **Quality & Audit** | Research Preflight Entrypoint | `scripts/research_preflight.py` | FROZEN |
| **Quality & Audit** | Equivalence Validator | `scripts/check_collect_equivalence.py` | FROZEN |

---

## 2. Frozen Feature Contract & Ordered Hashes

- **Feature Set:** `F3_top25_gbt_v1` (25 Model Features)
- **Feature Count:** `25`
- **Ordered JSON SHA-256 Hash:** `8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299`

---

## 3. Golden Reference Fixture & Parity Metrics (2025-03-03)

- **Reference Artifact:** `studies/reconstructed_long_rth_strict_retrain/reference_collection/reference_candidates_20250303.parquet`
- **Candidate Artifact:** `runs/20260814_233548_reconstructed_long_rth_strict_retrain_day/collection/candidates.parquet`
- **Equivalence Card:** `runs/20260814_233548_reconstructed_long_rth_strict_retrain_day/equivalence_card.json`

### Population Metrics
- **Reference Population:** `1,087`
- **Candidate Population:** `1,089`
- **Common Population:** `1,087`
- **Reference Coverage:** `100.00%` (1,087 / 1,087)
- **Jaccard Overlap:** `99.82%` (1,087 / 1,089)
- **Missing Candidates (NT):** `0`
- **Extra Candidates (NT):** `2`
- **Unexplained Divergence Classes:** `0`

---

## 4. Documented Legacy Semantic Differences

1. **Coincident Bar Dispatch Ordering (`10:48:00 CT`, `ts = 1741020480000000000`)**:
   - NT event loop processes the completed 1s bar ending at 10:48:00 CT before the coincident 1m bar.
   - Prevailing bullish regime is active during 1s evaluation $\rightarrow$ checkpoint 263 qualifies and emits.
   - Coincident 1m bar immediately follows and flips EMA to bearish.
   - *Classification:* `regime_timing` (NT adheres strictly to real-time event ordering).

2. **Threshold Crossing Baseline Offset (`11:37:05 CT`, `ts = 1741023425000000000`)**:
   - NT calculates $MFE = 1.0013 \ge 1.0$ at 11:37:05 CT, qualifying for entry.
   - Legacy offline script had a 0.25 pt (1 tick) ATR baseline difference at regime start ($19.36$ vs $19.34$), calculating $MFE = 0.99948 < 1.0$ at 11:37:05 CT and delaying entry by 5s to 11:37:10 CT.
   - *Classification:* `reference_semantics_drift`.

3. **Session Open Volume Accumulation**:
   - Legacy script included 08:30:00 open auction / uncrossing volume; NT event loop accumulates from completed 1s bar ending at 08:30:01 CT ($\Delta \approx 296$ contracts out of 554,800, a $99.988\%$ agreement ratio).
   - *Classification:* `reference_semantics_drift`.

---

## 5. Canonical Research Workflow

```text
Research Question
       ↓
  study.yaml
       ↓
create_study.py
       ↓
compile_study.py
       ↓
research_preflight.py
       ↓
run_nt_study.py --mode collect
       ↓
NT BacktestEngine Event Loop
       ↓
Causal Dataset Parquet
       ↓
Model Training & Evaluation
       ↓
Results Summary & Interpretation
```
