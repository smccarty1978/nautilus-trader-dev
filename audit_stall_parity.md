<!-- DOC-STATUS-BANNER -->
> **[HISTORICAL]**
>
> A point-in-time record of an individual historical audit. It is not a description of the current system
> and not a source of instructions.
>
> Current authority: **`docs/RESEARCH_WORKFLOW.md`**. Classification: `docs/DOCUMENT_MAP.md`.

# Look-Ahead & Timestamp Audit

**Date:** 2026-06-05
**Scope:** 
- `backtests/baseline_flip_parity/strategy.py`
- `backtests/baseline_flip_parity/run_backtest.py`
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 1
- Warning: 1
- Note: 1

---

## Critical findings

### [E4] strategy.py:319-326 (VFS Editor Version) — Premature Market Entry with Stale/None Side

In the 473-line VFS (virtual editor) version of `strategy.py`, `_check_entry` contains duplicate order submission code at the end of the method:
```python
319:         order = self.order_factory.market(
320:             instrument_id=self._inst_id,
321:             order_side=self._entry_side,
322:             quantity=Quantity.from_int(1),
323:             time_in_force=TimeInForce.FOK,
324:         )
325:         self._pending_entry = order.client_order_id.value
326:         self.submit_order(order)
```
This introduces a severe logic bug and potential crash:
1. **Crash on first trade:** `self._entry_side` is initialized to `None` in `__init__` and is only set in the confirmation block (which hasn't executed yet). Passing `None` to `order_factory.market` will raise a `TypeError` in Cython.
2. **Stale execution on subsequent trades:** If the first trade completes, `self._entry_side` retains the previous trade's side. On the next flip, it will submit an entry order using the previous side, causing wrong-direction entries (e.g., entering LONG on a SHORT flip).
3. **Confirmation Bypass:** Entering immediately on the flip defeats the purpose of the newly added Bar 1 confirmation logic.

*Note:* This block is **not** present in the 463-line file currently on disk. This indicates a severe discrepancy between the virtual editor buffer and the saved disk state. Saving the editor buffer will overwrite the clean disk state with this bug.

**Recommended fix (do not apply):** Delete lines 319-326 in the VFS editor version of `strategy.py` to align it with the clean disk version, ensuring entry orders are only submitted in the confirmation block (lines 218-236).

---

## Warnings

### [A4/E4] strategy.py:210 — Gaps in 1s data can bypass confirmation logic

The confirmation block checks:
```python
208:             if self._pending_flip_ts is not None:
209:                 expected_bar1_close = self._pending_flip_ts + 60 * NS_PER_S
210:                 if ts == expected_bar1_close:
```
In NautilusTrader, 1s bars are only published when there is trade activity. If there is a gap in activity such that no 1s bar is published for the exact second of `expected_bar1_close`, this block is skipped. On the next bar:
```python
240:                 elif ts > expected_bar1_close:
241:                     self._pending_flip_ts = None
242:                     self._pending_direction = 0
```
This will silently discard the pending flip without ever checking confirmation.

**Recommended fix (do not apply):** Replace the exact second check with a check against the closed minute bar's start timestamp:
```python
if closed["ts_event"] == self._pending_flip_ts:
```
This is robust to 1s bar gaps since the minute aggregation fold will trigger regardless of exactly when the first 1s bar of the new minute arrives.

---

## Notes

### [E5] strategy.py:89-92 — ATR Period not fully stabilized on warmup

The strategy considers itself warmed up as soon as `tf.atr` is not None (which occurs after 14 periods). Because ATR is a recursive indicator, it requires more periods (typically 3 * period = 42 periods) to fully stabilize. Acting on signals exactly at the 15th period may use slightly noisy ATR values.

**Recommended fix (do not apply):** Increase the lead-in warmup or change the `tf.warm` property to require at least `ATR_PERIOD * 3` bars.

---

## Clean checks

- **A1 (Timestamp Indexing):** Clean. The strategy uses `ts = bar.ts_init` in `on_bar` to index and drive strategy logic, preserving close-time semantics.
- **A2 (Catalog Wranglers):** Clean. Verified in `archive/scripts/build_catalog.py` that `ts_init_delta` is correctly set (1s for 1-SECOND, 60s for 1-MINUTE, 300s for 5-MINUTE).
- **A3 (Causal Lookups):** Clean. Close price references are strictly causal (using the close of the completed 1m bar `closed` or the current 1s bar).
- **A5 (Timezone Safety):** Clean. Time comparisons use UTC-aware timestamps and UNIX nanoseconds directly, preventing DST or naive timezone issues.
- **B1 (Rolling Windows):** Clean. No rolling window calculations use `center=True`.
- **B2 (Indicator Look-ahead):** Clean. Indicators are updated using the completed previous-minute bar (`closed`), which contains no data from the current bar's tick.
- **B4 (Shift Lags):** Clean. No negative lags or future-looking shifts are used in the strategy.
- **B5 (Forward Fill):** Clean. No forward-fill or back-fill operations are present.
- **B6 (Joins/Alignments):** Clean. No joins or alignments are performed; all updates are performed in real-time.
- **E1 (Bar Subscriptions):** Clean. Bar subscription `cfg["bar_type"]` matches the catalog bar type.
- **E3 (Order Fill Model):** Clean. Stops are placed using Stop Market orders, which prevent immediate fills when properly capped.
- **E5 (Warmup continuous updates):** Clean. The previous critical issue of clearing `_closes_1m` history has been resolved. Updates to `_closes_1m` and `_ema_close` are done continuously on background bars, preventing train/serve skew.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*
