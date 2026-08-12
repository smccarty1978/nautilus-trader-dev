# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-12
**Scope:** SPEC.md §4-5, implementation/policy.py, implementation/lineage.py, implementation/analysis.py, implementation/validate.py, run_study.py
**Scope hash:** 8f7bb8313fb8149a9e7e6760fed91b6214b5923977c4954c6ff9728166558bf3
**Lint:** 0 critical / 0 warning from causal_lint.py (8 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 2

## Audit items — verified against code

| # | Item | Verified at | Result |
|---|---|---|---|
| 1 | 5s state known before decision; mark bar cannot be future/nonexistent | `policy.py:164-167` `pos = searchsorted(ts, flip_ts, side="left")` + `ok = ts[pos]==flip_ts` (exact-equality mask) | CLEAN — `ts` is `market.ts` = `path_init_ns` (`engine.py:52,125`); equality mask guarantees the selected bar's `path_init_ns` literally equals the flip's `close_ts`, never an earlier or later bar. If no bar has that exact `path_init_ns` the flip is dropped rather than approximated. |
| 2 | Mark = close of bar with `path_init_ns == C` | `policy.py:174` `cur = (closes[p] - entry_price)*direction/atr` uses `closes[p]`, `p` from the item-1 exact match | CLEAN |
| 3 | Exit fills at open of first bar with `path_init_ns > C`, trigger price never credited | `policy.py:196,211-214`: `cond_fill = start+fire_at+1`; `exit_price = market.open_[fill]` | CLEAN — fill index is mark index + 1, i.e. the next bar strictly after `C`; validated at runtime by gate `V9_exit_after_flip` (`validate.py:79-89`, `exit_ns <= flip_ns` count must be 0). |
| 4 | Stop trigger completed-bar detect, fills next bar open, trigger price never credited | `policy.py:145-146,149-150` (`run_mae` from hi/lo, `stop_hits`), `195,211-216` (fill = `start+stop_idx+1`, price = `open_[fill]`) | CLEAN — same next-bar-open mechanism as the conditional exit (H1/H4 satisfied: extremes from HIGH/LOW, fill from OPEN). |
| 5 | Stop-vs-conditional collision compares FILL indices, resolves to stop | `policy.py:195-203`: `stop_fill = start+stop_idx+1`; `cond_fill = start+fire_at+1`; `if stop_idx>=0 and stop_fill<=cond_fill: ... stop wins`; `ambiguous = stop_fill==cond_fill` | CLEAN — matches SPEC §4.3 exactly (`<=` gives the stop priority on ties). |
| 6 | 1m confirmation appears in no exit rule | `policy.py:151-154,199-238` — `confirm_idx` only used to (a) split `STOPPED_BEFORE_CONFIRM`/`CONFIRMED_THEN_STOPPED` labels on an *already-resolved* stop exit, (b) populate `before_confirm`/`confirmed_before_exit` diagnostics. No branch changes `idx`, `fill`, or whether the conditional/stop fires. | CLEAN — enforced by gate `V5_*_outcome_set` (`validate.py:44-50`), which asserts the outcome set never exceeds the frozen label set. |
| 7 | Repeated flips walked ascending, fires on FIRST losing one | `policy.py:159-167` (flip_ts/pos derived from globally-sorted `r5.close_ts` via `searchsorted`, order preserved), `173-189` (`for n,(fts,p) in enumerate(...)`: `if conditional and fire_at<0 and cur<0`) | CLEAN — first-loss-wins by construction; validated by gate `V10_fires_on_first_losing_flip` (`validate.py:91-101`) against an independently computed `first_losing` table. |
| 8 | MFE/MAE indexed at trigger, not fill | `policy.py:179-180` (`current_mfe_atr`/`current_mae_atr` use `run_mfe[p]`/`run_mae[p]`, `p`=mark index) and `229` (terminal `mfe_atr`/`mae_atr` use `run_mfe[idx]`/`run_mae[idx]`, `idx`=trigger index, not `fill`) | CLEAN |
| 9 | Placebo `k`/`tau` from POOLED distributions, not the trade's own realised count/lifetime | `run_study.py:77-84`: `counts_pool` = all entered trades' `n_adverse_flips` under `BASELINE_1.00`; `times_pool` = all entered trades' individual flip `seconds_since_entry`; per new entry `k=rng.choice(counts_pool)`, `tau=rng.choice(times_pool, size=k)` — draw is independent of that entry's own row | CLEAN — matches SPEC §7 and `placebo_must_be_length_blind`. Time-window truncation to `(arm_ns, ts[-1]]` (`policy.py:161-162`) correctly discards checks beyond the trade's own natural end rather than forcing them; `V13_placebo_pooled_draws` gate records the pooling flag. |
| 10 | `flip_events_frame` enumerates over BASELINE window — does it leak into the conditional policy's own decisions? | `run_study.py:65-70`, `policy.py:117-141` | CLEAN — each `simulate()` call (baseline, cond, and both stop distances) independently recomputes its own window (`start`,`end`) and its own flip list via `adverse_flip_times(r5, arm_ns, ts[-1], direction)`. The window boundaries (`horizon_ns = min(session_close, opposing_ns)`) do not depend on `stop_atr` or the `conditional` flag, so `BASELINE_1.00` and `COND_1.00` provably enumerate the *same* flip list independently rather than one borrowing the other's — confirmed by gate `V6` (untouched trades bit-identical) and the fact `flip_events_frame` is fed from `walks_cache["BASELINE_1.00"]` only for descriptive tables (#2 manifest item) and the placebo pool, never back into a policy's own `simulate()` call. |

## Warnings
(none)

## Notes

- **N1 — placebo `tau` origin mismatch (arm_ns vs entry_ns), `policy.py:161` vs `policy.py:178`.** The pooled `times_pool` values are `seconds_since_entry` (`flip_ns - entry_ns` of the *donor* trade), but the placebo applies them as `arm_ns + round(tau*NS)` (`policy.py:161`) — i.e. relative to the *receiving* trade's `arm_ns`, not its `entry_ns`. Since `entry_ns` is by construction the first bar strictly after `arm_ns` (at most ~1s later, `engine.py:66-67`), this is a fixed sub-second-to-1s systematic shift, not a source of future information and not large enough to change any trade's outcome given hold times are tens of seconds or more. Disclosure only.
- **N2 — mark/flip silently dropped, not substituted, when no exact-timestamp bar exists.** `policy.py:166` (`ok = (pos<ts.size) & (ts[...]==flip_ts)`) drops any candidate flip whose `close_ts` doesn't exactly match a bar's `path_init_ns`, rather than snapping to a neighboring bar. This is the causally-safe choice (no substitution of an unavailable price) and is expected to be a no-op given continuous RTH 1s coverage; flagged only so a future data-integrity check on the canonical store's 1s continuity has a place to attach.

## Referred to contract-checker
- Gate `V10_fires_on_first_losing_flip` (`validate.py:91-101`) checks only `COND_1.00`; `COND_0.75` shares the identical code path (window construction is `stop_atr`-independent, so the invariant holds by construction) but has no equivalent gate assertion — test-coverage completeness, not a demonstrated defect.
- `validate.py` defines `V13_placebo_pooled_draws`, one gate beyond the `V1`-`V12` table enumerated in SPEC §5.1/§10 — manifest/gate-naming consistency with the frozen spec text.

## Clean checks
- A1-A5, B1-B7/B9-B10 (no rolling/feature computation in this study's causal path), C1-C3, F1 (RTH via canonical `session` column, inherited), G1-G2 (canonical store, inherited), H1, H2, H3 (n/a, no re-entry in this study), H4 — all verified clean per the item table above.
