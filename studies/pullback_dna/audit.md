# Pullback DNA Collector — Lookahead Audit

**Date:** 2026-06-25  
**Scope:** `studies/pullback_dna/collector.py`, `studies/pullback_dna/run_collector.py`  
**Status:** PASS (0 CRITICAL, 0 WARNING after fixes)

## Audit round 1 (subagent)
- 0 CRITICAL
- 3 WARNING: W-FLIP (MFE/MAE direction corruption), D1 (hC gate), W-FLIP2 (reduce_only race)
- 3 NOTE: ts_event vs ts_init, variable name, shared bars list

## Resolutions

**W-FLIP → FIXED**  
`on_bar` now uses `self._obs["direction"]` (snapshotted at entry fill) instead of `self._dir`
for all MFE/MAE and retracement calculations. Immune to direction change caused by regime flip.

**D1 → DISMISSED**  
Both the reference strategy and the collector allow pullbacks beyond bar 28 — identical behavior.
Late-regime pullbacks are intentionally included in the atlas (observational study, not deployment).

**W-FLIP2 → DISMISSED**  
Impossible with `bar_execution=True` + 1s bars. Entry fills 1 second after submission;
regime flip fires at the next 1m close (≥59 seconds later). `_in_position = True` by then.
No reduce_only rejection can occur.

**NOTE-A → FIXED**  
Checkpoint timestamps now use `int(bar.ts_init)` (bar close time) instead of `ts_event`.

**NOTE-B → FIXED**  
Variable renamed `e8 → e7` to reflect that `bars_in_regime=8` is bar k=7.

**NOTE-C → ACCEPTED**  
Same `bars_1s` list passed to three engine runs. NT `add_data` does not mutate input.
Risk is theoretical; accepted for runtime efficiency.

## Timestamp convention
- Aggregator fed with `int(bar.ts_init)` — matches capsule builder convention ✓
- No ts_init_delta needed for 1s bars ✓
- `regime_start_ts = bucket.close_ts` — matches hC mapping key convention ✓
- `hC_velocity = hC(k=8) - hC(k=7)` from walk-forward KNN (IS < test-year) ✓
