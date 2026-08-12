# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-11
**Scope:** `implementation/{timing.py,phases.py,common.py,lineage.py}`, `analysis/gates.py`, `run_study.py`, `SPEC.md`
**Scope hash:** `97d90ce588832449c40220ce22a1bf8f20e75db8b00182023425e081950e48d1`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 11 files scanned)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 1
- Note: 1

No git diff was available (new, untracked study directory) — reviewed full files per
Step 2 fallback.

## Critical findings

### [B/C1] `implementation/phases.py:329-343` — placebo controls C2/C3/C4 select each trade's global extreme observation, not a causal trigger, and feed the decisive D1 gate condition
**Failure path:** `phase9_placebo`'s C2/C3/C4 construction does:
```python
ranked = d.sort_values([col, "rung_ts"], ascending=[ascending, True], kind="stable")
sel = ranked.groupby("regime_id", as_index=False, sort=False).head(1).head(n)
```
This sorts the *entire* trade population by `col` (`rung_atr`, `seconds_since_confirm`,
`drawdown_from_hwm_atr`) and keeps, per trade, the single row that is that trade's most
extreme value of `col` — i.e. the DESC direction of `C4_DRAWDOWN_FROM_HWM_ONLY` picks
whichever rung had the *largest* drawdown-from-HWM among **all** rungs that trade ever
produced. Knowing which rung is a trade's eventual maximum-drawdown rung requires having
already observed every later rung of that same trade — the identical failure class as
`running_extremum_mechanically_contains_eventual_extremum` (project memory, Aug 2026).
Contrast with the ML trigger, `_first_trigger` (`phases.py:188-195`), which is correctly
the *first chronological* qualifying row per trade. The comparison the study calls
decisive is therefore causal-vs-hindsight, not causal-vs-causal.

This selection feeds `analysis/gates.py:124-134` (`beats_placebo`), where
`fam[prefix] = float(v.min())` takes the more negative of the two (ASC/DESC) directions
per control family, and `beats_placebo` is one of the eight AND-ed D1 conditions
(`gates.py:132-134`) and drives `control_killed` (`gates.py:148-149`), which
**dominates the routing** ("D3 dominates D2" per SPEC §10). A hindsight-selected C4
control can be pulled either stronger or weaker than any real single-variable rule could
ever fire on live, purely by the mean-reversion/reflection structure documented in
project memory — this can flip `beats_placebo` from pass to fail (or vice versa) and
change the terminal label the entire study exists to produce. `C2`/`C3` in the ASC
direction happen to coincide with the first chronological row only because
`rung_atr`/`seconds_since_confirm` are incidentally monotonic within a trade — this is
not enforced and `C4` (both directions) and the DESC direction of `C2`/`C3` are not
causal under any interpretation.

**Smallest fix:** For C2/C3/C4, select the first row per trade at which `col` first
crosses a threshold going forward (or restrict to `rung_ts <= ` the ML trigger's own
`rung_ts` for that trade), never `groupby(...).head(1)` on a `col`-sorted global frame.

## Warnings

### [F2/C1] `implementation/timing.py` Phase-7 timing window may censor unevenly across score cuts, uncontrolled
**Evidence:** The LONGEST-horizon walk (`timing.py:70-90`) correctly clamps
`stop = min(searchsorted(rung_ts + 300s), unc_i)`, where `unc_i` is each trade's own
natural terminal (opposing flip or session close) — so the *available* forward window
length varies row-by-row, and `window_reached_horizon` / `window_bars_available` are
computed to flag this (`timing.py:86-90`). But `phase7_geometry` (`phases.py:142-176`)
never aggregates or reports either field per cut — `_med` (`phases.py:179-183`) silently
`.dropna()`s unresolved rows. If the bottom-decile score correlates with trades that are
already near their own opposing-flip terminal (plausible, since a low score is meant to
flag deterioration), the bottom-decile median `secs_to_*` would be computed over a
systematically more-censored, resolved-only subset than the ALL population — the same
"length-blind placebo" failure class flagged in project memory, applied here to a
descriptive table rather than a control. I cannot confirm the direction or magnitude
without running the re-derivation, so this is not demonstrated as changing a number —
it is a real, unverified comparability gap.
**Smallest fix:** Report `pct_window_reached_horizon` (or `pct_resolved`) per cut
alongside every `median_secs_to_*` in `low_tail_forward_geometry.csv`.

## Notes

### [C1] `implementation/phases.py:419-441` — `phase10_mechanism`'s overlap diagnostic reuses the same hindsight-extremum selection
`ml_trigger_overlap_with_drawdown_rule` (`phases.py:434-441`) builds its "rival" set with
the identical `groupby(...).head(1)` global-extremum pattern as the Critical finding
above. It is explicitly descriptive ("no claim that a difference here is causal") and
does not feed the decision gate, so it is a NOTE, not a second CRITICAL — but it should
be fixed alongside the C4 control since it is the same code smell.

## Referred to contract-checker
- `analysis/gates.py:44-46` (V6) only asserts uniqueness (max 1 row per cut/trade); it
  does not independently verify SPEC §9's stated second half of V6 ("its `rung_ts` is
  the minimum ... among that trade's qualifying observations") — gate-fidelity to the
  frozen check text, C4 scope. (The underlying `_first_trigger` construction itself
  **is** verified causal in this pass — see Clean checks.)

## Clean checks
- A1-A5, B1-B10: not applicable / no violation found (no new pandas rolling/resampling
  paths; frozen artifacts loaded read-only in `common.py:load_full`).
- C1: label/feature separation intact in `timing.py` (`chk_*` re-derived quantities are
  forward-only, sliced `r+1:stop+1`, never index `r` itself) and in `common.py`
  (`exit_now_mark_atr`, `cme_mark` use only contemporaneous `return_from_entry_atr`).
- C2: label timestamps (`rung_ts`) align to feature row keys via exact-match merge
  (`timing.py:127`, `validate="1:1"`).
- C3: not applicable (no train/test split constructed in this study; V4/seal enforce the
  frozen 2024 OOS partition).
- `_first_trigger` (`phases.py:188-195`) verified genuinely chronological: sorts
  ascending on integer-ns `rung_ts`, `kind="stable"`, `groupby(...).head(1)` — correct.
- F1-F4: no new session/timezone logic (inherited RTH filter from predecessor, unchanged).
- G1-G4: `timing.py` re-derivation calls the already-accepted `MarketData`/`RegimeIndex`
  loaders; no new resampling or roll handling introduced.
- H1: `timing.py` uses `bar_hi`/`bar_lo` (HIGH/LOW) for all barrier/extreme detection,
  never close.
- H2: temporal resolution is the underlying 1s bar array inherited from `engine.prepare()`
  (`Window.ts`), matching NT execution granularity; no coarser aggregation introduced.
- H3/H4: no new re-entry or fill-price logic in this study; all economics reuse frozen,
  already-fill-resolved `return_from_entry_atr` / `nat_terminal_return_atr` fields.
- Same-bar ADVERSE-wins convention (`timing.py:63-64`) is inherited and disclosed
  (SPEC §7), and is empirically self-verified by gate V7 (0/2,991 mismatches per task
  context) — not re-litigated here.
