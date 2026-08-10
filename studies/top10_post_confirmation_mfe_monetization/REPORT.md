# Post-Confirmation MFE Monetization — Report

**Study:** `top10_post_confirmation_mfe_monetization` · 2026-08-10
**Population:** 8,950 original Top-10 entries → 4,656 confirmed trades
**Policies:** 14 + baseline (15 total) · **Target:** recover 35–50% of the giveback pool

---

## Executive summary

**The pool is real, P90 genuinely marks the top, and none of it is monetizable.**
The best measurable policy recovers **1.0%** of the giveback pool against a 35–50% target.

The reason is exact and it is not a modelling failure — it is arithmetic. Take
`P90B_EXIT` (the simplest measurable policy; `P90ARM_PRICE` is marginally better
at +0.0086 and behaves the same way):

```text
ATR saved by containing confirmed losers    +2,157
ATR surrendered by cutting >=3 ATR runners  -4,875   (61.0% of them cut short)
                                            ------
net over 8,950 entries                        +45.6  =  +0.0051 ATR / entry
```

It converts a losing book into a winning-looking one — win rate 0.515 → 0.846,
median capture 0.059 → 0.282, 96.6% of confirmed losers improved — and gives back
every ounce of it in truncated right tail. **The two effects cancel to three
decimal places.**

### The thirteen questions

**1. Where does P90 occur relative to MaxMFE?** Essentially *at* it. Median
**94.4%** of final MFE already realised (p75 = 1.000, i.e. at or after the peak
bar); median 34s from P90 to MaxMFE, p25 = −65s (the peak was already in).

**2. How much MFE remains after P90?** Median **0.095 ATR**. Almost nothing.

**3. Does exiting exactly at P90 improve the baseline?** Statistically yes,
economically no: **+0.0051 ATR per original entry**, 0.6% of the pool.

**4. Exit or arm?** Arm, marginally. `P90ARM_PRICE` (+0.0086) beats `P90B_EXIT`
(+0.0051) and preserves slightly more of every runner tier, because waiting for
price to cross back through the P90 mark spares the trades that keep running. The
gap is 0.0035 ATR/entry — real in sign, negligible in size.

**5. Best price anchor?** The P90 observation price, scanned from the bar AFTER
the warning. It is the best measurable policy in the study and still recovers 1.0%.

**6. Does the model beat a comparable price-only trail?** Yes in sign, no in
substance. Best model +0.0086 vs best price-only +0.0027; two price-only variants
are *negative*. Both are ~0, and a 0.006 ATR/entry edge is smaller than one tick.

**7. Is P80 useful as an earlier arm?** No. `P80ARM_100` reaches +0.0043,
below P90. Earlier warning buys nothing.

**8–9. How much of the ~0.89 ATR/entry pool can we recover?** **1.0%.** Not ≥25%,
not ≥35%, not ≥50%. Nothing comes close.

**10. What happens to runners?** They are destroyed. `P90B_EXIT` cuts **45.8% of
≥2 ATR, 53.6% of ≥2.5, 61.0% of ≥3, 68.2% of ≥4 ATR runners** before they reach
their tier, at a median eventual MaxMFE of 4.64 ATR for the ≥3 group.

**11. Loss containment?** Genuinely good — 96.6% of confirmed losers improved,
+2,157 ATR avoided. It just doesn't survive the runner cost.

**12. Broad across years/directions?** The *cancellation* is broad. No slice shows
material net gain.

**13. Which ≤3 warrant NT validation?** None. See §6. The best measurable
policy is `P90ARM_PRICE` at +0.0086 ATR/entry — 1.0% of the pool.

---

## 1. Phase 0 — the domain constraint that shapes everything

`top_20` exists for both models, `is_frozen = true`, provenance
`RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION` — Phase 8 ran.

**Contract-valid P90 (stream A) is not measurable.** First-crossing coverage:

| Outcome | n | A contract-valid | B raw causal |
|---|---:|---:|---:|
| CONFIRMED_THEN_STOPPED | 822 | **0.4%** | 97.2% |
| FINAL_FLIP_EXIT_LOSER | 1,359 | **1.0%** | 99.2% |
| FINAL_FLIP_EXIT_WINNER | 2,350 | **47.9%** | 99.6% |

A fires on 48–120× more winners than losers, because the in-domain flag needs the
new regime *established* (median 352–448s post-confirmation) and only long-lived
trades get there. `P90A_EXIT` therefore shows the best headline delta (+0.0159)
while touching 0.7% of losers and preserving 96.2% of ≥3 ATR runners — it barely
acts at all, and only on winners. Marked **NOT INTERPRETABLE — SURVIVORSHIP**
throughout; it is not a result.

All stream-B results are **EXPLORATORY_OUT_OF_DOMAIN**. A and B are never pooled.

---

## 2. Phase 1 — baseline, reconciled

| Quantity | This study | Accepted |
|---|---:|---:|
| Original Top-10 entries | 8,950 | 8,950 |
| Confirmed | 4,656 | 4,656 |
| Stopped before confirmation | 4,245 (−4,531 ATR) | 4,245 |
| Baseline net per **original entry** | **−0.0765** | −0.0742 |
| Giveback pool, flip-exit only | **0.898 /entry** (8,038 ATR) | 0.899 |

Both reconcile. Note the pool measured over *all* confirmed trades is 1.114/entry;
the accepted 0.89 figure is flip-exit-only, and recovery is reported against the
accepted definition.

**Per-original-entry figures include the 4,245 pre-confirmation stops.** Policies
cannot touch those trades, so they cancel from every delta — but omitting them
from the level would have reported a baseline of **+0.4298** instead of −0.0765,
inflating the study by conditioning on survivors.

---

## 3. Phase 3/4 — P90 is a real top-marker that arrives too late

Stream B, 4,573 of 4,656 trades (98.2%):

| Quantity | median | mean | p25 | p75 |
|---|---:|---:|---:|---:|
| fraction of final MFE realised | **0.944** | 0.747 | 0.491 | 1.000 |
| remaining MFE after P90 (ATR) | **0.095** | 1.147 | 0.000 | 1.450 |
| running MFE at P90 (ATR) | 1.460 | 1.879 | 1.006 | 2.251 |
| open PnL at P90 (ATR) | 0.625 | 0.881 | 0.266 | 1.100 |
| **giveback already suffered before P90** | **0.953** | 0.998 | 0.599 | 1.285 |
| seconds confirm → P90 | 75 | 181 | 24 | 245 |
| seconds P90 → MaxMFE | 34 | 276 | −65 | 450 |

Share of P90 events after ≥50/60/70/80/90% of final MFE: **74.5 / 68.1 / 61.9 /
56.6 / 52.0%**.

**This is the study's one genuinely positive finding: P90 is a real late-stage
exhaustion marker.** Over half of all P90 warnings land after 90% of the final
MFE is already in.

**And it is precisely why it cannot be monetized.** By the time it fires the
median trade has already surrendered **0.953 ATR** from its peak and has
**0.095 ATR** left to protect. A 0.75 ATR giveback trail fires *earlier* than P90
does. The warning is accurate and useless in the same breath.

---

## 4. Phases 5–9 — the policy table

Δ/entry = ATR per **original** entry. recov% against the accepted 0.898/entry pool.
Preserved = share of that runner tier NOT cut short.

| Policy | cov% | Δ/entry | recov% | capture | win | ≥2 | ≥2.5 | ≥3 | losers fixed | domain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P90A_EXIT | 24.3 | +0.0159 | 1.8 | 0.068 | 0.519 | 99.7 | 98.8 | 96.2 | 0.7 | **A — survivorship** |
| **P90ARM_PRICE** | 97.0 | **+0.0086** | **1.0** | 0.277 | 0.837 | 56.0 | 48.4 | 41.2 | 96.2 | B — exploratory |
| P90B_EXIT | 97.9 | +0.0051 | 0.6 | 0.282 | 0.846 | 54.2 | 46.4 | 39.0 | 96.6 | B |
| P90ARM_GB050 | 97.9 | +0.0046 | 0.5 | 0.276 | 0.836 | 55.7 | 47.0 | 39.4 | 96.6 | B |
| P80ARM_100 | 99.0 | +0.0043 | 0.5 | 0.247 | 0.770 | 64.3 | 53.0 | 41.6 | 97.5 | B |
| P80ARM_075 | 99.3 | +0.0035 | 0.4 | 0.285 | 0.840 | 51.7 | 40.2 | 30.2 | 98.6 | B |
| P90ARM_GB075 | 97.9 | +0.0034 | 0.4 | 0.257 | 0.800 | 60.2 | 50.7 | 42.0 | 96.3 | B |
| P80ARM_P90EXIT | 99.2 | +0.0033 | 0.4 | 0.295 | 0.866 | 50.7 | 41.1 | 31.4 | 98.8 | B |
| PRICE_D mfe2.0/gb1.00 | 56.2 | +0.0027 | 0.3 | 0.274 | 0.599 | 100.0 | 77.7 | 58.1 | 16.8 | price |
| P90ARM_PRICE_BUF | 85.5 | +0.0019 | 0.2 | 0.200 | 0.726 | 72.0 | 66.5 | 61.9 | 91.6 | B |
| PRICE_A mfe1.0/gb0.75 | 88.1 | +0.0021 | 0.2 | 0.338 | 0.878 | 50.7 | 34.0 | 20.9 | 75.2 | price |
| STAIRSTEP | 88.1 | +0.0008 | 0.1 | 0.288 | 0.834 | 56.4 | 31.7 | 13.4 | 75.1 | price |
| **BASELINE** | 0.0 | 0.0000 | 0.0 | 0.059 | 0.515 | 100.0 | 100.0 | 100.0 | 0.0 | — |
| PRICE_C mfe2.0/gb0.75 | 56.3 | **−0.0053** | −0.6 | 0.274 | 0.599 | 100.0 | 65.1 | 38.9 | 16.8 | price |
| PRICE_B mfe1.5/gb0.75 | 70.6 | **−0.0127** | −1.4 | 0.342 | 0.711 | 65.2 | 42.9 | 26.0 | 39.7 | price |

**Every improvement rounds to zero, and two price-only rules lose money.** The
spread across fifteen structurally distinct policies is 0.021 ATR/entry — smaller
than one tick of the cost model.

**Capture and win rate are traps here.** `PRICE_A` posts the best median capture
(0.338) and win rate (0.878) of any policy and delivers +0.0021 ATR/entry, because
it preserves only 20.9% of ≥3 ATR runners. Capture ratio measures how tidily you
harvest, not how much you make.

---

## 5. Phase 10/12 — the cancellation, exactly

`P90B_EXIT` runner destruction:

| Tier | n runners | cut before tier | median eventual MaxMFE of the cut | ATR surrendered |
|---|---:|---:|---:|---:|
| ≥2.0 | 2,627 | 45.8% | 3.52 | 4,522 |
| ≥2.5 | 2,082 | 53.6% | 4.07 | 4,780 |
| ≥3.0 | 1,696 | **61.0%** | 4.64 | 4,875 |
| ≥4.0 | 1,106 | 68.2% | 5.64 | 4,214 |

Against +2,157 ATR of loss containment. **The policy is a machine for turning
right tail into win rate at par.** That is the whole result.

---

## 6. Finalists

**None.** No policy satisfies the advancement standard: none materially improves
ATR per original entry, none recovers meaningful giveback, and every measurable
one destroys the majority of ≥3 ATR runners.

The closest to interesting is `P90ARM_PRICE_BUF` — it preserves 61.9% of ≥3 ATR
runners while still improving 91.6% of confirmed losers — but at +0.0019
ATR/entry it is economically indistinguishable from doing nothing.

---

## 6a. Defects found and fixed

| # | Defect | Found by | Effect |
|---|---|---|---|
| 1 | `P90ARM_PRICE` scanned for the adverse crossing starting **on** the P90 bar itself. `ref` is that bar's close and `bar_lo[jb]` its own worst level, so the test reduced to `low <= close` — true for nearly every OHLC bar | `lookahead-auditor` pass 1 (CRITICAL) | The policy collapsed into a duplicate of `P90B_EXIT`. **I had reported the identical numbers as a finding** ("arming is indistinguishable from exiting") rather than recognising a bug. Corrected: the policy is now distinct and is the best measurable one. |
| 2 | Per-original-entry level omitted the 4,245 pre-confirmation stops | own review | Reported a baseline of +0.4298 instead of −0.0765 — an inflated study conditioned on survivors. Deltas were unaffected. |
| 3 | Giveback pool included `CONFIRMED_THEN_STOPPED` peak-to-stop giveback | own reconciliation against the accepted study | Pool read 1.114/entry instead of the accepted 0.899. Recovery is now reported against the accepted flip-exit-only definition, which this study reproduces at 0.898. |

Two further WARNINGs were raised against the **validator** in pass 2 and both were
fixed: `score_causally_available` checked only the bullish model when roughly half
the population trades the bearish one, and the crossing check re-ran build.py's own
polars expression rather than deriving it independently — a shared bug would have
passed trivially. It now uses a per-regime numpy scan.

One WARNING is carried, not fixed: when a stop triggers on the final bar of an
already-truncated window there is no legal next bar to fill against, so the fill
falls back to that bar's close. It is session-containment-forced, not future
information, and cannot move the headline.

**All twelve validation gates pass (`all_passed = true`)**, including a 240-trade
independent replay of the causal fill from raw 1s with zero mismatches, and
reconciliation of both the population and the giveback pool to the accepted
excursion study.

## 7. Limitations

1. **Stream B is out of domain.** Even the ~0 results are exploratory; a positive
   one would not have been deployable without a purpose-built domain model.
2. **Stream A is survivorship, not signal.** Its headline number is the largest in
   the table and the least meaningful.
3. **No placebo control was run.** Not needed — nothing showed an effect to
   control for. If any future variant does show one, a count-matched random exit
   is mandatory first (this line has twice mistaken early exit for edge).
4. **Costs are charged once per trade**; policies that exit earlier do not pay
   more, so the comparison marginally favours the active policies.
5. **2025 is not threshold-OOS**; 2026 untouched.

---

## Final classification

```text
F. NO ROBUST POST-CONFIRMATION MFE MONETIZATION FOUND
```

Not **A** — P90 direct exit recovers 0.6% of the pool. Not **B** — arming does
beat exiting (+0.0086 vs +0.0051) but recovers 1.0%, which is not a monetization.
Not **C** —
P80 is worse than P90. Not **D** — price-only is also ~0 and two variants lose.
Not **E** — nothing warrants validation. Not **G** — the population, the giveback
pool and the baseline all reconcile to the accepted study.

**What was learned, and it is worth keeping.** The hypothesis was right about the
mechanism and wrong about the opportunity: the new-regime P90 warning *is* a
genuine exhaustion marker, landing after ≥90% of final MFE more than half the
time. But the giveback happens *before* the warning — a median 0.953 ATR is
already gone when it fires — so there is nothing left to protect. The 0.89 ATR
pool is real, and it is not reachable by any exit rule that triggers on
deterioration, because deterioration *is* the giveback.

**Where that leaves the program.** Recovering this pool requires acting before
deterioration is observable, which means either a signal that leads the peak
rather than marking it, or scaling out on favourable excursion rather than exiting
on adverse. Neither is an exit-timing rule, and neither is reachable with the
current frozen contract.
