# P90 Edge by Regime Age × Realized Progress — Diagnostic Report

**Study:** `p90_regime_age_progress_diagnostic` · **Run:** 2026-08-13 · **Years:** 2021–2025, 2026 sealed
**Verdict:** `D3_YOUNGER_TRADES_BETTER` (primary), co-firing with `D4_AGE_PROGRESS_INTERACTION` and `D5_NOTHING_CHANGES`
**Gates:** 34/34 passed · **Tests:** 28 passed · **Population B parity:** 8,950 reproduced exactly

> **Correction applied before publication.** The first run pooled
> `STOPPED_BEFORE_CONFIRM` trades into three confirmer-denominated columns
> (`return_at_confirm`, `mae_to_confirm_*`, `seconds_to_confirm`) — `measure_to_confirm`
> populates those fields whenever the flip was *reached in the window*, even when the
> stop hit first, so the omission did not show up as a null. Raised as a CRITICAL by
> lookahead-auditor pass 2 after it had reached `primary_matrix.csv`. All figures below
> are the corrected, confirmers-only values, now enforced by gate `V-DENOM` — an
> independent recompute of **all 10** confirmer-denominated columns, plus a
> coverage gate and a unit test that feeds it a deliberately leaked table and requires
> it to fail. (Pass 3 raised a second CRITICAL: the gate initially covered only 4 of
> the 10, leaving `p_mfe_ge_3` — which feeds the primary verdict — unenforced. Values
> were already correct; the coverage was not.) **The verdict and the eventual-MFE and
> flip-rate findings are unchanged throughout** — those columns were always correctly
> denominated; the return, MAE and time-to-confirm figures moved.

---

## The answer, in one paragraph

**P90 is a stale-regime detector by construction, and its classification sweet spot is
not its economic sweet spot.** The model almost never fires in young regimes — not
because the inherited >600 s gate excluded them, but because the model's own score
rises ~180× with regime age. Where it *does* fire young, it is a **worse classifier
and a better trade**: `P(flip ≤ 300 s)` is 6.1 pp lower, but median eventual opposite
MFE is **+0.60 ATR** larger (2.901 vs 2.305), `P(MFE ≥ 3 ATR)` is **+10.8 pp** higher,
and return at confirmation is **+0.28 ATR** better (1.117 vs 0.833). Every one of those
differences excludes zero on a bootstrap and holds in **2/2 sides and 4–5 of 5 years**.
Young confirmations also take **75 s longer** (190 s vs 115 s median) — they are slower
to confirm and further-travelling, not faster. Dropping the >600 s gate,
however, changes almost nothing at the pooled level (it adds 239 of 9,189 arms), so the
inherited population was never the problem — **the model's own age preference is.**

---

## 1. Phase 0 — the original contract, verified

All four remembered eligibility values are **confirmed exactly** against
`studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/config.yaml`
and measured against the store. 16/16 contract rows verified.

| Contract item | Config | Observed in store |
|---|---|---|
| `age_min_seconds` | 120 | min in-domain age **125.0 s** |
| `running_mfe_min_atr` | 1.0 | **1.0000177** |
| `progress_windows_min` | 2 | **2** |
| `retained_mfe_ratio_min` | 0.5 | **0.5000** |
| `progress_gap_seconds` | 120 | (not per-row observable) |
| session | RTH `[08:30,15:00)` CT | **100 %** of in-domain rows |
| cadence | 5 s | 5 s |
| target | `(T, T+300s]` regime flip | reproduced exactly |
| `established_regime_gate` | implied | **True on 100 %** of in-domain rows |

`bullish_in_domain` ⟺ prevailing `+1` (fade SHORT), `bearish_in_domain` ⟺ prevailing
`−1` (fade LONG); overlap is **0 rows**. No model artifact was loaded anywhere in this
study; probabilities are read from the store as collected.

### Three discrepancies — recorded, not reconciled

**(a) `age_min_seconds: 120` but the realized floor is 125.0 s.** The 5 s grid with a
strict `> 120` gate. The first age bucket is labelled `120–240s` and is in fact
`125–240s`. Not widened, not re-optimised.

**(b) The store scores well past the training grid.** The config freezes
`checkpoint_grid: ...through_less_than_1800s`, but the store carries in-domain
checkpoints out to **8,760 s** — **430,767 of 2,205,823 (19.5 %)** at age ≥ 1800 s.
**12.3 % of the `>900s` bucket** is armed beyond the model's training age range. That
bucket is partly extrapolation and is flagged as such in every table
(`pct_age_ge_1800s`).

**(c) The 0.5–2 ATR progress bucket is NOT a contradiction.** Prior discovery's
`path_dev_0.5_2.0` buckets **`current_progress_atr`**, a different column from
`running_mfe_atr`. Eligibility gates `running_mfe_atr >= 1.0` **and**
`retained_mfe_ratio >= 0.5`, which jointly *imply* `current_progress_atr >= 0.5`.
Verified: min current progress **0.5004**, min implied retained ratio **0.5000**
exactly, and 27.5 % of in-domain checkpoints sit in `[0.5, 2.0]`. This study buckets
`running_mfe_atr`, so **no 0.5–1.0 bucket was manufactured**, per the brief.

---

## 2. The population fact that reframes the question

**The >600 s gate is barely a restriction. The model is what excludes young regimes.**

Eligibility admits young regimes freely — 1,818 regimes first become eligible at
120–240 s, 2,002 at 240–300 s, 7,559 at 300–600 s. But the **P90 qualify rate among
already-eligible checkpoints** climbs ~180×:

| age bucket | eligible checkpoints | P90-qualifying | **rate** |
|---|---:|---:|---:|
| 120–240 s | 11,700 | 12 | **0.10 %** |
| 240–300 s | 26,763 | 53 | **0.20 %** |
| 300–600 s | 319,805 | 2,452 | **0.77 %** |
| 600–900 s | 414,891 | 13,862 | **3.34 %** |
| > 900 s | 1,255,235 | 232,427 | **18.52 %** |

Dropping the gate moves the population from **8,950 → 9,189** arms. Only **593** arms
are excluded by it at all (581 strictly below 600 s, plus 12 at exactly 600.0 s). The
brief's two youngest cells hold **n = 5** and **n = 14** — and **no choice of age
boundary rescues them**, because that is the entire universe. The verdict tests
therefore use `300–600s` vs `>900s` as the age contrast; this substitution is forced
by the data, recorded in `summary.json`, and the thin cells are reported with their N
but barred from every inferential test.

**Population B is not a clean subset.** 8,596 regimes arm at the same timestamp in
both, **354 arm at a different (earlier) timestamp under A** — median age 507.5 s vs
707.5 s — 239 appear only in A, and **0** appear only in B.

---

## 3. Primary matrix — population A

`n` / `P(flip≤300s)` / `P(confirm before 1 ATR)` / median return at confirm / median
eventual MFE. Rates over all arms; return and MFE over **confirmers only**.

| AGE | 1–2 ATR | 2–3 ATR | 3–5 ATR | >5 ATR |
|---|---|---|---|---|
| **120–240s** | n=5 · .600 · .600 · 2.321 · 5.004 ⚠ | n=0 | n=0 | n=0 |
| **240–300s** | n=14 · .500 · .500 · 1.252 · 2.845 ⚠ | n=0 | n=0 | n=0 |
| **300–600s** | n=170 · .447 · .471 · **1.129** · **2.809** | n=215 · .409 · .507 · **1.011** · **2.674** | n=148 · .399 · .466 · **1.248** · **3.788** | n=29 · .414 · .483 · 1.244 · 2.212 ⚠ |
| **600–900s** | n=280 · .457 · .546 · 0.990 · 2.476 | n=848 · .491 · .527 · 0.926 · 2.297 | n=870 · .479 · .518 · 0.831 · 2.423 | n=202 · .446 · .515 · 0.911 · 2.130 |
| **>900s** | n=323 · .495 · .495 · 0.983 · 2.703 | n=1385 · .451 · .500 · 0.912 · 2.498 | n=2593 · .467 · .519 · 0.819 · 2.342 | n=2107 · .511 · .535 · 0.758 · 2.061 |

⚠ = thin cell (`n < 30`), excluded from every verdict test.

**The D3 pattern holds *within* progress strata, so it is not a progress confound.**
In 3 of 4 progress buckets (the 4th is thin), the `300–600s` cell has the **lowest**
`P(flip≤300s)` and the **highest** eventual MFE, and it has the **highest return at
confirmation in all four**. The `3–5 ATR` column is the sharpest: `.399 / 1.248 / 3.788`
young versus `.467 / 0.819 / 2.342` old.

A clean secondary gradient runs the other way: **within any age band, more realized
progress means a smaller reversal.** At `>900s`, median eventual MFE falls 2.703 →
2.498 → 2.342 → 2.061 as progress rises 1–2 → >5 ATR, and return at confirm falls
0.983 → 0.758.

---

## 4. The headline contrast, with uncertainty

`300–600s` (young) vs `>900s` (old), population A. Bootstrap 2,000 draws, seed
20260813, one row per event. *Supplementary robustness check, not a SPEC deliverable.*

| Metric | Young | Old | Δ | 95 % CI | |
|---|---:|---:|---:|---|---|
| `P(flip ≤ 300 s)` | .4181 | .4794 | **−0.0613** | [−0.1055, −0.0201] | excludes 0 |
| `P(confirm before 1 ATR)` | .4840 | .5189 | −0.0349 | [−0.0793, +0.0085] | **includes 0** |
| median return at confirm | 1.117 | 0.833 | **+0.2843** | [+0.1954, +0.3560] | excludes 0 |
| median eventual MFE | 2.901 | 2.305 | **+0.5952** | [+0.3167, +0.8708] | excludes 0 |
| `P(MFE ≥ 3 ATR)` | .4779 | .3699 | **+0.1080** | [+0.0441, +0.1699] | excludes 0 |
| median seconds to confirm | 190 s | 115 s | **+75.0 s** | [+50.0, +100.5] | excludes 0 |
| median MAE to confirm | 0.347 | 0.329 | +0.0185 | [−0.0367, +0.1052] | **includes 0** |

This is **exactly the shape you predicted**: the classifier is worse where the trade is
better. Two metrics do *not* separate, and both are informative. The confirmation
**rate** is flat — young regimes confirm about as often, they just travel further when
they do. And **MAE to confirmation is flat at ~0.33–0.35 ATR**, so the extra
opportunity is not bought with extra heat: young trades are not riskier to hold to
confirmation, they simply take **75 s longer** to get there.

### The duration artifact was checked and is ruled out

Eventual MFE is measured to the unconstrained terminal, so a longer available window
mechanically inflates it. That would be the obvious artifact here — and it goes the
**wrong way**:

| age bucket | median session time remaining at the arm | median eventual MFE |
|---|---:|---:|
| 300–600 s | **8,753 s** | **2.901** |
| 600–900 s | 9,933 s | 2.342 |
| > 900 s | **11,653 s** | **2.305** |

Young arms produce a **larger** eventual MFE from a **shorter** remaining session, and
the correlation between session time remaining and eventual MFE among confirmers is
**−0.079**. A mechanical-window explanation predicts the opposite sign, so it is
rejected.

---

## 5. Year / side stability

| Metric | Direction | Holds in |
|---|---|---|
| `P(flip ≤ 300 s)` young < old | as predicted | **5/5 years, 2/2 sides** |
| median return at confirm young > old | as predicted | **5/5 years, 2/2 sides** |
| median eventual MFE young > old | as predicted | **4/5 years** (2023 is a 2.340 vs 2.326 tie), **2/2 sides** |
| `P(MFE ≥ 3 ATR)` young > old | as predicted | 4/5 years (2023 reverses, .359 vs .389), **2/2 sides** |

2025 is the extreme case and is internally consistent with D3: the young cell's
`P(flip≤300s)` collapses to **.295** and its confirm rate to **.377**, yet it still
posts the *largest* return at confirm (**1.272**), an eventual MFE of **3.024** and
`P(MFE≥3)` of **.522**. Fewer, better.

Both sides carry it, with LONG the stronger: LONG young 1.225 return / 3.031 MFE /
.505 `P(MFE≥3)` versus LONG old 0.821 / 2.295 / .364; SHORT young 1.075 / 2.713 / .463
versus SHORT old 0.838 / 2.319 / .375.

---

## 6. Progress velocity — real, monotone, and small

Quartile edges frozen on population A: 0.160 / 0.212 / 0.284 ATR/min.

| quartile | n | median age | median MFE | median vel | `P(flip≤300s)` | `P(confirm)` | ret@confirm | eventual MFE | `P(MFE≥3)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Q1 slowest | 2,297 | 1,170 s | 2.37 | 0.131 | .4684 | .5120 | 0.901 | **2.448** | .3920 |
| Q2 | 2,297 | 1,025 s | 3.17 | 0.185 | .4872 | .5246 | 0.855 | 2.354 | .3710 |
| Q3 | 2,297 | 975 s | 3.98 | 0.243 | .4702 | .5146 | 0.849 | 2.311 | .3875 |
| Q4 fastest | 2,298 | 945 s | 5.67 | 0.352 | .4756 | .5218 | 0.857 | **2.243** | .3586 |

`median_eventual_mfe` orders **monotonically** across all four quartiles (D4 fires),
but the total spread is only **0.21 ATR** — a third of the age effect — while
`P(flip≤300s)` is **flat** (.468–.487, no ordering), `P(confirm)` is flat
(.512–.525), and return at confirm is flat after the first quartile (.901 then
.855/.849/.857, i.e. no ordering across Q2–Q4).

**This contradicts the stated hypothesis.** You expected P90 to work best where
velocity is low; instead velocity is **inert for the classifier**, and slow regimes
give *slightly bigger* reversals rather than smaller ones. Velocity is not the axis —
**age is**, and the two are largely orthogonal here (quartile median ages span only
945–1,170 s).

---

## 7. Population A vs B — the gate was never the problem

| | n | conf | med age | med MFE | med vel | `P(flip≤300s)` | `P(confirm)` | ret@confirm | eventual MFE | `P(MFE≥3)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A** (model domain) | 9,189 | 4,762 | 1,030 s | 3.55 | 0.212 | .4754 | .5182 | 0.868 | 2.348 | .3772 |
| **B** (>600 s) | 8,950 | 4,656 | 1,045 s | 3.62 | 0.209 | .4803 | .5202 | 0.854 | 2.329 | .3741 |

Pooled deltas: `P(flip≤300s)` **0.50 pp**, `P(confirm)` **0.20 pp**, eventual MFE
**0.019 ATR**, return at confirm **0.013 ATR**. `D5_NOTHING_CHANGES` fires. Removing
the inherited gate does **not**
change the population's character — it adds 239 arms to 8,950 and shifts every pooled
metric by less than a percentage point. **The >600 s restriction was not what was
hiding the young-regime opportunity; the model's own score distribution is.**

---

## 8. Verdict

`D3_YOUNGER_TRADES_BETTER` — **primary**. Co-firing: `D4_AGE_PROGRESS_INTERACTION`
(velocity monotone but small) and `D5_NOTHING_CHANGES` (A ≈ B pooled). All three are
simultaneously true and not contradictory: the gate changes nothing (D5) precisely
*because* the model rarely fires young, while the arms that *are* young trade better
(D3).

**What the P90 model is actually good at identifying:** imminent termination of **old,
extended regimes**. That is what it was trained to do and it does it — `P(flip≤300s)`
is highest in the oldest, most-extended cells (`>900s` × `>5 ATR`: .511). But those
terminations produce the **smallest** opposite moves in the entire matrix (median
eventual MFE 2.061, the lowest of all 20 cells).

**What we have been excluding is real but tiny.** The economically best cell in the
matrix is `300–600s × 3–5 ATR` — median eventual MFE **3.788**, nearly double the
worst cell — and it contains **148 arms across five years**. It is a genuine signal
sitting in a population too small to trade on its own.

---

## 9. Limits of this diagnostic

- The brief's `120–240s` and `240–300s` buckets are **unanswerable** at n=5 / n=14.
  The youngest usable evidence starts at 300 s.
- The `>900s` bucket is **12.3 % extrapolation** beyond the model's training age range.
- 2025 is **not** threshold-out-of-sample (both calibration populations are
  calendar-2025); the inherited waiver applies.
- `p_confirm` uses the conservative bound — a bar satisfying both the stop and the flip
  resolves adversely. `P(ambiguous)` is carried in `outcome2_confirmation.csv`.
- Nothing here is an exit policy, an entry rule, or a stop. No economics beyond the
  descriptive columns above were computed, by design.

## 10. What this does NOT authorise

Per SPEC §10, this study stops here. It does **not** start model retraining,
bucket-specific models, 5m-ATR normalisation, exit work, or stop optimisation.

If the next study is taken up, the evidence points at **regime maturity as a model
input, not a filter**: the classifier's age gradient (0.10 % → 18.52 %) is far steeper
than the actual base-rate gradient in `P(flip≤300s)` (.418 → .479), which is the
concrete sense in which the model is mis-calibrated toward age. Whether that is
correctable — and whether the ~150-arm young cells can be enlarged by a different
trigger rather than a different threshold — is the open question.
