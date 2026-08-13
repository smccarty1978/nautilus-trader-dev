# Fast-Confirm Top-10 Post-Confirmation Runner Path — Report

**Study:** `top10_fast_confirm_runner_path` · 2026-08-10
**Population:** 8,950 original Top-10 entries → 4,656 measurable confirmed → **2,383 FAST_CONFIRM_120**
**Predecessor:** `top10_post_confirmation_mfe_monetization` (verdict F)

---

## Executive summary

**The fast-confirm hypothesis is refuted, and the post-confirmation path question
is answered yes — with a caveat that kills the exit rule anyway.**

Three findings, in order of confidence:

**1. Fast confirmation identifies a *worse* population, monotonically.** Not
neutral — inverted. Every 60 seconds of additional time-to-confirm buys a better
trade, all the way out past 300 s:

```text
cohort              n      mean net ATR   P(>=3 ATR)   median MAE to confirm
FAST_0_60         1,174       0.518          0.332           0.125
FAST_61_120       1,209       0.818          0.359           0.257
SLOW_121_300      1,522       0.998          0.405           0.497
VERY_SLOW_GT300     751       0.972          0.402           0.696
```

Fast confirmation buys exactly one thing — **less risk** (median MAE 0.181 vs
0.560 ATR) — and pays for it with less of everything else. It is a *smaller-
excursion* population, not a better one. The cohort test fails **0 of 5 years**.

**2. The post-confirmation path genuinely separates runners from failures.** This
survives the containment control that invalidates the naive version: at +120 s,
`ret_from_entry` reaches **AUC 0.756** on the 1,595 trades whose outcome is still
genuinely open, quintile-monotonic, same sign in **5 of 5 years**. The separation
is real and it is not a restatement of the label.

**3. It cannot be converted into an exit rule, and the reason is new.** All four
policies fail, but not the way the predecessor's did. They fail because **the
1.00 ATR initial stop has already taken the trades the signal identifies.** At
+120 s, 20.8% of fast trades sit at or below break-even — but **40.5% of those
are already stopped out**. Only 12.4% of the cohort is still actionable.

And every policy loses to its own count-matched random placebo:

```text
policy                   coverage   Δ/fast trade   placebo Δ   beats placebo
P2_PROG60_LE0              13.3%      +0.0109       +0.0864         NO
P3_STALL60_DD050           87.1%      +0.0031       +0.5177         NO
P1_PROG120_LE0             12.2%      +0.0016       +0.0834         NO
P4_MFE15_DD050_STALL45     64.0%      -0.0200       +0.2946         NO
```

The placebo column is the real result. **A uniformly random exit after
confirmation beats the natural exit by up to +0.52 ATR/trade** — so the baseline
is genuinely awful — and not one causal rule we derived beats a coin flip.

---

## 1. Phase 0 — reconciliation

| Quantity | Observed | Accepted | Pass |
|---|---:|---:|:--:|
| Original Top-10 entries | 8,950 | 8,950 | ✅ |
| Confirmed | 4,705 | 4,705 | ✅ |
| Stopped before confirmation | 4,245 | 4,245 | ✅ |
| Measurable in panel | 4,656 | 4,656 | ✅ |
| Non-measurable confirmed | 49 | 49 | ✅ |
| Giveback pool / original entry | **0.8981** | 0.899 | ✅ |
| Baseline net / original entry | **−0.0765** | −0.0742 | ✅ |

The **49** trades are the predecessor's `SESSION_CLOSE_UNRESOLVED` set: the
entry's own RTH session has no bar strictly after `entry_ns`, so the clamped
window collapses. They are enumerated by terminal label in
`validation_report.json`.

---

## 2. Phase 1 — FAST_CONFIRM_120, and a boundary defect worth recording

**2,383 measurable trades** (2,392 of the 4,705 confirmed): **51.2% of measurable
confirmed, 26.6% of all Top-10 entries.** LONG 1,079 / SHORT 1,304; by year
540 / 506 / 481 / 389 / 467.

**52 trades confirm at exactly 120.000 s.** Polars renders that Int64 gap as
`120.00000000000001` under `/1e9`, silently dropping all 52 out of the primary
population — a 2.2% population error from a float representation. Classification
is therefore done in **integer nanoseconds** (`confirm_ns − entry_ns ≤ 120·NS`).
The stored `walk_a_seconds_to_confirm` field would have classified 2,380 instead
of 2,392; it is not used. Both sensitivities are recorded in gate 5.

Cohorts partition exactly: 1,174 + 1,209 = 2,383.

---

## 3. Phases 2–3 — fast confirmation is a smaller move, not a better one

Entry → confirming flip (medians):

| | FAST_0_60 | FAST_61_120 | SLOW_121_300 | VERY_SLOW |
|---|---:|---:|---:|---:|
| seconds to confirm | 45 | 95 | 185 | 415 |
| return at confirm | 0.618 | 0.844 | 0.941 | 1.031 |
| MFE to confirm | 0.793 | 1.037 | 1.132 | 1.259 |
| **MAE to confirm** | **0.125** | 0.257 | 0.497 | 0.696 |
| capture at confirm | 0.816 | 0.839 | 0.860 | 0.857 |

Every column is monotone in confirmation time. Fast trades arrive at the flip
having risked less *and* gained less.

After confirmation the two groups are nearly identical — additional MFE
1.963 vs 1.978 mean, median 1.141 vs 1.167, seconds to MaxMFE 239 vs 259. **The
post-confirmation opportunity is the same; the difference is entirely in what
happened before the flip, and in the eventual ceiling** (eventual MaxMFE median
2.137 vs 2.482).

Median **fraction of eventual MaxMFE already realised at confirmation: 0.444**
(fast) vs 0.496 (slow). Slightly more of the move remains after a fast
confirmation — the one dimension where fast is nominally ahead, and it is not
enough to overcome the lower ceiling.

---

## 4. Phase 4 — runner buckets (retrospective, unconstrained MaxMFE)

| Bucket | n | % | median MaxMFE | mean natural return | % stopped after confirm | median s to MaxMFE |
|---|---:|---:|---:|---:|---:|---:|
| R0 <1 ATR | 328 | 13.8 | 0.761 | **−0.905** | 68.9 | 4 |
| R1 1–2 | 786 | 33.0 | 1.422 | −0.519 | 30.7 | 72 |
| R2 2–3 | 445 | 18.7 | 2.420 | +0.157 | 8.5 | 318 |
| **R3 ≥3** | **824** | **34.6** | 4.656 | **+2.876** | 4.1 | 814 |
| ≥2.5 ATR | 1,005 | 42.2 | 4.158 | +2.414 | 4.6 | 719 |
| ≥4 ATR | 543 | 22.8 | 5.663 | +3.777 | 3.7 | 1,022 |

**34.6% of fast-confirm trades become ≥3 ATR runners** and they carry the entire
book (+2.876 ATR mean against −0.905/−0.519 for R0/R1). Time-to-MaxMFE separates
the buckets by two orders of magnitude — R0 tops out 4 seconds after
confirmation, R3 takes 814.

---

## 5. Phases 5–6 — healthy runners do behave differently, immediately

State at **+60 s**, ≥3 ATR vs <2 ATR (constant population, medians):

| Variable | ≥3 ATR | <2 ATR |
|---|---:|---:|
| return from entry | **1.099** | 0.408 |
| return since confirmation | **+0.231** | **−0.244** |
| running MFE | 1.515 | 1.020 |
| drawdown from running max | 0.367 | 0.577 |
| **retracement fraction** | **0.250** | **0.573** |
| made a new extreme | 84% | 65% |
| seconds since last extreme | 31 | 53 |
| n new extremes | 4 | 1 |
| progress over prior 60 s (mark) | **+0.234** | **−0.236** |

The sign flip on `ret_since_confirm` and `prog_mark_60s` is the cleanest result
in the study: **by one minute after the flip, healthy runners are still going up
and failures are already going down.** A ≥3 ATR runner has made 4 new favorable
extremes; a failure has made 1.

---

## 6. Phase 7 — a 0.25–0.50 ATR retracement is completely normal

First armed giveback from the running MaxMFE (armed = you must have accumulated
the excursion before you can give it back):

| level | % reaching | raw def. | median MFE at event | P(new extreme after) | P(add +0.50) | P(≥3 ATR) |
|---:|---:|---:|---:|---:|---:|---:|
| 0.25 | **99.5** | 100.0 | 1.003 | 0.856 | 0.660 | 0.348 |
| 0.50 | **97.5** | 100.0 | 1.176 | 0.783 | 0.574 | 0.355 |
| 0.75 | 93.3 | 100.0 | 1.365 | 0.712 | 0.495 | 0.370 |
| 1.00 | 86.2 | 99.9 | 1.524 | 0.640 | 0.428 | 0.401 |
| *(none)* | 100 | — | — | — | — | 0.346 |

**Answer to "is a 0.25/0.50 ATR retracement normal or terminal?" — entirely
normal.** 99.5% and 97.5% of fast-confirm trades experience one, and after a 0.50
ATR giveback there is still a 78% chance of a new favorable extreme.

**There is no giveback level at which the probability of a new extreme materially
deteriorates.** It decays gently (0.856 → 0.640) and, critically, `P(≥3 ATR)`
*rises* with giveback depth (0.348 → 0.401) — because reaching a deep giveback
requires having had deep MFE. Giveback depth is a proxy for trade size, not for
trade death.

**Degeneracy disclosure.** The naive definition (`running max − low ≥ level`)
fires on **100% / 100% / 99.96% / 99.92%** of trades, because running MFE is
floored at zero and a trade merely trading 1 ATR *below entry* books a "1.00 ATR
giveback". Both definitions are reported; only the armed one is used.

---

## 7. Phase 8 — time since the last extreme is informative; the tables are not

Armed stall (clock runs from a genuine post-confirmation new favorable extreme):

| stall | % reaching | raw def. | median additional MFE | P(new extreme) | P(≥3 ATR) |
|---:|---:|---:|---:|---:|---:|
| 15 s | 90.1 | 100.0 | 0.913 | 0.781 | 0.383 |
| 30 s | 90.1 | 100.0 | 0.786 | 0.726 | 0.383 |
| 45 s | 90.1 | 100.0 | 0.656 | 0.682 | 0.383 |
| 60 s | 89.3 | 99.2 | 0.538 | 0.644 | 0.387 |
| 90 s | 88.0 | 97.1 | 0.339 | 0.583 | 0.391 |
| 120 s | 83.4 | 92.8 | 0.208 | 0.543 | 0.409 |

**Yes, time-since-last-favorable-extreme is informative** — median remaining MFE
falls 0.913 → 0.208 as the stall lengthens, a 4.4× decay, and `P(new extreme)`
falls monotonically. It carries `AUC` lift 0.13–0.21 in Phase 11, comparable to
drawdown.

But note `P(≥3 ATR)` *rises* here too (0.383 → 0.409), the same conditioning
artefact as Phase 7: only long-lived trades survive long enough to post a long
stall. **These conditional tables cannot be read as policy evidence.** Phase 11,
which compares within a fixed population, is the honest instrument.

---

## 8. Phase 9 — progress dominates; drawdown is nearly irrelevant

At +120 s (n, median additional MFE, P(≥3 ATR), mean natural return):

| progress ↓ / drawdown → | <0.25 | 0.25–0.50 | >0.50 |
|---|---|---|---|
| **low** | n=0 | n=3 | n=**792** · 0.000 · **0.157** · **−0.194** |
| **medium** | n=83 · 1.388 · 0.410 · +0.969 | n=246 · 0.770 · 0.289 · +0.578 | n=465 · 0.406 · 0.295 · +0.731 |
| **high** | n=369 · 1.358 · **0.612** · +1.717 | n=240 · 0.957 · 0.525 · +1.648 | n=185 · 0.818 · **0.573** · **+1.616** |

Read across any row: drawdown barely moves the outcome, and in the high-progress
row a **>0.50 ATR drawdown still returns +1.616 ATR with P(≥3) = 0.573** —
slightly *better* than the <0.25 drawdown cell on P(≥3) at +30 s. Read down any
column: progress changes everything (0.157 → 0.612).

**This is the study's central mechanism.** Exit rules in this program have always
been built on giveback. The data says giveback is the wrong axis; forward
progress is the right one. The low-progress cell at +120 s is large (792, one
third of the cohort), unambiguous (median additional MFE exactly **0.000**), and
economically dead (−0.194 ATR).

---

## 9. Phase 11 — the separation, and the control that validates it

`≥3 ATR` vs `<2 ATR`, best variables, **undetermined population** (the gate):

| landmark | variable | AUC | lift | monotone | years |
|---:|---|---:|---:|:--:|:--:|
| 120 | `ret_from_entry` | **0.756** | 0.256 | ✅ | 5/5 |
| 120 | `retrace_frac` | 0.262 | 0.238 | ✅ | 5/5 |
| 120 | `ret_since_confirm` | 0.728 | 0.228 | ✅ | 5/5 |
| 120 | `dd_from_run_max` | 0.290 | 0.210 | ✅ | 5/5 |
| 60 | `ret_from_entry` | 0.724 | 0.224 | ✅ | 5/5 |
| 60 | `retrace_frac` | 0.301 | 0.199 | ✅ | 5/5 |
| 30 | `ret_from_entry` | 0.692 | 0.192 | ✅ | 5/5 |

**25 variable×landmark combinations clear the frozen gate** (27 on the
unamended constant population). Every one is consistent in 5 of 5 years.

**The containment control.** `eventual MaxMFE ≥ run_mfe_entry` by construction,
so a trade already showing ≥2.0 ATR of running MFE **cannot** be in the `<2 ATR`
class — it is a guaranteed positive. Those trades are **6.8 / 9.5 / 17.7%** of
the labelled set at 30/60/120 s and **100% of them are positives**, exactly as
the containment argument predicts. Scoring them measures the definition of MaxMFE,
not the path. The gate was therefore **amended before any policy was written** to
judge on the `undetermined` population only (SPEC §8). It opens under both, so
the amendment could not have manufactured the verdict — but the AUCs it removes
are inflated by 0.05–0.09 and the honest numbers are the ones above.

---

## 10. Phase 10 — raw model score, EXPLORATORY_OUT_OF_DOMAIN

| landmark | metric | median | AUC (≥3 vs <2) | lift |
|---:|---|---:|---:|---:|
| 30 | score | 0.358 | 0.354 | 0.146 |
| 60 | score | 0.383 | 0.317 | 0.183 |
| 120 | score | 0.384 | **0.247** | **0.253** |
| 120 | Δ score since confirm | +0.042 | 0.259 | 0.241 |
| 120 | P90 reached | — | 0.335 | 0.165 |

Polarity is correct and inverted as expected — a *rising* new-regime score means
the new regime is likely to end, so high score → fewer runners. Score coverage is
essentially complete (2 nulls at +30 s, 0 thereafter).

**Does it add anything beyond price path? No.** At +120 s the score's lift
(0.253, constant population) is statistically comparable to `ret_from_entry`
(0.346 constant / 0.256 undetermined) and lands on the same trades. It is not
worse than price — it is simply not additive, and it remains out of domain.

---

## 11. Phase 12 — four policies, all fail, and the placebo explains why

| policy | coverage | Δ/fast trade | Δ/orig entry | placebo Δ | beats placebo | givebk recov | losers fixed | ≥3 preserved |
|---|---:|---:|---:|---:|:--:|---:|---:|---:|
| `P2_PROG60_LE0` | 13.3% | +0.0109 | +0.0029 | +0.0864 | ❌ | 0.3% | 19.7% | 95.2% |
| `P3_STALL60_DD050` | 87.1% | +0.0031 | +0.0008 | +0.5177 | ❌ | 0.1% | 75.0% | 29.7% |
| `P1_PROG120_LE0` | 12.2% | +0.0016 | +0.0004 | +0.0834 | ❌ | 0.05% | 18.0% | 95.4% |
| `P4_MFE15_DD050_STALL45` | 64.0% | **−0.0200** | −0.0053 | +0.2946 | ❌ | −0.6% | 32.9% | 30.6% |

**Runner destruction, ≥3 ATR tier (n = 798), mandatory:**

| policy | cut | % cut | placebo % cut | median MaxMFE of the cut | opportunity cost |
|---|---:|---:|---:|---:|---:|
| `P1_PROG120_LE0` | 37 | **4.6%** | 1.9% | 5.40 | 126 ATR |
| `P2_PROG60_LE0` | 38 | 4.8% | 2.3% | 4.25 | 117 ATR |
| `P3_STALL60_DD050` | 561 | **70.3%** | 35.6% | 4.57 | **1,084 ATR** |
| `P4_MFE15_DD050_STALL45` | 554 | 69.4% | 36.2% | 4.55 | 866 ATR |

Two distinct failure modes, and the split is exactly the Phase 9 mechanism:

* **The giveback/stall policies (P3, P4)** — the brief's own worked examples, and
  the family every previous study in this line has tried — destroy **70% of ≥3
  ATR runners**, twice the rate a random exit destroys, for ~zero and negative
  return. Phase 9 predicted this: they trigger on the axis that does not matter.
* **The progress policies (P1, P2)** — built on the axis that does matter —
  preserve **95% of ≥3 ATR runners** and are net-positive, but act on only
  12–13% of trades and return +0.0004 to +0.0029 ATR per original entry.

**Why coverage is so low is the finding.** At +120 s, 20.8% of fast trades are at
or below break-even, but **40.5% of those have already been stopped out** by the
1.00 ATR initial stop. The progress signal and the existing stop are largely
looking at the same trades — **the stop is already collecting most of this
edge.** The signal is real and substantially redundant with the frozen contract.

**Nothing is stable.** Three of four policies flip sign between LONG and SHORT
(`P2` +0.028 LONG / −0.003 SHORT; `P3` −0.020 / +0.023), and by year no policy is
positive in more than 3 of 5. `policy_stability.parquet` carries both slices.

**Every policy loses to its count-matched random placebo** (20 draws/trade, seed
20260810, uniform over `[confirm, natural terminal)`, causal next-bar-open fill).
The placebo deltas are large and positive (+0.083 to +0.518), which is a verdict
on the *baseline*: holding a fast-confirm trade to the opposing regime flip is so
poor that a coin-flip exit beats it by up to half an ATR. Median unconstrained
capture is **0.000** and mean is **−0.225** — the natural exit gives back the
entire excursion. Against that benchmark, no rule we derived from the causal path
is better than chance.

---

## 12. Defects found and fixed during this study

| # | Defect | Found by | Effect |
|---|---|---|---|
| 1 | 52 trades confirming at exactly 120.000 s dropped from the primary population by polars `Int64/1e9` → `120.00000000000001` | own cross-check | 2.2% population error. Classification moved to integer nanoseconds; both alternative methods recorded as gate-5 sensitivities |
| 2 | Giveback events defined as `running max − low` fired on **100%** of trades — a trade merely 1 ATR below entry booked a "1.00 ATR giveback" | own review of Phase 7 output | Phase 7 was uninformative by construction. Added the ARMED definition (`ext ≥ level`); raw retained as disclosure |
| 3 | Stall clock ran from the confirmation bar, crediting trades that never went favorable with a stall — 100% "reached" a 15 s stall | own review of Phase 8 output | Same. Armed definition requires a genuine post-confirmation favorable extreme |
| 4 | Phase 11 AUC inflated by mechanical containment (`run_mfe ≥ 2.0` ⇒ guaranteed positive) | own review before Phase 12 | AUCs overstated by 0.05–0.09. Gate amended to the `undetermined` population and the amendment recorded in SPEC §8 |
| 5 | Replay gate computed `seg_hi` but never checked it — validated only `mark` while claiming to validate landmark state; gate 9 was hardcoded `True` | `lookahead-auditor` pass 1 (NOTE) | Replay now checks **six** state variables on **hard-truncated** arrays (2,400 pairs, 0 mismatches) and gate 9 is *derived* from it |
| 6 | No-op filter `landmark_s == landmark_s`; empty `tests/` | `lookahead-auditor` pass 1 (NOTE) | Removed; 16 deterministic tests added covering cohort edges, causal fill, the stop invariant, and future-blindness of landmark states |

---

## 13. The fourteen questions

**1. How many confirm within ≤120 s before the stop?** 2,392 of 4,705 confirmed
(2,383 measurable) — 51.2% of confirmed, **26.6% of all Top-10 entries**.

**2. Is FAST_CONFIRM economically different?** Yes — **worse**, monotonically.
Mean net 0.670 vs 0.990 ATR; P(≥3 ATR) 0.346 vs 0.404. Cohort test fails 0/5
years. Its only advantage is lower risk (median MAE 0.181 vs 0.560).

**3. Median return and MFE at the fast confirming flip?** Return **0.739**, MFE
**0.927**, MAE 0.181, capture 0.830 ATR.

**4. How much additional MFE remains?** Mean **1.963**, median **1.141** ATR —
indistinguishable from slow confirm (1.978 / 1.167). Median **55.6%** of eventual
MaxMFE is still ahead at the flip.

**5. What fraction become runners?** ≥2 ATR **53.3%**, ≥2.5 **42.2%**, ≥3
**34.6%**, ≥4 **22.8%**.

**6. How quickly do ≥3 ATR runners make new extremes?** Immediately and
repeatedly — 84% have made one within 60 s, median 4 new extremes by then, median
31 s since the last. Failures: 65%, 1 extreme, 53 s.

**7. How much retracement do healthy runners require?** A lot. 99.5% of trades
give back 0.25 ATR and 97.5% give back 0.50 ATR; ≥3 ATR runners run a median
0.367 ATR drawdown and 0.250 retracement fraction at +60 s. **Retracement of this
size is normal runner behaviour, not evidence of termination.**

**8. At what giveback level does P(new extreme) materially deteriorate?**
**None.** It decays gently 0.856 → 0.640 from 0.25 to 1.00 ATR, and P(≥3 ATR)
*rises* over the same range. There is no threshold.

**9. Is time-since-last-favorable-extreme informative?** Yes — median remaining
MFE decays 4.4× from a 15 s to a 120 s stall, AUC lift 0.13–0.21. It is the best
of the "absence" variables, though below simple return.

**10. Best separators at 30/60/120 s?** `ret_from_entry` (AUC 0.692/0.724/0.756),
then `retrace_frac` (0.342/0.301/0.262, inverted), `ret_since_confirm`, and
`dd_from_run_max`. All 5/5 years, all quintile-monotonic, all on the
containment-controlled population.

**11. Does model score add anything beyond price path?** **No.** Correct inverted
polarity, comparable lift (0.253 at +120 s), same trades, still out of domain. Not
additive.

**12. Is there enough separation to justify an exit rule?** **Separation, yes.
Exit rule, no.** The actionable window is 12–13% of trades because the 1.00 ATR
stop has already removed 40.5% of the flagged trades, and no policy beats its
count-matched random placebo.

**13. Which ≤4 policies warrant validation?** **None.** `P1`/`P2` are directionally
correct and preserve 95% of ≥3 ATR runners but return ≤0.003 ATR/entry and lose to
chance. `P3`/`P4` destroy 70% of ≥3 ATR runners.

**14. Does this imply recovering 35–50% of giveback is incompatible with
preserving the tail?** For rules of this family, **yes — and this study explains
why more sharply than the predecessor did.** The pool lives in the ≥3 ATR runners
(34.6% of trades, +2.876 ATR each). Their defining behaviour is *surviving deep
retracements* — a median 0.367 ATR drawdown and 0.250 retracement fraction at +60
s, with 78% making a new extreme after a 0.50 ATR giveback. Any rule that
harvests giveback must fire inside the distribution the runners live in, which is
why P3/P4 cut 70% of them. The one axis that *does* separate — forward progress —
is already 40% consumed by the existing 1 ATR stop. Under the frozen contract,
these are not two failures but one structure: **giveback rules cannot avoid the
tail, and progress rules have already been front-run by the stop.**

---

## 14. Limitations

1. **The placebo is the binding evidence, and it indicts the baseline.** A random
   exit beating the natural exit by +0.52 ATR/trade means the opposing-flip exit
   is the real problem on this population. That is a *different* study — exit
   *architecture*, not exit *timing* — and nothing here validates one.
2. **Phase 10 is out of domain** and its AUCs are computed on the constant, not
   the undetermined, population; they are not directly comparable to §9.
3. **Phase 7/8 conditional tables carry a selection artefact** (P(≥3) rises with
   giveback depth and stall length). Stated in place; Phase 11 is the instrument.
4. **Costs are charged once per trade**, marginally favouring active policies.
5. **2025 is not threshold-OOS** (inherited waiver); **2026 untouched**.
6. Runner buckets are retrospective labels and are never available at decision
   time — they exist only to make the path comparison possible.

---

## Final classification

```text
C. CONFIRMATION SPEED IS NOT ECONOMICALLY INFORMATIVE, BUT POST-CONFIRM PATH IS
```

Routed by the frozen SPEC §6 decision table: **cohort test fails** (0/5 years) →
not A, not B; **separation gate opens** (25 variables, containment-controlled,
5/5 years) → not F. Not **D** — no policy is net-positive *and* beats its
placebo, which SPEC §6 requires. Not **E** — the score matches but does not
exceed the price path. Not **G** — Phase 0 reconciles exactly and both audits are
clean.

**One correction to the label's wording, stated plainly:** confirmation speed *is*
economically informative — it is just **inverted**. Faster confirmation reliably
identifies a *worse*, lower-excursion population. Label C is the correct routing
because the hypothesis under test ("fast confirm identifies a superior runner
population") is refuted, but the finding is stronger than "not informative".

**What was learned.** The predecessor found that deterioration *is* the giveback,
so exhaustion signals arrive too late. This study finds the complementary half:
**giveback is not the axis at all.** Forward progress separates runners from
failures within 60 seconds of the flip, cleanly, in every year, and survives the
containment control. It simply cannot be monetized here, because the 1.00 ATR
initial stop already acts on 40% of the trades it identifies, and because holding
to the opposing flip is a baseline so poor that chance beats every rule built on
top of it.

**Where that leaves the program.** The open question is no longer "which exit
signal" but "why is the terminal exit worth less than a random one". Recovering
this pool requires replacing the opposing-flip exit, not timing it — and that is
outside the frozen contract this study inherited.
