# Pre-Execution Lookahead and Execution-Contract Audit

**Status:** **PASS — authorized for the frozen 2025-first execution sequence**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope

Audited before any policy simulation:

- `SPEC.md`
- `config.json`
- `policy_freeze.json`
- `run_study.py`
- `tests/test_confirmation_clock.py`

The `results/` and `_work/` directories contained no study artifacts at audit time. This authorization covers only the exact file hashes bound in `pre_execution_authorization.json`.

## Audit conclusions

### Frozen inputs and policy scope

- The study consumes the exact repaired CODEX 5.X executed trade files, not a regenerated or altered entry set. The frozen SHA-256 values match both yearly trade inputs, both raw 1-second inputs, and the repaired runner/common dependencies.
- W4 is neither trained nor scored here. Entry timestamps, entry opens, directions, checkpoint ATR values, and trade membership come directly from the frozen repaired trades.
- The executable policy set is exactly A, B, and the single optional C. The timeout is fixed at 300 seconds; stops are fixed at 1.25 ATR for A/B and 1.00 ATR for C; B alone uses the fixed 0.75 ATR qualification and protected-profit level. There is no grid or alternate clock.
- The policy/configuration is hash-frozen before either year runs. The 2026 invocation requires a clean, hash-matching 2025 predecessor seal and exact 2025 artifacts. No 2026 result can select or modify a policy.

### Timestamp and causal sequencing

- Raw bars are treated consistently with the upstream repaired contract: `ts_event=t` is the open and labels the range `[t,t+1s)`. Stored integer nanosecond timestamps remain `int64`; the builder rejects non-integer output timestamp columns.
- An aligning flip at exactly `entry + 300s` is processed at that boundary and counts as confirmed. A later flip does not qualify as on time.
- B qualification uses only favorable movement from bars whose `ts_event` is strictly less than the timeout. Those ranges are completed at the timeout decision; the timeout-labelled bar cannot qualify itself.
- A/C make the timeout decision at 300 seconds and fill at the first available raw open strictly later. Their current stop remains active on the timeout-labelled bar and until that market fill.
- B activates its frozen protection for the timeout-labelled range (or the first available later range when a bar is absent), uses the contemporaneous open for a gap-through fill, never exits merely because 0.75 ATR was reached before timeout, and keeps the protected stop after a later aligning flip.
- Before alignment, policy stops are active from the entry bar. At alignment, A/C and unqualified B transition to the original 1.50 ATR stop before the aligning bar's range. Qualified B keeps its protected stop.
- Stop testing precedes favorable-excursion recording within a bar, providing the declared conservative loss-first rule when OHLC cannot determine ordering.
- An opposing-flip decision need not itself have a raw 1-second bar. The runner derives its fill boundary as the first available raw `ts_event >= scheduled_exit_decision_ts`. For stored opposing-flip exits, that derived timestamp and raw open must exactly match the frozen fill. For stored stop exits, replay continues toward the same future boundary but the stop must occur first through the baseline reconciliation gate.
- Stored opposing-flip exits and already-pending timeout fills occur at the applicable available bar open before that bar's range. No absent/intervening range is invented inside a raw-data gap, and the scheduled opposing-flip boundary retains priority if it coincides with an active protection check.

### Prices, PnL, and reconciliation

- All stop distances and MFE normalization use the frozen `atr_at_checkpoint`, consistent with the repaired established-fade trade execution and its stored 1.50 ATR stop.
- Directional point PnL, the $20 NQ multiplier, and one $10 round-trip cost are applied once per completed trade. Gap-through stops fill at the bar open; otherwise stop touches fill at the frozen level.
- Every trade is first replayed with `policy=None`; timestamp, fill price, and net PnL must match the repaired baseline before any output can be accepted.
- Paired rows preserve the original trade ID and expose causal exit changes, timeout counts, baseline-later-flip distinctions, B continuations/protected exits, winner clipping, loser conversion, and reductions in original stop-before losses.
- Year, direction, and session summaries contain trade count, mean/total net PnL, profit factor, win rate, stop rate, and all requested policy event counts. Path diagnostics separately preserve retrospective 5-minute and eventual-outcome evidence.
- Cardinality, baseline replay, timestamp dtype, frozen dependency, and 2025 predecessor checks all occur before final combined outputs are published.

## Independent checks

- Repository tests: **12 passed**.
- Independently exercised long and short paths, exact-threshold qualification, exact-300-second alignment, missing timeout bars, protected-stop gap fills, persistent protection after a late flip, scheduled decision timestamps absent from the raw series, no-intervening-bar scheduled fills, stop exits before a future gapped scheduled boundary, and scheduled-exit/protection collisions.
- Independently checked all frozen source rows against the raw indices. Scheduled decision timestamps lack an exact raw bar for 728 trades in 2025 and 230 trades in 2026. Every stored planned opposing-flip fill maps exactly to the first available raw timestamp and its open; every stored stop precedes its derived scheduled-fill boundary.
- Independently confirmed the frozen input/dependency hashes and source trade schema. The source contains 3,246 trades for 2025 and 1,137 for 2026; key timestamps are non-null `int64`, ATR is positive, all entries precede their aligning flips, and every scheduled opposing flip follows the aligning flip.
- Independently confirmed that no simulation result or predecessor seal existed when this audit was completed.

## Research limitation

This is a causal 1-second OHLC research replay, not NT-native executable validation or tick-order reconstruction. The declared loss-first OHLC rule and timeout-boundary activation contract make ambiguity explicit; they do not establish exact intrabar fill ordering.
