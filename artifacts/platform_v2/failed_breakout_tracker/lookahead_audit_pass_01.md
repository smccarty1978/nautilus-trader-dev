# Look-Ahead & Timestamp Audit — Pass 01
**audit_type:** "causal"
**Date** 2026-10-18 · **Worktree** `Nautilus Trader-failed_breakout_tracker` (branch `chore/failed_breakout_tracker`)
**Scope (files)**
- `features/trackers/price_level_failed_breakout.py` (223 lines, binding)
- `research_workflow/capabilities/proposals/tracker.price_level.failed_breakout.yaml` (168 lines, contract)
- `features/tests/test_price_level_failed_breakout.py` (599 lines, tests + oracle)
- Context read in full: `features/trackers/generic_price_levels.py`, `features/trackers/price_levels.py`, `utils/session_boundaries.py::is_rth_completed_bar_1m`, `research_workflow/host/interfaces.py::BarView`, `research_workflow/host/outcomes.py` (structural-unit stop handling)

**Scope hash:** not computed — no `audit/preflight.json` / `audit_packet.json` present for this worktree; this is an ad hoc direct read-only review, not a standard study-protocol pass. File identity confirmed by line count above; no edits made.
**Lint:** not run (no preflight gate available for this worktree) — reviewed by direct source inspection only.
**Verdict: PASS_WITH_NOTES**

## Summary            Critical: 0 · Warning: 0 · Note: 1

## Critical findings
None.

## Warnings
None.

## Notes

### [F2] `features/trackers/price_level_failed_breakout.py:105-118, 190-194` — same-bar re-arm across the ETH→RTH boundary uses a pre-RTH close
On the first RTH bar of a trading day, `_reset_session()` forces every episode to `UNAVAILABLE` (price_level_failed_breakout.py:190-194), but `step()` (called immediately after, same bar) transitions `UNAVAILABLE -> UNARMED` and then runs the arm test (`:156`) in the *same* iteration, using `prev_close` — which for the first RTH bar is the close of the **last ETH bar** before the open. For a level that is already known (pdh/pdl are normally known from day 2 on), this means a level can arm, breach, and fail entirely on the first RTH bar, driven by a pre-RTH close. This is causally sound (the ETH close is a real, already-available previous completed bar — no future information is used), and the contract's own ARMED bullet is worded generically ("the previous completed bar"), so this is not a demonstrated defect. It is, however, a plausible reading-gap against the contract's `reset_policy` line ("arming... reset[s] at... the first RTH bar of a trading day") that is not covered by any test (no test feeds a pre-RTH close on the near side of PDH/PDL into the first RTH bar). Not independently validated either way; no concrete wrong-number path shown, so `NOTE` rather than `WARNING` per the checklist's own rule ("not independently validated" is only a `WARNING` if failure can be shown).
**Smallest fix (if desired):** add one `step()`/`on_bar` golden test that feeds a pre-RTH close on the near side of PDH into the first RTH bar and pins the resulting behavior (arm+breach+fail allowed, or suppressed) so the contract text and the code agree explicitly.

## Referred to contract-checker
None.

## Clean checks

- **A1/A3** — all indexing/clock decisions (`is_rth`, day-key, expiry, `event_ts`, `last_bar_close_ts`) use `bar.ts_init` (close); `episode_start_ts` deliberately uses `bar.ts_event` (open) only as a descriptive "interval open" field per the contract, never for ordering/availability decisions. Confirmed at `price_level_failed_breakout.py:110,114,136,153,161,173,185`.
- **B2/B4** — the level dict (`known`) used to decide arming/breach/failure on the bar closing at T is always the provider snapshot taken *after* the previous completed bar (`on_bar` calls `step()` before `self._provider.update_completed_bar(bar)` and before recomputing `self._known`, lines 118-128). This is strictly causal and in fact one bar *more* conservative than the minimum requirement: `onh`/`orh` etc. become true at the instant they finalize (bar open) but the episode logic cannot use them until the following bar — confirmed by `test_overnight_level_is_usable_only_after_the_first_rth_bar_publishes_it` and `test_opening_range_is_usable_only_after_its_final_bar`.
- **B9/B10** — tracker/provider contracts for warmup, cadence, reset and gap policy are explicit in the YAML; the binding reuses the canonical `GenericPriceLevelProvider`/`PriceLevelTracker` rather than reimplementing level math (`price_level_failed_breakout.py:91,125`), pinned 1:1 by `test_levels_equal_the_provider_snapshot`.
- **Episode extreme / stop_reference (checklist item 3)** — `extreme` is updated with the current bar's high/low *before* the failure test every `BREACHED` bar, including the breach bar itself and the failure bar (`:159-169`); `_clear_bar_fields()` nulls `stop_reference_price`/`episode_extreme` etc. at the top of every `step()` call, so a fired value never survives into the next bar's fields. Confirmed by `test_multi_bar_episode_extreme_includes_every_bar_and_the_failure_bar` and the same-bar-sweep test.
- **Session resets (checklist item 4)** — every non-RTH completed bar and every new `trading_day_key` resets all tracked episodes to `UNAVAILABLE` and zeros `event_seq_level` (`:111-117,190-194`); no `BREACHED` episode survives an RTH close, a halt, or the overnight — confirmed by `test_episodes_do_not_survive_the_rth_close_or_the_next_session`.
- **Oracle independence (checklist item 5)** — `_oracle_levels`/`_oracle_events` (test file lines 328-410) reimplement trading-day grouping (`_tday`), the RTH clock (`_is_rth`), level finalization and the arm/breach/extreme/failure state machine entirely from the raw bar list; it imports only constants (`ACCEPTED, ARMED, ...`) from the binding module for the golden-test assertions, never the binding's `step()`/`_Episode` logic. Genuinely independent.
- **Off-by-one at the deadline (checklist item 6)** — the lazy pre-check uses strict `>` (`ep.start_ts + max_episode_ns`) so a bar closing *exactly* at the deadline is still eligible to fail; the post-update check uses `>=` so that same bar, if it does *not* fail, is the last one considered and the episode is accepted immediately after. Confirmed against `test_failure_at_the_deadline_counts_and_one_minute_later_is_accepted` (deadline-bar failure counts; one minute later is rejected) and `test_a_missing_minute_cannot_extend_an_episode` (a missing bar cannot push the deadline out).
- **ts_event vs ts_init** — `is_rth_completed_bar_1m` is called with `bar.ts_init` matching its own docstring ("timestamped at CLOSE"); `GenericPriceLevelProvider.update_completed_bar(ts_avail=bar.ts_init, ...)` matches `PriceLevelTracker.update_1m`'s documented contract ("`ts_avail` must be the bar's CLOSE timestamp"). No ts_event/ts_init confusion found.
- **Integration (`outcome.stop_reference`, unit: structural)** — `research_workflow/host/outcomes.py:333` freezes the stop at T and never re-reads it; `test_end_to_end_events_feed_the_structural_stop_at_T` confirms every candidate is an oracle event at its own bar close, the stop equals the frozen sweep extreme moved by the buffer and tick-rounded, and entry is the next bar's open — all platform-governed (R2/R4), not re-derived here.
