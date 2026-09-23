# Post-entry path mechanism — 2023 development sessions

**Verdict by the frozen rule: `EARLY_POST_ENTRY_INFORMATION`.**

**Qualification:** the only early information is **price location**, i.e. how far the trade has already moved
from the original entry. It behaves like distance to the two barriers (+2A above, the terminal 1m flip
below). Nothing else observable — MTF state, path shape, or how the level was reached — adds to it.

**Scope.** The final 20% of 2023 was never loaded (bars or rows). 2024, 2025 and 2026 were not touched. No
model of any kind was fitted.

## Direct answers

**1. When does +2A-vs-failure information first become observable?**
At **+30 s**. Among still-alive trades below +1A, current P&L gives AUC 0.603 [0.589, 0.617]. By +60 s,
four price variables pass the frozen threshold, with current P&L the strongest at 0.632 [0.617, 0.646]. It
peaks at about 0.66 at +120 s.

At T0 there is nothing: the best variable is 0.503.

**2. How much favourable excursion has already happened by then?**
- **At +30 s:** eventual runners have a median MFE of **0.35A**, against 0.23A for failures. 34% are already
  at ≥ +0.5A and 9% at ≥ +1A.
- **At +60 s:** median MFE is **0.57A** against 0.32A. 55% are at ≥ +0.5A and 22% at ≥ +1A.

The information is the move beginning.

**3. Does the 5m transition lead favourable development or follow it?**
**It follows.**
- Among trades whose 5m turned their way, the turn came **before +0.5A in only 2.8%**. It came after +1A in
  91%, and after +2A in 64%.
- Of the +2A trades that started with a misaligned 5m, the 5m aligned before +0.5A in 1.4% and after +2A in
  53%. It never aligned before the terminal flip in 27%.
- 15m and 1h are later still.
- MTF alignment has no separating power at any checkpoint or first touch (AUC 0.48–0.52).

**4. Can sustained +2A winners be told apart from +2A givebacks before +2A?**
**No.**
- The only signal is **speed**: givebacks get there faster. It builds from AUC 0.53 at the +0.5A touch to
  0.59 at +1.5A. It passes the threshold only **at the +2A touch** (0.632 [0.598, 0.663]); givebacks reach +2A
  at a median 265 s against 390 s.
- One late exception: trades still below +2A at +285 s that took more heat give back more (MAE AUC 0.39).
- Neither MTF alignment nor prior adverse excursion separates them.

**5. Is the information T0 structure, early price path, MTF transition, or late confirmation?**
**Early price path, and specifically location.** It is not T0 structure (null, consistent with both prior ML
studies) and not MTF transition, which follows the move. The event-anchored test settles what kind of path
information it is: **given the level already touched, nothing else observed at that moment separates the
continuation.** Every tested variable scores AUC 0.46–0.51. P(+2A) rises only with the level reached: 49% at
+0.5A, 63% at +1A, 80% at +1.5A.

**6. Is there enough early causal information to justify a later POST-ENTRY ML study?**
**Not as an ML study yet.** The early signal is one-dimensional: current location, plus elapsed time and
survival. It can be tabulated exactly without a model. The event-anchored results show the other observables
add nothing to it.

An ML study would be justified only if it is framed as **"does anything beat location?"** That means:
- a frozen location-only baseline;
- a **matched driftless-path placebo**, to show the location → continuation curve differs from what a
  random walk between the same barriers produces.

The placebo is the first thing to build. If the empirical curve equals the placebo curve, there is no
mechanism to model.

**7. The smallest causal checkpoint surface worth freezing for that study.**
At one predeclared checkpoint (**+60 s** is the earliest point where the frozen threshold is crossed with
only 22% of runners at ≥ +1A):
- `cur` (current P&L from the original entry, in A);
- `mfe`;
- `mae`;
- the implicit alive / not-yet-flipped status;
- elapsed time, fixed by the checkpoint.

That is 3 variables plus the survival condition. MTF alignment and path-shape flags should enter only as
**increments tested against this baseline**; on this evidence they add nothing.

## Evidence base

- **Timeline parity (`artifacts/TRADE_PATH_TIMELINE_AUDIT.json`):** 0 mismatches.
  - 6,024 trades × 7 first-touch levels, with every first-touch second matching the audited kernel
    resolution seconds, from raw 1s bars using `atr_entry_1m`.
  - Entry prices and times match.
  - Chain-derived 5m/15m/1h direction matches about 103k audited checkpoint rows.
  - Labels match the prior audited +2A/+3A/−0.5A/−1A/win/F5 labels.
- **Frozen plan:** groups, checkpoints, variables, subsets, effect-size rule and decision rule were committed
  at `91c3d2e3` before any comparison was computed.
- **Adverse excursion was handled jointly, not as "winners also took heat":**
  - Runners have lower MAE at every checkpoint (median 0.32 vs 0.49 at +60 s), and MAE is part of the same
    location signal.
  - The "favourable expands while adverse stalls" flags carry little separate information (AUC ≤ 0.58).
  - Prior adverse excursion at a first touch does not matter (AUC 0.47–0.50).
- **Old buckets:** not used and not shown.

## Missing primitives (not constructed retrospectively)

- **No checkpoints after +285 s.** The collector's maximum age is 300 s. Clock-time state after that is
  covered only through the first-touch anchors.
- **Structural state after T0 is not used.** 32% of trades have gaps in the collector's checkpoint rows.

## Files

| file | content |
|---|---|
| `artifacts/TRADE_PATH_TIMELINE_AUDIT.json` | event definitions, timing semantics, parity |
| `MTF_TRANSITION_TIMING.md` | 5m/15m/1h ordering against favourable excursion |
| `CHECKPOINT_PATH_SEPARATION.md` | information-emergence table |
| `EVENT_ANCHORED_CONTINUATION.md` | state at +0.5A / +1A / +1.5A / +2A first touches |
| `PLUS2_GIVEBACK_ANALYSIS.md` | sustained vs giveback |
| `INITIAL_STATE_MAP.md` | 13 supported states, long/short |
| `PATH_MECHANISM_VERDICT.json` | verdict |

Tables in `artifacts/`: `TRADE_EVENT_TIMELINE`, `CHECKPOINT_STATE`, `EVENT_ANCHORED_STATE`,
`GROUP_COMPARISONS_CHECKPOINT`, `GROUP_COMPARISONS_EVENT`, `INFORMATION_EMERGENCE`, `MTF_TIMING`,
`INITIAL_STATE_MAP`, `EVENT_BASE_RATES`.

No delayed entry, exit rule or model is recommended.

```
EARLY_POST_ENTRY_INFORMATION
```
