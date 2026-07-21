# W4 Exit Policy Study — Final Validation Summary

Full interactive report: see chat artifact from 2026-07-09. This file is the durable text record.

## Scope completed
1. Re-ran the lookahead-auditor gate to completion (9 passes total this session; passes 1-3 predate this session).
2. Fixed the B4 "partial exit" offline/live train-serve mismatch — implemented a true 2-lot partial exit in the NT strategy, then dropped B4 after 5 distinct execution-model bugs surfaced across passes 6-9 (all specific to the 2-lot mechanic; B0/B1/B2/B3/B5 unaffected).
3. Executed the full NT backtest matrix (B0-B5 x 2025/2026) and ran parity + slippage validation.

## Audit trail (this session)
- Pass 4: FAIL — `generate_trades_report()` doesn't exist on NT's Trader (crashed every run before saving); blended-PnL weight bug.
- Pass 5: PASS_WITH_WARNINGS — fixed above; found B1/B4 retry didn't actually retry, same-bar exit-order clobbering could drop a trade, `generate_positions_report()` miscounts open positions as closed.
- Pass 6: FAIL — fixed pass 5 items; found a **pre-existing** bug (not introduced this session): the child strategy's on_bar state-reset block checked `self._entry_px is not None`, but the base class already nulls it earlier in the same event — the warning state machine never reset between trades, for the life of every backtest ever run against this file.
- Pass 7: PASS_WITH_WARNINGS — fixed by resetting state synchronously in `on_order_filled`; empirically verified (59/59 closing fills reset correctly, 0/59 entry fills). Cleared the full matrix to run.
- Post-run discovery: B4 2025 trade count was 6,223 vs ~18,300-18,700 for every other policy. Root cause: NT's bar-execution engine only synthesizes ~1 lot of liquidity per tick; a single FOK order for qty=2 is entirely canceled (not partially filled) when it can't fill all at once.
- Pass 8: FAIL — fixed entries by splitting into separate 1-lot FOK legs; found the 2-lot SL/target brackets can themselves partially fill under the same thin liquidity, and the old fill handler treated the first partial fill as a full close (dropped the second fill, canceled the sibling bracket early).
- Pass 9: FAIL — fixed via exit-leg accumulation; found a WORSE bug: a same-bar double-fill on a resized bracket could leave **zero** trades recorded for a position NT itself confirms closed with real PnL. Recommended fix is architectural (finalize off `portfolio.is_flat()`, not order-id matching) — not applied. **B4 dropped per user decision** rather than pursuing a 10th pass.

## Real NT-validated economics (B0/B1/B2/B3/B5, both years)

| Policy | 2025 trades | 2025 mean PnL | 2025 win% | 2026 trades | 2026 mean PnL | 2026 win% |
|---|---|---|---|---|---|---|
| B0 | 18,331 | -$0.37 | 50.0% | 6,065 | -$8.07 | 48.5% |
| B1 | 18,714 | +$0.80 | 47.1% | 6,160 | -$7.16 | 45.5% |
| B2 | 18,443 | -$0.52 | 49.7% | 6,090 | -$8.52 | 48.2% |
| B3 | 18,501 | +$0.45 | 49.3% | 6,102 | -$8.16 | 47.7% |
| B5 | 18,420 | -$0.28 | 50.4% | 6,080 | -$8.38 | 48.7% |

2026 is a partial year (catalog runs through ~July 2026). Source: `backtests/results/w4_exit_backtests/NQ_<year>_<policy>/trades.parquet`.

**vs. the original offline Track B report (2026 test):** offline ranked B5 best (-$6.35/tr) and B1 worst (-$19.15/tr), spread $12.80. Real NT execution ranks B1 best (-$7.16/tr) and B2 worst (-$8.52/tr), spread $1.36 — a full ranking inversion for B1 and a ~9x overstatement of inter-policy differentiation by the offline sim.

**2026 is bad for every policy, including B0** (no W4 dependency at all) — looks like a broad regime/market effect on the underlying 1.0-ATR bracket strategy, not a W4-specific failure.

## Parity check: fixed the tautology, found a real failure
`run_parity_validation.py` previously compared `offline_w4_prob` to itself (always zero, could never fail). Fixed to keep only the genuine feature-parity checks. Result on 2025/B1 (16,259 checkpoints): Regime Age matches exactly (0.0s max diff — rules out a key-matching bug). Current PnL and Giveback FAIL badly: mean diff 0.47-0.80 ATR, max diff 6.9-9.9 ATR.

**Root cause**: the offline model atlas (`studies/regime_sequence_chop_context/build_flip_atlas.py:181`, `flip_close = float(r_curr.close)`) computes PnL against the regime-flip bar's own close. The live NT strategy uses the actual bar1-confirmed fill price (`self._entry_px`), which by construction is always further into the move than `flip_close` (entry requires the next bar to break the flip bar's extreme). This is a genuine train/serve skew in the W4 model's input features — undiscovered until the tautological check was fixed. Does not affect B0 (no W4 dependency); undermines the theta/N calibration behind B1/B2/B3/B5's warning logic, though their NT-execution results above are still honest replays of whatever the (mis-calibrated) model actually output. **Fix requires rebuilding `flip_context_atlas.parquet` with the bar1-confirmed entry price as the PnL reference and retraining W4 — not done, flagged for follow-up.**

## Slippage sensitivity (relabeled from fake "MBP-1")
The original script claimed streamed MBP-1 (tick/quote) validation; the catalog (`data/catalog/NQ_v0_2020_2026`) has no quote/tick data, only bars. Relabeled honestly as a flat 1-tick-per-side slippage sensitivity check against the *offline* B1 numbers (not NT execution). B1/2025: base -$66.80/tr, raw warning exit -$79.22/tr (EV lift -$12.42), with slippage -$89.22/tr (EV lift -$22.42). Verdict: ECONOMICALLY_UNRESOLVED.

## Bottom line
Every policy including the pure baseline (B0) is net negative in 2026. Nothing here clears the bar for deployment. The offline Track A/B reports' magnitudes and policy rankings should not be trusted — trust only the NT-execution table above, and treat the `flip_close` feature-parity issue as an open, unresolved problem affecting any conclusion that depends on the W4 model's calibration.
