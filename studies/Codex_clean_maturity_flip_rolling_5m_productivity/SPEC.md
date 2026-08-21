# Clean Maturity-Conditioned Flip Model with Rolling 5m Productivity

**Study:** `Codex_clean_maturity_flip_rolling_5m_productivity`  
**Status:** frozen design, pre-implementation  
**Branch:** `study/Codex_clean_maturity_flip_rolling_5m_productivity`

## Decision

Determine whether clean train-only baseline features plus causal structural geometry
and rolling five-minute productivity improve imminent prevailing-1m-flip prediction
within fixed maturity buckets, without degrading opposite-direction diagnostic
economics. This is not an entry, exit, or deployment study.

## Split and lineage

TRAIN is 2021-2023; 2024 is untouched OOS; 2025 is unused; 2026 is sealed.
The prior structural-geometry A/B result is exploratory only and contributes no
feature list, threshold, selection, conclusion, or acceptance evidence.

Baseline candidates are collected from the versioned `FEATURE_REGISTRY` verified
numeric universe through the NT event loop. The candidate-universe manifest must
list every feature definition/version, registry hash, collection code hash, and
prove no prior F3/2025-selected projection is read. A direction-specific Top-25 is
selected and frozen from 2021-2023 only before any 2024 score is read.

## Population and target

RTH NQ.XCME checkpoints at exact 5s cadence satisfying the accepted established
regime gate: age >120s, running MFE ATR >=1, progress windows >=2, retained MFE
ratio >=.5. Directions remain separate: bullish prevailing regime -> SHORT and
bearish prevailing regime -> LONG. The only fit target is a prevailing 1m flip in
`(T,T+300s]`; confirmation, stop, return, and MFE remain evaluation labels.

## Feature blocks

Model A is the frozen direction-specific clean Top-25. Model B adds the previously
audited causal structural family, including prior-regime semantics and completed-5m
geometry. Model C additionally adds the frozen rolling-productivity block.

At checkpoint T, rolling-productivity uses completed 1s state only in `[T-300s,T]`.
Its bullish anchor is the exact causal low at T-300s; its bearish anchor is the exact
causal high at T-300s. No boundary search is allowed. It emits max/current progress,
giveback, retention, max/current speed, and each speed relative to lifetime regime
expansion speed, normalized primarily by current-regime-start 1m ATR. Zero/invalid
denominators emit unavailable values, never clamps. Forming 5m bars remain excluded.

## Evaluation

Report the exact 18 directional model cells (A/B/C × SHORT/LONG × the three
primary maturity buckets) and the separate nine pooled direction-labelled
diagnostic rows (A/B/C × bucket). Pooled rows never enter terminal
classification. >=1800s is descriptive only. Freeze directional
P90/P95/P97.5 thresholds and deciles from TRAIN only. OOS reports AUC, PR AUC/Brier
where available, within-regime timing, first-crossing confirmation/MAE/return/MFE,
and decile economics. Pooled rows never determine terminal classification.

## Outcome labels

R1 broad clean improvement; R2 young-regime improvement; R3 timing only; R4 economic
tail only; R5 rolling block adds nothing; R6 no clean incremental information; ABORT
for any selection, causal, coverage, audit, or seal failure. Directional evidence
alone determines the terminal label; pooled rows are descriptive only.

## Deliverables and gates

Run lint and split causal/contract pre-execution audits before candidate
collection, feature freezing, or fitting; completion requires both clear.

## Deliverables Manifest

All paths below are relative to this study directory. Generated row data remains
untracked; manifests, reports, audit artifacts, and the frozen contract are
versioned.

| Path | Required contents / exact checks |
|---|---|
| `artifacts/phase0_source_manifest.json` | Authenticated `study.yaml` and `SPEC.md` hashes; registry and engine hashes; ordered verified numeric candidate inventory with definitions, implementation hashes, and test paths; explicit proof that F3 scored tables, 2024+ labels, 2025, and 2026 were not read. Must be created before collection, selection, or fit. |
| `artifacts/collection_manifest.json` | NT event-loop collector/config/data hashes; partitions restricted to 2021–2024; row counts and SHA-256 for each feature and runtime-regime partition; warmup/readiness, RTH, exact-5s, completed-1s, and completed-5m provenance checks. |
| `artifacts/frozen_feature_manifest.json` | One ordered 25-feature baseline list per SHORT/LONG direction; Train-only row/positive counts, temporal folds, candidate inventory hash, ranking method, feature-list hash, imputer fit hash, and explicit `2024_not_read_before_freeze: true`. |
| `artifacts/model_manifest.json` | A/B/C model feature blocks, fixed HistGradientBoosting parameters, direction, TRAIN dates, model hashes, and hashes of the frozen feature and preprocessing artifacts. No fit may run without a matching authenticated phase-zero manifest. |
| `artifacts/score_manifest.json` | 2024-only score partitions; score/model/source hashes; the exact 18 directional cells (A/B/C × SHORT/LONG × 300-600s/600-900s/900-1800s) and nine descriptive pooled rows. Each directional row contains N, positives, ROC AUC, PR AUC, Brier, and timing metrics. |
| `artifacts/crossing_manifest.json` | TRAIN-derived P90/P95/P97.5 thresholds and deciles for every model/direction/bucket; 2024 first-crossing rows with one arm per regime and Walk-A confirmation/MAE/return/eventual-MFE diagnostics. |
| `artifacts/decile_manifest.json` | 2024 OOS directional model/bucket/decile rows with flip rate, confirmation rate, return at confirmation, MAE, eventual opposite MFE, and P(MFE >=3 ATR). |
| `artifacts/validation.json` | Fail-closed checks for source authenticity, 2021–2023 selection/training, 2024-only scoring, no 2025/2026 access, availability timestamps, exact target interval, directional 18-cell completeness, pooled 9-row completeness, nonempty primary-cell denominators, and every required artifact/hash. |
| `artifacts/result_seal.json` | SHA-256 bindings for phase-zero, collection, frozen features, preprocessing, models, scores, crossings, deciles, validation, summary, and report. Missing or changed inputs invalidate the seal. |
| `artifacts/promotion_gate.json` | `PASS` only if both audit status files have zero critical/blocking findings, validation passes, result seal verifies, all primary directional cells are complete, and the terminal label is not ABORT. It records the directional-only evidence used for the label and never permits pooled rows to decide it. |
| `STUDY_REPORT.md` | The final R1–R6/ABORT label, direction-by-bucket A/B/C results, timing/crossing/decile/economic diagnostics, family attribution, limitations, all manifest locations/hashes, and an explicit statement that the old F3-selected study remains exploratory only. |
| `audit/pass_*.md`, `audit/status.json`, `audit/contract_pass_*.md`, `audit/contract_status.json` | Immutable causal and contract audit verdicts. Any nonzero critical/blocking result stops execution or promotion. |

The only canonical terminal labels are R1, R2, R3, R4, R5, R6, and ABORT as
defined above. The promotion gate must prove every label is reachable and must
fail closed when material evidence is absent. Pooled direction-labelled rows are
descriptive diagnostics only and cannot influence classification or promotion.
