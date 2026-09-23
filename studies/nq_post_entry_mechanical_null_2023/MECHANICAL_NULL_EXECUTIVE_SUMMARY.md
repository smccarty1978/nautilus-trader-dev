# Post-entry path information vs mechanical nulls — 2023 development sessions

**Verdict by the frozen rule: `INCONCLUSIVE_MECHANICAL_BASELINE`.**

## Why the verdict is INCONCLUSIVE

It was triggered by **one clause only: power.** The 51-session replication block's minimum detectable tercile
effect is 0.11–0.14 at every anchor, and I froze a ≤ 0.10 requirement.

**Every substantive test came back on the mechanical side:**
- The fixed-price race matches the location-only line (x + 1) / 3 at every anchor, within ±1.5pp.
- No level residual passes.
- No predeclared primary path variable passes discovery-plus-replication, on any outcome.
- The raw speed effects on the terminal race and on giveback are mostly explained by the trailing geometry
  of the 1m flip trigger.

**One candidate is left:** a sharp 30 s run-up into +1.5A or +2A gives back more, even against the engine null.
It is located at or just before +2A, and in replication it shrank to about a third of its discovery size.

**The reading:** location plus the moving terminal boundary explain continuation. The experiment cannot rule
out residual path effects smaller than about 7pp. Nothing here justifies post-entry ML.

**Scope.** No model was trained. The final 20% of 2023 was never loaded: bars, rows and labels, and the
engine replay stops at the development boundary. 2024–2026 were not touched.

The design was frozen at `2e8ca01e` before the build and before any comparison. The analysis code follows it.

## The ten required answers

**1. Does the real fixed-price race differ from the analytical location-only null?**
**No.** P(+2A before −1A | first touch x), pooled development, against (x + 1) / 3:

| x | 0.25 | 0.50 | 0.75 | 1.00 | 1.25 | 1.50 |
|---|---|---|---|---|---|---|
| actual | 41.0% | 49.7% | 58.6% | 66.9% | 75.0% | 83.4% |
| (x + 1) / 3 | 41.7% | 50.0% | 58.3% | 66.7% | 75.0% | 83.3% |
| residual [95% CI] | −0.7 [−1.9, +0.8] | −0.3 [−1.8, +1.4] | +0.2 [−1.5, +1.9] | +0.2 [−1.5, +1.9] | 0.0 [−1.7, +1.7] | 0.0 [−1.6, +1.5] |

Each residual is inside ±1.5pp in discovery and in replication, and no CI in discovery excludes zero. That
tightly bounds the *level*: any uniform drift or momentum in this population is under about 2pp.

**2. How large are the discrete-bar, tick and overshoot corrections?**
Negligible.
- The median anchor-bar overshoot is 0.00–0.01A.
- The overshoot-aware null (cur + 1) / 3 sits +0.4 to +0.5pp above (x + 1) / 3.
- The driftless 30 s block bootstrap of the preceding hour of real 1s bars (N2) sits within +0.1 to +0.8pp
  of the analytic line.

The analytic null needs no meaningful correction here.

**3. Conditional on exact location, does path history predict continuation?**
**Not in the fixed race.** At every anchor the four primary variables shift P(+2A before −1A) by at most
about 3pp against N2:
- time to anchor;
- pullback from MFE;
- MAE so far;
- 30 s return.

None is meaningful in discovery. The raw fixed race gives the same picture. In the terminal race and in
giveback, raw effects exist, but they shrink sharply against the engine null (answers 5–7).

**4. When does any residual path information first appear?**
Only at the top. The one discovery-passing residual (ret30 and speed → giveback against the engine null) is at
+1.5A and +2A, not below. Nothing survives at +0.25A to +1.25A in any residual outcome.

**5. Is speed informative after time-of-day and session-truncation controls?**
- **Fixed race:** no. The stratified speed delta is between −1.2 and +3.4pp, and none is meaningful.
- **Terminal race:** raw speed matters. Slow arrivals reach +2A before the flip about 5pp less often, and the
  time-of-day stratification and last-hour exclusion change nothing. Against the replayed-engine null it falls
  to −0.8 to −3.7pp, and none is meaningful.
- **Giveback:** the raw effect is large: −5.3 / −9.3 / −14.3pp (slow minus fast) at +1A / +1.5A / +2A. Against
  the engine null it is −2.2 / −4.5 / −5.9pp.

**6. What is the causal opposite-1m flip trigger, and does its movement explain the speed effect?**
**The engine.** The trigger comes from `features/trackers/regime_dual_ema.py`: EMA(3) and EMA(9) of completed
1m highs and lows.
- A long flips only when a **completed 1m close** falls below **both** low-EMAs, after they absorb that bar's
  own low. Shorts mirror this. Intrabar prices never flip.
- The causal trigger is therefore `min(EMA3_low, EMA9_low)`, a lagging, trailing boundary.
- Replaying the engine on catalog 1m bars reproduces **all 6,024 T0 flips and all 6,024 terminal flips**
  exactly.

**Yes, it explains most of the speed effect.** Fast arrivals leave the trigger far behind: at the +2A touch
its median is −0.92A for fast trades against +0.09A for slow ones. A later reversal then exits below entry.
Giveback at the +2A touch by trigger tercile is **25.5% → 17.3% → 7.7%**. Within trigger terciles the speed
effect falls to −1.8pp at +1.5A and −2.3pp at +2A, with CIs spanning zero. This is moving-boundary geometry,
not path behaviour.

**7. Can +2A givebacks be distinguished at +1A or +1.5A?**
- **At +1A:** no. The strongest residual is 2–4pp and not meaningful.
- **At +1.5A:** weakly, in discovery only. Against the engine null, ret30 gives +9.1pp and speed −5.6pp.
  In replication the same effects shrink to +2.8pp and −1.2pp: same sign, well under half the size.
- **Raw three-class rates** are ordered by speed but mostly mechanically. At +1.5A the giveback share of +2A
  runners is 22.5% fast against 12.4% slow in discovery, and 18.2% against 12.8% in replication.

**8. Which effects replicate from the 154-session block into the 51-session block?**
**None under the frozen rule.** Two primary variables passed discovery, both for giveback against the engine
null and both at +1.5A and +2A: ret30 (+9.1 / +10.7pp) and tod-stratified speed (−5.6 / −6.8pp). In
replication both kept their sign but fell to +2.8 / +4.8pp and −1.2 / −2.8pp. That is below the frozen
half-magnitude requirement, in a block that is itself underpowered.

**9. What was the experiment actually powered to detect?**
Minimum detectable top-vs-bottom tercile difference at 80% power, with a 1.3 design effect:

| block | fixed race / terminal race | giveback |
|---|---|---|
| discovery | 0.06–0.08 | 0.07 |
| replication | 0.11–0.14 | 0.12 |
| pooled | 0.05–0.07 | 0.06 |

Level residuals are much better constrained, to about ±1.7pp.

So the study rules out uniform continuation residuals above about 2pp, and path effects above about 7pp in
discovery. It **cannot confirm or exclude** replicated path effects in the 5–10pp range. That is why the frozen
verdict is INCONCLUSIVE and not LOCATION_ONLY.

**10. Is there enough independent residual information to justify ML?**
**No.** No primary path variable replicated. The one surviving candidate (a sharp run-up into +1.5A or +2A
gives back more) is small once the engine geometry is removed, and it attenuated in replication. It also sits
where the trade has already made its move.

If anything is carried forward, it is a **single frozen hypothesis**, not a feature surface: "at the first
+1.5A or +2A touch, ret30 raises giveback beyond the engine null". Testing it needs a genuinely powered and
untouched sample.

## What the study establishes (useful even without a positive verdict)

1. **The fixed-price race is pure geometry.** Given where price is, how it got there tells you nothing about
   reaching +2A before −1A. The earlier 49% → 63% → 80% progression is (x + 1) / 3.
2. **The terminal race is geometry plus a moving boundary.** The trailing dual-EMA trigger reproduces
   continuation within about 2pp. Real trades sit **consistently about 2pp below** the driftless engine null
   at every anchor. This is below the 5pp "meaningful" bar, but its sign never changes.
3. **"Fast +2A gives back" is mostly the flip trigger being left behind**, not a behavioural property of fast
   moves.

## Files

| file | content |
|---|---|
| `FIXED_RACE_NULL.md` | answers 1–2, level residuals |
| `TERMINAL_FLIP_TRIGGER.md` | answer 6, engine parity, trigger conditioning |
| `PATH_INFORMATION_TESTS.md` | answers 3–5, 8–9 |
| `GIVEBACK_MECHANISM.md` | answer 7 |
| `MECHANICAL_NULL_VERDICT.json` | verdict |

Tables in `artifacts/`:
- `EVENT_LEVEL` — one row per trade × anchor; reproduces every aggregate;
- `LEVEL_RESIDUALS`, `PATH_EFFECTS`, `POWER`, `TRIGGER_CONDITIONING`, `GIVEBACK_THREE_CLASS`, `ROBUSTNESS`;
- `ANALYSIS_RESULTS.json`, `BUILD_AUDIT.json`, `DESIGN.json`.

```
INCONCLUSIVE_MECHANICAL_BASELINE
```
