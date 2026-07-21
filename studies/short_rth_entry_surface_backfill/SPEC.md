# Short-RTH Entry Surface Backfill

## Objective

Build (or precisely specify, if not yet buildable) the causal 2021-2024
short-RTH entry-surface dataset needed before
[[short_rth_w4_retrain_entry_strength]] can retrain a short-RTH-only entry
model. The target of this study is **not** a retrained model and **not**
"W4 threshold crossings" — it is a comparable, non-circular labeled surface:
every eligible established-bullish-regime RTH short-fade checkpoint in
2021-2024, with the same causal feature vector and the same Policy A outcome
labels already used for 2025-2026. This study does not train, select, or
promote anything; it produces a dataset and a feasibility verdict.

## Blocking defect being resolved

`short_rth_w4_retrain_entry_strength` scoped its training population as "W4
threshold crossings" for 2021-2024. That population only exists via the
frozen W4 model's `w4_score`, and that model was trained on 2021-2024
(`CODEX_5_X_weakness_atlas_repair/CODEX_5_X_SPEC.md`) — scoring it against its
own training years is in-sample/circular. Checkpoint cadence for those years
is also 30s vs 5s for 2025-2026. Both issues were already hit and rejected for
an identical reason in `fable5_specialized_w4/SPEC.md` ("Split discipline",
2026-07-17). The fix is to stop defining the population by the frozen score
and instead define it directly from the causal established-regime gate, which
requires no score at all.

## Frozen inputs already available (reusable, unchanged)

- Repaired weakness atlas, 2021-2026, causally rebuilt from raw 1s bars:
  `studies/CODEX_5_X_weakness_atlas_repair/_work/CODEX_5_X_repaired_years/CODEX_5_X_weakness_atlas_repaired_{year}.parquet`.
  2021-2024 atlases are **30s** checkpoint cadence; 2025-2026 are **5s**.
- Raw 1-second bars, 2016-2026: `data/raw/NQ_v0_1s_{year}.parquet`
  (`_ytd` for 2026). Confirms 2021-2024 raw bars exist at full 1s resolution
  — a 5s rebuild is a data-availability non-issue.
- Established-regime filter, frozen and unchanged:
  `CODEX_5_X_established_fade_policy.json.filter` — `regime_age_s_min=120`,
  `running_mfe_atr_min=1.0`, `new_progress_windows_min=2`,
  `retained_mfe_ratio_min=0.5`. Operates only on atlas columns
  (`regime_age`, `current_mfe`, progress-window count, retained ratio) —
  **no dependency on `w4_score`.**
- RTH filter: `CODEX_5_X_run_established_fade.is_rth()` — pure timestamp
  check, cadence-independent.
- Policy A replay: `fable5_specialized_w4/fable5_common.simulate_trade_arrays`
  (array port, line-parity tested against
  `codex_5_w4_multi_candidate_reentry.run_study.simulate_trade`) — takes
  entry ts/px/direction/ATR plus the aligning-flip and next-scheduled-flip
  timestamps; no dependency on `w4_score`.
- Opposing-flip timeline: `CODEX_5_X_run_established_fade.canonical_regime_timeline`
  — rebuilds the full causal flip sequence per year from raw bars; cadence-
  independent.
- Progress-window counter: `CODEX_5_X_run_established_fade.progress_window_counts`
  — cadence-independent (operates on the running-MFE path, not the checkpoint
  grid).
- Causal feature vector definition (152 features: 47 center + 100 sequence +
  5 local) — same columns already present in the repaired atlas for every
  year 2021-2026 (`CENTER_FEATS`/`SEQUENCE_FEATS` in
  `CODEX_5_X_weakness_atlas_repair/train_weakness_model.py`, reused unchanged
  in `fable5_specialized_w4`).

## Missing artifacts

1. **A 5s-cadence repaired atlas for 2021-2024.** The existing
   `CODEX_5_X_build_repaired_atlas.py` already supports `step_s=5` (it uses
   exactly that value for 2025-2026: `step_s = 30 if year <= 2024 else 5`),
   but `parity_and_merge()` unconditionally requires a legacy atlas at the
   *same* cadence to reconcile against (`load_legacy_year` /
   `classify_noncausal_legacy_only`). No legacy 5s atlas exists for
   2021-2024, so the existing script cannot be pointed at `step_s=5` for
   those years without modification.
2. **A no-legacy-parity build path** that keeps every intrinsic causal check
   already in `parity_and_merge` (ATR positivity/finiteness, entry precedes
   flip decision, no non-causal endpoint checkpoints, current_mfe/mae ==
   running_mfe/mae, monotonic non-decreasing running MFE/MAE, zero negative
   excursion cells) but drops the legacy-atlas key-reconciliation step, since
   that step's only purpose is proving the repair matches a pre-existing
   30s atlas — not something a fresh 5s series can or needs to match.
3. **A checkpoint-level (not crossing-level) Policy A label pass** over the
   full eligible surface: for every checkpoint that passes the established
   filter, direction==1 (prevailing bullish), and is_rth, replay Policy A as
   if that checkpoint were an immediate entry (next raw-bar open at or after
   the checkpoint), using `canonical_regime_timeline` for the aligning flip
   and the next opposing flip. This differs from the existing
   `run_established_fade`/`multi_candidate_reentry` logic only in that it
   does **not** gate on a score threshold crossing — every eligible
   checkpoint gets a label, not just the first crossing. No such loop exists
   yet; it is a bounded adaptation of `codex_5_w4_multi_candidate_reentry`'s
   candidate-replay loop with the `strict_threshold_cross` gate removed.

## Cadence feasibility assessment

**Option A — rebuild 2021-2024 at 5s cadence (recommended).**
Mechanically feasible: raw 1s bars exist for all four years, and
`build_weakness_checkpoints_for_regime(step_s=5, ...)` is the identical
function already used for 2025-2026 — no new checkpoint-construction logic is
needed, only a fork of `build_raw_checkpoints`/`build_year` that (a) passes
`step_s=5` for 2021-2024 and (b) replaces `parity_and_merge`'s legacy-atlas
comparison with the intrinsic causal-audit assertions alone (item 2 above).
Cost: roughly 6x more checkpoint rows than the existing 30s atlas per year;
the regime engine and feature builders already run at 5s cadence for
2025-2026 without issue, so this is a runtime/storage cost, not a
correctness risk. This path removes the cadence confound entirely and is the
only path that lets 2021-2024 training features be apples-to-apples with the
2025 dev / 2026 OOS surface.

**Option B — reuse the existing 30s-cadence 2021-2024 atlas (fallback only).**
Zero rebuild cost (already built and audited: `CODEX_5_X_atlas_rebuild_{2021..2024}.json`
all show 0 monotonicity/negative-excursion violations). Carries forward the
same cadence-mismatch caveat already flagged in `fable5_specialized_w4`
("30s checkpoint cadence vs 5s for 2025/2026") — a model trained on
coarser-grained checkpoint timing may not transfer cleanly to a 5s-scored
population. Usable only as a documented-caveat diagnostic, not as the
primary training surface, if Option A proves too costly to build.

**Recommendation:** Option A. Build the 5s-cadence 2021-2024 atlas via the
no-legacy-parity fork described above, gated by the same intrinsic causal
checks the existing pipeline already enforces.

## Dataset contract (this study's actual deliverable)

For each year 2021-2024 (5s atlas, per Option A) and reusing 2025-2026
as-is:

1. Filter atlas checkpoints to: prevailing direction == 1 (bullish, so the
   candidate direction is short fade); established filter true (frozen
   thresholds above); `is_rth(observation_time)` true.
2. For each surviving checkpoint, construct a would-be entry: fill at the
   first raw 1s open at or after the checkpoint's `observation_time`; reject
   (and count) any checkpoint whose fill would land at or after its
   regime's `regime_end_ns` (no valid path, same guard already used in
   `run_established_fade`/`run_ladder`).
3. Replay Policy A independently for every surviving checkpoint (1.25A
   pre-alignment stop, 300s confirmation timeout, 1.50A post-alignment stop,
   opposing-flip exit) — unchanged contract, `simulate_trade_arrays`.
4. Label: `avoid_pre_alignment_stop` (primary), `net_pnl_usd`,
   `reaches_alignment_within_5m`, plus the 152-feature causal vector already
   defined in the repaired atlas, joined 1:1 by
   (`regime_start_ns`, `observation_time`).
5. Tag every row with `year`, `cadence` (`"30s"`/`"5s"`), and
   `established_filter_source` for downstream audit.

This is a checkpoint-level labeled surface (many rows per regime), not a
trade-level population — the same paradigm the original W4 model itself was
trained on, generalized so the *new* short-RTH model can learn from every
eligible opportunity rather than only from crossings of a threshold that
does not exist pre-2025 in a non-circular form.

## Split discipline (deferred to the retrain study)

This study does not train or select. It only certifies that a train/dev/OOS
split of `train: 2021-2024, dev/selection: 2025, sealed OOS: 2026` is
supportable on the delivered surface, and reports row counts, established-
filter survival rates, and RTH/short-fade survival rates per year so the
retrain study can size its splits before touching 2026.

## Required outputs

- Per-year row counts at each filter stage (raw eligible checkpoints →
  established-filter pass → RTH pass → valid-fill pass → labeled), 2021-2026.
- Cadence used per year, and — if Option A is executed — a side-by-side
  count of what the population would have been at 30s cadence for the same
  years (diagnostic only, to quantify the cadence-choice's practical size
  effect).
- Causal/parity audit: zero monotonicity violations, zero negative excursion
  cells, ATR positivity/finiteness, entry-precedes-flip-decision, on every
  newly built year — same checks already enforced for 2025-2026.
- Reconciliation: 2025-2026 rows produced by this contract's checkpoint-level
  loop, restricted to `candidate_seq==1` crossings of the frozen 0.688350
  threshold, must reproduce the existing audited short-RTH candidate
  population (650/222, `[[short_rth_threshold_ladder]]`) exactly. This is the
  parity gate that proves the new no-score loop is a strict generalization of
  the existing crossing logic, not a different population.
- Feasibility verdict and cost estimate for Option A (runtime, row count,
  storage) actually observed, not just estimated.

## Deliverables

`results/`: `short_rth_entry_surface_backfill_2021.parquet` ...
`_2024.parquet` (or combined), `short_rth_entry_surface_filter_stage_counts.csv`,
`short_rth_entry_surface_reconciliation_2025_2026.json` (parity gate above),
`short_rth_entry_surface_cadence_comparison.csv`, `final_report.md`.
`audit/`: `pre_execution_audit.md` (lookahead-auditor, mandatory before any
atlas rebuild or replay run per project CLAUDE.md), `completion_audit.md`.

## Final decision labels

```text
BACKFILL_COMPLETE_5S_FEASIBLE
BACKFILL_COMPLETE_30S_FALLBACK_ONLY
BACKFILL_PARITY_FAIL
BACKFILL_INFEASIBLE_COST
```

## Guardrails

No model training in this study. No threshold tuning. No change to Policy A,
the established-regime filter, or the RTH definition. No use of the frozen
W4 score for population membership in the 2021-2024 rows (that is precisely
the circularity being removed). The 2025-2026 reconciliation gate above must
pass before the 2021-2024 surface is considered usable — a mismatch means the
no-score loop is not a faithful generalization and the study stops and
reports `BACKFILL_PARITY_FAIL`. Mandatory `lookahead-auditor` pass before any
execution, per project CLAUDE.md invariant 5.

## Next concrete implementation step

1. Fork `CODEX_5_X_build_repaired_atlas.py` into a backfill variant (new file
   under this study's directory) that: sets `step_s=5` for 2021-2024, removes
   the `load_legacy_year`/`parity_and_merge` legacy-key reconciliation, and
   keeps every intrinsic causal assertion currently in that function.
2. Run it for 2021 only first (single-year smoke), check runtime/row-count
   against the Option A cost estimate, and run the mandatory pre-execution
   lookahead audit before touching 2022-2024.
3. Write the checkpoint-level (no-score) Policy A replay loop as a fork of
   `codex_5_w4_multi_candidate_reentry/run_study.py` with the
   `strict_threshold_cross` gate removed, and run the 2025-2026
   reconciliation gate against the existing 650/222 candidate population
   before trusting any 2021-2024 output.
4. Only after both gates pass, report `BACKFILL_COMPLETE_5S_FEASIBLE` and
   hand the dataset back to `short_rth_w4_retrain_entry_strength`.
