# W4 Entry Threshold Morphology Diagnostic

Run a focused diagnostic on the repaired CODEX 5.X W4 established-regime fade entry signal.

Do **not** retrain W4. Do **not** change the policy yet. This is descriptive entry-quality analysis only.

## Goal

Understand whether winning W4 fade entries and losing/chop entries differ in how the W4 score approaches, crosses, persists above, or collapses around the frozen entry threshold.

Current entry logic is approximately:

```text id="r1whyk"
first strict W4 threshold crossing -> enter
```

The question is:

> Are all threshold crossings equivalent, or do winners have a distinct threshold-crossing shape?

---

## Population

Use the same repaired 4,383 W4 entry trades.

For every entry, reconstruct the W4 score path at 5-second checkpoints around the trigger.

Use windows:

* -120s to entry,
* -60s to entry,
* -30s to entry,
* -15s to entry,
* -10s,
* -5s,
* entry checkpoint,
* +5s,
* +10s,
* +15s,
* +30s,
* +60s,
* +120s.

Use the correct direction-specific threshold:

* prevailing long threshold,
* prevailing short threshold.

Normalize score as:

```text id="xe2xd0"
score_margin = W4_score - direction_specific_threshold
```

Also compute absolute W4 score and threshold separately.

---

## Outcome groups

Compare morphology by original baseline outcome and by current Policy A outcome if available.

Primary groups:

* quick-aligning planned winners: aligning flip within 5 minutes and final positive,
* late-aligning winners: aligning flip after 5 minutes and final positive,
* planned-exit losers,
* stop-before-aligning-flip trades,
* timeout exits under Policy A,
* stop-after-aligning-flip trades.

Also report by:

* 2025 vs 2026,
* long fade vs short fade,
* RTH vs ETH.

---

## Core morphology features

For each trade, compute:

### 1. Threshold persistence

* number of consecutive 5s checkpoints above threshold after first crossing,
* whether score remains above threshold at:

  * +5s,
  * +10s,
  * +15s,
  * +30s,
  * +60s,
* first time score falls back below threshold,
* total seconds above threshold in the first 60s after crossing.

Question:

> Do winners persist above threshold longer than losers?

### 2. Threshold spike / jump behavior

Compute score changes:

* delta_5s = score_margin at entry minus score_margin at -5s,
* delta_10s,
* delta_15s,
* delta_30s,
* delta_60s.

Also compute:

* pre-crossing score_margin at -5s, -10s, -15s, -30s,
* overshoot at crossing,
* crossing velocity,
* crossing acceleration.

Question:

> Do losers spike through threshold from much lower values, while winners approach more gradually?

### 3. Pre-crossing dwell near threshold

For the 60 seconds before crossing, compute:

* number of checkpoints within 0.05 of threshold,
* number of checkpoints within 0.10 of threshold,
* time spent just below threshold,
* whether the score was monotonically rising,
* number of sign changes in score delta.

Question:

> Do winners spend time building near threshold before crossing, while losers jump from lower-quality states?

### 4. Chop / threshold instability

For the 120 seconds before entry, compute:

* score standard deviation,
* score range,
* number of local extrema,
* number of near-threshold crosses,
* number of times score crossed above/below the threshold if prior crossings are available,
* whether this was a first clean crossing or part of threshold chop.

Question:

> Are losing entries associated with noisy score behavior around the threshold?

### 5. Immediate post-entry score confirmation

For +5s, +10s, +15s, +30s, and +60s:

* score_margin,
* score_delta from entry,
* whether score remains above threshold,
* whether score makes a new local high after entry.

Question:

> Does requiring one additional 5s confirmation after threshold crossing improve entry quality?

### 6. Immediate price confirmation

Using 1-second bars after entry, compute:

* PnL at +5s, +10s, +15s, +30s, +60s, +120s,
* MFE and MAE over first 30s, 60s, 120s,
* whether price immediately moves in the fade direction,
* whether price makes a new adverse extreme within 30s,
* whether entry is already underwater by 30s/60s.

Question:

> Can score morphology plus immediate price response separate quick winners from chop losers?

---

## Required descriptive outputs

For each outcome group, report:

* median score_margin path from -60s to +60s,
* p25/p75 score_margin bands,
* persistence-above-threshold distribution,
* crossing velocity distribution,
* overshoot distribution,
* post-crossing collapse rate,
* pre-crossing dwell statistics,
* immediate PnL path.

Include compact tables for:

1. quick winners vs stop-before losers,
2. quick winners vs timeout exits,
3. quick winners vs planned losers,
4. short fades vs long fades,
5. RTH vs ETH.

---

## Candidate simple gates to evaluate descriptively only

Do not optimize. Evaluate these as fixed descriptive filters first:

### Gate 1 — Persistence confirmation

```text id="di7edb"
Enter only if W4 score remains above threshold at +5s.
```

### Gate 2 — Two-check persistence

```text id="skfjhw"
Enter only if W4 score remains above threshold at +10s.
```

### Gate 3 — No spike-through entry

```text id="rcljzq"
Reject entry if score_margin moved from far below threshold to above threshold in one 5s step.
Example diagnostic condition:
delta_5s > unusually large threshold-crossing velocity.
```

Do not freeze the numeric spike threshold yet. Report distributions first.

### Gate 4 — Near-threshold build

```text id="cnrtaw"
Require at least one checkpoint within 0.10 score_margin of the threshold during the prior 30s before crossing.
```

### Gate 5 — Price response confirmation

```text id="k1jv80"
Enter only if trade is not materially adverse after +10s or +30s.
```

For each candidate gate, report only descriptive retained/removed counts and baseline outcomes:

* trades retained,
* trades removed,
* retained net PnL,
* removed net PnL,
* removed winners,
* removed stop-before losses,
* removed planned losers,
* 2025/2026 split,
* long/short split,
* RTH/ETH split.

Do **not** call these policy results yet unless they are replayed causally with delayed entry and correct fills.

---

## Important causality note

Any post-crossing confirmation gate changes the entry time.

For example:

```text id="d35u6p"
threshold crosses at t
confirmation at t+5s
entry must occur at the next available 1s open after t+5s
```

Therefore, descriptive retained/removed tables are not enough. If a gate looks promising, run a separate delayed-entry replay later.

This diagnostic should only identify whether there is a signal worth replaying.

---

## Final report should answer

1. Do quick winners persist above threshold longer than losers?
2. Do losers show one-checkpoint spike-through behavior?
3. Do winners build near threshold before crossing?
4. Does score collapse immediately after entry identify bad trades?
5. Does immediate price response separate winners from losers?
6. Which, if any, simple entry-confirmation gates deserve a proper causal replay?
7. Is the effect stable in 2025 and 2026, or is it one-year noise?

Final decision label:

* `NO_ENTRY_MORPHOLOGY_EDGE_VISIBLE`
* `PERSISTENCE_CONFIRMATION_PROMISING`
* `SPIKE_THROUGH_FILTER_PROMISING`
* `NEAR_THRESHOLD_BUILD_PROMISING`
* `PRICE_RESPONSE_CONFIRMATION_PROMISING`
* `ENTRY_MORPHOLOGY_REPLAY_NEEDED`
