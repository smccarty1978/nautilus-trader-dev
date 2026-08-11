# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-11
**Scope:** implementation/engine.py, implementation/geometry.py, implementation/build.py,
implementation/validate.py, analysis/buckets.py, analysis/phases.py, analysis/gate.py,
analysis/harvest_control.py, analysis/close_out.py (causality only — A, B, C1–C3, F, G, H
per docs/CAUSAL_CHECKLIST.md). SPEC.md §5 (D1–D9) read as the frozen causal contract.
**Scope hash:** 0c88030ec8edec43000024fbb1a1b7c92c29d785d294401ffab45c482ee78fb1
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 14 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 2

## Findings

### Causal boundary (D3) — verified clean
`engine.py::TradeForward.state_at(j)` reads only prefix-bounded arrays (`w.mark[j]`,
`w.run_mfe[j]`, `w.last_ext[j]`, slices `[ci+1:j+1]`) and `forward_at(j)` builds suffix
arrays sliced `[j+1:unc+1]` — there is no array construction anywhere in this module that
spans the observation index. This is independently proved, not just read: `validate.py`
gate 8 recomputes 7 state fields and 3 label fields from the raw 1s canonical parquet on
two separately truncated slices (state hard-truncated at `j`; labels beginning at `j+1`),
for 300 sampled trades / 8,671 observations, `total_mismatches: 0`,
`boundary_violations: 0` (`results/validation_report.json`). Both directions of the
boundary are demonstrated rather than asserted.

### H4 fill convention — verified clean
Every trigger fill routes through `Window.realise(i, fill_next=True)`
(`top10_fast_confirm_runner_path/implementation/engine.py:101-112`), which prices at
`market.open_[start+i+1]`, never at bar `i`'s own high/low/close. Confirmed at every call
site touched by this study: `economics_at.exit_now_fill_atr` (`engine.py:216`),
`harvest.harvested`/`ret_a/b/c` (`geometry.py:144,151,155`), both placebo draws
(`geometry.py:50,63`), and the harvest-control placebo/rung fills (`harvest_control.py:58,
64,73`). No sim in scope computes `(trigger_px - entry_px) * MULT`.

### D1 dual-track discipline — verified clean
`cv_stop_live_atr` is `None` (not imputed) whenever `j > w.nat_i`
(`engine.py:223-224`); `forward_net_to_nat_exit_atr` is likewise `None` when `j > w.nat_i`
(`engine.py:157,182-183`). `validate.py`'s reconciliation check
(`natural_exit_reconciles_from_every_observation`, lines 246-260) confirms
`exit_now + continuation == natural_return` on both the mark basis and both fill bases for
every one of 140,929 observations, `violations: 0`.

### D4 progress-lookback nulling — verified clean
Both `engine.py:128-137` (this study) and the inherited
`top10_fast_confirm_runner_path/implementation/engine.py:319-327` null
`favorable/adverse/mark_progress_last_{15,30,60}s` when `ts[j] - confirm_ns < W·1e9`,
matching SPEC D4 exactly.

### D6 race resolution — verified clean
Same-bar collisions (`tf == ta`) resolve `ADVERSE` with `_ambiguous = True`
(`engine.py:203-209`), and `validate.py` counts the ambiguous share per pair and every
downstream race table (`buckets.py::race_exprs`) carries `_optimistic` and `_unresolved`
alongside the conservative rate. No table reports the optimistic bound as primary.

### Placebo disclosure (invariant 5) — verified accurate, no conclusion rests on it
`geometry.py:39-93` implements both the lifetime-uniform placebo (index-uniform draw over
`[ci, nat_i)`, explicitly commented "a benchmark, never a rule" because its support depends
on the realised lifetime) and the length-blind placebo (grid-offset draw, falls back to
`fwd.nat_ret` when the offset lands past `nat_i`, so it is causally implementable). The
same split is reproduced in `harvest_control.py:60-73`. `close_out.py`'s q11/q12 answer
explicitly reports the gap collapsing under the causal version
(`"+0.618 -> +0.011 ... on >=3 ATR runners the causally implementable version is sharply
negative"`) and `final_classification` is **E**, which does not depend on the
lifetime-uniform number. `validate.py`'s own gate text states the distinction correctly.

## Notes

**[N1]** `geometry.py::harvest` and `harvest_control.py::evaluate` both scan for rung
achievement from index 0 (`w.bar_hi[:unc+1]`), i.e. a rung may be flagged "achieved" before
the confirming flip. This is disclosed via `achieved_pre_confirm` in the output row and is
a description of the whole trade path, not a trigger fed into a causal decision — no
CRITICAL/WARNING failure path exists. Flagging only because a future reader could mistake
"achieved" for "achieved post-confirmation" without checking the flag.

**[N2]** `validate.py` gate `auditors_clean` currently reads `False` because
`audit/status.json` (this file's sibling) and `audit/contract_status.json` do not yet
exist — this is expected pipeline sequencing for a first completion-audit pass, not a
causal defect.

## Referred to contract-checker
- `README.md` and `REPORT.md` (Deliverables Manifest item #19) are not present in
  `studies/post_confirm_forward_opportunity/`; `audit/contract_status.json` also absent.

## Clean checks
- A1, A2 (ts_init-based indexing throughout; `ts` arrays are `ts_init` from the canonical
  store, never `ts_event`)
- B1-B7, B9 (no `center=True`, no `.shift(-N)`, no `bfill`; all `cummax`/`cummin` are
  prefix/suffix bounded by construction)
- C1-C3 (retrospective labels `eventual_max_mfe_atr`, `runner_bucket`, `reached_*` appear
  only in `trade_meta`/diagnostic aggregation, never in `state_at` or a trigger; D1-D9
  contract verified against implementation line-by-line)
- F1-F2 (RTH session containment verified by `validate.py` gate
  `session_containment_no_overnight`, 0 violations across trade and observation levels)
- G1 (upstream store is `*.v.0`; not re-verified here, inherited from accepted upstream
  studies)
- H1-H4 (bracket/rung/placebo fills all route through `Window.realise` with
  `fill_next=True`; no close/high/low used as a fill price anywhere in scope)
