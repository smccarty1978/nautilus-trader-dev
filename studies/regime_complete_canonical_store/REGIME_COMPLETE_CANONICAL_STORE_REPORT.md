# Regime-Complete Canonical Store — Report

## 1. Executive summary

| Question | Answer |
|---|---|
| Every regime represented | 137,673 regime rows |
| Every true scoring checkpoint | 12,156,904 score rows |
| Complete one-second paths | 61,543,945 path rows |
| Prior 5,836 population reproduced | PASS |

## 2. Frozen contract

Frozen in `REGIME_COMPLETE_CANONICAL_STORE_SPEC.md`; decisions and the options rejected are in `DECISIONS.md`. Regime definition, score cadence, timestamp semantics, path boundaries, domain behavior, threshold provenance, censoring, and ID construction are all fixed there.

## 3. Schema

| Dataset | File | Rows | Columns | Size |
|---|---|---|---|---|
| regimes | canonical_regimes_all.parquet | 137,673 | 32 | 0.01 GB |
| scores | canonical_regime_scores_all.parquet | 12,156,904 | 182 | 3.78 GB |
| paths | canonical_regime_paths_all.parquet | 61,543,945 | 34 | 1.35 GB |
| missing | canonical_missing_dispatch_all.parquet | 19,396,376 | 3 | 0.09 GB |

## 4. Coverage

| Metric | Value |
|---|---|
| Regimes | 137,673 |
| Established | 56,234 |
| Never established | 81,439 |
| Complete paths | 137,619 |
| Censored paths | 54 |
| Duplicate regime IDs | 0 |
| Consecutive same-direction regimes | 0 |

By year:

| Year | Regimes |
|---|---|
| 2021 | 27,825 |
| 2022 | 27,138 |
| 2023 | 28,029 |
| 2024 | 27,515 |
| 2025 | 27,166 |

## 5. Threshold-contract audit

| Model | Percentile | Threshold | Status |
|---|---|---|---|
| BULLISH_STRICT_top25_gbt_v2 | top_10 | 0.43167249785595935 | AVAILABLE_AND_FROZEN |
| BULLISH_STRICT_top25_gbt_v2 | top_2_5 | 0.5697449423968936 | AVAILABLE_AND_FROZEN |
| BULLISH_STRICT_top25_gbt_v2 | top_5 | 0.5067081427626979 | AVAILABLE_AND_FROZEN |
| BULLISH_STRICT_top25_gbt_v2 | top_0_5 | 0.6886333180788179 | RECONSTRUCTED |
| BULLISH_STRICT_top25_gbt_v2 | top_1 | 0.6412279079940403 | RECONSTRUCTED |
| BULLISH_STRICT_top25_gbt_v2 | top_20 | 0.34374423771129053 | RECONSTRUCTED |
| LONG_STRICT_top25_gbt_v2 | top_2_5 | 0.5641320087327389 | AVAILABLE_AND_FROZEN |
| LONG_STRICT_top25_gbt_v2 | top_5 | 0.5084619230529974 | AVAILABLE_AND_FROZEN |
| LONG_STRICT_top25_gbt_v2 | top_0_5 | 0.6706161496105166 | RECONSTRUCTED |
| LONG_STRICT_top25_gbt_v2 | top_1 | 0.6306416772425602 | RECONSTRUCTED |
| LONG_STRICT_top25_gbt_v2 | top_10 | 0.44559149246408103 | RECONSTRUCTED |
| LONG_STRICT_top25_gbt_v2 | top_20 | 0.3745119841718754 | RECONSTRUCTED |

> Both calibration populations are calendar-2025 and overlap the 2021–2025 evaluation window. Results using these thresholds are descriptive and must not be represented as threshold-out-of-sample for 2025.

## 6. Backward reproduction

| Metric | Value |
|---|---|
| Accepted trades | 5,836 |
| Regenerated trades | 5,836 |
| Matched | 5,836 |
| Missing | 0 |
| Extra | 0 |
| Duplicated | 0 |
| Value mismatches | {} |
| Verdict | PASS |

## 7. Capability demonstrations

| Population | Candidates | Regimes | Multi-candidate |
|---|---|---|---|
| first_top_20 | 11,615 | 11,615 | 0 |
| first_top_10 | 9,206 | 9,206 | 0 |
| first_top_5 | 7,450 | 7,450 | 0 |
| first_top_2_5 | 5,836 | 5,836 | 0 |
| first_top_1 | 3,415 | 3,415 | 0 |
| first_top_0_5 | 1,786 | 1,786 | 0 |
| crossings_top_5 | 28,784 | 7,450 | 5,346 |
| crossings_top_2_5 | 17,390 | 5,836 | 3,715 |
| crossings_top_1 | 7,642 | 3,415 | 1,763 |
| opposing_warning_top_10 | 15,106 | 15,106 | 0 |
| opposing_warning_top_5 | 15,079 | 15,079 | 0 |
| opposing_warning_top_2_5 | 14,995 | 14,995 | 0 |

These are data-capability demonstrations. No population is ranked economically and no policy is recommended.

### Re-entry capability

```json
{
  "percentile_label": "top_2_5",
  "hypothetical_stop_atr": 1.0,
  "regimes_with_candidates": 5836,
  "regimes_with_one_candidate": 2121,
  "regimes_with_multiple_candidates": 3715,
  "median_candidates_per_regime": 2.0,
  "max_candidate_sequence_count": 36,
  "regimes_with_a_post_first_candidate": 3715,
  "regimes_with_path_rows_after_first_candidate": 5697,
  "median_path_rows_after_first_candidate": 125.0
}
```

## 8. Causal audit

The strongest causal evidence is equivalence against the accepted artifact: after widening the collector to the full session, every RTH score row still carries exactly the accepted values.

| Metric | Value |
|---|---|
| Accepted rows | 95,054 |
| Rebuilt rows | 95,054 |
| Columns compared | 160 |
| Missing | 0 |
| Extra | 0 |
| Mismatched columns | 0 |

## 9. Independent audit

| Metric | Value |
|---|---|
| Regimes sampled | 125 |
| Independently derived flips | 172,942 |
| Unexplained mismatches | 0 |
| Verdict | PASS |

### Regime-count reconciliation

| Component | Count |
|---|---|
| Accepted flips, deduplicated | 137,881 |
| — outside the 2021–2025 window (2020 warmup) | 199 |
| — cold-start warmup artifacts | 9 |
| Store regimes | 137,673 |
| In store, not in accepted | 0 |
| **Unexplained** | **0** |

Every difference is explained. Flips outside the window come from the 2021-01 partition's 2020 warmup. The remainder are cold-start convergence artifacts recorded during a later partition's warmup; none appear in an independently derived continuous regime stream, so the store is correct to exclude them.

## 10. Limitations

- **Threshold provenance.** Both frozen calibration populations are calendar-2025 and overlap the 2021–2025 evaluation window. Every threshold row carries `overlaps_evaluation_window = true`. Results using these thresholds are descriptive and must not be represented as threshold-out-of-sample for 2025.
- **ETH scores are almost entirely absent by contract.** Three of the 25 frozen features are RTH accumulators that return null once the session ends, so the frozen adapters decline to score outside RTH. ETH checkpoints, regimes, and paths are retained in full, but ETH carries no usable model probability and is never in-domain.
- **Model coverage is unchanged.** This store adds no model, retrains nothing, and changes no feature. Out-of-domain and exploratory score semantics are inherited from the accepted artifacts.
- **Feature snapshots are inline, not a separate long table** (DECISION-5). Provenance is preserved via the per-model feature vector hashes; the tradeoff is documented rather than silent.
- **58 path rows of 61,543,945 carry a null `regime_sequence_number`.** They belong to a single regime that began during warmup before 2021-01, so its regime row falls outside the build window while its path rows fall inside. This affects the first regime of the corpus only.
- **2026 is absent by design**, reserved for runtime out-of-sample validation. No calibration or collection touched it.
- **Regime count differs from the accepted flip file by 208, fully explained** (199 outside the window, 9 cold-start warmup artifacts). No unexplained difference remains.

## 11. Verdict

```text
REGIME-COMPLETE STORE ACCEPTED
```

| Criterion | Status |
|---|---|
| Backward-parity status | PASS |
| Causal-audit status | PASS |
| Population-completeness status | RECONCILED |
