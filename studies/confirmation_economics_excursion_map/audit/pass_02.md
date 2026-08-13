# Look-Ahead & Timestamp Audit — Pass 02 (bounded re-audit)

**Date:** 2026-08-10
**Scope:** `studies/confirmation_economics_excursion_map/implementation/panel.py`
**Scope hash:** `b56ef37b6a0bd927cec8717231a1176edcbfd079e3fdd8d91579e1c1c038594f`
**Lint:** 0 critical / 0 warning (`causal_lint`, 7 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| CRITICAL 1 | Phase 7 `ia` checked post-confirm re-touch before "already held" | **RESOLVED** | `panel.py:308-312` now checks `run_mfe[confirm_idx] >= a` first, `ia=0` unconditionally when true — matches the requested fix exactly. `run_mfe[confirm_idx]` is the expanding, causal MFE read at the confirm bar (built by `np.maximum.accumulate` over `[start:end]`, no bar past `confirm_idx` contributes to that scalar), so the new branch introduces no lookahead. `test_transition_clock_resets_at_confirmation_when_landmark_already_held` constructs the exact regression case (giveback 1.4, would be ~0 under the old ordering) and passes. |
| CRITICAL 2 | Stop-vs-landmark / floor-vs-landmark same-bar collisions unflagged, resolved optimistically | **RESOLVED** | `panel.py:262-296` (landmarks) and `:336-363` (floors). `stop_post_idx` correctly maps the full-window `stop_idx` into the post-confirm slice's own index space (`stop_idx - confirm_idx - 1`, matching `sl = slice(confirm_idx+1, post_end)`); `-1` in unconstrained mode is correct, not masked — unconstrained genuinely has no live stop post-confirmation (SPEC §2), so there is no stop event to collide with, verified against `test_landmark_on_the_stop_bar_is_ambiguous_and_not_credited` (unconstrained row shows `ambiguous_with_stop=False`, credited=True — correctly no ambiguity where no stop exists). Ambiguous landmarks are refused credit (`credited = idx>=0 and not already and not amb`) — the adverse bound — in both modes; in unconstrained mode `amb` can never fire (`stop_post_idx>=0` required), so nothing is spuriously withheld there. Floor-vs-landmark reference set (`landmark_idx`, populated only for *credited* landmarks) is the correct set: landmarks excluded for `already_at_confirm` have no in-window achievement index to compare against, and landmarks excluded for `ambiguous_with_stop` sit exactly on the stop bar — a floor touching that same bar is a same-direction (low-vs-low) coincidence with the stop, not an intrabar-ordering ambiguity (floors and the stop both trigger off `bar_low_mark`; whichever is less extreme is crossed on the same monotonic move, no ordering question), so excluding it from the floor-vs-landmark check is correct, not a gap. |
| WARNING | Phase 1 / Phase 8 fields computed unconditionally regardless of `confirmed` / canonical outcome | **RESOLVED** | `panel.py:192-194` now gates the entire post-`confirm_idx` block on `out["confirmed"]` and returns early for both modes; `panel.py:371` additionally gates `reached_opposing_flip` on `label_c in (FLIP_WINNER, FLIP_LOSER)`. `confirmed` uses strict `confirm_idx < stop_idx` (not `<=`), so a same-bar stop/confirm tie — already flagged `ambiguous_stop_confirm` and resolved to `STOPPED_BEFORE` in the terminal-label logic — correctly falls out as unconfirmed too; no trade that is genuinely confirmed strictly before its stop is dropped. `test_stopped_before_confirmation_yields_no_confirmation_economics` confirms no Phase 1 keys are present in either mode for a pre-confirm stop. |

## New findings

None. No new CRITICALs, WARNINGs, or NOTEs raised this pass — the remediation matches the requested fixes exactly and the added regression tests cover the failure paths originally demonstrated. All 13 unit tests pass; `causal_lint` remains clean.

## Referred to contract-checker
- (carried from pass 1, now moot for this agent) whether `results/validation_report.json` gate 10 (`same_bar_accounting`) is populated from the new `ambiguous_with_stop`/`ambiguous_with_landmark`/`n_ambiguous_*` fields end-to-end is a completeness question for contract-checker, not re-raised here.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F2, G1, H1-H4: unchanged from pass 1, all still clean; no new data paths, timestamp handling, or session logic touched in this diff.
- Newly added same-bar ambiguity accounting (§1.1) and confirmation-gating logic (this pass's scope) verified clean per the adjudication table above.
