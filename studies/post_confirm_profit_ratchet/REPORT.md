# Post-Confirmation Profit-Ratchet Feasibility — Report

**Study:** `post_confirm_profit_ratchet` · **Completed:** 2026-08-11
**Population:** 4,656 measurable confirmed trades · 8,950 original Top-10 entries
**Years:** 2021–2025 · **2026 sealed and never read**
**Verdict:** **D — GEOMETRY SEPARATES BUT ECONOMICS DO NOT**

---

## 0. The one-paragraph answer

A profit ratchet does not work here, and the reason is not that the stop is
mispriced — it is that **successful continuation and failed continuation are the
same shape, and the successful one is the more violent of the two.** Measured to
their own terminals, trades that go on to make another rung suffer a *larger*
maximum drawdown from their high-water mark (median **2.35–2.75 ATR**) than
trades that fail (**1.97–2.36 ATR**), because they live three times longer and
travel two ATR further. Any stop tight enough to catch the failure catches the
runner too, a few minutes later. The apparent separation — a raw AUC of
**0.96–0.97** — is almost entirely trade duration: measured over the same elapsed
window it collapses to **0.56–0.75**. The best of the 126 frozen cells recovers
**1.73%** of the 0.898 ATR/entry giveback pool with a confidence interval that
spans zero.

---

## 1. Lineage — reproduced exactly, nothing repaired

| Quantity | Observed | Accepted | Status |
|---|---|---|---|
| Original Top-10 entries | 8,950 | 8,950 | exact |
| Confirmed | 4,705 | 4,705 | exact |
| Stopped before confirm | 4,245 | 4,245 | exact |
| Measurable confirmed | 4,656 | 4,656 | exact |
| Non-measurable | 49 | 49 | exact |
| Giveback pool / entry | 0.8980826 | 0.89808 | Δ 0.0000026 |
| Baseline net / entry | −0.0765296 | −0.07653 | Δ 0.0000004 |
| `P(next +0.50)` ladder, FROM_ENTRY | 0.8069712 / 0.8007743 / 0.7919762 / 0.8149016 / 0.8008037 / 0.8042328 | identical to 7 d.p. | exact |

All **16 validation gates pass**. No predecessor number required adjustment; no
lineage was silently repaired.

## 2. Phase 1 — the rung population

Primary basis is `POST_CONFIRM` (arming clamped to the confirmation bar, SPEC D2).

| Rung | N | % of 4,656 | % of 8,950 | % ARM_FRESH | median s confirm→rung |
|---|---|---|---|---|---|
| 1.0 | 4,160 | 89.3% | 46.5% | 41.6% | 0 |
| 1.5 | 3,358 | 72.1% | 37.5% | 73.9% | 38.5 |
| 2.0 | 2,692 | 57.8% | 30.1% | 90.0% | 140 |
| 2.5 | 2,134 | 45.8% | 23.8% | 96.3% | 242 |
| 3.0 | 1,742 | 37.4% | 19.5% | 98.3% | 369.5 |
| 4.0 | 1,134 | 24.4% | 12.7% | 99.3% | 582 |

97.4–98.7% of rung events are reachable while the accepted 1 ATR stop is still
live, so the descriptive population is not an artefact of already-dead trades.

**The already-met trap fired hard, exactly as anticipated.** 898 of the 2,429
`ARM_AT_CONFIRM` rows at the 1.0 rung (37%) had already banked ≥1.5 ATR when the
flip confirmed — their required retracement is zero *by construction*, not by
evidence. Counting them as successes would have inflated `P(next +0.50)` at that
rung by **21.9 points**. They are classified `ALREADY_MET` and excluded from every
distribution; the counts are in `rung_transitions.parquet`.

## 3. Q1 — How much retracement does successful continuation require?

`mae_from_hwm_atr`, SUCCESS_050 only, POST_CONFIRM basis:

| Rung | N | median | p75 | p90 | p95 |
|---|---|---|---|---|---|
| 1.0 | 2,447 | 0.526 | 0.893 | 1.388 | 1.640 |
| 1.5 | 2,391 | 0.595 | 1.040 | 1.560 | 1.905 |
| 2.0 | 2,023 | 0.563 | 0.964 | 1.518 | 1.886 |
| 2.5 | 1,685 | 0.591 | 1.025 | 1.699 | 2.041 |
| 3.0 | 1,344 | 0.559 | 1.018 | 1.592 | 1.971 |
| 4.0 | 871 | 0.546 | 0.986 | 1.437 | 1.920 |

**The requirement is memoryless in exactly the way the probability ladder is.**
Just as `P(next rung)` sits at 0.79–0.81 regardless of how much has been earned,
the retracement required to get there sits at **median ≈ 0.55, p90 ≈ 1.5 ATR**
regardless of rung. Earning 4 ATR buys no reduction in the room the next 0.5 ATR
demands. This is the finding that kills the "protect what you've earned"
intuition: there is nothing about having earned more that makes the next leg
safer.

## 4. Q2 — What stop distance preserves 85 / 90 / 95%?

| Rung | STATIC: D for 85% / 90% / 95% | HWM: D for 85% / 90% / 95% | STATIC max | HWM max |
|---|---|---|---|---|
| 1.0 | 1.00 / 1.25 / **none** | 1.25 / **none** / **none** | 92.5% | 86.9% |
| 1.5 | 1.25 / **none** / **none** | **none** / **none** / **none** | 88.5% | 82.3% |
| 2.0 | 1.25 / **none** / **none** | **none** / **none** / **none** | 89.7% | 83.9% |
| 2.5 | 1.25 / **none** / **none** | **none** / **none** / **none** | 86.5% | 81.6% |
| 3.0 | 1.25 / **none** / **none** | **none** / **none** / **none** | 87.9% | 81.8% |
| 4.0 | 1.25 / 1.25 / **none** | 1.25 / **none** / **none** | 90.8% | 85.5% |

**95% preservation is unreachable at every rung, in every architecture, at every
stop distance on the frozen grid.** A true high-water ratchet never reaches even
90% anywhere. The only cells reaching 90% are static floors at the widest
distance tested — a floor 1.25 ATR below a 4 ATR rung is protection in name only.

## 5. Q3 — Are failed transitions distinguishable? Not once duration is removed

This is where the study earns its keep.

| Rung | AUC raw (**duration-confounded**) | AUC matched @30s | @60s | @120s |
|---|---|---|---|---|
| 1.0 | 0.973 | 0.670 | 0.714 | 0.750 |
| 1.5 | 0.962 | 0.627 | 0.672 | 0.726 |
| 2.0 | 0.968 | 0.636 | 0.673 | 0.708 |
| 2.5 | 0.962 | 0.654 | 0.672 | 0.704 |
| 3.0 | 0.960 | 0.621 | 0.636 | 0.664 |
| 4.0 | 0.960 | 0.562 | 0.596 | 0.640 |

The naive comparison puts SUCCESS windows (median **41–62 s**, they stop at the
target) against FAIL windows (median **240–332 s**, they run to the terminal). A
window six times longer mechanically contains a larger maximum. Measuring both
classes over the **same elapsed window** removes almost the entire effect.

What survives is real but modest — and it points the wrong way for a stop, because
it *grows with horizon*: the information that a continuation has failed arrives
later, not sooner.

**And over the full path the ordering reverses.** Phase 3 measures the identical
statistic on both populations to their own terminals:

| Rung | | median extra MFE after rung | median MAE-from-HWM to terminal | median secs to terminal |
|---|---|---|---|---|
| 2.0 | FAIL | 0.150 | **2.268** | 299 |
| 2.0 | SUCCESS | 2.022 | **2.534** | 848 |
| 4.0 | FAIL | 0.142 | **2.357** | 332 |
| 4.0 | SUCCESS | 2.187 | **2.752** | 834 |

**A successful continuation drives further against its own high-water mark than a
failed one does.** It has to — it lives 2.8× longer. There is no stop distance
that is small relative to the failure and large relative to the success, because
the success is the larger of the two.

## 6. Q4 / Q6 / Q7 — The economics, and the exact cancellation

Gate outcome: **0 of 126 cells** clear all seven conditions.

| Condition | cells passing |
|---|---|
| 1 PRESERVATION ≥90% | 4 |
| 2 GIVEBACK ≥0.50 ATR & ≥25% fail-stop | 124 |
| **3 ECONOMICS (>0, beats both placebos, CI_lo>0)** | **0** |
| 4 YEAR ≥4/5 | 12 |
| 5 DIRECTION both sides | 1 |
| 6 TAIL | 48 |
| 7 NOT-ARTIFACT | 31 |

Failed-transition giveback reduction is real and large — **0.40–1.90 ATR
prevented on 91.7–100% of failures**. It buys nothing, because it is cancelled
almost exactly by what it costs the winners. Decomposition per original entry,
HWM architecture:

| Cell | gains | losses | **net** | of which ≥3 ATR runners |
|---|---|---|---|---|
| rung 2.0, D 0.50 | +0.2434 | −0.2497 | **−0.0063** | −0.1620 |
| rung 2.0, D 1.25 | +0.2022 | −0.1979 | **+0.0043** | −0.0869 |
| rung 3.0, D 1.25 | +0.1429 | −0.1320 | **+0.0109** | +0.0109 |
| rung 4.0, D 1.25 | +0.1038 | −0.0882 | **+0.0155** | +0.0155 |

This is the predecessor line's signature failure mode reproduced for a fourth
time: about **0.20 ATR/entry of loss containment, cancelled by about 0.20
ATR/entry of runner destruction.**

**The runner destruction, on the tiers where it is not tautological.** A tier at
or below the arming rung is meaningless — a ≥3 ATR runner necessarily reaches the
3.0 rung, so it is alive at that touch by construction, which is why
`runner_survival_3atr` reads 100% at rungs 3.0 and 4.0. The informative tiers:

| Cell | ≥3 ATR survival | ≥4 ATR | ≥5 ATR | ≥5 ATR PnL retained |
|---|---|---|---|---|
| rung 2.0, D 0.50 | 23.2% | 7.1% | 3.9% | 0.449 |
| rung 2.0, D 1.25 | 70.2% | 48.9% | 37.2% | 0.648 |
| rung 3.0, D 1.25 | — | 69.1% | 52.2% | 0.800 |
| rung 4.0, D 1.25 | — | — | 71.8% | 0.932 |

A 0.50 ATR trailing stop armed at 2 ATR destroys **77% of ≥3 ATR runners** and
keeps **45%** of the ≥5 ATR cohort's PnL.

**The best cell of all 126** — rung 4.0, D 1.25, HWM — passes five of seven
conditions and fails the two that matter:

```
delta / original entry        +0.0155 ATR      (1.73% of the 0.898 pool)
trade-clustered 95% CI        [-0.0019, +0.0314]   SPANS ZERO
absolute net / original entry -0.0610 ATR      (baseline -0.0765; still negative)
success_050 preservation      85.5%            (below the 90% bar)
years positive                4 / 5            (2025 = -0.0007)
sides                         LONG +0.0003 · SHORT +0.0152   (effectively short-only)
edge over P_BLIND / P_UNCOND  +0.1456 / +0.2213
```

It arms on **12.7% of original entries**, a median **582 s** after confirmation.

**Q7 — how much of the pool is recoverable: 1.73% at best**, against the
program's stated 35–50% bar. The predecessor's staged harvest reached 0.56%. Both
are rounding error on the same pool.

## 7. Q5 — Static floor vs high-water ratchet

They fail differently, and the difference is instructive.

- **STATIC preserves more at the same distance** — rung 2.0, D 0.50: 62.5% vs
  45.9% for HWM. A fixed floor does not chase the high-water mark, so a runner
  that surges and pulls back is not stopped by its own progress.
- **HWM has the better economics at high rungs** — rung 4.0, D 1.25: +0.0155 vs
  +0.0044. It captures more of the giveback on the trades that do roll over.
- **`LADDER_STATIC` ≡ `STATIC` in survival** and differs only marginally in
  economics; `LADDER_HWM` is **provably identical to `HWM`** (gate 8 asserts a
  bit-identical exit index) because a high-water stop already advances
  continuously, so re-arming it at a later rung cannot move it.

Neither architecture clears the gate. Static buys preservation and loses the
capture; high-water buys the capture and loses the runners.

## 8. Q8 — Can the payoff function replace prediction? No

The hypothesis was that we would not need to predict the end of the regime if the
adverse excursion required by continuation were materially smaller than the
giveback suffered by failure. **It is not smaller. It is larger.** Successful
continuation requires median 0.55 and p90 1.5 ATR of high-water retracement, and
by its own terminal has drawn down *more* from its high-water mark than a failure
has. The payoff function cannot be reshaped around a difference that does not
exist.

## 9. Stability

The headline cell, by partition:

| Slice | N | Δ / original entry |
|---|---|---|
| 2021 | 218 | +0.0055 |
| 2022 | 215 | +0.0010 |
| 2023 | 218 | +0.0003 |
| 2024 | 248 | +0.0094 |
| 2025 | 235 | **−0.0007** |
| LONG | 482 | +0.0003 |
| SHORT | 652 | +0.0152 |

Two years are within 0.001 of zero and the entire effect is short-side. **2025 is
NOT threshold-OOS** (inherited waiver `full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`).

## 10. Verdict

**D — GEOMETRY SEPARATES BUT ECONOMICS DO NOT.**

Two cells (rung 4.0 / D 1.25 / `STATIC` and `LADDER_STATIC`) clear ≥90%
preservation together with material failed-transition giveback reduction, which
is what routes this to **D** rather than **E** under the frozen SPEC §6 rules.
That distinction is technical and should not be read as encouragement: both cells
have CIs spanning zero, are positive in 3 of 5 years, and are direction-unstable.

By the frozen decision gate, **a ratchet architecture is not worth further
development.** The hypothesis as stated — *"the adverse excursion required by
successful continuation is materially smaller than the giveback experienced by
failed continuation"* — is **false in this population**, and the study should be
read as having answered that question rather than as having failed to find a
threshold.

**What this closes.** Post-confirmation exit *timing* was closed by the
predecessor (verdict E: state predicts scale, not sign). Post-confirmation exit
*protection* is now closed too. Loss containment and runner preservation are the
same lever pulled in opposite directions, and on this population they cancel to
within 0.02 ATR per entry at every rung and every stop distance tested.

**What this does not close.** Every result here is conditional on the accepted
entry: an immediate Top-10 fade whose baseline is −0.0765 ATR/entry with 47.4% of
arms stopped before they ever confirm. The giveback pool is large (0.898) but so
is the entry's own bleed. Nothing in this study speaks to a different entry, a
different initial stop, or position sizing — which is where the predecessor's
verdict E already pointed.

---

### Audit status

| Gate | Result |
|---|---|
| `causal_lint` | 0 CRITICAL, 0 WARNING (7 files) |
| 16 SPEC §9 validation gates | all pass |
| Hard-truncated replay | 890 trades, 2,782 rung events, **0 mismatches** |
| `lookahead-auditor` pass 1 (pre-execution) | 1 WARNING, fixed before first run |
| `lookahead-auditor` pass 2 (completion) | 1 CRITICAL, **fixed and fully re-run** (below) |
| `contract-checker` | CLEAR — 0 critical; 1 warning fixed, 1 note documented |

**The pass-2 CRITICAL, and what it changed.** Phase 5's survival frontier was
reading the **stop-live** exit (`policy_exit_idx`) instead of the unconstrained
one that SPEC D1 requires for a descriptive phase. Every rung event arriving
after the accepted 1 ATR stop had already closed the trade — 1.7–2.4% of events —
was counted as having "survived" a stop that in fact never armed, biasing
survival upward by up to 2.5 pp on all 168 cells, and feeding decision-gate
conditions 1 and 2. Worse, validation gate 7, the one check written to catch
exactly this, was a hardcoded `True`.

Both are fixed: the frontier now reads a dedicated unconstrained trigger
(`unc_exit_idx`), the economic columns stay on the stop-live track where they
belong, and gate 7 now asserts the **shipped** `stop_survival_frontier.parquet`
equals the Phase 2 CDF row by row (max difference **1.1e-16** across 168 cells).
Gate 14 was likewise converted from a hardcoded pass into a real structural test
of the length-blind placebo.

**Disclosed, non-binding.** Gate condition 2 combines an *unconstrained*
`failure_stop_rate` with a *stop-live* `giveback_prevented` — two tracks, by
design, since one is descriptive and the other economic. This cannot flip any of
the 126 cells: the minimum fail-stop rate on either track (90.6–91.7%) is far
above the 25% threshold, so condition 2 is always bound by
`giveback_prevented`, which is measured on the correct stop-live track.

The full pipeline was rebuilt and re-run. **The economics were never affected**
(they were always correctly stop-live) and are unchanged to the last digit; the
preservation figures in §4 and §6 moved by ≤0.7 pp and are the corrected values.
**The verdict is unchanged: D, gate 0/126, the same two cells clearing
conditions 1–2.**
