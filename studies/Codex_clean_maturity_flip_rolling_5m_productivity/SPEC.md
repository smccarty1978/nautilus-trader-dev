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

Report A/B/C separately by SHORT, LONG, pooled direction-labelled diagnostic, and
300-600s, 600-900s, 900-1800s; >=1800s is descriptive only. Freeze directional
P90/P95/P97.5 thresholds and deciles from TRAIN only. OOS reports AUC, PR AUC/Brier
where available, within-regime timing, first-crossing confirmation/MAE/return/MFE,
and decile economics. Pooled rows never determine terminal classification.

## Outcome labels

R1 broad clean improvement; R2 young-regime improvement; R3 timing only; R4 economic
tail only; R5 rolling block adds nothing; R6 no clean incremental information; ABORT
for any selection, causal, coverage, audit, or seal failure.

## Deliverables and gates

Required: candidate-universe manifest, frozen source manifests, collection/feature
manifests, model/score/crossing/decile artifacts, validation, summary, report, seal,
promotion gate, causal and contract audits. The report must state that the baseline
universe was rebuilt independently because the predecessor's F3 universe was
post-2024 selected. Run lint and split causal/contract pre-execution audits before
candidate collection, feature freezing, or fitting; completion requires both clear.
