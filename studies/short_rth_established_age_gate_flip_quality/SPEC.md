# Established-Regime Age Gate Study — 120s vs 240s

## Status

**COMPLETE. Final decision: `AGE_GATE_INCONCLUSIVE`.** See `STUDY_REPORT.md`
for the full write-up. Raising the gate from 120s to 240s costs under 1% of
regimes every year and lifts the raw bearish-flip-within-300s rate
consistently (+0.2 to +0.8pp, all 6 years) — but produces no meaningful
improvement in feature-separation learnability, univariate (AUC differences
in the 4th decimal across all families/labels/gates) or bounded-multivariate
(no consistent winner across gate x target x model, likely underpowered at
~1,700 first-eligible rows/year). Recommend keeping 120s as the operational
default; audit PASS, 0 CRITICAL (1 WARNING + 2 NOTEs found and fixed
post-audit, full pipeline re-run clean).

## Decision to inform

Whether future short-RTH regime-weakness models should train on a
120-second or 240-second established-regime age gate. Diagnostic/population-
quality study — not a deployable-model study.

## Primary hypothesis

The 120s established-regime gate is too permissive (includes fakeouts/early
failures); requiring `regime_age_seconds >= 240` (holding the gate's other
existing criteria fixed) produces a cleaner short-RTH population for
predicting bearish regime flips and post-flip follow-through.

Null hypothesis: the 240s gate removes too many opportunities, arrives too
late, or does not improve out-of-sample flip-quality separation versus the
120s control.

## Scout-pass findings (grounds this SPEC in verified fact, not assumption)

1. **Gate A is not literally "age >= 120" alone — it is the existing,
   already-frozen established-regime filter** (`CODEX_5_X_established_fade_policy.json`
   → `filter`, also `entry_surface.build_surface`'s `established` check):

   ```text
   regime_age_s_min = 120 (Gate A) / 240 (Gate B) / 180 (optional bridge)
   running_mfe_atr_min = 1.0        (unchanged, both gates)
   new_progress_windows_min = 2     (unchanged, both gates)
   retained_mfe_ratio_min = 0.5     (unchanged, both gates)
   ```

   The brief's abbreviated 3-line gate definition omits
   `new_progress_windows_min` (present in the real filter); this is treated
   as shorthand for "vary only the age parameter, hold every other gate
   criterion fixed" — the correct experimental-design interpretation (isolate
   one variable), not an instruction to drop a criterion. Gate A therefore
   reproduces the existing, already-reconciled 813,972-row (2021-2024) +
   198,255/63,021-row (2025/2026) surface **exactly** — it is not rebuilt.

2. **Canonical feature+label input**: `studies/ohlcv_volume_delta_price_level_features/_work/full_{year}.parquet`
   (same as `[[short_rth_enriched_retrain_overfits_2025]]`) — 149 existing +
   461 new features (`ohlcv_est_delta` 214, `price_level_context` 247),
   Policy A diagnostic labels, 0 provenance violations, rows/labels verified
   unchanged from the feature-foundation study's own join checks. **Does
   not** carry the raw gate-input columns (`regime_age_s`, `running_mfe_atr`,
   `retained_mfe_ratio`, `new_progress_windows`, `confirm_flip_ns`) — those
   were dropped when the prior retrain study joined labels onto the surface.
3. **Gate-input columns are recovered by a cheap, exact rejoin**, not
   recomputed, from the surfaces `entry_surface.build_surface` itself
   produced:
   - 2021-2024: `studies/short_rth_entry_surface_backfill/_work/surface_{year}.parquet`
   - 2025-2026: `studies/short_rth_entry_surface_backfill/results/reconciliation_2025_2026_surface.parquet`
     (filter `year==`)
   Verified by direct key comparison: `(regime_start_ns, observation_time)`
   in both files match `full_{year}.parquet` **exactly**, sorted-equal, for
   2021 and 2025 (representative years; the join itself will assert 100%
   match for all 6 in Phase 0). `full_{year}.parquet` has zero
   `label_available == False` rows (198,255/198,255 for 2025) — no censored-
   row handling needed.
4. **Empirical age-gate impact, checked directly on real data before writing
   any pipeline code** (this is the single most important scout-pass
   finding — it recalibrates what the study can plausibly conclude):

   | Year | Regimes @120s (Gate A) | Regimes @240s (Gate B) | Regimes lost | Rows with age≥240 |
   |--|--:|--:|--:|--:|
   | 2021 | 1,762 | 1,755 | 0.40% | 99.30% |
   | 2022 | 1,711 | 1,699 | 0.70% | 99.16% |
   | 2023 | 1,732 | 1,719 | 0.75% | 99.42% |
   | 2024 | 1,672 | 1,660 | 0.72% | 99.39% |
   | 2025 | 1,678 | 1,669 | 0.54% | 99.39% |
   | 2026 | 532 | 528 | 0.75% | 99.42% |

   Raising the gate from 120s to 240s **removes well under 1% of regimes
   entirely, every year** — the vast majority of established regimes are
   already well past 240s of age by the time any checkpoint first satisfies
   the other three criteria (median first-eligible age is materially above
   120s already; 2021's minimum observed age-at-first-eligibility is 130s,
   not 120s). This means: (a) opportunity-count preservation (key question
   5) is very unlikely to be the deciding factor either way — both gates
   keep effectively the same regime population; (b) the real test is
   entirely about the **first-eligible-per-regime surface** — *which*
   specific (generally later, occasionally different) checkpoint within each
   surviving regime gets selected as the training row, and whether that
   later checkpoint has cleaner flip-quality labels. The full-checkpoint
   surface for Gate B is a strict row-subset of Gate A's (age≥240 with
   identical other criteria strictly implies Gate A's own established
   condition), so Gate B's full/first-eligible surfaces are built by a pure
   filter on `regime_age_s`, not a rebuild.

5. **New regime-transition labels resolve almost entirely to existing,
   already-audited columns** — only one label genuinely requires new
   raw-bar computation:
   - `bearish_flip_within_300s` = existing `aligned` column, unchanged
     (Policy A's own "aligned" is defined as exactly this: bearish
     alignment/flip at or before the 300s confirmation deadline).
   - `no_flip_before_timeout` = `NOT aligned` (same 300s deadline; "timeout"
     is not a new invented parameter — it is Policy A's own `TIMEOUT_NS`,
     confirmed `= 300 * NS` project-wide, reused for consistency rather than
     inventing a second timeout convention).
   - `adverse_move_1p25A_before_bearish_flip` = existing `hit_pre_alignment_stop`
     column, **exactly**, not merely similar: `label_full_surface.label_row`
     defines the 1.25×ATR pre-alignment stop as literally "adverse move
     reaches 1.25×ATR before alignment-or-300s-timeout" — the two are the
     same condition by construction, traced directly in
     `label_full_surface.py:46-130`.
   - `time_to_bearish_flip_s` = `(confirm_flip_ns - observation_time) / 1e9`,
     pure arithmetic once `confirm_flip_ns` is rejoined (finding 3).
   - `bearish_flip_within_600s` = `time_to_bearish_flip_s <= 600`, pure
     arithmetic, no raw-bar scan.
   - **`post_flip_mfe_atr_300s` / `post_flip_mfe_atr_600s` genuinely require
     new raw-bar computation** — no existing column measures a *fixed*
     300s/600s window anchored at the actual flip; `post_align_mfe_atr`
     (existing) is bounded by Policy A's own conditional exit (1.50A stop or
     opposing flip), which can be earlier or later than a fixed window, so
     it is not a valid substitute. Computed **once per distinct
     `regime_start_ns`** (all checkpoints in a regime share the same flip
     time and therefore the same raw post-flip price path — this is a
     regime-level property, not a per-checkpoint one) using 1-second bars
     from `confirm_flip_ns` forward, anchored at that bar's open, then
     broadcast to every checkpoint row in the regime and normalized by each
     row's **own** `atr_at_entry` (= `atr_at_checkpoint` at that row,
     consistent with how every other `_atr` field in this project is
     computed — never a shared "regime ATR").
   - Follow-through labels are then pure combinations of the above:
     `bearish_flip_within_{300,600}s_and_followthrough_1A` =
     `bearish_flip_within_{300,600}s AND post_flip_mfe_atr_{300,600}s >= 1.0`;
     `flip_but_no_followthrough` = `bearish_flip_within_600s AND NOT
     bearish_flip_within_600s_and_followthrough_1A`.

6. **Feature sets reuse `[[short_rth_enriched_retrain_overfits_2025]]`'s
   F0/F1/F2/F3 construction verbatim** (`phase0_prepare_data.py`'s
   `find_position_cols`/`one_hot_position_cols`/family-membership logic,
   imported not reimplemented) — same 149/214/247/29-categorical
   composition, same exclusions (4 provenance columns, 2 `*_name` columns).

## Population

* Instrument `NQ`, direction `short only`, session `RTH only` (existing
  remediated fill-time convention, unchanged), regime context `prevailing
  bullish`. No long fades, no ETH.
* Years: 2021-2026, all six, every diagnostic reported per-year (this study
  has no fixed train/dev/test role beyond the optional diagnostic model in
  the last section — the primary population/label-quality comparison uses
  all years).

## Gates to compare

Gate A (120s control) and Gate B (240s proposed) per finding 1 above.
Optional 180s bridge, diagnostic only, built the same way (pure filter), run
only if it does not materially extend runtime beyond Gates A/B (it does not
— identical mechanism, same joined columns, one more filter pass).

## Candidate construction

Two surfaces per gate, per year (finding 4):
- **Full checkpoint surface**: every row in `full_{year}.parquet` (after the
  gate-column rejoin) satisfying that gate's `regime_age_s` threshold — Gate
  A is the unfiltered joined surface; Gate B/bridge are row-filters on it.
- **First-eligible-per-regime surface**: `groupby(regime_start_ns).first()`
  after sorting by `observation_time`, on each gate's full checkpoint
  surface — the checkpoint used for the population/label-quality comparison
  itself (not a trading policy).

## Labels

Primary regime-transition labels (finding 5): `bearish_flip_within_300s`,
`bearish_flip_within_600s`, `time_to_bearish_flip_s`,
`bearish_flip_within_300s_and_followthrough_1A`,
`bearish_flip_within_600s_and_followthrough_1A`, `post_flip_mfe_atr_300s`,
`post_flip_mfe_atr_600s`, `adverse_move_1p25A_before_bearish_flip`,
`no_flip_before_timeout`, `flip_but_no_followthrough`. Policy A outcome
labels (`hit_pre_alignment_stop`, `hit_timeout`, `hit_post_alignment_stop`,
`opposing_flip_exit_positive`/`hit_opposing_flip` combined per
`[[short_rth_enriched_retrain_overfits_2025]]`'s `outcome_class` mapping,
`net_pnl`) are joined as diagnostics only — never a primary target here.

## Feature sets

F0/F1/F2/F3 exactly as finding 6. Any model training in this study is
diagnostic only (see "Optional diagnostic model"); no deployable strategy
model is trained.

## Required diagnostics

Per gate (A/B, + bridge if run) × per year (2021-2026) × {full checkpoint
surface, first-eligible surface}: regime count, checkpoint-row count,
median `regime_age_s` / `running_mfe_atr` / `retained_mfe_ratio` at
candidate, `bearish_flip_within_300s` rate, `bearish_flip_within_600s` rate,
followthrough-1A rate after flip, `adverse_move_1p25A_before_bearish_flip`
rate, Policy A `opposing_flip_winner` rate / `pre_alignment_stop` rate /
`timeout` rate (diagnostic only).

## Model-free information-content diagnostics

Per gate, for `bearish_flip_within_300s`,
`bearish_flip_within_300s_and_followthrough_1A`,
`adverse_move_1p25A_before_bearish_flip`: AUC, Cohen's d, decile
monotonicity, year-by-year stability, computed separately per feature family
(existing / volume-delta / price-level / combined) on the first-eligible
surface (the deployable-candidate framing) using the same univariate
methodology this project already uses for information-content probes
(`[[ohlcv_volume_delta_price_level_features_accepted]]`'s own "next bounded
study" recommendation). No threshold selection.

## Optional diagnostic model

If the model-free diagnostics justify it: regularized logistic regression +
shallow GBT, train 2021-2024 / inspect 2025 / sealed-diagnostic 2026,
targets `bearish_flip_within_300s_and_followthrough_1A` and
`adverse_move_1p25A_before_bearish_flip`, reusing
`[[short_rth_enriched_retrain_overfits_2025]]`'s `train_and_evaluate.py`
model-fitting code (`fit_logistic`/`fit_gbt`) rather than reimplementing.
Explicitly not a production candidate — answers only "is the 240s surface
more learnable than 120s," reported as `results/optional_model_diagnostics.csv`.

## Key comparison questions

Answered directly in `STUDY_REPORT.md`: (1) does 240s reduce fakeout/noisy
candidates vs 120s, (2) does 240s improve bearish flip rate, (3) does 240s
improve flip-plus-followthrough rate, (4) does 240s reduce adverse-before-
flip failure, (5) does 240s preserve enough trade count (finding 4 already
suggests: yes, trivially — under 1% regime loss every year), (6) do
volume/delta features separate flip quality better under 240s, (7) do
price-level features separate flip quality better under 240s, (8) does 240s
look like a better training surface overall.

## Forbidden

No changes to Policy A, RTH definition; no long fades, no ETH, no new
exits; no trading-threshold tuning or stop/target optimization; no 2026
model selection; no deployable strategy model; no interpreting overlapping
full-checkpoint-surface PnL as a strategy result; no new feature
interactions.

## Required artifacts

```text
studies/short_rth_established_age_gate_flip_quality/
  SPEC.md
  results/gate_population_summary.csv
  results/gate_label_quality_by_year.csv
  results/gate_feature_separation.csv
  results/first_eligible_surface_summary.csv
  results/full_checkpoint_surface_summary.csv
  results/optional_model_diagnostics.csv
  results/manifest.json
  audit/audit.md
  STUDY_REPORT.md
  REPRODUCE.md
```

No `implementation/` subfolder — the study reuses production feature code
from `features/` and study-local Phase-0/label code from this directory,
importing (not duplicating) `[[short_rth_enriched_retrain_overfits_2025]]`'s
feature-set construction where noted above.

## Final decision labels

```text
AGE_GATE_240_ADOPT_FOR_TRAINING
AGE_GATE_120_REMAINS_BEST
AGE_GATE_240_TOO_LATE
AGE_GATE_INCONCLUSIVE
AGE_GATE_REQUIRES_REMEDIATION
```

## Final report must answer

1. Is 120s too early/noisy? 2. Does 240s produce a cleaner established-
regime population? 3. Does 240s improve flip-quality labels? 4. Does 240s
preserve enough opportunities? 5. Which feature families look more
informative under 240s? 6. Should the next enriched training study use 240s
as the base gate? 7. What is the next bounded step?

## Guardrails

Mandatory `lookahead-auditor` pass, 0 CRITICAL required before accepting
results. No model training/threshold optimization beyond the bounded
diagnostic model above.
