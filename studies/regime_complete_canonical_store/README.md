# Regime-Complete Canonical Store

A reusable canonical research substrate: **every** eligible regime, **every** true
model-scoring checkpoint, and the **complete** one-second market path — with no
entry threshold, stop, exit, confirmation requirement, or trade-selection policy
baked into collection.

The collection layer records observable state. The analysis layer creates trades.

## Status

| Phase | State |
|---|---|
| 0 — discovery, contract freeze, threshold contracts | **complete** |
| 1 — micro fixture | **complete** |
| 2 — bounded pilot (2025-03) | **complete** |
| 3 — full 2021–2025 build | **complete** — 60/60 partitions, 0 failed |
| 4 — backward parity vs 5,836 accepted trades | **PASS** — 0 unexplained |
| 5 — independent audit | **PASS** — 125 regimes, 0 mismatches |

**Verdict: REGIME-COMPLETE STORE ACCEPTED.** See
`REGIME_COMPLETE_CANONICAL_STORE_REPORT.md`.

## Documents

| File | Purpose |
|---|---|
| `REGIME_COMPLETE_CANONICAL_STORE_SPEC.md` | The frozen contract. Read this first. |
| `DECISIONS.md` | Six decisions, with the options rejected and why. |
| `REGIME_COMPLETE_CANONICAL_STORE_REPORT.md` | Written at Phase 5. |

## What Phase 0 established

- The score population is **already** global and threshold-free: 5,665,103 true 5s
  checkpoints with both models, domain flags, and all 25 feature values inlined per
  model. This store extends it; it does not replace it.
- The regime engine has **no flip/confirmation split** — the sticky V_A flip *is*
  the confirmation. Regimes tile time and strictly alternate, so the four requested
  lifecycle events are recoverable by `regime_sequence_number` arithmetic. See
  DECISION-2.
- **All six percentiles are now materialized for both models.** Both frozen
  calibration populations reconstruct exactly and reproduce every previously-frozen
  threshold bit-exactly. See DECISION-3.

## The threshold contracts (built)

```bash
python -m studies.regime_complete_canonical_store.implementation.build_threshold_contracts
python -m pytest studies/regime_complete_canonical_store/tests/test_threshold_contracts.py -q
```

Writes `data/canonical/regime_complete_v1/canonical_model_threshold_contracts.parquet`
(12 rows) and `results/threshold_availability_report.json`.

| Percentile | Bullish | Bearish |
|---|---|---|
| Top 20% | 0.34374423771129053 | 0.3745119841718754 |
| Top 10% | **0.43167249785595935** ✔ | 0.44559149246408103 |
| Top 5% | **0.5067081427626979** ✔ | **0.5084619230529974** ✔ |
| Top 2.5% | **0.5697449423968936** ✔ | **0.5641320087327389** ✔ |
| Top 1% | 0.6412279079940403 | 0.6306416772425602 |
| Top 0.5% | 0.6886333180788179 | 0.6706161496105166 |

✔ = reproduced bit-exactly from the frozen upstream artifact. The builder **aborts**
if any frozen value fails to reproduce. Bearish Top-10, previously unavailable, is
now materialized.

> **Disclosure — carried on every row.** Both calibration populations are
> calendar-2025 and overlap the 2021–2025 evaluation window. Results using these
> thresholds are descriptive and must not be represented as threshold-out-of-sample
> for 2025. Inherits `full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`.

## Built outputs

```text
data/canonical/regime_complete_v1/
  canonical_regimes_all.parquet                    137,673 rows    0.01 GB
  canonical_regime_scores_all.parquet           12,156,904 rows    3.78 GB
  canonical_regime_paths_all.parquet            61,543,945 rows    1.35 GB
  canonical_missing_dispatch_all.parquet        19,396,376 rows    0.09 GB
  canonical_model_threshold_contracts.parquet           12 rows
  canonical_collection_manifest.json
```

Scores and paths land **exactly** on the counts measured independently from the
catalog before this code existed (12,156,904 5s dispatch slots; 61,543,945 1s
bars), and `scores + missing` equals the full 5s grid.

Development writes to `regime_complete_v1/`. The accepted `full_trade_path_builder/`
artifacts are never overwritten — they are the backward-parity reference.

## Acceptance question

> Does the collector retain every eligible regime, every true causal score
> checkpoint, and the complete reusable one-second regime path, while reproducing
> the existing **5,836**-trade selected population with no unexplained extra,
> missing, duplicated, retimed, or value-mismatched candidates?

## Scale (measured, 2021–2025, NQ)

| Quantity | Value |
|---|---|
| 1s bars | 61,543,945 |
| 5s dispatch checkpoints, full session | 12,156,904 |
| 5s dispatch checkpoints, RTH only (today) | 5,665,103 |
| Unique confirmed flips (regimes) | 137,881 |
| Regime duration: min / median / mean / max | 60s / 540s / 1,146s / 342,240s |
| Regimes under 120s (can never establish) | 2.0% |
