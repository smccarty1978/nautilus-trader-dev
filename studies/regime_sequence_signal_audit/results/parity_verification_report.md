# Parity Verification Report (2025 B1)

* **Status**: **FAIL**
* **Total checkpoints verified**: 16,259
* **Scope**: Verifies that runtime-computed causal features (regime age, current PnL, giveback)
  match the offline prediction table for the same (direction, regime_start_time, observation_time)
  key. Does NOT independently verify the W4 model score itself � the live strategy looks up the
  offline prediction rather than recomputing it, so there is no independent online score to compare.

| Feature | Max Absolute Difference | Mean Absolute Difference | Parity Status |
|---|---|---|---|
| **Regime Age** | 0.000000 s | 0.000000 s | PASS |
| **Current PnL** | 6.895586 ATR | 0.469559 ATR | FAIL |
| **Giveback** | 9.938733 ATR | 0.798904 ATR | FAIL |

## Root cause (diagnosed 2026-07-09)

Regime Age matches exactly (0.0s across all 16,259 checkpoints), which proves the offline
prediction table is being looked up under the correct `(direction, regime_start_time,
observation_time)` key — this is NOT a key-matching bug. The mismatch is in the reference price
used to compute `current_pnl`/`giveback`:

- **Offline** (`studies/regime_sequence_chop_context/build_flip_atlas.py:181`): `flip_close =
  float(r_curr.close)` — the CLOSE of the regime-flip bar itself.
- **Online** (`strategies/w4_exit_strategy.py` via `backtests/baseline_flip_parity/strategy.py`):
  `self._entry_px` — the actual FILL price, one bar later, only after "bar1 confirmation" (entry
  requires the next 1m bar's high/low to break the flip bar's extreme). By construction this fill
  price is already further into the move than `flip_close`, so offline `current_pnl` is
  systematically inflated relative to what a live strategy actually captures — consistent with the
  observed pattern (offline values mostly larger/more positive than runtime values, sometimes by
  6-10 ATR).

**Consequence**: the W4 model (and any other score sharing this atlas) was trained on
`current_pnl`/`giveback` features computed against a reference price that no NT-executable policy
in this study ever actually gets filled at. This is a train/serve skew that the original
(tautological) parity check could never have caught. It does not affect B0 (no W4 dependency), but
directly undermines the theta/N calibration and warning-firing behavior of B1/B2/B3/B5 — the
policies' NT-execution results are still faithful replays of whatever the (mis-calibrated) model
outputs, but the model itself was not calibrated against reality. Fixing this requires rebuilding
`flip_context_atlas.parquet` with the bar1-confirmed entry price as the PnL reference and
retraining W4 — out of scope for this validation pass; flagged for follow-up.
