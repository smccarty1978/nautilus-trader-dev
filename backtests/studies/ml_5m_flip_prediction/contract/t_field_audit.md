# `_T_*` Field Audit — Collector v3 (April 2026)

## Purpose

After discovering `checkpoint_bars_since_signal_1m_T_*` was set at
trade-finalization time using accumulated state (creating a lookahead),
audit every `_T_*` field in the collector to verify snap-time correctness.

## Audit methodology

For each `_T_*` field written to `record` in the serialization loop
(collector.py lines 1247–1406), classify:

- **A. Reads `cp.X`** where `cp.X` was set inside
  `_snap_checkpoint(ts_data, T, current_ts)`. ✅ SAFE — snapshot at
  observation time.
- **B. Reads `ts_data.X_at_signal`** — set once in `_check_confirmation`,
  never modified. ✅ SAFE — signal-time constant.
- **C. Reads `ts_data.X_accumulated`** — updated over the trade lifetime
  (e.g., in `_update_active_trades_on_1m`). ⚠️ SUSPECT — value at
  serialization differs from value at observation time.

Also verify that in `_snap_checkpoint` itself, any read of `ts_data.X`
corresponds to an X that has the correct value at observation time.

---

## Findings

### 1. KNOWN BUG — `checkpoint_bars_since_signal_1m_T_*`

**Status:** FIXED in build_dataset.py (Apr 2026)

**Original code (collector.py:1269–1271):**
```python
record[f"checkpoint_bars_since_signal_1m_T_{tag}"] = (
    len(ts_data.bars_since_signal_1m)
    if cp.alive_at_T == 1 else float("nan"))
```

Uses `ts_data.bars_since_signal_1m` (a list that accumulates 1m bars over
trade lifetime). At serialization time this is the total trade lifetime
in 1m bars, same value for every T. This is a lookahead.

**Fix applied:** build_dataset.py now overrides this column to `T_d // 60`
(the semantically correct "bars elapsed between signal and checkpoint T").

**Impact:** previously 7.0% gain importance; when fixed, all "validated"
walk-forward filter economics collapsed (see MEMORY.md).

---

### 2. All OTHER `_T_*` fields — SAFE after audit

Walked every write in the serialization loop (lines 1247–1406) and every
assignment in `_snap_checkpoint` (lines 670–853). Classifications:

| Field stem | Source | Class | Notes |
|---|---|---|---|
| `alive_at_T`, `dead_before_T`, `fillable_at_T` | `cp.X` | A | Set in `_snap_checkpoint` / `_snap_fill` at obs/fill time. Backfill in `_finalize_trade` only for trades that actually died before the checkpoint — correct semantic. |
| `checkpoint_time_T`, `checkpoint_elapsed_s_T`, `checkpoint_entry_fill_time_T`, `checkpoint_entry_fill_price_T` | `cp.X` | A | Snap-time values. |
| `regime_1m_T`, `regime_30s_T`, `regime_5m_T` | `cp.X` | A | Set in `_snap_checkpoint` reading the live indicator state at `current_ts`. |
| `regime_*_aligned_T`, `regime_*_duration_bars_T`, `regime_5m_flipped_to_align_by_T`, `regime_5m_changed_during_delay_by_T` | `cp.X` | A | Derived in `_snap_checkpoint` from live regime state. |
| `ema*_slope_*_atr_T` | `cp.X` | A | Two of these are hardcoded 0.0 (collector placeholder, documented). |
| `ema_spread_*_atr_T`, `price_vs_sma20_*_atr_T`, `bar_range_30s_current_atr_T` | `cp.X` | A | Read from indicator state at snap time. |
| `distance_from_session_*_atr_T`, `atr_14_at_T` | `cp.X` | A | Session high/low updated on every 1s bar; `cp.X` captures value at obs time. |
| `continuation_count_since_signal_T`, `consecutive_continuation_bars_T`, `bars_since_last_continuation_T` | `cp.X` | A | Inside `_snap_checkpoint`, these read `ts_data.continuation_count` etc. — but that value IS already the count at `current_ts` (updates happen only on 1m close; subsequent updates don't retroactively change what `cp.X` captured at snap). Verified snap-correct. |
| `micro_*_T` | `cp.X` | A | Computed from `self._recent_1s` (last 12 1s bars) at snap time. |
| `vol_total_30s_recent_T`, `vol_vs_20avg_30s_T` | `cp.X` | A | Read from `self._1s_for_30s` and `self._recent_30s` at snap time. |
| `is_rth_T`, `hour_of_day_T`, `minute_of_hour_T`, `minutes_since_rth_open_T` | `cp.X` | A | Derived from `current_ts` at snap. |

### 3. Forward fields — NOT features (not in contract)

`forward_peak_mfe_atr_T_*`, `forward_peak_mae_atr_T_*`,
`forward_mfe_at_*s_T_*`, `forward_pt100_before_sl100_T_*`,
`forward_regime_pnl_dollars_T_*` etc. — ALL are forward from the
checkpoint fill. Correctly excluded from features; used only as labels
or forward-path metrics.

### 4. Non-`_T` intermediate fields — NOT features

`pnl_from_t0_to_T_atr_*`, `mfe_from_t0_to_T_atr_*`,
`mae_from_t0_to_T_atr_*` — excluded from features. These use
`ts_data.t0_fill_price` (set once at T0 fill) and current 1s close at
snap time. Correctly snap-time computed.

### 5. Already flagged by MEMORY.md (not a feature in our contract)

`regime_5m_flip_checkpoint` — post-hoc `max T ≤ elapsed` mapping, not a
feature, explicitly excluded.

---

## Audit conclusion

**Only one `_T_*` field in the 100-feature contract had finalize-time
leakage: `checkpoint_bars_since_signal_1m_T`. That is now fixed.**

All other `_T_*` features in the contract read from `cp.X` (set at
`_snap_checkpoint(T, current_ts)` time) or from signal-time constants on
`ts_data`. No other lookahead identified.

For future contract expansions (v2+), any new `_T_*` field must:
1. Be set inside `_snap_checkpoint` reading only state available at
   `current_ts`, OR
2. Read `ts_data.X` where X is either signal-time constant OR a value
   that's consistent between snap and serialization (i.e., doesn't
   accumulate).

Auditor: coder
Date: 2026-04-23
