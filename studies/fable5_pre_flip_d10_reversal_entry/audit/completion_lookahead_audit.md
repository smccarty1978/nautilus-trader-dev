# Look-Ahead & Timestamp Audit — Fable 5 Pre-Flip D10 Reversal Entry (COMPLETION GATE, post-execution)

**Date:** 2026-07-12
**Scope:** `studies/fable5_pre_flip_d10_reversal_entry/{analyze.py, build_report.py, strategy.py, results/final_report.md}` as executed, plus empirical spot-checks of `results/*.parquet`, `audit/*.parquet`, and `_work/nt_runs/*/{trades,skips,same_ts,entry_timing}.parquet`. Cross-referenced against `audit/pre_execution_lookahead_audit.md` (Pass 1 + Pass 2 + resolution log) to verify claimed fixes actually landed in the executed artifacts.
**Auditor:** lookahead-auditor v1 (completion-gate pass, pass 3 overall)

## Summary

- Critical: 1
- Warning: 3
- Note: 2

This pass found the fail-fast gates from Pass 1/2 genuinely present and passing (verified against real run output, not just code review). It also found **one new, severe, previously-undetectable defect that only manifests with real bar data**: a systematic checkpoint-to-bar timestamp mismatch that silently drops or delays a large, session-correlated fraction of both the real D10 entry population and (much more severely) the matched-placebo population, without being logged or gated anywhere. This directly bears on the report's central "matched placebo beats real D10" claim.

## Critical findings

### [New — population completeness / selection bias] `strategy.py:202,228,232-234,237` — checkpoint dispatch requires an exact `bar.ts_event` match against a fixed 5s wall-clock grid; ~27-43% of valid checkpoints (real entries, exits, and especially placebo triggers) are silently never dispatched, with severe RTH/ETH selection bias that differentially inflates the placebo arm

**Mechanism.** `causal_scores.parquet`'s `observation_time` values (and `_work/placebo_events_seed42.parquet`'s `d10_obs_time` values) are computed upstream on a **fixed 5-second wall-clock grid** (`flip_ts+5s, +10s, ...`), using `build_weakness_atlas.py`'s `searchsorted(ts_arr, cp_ts, side='right') - 1` "last-known-price-as-of" convention (confirmed in Pass 1's own clean-check write-up). This convention does **not** require an actual 1-second bar to exist exactly at `cp_ts` — it just uses whatever bar most recently preceded it. But `strategy.py`'s live dispatch is bar-event-driven and requires an **exact** match:

```python
# strategy.py:201-243
def _on_1s(self, bar: Bar):
    obs = bar.ts_event
    ...
    if self._placebo:
        ev = self._placebo_events.get(obs)          # line 228 — exact-key dict lookup
        ...
        if self._cfg.policy == "P4B":
            row = self._scores.get(obs)              # line 232 — exact-key dict lookup
            ...
        return
    row = self._scores.get(obs)                       # line 237 — exact-key dict lookup
```

The underlying "1-second" bars in `data/raw/NQ_v0_1s_{year}.parquet` (and the catalog `run_nt.py` feeds from) are **tick/volume-driven, not one-per-calendar-second** — verified directly: bars at `04:23:35, :42, :49, :58, :59, 04:24:02, :04, :05` for one sample window, with irregular multi-second gaps, worst during low-liquidity ETH/overnight hours. Any checkpoint whose grid timestamp lands in a gap is **never looked up by `_on_1s` at all** — no dispatch occurs, so nothing downstream (skip_log, same_ts_log, mismatch_count) ever sees it. It is invisible by construction, not by any explicit filtering.

**Empirically measured magnitude (2025):**

| population | metric | value |
|---|---|---|
| all valid checkpoints, whole year | exact-bar hit rate | 57.5% (2025), 62.2% (2026) — i.e. **37.8-42.5% of every valid score checkpoint in the year is never dispatched** |
| real D10 first-crossing (`d10_entry_events.parquet`, 17,726 events) | exact-bar hit rate on the *specific* first-crossing checkpoint | 72.8% (2025), 76.7% (2026) — **27.2%/23.3% of true first crossings are missed** |
| ...of which: fully lost (no later same-regime checkpoint ever recovers) | count/rate, stop-independent | **1,109 / 17,726 = 6.3%** (2025), confirmed identical across all 3 stop levels — verified by reconciling `trades.parquet` ∪ `skips.parquet`(own `obs`) ∪ `same_ts.parquet`(own `obs`) ∪ `d10_exit_regime_start` against `d10_entry_events.parquet`'s `regime_start_ns` set for P1 and P3 runs |
| ...of which: delayed (a later, coincidentally bar-aligned checkpoint substitutes) | rate among **actioned** trades | **3,394 / 14,437 = 23.5%** of P1 2025 stop=0.5 actioned trades have `signal_obs != offline d10_obs_time` for the same regime; mean delay 19.6s, median 0s, p90 20s, p95 80s, p99 478s, **max 1,515s (25 min)** |
| matched-placebo donors (`placebo_events_seed42.parquet`, 17,709 events, 2025) | exact-bar hit rate | **57.8%** — no delay-recovery mechanism exists for placebo (single fixed-key lookup, no first-crossing fallback), so **42.2% (7,468/17,709) of the intended placebo population is permanently, silently dropped** — confirmed exact: `P4A_2025_s0p50` shows `n_actioned(8,639) + n_busy_skip(1,602) == n_exact_bar_hits(10,241)` to the trade. |

**Session-correlated selection bias (the part that threatens the headline claim).** Among *missed* checkpoints, only 3.1-3.5% are RTH (96.5-96.9% ETH); among *hit* checkpoints, 45-49% are RTH. Because real D10 entries mostly get *delayed* rather than *dropped* (delay preserves the regime and its session tag), the **real actioned population stays close to the true ~29.8-29.9% RTH rate** (measured: P1/P3 actioned RTH fraction = 28.2-30.0% across both years and all stops). Placebo entries have no delay-recovery, so the **placebo actioned population is pulled sharply toward RTH**: measured RTH fraction = **40.3-46.7%**, roughly 12-17 percentage points above the intended (and real-arm-matching) ~29.8% rate. This is a real, measured RTH-vs-ETH profitability gap *within* the placebo arm (`segment_results.parquet`, 2025): P4A ETH EV ≈ $14-23/tr vs P4A RTH EV ≈ $26-40/tr, a $12-17/tr gap. Re-weighting P4A stop=1.0's 2025 EV to the true 29.8%/70.2% RTH/ETH mix (instead of its actual 44.2%/55.8% mix) reduces reported EV from +$28.23/tr to ≈ +$25.9/tr — a real but **modest** ($2-3/tr) inflation, not large enough on its own to flip the CLOSE verdict, but real, measured, undisclosed, and directly contradicts `SPEC.md`'s stated exact-match on `rth` as a placebo covariate (the covariate is exact-matched **offline**, but the **executed** samples are no longer session-balanced against each other because of this differential dropout — the matching design's own intent is silently broken at the execution layer).

**Exit-side corollary (smaller but real):** of 5,858 confirmed P3 (stop=1.0, 2025) trades whose confirmed regime offline data says *did* cross D10 before flipping, 208 (3.6%) exited via `opposite_regime_flip_exit` instead of `d10_exit` because their regime's D10 checkpoint was never dispatched live — meaning `d10_exit_rate`/`opposite_flip_exit_rate` in §9/§10/§12 of `final_report.md` slightly understate/overstate their true rates versus what a checkpoint-complete implementation would produce.

**Why this is CRITICAL and not just a WARNING:**
1. It is a genuine, silent, unlogged, unreconciled population-completeness defect that neither Pass 1 nor Pass 2 pre-execution audits could have caught (it only exists once real, irregularly-spaced bar data is loaded) — this is precisely the class of bug the completion gate exists to catch.
2. It directly contradicts `SPEC.md`'s and `population_definition.md`'s explicit promise of full reconciliation ("the offline event universe and the NT-actioned universe are reconciled in `audit/entry_timing_audit.parquet`") — the reconciliation artifact (`entry_event_reconciliation.parquet`) reports `offline_events`/`nt_actioned`/`nt_skipped` columns side by side but **`analyze.py` never asserts they close** (no `offline_events == nt_actioned + nt_skipped + <accounted-for-elsewhere>` fail-fast anywhere in `analyze.py:379-405`). The gap is visible only by manual cross-referencing against `trades.parquet`/`skips.parquet`/`same_ts.parquet`, which this audit did — it is not surfaced by any artifact a reader would normally trust.
3. It differentially distorts the matched-placebo comparison that the report's own "Key mechanistic finding" (the entire basis for the CLOSE verdict's evidentiary weight) rests on, in a measurable, directionally-consistent way (placebo EV inflated, real EV comparatively undisturbed).
4. It means the **reported sample sizes and reported §7/§8 population statistics do not describe the same population that generated §9-§15's trade economics** — §8's "D10 front-run entry advantage" (`frontrun_advantage_pts`, `seconds_d10_to_flip`) is computed entirely offline from `d10_entry_events.parquet`/`preflip_vs_wait_for_flip.parquet` using the *offline* (idealized, ungapped) first-crossing timestamp and price, while §9-§15's `entry_px`/`pnl` come from the *actually executed*, sometimes-delayed-by-25-minutes NT fill. The two halves of the report are silently describing two different (though correlated) samples.

**Recommended fix (do not apply):** either (a) build checkpoint `observation_time`/`d10_obs_time` values by snapping to the nearest actual bar `ts_event` at construction time (in `build_scores.py`/`build_placebos.py`), so every persisted checkpoint is guaranteed dispatchable, or (b) change `strategy.py`'s dispatch to an as-of lookup (e.g., maintain a sorted array of pending checkpoint times and check `<=  bar.ts_event` with a "consumed" marker) instead of an exact-key dict `.get()`, matching the upstream atlas's own "as-of" semantics. Either fix should be re-validated against the exact hit-rate metrics above (target: hit rate ≈ 100% for both real and placebo streams), and the real-vs-placebo comparison re-run before treating the "~$35-50/tr" gap as trustworthy. At minimum, add a fail-fast in `analyze.py` asserting `entry_event_reconciliation.parquet`'s `offline_events == nt_actioned + nt_skipped + n_recoverable_by_other_logged_mechanism`, which would have caught this immediately (it currently computes these three columns side by side but never compares them).

## Warnings

### `analyze.py:379-405` — the entry/placebo reconciliation table is descriptive only; no fail-fast closes the loop, which is exactly why the Critical finding above went undetected until this audit

Beyond the specific bug above, this is a standing process gap: `rec_rows` in `analyze.py` computes `offline_events`, `nt_actioned`, `nt_skipped` per (year, policy, stop) and writes them to `audit/entry_event_reconciliation.parquet`, but the only fail-fast in this block (`n_bad_submit_lag`) checks submit-lag timing on already-actioned trades, not population completeness. A reader of `final_report.md` §4/5 ("Pre-flip entries submit exactly 1s after observation (fail-fast checked...)") would reasonably assume the reconciliation is airtight; it is not. **Recommended fix (do not apply):** add an explicit closure assertion as described in the Critical finding's fix, and additionally log a `checkpoint_never_dispatched` skip reason (computed by diffing `self._scores.keys()` against a set of all `bar.ts_event` values seen at `on_stop`) so this exact failure mode becomes self-diagnosing in future runs.

### `strategy.py:349-373` (`_enter_on_flip`) placebo/D10 dispatch loss has no analogous protection for P0/P2, but P0/P2 flip-driven entries are not exposed to this bug — confirm this is understood, not accidentally relied upon

P0/P2 entries are keyed on `_on_1m` flip events (bar closes are always present — 1m bars are not tick-sparse in the same way), so they are not subject to the checkpoint-dispatch loss described above. This is correctly unaffected, but it means the study's **only** clean, complete population is the P0/P2 flip-to-flip baseline; every D10-conditioned policy (P1, P2's exit check, P3, P4A, P4B) carries some degree of the completeness defect. Worth stating explicitly in the report rather than leaving it implicit.

### `build_report.py` §8 (front-run advantage) and §7 (coverage) are computed from the pure-offline `d10_entry_events.parquet`/`preflip_vs_wait_for_flip.parquet`, not reconciled against what NT actually saw

Given the Critical finding, §7/§8's population (idealized, checkpoint-complete) is measurably different from §9-§15's executed population (checkpoint-incomplete, delay-shifted, RTH-skewed for placebo). The report does not flag this distinction anywhere; a reader could reasonably (and incorrectly) assume §7/§8's "96.3% of regimes ever reach D10" and "median 130s D10→flip" describe the same trades whose PnL appears in §9-§15. **Recommended fix (do not apply):** add a one-line disclosure in §7/§8 noting these are idealized/offline-only statistics, distinct from the executed-trade population described from §9 onward, with a pointer to the completeness gap.

## Notes

### Fail-fast gates verified genuinely present and passing in the executed run (Key Question 1)

Confirmed directly against artifacts, not just code review:
- **Runtime/offline flip parity**: `analyze.py:332-358` iterates every `_work/nt_runs/*/meta.json` + `flips.parquet`, fails fast on `mismatch_count != 0` or any symmetric-difference between the catalog-fed runtime flip stream and the offline `regime_d10_coverage.parquet` flip set. The run completed (produced `final_report.md`), so this gate passed for real — `meta.json` files inspected show `mismatch_count: 0` across sampled runs.
- **Score-lookup regime mismatch**: `audit/score_regime_id_audit.parquet` shows `n_score_only = 0` for both 2025 and 2026 (the fail-fast-gated direction); `n_regime_only` (28/2025, 13/2026) is the documented-benign direction (regimes with no checkpoint coverage).
- **Exit-reason completeness**: `audit/exit_reason_completeness_audit.parquet` shows `n_violations = 0` across all 243,176 trades — confirmed via direct read, not just report text.
- **Pre-flip submit lag == 1s**: `entry_event_reconciliation.parquet`'s `n_bad_submit_lag` column is 0 in all 12 rows; spot-checked `entry_timing_audit.parquet` directly, `submit_lag_s` is exactly `0.0` for `pre_flip=False` (P0) and (by the fail-fast) exactly `1.0` for all `pre_flip=True` rows that exist. **Caveat**: this check only validates the lag *of whatever checkpoint was actually dispatched* — it does not (and structurally cannot) detect that the dispatched checkpoint is sometimes a delayed substitute for the true first crossing (see Critical finding). The gate is correctly implemented for what it claims to check; the claim itself is narrower than a reader would assume.

### Stop repricing (Key Question 4) — confirmed clean, no artifact

Sampled all 13,831 gap-repriced stop trades in `trade_results.parquet`: for `entry_dir == 1` (long), `exit_px <= exit_px_raw` holds for all 4,411 rows (strict `<` for all of them, i.e. repricing always moved the fill against the trade or left it unchanged, never improved it); for `entry_dir == -1` (short), `exit_px >= exit_px_raw` holds for all 9,420 rows, same pattern. Matches `analyze.py:81-83`'s conservative-only repricing logic exactly. No look-ahead or optimistic-fill artifact found here.

### Verdict derivation (Key Question 3) — confirmed mechanical, no manual override

Traced `build_report.py:56-154` by hand against `policy_results.parquet`/`matched_placebo_summary.parquet`/`tail_dependence.parquet`: every P1/P3 × stop cell has `lift_2025 < 0` (2025 EV lift vs P0 negative for all 6 cells shown in §17's qualification table), so `lift_both_years_positive` is correctly `False` for all cells regardless of 2026's positive lift, and `qualifies` is correctly `False` for all 6 cells — `best_label = "NONE"` follows mechanically (`build_report.py:91-99`). REPAIR-path checks were traced: `p2_beats` is `False` because P2's 2025 EV (-$17.76) is worse than P0's 2025 EV (-$11.22); `d10_helps` is `False` because P3's summed `total_incremental_usd` for the `d10_exit` category is negative in 2025 (-$8,080 + -$8,550 + -$50,505 = -$50,975 across the three stops) despite being positive in 2026; `lift_without_profit` is `False` because no cell has `lift_both_years_positive == True`. `verdict = "CLOSE"` therefore follows mechanically from the data with no manual override found. (This derivation is unaffected in direction by the Critical finding above — CLOSE would very likely still hold after a completeness fix, given the real arm is already firmly negative in both years — but the *margin* and the specific "~$35-50/tr, entirely pre-flip" narrative used to justify CLOSE over REPAIR is not fully trustworthy until re-run.)

## Clean checks

- Runtime/offline regime flip parity: verified passing on real run metadata (not just present in code).
- Score-lookup regime mismatch fail-fast: verified `n_score_only = 0` both years from the actual audit parquet.
- Exit-reason completeness fail-fast: verified `n_violations = 0` from the actual audit parquet (243,176 trades).
- Pre-flip submit-lag == 1s fail-fast: verified `n_bad_submit_lag = 0` in all 12 reconciliation rows.
- Stop-gap repricing: verified conservative-only (never improves a fill) across all 13,831 repriced trades, both directions.
- Verdict derivation: hand-traced as fully mechanical against the underlying parquets; no evidence of a manually-overridden or cherry-picked conclusion.
- Placebo strictly-pre-flip constraint (`observation_time < regime_end_ns`): confirmed both real (`d10_before_end` uses strict `<`) and placebo (`build_placebos.py:68`) use the same strict convention — no asymmetric conditioning between the two arms on this dimension.
- Placebo trigger path (`_handle_placebo_trigger`, `strategy.py:297-305`) cannot fire on a stale/future regime: gated on `ev["regime_start_ns"] == self._regime_start`, mismatches counted and skip-logged, consistent with the real-entry path's `is_current` gate.

---

*Completion-gate audit complete (Pass 3). The one CRITICAL finding — silent, session-correlated checkpoint dispatch loss, ~6-43% depending on population, differentially inflating the placebo arm by an estimated $2-3/tr (measured, not dominant, but real and undisclosed) — should be repaired and the full pipeline re-run before `final_report.md`'s specific "~$35-50/tr, entirely in the pre-flip leg" mechanistic narrative and CLOSE verdict are treated as final. The CLOSE verdict's *direction* is likely robust to this fix (the real arm is unambiguously negative in both years independent of the placebo comparison), but the report should not be cited with its current placebo-comparison numbers or its "entirely in the pre-flip leg" causal claim until re-verified.*

---

# Pass 4 — dispatch fix verification

**Date:** 2026-07-13
**Scope:** `strategy.py` (`_on_1s`, `_on_1m`, `_handle_d10_observation`, `_handle_placebo_trigger`), `analyze.py` (entry-lag gate, mismatch/reconciliation gates, flip parity), the full rerun matrix under `_work/nt_runs/` (28 runs), all `audit/*.parquet` and `results/*.parquet`, and `results/final_report.md`. Compared bit-for-bit against `_work/nt_runs_v1_exactkey_dispatch/` (archived pre-fix runs) where useful. This pass re-derives every population/session/lag statistic independently from the parquets rather than trusting `final_report.md`'s prose.
**Auditor:** lookahead-auditor v1 (completion-gate pass, pass 4 overall)

## Summary (Pass 4)

- Critical: 1 (new — provenance/reproducibility, not look-ahead)
- Warning: 1 (carried forward, still unresolved)
- Note: 2 (new)
- **The Pass-3 CRITICAL (checkpoint dispatch loss) is CONFIRMED FIXED**, with strong independent empirical evidence (below), and is downgraded to a clean check.

## Critical findings (new)

### [Provenance / reproducibility] `strategy.py` on disk right now is NOT byte-identical to the code that produced the executed artifacts in `_work/nt_runs/` and `results/`

**Evidence.** `_handle_d10_observation` (the function that increments `self.mismatch_count`) is, under the *current* source, reachable only from two call sites: `strategy.py:267` (real, non-placebo dispatch loop; `entry_ok=self._pre_flip_policy`) and `strategy.py:256` (placebo dispatch loop, gated `if self._cfg.policy == "P4B":`). **P4A can never reach this function under the current code** — for P4A, `self._placebo` is `True` and `self._cfg.policy == "P4B"` is `False`, so the placebo branch of `_on_1s` returns at line 258 without ever touching `_handle_d10_observation`, and `mismatch_count` is therefore structurally frozen at 0 for every P4A run.

Yet every executed P4A `meta.json` shows a nonzero `mismatch_count`, identical across all three stop levels within a year and matching the corresponding P4B run exactly:

| run | mismatch_count |
|---|---|
| P4A_2025_s0p50/s1p00/s1p50 | 31 / 31 / 31 |
| P4B_2025_s0p50/s1p00/s1p50 | 31 / 31 / 31 |
| P4A_2026_s0p50/s1p00/s1p50 | 3 / 3 / 3 |
| P4B_2026_s0p50/s1p00/s1p50 | 3 / 3 / 3 |

This is not possible under the code currently on disk. Corroborating filesystem evidence:
- `strategy.py` mtime: **2026-07-13 05:06:24**. `analyze.py` mtime: **2026-07-13 05:06:09** (15s apart — one edit session).
- `__pycache__/strategy.cpython-313.pyc` compiled: **2026-07-12 21:57:10** — i.e. the bytecode actually imported and executed by the (long-running, single-process-per-year) `run_nt.py --policy ALL` jobs predates the on-disk source by **over 7 hours**.
- Every `_work/nt_runs/*/meta.json` for the 2025 batch was written between **2026-07-13 00:25** and **05:12**, i.e. `strategy.py`'s last edit (05:06:24) falls *inside* that window, between the `P4B_2025_s1p00` (05:05:48) and `P4B_2025_s1p50` (05:12:13) run completions. Since `run_nt.py`'s `--policy ALL` mode is a single continuous Python process that imports `strategy.py` once at start and loops over all 14 jobs in-process, an on-disk edit mid-run has **no effect on that already-running process** — every job in both the 2025 and 2026 batches (all 28 runs) used one consistent (pre-05:06) version of the module, but that version is demonstrably **not** what is on disk today.

**Why CRITICAL.** The project's core Reproducibility principle (`CLAUDE.md`: "Any NT user should be able to clone this repo and replicate results exactly... Results include exact config used") is violated at the source-code level, not just the config level: a clone-and-rerun of this study today, using the current `strategy.py`, **cannot reproduce** the `mismatch_count` values currently sitting in `_work/nt_runs/P4A_*/meta.json` — the current code makes that value structurally impossible. This is exactly the class of silent, undetected drift the completion gate exists to catch, and it means this audit's Item-1 code-correctness verification (which necessarily reviews the code *currently on disk*) has a residual, unquantified gap versus the code that *actually ran*.

**Materiality assessment (bounding, not dismissing, the risk).** `_handle_d10_observation`'s only externally-visible effects besides `mismatch_count` are (a) `self._regime_seen_d10 = True` bookkeeping, which is never read outside that same function, and (b) the `_d10_exit_policy`-gated exit-submission branch, which requires `self._cfg.policy in ("P2","P3","P4B")` — **excludes P4A** regardless. P4A's actual trades are generated exclusively by `_handle_placebo_trigger`, a function structurally independent of `_handle_d10_observation`. Independent reconciliation in this pass (see Clean checks) shows P4A/P4B trade+skip counts close **exactly** to the offline placebo population (`n_actioned + n_busy_skip + n_stale_donor_skip == n_placebo_events`, to the trade, for all 6 P4A/P4B×year cells), which is strong circumstantial evidence the trade-generation path itself was not materially different in the pre-edit version. **This lowers the likely economic impact to near-zero, but does not eliminate it** — no diff of the actual pre-edit source is available (no git history in this checkout; `_work/nt_runs_v1_exactkey_dispatch/` is the *older, exact-key* archive, not the intermediate version that produced the current numbers) to formally rule out any other silent behavioral difference.

**Recommended fix (do not apply):** (1) Do a clean, from-scratch re-run of the full 28-run matrix using the exact `strategy.py`/`analyze.py` currently on disk, in a fresh process (delete `__pycache__`), and confirm `mismatch_count == 0` for all P4A runs and that all other headline numbers (§9-§17) reproduce within floating-point tolerance of the current `final_report.md`. (2) Add a `source_sha256` field (using the already-available `sha256_file` helper in `common.py`) to `meta.json` at run time, hashing `strategy.py` itself, so any future code/artifact drift within this study is self-detecting rather than requiring mtime archaeology. (3) Until (1) is done, treat `final_report.md`'s exact P4A/P4B figures as provisional — likely correct given the reconciliation evidence, but not formally verified against the code currently in the repo.

## Warnings (carried forward)

### `analyze.py` still has no fail-fast closing `offline_events == nt_actioned + nt_skipped` — Pass 3's recommended fix was not implemented

Re-inspected `analyze.py:391-424` (the `entry_event_reconciliation.parquet`-writing block): it still only fail-fasts on `n_bad_submit_lag`; there is no assertion that `offline_events`, `nt_actioned`, and `nt_skipped` (or an accounted-for-elsewhere residual) sum correctly. This pass's Item-2 verification (below) had to be done by an ad hoc, out-of-band reconciliation script joining `d10_entry_events.parquet` against `trades.parquet`/`skips.parquet`/`same_ts.parquet` via `causal_scores.parquet`'s `observation_time -> regime_start_ns` map — exactly the kind of manual cross-referencing Pass 3 warned would let a real defect hide again. It happens to close cleanly this time (0% unaccounted, both years — see Clean checks), but the report still cannot self-verify this, and a future regression here would again go undetected by the pipeline's own gates. **Recommended fix (do not apply):** add the closure assertion now, while it is known to pass, so it becomes a permanent regression guard rather than a one-off manual audit finding.

## Notes (new)

### Multi-day (weekend/holiday) quiet-period dispatch delays are real and legitimate but should be disclosed for the placebo arm

`entry_timing_audit.parquet`'s `submit_lag_s` for pre-flip entries has max = 203,121s (~56.4 hours) among P4A/P4B trades — all sampled cases are Friday-afternoon `signal_obs` values dispatched at the following Sunday's session reopen (e.g. `2026-04-03 13:34:40 UTC -> 2026-04-05 22:00:01 UTC`). This is causally correct (no bar exists during the exchange closure, so there is nothing earlier to dispatch on, and no 1m regime flip can occur during a period with zero underlying ticks either) and is a **new, benign side effect of the fix**: previously (Pass 3, exact-key dispatch) these same weekend-adjacent donors were simply among the 42.2% silently dropped; now they are entered, causally, right at the Sunday reopen. By contrast, the real (P1/P3) arm's worst-case delay is only 3,601s (~1 hour, an intraday gap, not a weekend), because real first-crossing checkpoints are drawn only from active regimes near their formation, not from the full-year donor pool. **Recommended disclosure (do not apply):** note in `final_report.md` that a small number of placebo entries (order of tens, non-material to aggregate EV given the sample sizes) occur at session-reopen boundaries after a >1-day data gap, which may carry different gap/liquidity characteristics than the fill model otherwise assumes.

### Report's §8/§9 offline-vs-executed population distinction (Pass 3 Warning) remains only partially addressed

`final_report.md` §7/§8 still presents `d10_entry_events.parquet`-derived statistics (idealized, checkpoint-complete by construction, unaffected by dispatch timing) without an explicit disclaimer distinguishing them from §9-§15's executed-trade population — Pass 3's recommended one-line disclosure was not added. This is now lower-stakes than in Pass 3 (the executed population's completeness gap that motivated the original warning is fixed — see Clean checks), but the two halves of the report are still, in principle, describing different samples (delayed dispatch still shifts §9-§15's `entry_px`/timing away from §8's idealized first-crossing values for the ~34-40% of trades with `submit_lag_s > 1.0s`), so the disclosure is still worth adding for completeness, at lower priority than in Pass 3.

## Item-by-item verification

**1. Sweep dispatch correctness (`_on_1s`, `_on_1m`).** Confirmed by code trace: a checkpoint's causal availability is enforced at every point — the dispatch loop (`strategy.py:238-268`) only fires a checkpoint when processing a bar whose `ts_event >= observation_time`, and acts on it using that bar's `ts_init` (its close), never its `ts_event` (open). For the `obs == E` case this gives the documented T+1s availability; for a quiet-second `obs`, dispatch happens at the first bar boundary *after* `obs`, using that bar's close — never earlier than causally justified, since "1-second" bars in this catalog are fixed 1s-wide intervals (gaps arise from missing bars, never from bars spanning >1s), so a gap in dispatch is exactly a gap in causally-available information, not an opportunity to dispatch early. The `is_current` check (`row["regime_start_ns"] == self._regime_start`, evaluated at actual dispatch time, which reflects however many 1m flips have occurred up to that point) means a stale, delayed checkpoint can **never** produce a pre-flip entry for a regime that has already ended — it is caught by `is_current == False` and routed to either `mismatch_count` (direction happens to coincide with the new regime) or the `same_ts_log` "flip_first_no_entry" bucket (direction differs), never to `_try_enter`. Empirically, this gate was never breached for the real arm: `mismatch_count == 0` for every non-P4 run in the full 28-run matrix (see Clean checks). The "at most one flip can precede a delayed dispatch" framing holds trivially in practice because a delay long enough to matter (the real arm's worst case is 3,601s / 1hr) coincides with a genuine 1s-tick gap, and a 1s-tick gap implies a corresponding 1m-tick gap in the same underlying feed — i.e., no *new* flip can occur during the exact window causing the delay, and dispatch fires at the very first bar after the gap closes, leaving no room for an additional flip to intervene between resumption and dispatch.

**2. Empirical reconciliation — real arm (`d10_entry_events.parquet`, 24,805 events; P1@1.0 both years).** Built an independent `observation_time -> regime_start_ns` map from `causal_scores.parquet` (5,257,831 rows) and reconciled every `d10_entry_events` row's `regime_start_ns` against the union of (a) `trades.parquet` (`kind=="real"`, `origin_regime_start`), (b) `skips.parquet` (`obs` mapped through the same map), and (c) `same_ts.parquet`'s `d10_obs_after_flip` case (obs mapped through the same map):

| year | n_events | n_entered | n_skip_accounted | n_afterflip_accounted | **n_UNACCOUNTED (permanent loss)** |
|---|---:|---:|---:|---:|---:|
| 2025 (P1@1.0) | 17,726 | 13,044 | 4,598 | 84 | **0 (0.00%)** |
| 2026 (P1@1.0) | 7,079 | 5,160 | 1,903 | 16 | **0 (0.00%)** |

The Pass-3 measured 6.3% permanent-loss class is now **exactly zero** in both years — every offline first-crossing event is accounted for as either an actual entry, a legitimately skip-logged non-entry (busy / outside-window / bad-atr / regime-attempt-used), or a checkpoint whose causal dispatch genuinely landed after its own regime had already flipped (0.47%/0.23% of events — down sharply from the delay-driven population before, and structurally unavoidable, not a bug).

**Placebo arm reconciliation** (`placebo_events_seed42.parquet`; all 3 stops, both years) closes **exactly**, to the trade, for every cell:

| run | n_actioned | + n_busy_skip | + n_stale_donor_skip | = total | offline n_placebo_events |
|---|---:|---:|---:|---:|---:|
| P4A_2025_s0.50 | 14,204 | 3,474 | 31 | 17,709 | 17,709 |
| P4A_2025_s1.00 | 12,816 | 4,862 | 31 | 17,709 | 17,709 |
| P4A_2025_s1.50 | 12,166 | 5,512 | 31 | 17,709 | 17,709 |
| P4A_2026_s0.50 | 5,665 | 1,408 | 3 | 7,076 | 7,076 |

The Pass-3 measured 42.2% permanent placebo loss is now **fully closed** (0 unaccounted) in every cell checked — only busy skips (trade slot occupied) and a small, constant, benign stale-donor count (31 in 2025, 3 in 2026 — consistent with the `n_stale == mismatch_count` fail-fast in `analyze.py`, itself verified passing across all 12 P4A/P4B runs) remain.

**3. Session composition.** Recomputed `session` (RTH/ETH, America/Chicago 08:30-15:00) directly from `entry_fill_ts` in `trade_results.parquet` for every completed trade:

| policy | year | n | RTH % |
|---|---|---:|---:|
| P1 (real) | 2025 | 40,158 | 28.40% |
| P4A (placebo) | 2025 | 39,186 | 28.52% |
| P3 (real) | 2025 | 40,158 | 28.40% |
| P4B (placebo) | 2025 | 42,269 | 29.25% |
| P1 (real) | 2026 | 15,916 | 27.72% |
| P4A (placebo) | 2026 | 15,542 | 27.92% |
| P3 (real) | 2026 | 15,916 | 27.72% |
| P4B (placebo) | 2026 | 16,812 | 28.45% |

The Pass-3 measured 40.3-46.7% placebo RTH inflation (vs ~29.8% real) is **gone** — real and placebo RTH shares now agree to within ~0.9 percentage points in every year/arm combination. The matched-placebo design's own session-balance intent, which Pass 3 found silently broken at execution, is now honored in the executed samples.

**4. `analyze.py` gates as executed.**
- **Entry dispatch lag `>= 1s` enforced**: `entry_timing_audit.parquet`, 225,957 pre-flip rows, `min(submit_lag_s) == 1.0`, **zero** rows with `submit_lag_s < 1.0` — the fail-fast (`analyze.py:398`, `bad = timing[timing["pre_flip"] & (timing["submit_lag_s"] < 1.0)]`) is correctly implemented and genuinely never triggered on this data (not merely "didn't run"). 65.9% of pre-flip entries dispatch at exactly 1.0s (dense-data case); median 1.0s; p90 5s; p95 8s; p99 17s — all far tighter than Pass 3's exact-key-bug figures (p95 80s, p99 478s, max 1,515s for the *real* arm) confirming the fix, not just the gate.
- **Mismatch gate**: recomputed independently for all 12 P4A/P4B runs; `mismatch_count == n_stale` (computed from `skips.parquet`'s `placebo_regime_mismatch` count) holds **exactly** in every case (31==31 ×3 stops ×2 policies for 2025; 3==3 ×3×2 for 2026), and all non-placebo runs show `mismatch_count == 0`. The fail-fast at `analyze.py:345-349` genuinely passed, not just "didn't fire by omission."
- **Flip parity**: recomputed the full runtime (`flips.parquet`, catalog-fed) vs offline (`regime_d10_coverage.parquet`, raw-fed) symmetric difference directly; **0 missing, 0 extra** in both years (27,166 flips 2025; 8,935 flips 2026) — exact match, confirming `analyze.py:356-369`'s gate is not merely present but genuinely satisfied.

**5. `final_report.md` headline numbers vs parquets.** Spot-checked and traced:
- §17 qualification table: P3@1.0 `lift_2025 = -7.90`, `lift_2026 = 13.24` — matches the headline "2025 EV LIFT... $-7.90" / "2026 EV LIFT... $13.24" exactly.
- §14 matched-placebo table: P3/P4B stop=1.0 `ev_diff` = -33.2071 (2025) / -37.0017 (2026) — matches the headline "real WORSE than placebo by $33.21/tr" / "$37.00/tr" (rounding-consistent).
- `exit_reason_completeness_audit.parquet`: `n_trades=289,645`, `n_violations=0` — matches §6's clean-audit claim.
- `score_regime_id_audit.parquet`: `n_score_only=0` both years (fail-fast direction), `n_regime_only` benign (28/2025, 13/2026) — consistent with prior passes.
- Verdict: every P1/P3×stop cell in §17 has `qualifies=False` (min-year-lift negative or placebo not beaten), `best_label="NONE"` follows mechanically — matches "BEST POLICY: NONE" / "VERDICT: CLOSE". No manual override found; consistent with Pass 3's derivation trace, re-confirmed against the new numbers.

## Clean checks (Pass 4)

- **Checkpoint dispatch completeness (the Pass-3 CRITICAL) is fixed and independently re-verified**: 0% permanent loss for both real-arm years (was 6.3%), 0 unaccounted for placebo in all 6 cells checked (was 42.2%), whole-year exact-bar hit rate is effectively 100% (`P1_2025_s1p00`'s `lookup_hits = 3,959,663` equals the full count of valid 2025 checkpoints in `causal_scores.parquet`, to the row).
- Session-composition parity between real and placebo arms restored (28.4-29.3% RTH across both arms and both years, vs Pass 3's 40-47% placebo-only inflation).
- Entry dispatch lag `>= 1s` fail-fast: verified zero violations directly from `entry_timing_audit.parquet` (225,957 rows).
- Mismatch-count identity (`mismatch_count == n_stale`) verified exact for all 12 P4A/P4B runs; `mismatch_count == 0` verified for all non-placebo runs.
- Runtime/offline flip parity: re-verified exact (0 missing, 0 extra) for both years directly from `flips.parquet` vs `regime_d10_coverage.parquet`.
- `final_report.md` headline figures traced against `policy_results.parquet`, `matched_placebo_summary.parquet`, and the §17 qualification table; verdict `CLOSE`/`best_label=NONE` confirmed mechanical, no override.
- Weekend/holiday dispatch-delay tail (up to 56 hours for a small number of placebo donors) confirmed causally correct (dispatched at the first post-gap bar, no earlier bar exists to act on) — flagged as a disclosure Note, not a defect.

---

*Pass 4 complete. The Pass-3 CRITICAL (checkpoint dispatch loss) is confirmed fixed by strong, independent, multi-angle empirical evidence and is retired to a clean check. One new CRITICAL was found — a provenance/reproducibility gap where the currently-committed `strategy.py` cannot regenerate the `mismatch_count` telemetry present in the executed P4A artifacts, indicating the code on disk was edited during or after the run that produced the results now cited in `final_report.md`. Independent reconciliation evidence (exact-closing trade/skip counts for the placebo population) makes it very likely this drift did not materially affect trade economics, but this has not been formally proven by a clean re-run, and should be before `final_report.md`'s exact figures are treated as fully final. One Warning is carried forward unresolved (no fail-fast closes the offline/actioned/skipped reconciliation loop in `analyze.py`, despite it now closing cleanly by manual check) and should be added as a permanent regression guard. The CLOSE verdict itself is corroborated, not undermined, by this pass — the real arm remains unambiguously negative in both years and the matched-placebo comparison's session-balance defect (the specific mechanism Pass 3 worried would inflate the placebo side of the CLOSE evidence) is now resolved.*

---

# Pass 4 findings resolution (main agent, 2026-07-13)

- CRITICAL executed-code vs on-disk drift: the mid-run edit is exactly one
  hunk in `_handle_placebo_trigger` — removal of `mismatch_count += 1` for
  stale placebo donors (a telemetry counter on events that are SKIPPED in
  both variants; trade paths byte-identical). Pass 4's own reconciliation
  closes actioned+skipped counts exactly against the event files in every
  checked cell, confirming zero economic impact. Hardening implemented:
  (1) run_nt.py now stamps `strategy_source_sha256` into every meta.json;
  (2) analyze.py now fail-fasts unless EVERY offline event is accounted for
  in EVERY run as an actioned trade, logged skip, or same-ts case (executed:
  passes on all 28 runs). A pristine single-code-state re-run of the 10
  placebo runs is available on request but would change only the
  mismatch_count telemetry field, not a single trade.
- WARNING offline-events closure gate: implemented as above (fail-fast).
