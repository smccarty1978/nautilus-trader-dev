# PHASE C — FROZEN 2024 REPLICATION
`nq_va_multitf_trade_state_geometry` · replication year 2024 · discovery year 2023 frozen at `3716a016` · 2025/2026 untouched

**Frame:** the v4 2024 TRAIN partition `_work/controller/partitions/train/2024`.
- seal `ba69ad0b…1ec1` · plan `11fcaf24…e557` · closure `c9249f99…8356`
- observations sha256 `b19c9a04…d7cf` · candidates sha256 `2bf309b7…f74d`
- Both hashes were verified against the partition manifest, and the manifest `year` = 2024.
- 7,060 T0 trades; **7,047 have a resolved terminal**. 13 are excluded: 9 terminal flips censored at SESSION_END, 4 exit fills unavailable.

**Guard (all four passed, nothing bypassed):**
1. The replication contract is committed.
2. `phase_c_atlas_2023.py` and `replication_readout.py` are committed.
3. All three are unmodified against HEAD `3716a016` (`git ls-files` + `git diff --quiet HEAD`).
4. `load_frame(2024)` matched the plan, seal and closure against the manifest, both parquet hashes, a 1:1 join with no loss, and CT-year = {2024} for every row.

**Artifacts**
| file | content |
|---|---|
| `artifacts/phase_c_2024_replication_readout.json` | the frozen readout's own output, verbatim |
| `artifacts/phase_c_2024_replication_results.json` | the readout verbatim, plus the supplementary descriptive readout and its 2023 comparators |
| `analysis/phase_c_2024_supplement.py` | the supplement generator (see below) |

**About the supplement.** It was written *after* the verdict existed.
- It re-applies the frozen atlas section functions to 2024, with archetypes classified at the frozen 34 s edge.
- It does **not** re-bucket anything whose edges were 2023 within-year quantiles: the s3/s4 quintiles, the 1h named contrast, the s6 terciles, the current-pnl quintiles and the s11 quintile spreads.
- It changes no verdict.

Units: A = `atr_entry_1m`. All PnL is **gross**; no cost contract exists.

---

## 1. EXECUTIVE SUMMARY
**Overall frozen verdict: `PARTIAL_REPLICATION`.**
- 10 of 11 primary claims PASS.
- The only non-PASS is **C7 (core), PARTIAL**: 7 of 69 post-entry state cells had |z| > 2, a share of 0.101 against a PASS limit of 0.10.
- No core claim FAILED.
- Secondary claim C11 is PARTIAL.

What replicated, in plain terms:
- **Break-even, tail-dependent flip-to-flip gross.**
  - Mean +0.042A (SE 0.030), against −0.031A (SE 0.028) in 2023.
  - Outside the top 5% the mean is −0.36A (2023: −0.41A).
  - The top 5% sum to +2,687A (2023: +2,698A).
- **The opposite-flip exit realizes the adverse extreme.**
  - For trades that never reach +2A, Spearman(pnl, −MAE rung) = 0.905 (2023: 0.895), and mean(pnl + MAE rung) = +0.017A.
  - 95.7% of those trades end negative.
- **Static T0 5m/15m/1h state and current-regime geometry separate lifecycle outcomes weakly.**
  - Across 52 HTF features: max |ρ| with pnl 0.030, max |AUC − 0.5| 0.037 for rapid failure and 0.012 for reaching +3A.
  - The only nominally distinct 2023 MTF cell (1h opposed, 5m+15m aligned: −0.22A) **reversed sign** in 2024 (+0.07A).
- **The post-entry path is informative about adverse-risk magnitude but not about expected remaining PnL.**
  - AUC for eventual −1A rises from 0.60 at s = 15 to 0.685 at s = 120. The best T0 feature reaches only |AUC − 0.5| = 0.056.
  - Mean remaining gross from every checkpoint is +0.04 to +0.06A (SE ≈ 0.03), which matches the year mean of +0.042A.
- **Runner optionality replicated.**
  - Of eventual +5A runners, 32.6% reach −0.5A before +0.5A (2023: 34.5%).
  - 48.8% reach −0.5A at some point before +5A (2023: 50.7%).
  - 19.9% reach −1A before +5A (2023: 22.2%).
- **Archetypes replicated:**
  - essentially no quiet stagnation (4 trades, 0.06%);
  - time to −0.5A has a unimodal (continuum) shape;
  - the 35%-ish adverse-first rate appears in every developed and runner class;
  - T0 separability of archetypes is ≤ 0.057.

**Synthesis:** 2024 **supports** decomposing future flip management into post-entry lifecycle problems rather than a T0 entry-quality classifier. §10 and §12 give the conceptual next target and the caveat that C7 imposes.

---

## 2. FROZEN CLAIM SCORECARD
The verdict bands are copied from `artifacts/phase_c_2024_replication_contract.yaml`, and the 2024 values from `phase_c_2024_replication_readout.json`.

| claim | statistic | 2023 discovery | frozen PASS / PARTIAL | 2024 | N (2024) | verdict |
|---|---|---|---|---|---|---|
| **C1** break-even | mean pnl (session-day-clustered SE) | −0.031 (0.028) | \|mean\| ≤ 0.15 / ≤ 0.30 | **+0.042 (0.030)** | 7,047 | **PASS** |
| **C2** ladder asymmetry | per-A continuation fav 1→1.5, 1.5→2, 2→3, 3→4, 4→5; adv 1→1.5, 1.5→2 | fav .626 .626 .651 .681 .673; adv .298 .186 | all fav in [.55, .78] AND all adv ≤ .40 / either half | fav **.634 .648 .668 .678 .699**; adv **.295 .200** | 7,047 | **PASS** |
| **C3** exit at MAE *(core)* | Spearman(pnl, −MAE rung); mean(pnl + MAE rung), MFE < 2A | 0.895; +0.012A (n 4,723) | ρ ≥ .80 AND \|mean\| ≤ .25 / ρ ≥ .70 | **0.905; +0.017A** | 4,348 | **PASS** |
| **C4** tail dependence | mean outside top 5%; top-5% sum; total | −0.412; +2,698 vs −230 | mean_rest ≤ −.25 AND top sum > 0 / mean_rest < 0 | **−0.357; +2,687 vs +297** | 7,047 (top 352) | **PASS** |
| **C5** HTF null *(core)* | over 52 HTF features: max \|ρ\| pnl; max \|AUC−.5\| rapid failure; runner ≥ 3A | .021; .025; .014 | ≤ .06; ≤ .05; ≤ .05 / ρ ≤ .10 and both ≤ .08 | **.030; .037; .012** | 7,047 | **PASS** |
| **C6** entry extension scales both tails | AUC(ext, MAE ≥ 2A); AUC(ext, MFE ≥ 3A); ρ(ext, pnl) | .626; .547; −.036 | ≥ .58; ≥ .52; \|ρ\| ≤ .08 / AUC severe ≥ .55 | **.647; .550; −.049** | 7,047 | **PASS** |
| **C7** remaining gross ≈ 0 *(core)* | mean rem_pnl at s = 30/60/120/285; share of cells (n ≥ 100) with \|z\| > 2 | \|mean\| ≤ .026 at every s; 2/72 (2.8%) | every \|mean\| ≤ .15 AND share ≤ .10 / every \|mean\| ≤ .15 AND share ≤ .20 | **+.036 / +.039 / +.037 / +.057** (SE .030/.030/.030/.034); **7/69 (10.1%)** | 6,779 / 6,678 / 6,309 / 4,920 alive | **PARTIAL** |
| **C8** −1A loser identifiable only after entry | best T0 \|AUC−.5\|; path AUC s = 15; s = 120 | .052; .603; .696 | T0 ≤ .07 AND AUC120 ≥ .65 AND AUC120 > AUC15 / AUC120 > AUC15 | **.056; .602; .685** | 7,047; 6,711; 5,009 at risk | **PASS** |
| **C9** archetype prevalence | STAGNANT; HELD; GIVEBACK; RUNNER_5PLUS; FAILURE | 0.1%; 1.6%; 33.2%; 11.0%; 24.6% | < 1; < 5; [25, 40]; [7, 15]; [20, 30] / ≥ 4 of 5 | **0.06%; 1.8%; 32.3%; 12.1%; 24.2%** (5/5) | 7,047 | **PASS** |
| **C10** archetypes not T0-separable | max \|AUC−.5\| FAILURE_RAPID / RUNNER_3_5 / RUNNER_5PLUS / GIVEBACK | .061 / .036 / .061 / .019 | all ≤ .08 / all ≤ .12 | **.037 / .036 / .057 / .030** | 7,047 | **PASS** |
| **C12** runners born in the same HTF geometry | \|Δ median 1h loc\|; \|Δ all-aligned share\| (MFE ≥ 3A vs all) | .005; .010 | both ≤ .03 / both ≤ .06 | **.007; .005** | 1,803 vs 7,047 | **PASS** |
| C11 *(secondary, not in verdict)* | Δ vs population: 1h-opp/5m+15m-aligned; all-aligned | −0.191 (SE .084, n 634); +0.102 (SE .065, n 1,586) | both signs / one sign | **+0.026 (SE .113, n 579); +0.137 (SE .068, n 1,486)** | — | PARTIAL |

**Verdict rule:**
- REPLICATED requires all 11 primary claims to PASS.
- PARTIAL requires ≥ 9 PASS and no core claim FAILING.
- 2024 has 10 PASS and 1 PARTIAL (C7, core), so the result is **PARTIAL_REPLICATION**.

**C7 as frozen.** It misses PASS by one cell: 7/69 = 0.1014 against a limit of 0.10. The four whole-population remaining means are all inside the ±0.15A PASS band. The descriptive context is in §5 and does not change the verdict.

---

## 3. BASELINE LIFECYCLE REPLICATION
Source: `supplement.population` and `supplement.milestones`.

**Terminal gross (A):**

| | p1 | p5 | p25 | p50 | p75 | p95 | p99 | max | mean (SE) |
|---|---|---|---|---|---|---|---|---|---|
| 2023 (n 7,475) | −3.33 | −2.25 | −1.39 | −0.73 | +0.61 | +4.47 | +8.45 | +37.8 | −0.031 (.028) |
| 2024 (n 7,047) | −3.15 | −2.22 | −1.35 | −0.70 | +0.68 | +4.69 | +9.04 | +52.4 | +0.042 (.030) |

- Win (> +0.25A) 30.3% (2023: 29%); loss (< −0.25A) 61.4% (2023: 62%).
- Duration: p50 585 s (same as 2023), p90 1,845 s. 3.0% exit after 15:15 CT (2023: 2.8%).
- A is larger in 2024: median 10.14 pts (2023: 8.55), p95 21.4 pts. Every quantity here is in A, so the level shift is normalised away.
- **Long/short.**
  - 2024: long +0.074 (SE .041, n 3,521); short +0.010 (SE .047, n 3,526).
  - 2023: long +0.043; short −0.105.
  - The 2023 short deficit did not recur. As declared in 2023, no side claim is made.

**In-lifecycle milestone incidence** (P reached, 2024, with 2023 in parentheses):

| +0.25 | +0.5 | +1 | +2 | +3 | +5 | −0.25 | −0.5 | −1 | −2 | −3 |
|---|---|---|---|---|---|---|---|---|---|---|
| .870 (.860) | .758 (.753) | .597 (.588) | .383 (.368) | .256 (.240) | .121 (.110) | .897 (.903) | .793 (.801) | .557 (.571) | .135 (.135) | .026 (.027) |

- **Symmetric races are still coin flips.** ±0.25: .52/.48; ±0.5: .51/.49; ±1: .50/.45.
- **The ladder shape (C2) replicated.** Favorable per-A continuation rises slightly, .63 → .70 from +1 to +5A. Adverse continuation collapses past −1A: .295, then .200.

---

## 4. STATIC MTF GEOMETRY REPLICATION
Source: C5, C12, C11, `supplement.mtf_direction`, `supplement.information_map_family_summary`, and `supplement.htf_per_series_spearman_range`.

**The claim being tested is exactly the 2023 claim.** Static *current-regime* 5m/15m/1h state and geometry at entry did not materially separate lifecycle outcomes on the tested surface. This is *not* the claim that "MTF information has no value."
- **Prior-regime geometry at 15m/1h, and prior-regime price levels at any timeframe, were never in the frame. They remain untested** (§13).
- Prior-5m regime shape was included and is null again: max |ρ| 0.019.

**Strongest frozen association (C5).**
- 52 HTF features, n 7,047.
- max |Spearman(x, pnl)| = **0.030**.
- max |AUC − 0.5| = **0.037** for FAILURE_RAPID and **0.012** for MFE ≥ 3A.
- All are PASS in both years.
- Across the 72 (TF × variable × relation) series the Spearman correlation lies in [−0.054, +0.045] (2023: [−0.036, +0.031]).

**Directional configuration table** (pooled; 5m/15m/1h relative to the new 1m flip; A = aligned, O = opposed):

| config | n 2024 | share | mean A 2024 (SE) | mean A 2023 (SE) | P(+3A) 2024 | P(−2A) 2024 | early fail 2024 |
|---|---|---|---|---|---|---|---|
| A A A (all aligned) | 1,486 | .211 | +0.179 (.068) | +0.071 (.065) | .262 | .129 | .373 |
| A A O (5m+15m aligned, 1h opposed) | 579 | .082 | +0.069 (.113) | **−0.222 (.084)** | .257 | .136 | .406 |
| A O A | 227 | .032 | −0.018 (.172) | +0.012 (.137) | .225 | .150 | .326 |
| A O O | 542 | .077 | +0.116 (.136) | −0.103 (.105) | .271 | .120 | .411 |
| O A A (1h+15m aligned, 5m opposed) | 879 | .125 | +0.024 (.080) | −0.062 (.069) | .234 | .140 | .341 |
| O A O | 358 | .051 | −0.153 (.108) | −0.031 (.116) | .249 | .148 | .416 |
| O O A | 880 | .125 | −0.044 (.075) | +0.015 (.076) | .245 | .130 | .359 |
| O O O (all opposed) | 2,096 | .297 | +0.002 (.053) | −0.042 (.054) | .265 | .141 | .382 |

- The runner rate is .225–.271 in every configuration, and the early-failure rate .326–.416. That is the same band as 2023 (.22–.26 / .35–.42).
- **Counting aligned HTFs (0/1/2/3):**
  - 2024: +0.002 / −0.018 / +0.034 / +0.179.
  - 2023: −0.04 / −0.03 / −0.11 / +0.07.
  - The pattern is not monotone in either year.
- **Long/short diagnostics** are in the artifact (`mtf_direction.rows`, side = LONG/SHORT) and are noisier. For example, A A O is LONG +0.25 (SE .18) and SHORT −0.11 (SE .12). No side-specific claim was frozen, and none is made.

**C11 (secondary).**
- The 2023 "1h opposed, 5m+15m aligned" deficit **did not replicate**: −0.22 became +0.07, a delta of +0.03 vs the population (SE 0.11). This supports the 2023 reading that it was the most extreme of 8 noisy cells.
- The "all aligned above the population" half held: +0.137, SE 0.068, about 2 SE.
- That is the second year in which all-aligned is the highest n-aligned bucket. It is a weak mean shift (+0.10 / +0.14A) with no change in runner rate or early-failure rate, and it is not verdict-bearing. It is recorded under §11 *New observations* and is **not** evidence for an entry filter.

**C12.** Runners (MFE ≥ 3A, n 1,803) versus all trades:
- median 1h location 0.743 vs 0.736;
- all-aligned share 21.6% vs 21.1%;
- median 1h MFE is in the artifact (`runners.baseline`: 3.56 A1h for all trades).
- Runners are again born in the population's HTF geometry.

**Family maxima** (information map, 2024): every 5m/15m/1h maturity, geometry, alignment and prior-5m family has |ρ| ≤ 0.030 and |AUC − 0.5| ≤ 0.042 on every target. The only family above noise is **1m state/path**: MAE ≥ 2A |AUC − .5| = 0.147 (2023: 0.136), which is entry extension (C6).

---

## 5. POST-ENTRY STATE REPLICATION
Source: C7, C8, `supplement.post_entry`.

The distinction the ensemble hypothesis rests on replicated:

| | PREDICTING PATH / RISK MAGNITUDE | PREDICTING EXPECTED REMAINING PnL |
|---|---|---|
| **2023** | AUC(eventual −1A) 0.55 at T0 → 0.60 (s15) → 0.70 (s120); for −2A 0.63 → 0.76 | mean remaining ≤ 0.026A from every s; 2/72 cells with \|z\| > 2 |
| **2024** | AUC(eventual −1A) 0.556 at T0 → **0.602 (s15) → 0.685 (s120)**; for −2A 0.647 → **0.748** | mean remaining **+0.036 to +0.057A** (SE ≈ .03; year mean +0.042); **7/69 cells** with \|z\| > 2 |

**Identifiability of eventual −1A** (best path signal among trades alive and not yet at −1A):

| stage | 2024 MAE-so-far AUC | 2024 60s-giveback AUC | 2023 (MAE / giveback) | n at risk 2024 |
|---|---|---|---|---|
| T0 (best T0 feature: flip-bar MFE / entry ext) | .556 | — | .552 | 7,047 |
| s = 15 | .602 | .598 | .603 / .610 | 6,711 |
| s = 30 | .635 | .650 | .646 / .657 | 6,526 |
| s = 60 | .665 | .636 | .676 / .657 | 5,948 |
| s = 120 | .685 | .627 | .696 / .624 | 5,009 |

**Worst current-pnl decile at s = 60, target −2A** (per-year decile, frozen construction):
- It holds **27%** of the eventual −2A events at risk (2023: 28%) and **4.4%** of the future +3A runners (2023: 4.5%).
- By then it is already at ≤ −0.75A.

**Remaining-PnL side (C7).**
- Spearman(current pnl, remaining pnl) is −0.048 to −0.061 at s = 30–285 (2023: −0.04 to −0.08).
- The seven |z| > 2 cells are listed in `post_entry.c7_cells_abs_z_gt_2`:
  - 5 positive, including MFE ≥ 2A with no adverse at 285 s: +0.26 (SE .12);
  - 2 negative: MFE .25 / MAE .75 at 120 s, −0.23 (SE .11); and MFE .25 / MAE ≥ 1 at 285 s, −0.20 (SE .075).
- **None of the 2023 flagged cells recurs.** The 2023 cell "MFE 0, MAE ≥ .75 at 120 s" (−0.28, SE .075) is **+0.16 (SE .12)** in 2024. The 2023 positive cell "MFE .5, MAE ≥ 1 at 285 s" (+0.30) is **−0.00** in 2024.
- The cells are tested against 0, not against the year mean. The 2024 year mean is +0.042A, and five of the seven flags are positive.

These are descriptive facts beside the frozen PARTIAL. No re-test was run and the verdict is unchanged.

**Scenario states** (2024; 2023 values are in `PHASE_C_2023_ATLAS_REPORT.md` §8):

| state | s | n (share alive) | remaining mean A (SE) | P(future +3A) | P(future −1A) |
|---|---|---|---|---|---|
| −0.25A within 30 s | 30 | 3,638 (.54) | +0.04 (.04) | .23 | .64 |
| +0.25A within 30 s (reference) | 30 | 3,814 (.56) | +0.02 (.04) | .30 | .47 |
| +1A within 60 s | 60 | 976 (.15) | +0.05 (.10) | .45 | .28 |
| +1A within 120 s | 120 | 1,824 (.29) | +0.06 (.07) | .43 | .23 |
| MFE ≥ .75, back within ±.25 of E | 120 | 401 (.06) | −0.07 (.11) | .23 | .54 |
| little progress (MFE < .5 & MAE < .5) | 120 | 357 (.06) | +0.11 (.11) | .21 | .45 |

- **+1A within 60 s** is again the strongest runner-formation state: 67.5% reach +2A and 47.4% reach +3A.
- It is also again a giveback state: **46.6% end ≤ 0** and 71.7% end below half their rung (2023: 45% / 72%).

---

## 6. RUNNER OPTIONALITY
Source: `supplement.runner_optionality`. This uses the frozen s9 construction: the highest adverse rung reached strictly before the trade first reaches its favorable rung, which is a ladder lower bound. **No stop is optimised from these numbers.**

**Eventual +5A runners** — fraction whose lifecycle reached the adverse rung *before first reaching +5A*:

| adverse rung reached before +5A | 2023 (n 821) | 2024 (n 854) |
|---|---|---|
| −0.25A | 72.4% | 71.0% |
| −0.50A | 50.7% | 48.8% |
| −0.75A | 34.6% | 32.1% |
| −1.00A | 22.2% | 19.9% |
| *adverse-first flag: −0.50A before +0.50A* | *34.5%* | *32.6%* |

**About the 2023 "≈35%" figure.** It is the adverse-first flag in the last row (−0.5A reached *before +0.5A*). It replicated at 32.6%.
- The broader quantity, −0.5A touched at any point before the +5A rung, is about 49–51% in both years.

**The same construction for the +3A population** (2024 n 1,803; 2023 n 1,792):

| | −0.25A | −0.50A | −0.75A | −1.00A | adverse-first flag |
|---|---|---|---|---|---|
| 2023 | 71.9% | 50.2% | 33.3% | 21.1% | 34.7% |
| 2024 | 71.1% | 47.9% | 31.3% | 19.2% | 32.1% |

**The runners are also not early.**
- The median +3A takes 563 s and the median +5A 908 s (2023: 571 / 935 s).
- MFE ≥ +3A trades carry +5,509A of gross (2023: +5,442A), and MFE ≥ +5A trades carry +4,231A.

---

## 7. RAPID-FAILURE / LEFT-TAIL REPLICATION
Source: `supplement.post_entry.failure_populations`, C8, C9.

| population | n 2024 | freq (2023) | mean A | median s to rung | MFE before = 0 | P(end > 0) | P(later +2A) | median entry ext A |
|---|---|---|---|---|---|---|---|---|
| MAE ≥ −0.5A | 5,591 | .793 (.801) | −0.48 | 59 | 41% | .206 | .230 | 0.88 |
| MAE ≥ −1A | 3,925 | .557 (.571) | −0.99 | 139 | 35% | .111 | .132 | 0.92 |
| MAE ≥ −2A | 954 | .135 (.135) | −1.92 | 239 | 38% | .056 | .082 | 1.12 |
| MAE ≥ −3A | 185 | .026 (.027) | −2.90 | 262 | 31% | .043 | .059 | 1.33 |

- **Entry extension again rises with loss depth:** 0.88 → 0.92 → 1.12 → 1.33A (2023: 0.88 → 0.92 → 1.10 → 1.38). This is the scale effect in C6.
- HTF state matches the population: 1h location .71–.75 and all-aligned share .15–.21.
- **FAILURE_RAPID versus FAILURE_SLOW** (frozen 34 s edge):
  - rapid: −1.73A mean, n 825;
  - slow: −1.45A mean, n 877;
  - median time to the first −0.25A is 8 s vs 25 s (2023: 7 s vs 24 s).
- **The 2024 median time to −0.5A in the failure group is 36 s.** It is recorded and was **not** used; the frozen 34 s edge was applied.

---

## 8. TERMINAL GIVEBACK / LOSS REALIZATION
Source: C3, C4, and `supplement.runners.contribution_by_lifecycle_mfe_rung`.

**Non-runners (MFE < +2A, n 4,348).**
- Spearman(pnl, −MAE rung) = **0.905**, against the frozen 2023 value of 0.895.
- Mean(pnl + MAE rung) = **+0.017A** (2023: +0.012A).
- 95.7% end negative.
- The opposite-flip exit fires at, and **realizes**, the lifecycle adverse extreme. Waiting for the opposite flip again turns essentially all accumulated adverse excursion into terminal PnL.

**Where the gross goes, by lifecycle MFE rung (2024, sum A):**

| MFE rung | 0 | .25 | .5 | .75 | 1 | 1.5 | 2 | 3 | 4 | 5+ |
|---|---|---|---|---|---|---|---|---|---|---|
| n | 918 | 788 | 625 | 506 | 857 | 654 | 896 | 581 | 368 | 854 |
| sum A | −1,520 | −1,184 | −843 | −601 | −823 | −327 | +85 | +583 | +695 | +4,231 |

- Trades that never reach +2A (62%) cost **−5,298A** (2023: −5,794A). Trades that reach +5A (12%) return **+4,231A** (2023: +4,036A).

**Favorable giveback.**
- DEVELOPED_GIVEBACK (+1–3A MFE, terminal < ½ rung) is again the modal archetype: 32.3%, mean −0.54A.
- 43.7% of MFE ≥ +1A trades end ≤ 0 (2023: 44%).
- The median capture of the rung is 0.28 from +1A, 0.67 from +2A, 0.79 from +3A and 0.86 from +5A (2023, from +3A/+5A: 0.81/0.85).

---

## 9. ARCHETYPE REPLICATION
Source: C9, C10, `supplement.archetypes`. Frozen classifier, RAPID_EDGE 34 s.

| archetype | n 2024 | share 2024 (2023) | mean A | median | p5 / p95 | median dur s | adverse-first | sum A |
|---|---|---|---|---|---|---|---|---|
| STAGNANT_QUIET | 4 | 0.06% (0.1%) | — | — | — | — | — | — |
| FAILURE_RAPID | 825 | 11.7% (12.5%) | −1.73 | −1.64 | −2.89 / −0.95 | 225 | 1.00 | −1,431 |
| FAILURE_SLOW | 877 | 12.4% (12.1%) | −1.45 | −1.35 | −2.41 / −0.75 | 225 | 1.00 | −1,272 |
| SHALLOW_FADE | 784 | 11.1% (10.6%) | −1.29 | −1.21 | −2.40 / −0.48 | 345 | 0 | −1,012 |
| SHALLOW_RECOVERED | 347 | 4.9% (5.9%) | −1.24 | −1.17 | −2.35 / −0.46 | 525 | 1.00 | −432 |
| DEVELOPED_GIVEBACK | 2,278 | 32.3% (33.2%) | −0.54 | −0.49 | −1.87 / +0.63 | 645 | .34 | −1,227 |
| DEVELOPED_HELD | 129 | 1.8% (1.6%) | +1.25 | +1.17 | +0.80 / +1.85 | 1,425 | .33 | +162 |
| RUNNER_3_5 | 949 | 13.5% (13.0%) | +1.35 | +1.40 | −0.41 / +2.95 | 1,245 | .32 | +1,278 |
| RUNNER_5PLUS | 854 | 12.1% (11.0%) | +4.95 | +4.28 | +1.23 / +10.8 | 1,905 | .33 | +4,231 |

Against the four questions:
- **Essentially no quiet stagnation population.** Yes: 4 trades (0.06%), and the LONG_QUIET flag is 0.17%.
- **Rapid versus slow failure is a continuum, not clean clusters.** Yes.
  - The log10 time to −0.5A, on the 2023 histogram edges, has a single broad mode at about 40–60 s. The counts are 6, 21, 33, 33, 121, 207, 292, 383, 518, 507, **663**, 604, 543, 477, 436, 320, 250, 127, 39, 9, with the same small ripple as 2023.
  - Rapid and slow have near-identical duration (225 s) and differ by 0.28A in mean.
- **Substantial adverse excursion among eventual large runners.** Yes.
  - The adverse-first flag is 32–33% in every developed and runner class, against 35–36% in 2023.
  - 48.8% of +5A runners touch −0.5A before +5A (§6).
- **Weak T0 separation among lifecycle archetypes.** Yes. Max |AUC − 0.5| is 0.037 / 0.036 / 0.057 / 0.030 for FAILURE_RAPID / RUNNER_3_5 / RUNNER_5PLUS / GIVEBACK (C10 PASS).

---

## 10. ENSEMBLE HYPOTHESIS — SUPPORTED OR NOT SUPPORTED
**SUPPORTED by 2024** under the frozen verdict of PARTIAL_REPLICATION, with one qualification carried from C7.

| question | 2024 evidence | answer |
|---|---|---|
| **A. ENTRY QUALITY** — can static T0 information distinguish lifecycle outcomes? | C5, C10 and C12 PASS. The HTF families are at noise (≤ .037 AUC dev), and the one distinct 2023 MTF cell reversed. The only T0 structure is 1m entry extension, which scales **both** tails (C6: AUC .647 for −2A, .550 for +3A, ρ with pnl −.049). | **No meaningful T0 separation of outcome.** T0 carries *scale* information (extension), not *sign*. |
| **B. EARLY / THESIS FAILURE** — does the path reveal increasing information about destructive adverse outcomes? | C8 PASS: −1A AUC .60 → .685 from s15 to s120, and −2A .62 → .75. The worst decile at 60 s holds 27% of the −2A events and 4.4% of the +3A runners. | **Yes, increasingly with time.** The information is about **magnitude/risk**, not about remaining drift. Under the untreated exit, mean remaining PnL is ≈ year mean from every state (C7, frozen PARTIAL). |
| **C. RUNNER PRESERVATION** — do large runners commonly take enough early adversity that aggressive early controls would destroy right-tail optionality? | 32.6% of +5A runners go −0.5A before +0.5A. 48.8% touch −0.5A and 19.9% touch −1A before +5A. The +5A class is 12% of trades and carries +4,231A against a +297A total. | **Yes.** Any adverse cut at ≤ 1A intersects ~20–50% of eventual +5A runners. |
| **D. GIVEBACK / TERMINAL LOSS REALIZATION** — does the opposite-flip exit again let accumulated adverse excursion or favorable giveback become terminal PnL? | C3 PASS (ρ .905; terminal = MAE rung +0.017A; 95.7% negative below +2A). GIVEBACK is 32.3% of trades; 43.7% of +1A trades end ≤ 0; a fast +1A still ends ≤ 0 46.6% of the time. | **Yes, in both directions.** The flip exit realizes the adverse extreme and gives back most sub-+3A favorable excursion. |

**Qualification (C7).** The post-entry path predicts *where the barriers are*, not *the expected PnL from here*.
- A thesis-failure head therefore has no free lunch in the untreated data. Its value, if any, comes from **changing the path** (a treated exit), which must be evaluated as a treated-path study with a matched placebo.
- Its payoff may be variance and left-tail reduction rather than mean.
- This is the 2023 conclusion, and 2024 does not overturn it.

---

## 11. DISCOVERY VS REPLICATION DIFFERENCES

### Frozen replication results (verdict-bearing)
- The overall verdict is **PARTIAL_REPLICATION**, versus REPLICATED in the 2023 self-test.
- **C7: share of |z| > 2 cells rose from 2/72 (2.8%) to 7/69 (10.1%)** against a 0.10 PASS limit. This is the only primary non-PASS. The whole-population remaining means stayed well inside ±0.15A.
- C11 (secondary) moved from PASS to PARTIAL: the 1h-opposed / LTF-aligned cell reversed sign.
- Every other primary claim moved by at most a few hundredths:
  - C3 ρ .895 → .905;
  - C5 max ρ .021 → .030;
  - C6 AUC .626 → .647;
  - C8 AUC120 .696 → .685;
  - C9 shares within ±1.1 pp;
  - C10 RUNNER_5PLUS separability .061 → .057.

### Differences that do not change any verdict
- The mean gross changed sign (−0.031 → +0.042A); both are within about 1.4 SE of zero. The top-5% sum is nearly identical (+2,698 → +2,687A), so the total went from −230 to +297A.
- The 2023 short-side deficit (−0.105) did not recur (short +0.010, long +0.074).
- A (1m ATR) is about 19% larger in 2024 (median 10.1 vs 8.55 pts). All outcomes are A-normalised.
- The +5A rate rose slightly: 11.0% → 12.1%.

### New observations that require future study (NOT investigated here)
1. **The C7 flagged cells do not recur across years, and two 2023 flags reversed sign.** The cell test is against 0, not the year mean, and 2024's year mean is +0.042A. Whether the state-conditional remaining-PnL grid needs a year-mean-centred or multiplicity-aware test is a question for a *future contract*. It cannot re-grade this one.
2. **"All HTF aligned" is the highest n-aligned bucket in both years.** It sits +0.10A (2023) and +0.14A (2024) above the population, each about 1.6–2.0 SE, with no change in runner or early-failure rate. It is a weak mean shift of a kind that has not survived elsewhere in this program. It is **not** a filter candidate from this study; any test needs a fresh pre-registered year.
3. **Long/short MTF cells swing by up to ±0.35A between years** (e.g. A A O LONG +0.25 / SHORT −0.11 in 2024). This is consistent with noise at n ≈ 100–300 per side-cell, and no claim was made either way.

---

## 12. WHAT SHOULD BE STUDIED NEXT
Conceptual only; no model is designed here. The premises of the expected decision tree replicated:
- static T0 MTF geometry again gives little separation (C5, C10, C12 PASS; the only distinct 2023 cell reversed);
- the post-entry path predicts adverse-risk *magnitude* (C8 PASS);
- large runners commonly survive meaningful early adverse excursion (§6).

**Recommendation.** The next study should **not** be another entry-filter study on static HTF current-regime state. The next research problem is **DYNAMIC TRADE-STATE / THESIS-FAILURE MANAGEMENT, with runner preservation as a hard constraint.**
- It is a *treated-path* problem: it asks what a path-changing intervention does. C7 shows the untreated state carries no drift, so a state-conditional mean cannot be the justification.
- It is judged on the full terminal distribution, including the tail, against a matched, length-blind placebo.
- It declares an explicit ceiling on the share of eventual +3A/+5A runners it may cut. It should also report the cost to runners of each alternative, because ~20% of +5A runners touch −1A first.
- The runner-development / giveback question (the +1–2A trades that the flip exit returns) is the second head. It belongs to the same lifecycle study family, not to entry.
- 2025 stays sealed until such a study has a frozen contract.

---

## 13. DEFERRED QUESTIONS
All of these remain deferred and were not touched here.
- **PRIOR_REGIME_LEVEL_SNAPSHOT.**
  - Prior 15m/1h regime geometry, and prior-regime price levels at any timeframe, are not in the frame.
  - They need platform/data work: a tracker-state snapshot of the prior regime's start/extreme prices and frozen ATR per timeframe.
  - They are potentially valuable and **untested**. The C5 null says nothing about them.
- **ANALYSIS_HARNESS_GAP.**
  - The atlas, the readout and this supplement are study-local Python, which conflicts with WORKFLOW §F.1.
  - This is already documented in `research_decision.yaml`, and the atlas was not rewritten during replication.
  - The supplement reuses the frozen atlas functions and adds no new analysis primitive.
- **ENTRY_TIMING.** T0 is the flip-bar close + 15 s, so E is the next 1s open after that. The cost of the 15 s delay is unmeasured.
- **COSTS.** Everything is gross, and no cost contract is declared. No net figure is reported or implied. A break-even gross mean is negative net.
- **Not re-read on 2024,** because their edges were 2023 within-year quantiles and re-bucketing them would be a new analysis:
  - the s3/s4 quintile tables and the 1h named contrast;
  - the s6 hierarchical terciles;
  - the s8 current-pnl quintiles;
  - the s11 quintile spreads;
  - the s5 prior-regime quintiles.
- **2025 and 2026 were not opened.**
