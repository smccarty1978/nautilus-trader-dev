# Look-Ahead & Timestamp Audit

**Date:** 2026-07-22T00:00:00-05:00  
**Scope:** semantic migration registry, compatibility resolver, frozen-catalog/binding metadata, prediction-reproduction evidence, and the named pre-flip reliability reports/scripts  
**Scope hash:** `637d3de01ba97371f7cfcc1e52885b8f1337cd7a21a3192b5d8a15fa19184ab6`  
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 0
- Note: 1

## Critical findings

None.

## Warnings

None.

## Notes

### [A1] `studies/pre_flip_signal_reliability_top103/implementation/collect_and_evaluate.py:61-68,138-145,175-178` — raw-bar timestamp convention remains an upstream provenance assumption

The path evaluator indexes raw bars by `ts_event` and advances one row beyond the observation timestamp. This is causally conservative for the documented open-labelled one-second source and prevents use of the bar beginning at the observation. The loader validates ordering and OHLCV integrity but does not independently encode the source labelling convention. This is not a demonstrated look-ahead defect in the frozen migration scope.

## Remediation verification

- `legacy_long_model` now resolves to `bearish_fade_top103_gbt_v2` in both `legacy_name_mapping.json:3` and `model_semantics_registry.json:143-147`.
- Every standalone mapping entry resolves to the same runtime alias through the executable registry; no duplicate accepted name exists.
- `reproduce_predictions.py:46-56` checks every legacy name and each runtime alias against its canonical artifact path.
- `prediction_reproduction_report.json:1-94` records all aliases and reports bit-exact scores with maximum absolute difference `0.0` for all seven frozen artifacts.
- The threshold hash at `model_binding.json:20` equals the actual SHA-256 of `config/frozen_thresholds.json`: `f5a4a62deccc504c838b257b93bfd89f7475be39db70271bb4c383ad54ad8e01`.

## Clean checks

- Candidate direction is internally consistent: Bullish Fade uses prevailing `+1`, bearish-flip positive class, and short trade direction; Bearish Fade uses prevailing `-1`, bullish-flip positive class, and long trade direction.
- Positive-score polarity is consistently `predict_proba(... )[:, 1]`, matching frozen class order `[0, 1]` and each declared flip target.
- Frozen model SHA-256 values for all seven registry records match the declared artifact hashes.
- Bearish Fade Top103 V2 production status agrees across the strict retrain manifest, freeze manifest, production catalog, semantic registry, and report language.
- Bullish Fade Top25 remains explicitly not production-valid / requiring target-and-direction re-audit.
- No model binary, fitted weight, feature list/order, class order, score threshold, or prediction changed in the migration evidence.
- Top103 scores use the frozen 103-column order; the checkpoint merge is one-to-one and rejects key mismatch or attrition.
- RTH conversion is explicit, timezone-aware, and DST-safe through `America/Chicago`.
- Flip-boundary PnL is disclosed as a non-executable last-close mark rather than a fill.

## Forced compliance matrix

| Rule | Status | Basis |
|---|---|---|
| A1 | NOTE | Open-labelled `ts_event` path begins strictly after observation; labelling is documented upstream. |
| A2 | N/A | No NT catalog construction in scope. |
| A3 | N/A | No NT strategy callback in scope. |
| A4 | N/A | No timer callback in scope. |
| A5 | PASS | UTC-to-Chicago conversion is timezone-aware; no resampling. |
| B1 | PASS | No centered rolling computation in migration/scoring path. |
| B2 | PASS | Frozen features are consumed without recomputation. |
| B3 | N/A | No recursive feature computation in scope. |
| B4 | PASS | No negative-lag feature operation. |
| B5 | PASS | No fill operation in feature path. |
| B6 | PASS | Top103 scores merge one-to-one on exact checkpoint keys. |
| B7 | PASS | Frozen fitted models are loaded without refitting. |
| C1 | PASS | Future flip timestamps appear only in outcome/path reporting. |
| C2 | PASS | Scores attach to exact regime/checkpoint keys. |
| C3 | N/A | No training or split in scope. |
| C4 | N/A | No walk-forward fitting in scope. |
| D1 | N/A | No live strategy feature implementation in scope. |
| D2 | N/A | No model cascade in scope. |
| D3 | PASS | All frozen artifacts reproduce bit-exact scores; all aliases resolve to the same artifact. |
| D4 | PASS | Alias mapping, feature ordering, class index, artifact hashes, and threshold hash are deterministic. |
| E1 | N/A | No subscription configuration. |
| E2 | N/A | No BarType construction. |
| E3 | N/A | No venue/fill model. |
| E4 | N/A | No executable order submission. |
| E5 | N/A | No live indicators. |
| F1 | PASS | Candidate semantics use observation/close-time contract; raw path begins after signal second. |
| F2 | PASS | Regime grouping is explicit by `regime_start_ns`. |
| F3 | PASS | UTC and Chicago conversion are explicit. |
| F4 | PASS | Named timezone conversion handles DST. |
| G1 | N/A | Contract-roll handling is upstream and unchanged. |
| G2 | PASS | No forward filling; observed bar timestamps are searched directly. |
| G3 | N/A | No resampling. |
| G4 | NOTE | Zero-volume/single-tick bars are intentionally retained for exact historical parity. |
| H1 | PASS | Excursion geometry uses high/low; close is only the disclosed non-fill mark. |
| H2 | PASS | Offline path uses one-second source bars. |
| H3 | N/A | Reliability checkpoints are not an executable re-entry simulator. |
| H4 | N/A | No executable bracket fills are claimed. |

---

*Re-audit complete. Findings reflect read-only static analysis. No backtest or study pipeline was executed.*
