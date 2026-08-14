# Structural Regime Geometry within Maturity Buckets

**Study:** `Codex_structural_regime_geometry_maturity`  
**Frozen:** 2026-08-14, before implementation  
**Branch:** `study/Codex_structural_regime_geometry_maturity`  
**Type:** causal feature feasibility study; no policy, stop, exit, or hyperparameter optimisation.

## 1. Decision to inform

Decide whether a compact structural-regime geometry family should enter the next
survival-conditioned flip-model research iteration.  The study does not authorise a
new production model or a trading-rule change.

## 2. Hypothesis

Within a fixed 1m-regime maturity bucket, structural expansion, retained expansion,
prior 1m geometry, and fully-completed 5m geometry improve identification of an
imminent prevailing 1m flip.  Classification improvement and economic-path
improvement are distinct outcomes; either may be absent.

## 3. Frozen scope

| Item | Contract |
|---|---|
| Instrument / session | NQ.XCME, RTH `[08:30,15:00)` America/Chicago |
| Train | 2021-01-01 through 2023-12-31 |
| OOS evaluation | 2024-01-01 through 2024-12-31 only |
| Explicitly unused | 2025 |
| Sealed | 2026; no path, feature, label, model, threshold, or report input may read it |
| Base populations | Existing accepted, feature-complete, established RTH checkpoints: bullish prevailing regime / SHORT model and bearish prevailing regime / LONG model |
| Target | Existing direction-specific prevailing 1m-regime flip in `(T, T+300s]`; right-censored labels are excluded |
| Model | Two direction-specific `HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)` models, never a pooled model |
| Baseline A | Exact accepted ordered Top-25 feature list for the matching direction |
| Enriched B | Exact A plus this SPEC's structural family, with no feature selection on 2024 |
| First crossings | Separate directional P90 / P95 / P97.5 score thresholds fit only to the respective 2021-2023 TRAIN scores (`numpy.quantile(method="linear")`, membership `>=`) |
| Primary maturity buckets | `[300,600)`, `[600,900)`, `[900,1800)` seconds from current 1m-regime start |
| Separate extrapolation bucket | `[1800,∞)`; never mixed with the primary buckets |

The accepted eligibility is verified before collection against
`BULLISH_STRICT_top25_gbt_v2` and `LONG_STRICT_top25_gbt_v2`: strict age `>120s`,
`running_mfe_atr >= 1`, `new_progress_windows >= 2`,
`retained_mfe_ratio >= .5`, ATR anchored at confirmed 1m-regime start, and 5s cadence.
Any discrepancy aborts rather than being repaired here.

## 4. Structural feature contract

### 4.1 Timing and source contract

New features are emitted in a NautilusTrader event-loop collector at existing 5s
decision times.  At decision `T`: completed 1s state through `T` may be used;
completed 1m state must satisfy `close_ts < T`; completed 5m state must satisfy
`close_ts <= T`.  The equal-time order is completed 1s update, completed 5m update,
checkpoint snapshot, then the equal-time 1m regime update.  A current price is the
last completed 1s close.  No forming 5m bucket is readable.

The `TimeframeAggregator -> RegimeStateEngine -> CompletedBarRegistry` stack is the
accepted 5m definition.  The registry's `audit_provenance(T)` is called before each
snapshot.  Its immutable completed state, not an open bucket, is the only 5m input.

### 4.2 Current 1m structural origin and expansion

At every confirmed 1m flip, complete the former 1m regime first.  For the new
bullish regime freeze the prior completed bearish regime's actual low and timestamp;
for the new bearish regime freeze the prior completed bullish regime's actual high
and timestamp.  `structural_origin_price` and `structural_origin_ns` are immutable
for the new regime.  Regimes without such a completed predecessor (dataset warmup)
are unavailable and are excluded explicitly, never imputed.

The current regime maintains running 1s high/low only through `T`.  With `d=+1` for
bullish and `d=-1` for bearish, origin `O`, current close `C`, and the directionally
favourable running extreme `E`, primary features are:

```text
structural_max_expansion_atr     = d * (E - O) / atr_1m_start
structural_current_expansion_atr = d * (C - O) / atr_1m_start
structural_giveback_atr          = max_expansion - current_expansion
structural_retention_ratio       = current_expansion / max_expansion
structural_expansion_atr_per_min = max_expansion / ((T-origin_ns)/60)
regime_expansion_atr_per_min     = max_expansion / ((T-regime_start_ns)/60)
```

`atr_1m_start` is frozen when the current 1m regime is causally recognised.  A
non-positive ATR, non-positive elapsed clock, or non-positive maximum expansion
makes the affected field unavailable; values are never clamped or inf/nan-filled.
Checkpoint-ATR versions of maximum/current expansion are retained only as labelled
secondary diagnostics.

### 4.3 Prior completed 1m geometry

The same completed predecessor supplies immutable context, normalized by its own
frozen regime-start ATR:

```text
prior_1m_regime_duration_min
prior_1m_regime_range_atr                 = (high-low) / prior_atr_start
prior_1m_regime_net_directional_move_atr  = d_prior*(end_close-start_price)/prior_atr_start
prior_1m_regime_mfe_atr                   = d_prior*(favourable_extreme-start_price)/prior_atr_start
prior_1m_regime_range_atr_per_min
prior_1m_regime_net_move_atr_per_min
prior_1m_regime_efficiency                = abs(end_close-start_price)/(high-low)
```

Zero range or elapsed duration makes the ratio unavailable.  The prior regime is
complete before any one of these values can be snapped.

### 4.4 Completed 5m structural geometry

The 5m state is continuous across RTH and ETH for warmup, while snapshots remain
RTH-only.  A current 5m regime begins when a fully completed bucket causes the
accepted sticky EMA3/EMA9 5m engine to change state.  Its `atr_5m_start` is frozen
at that causal start.  Its high, low, range, directional displacement, and age use
only completed 5m buckets available by `T`.

Primary 5m fields are current 5m age, range / directional displacement / range-rate
in frozen-start-ATR terms; the same duration, range, displacement and range-rate for
the immediately prior completed 5m regime; and:

```text
distance_to_completed_5m_high_atr = (current_5m_completed_high - current_price) / atr_5m_start
distance_to_completed_5m_low_atr  = (current_price - current_5m_completed_low) / atr_5m_start
current_1m_move_outside_completed_5m_range = current_price > completed_high
                                              OR current_price < completed_low
```

`completed_high` / `completed_low` mean the running high/low of the **current active
5m regime using only fully completed 5m bars available by T**.  The forming bucket
is strictly excluded.  The immediately prior completed 5m high/low/range are kept
only as separate prior-regime context fields.  Checkpoint-ATR versions are secondary
diagnostics only.

### 4.5 Labels and analysis conventions

Future prevailing flip, accepted opposite confirmation, MAE, return at confirmation,
and eventual opposite MFE are labels or evaluation quantities only.  Economic labels
reuse the accepted Walk-A convention exactly: checkpoint reference analytical entry,
1 ATR stop evaluated on 1s high/low, adverse same-bar tie resolution, accepted
opposite-confirmation definition, and accepted unconstrained eventual-MFE definition.
They are explicitly analytical diagnostics, not executable-fill claims.

## 5. Evaluation contract

For every model set (A/B), direction (SHORT/LONG), pooled direction-labelled summary,
and maturity bucket, report row-level 2024 OOS AUC.  Pooled values concatenate only
the two direction-specific OOS score rows; no pooled classifier exists.

Within regimes with at least two eligible checkpoints and an observable terminal
flip, report: Spearman correlation of within-regime score percentile with negative
seconds-to-flip, median seconds-to-flip at the top-scored checkpoint, and mean score
percentile of the final eligible pre-flip checkpoint.  These are evaluation labels;
they never enter features, fitting, thresholds, or crossings.

For P90/P95/P97.5 TRAIN-derived score thresholds, arm at most once per regime per
threshold and model: first crossing from below within that regime and maturity
bucket.  On OOS crossing arms report `P(flip<=300s)`, confirmation-before-stop,
confirmation time, MAE, return at confirmation, eventual MFE, and `P(MFE>=1/2/3)`.
Also emit row-level OOS score-decile diagnostics, using decile edges derived on TRAIN
only.  All labels retain their existing censoring and denominator conventions.

Family attribution, conditional on enriched-model improvement, is 2024 OOS
permutation importance and five predeclared enriched-model family ablations:
`expansion`, `retention_giveback`, `speed`, `prior_1m_geometry`, `geometry_5m`.
No importance result is feature selection.

## 6. Deliverables Manifest

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/phase0_contract.json` | json | accepted eligibility, target, Top-25 source hashes, and observed reconciliation |
| 2 | `results/structural_checkpoints.parquet` | table | 2021-2024 causal feature rows; decision key, regime keys, base feature columns, all named structural fields, null/unavailable reasons, 1m/5m provenance timestamps |
| 3 | `results/collection_manifest.json` | json | partition coverage, attrition including missing prior anchors, source/code hashes, no-2026 assertion |
| 4 | `results/models_manifest.json` | json | direction-specific feature order, TRAIN-only fit facts, thresholds/deciles, hashes |
| 5 | `results/oos_row_metrics.csv` | table | `model_set,direction,maturity_bucket,n,positives,roc_auc` |
| 6 | `results/oos_timing_metrics.csv` | table | `model_set,direction,maturity_bucket,n_regimes,spearman_score_pct_vs_neg_secs_to_flip,median_top_score_secs_to_flip,mean_final_preflip_score_pct` |
| 7 | `results/oos_deciles.csv` | table | train-defined deciles and 2024 target/economic outcome diagnostics |
| 8 | `results/oos_first_crossings.parquet` | table | one OOS arm per regime/model/threshold; causal scores/features plus Walk-A labels |
| 9 | `results/oos_crossing_metrics.csv` | table | requested threshold, discrimination, confirmation, MAE, return, MFE metrics by model/direction/maturity |
| 10 | `results/oos_family_attribution.csv` | table | OOS permutation and declared family ablations, or explicit `NOT_RUN_NO_ENRICHED_IMPROVEMENT` rows |
| 11 | `results/validation_report.json` | json | every deterministic contract and denominator gate |
| 12 | `results/summary.json` | json | terminal label, primary comparisons, attrition, sealed-data assertion |
| 13 | `REPORT.md` | report | compact A/B maturity tables, interpretation S1-S5, limitations |
| 14 | `audit/lint.json`, `audit/pass_NN.md`, `audit/status.json` | audit | lint and causal-audit status |
| 15 | `audit/contract_pass_NN.md`, `audit/contract_status.json` | audit | deliverables-contract status |

### Terminal labels

| Label | Condition |
|---|---|
| `S1_STRUCTURAL_GEOMETRY_ADDS_REAL_INFORMATION` | B improves OOS discrimination or timing in at least two primary buckets and is not economically worse at P90 crossings |
| `S2_YOUNGER_REGIMES_SPECIFICALLY` | S1 criterion is concentrated in `[300,600)` |
| `S3_CLASSIFICATION_ONLY` | B improves discrimination/timing but not confirmation or eventual-MFE quality |
| `S4_ECONOMIC_TAIL_ONLY` | B improves crossing economics without material AUC improvement |
| `S5_NO_MATERIAL_INCREMENTAL_INFORMATION` | none of S1-S4 conditions holds |
| `ABORT_CONTRACT_OR_CAUSAL_FAILURE` | any frozen contract, coverage, lint, or audit blocker fails |

## 7. Domain and completeness contract

Collection partitions are calendar months in UTC, `[month_start, next_month_start)`,
with four days of warmup but output rows retained only for 2021-01 through 2024-12.
The expected grid is 48 output months.  Each observed 5s RTH score-row key is joined
exactly to one structural snapshot; duplicate/missing keys fail.  A zero-row month
is retained in the manifest and fails only if the accepted base surface contains
eligible rows.  Missing 5s dispatches are never filled.  A regime may not straddle a
train/OOS fit boundary: model membership is determined by checkpoint calendar year.

## 8. Stop conditions

Abort before fitting if eligibility reconciliation fails, any 2026 access is
observed, any structural feature reads a 5m `close_ts > T`, a frozen origin mutates,
the 5m parity/boundary tests fail, the exact checkpoint join is incomplete, a primary
maturity bucket has no positive OOS labels for either direction, or a required
deliverable cannot be produced.

## 9. Audit plan

Run `python scripts/causal_lint.py --study studies/Codex_structural_regime_geometry_maturity --json studies/Codex_structural_regime_geometry_maturity/audit/lint.json` before the completion audit.  The causal audit must specifically inspect frozen prior-regime origins, current 1m running extrema, 1m/5m frozen ATRs, forming-5m exclusion, coincident 1s/1m/5m ordering, train-only preprocessing and thresholds, label isolation, and 2026 sealing.  The contract audit verifies this manifest and terminal labels.  Completion requires both machine-readable statuses to show zero critical findings and no unadjudicated warnings.
