# Look-Ahead & Timestamp Audit (Pre-Execution, Stage 1 only)

**Date:** 2026-07-13
**Scope:**
- `studies/fable5_established_regime_weakness_fade/SPEC.md`
- `studies/fable5_established_regime_weakness_fade/common.py`
- `studies/fable5_established_regime_weakness_fade/build_stage1.py`
- Context (read-only, for provenance/convention checks): `studies/regime_sequence_chop_context/reproduce_regimes.py`,
  `studies/regime_sequence_chop_context/build_weakness_atlas.py`,
  `studies/fable5_pre_flip_d10_reversal_entry/SPEC.md`,
  `studies/fable5_pre_flip_d10_reversal_entry/build_scores.py`

**Auditor:** lookahead-auditor v1 (pre-execution gate — Stage 1 has not yet been run)

This audit is a **pre-execution** gate: `build_stage1.py` has not produced any
`results/` artifacts yet. Per CLAUDE.md's pre-execution trigger, this is
required before first run because the study reuses stop/exit and checkpoint
mechanics from a prior study "verbatim" and defines Stage-2 filter components
that must be causal.

## Summary

- Critical: 2
- Warning: 4
- Note: 2

## Critical findings

### [A2/A4] `w4_at_end` structurally reads ~1s into the FOLLOWING regime for every non-timed-out regime

`build_stage1.py:122-124` (`w4_at`), `:140-141` (half-open `[a,b)` slicing used
for MFE), `:170` (`end = r.regime_end_ns`), `:193` (`"w4_at_end": w4_at(obs_arr, sc_arr, end)`).
Upstream construction: `studies/regime_sequence_chop_context/build_weakness_atlas.py:42-59`
(`idx_cp = searchsorted(ts_arr, cp_ts, side='right') - 1`; `current_price =
close_arr[idx_cp]`, i.e. the close of the 1s bar whose **open** is `<= cp_ts`).

`w4_at(x_ns)` selects "last checkpoint with `observation_time <= x_ns`"
(correct definition per item 4 of the audit brief), but for `w4_at_end` the
query point `x_ns = end = regime_end_ns` is the regime's own boundary. Two
facts combine to make this a structural (not edge-case) bug:

1. Every `regime_start_ns` / `regime_end_ns` is a 1m-bar `close_ts`, hence an
   **exact multiple of 60s**. The atlas checkpoint step is 30s (train) or 5s
   (val/test), and the 1800s age cap is a multiple of both. Therefore, for
   **every regime whose duration is < 1800s** (i.e. did not hit the W4
   scoring age cap — the majority per SPEC.md:44-45's own framing), the
   checkpoint arithmetic in `build_weakness_atlas.py:26`
   (`arange(flip_ts+step, ep_end_ts+1, step)`) is *guaranteed* to emit a
   checkpoint at `cp_ts == opp_flip_ts == regime_end_ns`, because 60s is an
   exact multiple of both 30s and 5s.
2. That checkpoint's own feature snapshot (`current_price`, and everything W4
   is scored on) is built from the 1s bar whose **open equals `cp_ts`**, i.e.
   `[regime_end_ns, regime_end_ns+1s)` — which is, by this same file's own
   half-open `[start, end)` convention used four lines away for MFE
   (`build_stage1.py:140-141`), the **first second of the NEXT (opposite)
   regime**, not the ending regime.

Net effect: `w4_at_end` — one of the headline descriptive fields in
`MED_COLS` (`build_stage1.py:213-216`) feeding the SPEC's own "Key contrast:
7 vs 6" (SPEC.md:70) and the cohort medians table — is, for essentially all
non-timed-out regimes, computed from a checkpoint that has already seen one
second of the confirmed opposite move. This mechanically inflates how
"terminal" W4 appears to look right at the regime's own end, exactly the
quantity this study exists to characterize. It is internally inconsistent
with the file's own correct half-open treatment of the same boundary for MFE.

**Recommended fix (do not apply):** exclude the boundary itself from every
`w4_at_*` lookup, consistent with the `[start, end)` convention used
elsewhere in this file and with the prior study's own rule
("a crossing whose `observation_time` equals the regime's end `close_ts` is
not causally pre-flip" — `fable5_pre_flip_d10_reversal_entry/SPEC.md:87-89`).
E.g. query `w4_at(obs_arr, sc_arr, end - 1)` (or filter `obs_arr < end`
before the search) for `w4_at_end` specifically, and consider doing so
uniformly for all `w4_at_*` calls for defense in depth.

**STATUS AS OF PASS 2: FIXED.** See "Pass 2" section below.

### [D2] Stage-2 filter components `new_progress_windows` / `retained_mfe_ratio` are specified as causal but Stage 1 only computes their hindsight/full-regime counterparts

`SPEC.md:74-78`: "Filter (values finalized from Stage-1 train medians, frozen
before 2026): regime_age >= threshold, running_mfe_atr >= 1.0,
new_progress_windows >= 2, retained_mfe_ratio >= 0.50 — **all computable
causally bar-by-bar**."

`build_stage1.py:156-162` computes `new_progress_windows` as a single count
over the **entire** regime window `[a,b)` (i.e. `regime_start_ns` to
`regime_end_ns` — the full future is known before the count is taken).
`build_stage1.py:184-186` computes `retained_ratio = flip_pnl_atr /
peak_mfe_atr`, where `flip_pnl_atr` (`:138`) is itself only knowable at the
regime's end (it uses `px1 = closes[e0]`, the exit/flip price). Neither
field is indexed "as of trigger time X" the way `w4_at_qual` /`w4_at_peak`
etc. are — both are single full-regime hindsight aggregates attached to the
regime row.

SPEC.md's own language ("values finalized from Stage-1 train medians")
implies whoever builds Stage 2 will read `med_new_progress_windows` and
`med_retained_ratio` (or per-cohort equivalents) straight out of Stage 1's
cohort summary and use them to calibrate live thresholds. But a live/causal
`new_progress_windows` at an arbitrary mid-regime decision point (how many
progress clusters have occurred **so far**) and a live `retained_mfe_ratio`
(current unrealized P&L relative to the running-max-so-far) are different
quantities from the full-regime totals Stage 1 currently produces — the
full-regime count is always `>=` the count available at any earlier decision
point, and the final ratio uses the regime's actual exit price rather than
"current" price. No code path in this study yet computes the bar-by-bar
versions of either quantity. Directly reusing Stage 1's hindsight medians as
Stage-2 threshold calibration inputs for the same-named causal filter
components would silently calibrate a live filter against a systematically
more favorable (fuller-information) distribution than what will actually be
observable at each candidate trigger — a genuine train/serve skew, not
merely a documentation gap, because the two computations share a name but
not a definition.

**Recommended fix (do not apply):** before Stage 2 is built, add a bar-by-bar
/ "as of decision time X" computation of both quantities (e.g. running count
of progress-window clusters observed up to X, and `current_pnl_at_X /
running_mfe_at_X`) alongside the existing hindsight fields, clearly renamed
(e.g. `new_progress_windows_asof` / `retained_ratio_asof`) so Stage-2
threshold-freezing is calibrated against the same causal quantity the live
filter will evaluate. This is exactly the kind of state-machine/filter logic
CLAUDE.md's pre-execution trigger calls out for auditing before first run.

**STATUS AS OF PASS 2: PARTIALLY FIXED.** `retained_{qual,peak,m60,m30,flip}`
are now genuinely causal (computed as-of a specific decision boundary X, see
Pass 2 below). `new_progress_windows` remains an unfixed full-regime
hindsight aggregate with no bar-by-bar counterpart anywhere in the repo —
this half of the finding is still open. See "Pass 2" section.

## Warnings

### [A2/A4] General ~1s embedded look-ahead in every atlas checkpoint feature, not restated in this study's SPEC

Beyond the structural boundary bug above, every `w4_at_*` lookup inherits a
smaller, universal issue: a checkpoint labeled `observation_time = T` is
itself built (`build_weakness_atlas.py:44,59`) from the 1s bar whose **open**
is `<= T`, i.e. its `current_price`/derived features reflect information up
to that bar's **close**, `T + 1s`. The prior study's SPEC explicitly
disclosed this ("the checkpoint... is therefore causally available at wall
clock T+1s" — `fable5_pre_flip_d10_reversal_entry/SPEC.md:56-60`), but this
study's own definition of "W4 score at time X" (`SPEC.md:63-66`) only says
"descriptive; availability rate reported" without restating the +1s
construction lag. For most `X` values here (qualification touch, peak,
end-60s, end-30s) this is immaterial relative to the 5-30s checkpoint
cadence, but since "these medians will inform the Stage-2 trigger choice"
(per the audit brief), the lag should be explicitly disclosed in this
study's SPEC.md, not only inherited by reference.

**Recommended fix (do not apply):** add one sentence to SPEC.md's "W4 score
at time X" definition stating the inherited +1s construction lag and its
assessed immateriality for non-boundary `X` values (contrast with the
boundary case above, which is material).

**STATUS AS OF PASS 2: FIXED (generalized, not just disclosed).** The revised
`attach_w4()` applies the `observation_time + 1s <= target` rule uniformly to
all five `X` values (qual/peak/m60/m30/flip), not only to the boundary case.
See Pass 2 below.

### [G-general / SPEC disclosure] Silent, uncounted exclusions beyond the documented censored-last-regime case

SPEC.md:46 promises "Regimes censored at year end (no final flip) are
excluded **and counted**." `build_stage1.py:95-96` does exclude the last
(censored) regime (`frows[:-1]`) but there is no counter, print statement, or
output column anywhere in the script recording *how many* were excluded per
year — the "counted" half of the promise is not implemented.

In addition, three other silent `continue` paths drop regimes with no
counting or reporting at all:
- `:129-130` — non-finite or `<= 0` `atr_at_start`.
- `:132-134` — `s0 < 0 or e0 <= s0` (degenerate executable-price indices).
- `:141-143` — `b <= a` (empty MFE window).

None of these is necessarily wrong to exclude, but with zero visibility a
silent change in upstream data (e.g. a gap that pushes more regimes into one
of these branches) would change Stage-1 sample composition without any
signal in the output.

**Recommended fix (do not apply):** accumulate and print/report per-year
counts for the censored-last-regime exclusion and each of the three
`continue` branches (e.g. a small `exclusions` dict written alongside the
cohort summary parquet).

**STATUS AS OF PASS 2: PARTIALLY FIXED.** `stage1_build_reconciliation.json`
(`build_stage1.py:302-309`) now reports `censored_rows` explicitly — the
"and counted" half of SPEC.md:46's promise is met for that specific case.
The other three silent `continue` branches (non-finite ATR, degenerate
anchor/exit index, empty MFE window — now at `build_stage1.py:141-146`) are
still uncounted individually; only the aggregate gap
(`source_f1_rows - censored_rows - completed_metric_rows`) is recoverable by
subtraction, with no breakdown by reason. Downgraded to a Note in Pass 2
given the main promise is now honored.

### [C3 / chronology] No guard against mixing discovery (2021-2024) and validation (2025) years in one Stage-1 run

`build_stage1.py:238-239` only asserts `y != 2026` per requested year; there
is no assertion that `args.years` is either exactly the training set or
exactly `[2025]`. A run of `python build_stage1.py --years 2021 2022 2023
2024 2025` would silently succeed, tag its output
`stage1_regime_metrics_2021_2022_2023_2024_2025.parquet` (`:253-254`), and
combine discovery and validation rows into one `stage1_cohort_summary_*`
table — exactly the "train vs. validation" chronological boundary SPEC.md's
"Chronology (hard)" section (lines 14-19) is meant to enforce. Nothing in
the code prevents a human from reading medians off that combined summary as
if they were pure-discovery.

**Recommended fix (do not apply):** add an explicit assertion that
`set(args.years)` is either `set(TRAIN_YEARS)` (or a subset) or exactly
`{2025}`, rejecting any mix of `<=2024` and `2025` years in a single
invocation.

**STATUS AS OF PASS 2: MOOT / RESOLVED BY REWRITE.** The rewritten
`build_stage1.py` no longer accepts a `--years` CLI argument at all; `main()`
(`:288-314`) unconditionally processes `range(2021, 2026)` and writes a
single `stage1_regime_metrics.parquet` tagged with a `period` column derived
from each row's own year (`:202`), not from a run-time argument. The new
`evaluate_stage1.py` splits strictly on `period == "train"` /
`period == "validation"` (`:112-113`) and requires **both** gates to pass
(`:130-132`) before emitting `ESTABLISHED_REGIME_FILTER_FOUND`. The
mixed-invocation failure mode this warning described is no longer
constructible.

### [D-general / hygiene] `load_scores()` pulls all of `SCORES_2025_2026` (including 2026 rows) whenever any requested year is >= 2025

`build_stage1.py:75-86`; path defined at `common.py:19`. When `years`
includes 2025 but not 2026 (e.g. a future `--years 2025` validation run), the
`if any(y >= 2025 ...)` branch loads the **entire** `causal_scores.parquet`
file — both 2025 and 2026 rows — with no year filter, then concatenates it
into `scores`. This is functionally safe *today* only because
`observation_time`/`regime_start_ns` are absolute epoch-nanosecond values,
and 2025 and 2026 wall-clock ranges are numerically disjoint (no key
collision is possible), so `regime_metrics`'s `scores.groupby
("regime_start_ns")` lookup by an actual 2025 regime's start can never match
a 2026 row. There is, however, no explicit filter or assertion encoding that
safety — a future change (e.g. a relative/mod-based key, or reusing this
loader for a different join) could silently reintroduce 2026 rows into a
2025-only analysis without any visible symptom.

**Recommended fix (do not apply):** load the `year` column from
`causal_scores.parquet` (already written by
`fable5_pre_flip_d10_reversal_entry/build_scores.py:85`) and filter
`s[s["year"].isin(years)]` explicitly, both for defense-in-depth and to
avoid needlessly holding 2026 rows in memory for a 2025-only run.

**STATUS AS OF PASS 2: MOOT / RESOLVED BY REWRITE.** `build_causal_scores()`
(`build_stage1.py:28-96`) no longer branches on requested years at all; it
streams every row group of `WEAKNESS_ATLAS` and filters every row group by
absolute timestamp (`d = d[d["observation_time"] < cutoff_2026]`,
`build_stage1.py:52`), with a hard `assert max_observation_time <
cutoff_2026` (`:85`) before the function returns. There is no longer a
conditional "load everything" branch to regress.

## Notes

### No automated regime/timestamp parity check against the upstream atlas

Unlike the prior study, which ships
`audit/score_regime_id_audit.parquet` to verify its independently re-run
`RegimeEngine` produces identical flip/regime keys to the atlas it joins
against, `build_stage1.py` has no equivalent check. A *systematic* mismatch
(e.g., a different flip-bar close convention) would likely be self-evident
(near-zero `n_score_cp` / `w4_end_availability` across the board on first
run), but an explicit assertion (e.g. "median join hit rate > X%") would
surface it faster and more legibly than eyeballing a summary table.

**STATUS AS OF PASS 2: ESCALATED TO CRITICAL.** This note's premise — "a
systematic mismatch would likely be self-evident" — turns out to be false in
practice for the specific failure mode found in Pass 2 (see new Critical
finding below): a real regime-identity provenance defect is present in the
exact upstream artifact this note was worried about, it is *not* self-evident
(it produces a plausible, non-degenerate, non-zero-everywhere summary table),
and no parity check anywhere would have caught it without directly comparing
the `direction`/`regime` columns row-by-row, which is what this audit pass
did. See Pass 2, Critical Finding 1.

### Guard against silently swapping a Stage-1 median for the frozen W4 threshold

`MED_COLS` (`build_stage1.py:213-216`) includes `med_w4_at_qual`,
`med_w4_at_peak`, `med_w4_end_m60`, `med_w4_end_m30`, `med_w4_at_end` —
purely descriptive score levels. The operating threshold for any live W4
trigger must remain the frozen `0.618328` (`SPEC.md:79`,
`common.py:frozen_threshold()`), verbatim from the prior study. Recommend an
explicit comment (or assertion) in any future Stage-2 script that the trigger
threshold is read only from `frozen_threshold()`, never from a Stage-1
cohort median, to close off an easy copy-paste trap.

**STATUS AS OF PASS 2: STILL OPEN, unchanged.** Stage 2 has not been built.
Reaffirmed as a forward-looking note for whoever writes Stage 2.

## Clean checks

- Chronology: `main()` (`build_stage1.py:238-239`) hard-blocks any requested
  year `== 2026`; `build_train_scores()` filters `period == "train"` only
  (`:51`); `SCORES_2025_2026` load is separate from train scoring — no path
  currently mixes 2026 into a train-year run.
- In-sample disclosure: both the code docstring
  (`build_stage1.py:1-8, 36-40`) and `SPEC.md:37-40` clearly disclose
  2021-2024 W4 scores as in-sample; the frozen D10-style threshold
  (`0.618328`) is reused verbatim and not re-derived from these in-sample
  scores.
- Executable price convention: `s0 = searchsorted(ts, start, 'left') - 1`
  (and symmetric for `e0`) matches SPEC.md:52 ("last 1s close before the
  flip boundary") and the prior study's documented P0/NT fill convention.
- MFE / progress-window / first-touch computations are all backward-looking
  (`np.maximum.accumulate`, `prev_max` built from `run_max[:-1]`,
  `np.argmax` returning the *first* max) — no `shift(-N)`, no `center=True`,
  no `.bfill()` anywhere in scope.
- Regime slice for MFE/progress-window purposes correctly uses the
  half-open `[regime_start_ns, regime_end_ns)` convention by open time
  (`build_stage1.py:140-141`) — this is the convention the `w4_at_end`
  finding above shows is *not* applied consistently to the checkpoint
  lookup itself.
- ATR (`atr_at_start`) is read directly from the flip bar's own engine state
  (`Wilder` recursive TR/ATR, fully causal, no future bars) —
  `reproduce_regimes.py:42-54`.
- RTH/ETH classification uses regime **start** time (`build_stage1.py:106`,
  per `SPEC.md:71`) via a UTC-aware, DST-safe `tz_convert("America/Chicago")`
  (`common.py:46-54`) — no naive-datetime risk.
- `RegimeEngine` is instantiated fresh per year
  (`aggregate_and_run_regimes` in `reproduce_regimes.py:112`, called once per
  `yr` in `build_stage1.py:246`), matching the documented atlas-seeding
  convention.
- No pandas rolling/ewm/expanding calls, no `.ffill()`/`.bfill()`, no merge
  with ambiguous direction in scope — the study uses hand-rolled
  `searchsorted` joins that are the causal equivalent of
  `merge_asof(direction="backward")`.
- Section H (offline bracket simulation) is not yet applicable: Stage 1 does
  not simulate any stop/PT/trigger fill; this must be re-audited before
  Stage 2's first execution once the bracket/stop mechanics described in
  `SPEC.md:80-90` are implemented, per CLAUDE.md's pre-execution trigger for
  reused stop-timing mechanics.

---

*Audit complete. Findings reflect read-only static analysis of Stage 1 code
prior to its first execution. No `results/` artifacts exist yet for this
study; nothing here reflects observed output, only code/spec inspection.*

---

## Pass 2 — revised Stage 1 (2026-07-13)

**Trigger:** re-audit requested after a substantial rewrite of `build_stage1.py`,
a new `evaluate_stage1.py`, a predeclared `STAGE1_GATE` in `common.py`, and a
frozen-gate section added to `SPEC.md`. Nothing has been executed yet — this
remains a pre-execution gate.

**Scope (current versions re-read in full):**
- `studies/fable5_established_regime_weakness_fade/SPEC.md` (lines 1-119,
  "Predeclared Stage-1 gate" at 74-95)
- `studies/fable5_established_regime_weakness_fade/common.py` (85 lines, full file)
- `studies/fable5_established_regime_weakness_fade/build_stage1.py` (315 lines, full file)
- `studies/fable5_established_regime_weakness_fade/evaluate_stage1.py` (163 lines, full file, new)
- `studies/regime_sequence_chop_context/build_flip_atlas.py` (F1 construction,
  `opposing_flip_time` semantics, lines 145-402)
- `studies/regime_sequence_chop_context/build_weakness_atlas.py` (checkpoint
  construction, lines 1-80)
- `studies/regime_sequence_chop_context/run_study.py` (incremental-cache /
  year-skip logic, lines 120-165, 322-326)
- Direct read-only column inspection of the on-disk artifact
  `studies/regime_sequence_chop_context/results/flip_context_atlas.parquet`
  (via pandas, read-only — no pipeline code executed), to verify claims made
  by `load_regime_population` about `direction`/`regime`/`opposing_flip_time`
  that cannot be settled by reading source alone.

### Summary (Pass 2)

- **New Critical: 1** (severe — blocks execution)
- Critical carried forward, still open: 1 (progress-windows half of D2)
- Resolved since Pass 1: 2 critical, 2 warnings (moot-by-rewrite)
- Warning downgraded to Note (partially fixed): 1
- New Note: 1 (escalation cross-reference, folded into critical below)

### Critical findings (Pass 2)

#### [G3 / provenance] `direction` is 100% NaN for the entire in-scope population (2021-2025); the `fillna(regime)` fallback at `build_stage1.py:106` is not a defensive no-op — it is the *sole* source of every regime's direction sign, and the one year where it is checkable against ground truth shows a large, session-dependent disagreement rate

`build_stage1.py:99-106`:
```python
d["direction"] = d["direction"].fillna(d["regime"]).astype(np.int8)
```
This line was read in the prior pass as a defensive fallback for occasional
missing values. Direct inspection of the actual on-disk
`flip_context_atlas.parquet` (F1 population, the exact rows
`load_regime_population` reads) shows this is not an edge case:

```
year   n_F1_rows   direction_NaN_fraction
2021   27,824      100%
2022   27,137      100%
2023   28,028      100%
2024   27,514      100%
2025   27,166      100%
2026    8,934        0%
```

Every single row for 2021-2025 — i.e. **all** of Stage-1's in-scope
population, both discovery and validation splits — has a null `direction`
and is therefore assigned its sign entirely from the `regime` column via the
fallback. Only 2026 (out of scope, filtered out one line later by
`d = d[d["year"] <= 2025]`, `build_stage1.py:115`) has `direction` populated
directly.

Root cause is visible in `studies/regime_sequence_chop_context/run_study.py:130-149`:
the combined atlas is built incrementally — years already present in the
cached `flip_context_atlas.parquet` are *skipped*, not recomputed
(`if yr in processed_years: continue`). `direction` was evidently added to
the F1 context dict (`build_flip_atlas.py:201`, `context["direction"] =
direction`) at some point *after* 2021-2025 were already cached and frozen;
those years were never rebuilt with the newer schema, so their `direction`
column is uniformly absent. `run_study.py:322-326` shows the study's own
authors were aware of this ("Ensure direction column exists... if 'direction'
not in df_f1.columns and 'regime' in df_f1.columns: df_f1['direction'] =
df_f1['regime'].astype(int)") and treat `regime` as an acceptable substitute
— but this substitution has never been checked against a case where both
columns are actually present.

2026 is exactly that case, and the comparison is damning. For the 8,934 F1
rows in 2026 where both `direction` and `regime` exist:

```
overall match rate:      75.1%  (24.9% disagree)
RTH match rate (n=2,394): 98.7%  (1.3% disagree)
ETH match rate (n=6,540): 66.4%  (33.6% disagree)
```

Every disagreement is a sign flip (`direction=+1, regime=-1` or vice versa —
verified directly, no partial/off-by-N values). The match rate is also
strongly time-of-day dependent (near-perfect 8am-3pm CT, degrading sharply
outside RTH, e.g. hour 22-23 CT match rate ~0.50-0.58, i.e. indistinguishable
from a coin flip). This pattern — clean during RTH, near-random overnight —
is consistent with a since-changed session-boundary/reset behavior in the
regime engine between whatever run produced the cached 2021-2025 `regime`
column and the current `reproduce_regimes.RegimeEngine`/`build_flip_atlas.py`
that produced 2026's `direction`. It is not consistent with a benign
relabeling; it means the two columns encode the output of two different
regime-engine states for a full third of ETH history.

**Why this is critical, not a data-hygiene footnote:** `direction` is
multiplied directly into every quantity this study measures —
`characterize_year` (`build_stage1.py:155-162, 209-214`) computes `fav`,
`running_mfe`, `pnl`, and `final_pnl` all as `r.direction * (...)`. A wrong
sign does not add noise; it relabels a regime's own favorable side as
unfavorable and vice versa, which:
- Flips `final_flip_pnl_atr` sign, moving rows between cohorts 4 (`flip<0`)
  and 2/3 (`flip>=0.5`/`>=1.0`) arbitrarily.
- Flips which side of price action is "favorable" for `peak_mfe_atr`,
  `giveback_atr`, `retained_*`, and `new_progress_windows` (fav is computed
  from `h`/`l` conditioned on `r.direction == 1`, `build_stage1.py:155-160`),
  scrambling cohort 6/7 membership — the study's own "key contrast."
- Given ETH is the majority of all-hours flip volume (67-73% of 2026 rows in
  this same file) and shows a ~1-in-3 sign-disagreement rate, a large
  fraction — plausibly 20-25% overall, concentrated in ETH — of the entire
  2021-2025 population Stage 1 is built on may have the **wrong regime
  direction**, silently, with no assertion or sanity check anywhere in
  `build_stage1.py` or `common.py` that would surface it. The current
  `assert not d.duplicated("regime_start_ns").any()` (`build_stage1.py:123`)
  checks key uniqueness, not sign correctness, and would not fire.

This also directly contradicts SPEC.md:28-29's own stated methodology:
"Regime engine: exact upstream `reproduce_regimes.RegimeEngine` port, fresh
per year (atlas-matching), regimes = flip close_ts intervals." No code in
this study (`common.py`, `build_stage1.py`) imports or calls
`reproduce_regimes.RegimeEngine` at all — `load_regime_population`
(`build_stage1.py:99-124`) is a pure read of pre-built atlas columns. Had the
SPEC's stated "fresh per year" re-run actually been implemented, `direction`
would never be null and this entire fallback — and the provenance question it
raises — would not exist.

**Recommended fix (do not apply):** before Stage 1 is executed, either (a)
actually implement SPEC.md:28-29 as written — instantiate
`reproduce_regimes.RegimeEngine` fresh per year inside this study and derive
`direction` independently from the 1m regime state at each flip's own
`close_ts`, never trusting the atlas's `regime`/`direction` columns for sign;
or (b) if continuing to consume the atlas directly, add an explicit
parity check comparing a fresh regime-engine re-run against the atlas's
`regime` column for a sample of 2021-2025 rows (the same kind of check the
prior study shipped as `audit/score_regime_id_audit.parquet`) before trusting
`fillna(regime)` for the bulk of the population, and resolve/document why
`regime` and `direction` disagree 33% of the time in ETH for the one year
where both are observable. Do not proceed to build cohort summaries or
evaluate the Stage-1 gate until this is resolved — the gate's pass/fail
decision is not trustworthy while direction sign for a material, non-random
fraction of the population is unverified.

*(Reproducibility note: the statistics above were produced by a read-only
pandas inspection of the existing `flip_context_atlas.parquet` artifact —
`d[d.population=='F1']`, grouped by year and by `direction==regime`,
cross-tabbed against RTH/ETH via the same `America/Chicago` 8:30-15:00
convention `common.is_rth` uses. No study code was executed and no file was
modified.)*

### Item-by-item verification (Pass 2)

**1. Pass-1 Critical 1 (`w4_at_end` reads 1s into next regime) — CONFIRMED FIXED.**
`attach_w4()` (`build_stage1.py:234-285`) now selects, for every target `X`
(`qual`/`peak`/`m60`/`m30`/`flip`), the last checkpoint with
`observation_time + 1s <= target` (`:266`, `j = searchsorted(obs, target - NS,
side="right") - 1`), plus a freshness cap requiring the selected checkpoint be
no older than one native cadence interval (`:269-273`). At the exact boundary
`target == regime_end_ns`: because regime boundaries are exact multiples of
60s and checkpoint cadence (30s/5s) divides 60s evenly, the atlas is
guaranteed to contain a checkpoint at `obs == regime_end_ns` for any
non-timed-out regime (the same fact that made Pass 1's finding structural).
The new rule requires `obs + 1s <= target`, i.e. `obs <= target - 1s`; since
`obs == target` fails that inequality, the boundary checkpoint is correctly
excluded. The next-earlier checkpoint (`obs = target - step_s`) is selected
instead, and its recency check passes (`step_s - 1s <= step_s` always holds).
Verified analytically for both cadences (30s train, 5s val). No off-by-one
remains at the boundary.

**2. Pass-1 Critical 2 (hindsight vs. causal filter components) — retained_ratio fixed, new_progress_windows still hindsight.**
`retained_{qual,peak,m60,m30,flip}` (`build_stage1.py:217-229`) are now
computed from bars strictly preceding each target's own decision boundary:
`k = searchsorted(t, target, side="left") - 1` selects the last bar with
`open < target`. This correctly *includes* the bar whose open is
`target - 1s` (closing exactly at `target`) — consistent with the same
`side='left'-1` convention used for the executable-price anchor/exit
(`_last_close_before`, `:127-129`) and the intended "last known information
as of `target`" semantics; it is not an off-by-one. `target` itself is
derived causally: for `qual`/`peak` it is `t[i] + NS` (the touching/peak
bar's own close), and for `m60`/`m30`/`flip` it is a `regime_end_ns` offset,
guarded against preceding `regime_start_ns` (`:219`, returns `NaN`). This
resolves the causal half of Pass 1's finding.

`new_progress_windows` (`:179-187`), however, remains a single count over the
**entire** `[a,b)` regime window — still full-regime hindsight, with no
bar-by-bar "as of X" counterpart anywhere in the repo. Per SPEC.md's own
framing this is currently used "descriptively" for the Stage-1 gate contrast
(cohort medians on **completed** regimes, which is legitimate for a
descriptive characterization stage), so it is not itself a bug in Stage 1.
But `evaluate_stage1.py:69-71` feeds this exact hindsight quantity
(`med_new_progress_windows`) directly into one of the gate's four structural
conditions (`progress_windows_delta_min`), and SPEC.md:98-99 explicitly
promises Stage 2 will use "a `new_progress_windows` computed causally
bar-by-bar" for the live filter. No such causal version exists yet. This
half of the Pass-1 finding remains **open and unresolved** — flagged again
here per CLAUDE.md's pre-execution audit mandate, to be closed before any
Stage-2 code is written, not merely before Stage 2 is declared done.

**3. `load_regime_population` / `opposing_flip_time` timeout-substitution question — VERIFIED CLEAN, separate from the direction-sign issue above.**
`build_flip_atlas.py:184-194`: `opp_flip_ts` is set by scanning forward for
the actual next `r_fwd.regime == -direction` 1m bar; only if none is found
before the year's data ends is it substituted with the **last** bar's
`close_ts` (`:189-190`, "data end", not the 1800s timeout — the 1800s
`timeout_ts` is used only to build the separate `ep_end_ts` window for the
outcome-replay simulation and checkpoint arithmetic, and is never written
into the persisted `opposing_flip_time` column). Since regime state is
binary (`+1`/`-1`, with `0` as a non-regime gap state) and
`build_flip_atlas()` is invoked once per calendar year on that year's own raw
file (`run_study.py:161`, no cross-year lookahead is even possible), a
mid-year flip can only fail to find its opposite if it is the chronologically
last flip in that year's data — i.e. exactly the row `load_regime_population`
marks `end_censored=True` via `groupby("year").tail(1)`
(`build_stage1.py:120-121`). No mid-year row can have a timeout-substituted
(as opposed to data-end-substituted) `regime_end_ns`, so marking only the
last regime per year as censored is structurally correct. This is
independent of, and does not mitigate, the direction/regime sign-disagreement
finding above.

`d["direction"] = d["direction"].fillna(d["regime"])` (`:106`) — see Critical
finding above; this is *not* clean, contrary to how it read in Pass 1.

**4. `characterize_year` anchor/exit/target semantics — CONFIRMED CLEAN.**
Anchor and exit prices use `_last_close_before` (`:127-129`,
`searchsorted(..., side='left') - 1`), which selects the bar closing exactly
at the boundary when one exists (open = boundary − 1s) — matching SPEC.md:52
("last 1s close before the flip boundary") and the flip's own close-price
semantics. `targets["qual"]`/`targets["peak"]` are explicitly the *closing*
timestamp of the touching/peak bar (`t[i] + NS`, with an explanatory comment
at `:190-191` about the open/close convention), not the bar's open — no
lookahead. `m60`/`m30` targets are guarded against `target < regime_start_ns`
(`:219`) for short regimes, correctly producing `NaN` rather than a negative
or nonsensical index. The `new_progress_windows` loop (`:179-187`) uses a
`>= 120s` gap-since-last-extreme rule exactly as documented, operating only
on already-computed `running_mfe` (backward-looking `np.maximum.accumulate`)
— no `center=True`, no forward index access.

**5. `evaluate_stage1.py` — gate applied mechanically, no extra knobs, both splits required, cohort masks match SPEC — CONFIRMED CLEAN.**
`gate_for_split()` (`:59-105`) references every key of `common.STAGE1_GATE`
(all 12 fields — `duration_ratio_min`, `peak_mfe_ratio_min`,
`progress_windows_delta_min`, `retained_m60_delta_min`,
`minimum_structural_conditions`, `minimum_winner_count_train/2025`,
`minimum_paired_w4_count_train/2025`, `weakness_rise_min`,
`minimum_median_peak_to_flip_s`, `minimum_median_giveback_atr`) and adds no
additional ad hoc thresholds beyond what SPEC.md:76-85 predeclares.
`COHORT_MASKS` (`:19-31`) for cohorts 6 and 7 match SPEC.md:68-70 exactly
(`peak_mfe_atr>=1.0 & final_flip_pnl_atr<0.5` / `>=0.5`). `main()`
(`:108-133`) computes train and validation gates independently
(`gate_for_split` called once per split with split-specific
`min_winners`/`min_paired`) and requires **both** to pass
(`decision = ... if g_tr["pass"] and g_vl["pass"] else ...`) before emitting
`ESTABLISHED_REGIME_FILTER_FOUND`, matching SPEC.md:76 ("must pass in both
2021-2024 and 2025"). No hindsight column is used as if it were causal
anywhere in this file beyond the already-flagged `new_progress_windows`
carry-forward (item 2 above), which is legitimate for Stage 1's own
descriptive gate on completed regimes.

**6. Chronology firewall — CONFIRMED CLEAN.**
`build_causal_scores()` filters every row group by
`observation_time < cutoff_2026` before any scoring (`build_stage1.py:52`)
and asserts `max_observation_time < cutoff_2026` after (`:85`).
`load_regime_population` filters `year <= 2025` and asserts the max
(`:115-116`). `main()` in `build_stage1.py` asserts
`metrics["year"].max() <= 2025` and that no `period == "test"` row is present
(`:298-299`). `evaluate_stage1.py:110` re-asserts `m["year"].max() <= 2025`
independently at analysis time. Train/validation are never combined for gate
purposes (item 5 above). This is a materially more defended chronology
firewall than Pass 1's version.

**7. Upstream `flip_context_atlas` known PnL/giveback skew — CONFIRMED NOT CONSUMED.**
`load_regime_population`'s column list (`build_stage1.py:100-103`) is
`["observation_time", "opposing_flip_time", "atr", "close", "regime",
"direction", "population", "period"]` — none of the atlas's own
`pnl_base`/`pnl_plus_1t`/`pnl_plus_2t`/`E0_regime_exit_pnl`/`MFE`/`MAE`/
`giveback` columns (built in `build_flip_atlas.py:252-293` against
`flip_close`, not a true fill price) are read. Every PnL/MFE/giveback/
retained-ratio quantity used downstream in this study is independently
recomputed from raw 1s bars in `characterize_year`
(`build_stage1.py:132-231`). Note: `close` is loaded and renamed to
`start_close` (`:110`) but is never referenced again anywhere in the file —
a harmless dead column, not a leak, worth removing for hygiene but not a
finding.

### Clean checks (Pass 2 additions)

- `w4_at_end`/`w4_at_*` boundary look-ahead: fixed and verified at the exact
  boundary case for both checkpoint cadences (see item 1).
- `retained_*` causal computation at fixed decision points: fixed and
  verified, no off-by-one (see items 2, 4).
- `opposing_flip_time` timeout-vs-data-end substitution: verified structurally
  clean, only the true last regime per year can be data-end-substituted (see
  item 3).
- Gate mechanics (`evaluate_stage1.py`): verified mechanical, no undeclared
  knobs, both chronological splits required (see item 5).
- Chronology firewall: verified redundant/defended at four independent points
  (see item 6).
- Atlas PnL-skew columns: verified not consumed; this study computes its own
  PnL/MFE from raw bars (see item 7).
- Pass-1 Warnings on CLI year-mixing and `SCORES_2025_2026` blanket-load are
  both moot: the rewritten scripts removed the code paths that made them
  possible (no `--years` CLI arg; `build_causal_scores` filters every row
  group by absolute timestamp unconditionally).

---

*Pass 2 complete. One new CRITICAL finding (regime-direction provenance) was
discovered only by directly inspecting the on-disk upstream atlas artifact
and cross-tabulating `direction` vs. `regime` for the one year where both are
present — this was not visible from reading `build_stage1.py`/`common.py`
source alone, and would not have been caught by any check currently in this
study's own code. Per CLAUDE.md, this CRITICAL must be resolved (Stage 1 gate
must not be run/trusted) before Stage 2 is built, and Stage 1 itself should
not be executed for a real decision until direction-sign provenance for
2021-2025 is independently verified or the population is rebuilt with a
fresh, in-study `RegimeEngine` re-run as SPEC.md already promises.*
