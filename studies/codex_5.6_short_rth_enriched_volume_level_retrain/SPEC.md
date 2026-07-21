# Enriched volume/level retrain

## Scope

Research-only retraining over immutable, precomputed NT-derived causal surfaces. This is not an NT validation or a reconstruction of labels, features, Policy-A fills, or exits.

## Population and split

Rows are short (`entry_direction=-1`), label-available rows from `full_2021.parquet` through `full_2026.parquet`. Training is 2021–2024; selection is exclusively 2025; evaluation is exclusively 2026 after the atomic 2025 seal validates.

## Features and models

F0 dynamically imports the ordered `CENTER_FEATS + SEQUENCE_FEATS` (149). F1 adds 214 verified `ohlcv_est_delta` registry features. The 247-entry price-level family contains two excluded identity strings and 29 categorical positions; F2 adds 216 numeric fields plus fixed four-way encoding of those 29 fields (481 total); F3 is 695. Provenance and level-name identity columns are excluded. The only models are fixed L2 logistic regression and fixed HistGradientBoosting, both with train-only median imputation.

## Labels and score

`original_opposing_flip_exit` is `winner` only when `net_pnl > 0`, otherwise `loser`; `preflip_policy_stop`, `confirmation_timeout_exit`, and `original_stop_after_aligned_flip` map to the other frozen classes. Unknown labels fail closed. Score is `P(winner)-P(pre_alignment_stop)-.25P(timeout)-.5P(poststop)` using explicit `classes_` lookup; `loser` is intentionally zero-weighted.

## Selection

Six inclusive quantile bands are tested for all eight models. Layer 2 keeps the first stable-sorted observation per regime. The 2025 winner is selected only by the frozen economic checks and tie-break rule, sealed atomically; stage 2 never reselects.

Stage 1 reads only the trusted 2025 baseline file. The seal commits to the expected hash of the separate stage-2 dependency without importing it. Stage 2 authenticates the seal and that dependency before it can read any 2026 baseline or surface.

## Audit

The foundation audit's two dormant warnings concern full unwindowed artifacts. Execution requires final foundation zero-CRITICAL status and local zero-CRITICAL/zero-WARNING audit status.

## Exact 2026 promotion gates

Baseline A is the hash-gated candidate/control trade table keyed by `regime_start_ns`, not an aggregate proxy. Kept, dropped, and added regimes are reported. Exact winner clipping must not exceed exact comparable pre-stop savings. Monthly CT checks require selected worst month no worse than 25% below Baseline A's worst month, selected positive-month share no more than 10pp below Baseline A, and no selected month above 75% of total gross absolute monthly PnL.
