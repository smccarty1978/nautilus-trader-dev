# Chore `v4_outcome_lineage`: C1 terminal outcome + composite truncate, transplanted onto main

Requested by `studies/nq_mtf_regime_structural_geometry_atlas/CAPABILITY_REQUEST_v4_outcome_lineage_on_main.md`.
Base: `main` @ `5dd01ea1`. Branch `chore/v4_outcome_lineage`.

The six historical commits were cherry-picked in order. There is no redesign and no change to kernel logic.
Seven of the eight transplanted files are byte-identical to the historical repaired state (`e341d709`). The eighth
is `compiler.py`, which differs only by code that belongs to a different, un-transplanted change (below).

## 1. Lineage

The table lists each historical commit, the commit it became on this branch, its purpose, the files it changed,
its dependency, and its conflict risk. Every original commit still applies to main.

| original → new | purpose | files | depends on | conflict risk (actual) |
|---|---|---|---|---|
| `7c4a2673` → `d07f6380` | C1: canonical lifecycle terminal, executable exit fill, realized gross/net economics | `host/outcomes.py`, `grammar/compiler.py`, `grammar/spec.py`, `tests/test_c1_terminal_outcome.py` (+ a DESIGN.md section) | none among the six | low (code applied cleanly; a doc conflict) |
| `3756f092` → `a9e64ca1` | relocate the first-passage oracle parity proof into `research_workflow/tests` | `tests/test_first_passage_oracle_parity.py` | 7c4a2673 | none |
| `e2169543` → `61274baf` | the kernel's `observation_columns` carry the terminal block (the sink buffered from them and dropped the columns) | `compiler.py`, `outcomes.py`, test | 7c4a2673 | none |
| `292c8ca4` → `7f7217dd` | the merge fails when a declared observation column is absent from the parquet | `lifecycle_v2.py`, test | e2169543 | none |
| `4139ae15` → `42bbb85a` | `session_end_rule: truncate` was inert in the barrier/composite kernel | `outcomes.py`, `target_replay_oracle.py`, `tests/test_composite_session_end_truncate.py` | C1 (the tests assert the terminal columns) | none |
| `e341d709` → `57a2ec67` | session-bounded C1 exit fill; one-tick close hold for a same-instant flip | `outcomes.py`, test | 4139ae15 | none |
| (new) `085c2fd5` | three executable-entry proofs with non-coinciding prices (§5) | `tests/test_c1_terminal_outcome.py` | — | — |
| (new) `db81625e` | `MEANING` entry for `outcome.cost_points_per_side` (added by C1's `spec.py`, never documented) + regenerated reference | `scripts/gen_yaml_reference.py`, `docs/RESEARCH_YAML_REFERENCE.md` | 7c4a2673 | — |

**Historical branch state:**

- `4c2d1daf`, labelled "Add results and analysis files…", actually carries the **C0 fill-scope** platform change:
  `sessions.FillScopeTable`, `mux`, `strategy`, and the `compiler` outage-rule gap.
- `b909425e` is ~970 legacy study files.
- Neither was pulled in. None of the six commits needs either one: the code applied cleanly, and all lineage
  tests pass without them.

## 2. Conflicts and resolutions

There was one conflict: `artifacts/platform_v2/fill_outcome_session/DESIGN.md` (modify/delete).

- **Historical:** `4c2d1daf` created the file as the C0 fill-scope design, and `7c4a2673` appended a C1 section.
- **Current main:** the file does not exist.
- **Resolution:** the file was not added. Adding it would have documented the C0 fill scope, which main does not
  have. The C1 section is carried into this report as §4–§9.
- **Why behaviour is preserved:** the file is documentation only; no code or test changes.

There were no code conflicts.

## 3. Final diff scope (`5dd01ea1..HEAD`)

8 lineage files (+1,295/−14 lines), plus 3 tests (+~60 lines), the reference-doc fix (2 files) and this report. Total `5dd01ea1..HEAD` before the report: 10 files, +1,350/−14:

- `research_workflow/host/outcomes.py`, `research_workflow/grammar/compiler.py`, `research_workflow/grammar/spec.py`
- `research_workflow/lifecycle_v2.py`, `research_workflow/target_replay_oracle.py`
- tests: `test_c1_terminal_outcome.py`, `test_composite_session_end_truncate.py`, `test_first_passage_oracle_parity.py`

`git diff e341d709 HEAD` is empty for every file except `compiler.py`. For `compiler.py` the only difference is
the absent C0 `_require_outage_rule` / `outage_gap_seconds` code, which comes from `4c2d1daf` and is not part of
the lineage.

## 4. Terminal schema (`TERMINAL_OBSERVATION_COLUMNS`, one declaration used by compiler and kernel)

| column | meaning |
|---|---|
| `terminal_flip_ts` | instant of the qualifying opposite flip |
| `terminal_flip_disposition` / `terminal_flip_censor_reason` | canonical terminal status (`LABELED_POSITIVE`, or `CENSORED` with `SESSION_END` / `UNRESOLVED` / …) |
| `terminal_time_to_flip_seconds` | flip instant − decision epoch T |
| `terminal_exit_ts` / `terminal_exit_price` | executable exit fill (§6) |
| `terminal_exit_unavailable_reason` | `GAP` / `DATA_END` / session reason when no exit bar exists |
| `terminal_entry_ts` / `terminal_entry_price` | executable entry fill (§5) |
| `terminal_gross_pnl_points` / `terminal_gross_pnl_atr` | `direction·(exit − entry)`, and that divided by the frozen contract ATR |
| `terminal_duration_seconds` | `(exit_ts − entry_ts)/1e9` |
| `terminal_cost_points` / `terminal_net_pnl_points` / `terminal_net_pnl_atr` | **null unless `outcome.cost_points_per_side` is declared** |

Schema guards, retained unchanged:

- `compiler.py` and `outcomes.py` both build from `TERMINAL_OBSERVATION_COLUMNS`;
- every emitted terminal key is a declared column (`test_every_emitted_terminal_key_is_a_declared_column`);
- `lifecycle_v2` fails the merge when a declared observation column is absent from the parquet
  (`test_merge_carries_the_persisted_schema_assertion`);
- `observed_seconds` stays the last column (A5).

## 5. Executable entry

`terminal_entry_price` = the **OPEN of the first execution-stream bar with `ts_init > T`**. A bar at `ts_init == T`
is not eligible. `terminal_entry_ts` = that bar's open instant (`ts_init − duration` = `ts_event`). The entry is
subject to `max_gap`: an entry more than `max_gap` after T is a stale price and censors the arms `GAP`.

Proven by:

- `test_executable_entry_is_the_open_of_the_first_bar_strictly_after_the_decision`: the decision bar and entry bar
  have distinct open/close. Entry = 15,002 = entry.open ≠ decision close (15,000), decision open, entry close and
  flip close; `terminal_entry_ts == entry.ts_event`.
- `test_executable_entry_after_a_tape_gap_is_the_next_bar_that_exists`.
- `test_realized_gross_arithmetic_is_exact`.

**Publication limitation (historical C1 behaviour, unchanged, pinned by
`test_entry_columns_are_published_only_with_an_executable_exit`):** the entry pair is emitted in the same branch
as the realized economics (`outcomes.py`: `if p.entry_resolved and p.exit_ts is not None ...`). A row with no
executable exit has a **null** entry, even though its entry was resolved at T+1 bar. That covers:

- no flip before the trading-day close (terminal `SESSION_END` under truncate);
- `DATA_END`;
- an exit `GAP`.

## 6. Executable exit

`terminal_exit_price` = the OPEN of the first bar strictly after the qualifying flip, which is the same
next_bar_open convention as the entry, so there is no new fill convention. It is never sourced from a bar after the
session close: `test_the_exit_fill_never_comes_from_a_bar_past_the_session_close`, and the bound does not depend on
`max_gap` (`test_the_exit_fill_session_bound_does_not_depend_on_max_gap`). When no exit bar exists,
`terminal_exit_unavailable_reason` records why and no fill is fabricated
(`test_flip_on_the_final_bar_records_why_the_exit_is_missing` → `DATA_END`).

## 7. Composite truncate

For barrier/composite arms under `session_end_rule: truncate`:

- **effective end:** `min(nominal horizon end, session close)`;
- **no censoring at setup:** arms are no longer censored when the observation opens
  (`test_a_normal_truncate_population_is_a_mixture_not_total_session_end_censoring`);
- **touches:** a touch at or before the effective end resolves normally
  (`test_favorable_…`/`test_adverse_barrier_resolves_before_session_close_under_truncate`,
  `test_first_passage_order_is_exact_under_truncate`);
- **untouched arms:** they resolve `CENSORED/SESSION_END` only when the effective end is actually reached
  (`test_untouched_arm_is_censored_only_when_the_truncated_end_is_reached`);
- **past the close:** no arm ever resolves from a bar after the close
  (`test_truncate_never_resolves_an_arm_from_a_bar_past_the_close`);
- **precedence:** a truncated arm is `SESSION_END`, not the negative expiry policy, and a tape gap still outranks
  `SESSION_END`.

`censor` and `ignore` are unchanged (`test_censor_still_voids_…`, `test_censor_is_unchanged_…`,
`test_ignore_still_sees_past_the_close`). The independent replay oracle agrees
(`test_kernel_agrees_with_the_independent_replay_oracle_under_truncate`).

## 8. Flip at the session boundary

The 1s outcome bar closing at the session-close instant is delivered before the same-instant 1m flip bar. The kernel
therefore holds the close one tick instead of resolving on `now >= close`: a flip AT the close lands
(`test_a_flip_at_the_close_instant_still_lands_although_the_bar_arrives_first`). A flip after the close is
`SESSION_END`, not a cross-session terminal (`test_flip_after_the_close_is_session_end_not_a_cross_session_terminal`),
and a flip before the close survives into the terminal columns.

## 9. Milestones after the flip; terminal independence

There are three independent clocks: the fixed-time checkpoints, the milestone arms (their own horizons), and the
canonical terminal flip.

- The terminal columns read `p.flip_ts` directly and are never derived from the composite disposition
  (`test_terminal_flip_survives_a_censored_arm`, `test_a_mixed_composite_carries_resolved_and_censored_arms_and_a_real_terminal`).
- Arms keep resolving after the flip (`test_milestone_arms_keep_running_after_the_flip`). Restricting milestones to
  "before the opposite flip" is left to the study's analysis, not collection.
- The composite row's `disposition`/`censored` semantics are unchanged.

## 10. Sealed-plan compatibility

- `terminal_outcome` is a contract flag. A plan without it (every plan sealed before C1) emits no terminal columns
  and replays the pre-C1 rows exactly (`test_pre_c1_behaviour_is_the_documented_defect`,
  `test_kernel_columns_omit_the_terminal_block_for_a_pre_c1_contract`).
- New compiles that declare a flip item set `terminal_outcome: true`.
- `session_end_rule` defaults are unchanged, so a sealed `censor` / `ignore` plan is unaffected.

**Consequence:** `outcomes.py`, `compiler.py` and `lifecycle_v2.py` are in every V2 study's execution closure.
Any sealed study that merges this `main` gets a new closure hash and must re-run prepare (and stages 3–6 if it
re-seals). A study that does not merge `main` keeps its sealed closure. A study that recompiles a flip outcome gets
a new plan hash with the terminal block.

## 11. Targeted tests (on `chore/v4_outcome_lineage`)

- **Lineage suites:** `test_c1_terminal_outcome.py` 19, `test_composite_session_end_truncate.py`, and
  `test_first_passage_oracle_parity.py`: all pass (39 + 3 new).
- **Related suites:** `test_host_core`, `test_grammar_v2`, `test_golden_fixture`, `test_session_end_truncate`,
  `test_trading_day_censoring`, `test_composite_target_expression`, `test_ordered_barrier_entry_reference`,
  `test_single_primitive_ordered_barrier_regression`, `test_target_runtime` and `test_bucketing_and_gate`.
  Result: 159 passed, 6 failed.

**All 6 failures are pre-existing.** Each node was re-run on the actual pre-chore `main` `5dd01ea1`, and the
failure text is byte-identical after address normalization:

- `test_composite_target_expression.py::test_runtime_OR_flip_only_is_positive`
- `test_ordered_barrier_entry_reference.py::test_8_timeout_when_neither_barrier_is_touched`
- `test_ordered_barrier_entry_reference.py::test_9b_horizon_that_fits_before_close_is_labeled_not_censored`
- `test_ordered_barrier_entry_reference.py::test_10b_touch_one_second_past_the_horizon_does_not_count`
- `test_single_primitive_ordered_barrier_regression.py::test_primitive_timeout_is_negative_not_censored`
- `test_target_runtime.py::test_ordered_barrier_timeout_gap_ambiguous_and_exact_boundary`

## 12. test_delta gate

One run of `python scripts/test_delta.py research_workflow/tests scripts/tests --json` on `085c2fd5`.
Result: 2,316 ran, 2,226 passed, 63 failed, wall 14,616 s (4h04m).

The committed baseline is stale (`baseline_commit c480d8af`), so the card labels all 63 failures `NEW_FAILURE`.
Each node was re-run in isolation on pre-chore `main` `5dd01ea1` and on the chore, with the same command, and the
normalized failure text was compared:

| class | n | nodes / evidence |
|---|---|---|
| **pre-existing**: fails on `5dd01ea1` with byte-identical failure text | 58 | ordered-barrier/target-runtime (6, as in §11), `test_stage3_integration` (8), `test_nt_runner_backtest` (6), `test_rt_final_blockers` (6), `test_population_qualification_strictness` (5), `test_modeling_driver_lineage` (5), `test_diagnostic_followup_collector` (3), `test_redteam_pass2_*` (3), and 16 others |
| **order-dependent in the broad run, passes in isolation on BOTH** | 1 | `scripts/tests/test_supervisor_blackbox.py::test_stale_worker_result_is_refused` |
| **environmental**: fails identically in a FRESH worktree of `5dd01ea1` | 3 | `test_external_model_scoring::test_external_scorer_matches_repaired_model_c_…`, `test_runtime_bindings::test_episode_study_is_provider_host_mode_and_all_features_bind`, `test_stage3_integration::test_stage3_model_c_long_short_routing`. All three need the gitignored `studies/clean_maturity_flip_model_rolling_productivity/artifacts/train_fitted_models.joblib`, which exists only in the main checkout (memory: fresh-worktree failures are untracked artifacts) |
| **caused by this lineage** | 1 | `test_docs_v2::test_generated_reference_and_registry_are_current`: C1 added `outcome.cost_points_per_side` without a reference `MEANING` entry. The historical branches carried the same latent failure. **Fixed** in `db81625e`; `test_docs_v2` 9/9 pass |

Net: 0 unresolved failures attributable to the chore. The baseline was not re-recorded (outside scope). The broad
run rewrote tracked `studies/*/artifacts|audit` JSON and left `research_workflow/tests/first_passage_parity.json`
behind; both were restored or removed and are not committed.

## 13. Requesting-study compile proof (no collection, no outcomes read)

The unchanged `studies/nq_mtf_regime_structural_geometry_atlas/study.yaml` was compiled against the chore code
from a scratch copy. Result: `ok`, plan `28b77d54…`.

- `kernel: composite`, `terminal_outcome: True`, `session_end_rule: truncate`, `censor_session: TRADING_DAY`.
- `entry_reference: next_bar_open` on outcome stream `nq_1s` (= the epoch stream), so the entry is the next **1s**
  bar OPEN.
- All 15 `terminal_*` columns, in canonical order; `cost_points_per_side: None`, so net is null.
- 16 first-passage arms, each with a 24h horizon, plus the opposite-flip child (`regime_1m`, 24h, inclusive start).
- `prior_5m/15m/1h` (`tracker.regime.prior_level_snapshot`) with 39 `prior_*` columns.
- Outcome ATR `excursion_1m.frozen_atr`, `atr_availability: through_decision_ts`; `observed_seconds` is last.

The plan therefore supports:

- **SPEC §2 structural distances from executable entry:** `terminal_entry_price` plus the HTF raw levels and both
  ATR denominators. See the limitation in §15.
- **SPEC §5 lifecycle outcomes:** terminal winner/loser/flat from `terminal_gross_pnl_atr`, duration, the 16 probes
  and orderings from the `fp_*_resolution_seconds` columns.

## 14. Final main merge commit

The `--no-ff` merge of `chore/v4_outcome_lineage` into `main` (the first-parent merge whose message begins
`merge(chore/v4_outcome_lineage)`). Its exact SHA is recorded in the requesting study's
`CAPABILITY_COMPLETE:v4_outcome_lineage` handoff note; a merge commit cannot carry its own hash.

## 15. Remaining limitations

1. **Entry published only with an exit (§5).** In the predecessor's v4 run, 99.86% of terminals resolved, so
   roughly 0.1–0.2% of rows would lack an entry. The missing rows are selected by the FUTURE outcome (no exit), so
   a structural distance computed from `terminal_entry_price` has outcome-dependent missingness. The requesting
   study must measure this and treat it explicitly (report, exclude, or request a follow-up). The follow-up would be
   a one-line decoupling: publish entry whenever `entry_resolved` and not gap-stale. It was deliberately **not**
   done here, because it would change the historical C1 contract.
2. **C0 fill scope is not on main (`4c2d1daf`).** With it missing, closed-window zero-volume fill still runs through
   declared maintenance halts (372 on NQ, 2020-01-02..2021-06-25) and through data outages inside a TRADING_DAY row
   (for example short Dec-31 sessions). 2023/2024 have no halts, but outage rows can exist. The requesting study
   should check its 2023/2024 `empty_windows_published` against the dataset `gaps` table, or request C0 as its own
   chore. This is separate from this lineage by design.
3. The 6 pre-existing ordered-barrier / target-runtime failures (§11) remain on main; they are not this chore's.
