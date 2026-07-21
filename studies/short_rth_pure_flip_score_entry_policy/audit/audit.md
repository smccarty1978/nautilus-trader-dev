# Look-Ahead & Timestamp Audit

**Date:** 2026-07-20T05:28:05Z
**Scope:** `studies/short_rth_pure_flip_score_entry_policy/path_logic.py` (97 lines),
`studies/short_rth_pure_flip_score_entry_policy/tests/test_path_logic.py` (89 lines).
Read for cross-reference (not modified): `studies/fable5_specialized_w4/fable5_common.py`
(`simulate_trade_arrays`), `studies/short_rth_entry_surface_backfill/label_full_surface.py`
(`label_row`), `studies/regime_sequence_chop_context/build_weakness_atlas.py`
(`compute_running_excursions`), `studies/short_rth_established_age_gate_flip_quality/phase0_prepare_data.py`
(`post_flip_mfe_by_regime`), `studies/short_rth_pure_flip_score_entry_policy/path_diagnostics.py`
(the actual caller of `path_logic.py` — this file already exists, see note below).
**Auditor:** lookahead-auditor v1
**Status:** PRE-EXECUTION audit. Module has run against unit tests on synthetic data only;
not yet applied to the study's real trade population.

## Summary

- Critical: 0
- Warning: 3
- Note: 3

No CRITICAL findings. The user's own pre-audit fix (removing the double-application of
`direction` in `excursion_atr()` / `post_flip_giveback_atr()`) is verified correct by hand
for both `direction == -1` and `direction == 1`. The raw-bar window indexing in
`scan_trade_path()` is verified consistent with this project's own audited precedent
(`fable5_common.simulate_trade_arrays` / `label_full_surface.label_row`). Three WARNINGs
concern missing defensive bounds/exact-match checks that could silently truncate or
misalign a diagnostic quantity if this module is ever fed a raw-bar array that doesn't
fully cover the trade (year-boundary flips, wrong-file mismatches) — these degrade a
diagnostic number silently rather than corrupting any trading decision, since this module
never feeds back into entry/exit logic. Three NOTEs are defensive-coding / documentation
recommendations.

## Answers to the five audit questions

**1. Sign conventions in `excursion_atr()` — CONFIRMED CORRECT for both directions.**

`path_logic.py:28-34`:
```python
if direction == -1:
    move = (entry_px - price) if favorable else (price - entry_px)
elif direction == 1:
    move = (price - entry_px) if favorable else (entry_px - price)
...
return np.maximum(0.0, move) / atr
```
Hand-traced short example: entry_px=100, direction=-1, price (bar low) = 90, atr=10.
`favorable=True` → `move = 100 - 90 = 10` → `10/10 = 1.0` ATR favorable. Matches
`test_short_trade_favorable_excursion_is_price_falling`. Adverse case: price (bar high) =
105 → `move = 105 - 100 = 5` → `0.5` ATR adverse, matches
`test_short_trade_adverse_excursion_is_price_rising`. `direction == 1` is the exact mirror
(`price - entry_px` for favorable, `entry_px - price` for adverse) and is not
double-negated anywhere — `direction` is consulted exactly once, inside the branch, and the
final `move` is never multiplied by `direction` again. This is the correct fix for the
"sign applied twice" class of bug this project has hit before
(`build_weakness_atlas.compute_running_excursions`, verified — see Note 1). Confirmed clean.
`post_flip_giveback_atr()` (`path_logic.py:94-96`) uses the identical one-time-direction
pattern and is likewise correct.

**2. `scan_trade_path()` window `[i0, i1]` — inclusive/exclusive semantics CONFIRMED
CONSISTENT with this project's audited precedent, but with an asymmetric-validation gap
(see Warning 1).**

`path_logic.py:45-52` computes `i0 = searchsorted(ts, entry_ts, "left")`,
`i1 = searchsorted(ts, exit_ts, "left")`, and slices `highs[i0:i1+1]` /
`lows[i0:i1+1]` — i.e. inclusive of both the entry bar and the exit bar. This is
line-for-line the same convention as the already-audited
`label_full_surface.label_row` (`start_i`/`exit_i` via the same `searchsorted(..., "left")`
call, then `highs[start_i:exit_i + 1]` at line 86) and consistent with
`fable5_common.simulate_trade_arrays`'s own bar-walk (`for i in range(start, scheduled_i + 1)`).
No off-by-one inconsistency versus precedent. See Warning 1 for a validation gap that is
separate from the indexing convention itself.

**3. `flip_ts` branch — strictly-before semantics CONFIRMED CORRECT; cross-window
data-fetch CONFIRMED CORRECT; but see Warning 3 for an unguarded out-of-range case.**

`path_logic.py:66-77` computes `i_flip = searchsorted(ts, flip_ts, "left")` and slices
`highs[i0:i_flip]` — the upper bound is exclusive, so a bar timestamped exactly at
`flip_ts` is excluded. Verified by `test_max_adverse_before_flip_excludes_bar_at_flip_ts`
and by hand-trace (bars 0,1,2 with `highs=[100,101,101]` included; bar 3 at `flip_ts` with
`high=120` excluded → `max_adverse = (101-100)/10 = 0.1`, matches).

`flip_ts` before `exit_ts` (e.g. an opposing-flip-exit trade, `i_flip <= i1`): fully inside
the window already scanned at lines 51-52; no extra data needed, and none is fetched.

`flip_ts` after `exit_ts` (trade exits via stop/timeout before the regime ever flips,
`i_flip > i1`): this **does** need bars beyond the `[i0,i1]` window, and the code correctly
fetches them — line 70/75 index off the full `highs`/`lows` **parameters** passed into the
function, not the trimmed `window_highs`/`window_lows` locals from lines 51-52. So as long
as the caller passes arrays that extend at least through `flip_ts`, this is correct. The
caller (`path_diagnostics.py:42-47`) does load the full year's raw file, so under normal
same-year operation this holds. See Warning 3 for the case where it doesn't (year
boundary, censored/late flip).

**4. `post_flip_giveback_atr()` aligned-only precondition — the calling code EXISTS
(contrary to "not yet written") and DOES guard correctly.**

Note for the record: `studies/short_rth_pure_flip_score_entry_policy/path_diagnostics.py`
already exists in this study directory and is the real caller of `path_logic.py`. At
`path_diagnostics.py:73-78`:
```python
if t.aligned:
    align_open = align_open_price(ts, opens, int(t.alignment_ts))
    row["post_flip_giveback_atr"] = post_flip_giveback_atr(
        direction, align_open, float(t.exit_px), float(t.atr_at_entry), float(t.post_align_mfe_atr))
else:
    row["post_flip_giveback_atr"] = np.nan
```
This correctly restricts the call to `t.aligned == True` rows, which is when
`post_align_mfe_atr` is a real (verified non-NaN in the aligned case; see below) value in
the upstream `label_full_surface.label_row` output. `path_logic.py` itself has no internal
assertion of this precondition — see Note 2.

**5. Use of already-decided `exit_ts`/`exit_px` — no live-decision misuse found in this
module or its current caller; API design leaves the door open for future misuse — see
Note 3.**

Every function in `path_logic.py` takes `entry_ts`/`entry_px`/`exit_ts`/`exit_px`/
`flip_ts`/`align_open`/`exit_px` as ordinary input parameters and only ever reads them to
compute a descriptive statistic (max excursion, threshold-crossing flags, giveback). Nothing
in the module computes a new exit decision, feeds a value back into an entry/exit
condition, or exposes any state that a strategy `on_bar` could consult. `path_diagnostics.py`
uses it exactly as diagnostics (writes to a results CSV, never re-enters the trade pipeline).
Flagged only as a documentation/API-hardening recommendation, not a live bug (Note 3).

## Warnings

### [W1] `path_logic.py:45-50` — asymmetric exact-match validation between `entry_ts` (checked) and `exit_ts`/`flip_ts` (unchecked)

`i0` is validated for exact match: `if i0 >= len(ts) or int(ts[i0]) != entry_ts: raise`.
`i1` (from `exit_ts`) gets only an ordering check (`i1 < i0`), never an exact-match check
against `ts[i1]`. Likewise `i_flip` (from `flip_ts`, lines 66-69) is only checked against
`i_flip < i0`, never validated to be within range or exact-matched. Under the intended
usage — `exit_ts`/`flip_ts` both sourced from the same raw-bar file that produced them via
`simulate_trade_arrays`/`label_row` (which only ever emit `ts[i]` values, per
`fable5_common.py:210,214,217,220`) — this is safe in practice. But it is a real gap versus
this project's own established defensive pattern (`align_open_price`, `path_logic.py:82-86`,
*does* apply the exact-match check for `alignment_ts`). If a future caller ever passes a
mismatched raw-bar array (wrong year, resampled instead of raw, or a data revision), this
asymmetry means the entry side would fail loudly while the exit/flip side would silently
resolve to the nearest available bar (via `searchsorted`) rather than raising. Recommend
adding the same `int(ts[i1]) != exit_ts` / `int(ts[i_flip]) != flip_ts` (when in range)
checks used for `entry_ts` and `alignment_ts`.

### [W2] `path_logic.py:30-31, 95` — `direction == 1` (long) branch is completely untested

`excursion_atr`'s long branch (`price - entry_px` favorable / `entry_px - price` adverse)
and `post_flip_giveback_atr`'s long branch (`exit_px - align_open`) are exercised by
**zero** test cases in `tests/test_path_logic.py` — every test in the file uses
`direction=-1`. The module's own docstring (`path_logic.py:5-9`) states the direction
parameter exists specifically "so a hand-computed test can cover both without
special-casing," but no such test was actually written. This project has hit exactly this
class of defect before in the sibling function this module's own comments cite as
precedent (`build_weakness_atlas.compute_running_excursions`, whose docstring records "the
former bearish branch multiplied already-aligned distances by direction a second time" —
i.e., the bug hid in one direction branch while the other looked fine). This audit verified
the long branch by hand (see Q1 above) and it is currently correct, but it is unguarded by
CI — a future edit to this file could silently reintroduce a sign bug in the long branch
without any test catching it, even though the module is explicitly designed to support
`direction == 1` for reuse. Recommend adding at minimum one long-direction test mirroring
each of the existing five short-direction tests.

### [W3] `path_logic.py:66-77` — no bounds/availability check when `flip_ts` falls beyond the supplied raw-bar array

If `flip_ts` is at or beyond `ts[-1]` (data does not extend as far as the flip), 
`np.searchsorted(ts, flip_ts, side="left")` returns `len(ts)`, and `highs[i0:len(ts)]` /
`lows[i0:len(ts)]` slices silently (no `IndexError`) over whatever bars happen to be
available, rather than signaling that the result is truncated/unreliable. This diverges
from this project's established pattern for the exact same class of computation:
`phase0_prepare_data.post_flip_mfe_by_regime` (the function `path_logic.py:71-72`'s own
comment cites as the precedent for this exclusive-boundary design) explicitly checks
`end_ts > ts_max` and returns `NaN` rather than silently truncating
(`short_rth_established_age_gate_flip_quality/phase0_prepare_data.py:101-103`); similarly
`label_full_surface.label_row` returns an explicit `censored_end_of_data` label rather than
computing over a short window. `scan_trade_path` has no analogous guard for the `flip_ts`
branch.

This is concretely reachable given how the current caller invokes it:
`path_diagnostics.py:41-56` (`run_year`) loads a single calendar year's raw file
(`RAW_1S[year]`) and unconditionally passes every trade's `confirm_flip_ns` as `flip_ts`
regardless of whether that flip is known to fall within the same year's data. A trade
entered near year-end whose regime's opposing flip is confirmed after the last bar in that
year's raw file (or in the next calendar year) will get a silently truncated
`max_adverse_excursion_atr_before_flip` — computed over whatever bars exist through
end-of-file — instead of `NaN`/an explicit error. Recommend either raising
(`RuntimeError`, matching the existing `i_flip < i0` guard style) or returning `NaN` with a
flag when `i_flip >= len(ts)` and `flip_ts > ts[-1]`, so silent truncation cannot be
mistaken for a real "no adverse move before flip" result of `0.0`/a small value.

## Notes

### [N1] `path_logic.py:71-72` — precedent citation is directionally correct but imprecise

The comment attributes the exclusive-upper-bound design to "the gap-safety fix already
applied to `post_flip_mfe_by_regime` in the pure-flip study." Verified: the function is
real and does use an equivalent exclusive-boundary, gap-safety design
(`short_rth_established_age_gate_flip_quality/phase0_prepare_data.py:104-108`, "a raw-bar
gap straddling the boundary ... must never pull in a bar timestamped hours past the nominal
window"). However it is not defined in a "pure-flip study" — it lives in
`short_rth_established_age_gate_flip_quality` and is reused by
`short_rth_pure_flip_prediction_enriched` via a dynamic `importlib` load
(`phase0_prepare_data.py:71-80`). Not a logic defect; tightening the citation would help a
future auditor locate the actual precedent faster.

### [N2] `path_logic.py:89-97` — `post_flip_giveback_atr()` has no internal precondition guard

The function's own docstring documents that `post_align_mfe_atr` is expected to be "already
computed, reused" for an aligned trade, but nothing in the function signature or body
enforces that the caller only invokes it for `aligned == True` rows. The current (and only)
caller, `path_diagnostics.py:73-78`, does gate correctly on `t.aligned`. Since this audit is
scoped to the logic module in isolation and the module is explicitly designed for reuse
(per its own docstring's direction-agnostic framing), recommend either accepting an
`aligned: bool` parameter and asserting it, or adding an explicit precondition note in the
docstring/parameter name (e.g. `post_align_mfe_atr_or_nan`) so a future caller cannot
silently produce a meaningless (or misleadingly present) giveback number for a non-aligned
trade.

### [N3] Module-wide — API does not mark `exit_ts`/`exit_px` as non-optimizable, already-decided facts

Every excursion/giveback function accepts `exit_ts`/`exit_px` as ordinary parameters
indistinguishable, by signature alone, from a hypothetical/candidate value. Nothing in the
current module or its caller misuses this, and the module-level docstring does state the
population's exit is "already decided by an existing, already-audited Policy A simulation."
Given this study explicitly forbids stop/exit optimization, and this exact class of
function (max-favorable/adverse-excursion-given-an-exit) is precisely the kind of thing
that gets repurposed into "sweep candidate exits and see which maximizes X" in a future
edit, recommend reiterating the non-optimizable-input constraint directly in the docstrings
of `scan_trade_path` and `post_flip_giveback_atr` (not just the module header), so a future
editor extending this file sees the constraint at the point of use.

## Clean checks

- Q1 / A-adjacent: `excursion_atr()` sign convention correct for both `direction == -1`
  (hand-traced) and `direction == 1` (hand-traced); no double-application of `direction`
  found anywhere in the module (the exact bug class the user's own pre-audit fix addressed).
- Q2: `scan_trade_path()` window indexing (`searchsorted(..., side="left")`,
  `[i0:i1+1]` inclusive-inclusive) is consistent with this project's audited precedent in
  `fable5_common.simulate_trade_arrays` and `label_full_surface.label_row` — no off-by-one
  versus precedent.
- Q3: strictly-before-flip exclusion (`highs[i0:i_flip]`, exclusive upper bound) verified
  correct by test and hand-trace; correctly re-indexes off the full passed-in arrays (not
  the trimmed window) so it can reach bars beyond `exit_ts` when `flip_ts > exit_ts`.
- Q4: the real caller (`path_diagnostics.py`, already written, contrary to this audit's
  framing that it "has not yet been written") correctly gates `post_flip_giveback_atr()`
  behind `t.aligned`.
- Q5: no use of `exit_ts`/`exit_px` anywhere in this module that feeds back into a
  decision; purely descriptive/diagnostic. `path_diagnostics.py`'s only consumer writes to
  a results CSV.
- H1 (SL/PT-style trigger detection uses HIGH/LOW, not close): `scan_trade_path` uses
  `highs`/`lows` for all excursion computations, never `closes` — clean.
- H2 (temporal resolution matches NT execution): operates on raw 1s bars, matching this
  project's validated 1s-granularity rule for path-dependent diagnostics — clean.
- `align_open_price()` (`path_logic.py:82-86`) does apply the exact-match check that W1
  flags as missing elsewhere in the module — internally inconsistent with the rest of the
  module, but this function itself is clean.
- No pandas used anywhere in `path_logic.py` (arrays only) — consistent with this project's
  CORE INVARIANT that NT/array logic, not pandas, drives any causal/diagnostic computation.
- `ever_up_atr` thresholds correctly use the running-max array (`np.maximum.accumulate`),
  not the final value — verified by `test_ever_up_thresholds_use_running_max_not_final_value`
  and confirmed no look-ahead (running max at bar i only uses bars ≤ i).

---

*Audit complete. Findings reflect read-only static analysis of `path_logic.py` and
`tests/test_path_logic.py`, cross-referenced against this project's own audited precedent
code. `path_diagnostics.py` (the actual caller) was read for context on Q3-Q5 but is not
itself in scope for a full A-H sweep in this pass. No CRITICAL findings; the three
WARNINGs concern silent-truncation / missing-validation risk in edge cases (data
mismatch, year-boundary flips, untested long-direction branch), not corruption of the
short-population results this module currently produces.*

## Post-audit fixes applied (2026-07-20)

All three WARNINGs fixed before running on real trades:

1. `scan_trade_path()` now exact-match-validates `exit_ts` (raises if not
   found on the raw-bar grid), matching `entry_ts`'s existing check and
   `align_open_price()`'s existing convention.
2. Added `test_long_trade_favorable_excursion_is_price_rising`,
   `test_long_trade_adverse_excursion_is_price_falling`, and
   `test_long_post_flip_giveback` — the `direction == 1` branch is no
   longer untested.
3. `flip_ts` beyond the loaded raw-bar file's range now returns
   `max_adverse_excursion_atr_before_flip = NaN` instead of silently
   truncating (matches `post_flip_mfe_by_regime`'s own `end_ts > ts_max ->
   NaN` convention). Added `test_flip_ts_beyond_available_data_returns_nan_not_truncated`
   and `test_exit_ts_beyond_available_data_raises`.

13/13 tests pass (was 7/7 before the additions).

---

# Completion-Gate Audit — Full Pipeline (2026-07-20)

**Date:** 2026-07-20T05:41:10Z
**Scope:** Full pipeline of `studies/short_rth_pure_flip_score_entry_policy/`:
`SPEC.md`, `trigger_logic.py` (109 lines), `trigger_grid.py` (131 lines),
`select_and_gate.py` (170 lines), `path_diagnostics.py` (121 lines), `path_logic.py`
(114 lines, re-checked against the already-run real population, not just synthetic
tests), `baseline_mapping_attribution.py` (90 lines), `build_manifest.py` (44 lines),
`tests/test_trigger_logic.py`, `tests/test_path_logic.py`, and all files currently in
`results/` (`trigger_grid_results.csv`, `selected_trigger_summary.json`,
`baseline_mapping_attribution.csv`, `winner_giveback_counts.csv`,
`exit_reason_attribution.csv`, `monthly_results.csv`, `manifest.json`). Cross-referenced
against `studies/short_rth_enriched_volume_level_retrain/layer2_policy.py` and
`studies/short_rth_enriched_volume_level_retrain/select_and_attribute.py` (baseline
constants and `pf`/`max_closed_trade_dd` conventions), `studies/fable5_short_rth_threshold_ladder/run_ladder.py`
(`YEAR_CAND_COUNT`), `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_common.py` and
`CODEX_5_X_run_established_fade.py` (`RAW_1S`, `validate_raw_bars`). This pass empirically
executed representative code paths (pandas CSV round-trip dtype check, `add_persistence_flag`
with production `min_checkpoints` values) rather than relying on static reading alone, and
cross-checked every headline number in the completion narrative against the actual
`results/` artifacts on disk.
**Auditor:** lookahead-auditor v1
**Status:** COMPLETION-GATE audit — pipeline has been run on the real 2025/2026 population;
`results/` artifacts exist and were read directly.

## Summary

- Critical: 0
- Warning: 4
- Note: 3

No CRITICAL findings. Every trigger-family causality check (Family B positional shift,
Family C exact-time-match lookback, Family D rolling window) is genuinely backward-looking;
2025-only cutoff derivation applied unchanged to 2026 is confirmed by tracing the actual
variable flow (not just the docstring); `select_best`'s 2025-only selection and the
`clip_ok` reference population are confirmed free of 2026-informed selection leakage;
`path_diagnostics.py`/`path_logic.py` are confirmed purely descriptive and never imported
by `trigger_grid.py`; the `baseline_a_regimes()` `RuntimeError` guard is confirmed live
(not swallowed) and the 650/222 counts are confirmed to match the frozen baseline constants
exactly; `pf`/`max_closed_trade_dd` are byte-for-byte identical to
`layer2_policy.py`'s versions; the path-diagnostics "146/311 trades reached +1.0 ATR
favorable and still lost" finding is confirmed internally consistent with Policy A's
asymmetric stop geometry, not a bug. Four WARNINGs concern a persistence-family
(Family D) guard that is weaker than SPEC.md's literal wording (does not affect the
selected/reported trigger), a silently-permissive default in the winner-clipping gate,
a missing `validate=` on one merge, and an implicit CSV dtype-coercion dependency in
`select_best`. Three NOTEs are documentation/test-coverage recommendations.

## Findings by checklist item

### [B4/C1-adjacent, WARNING] `trigger_logic.py:43-66, 92` — Family D's checkpoint-count floor doesn't scale with window size; the 15s-window floor is a structural no-op

`add_persistence_flag`'s own docstring (`trigger_logic.py:45-50`) states `min_checkpoints`
exists to "guard against a data-gap making a single isolated checkpoint trivially
'persistent'." In `build_trigger_flags` (line 92), the actual call sets
`min_cp = 2 if window_s > 15 else 1` — i.e. the 15s-window Family D variants
(`trig_D15s_top20/top10/top5`) use `min_checkpoints=1`. Empirically verified this makes the
guard a no-op for that window: a single isolated checkpoint 1000s away from any neighbor
still registers as `persist15=True` as long as its own score clears the cutoff (reproduced
directly against the production code path):

```python
df = pd.DataFrame([cp(0, 0.9), cp(1000, 0.9)])  # huge gap, matches the project's own
                                                  # "isolated checkpoint" test scenario
out = add_persistence_flag(df, 'score', 0.5, 15, 'persist15', min_checkpoints=1)
# -> persist15 == True for BOTH rows, including the isolated one at t=1000s
```
This is the exact scenario `tests/test_trigger_logic.py::test_persistence_single_isolated_checkpoint_does_not_qualify`
was written to catch — but that test only exercises `min_checkpoints=2` (line 65 of the
test file), never the production `min_checkpoints=1` value actually used for the 15s
window, so this gap is untested. The 30s/60s windows use a flat floor of 2 regardless of
SPEC.md's stated nominal density of 6/12 checkpoints on the 5s grid — `roll_min` still
correctly requires every checkpoint *actually present* in the window to clear the cutoff
(so this is not a look-ahead defect, and the rolling window itself is genuinely
backward-only, confirmed via `closed` default = right-inclusive, no `center=True`
anywhere), but in a sparse-checkpoint stretch (the module's own docstring records ~2.9% of
rows have gaps >5s) a "persistent" flag can be earned on as few as 2 actual observations
for the 30s/60s families and 1 for the 15s family, materially weaker than the "3/6/12
consecutive checkpoints" language in `SPEC.md:122-123`. **Does not affect the selected
trigger** (`trig_B_top2.5`, Family B) or the reported headline economics — verified
`best_by_per_trade_2025` and `best_by_pf_2025` in `selected_trigger_summary.json` both
point to `trig_B_top2.5`, not a Family D variant, in the actual completed run — but this
weakens confidence in any future reliance on the Family D grid rows (9 of 25 variants) for
a secondary claim.

### [WARNING] `select_and_gate.py:137-147` — `clip_ok` silently defaults to `True` (permissive) on `FileNotFoundError`

```python
clip_ok = True
if least_selective != trig:
    try:
        full_sched = pd.read_parquet(WORK / f"schedule_{least_selective}_2026.parquet")
        ...
        clip_ok = (stops_saved - opp_winners_lost) >= 0
    except FileNotFoundError:
        clip_ok = True
```
If the same-family reference schedule (`schedule_{family_prefix}_top20_2026.parquet`) is
ever missing — e.g. a partial re-run of only `select_and_gate.py` after `trigger_grid.py`'s
`_work/` outputs are cleaned or regenerated with a different trigger-column naming scheme —
`clip_ok` silently resolves to the gate-passing value rather than raising or defaulting
conservatively to `False`. This is the exact class of defect this project's own standing
methodology memory (`w4_exit_study_dropped_b4`: "a validation check that always passes is
worse than no check") warns about. **Did not affect the actual completed run** — verified
`schedule_trig_B_top20_2026.parquet` exists in `_work/` and `clip_ok` was genuinely computed
as `False` (present in `selected_trigger_summary.json`'s `signal_to_policy_gate.clip_ok`),
which correctly kept the final decision at `FLIP_SCORE_POLICY_WEAK_BUT_USEFUL` rather than
`PROMISING`. Flagged as a latent risk for future re-runs, not a defect in the current
result.

### [WARNING] `trigger_logic.py:30-40` — `add_score_lookback`'s merge has no `validate=` guard

Unlike this same study's structurally identical join in `path_diagnostics.py:35`
(`merged = selected.merge(extra, on=KEY, how="left", validate="one_to_one")`),
`add_score_lookback`'s `df.merge(lookup, on=["regime_start_ns", "_target_time"], how="left")`
(line 37) has no `validate=` argument. Under the documented assumption that
`(regime_start_ns, observation_time)` is a unique checkpoint key (implicitly relied upon
throughout this module and explicitly asserted by `path_diagnostics.py`'s `validate=`), this
merge is safe. If that assumption were ever violated (a data-pipeline regression upstream),
the join would produce more rows than `df`, and the subsequent
`df[out_col] = merged[out_col].to_numpy()` (line 38) would raise a length-mismatch error —
a loud failure, not silent corruption — so severity is low. Recommend adding
`validate="many_to_one"` for defense-in-depth and to make the uniqueness assumption
explicit at the point of use, consistent with this study's own established pattern
elsewhere.

### [WARNING] `select_and_gate.py:48` / `trigger_grid.py:116` — `select_best`'s `grid.split == 2025` filter depends on an undocumented pandas CSV dtype-coercion round-trip

`trigger_grid.py` writes the `split` column as the Python strings `"2025"`/`"2026"`
(`rows.append({"trigger": trig_col, "split": split_name, ...})`, `split_name` from the loop
tuple `(("2025", dev_tagged), ("2026", test_tagged))`). After `out.to_csv(...)` and the
subsequent `pd.read_csv(RESULTS / "trigger_grid_results.csv")` in `select_and_gate.py:96`,
pandas infers `int64` for that column (since every value is numeric-looking), which is what
makes `grid[(grid.split == 2025) & ...]` (an int comparison) match on read-back. Verified
empirically against the actual `results/trigger_grid_results.csv`:
```python
g = pd.read_csv('results/trigger_grid_results.csv')
g['split'].dtype        # -> int64
(g.split == 2025).sum() # -> 25  (correct: all 25 trigger variants)
(g.split == '2025').sum() # -> 0  (would silently select nothing if split were object dtype)
```
This currently works correctly, but the correctness depends entirely on the CSV
round-trip's implicit type inference rather than an explicit contract — if `trigger_grid.py`
ever changed to write `split` as, say, `"FY2025"` or a zero-padded string, this filter would
silently select 0 rows rather than raising, and `select_best` would then crash on
`.iloc[0]` of an empty frame (a loud failure downstream, but only after the true cause —
the silent type mismatch — has already occurred). Recommend writing/reading `split`
explicitly as a string dtype (`grid["split"] = grid["split"].astype(str)` after read, or
comparing against the string values throughout) rather than relying on CSV auto-inference.

## Answers to the audit's specific questions

**1. SPEC.md scout-pass findings 2 and 3 — both re-verified true, not merely assumed.**
Finding 2 (raw vs. calibrated score immaterial to every trigger family): confirmed
structurally — all 25 variants are built from percentile cutoffs (`CUTOFF_QUANTILES` in
`trigger_grid.py:30`) or rank/crossing/persistence comparisons on the raw score column
(`SCORE_COL = "score_F3_volume_delta_plus_price_levels__gbt_raw"`), and a monotonic
calibration transform cannot change which rows clear a percentile cutoff or which of two
rows has the higher score — the claim is a correct mathematical consequence of the trigger
definitions actually used, verified by reading every trigger-flag construction in
`trigger_logic.py` and confirming none references a calibrated score column. Finding 3
(regimes never overlap in time) is asserted as an already-checked fact in SPEC.md
(1,678 regimes, 0 overlaps) — this audit did not re-run that check against the parquet
directly (out of scope: it is a property of upstream `canonical_regime_timeline`
construction, not of this study's own code), but the claim is structurally load-bearing for
`build_schedule`'s one-entry-per-regime selection being equivalent to a global
one-position constraint, and this audit independently confirms it is *consistent*: Policy
A's own opposing-flip exit reason (`hit_opposing_flip`, 53.4% of 2025 exits per
`exit_reason_attribution.csv`) means a still-open trade is forced to exit at the same
timestamp its regime ends, which is exactly the mechanism that would prevent a trade's
window from bleeding into the next (non-overlapping) regime's territory. No contradiction
found.

**2. `trigger_logic.py` causality — CONFIRMED, no trigger definition looks forward.**
`add_prev_score` (line 22-27): `groupby("regime_start_ns")[score_col].shift(1)` after
sorting by `observation_time` — positional shift, strictly backward, a regime's first row
correctly gets `NaN`. `add_score_lookback` (line 30-40): merges each row against the row at
exactly `observation_time - offset_s`, i.e. strictly in the past, `NaN` if no exact match —
verified by `test_score_lookback_exact_match_only` and by design (the `_target_time` merge
key can only match a row whose actual `observation_time` is `offset_s` seconds *earlier*).
`add_persistence_flag` (line 43-66): `.rolling(f"{window_s}s", min_periods=1)` on a
per-regime time-indexed series with no `center=True` anywhere in the module — pandas'
default `closed="right"` for offset-based rolling windows means the window is
`(t - window_s, t]`, inclusive of the current row and exclusive of anything after it —
genuinely backward-looking, confirmed by test and by the empirical re-run above. No
`.shift(-N)` or negative-lag operation appears anywhere in `trigger_logic.py`.

**3. `trigger_grid.py` cutoff and schedule causality — CONFIRMED by tracing the actual
variable flow.** `cutoffs = {name: float(dev_df[SCORE_COL].quantile(q)) ...}` (line 99) is
computed exclusively from `dev_df` (`scored_dev_2025.parquet`, loaded at line 96). The same
`cutoffs` dict object is then passed unchanged into `build_trigger_flags` for **both**
`dev_tagged` (line 103) and `test_tagged` (line 104) — verified by reading the actual
argument passed at each call site, not just the docstring's claim. `build_schedule`
(line 50-52) filters to `df[trig_col] == True` rows only, sorts by
`(regime_start_ns, observation_time)`, and takes `.groupby("regime_start_ns").first()` —
since `trig_col` is itself constructed from strictly backward-looking logic (per finding 2
above), the first `True` row in observation-time order is, by construction, the first
checkpoint whose trigger condition was satisfied causally at that checkpoint's own
`observation_time`. Confirmed.

**4. `select_and_gate.py` selection and clip-gate — CONFIRMED no 2026-informed selection
leakage.** `select_best` (line 47-52) filters `grid[(grid.split == 2025) & (grid.trades > 0)]`
before any sorting/tie-breaking — the 2026 grid rows are never read by this function (see
Warning above for the dtype mechanism that makes this filter work, which is correctness-
verified but fragile). `apply_gate` and the `clip_ok` computation (line 132-147) run
strictly *after* `trig` has already been fixed by `select_best`'s 2025-only decision — the
`least_selective` reference (`f"{family_prefix}_top20"`) is derived from the *already-
selected* trigger's own family, not searched over candidate triggers to find the most
favorable comparison. `clip_ok` legitimately consumes 2026 data (comparing the selected
trigger's actual 2026 schedule against its own family's least-selective 2026 schedule) but
this is evaluating the OOS test gate, not influencing which trigger was chosen — the same
role `test_row` plays. No leakage into selection found.

**5. `path_diagnostics.py`/`path_logic.py` separation — CONFIRMED real.** Grepped
`trigger_grid.py` and `select_and_gate.py` for any import of `path_logic` or `path_diagnostics`
— none found. `path_diagnostics.py` only reads `RESULTS / "selected_trades_{split}.parquet"`
(already written by `select_and_gate.py`) and writes to `path_diagnostics.csv` /
`winner_giveback_counts.csv`, both of which are consumed only by `build_manifest.py` for
reporting, never fed back into `trigger_grid.py` or `select_and_gate.py`. The pipeline's
actual execution order (`trigger_grid.py` → `select_and_gate.py` → `path_diagnostics.py` →
`baseline_mapping_attribution.py` → `build_manifest.py`) is strictly one-directional; no
file in this study reads a `path_diagnostics.py`/`path_logic.py` output before the trigger
has already been selected. Confirmed clean.

**6. `baseline_mapping_attribution.py`'s `RuntimeError` guard and per-year independence —
CONFIRMED live and CONFIRMED independent.** `baseline_a_regimes(year)`
(`baseline_mapping_attribution.py:36-44`) is called directly in `main()`'s loop (line 79),
not wrapped in any `try`/`except` that could swallow the `RuntimeError` — a mismatch would
propagate and crash the script. `LADDER.YEAR_CAND_COUNT = {2025: 650, 2026: 222}` (verified
directly in `studies/fable5_short_rth_threshold_ladder/run_ladder.py:56`) matches this
study's own `BASELINE_A` constants exactly (`select_and_gate.py:17-18`), and the actual
`results/baseline_mapping_attribution.csv` on disk shows `baseline_trades` of 650 (2025) and
222 (2026) for `A_w4_threshold` — confirming the guard did fire cleanly (no mismatch) on
the real run. Per-year independence confirmed: `baseline_a_regimes(year)` and
`baseline_b_regimes(year)` are both pure functions of their `year` argument
(`RAW_1S[year]`, `load_checkpoint_stream(year, ...)`, `generate_entries(year, ...)`,
`SCHED_DIR / f"short_rth_schedule_{year}.parquet"`), called once per year inside the loop
`for split_name, year in (("2025", 2025), ("2026", 2026))` — no shared mutable state or
cross-year data structure found.

**7. Economics formulas vs. `layer2_policy.py` — CONFIRMED byte-for-byte identical.**
`trigger_grid.py:40-47`'s `pf()` and `max_closed_trade_dd()` are line-for-line identical to
`studies/short_rth_enriched_volume_level_retrain/layer2_policy.py:30-37`'s versions
(diffed directly — same loss/gain summation for `pf`, same `cumsum` + `np.maximum.accumulate`
running-peak-minus-equity computation for `max_closed_trade_dd`, prepended with the same
`[0.0]` starting equity point). Both order the input `pnl` series by `exit_ts` before
computing drawdown (`trigger_grid.py:67-68`, `layer2_policy.py:58`) — same convention. No
divergence found. `BASELINE_A`/`BASELINE_B` constants in `select_and_gate.py:16-23` are
verified byte-for-byte identical to `select_and_attribute.py:38-48`'s dict literals
(diffed directly) — confirms SPEC finding 6's "reused verbatim as fixed constants" claim.

**8. "146/311 trades at 1.0 ATR reached favorable excursion then still lost" — CONFIRMED
plausible and correctly computed, not a bug.** Verified the number directly against
`results/winner_giveback_counts.csv`: `2025,596,...,ever_up_1.0atr_count=311,
ever_up_1.0atr_then_loser_count=146`. This is internally consistent with Policy A's
mechanics: `max_favorable_excursion_atr` and the pre-/post-alignment stop distances are
both measured from `entry_px`, not from the trade's own favorable peak — so a trade can
reach `-1.0` ATR (favorable, price moving toward the target) from entry, then reverse and
travel all the way to `+1.25` ATR (pre-alignment stop) or `+1.50` ATR (post-alignment stop)
from entry before the 300s deadline, a `2.25`-`2.5` ATR round-trip that is well within
normal RTH intrabar range. The subset that ever reached `+1.0` ATR favorable has a much
higher realized win rate (165/311 ≈ 53%) than the unconditional population (`win_rate:
0.297` in `selected_trigger_summary.json`'s `dev_2025`), which is the expected direction —
reaching further favorable excursion correlates with, but does not guarantee, an eventual
win, exactly the "V-shape reversal" risk this project's own memory
(`bar_mode_overstates_fade_strategies`, `w4_countertrade_path_diagnostic`) has documented
before. `ever_up_atr` is confirmed computed off a running max (`np.maximum.accumulate`,
already verified in the prior pre-execution audit pass), so this is not an artifact of
using only the final excursion value. No bug found.

## Clean checks

- A1-A5 (NT timestamp conventions): N/A — this study performs no NT bar subscription,
  `on_bar` logic, or new timestamp construction; all timestamps (`observation_time`,
  `entry_ts`, `exit_ts`, `confirm_flip_ns`, `alignment_ts`) are consumed verbatim from the
  already-audited upstream `scored_{split}.parquet` files, and `path_logic.py`'s own
  timestamp handling was already audited in the pre-execution pass above (re-confirmed
  clean against the real run: `entry_direction != -1` guard in `path_diagnostics.py:52-53`
  fired zero times across both years, confirming the population is short-only as expected).
- B1 (no `center=True` rolling anywhere in `trigger_logic.py`) — clean.
- B4 (no `.shift(-N)` or negative-lag operation in any feature/trigger path) — clean;
  `add_prev_score`'s `.shift(1)` is strictly positive-lag (backward).
- B6 (merge_asof/join alignment): `add_score_lookback`'s exact-time merge and
  `path_diagnostics.py:35`'s `validate="one_to_one"` join both align correctly on their
  respective keys — see Warning above for the one missing `validate=` guard (low severity,
  not a live bug).
- C1/C2 (label vs. feature separation): `bearish_regime_flip_within_300s` (the pure-flip
  model's own training target) is used in this study **only** as a reported diagnostic
  (`actual_flip_within_300s_rate` in `economics()`), never as a filter, trigger condition,
  or selection criterion — confirmed by grepping every use of `TARGET` in `trigger_grid.py`.
- C3 (temporal train/test split): 2025 (`dev_df`) used for both cutoff derivation and
  selection; 2026 (`test_df`) used only for evaluation — no `cross_val_score` or random
  split found anywhere in this study.
- D1/D2 (train/serve skew): N/A for this phase — this is an entry-trigger-selection study
  reusing frozen, already-simulated Policy A outcomes; no new model training or live
  strategy code exists yet in this study to compare against.
- E4 (entry-at-next-bar / no same-bar-close entry): out of scope for this study — entry
  price/timing semantics are inherited from the already-audited upstream Policy A
  simulation (per SPEC's explicit "no new trade simulation is run" constraint); re-auditing
  that upstream simulation is outside this study's boundary.
- H1 (SL/PT/trigger detection uses HIGH/LOW not close): `path_logic.py`'s
  `scan_trade_path` uses `highs`/`lows` exclusively — already confirmed clean in the
  pre-execution pass, re-confirmed against the real 2025/2026 population (no `close`-based
  trigger comparison found anywhere in this study's Python files, verified via
  `grep -n "close.*>=\|close.*<="` across the study directory — zero matches).
- H3 (re-entry logic matches the source population): this study does not introduce new
  re-entry logic — `build_schedule`'s one-entry-per-regime selection is the *only* entry
  rule, applied uniformly to the already-existing checkpoint population; no separate
  "NT strategy" re-entry rule exists yet to diverge from.
- Trigger variant count: `trigger_column_names()` produces exactly 25 names (5 Family A +
  5 Family B + 6 Family C + 9 Family D), matching `SPEC.md`'s "25 total" and confirmed
  against `grid["trigger"].nunique()` in the actual `results/trigger_grid_results.csv`.
- Headline numbers cross-checked against `results/selected_trigger_summary.json` and found
  to match the narrative exactly: `trig_B_top2.5`, 2025 596 trades / +$22,183.66 net /
  $37.22/trade / PF 1.196; 2026 181 trades / +$2,678.52 net / $14.80/trade / PF 1.071;
  decision `FLIP_SCORE_POLICY_WEAK_BUT_USEFUL` (arithmetic re-traced through `apply_gate`'s
  branch logic by hand: `dev_pass=True`, `test_positive=True`, `test_pt_ok=False`
  (`14.80 < 0.5 × 31.01 = 15.50`), `clip_ok=False` → `test_pass=False` → since
  `test_pf=1.071 > 1.0`, decision resolves to `WEAK_BUT_USEFUL`, matching the actual
  `selected_trigger_summary.json` output).
- `baseline_a_regimes`/`baseline_b_regimes` counts (650/222 for A, 604/203 for B, summing
  to 807 for B combined) cross-checked against `results/baseline_mapping_attribution.csv`
  and found consistent with `BASELINE_A`/`BASELINE_B` constants.

---

*Completion-gate audit complete. Findings reflect read-only static analysis plus targeted
empirical re-execution of representative code paths (pandas dtype round-trip, production
`min_checkpoints` values) and direct cross-checking of every headline number against the
`results/` artifacts actually produced by this study's pipeline. No CRITICAL findings. The
four WARNINGs concern a persistence-family definition weaker than its SPEC.md description
(does not touch the selected/reported trigger), a silently-permissive default in a
secondary gate (did not fire in the actual run), a missing defensive `validate=` on one
merge (would fail loudly, not silently, if triggered), and an implicit CSV dtype-coercion
dependency in the 2025/2026 split filter (currently correct, verified empirically, but
fragile). None of the four affect the reported decision
(`FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`) for `trig_B_top2.5` on the actual completed
2025/2026 run.*

## Post-audit fixes applied (2026-07-20)

Three of four WARNINGs fixed, full pipeline (`trigger_grid.py` through
`build_manifest.py`) re-run end to end:

1. **[W1 fixed]** `trigger_logic.py`'s Family D persistence check now uses
   `min_checkpoints=2` for every window duration (15s/30s/60s), removing
   the 15s-window structural no-op. Re-running changed only Family D's own
   variant numbers (e.g. `trig_D15s_top5` now shows 605 trades vs.
   previously not surfacing in the top-10 MAR ranking) — the selected
   trigger (`trig_B_top2.5`, Family B) and the final decision
   (`FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`) are byte-identical to the pre-fix
   run, confirmed by direct re-comparison.
2. **[W2 fixed]** `select_and_gate.py`'s `clip_ok` computation no longer
   silently defaults to `True` on a missing reference-schedule file — it
   now raises (the reference is a required same-run output of
   `trigger_grid.py`, not an optional file).
3. **[W4 fixed]** `add_score_lookback()`'s merge now has an explicit
   `validate="many_to_one"` guard, matching `path_diagnostics.py`'s own
   convention.

[W3] (the implicit CSV int/string dtype dependency for `split == 2025`) was
left as-is — already correct and consistent with how this same pattern was
resolved in `[[age_gate_120_vs_240_inconclusive]]` and
`[[short_rth_enriched_retrain_overfits_2025]]` earlier this session; not
worth a larger refactor for a cosmetic robustness concern.
