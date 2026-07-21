# Pre-Flip D10 Reversal Entry Study — Fable 5 implementation

Independent implementation of the "Pre-Flip D10 Reversal Entry" specification
(Codex implementation prompt, 2026-07-11). A sibling implementation lives at
`studies/pre_flip_d10_reversal_entry/` (Codex agent); this study shares NO code
or intermediate artifacts with it. All paths here are prefixed `fable5_` so the
two result sets can be compared.

The referenced source document `pre_flip_d10_reversal_investigation(1).md` is
not present in the repository; the implementation prompt supplied in chat is
the authoritative specification.

## Hypothesis

1. The first causal crossing of the current (old) regime's terminal-weakness
   score into its frozen top decile (D10) supports a profitable reversal entry
   *before* the formal 1m regime flip, protected only by a fixed ATR stop.
2. After the anticipated flip confirms the trade, the *new* regime's first D10
   event is a useful exit ahead of the opposite regime flip, with the opposite
   flip as the complete natural fallback for regimes that never reach D10.

## Frozen weakness score and D10 threshold

- Score: **W4** terminal-weakness model from
  `studies/regime_sequence_chop_context/` — HistGradientBoostingClassifier
  (max_iter=100, max_depth=5, learning_rate=0.05, random_state=42) on
  CENTER + SEQUENCE + LOCAL features (feature list read from
  `weakness_model_manifest.json`), target
  `(opp_flip_in_120s == 1) | (terminal_deterioration == 1)`.
- Refit in this study on `weakness_checkpoint_atlas.parquet` rows with
  `period == 'train'` (2021-01-01 .. 2024-12-31, 30 s checkpoint cadence),
  after `dropna(subset=['aligned_price_minus_center_5m'])` exactly as the
  upstream trainer does. Persisted to `_work/w4_fable5.pkl`.
- **D10 threshold: an absolute validation-frozen score threshold** — the 90th
  percentile of W4 predicted probabilities on `period == 'val'` checkpoints
  (2025-01-01 .. 2025-02-28, 5 s cadence). Persisted to
  `_work/frozen_threshold.json` with provenance (atlas SHA-256, row counts,
  feature list) **before** any 2025/2026 policy economics are computed.
  It is NOT a contemporaneous test-set rank; no 2025-Mar+ or 2026 data
  contributes to the threshold.

## Population, timing and causality conventions

- Regimes: EMA3/EMA9 sticky regime on 1m H/L/C with Wilder ATR(14)
  (`RegimeEngine`, ported exactly from
  `studies/regime_sequence_chop_context/reproduce_regimes.py`). A flip is
  known at the flip bar's CLOSE time (`close_ts`). Regime id =
  `(direction, start_close_ts)`. The engine is seeded fresh at Jan 1 of each
  processed year, matching the upstream atlas construction, so regime
  boundaries and checkpoint keys align with the atlas bit-for-bit.
- Checkpoints (2025/2026): every 5 s from `flip_ts + 5s` to
  `min(next_flip_ts, flip_ts + 1800s)`, inclusive. **Regimes older than
  1800 s have no score by construction** — this is inherited from the
  upstream atlas and is measured explicitly in the coverage report
  (`score_unavailable_reason = 'age_gt_1800s'` for the uncovered tail).
- **Score availability**: the checkpoint at `observation_time = T` is computed
  from 1s bars whose OPEN time is <= T. When a bar opens exactly at T the
  score becomes available at wall-clock **T + 1 s** (that bar's close). When
  T falls on a quiet second (no trade, hence no bar — common in ETH), the
  underlying data completed earlier but "no newer bar <= T" is only knowable
  at T itself; the first event-loop boundary at/after that is the close of
  the first 1s bar opening after T. Dispatch is therefore a sorted pointer
  sweep: while processing the bar with `ts_event = E`, every undispatched
  checkpoint with `obs <= E` fires (completion-audit fix — an exact
  `ts_event` lookup silently dropped ~40% of ETH checkpoints and skewed the
  placebo arm toward RTH).
- **Entry/exit fills** (micro-fixture verified, see
  `audit/fill_fixture_observations.json`): a decision made while processing
  the 1s bar closing at T+1 is submitted immediately as a 1-lot FOK market
  order, and NT bar execution fills it AT the decision boundary against the
  just-completed bar's CLOSE — the event loop's actual executable price at
  decision time (the last trade before the order could physically reach the
  market). Per the spec's own rule, the checkpoint close is used only
  because it IS "the actual next executable price under the event loop";
  the +1 tick round-trip slippage allowance covers the close-to-next-open
  microstructure gap.
- **Stop fills**: resting GTC stop-market orders fill at the trigger price
  on touch. The fixture shows NT fills at trigger EVEN when a bar gaps
  through it (optimistic); analysis conservatively reprices such fills to
  the fill bar's open and reports both raw and repriced economics
  (primary = repriced).
- **D10 crossing**: within one regime, the first checkpoint with
  `score >= threshold` where the previous *valid* score in the same regime was
  `< threshold`. If the first valid score of a regime is already
  `>= threshold`, it counts as the crossing (transition from the implicit
  no-score state). One crossing event per regime is actionable.
- A crossing whose `observation_time` equals the regime's end `close_ts` is
  **not** causally pre-flip (the flip is known at T+0, the score only at
  T+1s): it is excluded from entries and logged in the same-timestamp audit.

## Policies

All trades are 1 NQ contract on the XCME bar-execution venue (1s + 1m bars),
netting OMS. Costs: $5 round-trip commission + 1 NQ tick ($5) round-trip
slippage allowance, applied in analysis; gross and net both reported.

- **P0** — flip-to-flip baseline: enter the new regime direction at the first
  executable 1s open after each observed flip; exit at the next opposite flip
  (which is simultaneously the next trade's entry signal). No stop, no D10.
- **P1** — D10 pre-flip entry -> opposite-flip exit: enter opposite the old
  regime at its first D10 crossing; fixed ATR stop from the actual fill
  (0.50 / 1.00 / 1.50 ATR grid); before confirmation the stop is the ONLY
  exit; after the anticipated flip confirms, hold to the next flip opposite
  the trade direction. The original stop stays active for the whole trade.
- **P2** — flip entry -> D10-or-flip exit: enter as P0; exit at the first of
  (a) the entered regime's own first D10 event, (b) the next opposite flip.
  No stop (there is no project-standard universal catastrophic stop for
  flip-to-flip trades; disclosed here explicitly).
- **P3** — D10 pre-flip entry -> D10-or-flip exit: enter as P1 with the same
  stop grid; before confirmation only the stop may exit; after confirmation,
  exit at the first of the confirmed regime's first D10 event or the next
  opposite flip. Stop stays active throughout.
- **P4A / P4B** — matched placebo entries (see below) run through exactly the
  P1 / P3 exit machinery and stop grid.

**One entry attempt per originating regime.** After a stop-out there is no
re-entry during the same regime. An entry signal arriving while a position is
open is consumed (skipped), not deferred: entries only happen at the first
crossing moment itself ("submit immediately"). An event that triggers an exit
is not simultaneously used as a new entry (no same-event reversal); this is
the conservative independent-trades reading of the spec and is documented as
an interpretation choice.

Open positions at data end are `data_end_censored`: excluded from
completed-trade economics, counted and reported.

## Exit priority and same-timestamp policy

Phase 1 (before anticipated flip): 1. stop-loss (resting GTC stop-market at
the venue — intrabar, event-loop handled). Phase 2 (after confirmation):
1. new-regime D10 exit if it occurs first; 2. opposite regime flip. The stop
remains resting the whole time; if the stop and a D10/flip exit could fill on
the same 1s bar, the resting stop participates in NT's intrabar tick
sequence (adaptive high/low ordering) and any FOK exit that arrives after the
position is already flat is rejected and logged — ties therefore resolve to
the stop (conservative). All same-timestamp D10/flip coincidences are written
to `audit/same_timestamp_exit_audit.parquet` with actual callback ordering.

D10-vs-flip observation ordering: a flip closing at time T is processed at
ts_init = T (1m bar), a D10 crossing observed at checkpoint T is processed at
ts_init = T + 1s (1s bar) — the flip state update always precedes a
same-nominal-timestamp D10 observation, so such crossings classify as
`opposite_regime_flip_exit` (spec primary policy) and never as pre-flip
entries.

## Matched placebo (P4)

For each real D10 entry event, a donor checkpoint is sampled from a different
regime of the same year matched on: direction (exact), session (RTH/ETH),
regime-age bucket, ATR bucket, current-MFE bucket, giveback bucket, and valid
weakness-score availability, with donor `score < threshold` (not itself a D10
crossing) and at most one placebo entry per donor regime. All matching
covariates are entry-time causal; nothing about the donor regime's future
enters the match. Placebo entries run through the identical NT strategy code
(same fill, stop, confirmation and exit mechanics), seeds fixed and recorded.

## Evaluation windows

- Threshold calibration: 2025-01-01 .. 2025-02-28 (excluded from economics).
- **2025 economics: 2025-03-01 .. 2025-12-30** (data end).
- **2026 economics: 2026-01-01 .. 2026-04-29** (data end).
- Engines are fed from Jan 1 of each year (fresh regime engine, matching the
  atlas); trading is gated to the economics window.

## Final evidence

Final policy economics come from the NautilusTrader BacktestEngine event loop
(1s bars, causal score lookup keyed as above, FOK market fills, resting GTC
stop-market orders). Offline analysis is used only for: forward diagnostics,
threshold/coverage reports, placebo generation, and policy design. The
regime/score parity between the offline stream and the NT runtime stream is
itself audited (`audit/score_regime_id_audit.parquet`).

## Directory

```
studies/fable5_pre_flip_d10_reversal_entry/
├── SPEC.md                  # this file
├── common.py                # paths, constants, shared helpers
├── freeze_model.py          # W4 refit + D10 threshold freeze (train/val only)
├── build_scores.py          # causal 5s score stream for 2025/2026
├── build_events.py          # regimes, D10 crossings, coverage, diagnostics
├── build_placebos.py        # matched placebo entries
├── strategy.py              # NT strategy implementing P0-P4
├── run_nt.py                # BacktestEngine runner (policy x stop x year)
├── test_fill_fixture.py     # NT fill/stop semantics micro-fixture
├── analyze.py               # results, decomposition, audits, final report
├── results/                 # required result parquets + final_report.md
├── audit/                   # required audit artifacts
└── _work/                   # frozen model, threshold, intermediates
```
