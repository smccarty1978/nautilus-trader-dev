# failed_breakout_tracker — capability evidence

Branch `chore/failed_breakout_tracker` (from main `53cc9638`), claim `failed_breakout_tracker` (claude).
Capability `tracker.price_level.failed_breakout` (status `verified`).

## What lands on main

| commit | content |
|---|---|
| `b081ec7e` | `features/trackers/price_level_failed_breakout.py` (`PriceLevelFailedBreakoutBinding`), proposal + contract `research_workflow/capabilities/proposals/tracker.price_level.failed_breakout.yaml`, registry entry, parity artifact `artifacts/parity/price_level_failed_breakout.json`, 29 tests |
| `750dc2a6` | test pinning first-RTH-bar arming on the last pre-RTH close; contract `reset_policy` says so; lookahead audit pass 01 |
| (this) | evidence: this README + `test_delta_broad.json` |

No `studies/` path is touched. No change to grammar, outcome kernel, collector or existing trackers.

## Episode contract (summary; authoritative text in the proposal)

Completed 1m bars and the existing `GenericPriceLevelProvider` levels (prior_day_high/low, overnight_high/low_final,
opening_range_30m_high/low_final). A level is *eligible* on bar T only if the provider published it after bar T-1;
*armed* when the previous completed close is at/inside it; *breach* = high >= L + 0.5 (low <= L - 0.5 for support), a
close beyond is not required; the episode starts at the breach bar's open; the extreme includes every episode bar
including the failure bar; *failure* = a close strictly back inside no later than start + 5 min (same-bar sweep
allowed); otherwise *accepted* (re-arms on a later close back inside). A level move / disappearance mid-episode
invalidates it. Repeats are unlimited and counted (`event_seq_level`). One primary event per bar, priority = declared
`levels` order; opposite directions on one bar => `conflict = 1`, no event. Reset at every non-RTH bar and at a
new trading day (17:00 CT). `stop_reference_price` = the frozen episode extreme, consumed by
`outcome.stop_reference` with `unit: structural` arms. Fixed defaults, no grid. The nq_pa_level_setups rolling-5m
sweep approximation is NOT used.

## Gates

* Targeted `test_delta` at `b081ec7e`: 93/93 (new file + capability, docs, structural-stop and FPR tracker tests);
  new file 30/30 at `750dc2a6`; `research cap generate --check` OK.
* Parity (`artifacts/parity/price_level_failed_breakout.json`): independent test-only forward-scan oracle (own
  trading-day grouping, own CT clock, own level rebuild) vs the runtime binding, per level and per bar, seeds 11 and 3:
  103 / 87 level events, 101 / 83 primary, **0 mismatches**; all six levels exercised (union coverage test).
* Causality: fields at T unchanged under a perturbed future; ON usable from the 2nd RTH bar, OR only after its final
  bar; no episode across the RTH close; level prices equal the provider's `snapshot()`.
  Lookahead audit pass 01: PASS_WITH_NOTES, the single note (first-RTH-bar arming) resolved in `750dc2a6`.
* End-to-end: compiled synthetic study -> HostCore with structural arms r1/r2 (buffer 0.25, tick 0.25,
  adverse_first): every candidate is an oracle event at T with matching direction; stop = extreme +/- 0.25 rounded
  away; risk and r2 target checked.
* Broad pre-merge gate (`test_delta_broad.json`):
  `python scripts/test_delta.py research_workflow/tests scripts/tests research/analysis/tests features/tests --json`
  at `750dc2a6`: ran 2,999, passed 2,908, failed 63, wall 7,783 s. All 63 are NEW only by `BASELINE_COMMIT_MISMATCH`
  (baseline at `c480d8af`). The 63 node ids are **identical** to the 63 of main's last broad gate
  (`artifacts/platform_v2/structural_stop_outcome/test_delta_broad.json`, head `8ac62d51`, merged as `53cc9638`):
  0 new, 0 fixed. The +30 run / +30 passed are this chore's test file. **0 failures attributable.** Baseline not updated.

## Limitations

* Conflict bars (opposite-direction failures on one bar) produce no candidate and are not counted as candidates by
  a study; the per-level `*_event` fields still expose them.
* Synthetic tapes sweep prior-day levels rarely (pdh 1, pdl 4 on seed 11); covered by the union test and GOLDEN
  step() scenarios, not by volume.
* Performance: ~79 us per 1m bar (reads the provider's raw levels, not the full `calculate()`).
