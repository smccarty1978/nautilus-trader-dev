# SESSION HANDOFF — chore/volume_clock_tracker (merge-ready, NOT merged)

**State:** `tracker.volume_clock.developing` is PROMOTED on `chore/volume_clock_tracker`. All technical gates pass
(`README.md` §1). The workflow requires explicit approval for the merge into main
(`DESTRUCTIVE_ACTION_REQUIRES_APPROVAL`; study `nq_developing_volume_clock` does not declare `platform_merge: auto_if_green`).

## Next session (merge, after explicit owner approval)

1. In the main checkout: `git merge --no-ff chore/volume_clock_tracker`. Message: `merge(chore/volume_clock_tracker):
   tracker.volume_clock.developing -- causal developing volume clock on 1s OHLCV, exact vc_v1 Stage C parity`.
2. On main: `python scripts/research.py cap generate --check`.
3. Record CAPABILITY_COMPLETE for the study gap (`studies/nq_developing_volume_clock/CAPABILITY_GAP_HANDOFF.json`, G1),
   then release the chore claim `volume_clock_tracker` (`ws chore release`).
4. There is no need to re-run the broad gate unless main moves before the merge. It is at `e3db799d`, and the gate ran on `c31d42ec`.

## Notes for the study session (do not act on them in the chore)

- The `vclock` context must add `dataset: NQ_1S_V2_GLOBEX` and `bars: 1s` (PARAMS `dataset` is REQUIRED).
- Warmup: the roll-transition rule needs ≥ 10 eligible sessions, and calibration needs 5 prior FULL sessions.
  Verify that the declared 14-day warmup covers this, or widen it, before collection. The tracker emits uncalibrated null state until then.
- Fields: `session_elapsed_s`, `rate_last_10s/15s/30s`, `dir_d60`, `k25/k50/k75_*`, and the 54 fields in the proposal YAML.

## Operational notes

- The `ws claim` worktree-lease limitation is unchanged and documented as an operational issue. It is not resolved here.
- The broad test run rewrote tracked study audit files (`studies/es_wick_imbalance_acceptance_v2/audit/*`,
  three `research_decision_fidelity_report.json`) and created `research_workflow/tests/first_passage_parity.json`.
  These are test side effects, deliberately **not committed** and not cleaned up.
- The replay inputs are reusable: comparison re-runs offline in about 3 s from `replay/` (command in `README.md` §2).

## Scope kept

No merge, no study-design change, no observations, outcomes, models or predictive results, no 2026 data, no
downloads, no change to the frozen vc_v1 results.
