# Look-Ahead & Timestamp Audit — Pass 03

**Date:** 2026-08-12
**Scope:** `__init__.py`, `implementation/__init__.py`, `implementation/analysis.py`, `implementation/lineage.py`, `implementation/policy.py`, `implementation/validate.py`, `run_study.py`, `tests/__init__.py`, `tests/test_conditional_rule.py`
**Scope hash:** 8d5de7b47f43386e99cf79926c49d350f940aabbc6366ba56417656c901402f5
**Lint:** 0 critical / 0 warning from causal_lint.py (9 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| N1 (pass 1) | Placebo `tau` anchored on `arm_ns` vs pool clock | **FIXED, re-confirmed** | `policy.py:172` unchanged since pass 2 — no edit touched this line this pass. |
| N2 (pass 1) | Exact-timestamp mark matching drops non-matches | **ACCEPTED, closed** | `policy.py:183-185` unchanged. |
| Referral (pass 2) | `tests/` had no executable coverage for `policy.py`/`validate.py` | **FIXED** | `tests/test_conditional_rule.py` added, 23 tests, `python -m pytest studies/p90_conditional_losing_5s_exit/tests/test_conditional_rule.py -q` → 23 passed. Imports `simulate`/`determine_verdict` directly, does not stub or bypass either. |

## New verifications (this pass — the 4 stated changes only)

1. **`validate.py:1` docstring "V1-V12"→"V1-V13"** — text-only. Grepped the file: `V13_placebo_pooled_draws` gate (`validate.py:112`) already existed pre-edit (confirmed present and passing in pass-2's 28/28). The docstring was simply wrong before; no gate logic touched. CLEAN.

2. **`analysis.py:176-179` new `pct_losing_before_1atr` key** — read the surrounding block (`analysis.py:170-181`): both `pct_losing_before_1atr` and `pct_losing_before_1atr_stop` are computed by the identical expression `float(np.mean(has & np.isfinite(stop_ns) & (fl < stop_ns)))`, same inputs (`has`, `stop_ns`, `fl`), same line pair, no new variable derivation. Confirmed by direct data comparison: `results/trade_level_signal_coverage.csv` columns `pct_losing_before_1atr` and `pct_losing_before_1atr_stop` are element-wise identical (`equal2: True`). Pure output-manifest alias. CLEAN.

3. **`run_study.py:199` new `delta_vs_conditional` key** — both `delta_vs_conditional` and `delta_placebo_minus_conditional` read `placebo_delta["delta_per_arm"]`, the same dict entry, same line pair (`run_study.py:199-200`). Confirmed by data: `results/matched_placebo.csv` columns are element-wise identical (`equal: True`). No new computation, no new timestamp, no change to `placebo_delta` itself (which was verified clean in pass 2, item N1). CLEAN.

4. **`tests/test_conditional_rule.py`, new file, 23 tests** — synthetic-fixture unit tests, imports `simulate`/`determine_verdict` unmodified; does not patch or monkeypatch either. Specifically traced the two fixtures called out for scrutiny:
   - `test_conditional_exit_fills_strictly_after_the_flip_becomes_known` (line 140): flip `close_ts = T0+5s`. Traced `simulate()` (`policy.py:182-236`): mark-bar match requires `ts[pos]==flip_ts` (exact), `market_from()` builds `ts[i] = T0+(i+1)s`, so `close_ts=T0+5s` matches bar index 4 exactly. Fill is `start+idx+1` (`policy.py:230`) → bar index 5 → `market.ts[5] = T0+6s`. The test's `exit_ns == T0+6*NS` assertion is arithmetically exact per the real fill logic, not an invented expectation — it reproduces the same "mark index + 1" rule pass-2 already verified clean at `policy.py:213-214,229-234`.
   - `test_placebo_times_are_anchored_on_entry_not_the_arm` (line 214): traces `policy.py:172` (`cand = entry_ns + round(tau*NS)`), the exact code path fixed under pass-1 finding N1 and re-verified in pass 2. `entry_ns = T0+1s` (confirmed separately by `test_entry_fills_after_the_decision_not_at_it`, itself traced to `policy.py:132`, `entry_ns = int(market.ts[start])`, `start = index_strictly_after(arm_ns)`). `tau=4s → T0+5s`, matches bar 4, fills at bar 5 → `T0+6s`. This is the correct behavior per the already-audited anchor fix, not a masked regression — an anchor-on-`arm_ns` regression would instead land the candidate at `T0+4s` (bar 3, fill bar 4, `T0+5s`), which the test's inline comment explicitly calls out as the wrong-answer case it is designed to catch.
   Neither fixture encodes an incorrect causal expectation; both are regression-detecting for the exact clock convention pass 1/2 fixed. No new data dependency, no new timestamp source (`T0`, `NS` are synthetic constants local to the test module), no production code modified.

## Re-run verification
- `causal_lint.py`: 9 files scanned → 0 critical / 0 warning (`audit/lint_pass3.json`).
- `results/validation_report.json`: `n_gates=28`, `n_failed=0`.
- `results/summary.json`: `verdict = "G4_NO_USEFUL_EDGE"` — unchanged from pass 2.
- `pytest studies/p90_conditional_losing_5s_exit/tests/test_conditional_rule.py`: 23 passed, 0 failed.

## Warnings
(none)

## Notes
(none)

## Referred to contract-checker
(none new this pass — pass-2 test-coverage referral is now FIXED, see adjudication table)

## Clean checks
- A1-A5, B1-B7/B9-B10, C1-C3, F1, G1-G2, H1-H4 — re-verified clean; only the 4 stated non-causal edits touched the tree since pass 2, none of which changed any economic quantity, timestamp source, or data dependency.
