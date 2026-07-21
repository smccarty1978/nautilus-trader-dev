# Pre-Execution Look-Ahead and Execution-Contract Audit

**Study:** `CODEX_5_X_W4_PRICE_RESPONSE_DELAYED_ENTRY_REPLAY`

**Status:** **PASS — AUTHORIZED FOR FIRST TEST/REPLAY**

**Findings:** **0 CRITICAL, 0 WARNING**

**Audit type:** Read-only static analysis before any execution of the new runner or its tests.

## Scope reviewed

- `run_replay.py`
- `config.json`
- `input_freeze.json`
- `SPEC.md`
- `tests/test_replay.py`
- The exact current implementation prompt.
- The frozen upstream repaired-trade and Policy A contracts referenced by the runner, including the established-fade and confirmation-clock replay semantics.

No new study code, unit test, replay, or result-producing path was executed during this audit. File reading, source comparison, and SHA-256 calculation only were used.

## Causality and timestamp findings

- The gate clock is anchored to the stored original explicit next-open fill timestamp, not to a later outcome. The only confirmation delays are the predeclared 10 and 30 seconds.
- Raw Databento one-second timestamps are treated as bar-open timestamps. A raw bar stamped `s` represents `[s, s+1s)`. At gate time `tg`, `searchsorted(..., side="left") - 1` selects the latest bar whose interval has fully completed; the explicit completion assertion prevents use of an incomplete gate-time bar.
- Virtual confirmation PnL uses only the completed close, original would-be fill, and fixed trade direction. It is kept separate from actual realized PnL and contains no outcome-derived cost or later price.
- Approved entries use `searchsorted(..., side="right")`, so the actual fill is the first available raw one-second open strictly after the decision time. A gate-time open cannot be used. Raw gaps are preserved rather than filled or imputed.
- The aligning regime flip is rejected when it occurs at or before the gate decision or at or before the delayed fill. This correctly rejects setups that end inside a raw gap before the next available open.
- Alignment, timeout, scheduled-exit, and stop events are sequenced causally. An aligning flip at exactly the delayed-fill-anchored timeout is accepted; a later flip cannot cancel an already-made timeout decision. Timeout fills occur only on the first available open strictly after the decision.
- The natural scheduled opposing-flip exit uses the first available open at or after its already-observed decision timestamp, matching the frozen upstream one-second OHLC contract. The scheduled-fill bar's range cannot stop the trade after that market-open exit.

## Stop and management findings

- The five-minute timeout is restarted from the actual delayed fill, as required for the primary variant.
- Both stop prices are anchored to the actual delayed fill and the frozen, causal `atr_at_checkpoint`: 1.25 ATR before alignment and the original 1.50 ATR after alignment.
- Stop processing begins on the delayed entry bar. Long and short touch rules are directionally correct, and the conservative gap rule fills at the adverse bar open when the open is through the stop, otherwise at the stop.
- The active stop remains effective on the timeout decision bar. The later timeout market fill takes precedence at its open, so that fill bar's subsequent OHLC range is not incorrectly applied first.
- An aligning flip inside a raw gap is recognized before the first later raw open when it occurred by the timeout boundary; a flip after that boundary does not retroactively suppress the timeout. This preserves raw-gap event sequencing.

## Frozen-input and year-isolation findings

- The runner validates the exact frozen SHA-256 hashes for both raw one-second inputs, both repaired trade files, the Policy A isolation diffs, its completion audit, and its manifest.
- The opportunity set is fail-fast checked at 4,383 candidates: 3,246 for 2025 and 1,137 for 2026. Policy A IDs must match the frozen entry-order IDs, baseline and repaired entry timestamps must agree row by row, and the final two-policy key must be unique and exactly 8,766 rows.
- Only `PR10` and `PR30`, delays 10/30, threshold zero, the completed-close mark, strict delayed fill, delayed-fill timeout anchor, 300-second timeout, 1.25/1.50 stops, and checkpoint ATR are accepted.
- A clean, hash-bound 2025 reconciliation and unchanged 2025 diff artifact are mandatory before the 2026 path can run. Thus 2026 cannot be loaded into the result pipeline before 2025 is completed and sealed. The policies are predeclared, so 2026 cannot create a new delay or threshold candidate.

## Reporting and accounting findings

- Baseline Policy A is emitted once from the PR10 copy of the identical frozen candidate population; it is not double counted across PR10 and PR30.
- Required splits are present: combined, year, long/short fade, ETH/RTH, and all four direction-session intersections.
- For delayed policies, `mean_net_pnl_usd`, profit factor, win rate, stop rate, timeout rate, and average winner/loser use approved executed trades. `mean_net_pnl_per_candidate_usd` separately exposes opportunity-set EV. Candidate/approved/skipped counts make those denominators explicit.
- Skipped candidates contribute zero delayed-policy PnL. Consequently total PnL and trade-sequence drawdown represent the deployable gate policy over the complete chronological candidate stream, while executed-trade distribution metrics remain execution-conditional. Zero-valued skips do not change cumulative equity or drawdown.
- The overlapping trade-accounting table includes all requested cohorts: four skipped original-outcome groups, aggregate delayed-entry slippage versus original entry, improved/worsened/unchanged fills, regime end before delayed entry, approved later timeout, approved pre-alignment stop, and approved alignment reached.
- Every accounting cohort reports count, Policy A total, delayed-policy total, total and average PnL change. Approved-fill cohorts also report the correctly signed directional fill change, where negative is an improved fill and positive is a worsened fill.

## Test-source review

The unexecuted tests directly specify the new boundary behavior for completed-bar selection, strict later opens, adverse and exactly-zero confirmation, regime end at the gate, flip inside a gap before delayed fill, entry-bar fill-anchored stop activation, actual-fill timeout restart, strict post-timeout fill, exact-timeout alignment, and short-direction virtual-PnL sign. The inherited scheduled-exit and raw-gap management logic was also statically compared with the previously audited Policy A isolation contract.

## Authorization conclusion

The current source has no identified look-ahead path, timestamp leak, incomplete-bar confirmation, forced post-regime entry, timeout-anchor error, entry-bar stop blind spot, raw-gap sequencing error, year-isolation breach, frozen-population mismatch path, or reporting-denominator/accounting defect. It is authorized for its first test/replay only while the runner, config, freeze, and this audit retain the hashes recorded in `pre_execution_authorization.json`.
