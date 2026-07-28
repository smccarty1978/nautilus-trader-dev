# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-07-27
**Scope:** collector.py, writer.py, run_collect.py, run_months.py, consolidate.py,
identity.py, independent_audit.py, reconcile_regime_count.py,
build_threshold_contracts.py, analysis/generate_populations.py (plus
phase_b_strategy.py, phase_a_strategy.py, fable5 `RegimeEngine` read for
causal context only, not audited as new code).
**Scope hash:** a16c943b2253b85eb68cfe9834b70b9a9f011a41a162d52eb51360ea828c2609
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 20 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 1
- Note: 2

## Warnings

### [G2] `collector.py:100-161`, `run_collect.py:94-146` — path rows can be silently dropped for a regime that outlives one partition's warmup window
**Failure path:** `_open_regime` is created only inside `_open_new_regime`,
which fires only on a detected `flip` in `_on_1m` (`collector.py:171-188`). Each
monthly partition starts a *fresh* `RegimeCompleteCollector` warmed up from
`load_start = start - 4 days` (`run_collect.py:60,95`). If a regime's actual
start is more than `WARMUP_DAYS` (4) before a partition boundary and it has not
reversed by the time the next partition begins, the next partition's collector
never observes the flip that opened it, so `self._open_regime` stays `None`
until the *next* real flip inside that partition. Every 1s bar in that gap
hits `_append_path_row`'s early return (`regime is None: return`,
`collector.py:143-145`) and is dropped from `paths` — with no `regime_id`,
no row, and no entry in `missing_dispatch` (that table only tracks score-grid
gaps, not path gaps). `reconcile_regime_count.py` and `independent_audit.py`
verify regime *start* counts and per-regime `path_row_count` self-consistency,
but neither checks for a whole *missing* regime spanning a partition boundary
this way, so the drop would not surface in either existing check.
**Smallest fix:** either lengthen warmup to the observed max regime duration
with an assertion, or detect on the first `_on_1m` call whether the engine's
direction is already non-zero and open a synthetic regime record dated to
warmup start (matching what `full_trade_path_builder`'s cold-start disclosure
already does for flip counts, extended to path coverage).

*Note: regime frequency in the store (~137.7K regimes / ~1,260 trading days,
≈109/day) makes a single regime surviving 4+ days without a reversal an
extreme outlier; I found no direct evidence this has occurred in the sealed
2021-2025 build. Flagged as WARNING, not CRITICAL, because the mechanism is
concrete but unconfirmed to manifest.*

## Notes

- `build_threshold_contracts.py:9-12,251-259` reproduces (bit-exact,
  assert-or-abort) thresholds calibrated on calendar-2025 data and applies them
  to the 2021-2025 evaluation population, which includes 2025 itself — a
  within-year threshold/evaluation overlap. This is not new to this study: it
  is inherited from `full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`
  (human-authorized 2026-07-25), carried forward with `overlaps_evaluation_window
  = true` and disclosure text on every emitted row
  (`build_threshold_contracts.py:251-257`). Verified the disclosure/waiver
  chain is intact; not re-litigating the authorized decision.
- `collector.py:135` (`DECISION-1`) intentionally removes the RTH gate on
  score dispatch so ETH checkpoints score too. Verified this cannot leak into
  entry populations: `_augment_score_row` (`collector.py:261-281`) forces
  `bullish_in_domain`/`bearish_in_domain` to `False` for any non-RTH
  `decision_ns`, and every population query in `generate_populations.py`
  (`_candidates`, `all_crossings_population`, `highest_score_population`,
  `first_after_established_population`) filters on `{prefix}_in_domain` before
  selecting candidates. Clean.

## Referred to contract-checker
- No path-row-coverage test exists for regimes spanning a partition boundary
  beyond the count/hash checks already in `consolidate.py`/`independent_audit.py`
  (completeness/test-quality — see the G2 warning above for the causal
  mechanism, which is in my scope; whether a new test is *required* is not).

## Clean checks
- A1, A2, A5: `decision_ns`/`checkpoint_decision_ns` used throughout is
  `bar.ts_init` (close time) end-to-end from `collector.py` through
  `writer.py`'s `_session_expr`/`_year_expr`; no `ts_event` used for
  session/year classification.
- B1-B7: no `center=True`, no `.shift(-N)` (only backward `shift(1,
  fill_value=False)` in `generate_populations.py:129-131`), no `bfill`,
  `RegimeEngine`/`PrevailingDomain` are purely causal recursive updates fed
  current-bar-only values (verified against `independent_audit.py`'s
  from-spec reimplementation, which agrees on sampled regimes).
- C1-C3: `paths` (label/telemetry) table's terminal columns
  (`regime_end_decision_ns`, `is_opposing_flip_row`, etc.) are confined to the
  paths table by design (`writer.py:99-101` — "Entry-dependent quantities are
  forbidden here"); the `scores` table (features) carries none of them.
  `generate_populations.py` splits are governed by `checkpoint_decision_ns`
  ordering only, no random splitting.
- F1-F4: session classification uses close-time (`ti`/`path_init_ns`) with
  named zone `America/Chicago` throughout (`phase_a_strategy.py:27-30`,
  `writer.py:42-55`); no naive timestamps, no fixed-offset arithmetic.
- G1, G3, G4: no resampling in the audited files; `*.v.0` continuous catalog
  is the only source referenced (`writer.py:22`, `independent_audit.py:20-29`).
- H1-H4: no bracket/fill simulation exists in the audited files;
  `reentry_capability`'s "hypothetical stop" is a row-count diagnostic, not a
  PnL/fill computation.
- Score-row carry-forward arithmetic (`score_age_seconds`, `is_carried_forward`,
  `established_state`) verified non-negative/monotonic by construction —
  `_emit` always precedes `_append_path_row` within the same `_on_1s` call, so
  `last_score_decision_ns <= path_init_ns` always.
