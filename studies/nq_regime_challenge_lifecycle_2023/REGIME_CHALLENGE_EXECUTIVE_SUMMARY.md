# Regime challenge / internal lifecycle: executive summary

**VERDICT: WEAK_CHALLENGE_CONTEXT, race information only.**

**What was built.** The inside of every development regime was rebuilt the way the chart shows it:
- numbered challenges at 0.25–2.0A depth;
- impulse and challenge candles;
- the EMA3/EMA9 high/low band and the distance to the flip threshold;
- level memory inside and across regimes;
- 5m/15m/1h changes since the regime began;
- volume, session and raw-point context;
- clock and event response checkpoints out to 720 s.

Everything matched the audited artifacts with 0 mismatches.

**What the inside of a regime does contain.** Replicated, above-null information about whether the current challenge
is rejected (a new favourable extreme) or becomes the transition. It is worth 5–10pp beyond location at onset, and
10–15pp at the first 1m close through EMA3-low:

| raises the odds of a new extreme | lowers the odds of a new extreme |
|---|---|
| fast, heavy challenges | slow challenges |
| wicky challenge candles | long impulses |
| the opening drive | a long time since the last challenge |
| | a large previous recovery leg |
| | deeper price and more new lows at the EMA3 close-through |

All of these hold in both blocks, in both directions, trimmed, and at one episode per regime.

**What it does not contain: value.** The value of holding to the flip versus exiting at the challenge is ≈ 0 on average
at every depth (−0.02 to +0.05A). No challenge-internal feature moves it once robustness is checked. Challenges that
become new extremes more often give the gain back elsewhere, which is the same martingale found after entry, now at
challenge resolution. Every apparent value effect turned out to be regime-level context or 2023 drift:
- low ATR in points: long-only in block A, gone at one episode per regime;
- opening drive: + for longs, − for shorts;
- the 15m flipping during the regime: long-dominated, unstable;
- 1h alignment: already known;
- a degenerate spike-and-reverse bin at 2.0A.

**"Can internal regime evolution distinguish ordinary challenge from deterioration early enough to be economically
useful?"** It distinguishes them *somewhat*: which challenges get rejected is partly predictable. It is not
economically useful, because the expected value of holding through the predicted-bad challenges equals the value of
exiting them.

**"Is a challenge-level ML model justified?"** No. Model A (transition risk) would learn a real 5–15pp signal that
does not change the hold-or-exit decision in expectation. The representation is not the bottleneck either: the
deteriorating case's fatal challenge has a near-identical twin among clean-trend successes, and the two look alike
on the chart too.

## Answers to the 28 questions

| # | answer |
|---|---|
| 1 | A regime is a run of fast sub-candle wiggles (≈ 10 per regime at 0.25A, median resolution 11 s) with about 1–2 human-scale pullbacks (≥ 1A) and dies inside its last challenge (96.5–100% of regimes end in an open challenge episode). Response categories are slices of a continuum, and the next challenge's category does not depend on the previous one (rows equal within about 3pp) |
| 2 | Mean / median per regime: 0.5A 4.6 / 3; 1.0A 2.2 / 2; 1.5A 1.5 / 1; 2.0A 1.25 / 1 (69% of regimes ever see a 2A pullback) |
| 3 | New extreme before the flip: 0.25A 90%, 0.5A 78%, 1.0A 56%, 1.5A 36%, 2.0A 23% |
| 4 | Depth matters for the race almost entirely through location: P(new extreme) goes 65% → 91% across distance-to-flip deciles at 0.5A. Hold value ≈ 0 at every depth |
| 5 | Challenge number does not matter: later challenges succeed more only because survivors sit further from the flip (residual within ±1.2pp for n = 1…8+) |
| 6 | Maturity lowers the odds of a new extreme (accumulated MFE −5 to −10pp at checkpoints; long since the last challenge −7.7pp at 1.5A) but not the value |
| 7 | Impulse length (1m bars) lowers the odds at 2.0A (−9.7 / −9.5pp). Impulse efficiency, overlap and big-bar share carry nothing |
| 8 | Speed matters: slow 0.5A challenges −6.4 / −6.7pp, fast +4.9 / +6.6pp; wicky challenge candles at 1.0A +5.1 / +5.8pp. Value-neutral |
| 9 | Consecutive adverse candles add nothing beyond depth (within ±1.8pp at onset across 0.5–1.5A; not material at checkpoints except n ≈ 500 cells at +720 s) |
| 10 | Recovery behaviour adds about as much as challenge behaviour: mostly location, ≤ 6pp beyond it at clock checkpoints. The richest point is an *event*: the first 1m close through EMA3-low (10–15pp). No value either way |
| 11 | Failure to recover the prior extreme is largely location: an unresolved challenge at +300 s makes a new extreme 46% of the time; beyond location, residuals are ≤ 6pp and inconsistent between blocks |
| 12 | Declining progress across successive legs does not matter. DETERIORATING vs STRENGTHENING sequences have residuals within ±1.2pp. Only a *large* previous leg lowers the odds (−5.6pp at 1.5A), which reads as extension |
| 13 | Repeated tests of the same level do not matter (earlier challenge lows near the touch: ±1pp) |
| 14 | "Already tried and failed here" is no more informative inside the regime than across completed regimes (mostly ≤ 3pp, one cell +6.3pp in block B only; inconsistent signs) |
| 15 | EMA penetration is rare at shallow onsets (0.4% at 0.5A) and informative at the first close through EMA3-low: 32% new-extreme rate, plus a 10–15pp residual from depth and new lows. EMA3 recapture +6pp at 1.0A / +120 s. Value-neutral |
| 16 | Band compression/expansion: no effect (`band_w_chg5` within ±2.2pp, signs flip between blocks) |
| 17 | Volume: heavier challenges +4pp; volume response at the EMA3 close-through +10pp (0.5A). No value |
| 18 | Raw point measures looked like they carried value (low ATR → better hold) but it is 2023 drift: long-only in block A, gone at one episode per regime. No hidden information survives |
| 19 | Changing MTF context carries more than static labels: a 15m flip during the regime gives hold −0.42 / −0.57A, while static labels are flat. It is long-dominated and unstable, so a lead only |
| 20 | Only in hindsight: the fatal challenge follows a weaker impulse (efficiency 0.36 vs 0.45) and is slower (3.0 vs 3.75 A/min). Prospectively these are the 5–10pp race effects |
| 21 | No recognisable rejection sequences: a rejection does not predict the next rejection |
| 22 | Race information appears at onset (speed) and is largest at the first close through EMA3-low |
| 23 | About 1.6A of favourable movement remains on average at that point, but holding and exiting have equal expected value |
| 24 | Race effects replicate in both blocks (10/10 vetting splits). Value effects do not |
| 25 | Missing from the library: distance to the engine flip threshold and the EMA high/low band, a challenge-episode tracker with per-challenge history, HTF changes since regime start, and event-anchored checkpoints (FEATURE_COVERAGE_AUDIT.md) |
| 26 | No ML |
| 27 | None worth fitting now. If the race signal is ever wanted (e.g. for exit + re-entry mechanics), the smallest problem is P(new extreme before flip) for 1.0–1.5A challenges from `dist_flip`, challenge speed, candle wicks, impulse length and time since last challenge. It must be judged on hold value, not AUC, and this study says it will not move hold value |
| 28 | The chart itself is now represented. What remains unrepresented is off-chart (order flow, cross-market, news), and the near-twin check suggests the chart is not hiding a distinction the features miss |

## Integrity

- 2023 development sessions only (blocks 154 / 51). The final 20% and 2024+ were never loaded. 2022-12-20…31 1m bars
  were used only for engine warm-up.
- Parity with 0 mismatches (`artifacts/EXTRACT_AUDIT.json`): 6,024 flips, directions, ATRs, terminal flips, ledger
  ends, 5m/15m/1h direction + start at T0, flip-bar close, entry.
- Causal features only (REGIME_LIFECYCLE_DEFINITION.md, CHALLENGE_FEATURE_DEFINITIONS.md). Block-A bin edges apply
  to both blocks. Every contrast is reported raw and beyond a location baseline.
- Materiality was pre-declared and checked against a circular-shift null (20 rotations × 2 depths). Candidates were
  vetted by block × direction, trimmed, and at one episode per regime.
- Two defects were found and fixed during the run and are disclosed:
  - bootstrap CIs were first computed on raw rather than residual outcomes;
  - discrete features collapsed to one bin.
  All tables were regenerated after both fixes.

## Runtime by phase

| phase | wall time |
|---|---|
| 0: engine replay (293k 1m bars), ledger, HTF, parity, raw-1s lifecycle pass (4.67M bars) | 17.1 s |
| 1–4: challenge episodes at 6 depths (132k), onset context, outcomes, 401k response checkpoints | 128.2 s |
| 5–9: atlas (onset, strata, checkpoints, sequences), bootstraps | 27.5 s |
| null calibration (2 depths × 20 rotations) | 34.9 s |
| robustness vetting | 1.1 s |
| case studies + representation check | ≈ 6 s |
| **total compute** | **≈ 3.6 min** |

Session time went mostly to deciding definitions (the sub-candle nature of 0.5A challenges forced adding 1.5/2.0A)
and to the two fixes above.

**Reused:** the audited timeline, TEMPORAL_SPLIT, the audited merged frame (hash-checked), and the authoritative
`regime_dual_ema` tracker. Nothing was recollected.

**Reusable outputs:** `LIFECYCLE_1M`, `REGIME_LEDGER`, `LIFECYCLE_1S`, `CHALLENGE_EVENTS`, `CHALLENGE_CHECKPOINTS`
(`artifacts/`, rebuilt in about 2.5 min).

**What should become shared infrastructure** (FEATURE_COVERAGE_AUDIT.md §C):
1. the dual-EMA fields and `dist_flip_atr`;
2. a generic challenge-episode tracker;
3. a per-timeframe regime ledger including the collector-universe holes (84 in this development window);
4. event-anchored observation checkpoints;
5. HTF-change-since-parent-start fields.

Items 1–3 would have cut this study's code by about half.

## Deliverables

- `REGIME_LIFECYCLE_DEFINITION.md`
- `CHALLENGE_FEATURE_DEFINITIONS.md`
- `CHALLENGE_RESPONSE_ATLAS.md`
- `REPEATED_CHALLENGE_ANALYSIS.md`
- `FEATURE_COVERAGE_AUDIT.md`
- `DEVELOPMENT_REPLICATION.md`
- `REGIME_CHALLENGE_VERDICT.json`
- `artifacts/REGIME_LIFECYCLE_ATLAS.parquet`
- `artifacts/CHALLENGE_EVENTS.parquet`
- `artifacts/cases/` (five charts, event table, representation check)

Code: `extract.py`, `challenge.py`, `atlas.py`, `null_shift.py`, `vet.py`, `cases.py`.
