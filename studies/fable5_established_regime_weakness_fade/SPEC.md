# Established Regime Weakness Fade — Fable 5

Narrow follow-up to `studies/fable5_pre_flip_d10_reversal_entry/` (kept fully
separate). Question: do regimes that exit profitably at the opposite flip
have a causal "real trend" signature, and can the frozen W4 weakness model
identify their terminal phase early enough to fade the prevailing regime
profitably?

Structural context from the prior study: unfiltered D10-entry fades
(P1 @ 1.5 ATR ≈ this study's Stage-2 mechanics without the filter) lost
~$15-22/tr net and lost to matched placebos. Stage 2 here only proceeds if
Stage 1 shows the winner cohort is causally distinguishable.

## Chronology (hard)

- Discovery / descriptive characterization: **2021-2024 only**.
- Validation / filter sanity-check: 2025.
- Untouched test: 2026. No 2026 metric may alter filter, trigger, stop or
  exit.

## Reused frozen inputs (read-only)

- W4 model + D10 threshold (0.618328) from
  `studies/fable5_pre_flip_d10_reversal_entry/_work/` (refit on 2021-2024,
  threshold = P90 of Jan-Feb 2025 val scores; frozen 2026-07-11).
- Causal 2025/2026 score stream (`causal_scores.parquet`) from the same
  study; 2021-2024 checkpoints are scored here with the same frozen model.
- Regime engine: exact upstream `reproduce_regimes.RegimeEngine` port,
  fresh per year (atlas-matching), regimes = flip close_ts intervals.
- NT fill semantics as fixture-verified in the prior study (market FOK fills
  at decision boundary vs just-completed 1s close; stop-market fills at
  trigger, gap-through repriced to fill-bar open in analysis; stop wins
  same-bar races).

## Disclosures

- 2021-2024 W4 scores are **in-sample** (W4 was trained on those
  checkpoints). Stage-1 W4-trajectory contrasts on train years are
  therefore upper bounds; 2025 serves as the out-of-sample sanity check
  before any 2026 exposure.
- Checkpoint cadence is 30 s in 2021-2024, 5 s in 2025/2026 (upstream
  atlas). Scoring stops at regime age 1800 s — regimes older than 30 min
  have no W4 coverage in their later phase. Score-availability is reported
  per cohort; this is a structural constraint on any weakness-fade of long
  "established" regimes.
- Regimes censored at year end (no final flip) are excluded and counted.

## Stage 1 — definitions

Per completed regime (metrics from 1s bars, ATR = engine ATR at start flip;
executable prices = last 1s close before the flip boundary, the P0/NT
convention):

- `flip_pnl_atr` = dir x (end_exec - start_exec) / ATR (gross).
- `peak_mfe_atr` = max favorable excursion from start_exec (highs/lows).
- `t_to_0p5`, `t_to_1p0` = seconds from regime start to first touch of
  +0.5 / +1.0 ATR MFE.
- `t_peak_to_flip` = seconds from (first) peak-MFE bar to regime end.
- `giveback_atr` = peak_mfe_atr - flip_pnl_atr;
  `retained_ratio` = flip_pnl_atr / peak_mfe_atr (peak > 0).
- `new_progress_windows` = count of clusters of new-favorable-extreme
  events, clusters separated by >= 120 s without a new extreme.
- W4 score "at time X" = last checkpoint with observation_time + 1s <= X
  inside the regime (descriptive; availability rate reported). X in
  {trend qualification = first touch of +1.0 ATR MFE, peak MFE,
  end-60 s, end-30 s, end}.

Cohorts: (1) all; (2) flip >= +0.5; (3) flip >= +1.0; (4) flip < 0;
(5) 0 <= flip < 0.5; (6) peak >= 1.0 & flip < +0.5; (7) peak >= 1.0 &
flip >= +0.5 (real-trend winners); (8) peak < 1.0. Key contrast: 7 vs 6.
Splits: direction, RTH/ETH (regime start, 08:30-15:00 CT). Splits reported
once, not exploded.

### Predeclared Stage-1 gate

The key cohort-7 versus cohort-6 contrast must pass in both 2021-2024 and
2025. Before any Stage-1 result is generated, the gate is frozen as:

- at least 3 of 4 structural conditions: duration median ratio >= 1.25,
  peak-MFE median ratio >= 1.25, median new-progress-window difference >= 1,
  and retained-MFE-ratio difference at flip-minus-60s >= 0.15;
- winner sample >= 500 in discovery and >= 100 in 2025;
- at least 250 paired W4 observations in discovery and 50 in 2025;
- winner median paired within-regime W4 rise from flip-minus-60s to flip >= 0.05, median
  peak-to-flip time >= 30s, and median giveback >= 0.25 ATR.

Failure of either chronological split produces
`NO_CLEAR_ESTABLISHED_REGIME_FILTER` and Stage 2 is not run.

Stage 1 does not score, characterize, summarize, or otherwise inspect 2026.
For an "at time X" W4 summary, the last causally available score must also
be no older than one native checkpoint interval (30s in 2021-2024; 5s in
2025); otherwise it is unavailable rather than carried forward from the
1,800s scoring cap.

## Stage 2 (Stage 1 passed) — single frozen policy

- Filter (frozen before Stage-2 monetization and before 2026):
  regime_age >= 120s, running_mfe_atr >= 1.0, new_progress_windows >= 2,
  retained_mfe_ratio >= 0.50 — all computable causally bar-by-bar.
- Trigger: first causal crossing of the frozen W4 threshold (0.618328)
  occurring while the filter is true. One trigger, no alternatives tested.
- Entry: fade prevailing regime at the explicit next available 1-second bar
  open after score availability (`observation_time + 1s`). This uses the
  previously authorized `EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT`; it is a
  1-second OHLC research simulation, not NT-native executable validation.
- Stop: 1.5 ATR from entry fill (ATR at trigger checkpoint), resting GTC
  stop-market, active whole trade.
- Exit: hold through the first flip aligned with the trade; exit at the
  next flip against the countertrade. Optional second variant (reported
  separately, not mixed): exit on the confirmed regime's first W4
  threshold crossing. Data-end positions censored.
- Costs: $5 RT commission + 1 tick RT slippage ($10/RT); net is decisive.
- Evaluation: causal sequential 1-second OHLC replay. The stop is active on
  the entry bar after the explicit open. A stop touch fills at the trigger;
  a gap through fills at the bar open. A scheduled flip exit fills at its
  boundary open before that bar's intrabar range. 2025 runs first; 2026 is
  opened only after the exact policy file and code pass pre-execution audit.

## Decisions

Stage 1: `ESTABLISHED_REGIME_FILTER_FOUND` or
`NO_CLEAR_ESTABLISHED_REGIME_FILTER` (stop).
Stage 2: `NO_MONETIZABLE_WEAKNESS_FADE`, `PROMISING_NEEDS_FULL_VALIDATION`,
or `ADVANCES_TO_EXECUTION_VALIDATION`. Not deployable in any case.
