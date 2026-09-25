# T0-segment path atlas — 2023 development sessions

**Verdict: `T0_SEGMENT_PATH_HETEROGENEITY_WEAK`.**

**Qualification:** there is **one** reproducible axis of heterogeneity: **runner share**. It is small and cannot
support segment-specific management or loss functions.
- **Failure mode does not differ by T0 segment.** That covers the quick-fail share, the slow-fail share and the
  shape of the duration distribution.
- **The post-entry state overwhelms the T0 segment by about an order of magnitude.**
- **Two T0 conditions shift runner share by 5–10pp in both blocks.** They are candidates for one controlled test.

**Scope.**
- **Data:** 6,024 trades from 205 development sessions (2023-01-03 → 2023-10-17). The final 20% of 2023 was
  never loaded (sessions come only from the audited timeline). 2024–2026 were not touched.
- **No model was fitted.**
- **Taxonomy:** the complete existing T0 taxonomy was used, not only the positive-lift buckets:
  - 16 exact MTF states;
  - 8 alignment codes;
  - side;
  - 51 one-dimensional structural bucket columns (341 buckets);
  - 263 state × structure cells (N ≥ 150 with rest-of-state ≥ 150).
- **Blocks:** heterogeneity is judged by effect size against a 60-shift circular-shift null (which preserves
  temporal clustering), and by replication of the same deviation in the development-train block (154 sessions)
  vs the development-validation block (51 sessions).

## Phenotype definitions

| phenotype | rule | share |
|---|---|---|
| QUICK_FAIL | MFE < 0.5A and terminal ≤ 225 s | 15.1% |
| SLOW_FAIL | MFE < 0.5A and terminal > 225 s | 9.8% |
| PARTIAL | 0.5A ≤ MFE < 2A | 38.2% |
| RUNNER | MFE ≥ 2A | 36.9% (≥1A: 58.6%, ≥3A: 23.9%) |

Train and validation mixes are identical within 1pp.

**Where the 225 s boundary comes from:** it was not chosen in advance.
- **Failure durations are unimodal.** A log-duration mixture prefers 1 component; BIC 3051 vs 3083 for 2.
- **So there is no natural gap.** The boundary is where the terminal hazard of still-undeveloped trades
  (running MFE < 0.5A) stops rising: 7.5% → 12.0% → 14.1% → 15.5% per minute at 45 / 105 / 165 / 225 s, then a
  flat 11–16%.
- **225 s is also exactly the median failure duration.**
- **Sensitivity:** 165 s and 345 s variants are in `PATH_ATLAS_SEGMENTS.parquet`; conclusions are unchanged.

## Answers

**1. How long do these trades live?**

T0 → terminal (s):

| P10 | P25 | P50 | P75 | P90 | P95 |
|---|---|---|---|---|---|
| 165 | 285 | 585 | 1065 | 1725 | 2205 |

- **The terminal hazard is nearly memoryless.** From minute 2 on, about 8% of the survivors flip in each minute
  (7–9%), out to 30 min.
- **Survival:** 79% at 225 s, 51% at 525 s, 24% at 1065 s.
- **Surviving longer does not raise or lower the flip risk.** Only price location does.

**2. Where is the natural separation between quick and slow failures?**
There is no gap. It is a continuum, with the hazard ramp ending at about 225 s.
- **Quick failures** reach their maximum MFE at a median of **7 s** and flip at a median of 165 s. They never go
  anywhere.
- **Slow failures** peak at a median of 34 s. They then drift 5 min (median) below entry before the flip: median
  duration 345 s, P90 705 s.

**3. Fractions:** see the table above.

Durations by phenotype:

| phenotype | median | P90 |
|---|---|---|
| partial | 465 s | 945 s |
| runner | 1215 s | 2385 s |

Runner timing:
- +2A arrives at a median of 358 s after T0 (P90 838 s).
- The maximum MFE comes at 828 s.
- The terminal flip follows the maximum MFE by 307 s (median).

For every phenotype, the gap between maximum MFE and the terminal flip is 128–307 s. That is the mechanical lag
of the flip exit.

**4. Do the fractions differ materially across T0 segments?**
Barely, and mostly not beyond chance.

| family | quick-fail range across segments | runner range | material flags vs circular-shift null |
|---|---|---|---|
| MTF state (16) | 13.0–17.8% (sd 1.6pp) | 32.3–43.9% (sd 2.8pp) | 0 vs ~0.1 on every phenotype |
| alignment code (8) | 12.9–15.9% | 32.4–41.5% | 0 vs ~0.05 |
| side | 14.3 / 15.9% | 37.8 / 35.9% | 0 |
| 1-D structure (341) | 8.2–21.3% | 30.4–50.6% | QF 6 vs 1.9 (p 0.03); runner 5 vs 3.3 (p 0.27); train/val rank correlation of QF deviations **−0.20** |
| state × structure (263) | 8.6–22.6% | 29.4–45.5% | **runner 17 vs 3.7 (p < 0.02); 15 vs 3.3 replicated; train/val ρ 0.26 vs null p95 0.24**; QF 4 vs 3.4, SLOW 7 vs 3.6, PARTIAL 4 vs 3.7 (all null-level) |

The spread across MTF states (runner sd 2.8pp) is about the binomial noise for N ≈ 400 (≈ 2.4pp).
Duration and chop replicate no better than the null:

| family | log-duration ρ (null p95) | crossings/min ρ (null p95) |
|---|---|---|
| 1-D structure | 0.15 (0.22) | 0.06 (0.14) |
| state × structure | 0.12 (0.24) | −0.17 (0.13) |

**5. Segments with unusually high QUICK-FAIL rates.**
Only one survives both blocks:

**Entry ≥ 2 1h-ATR on the unfavourable side of the current 1h regime's MFE extreme** (`b_sd_cur_mfe_1h_A <-2`,
N 563):

| block | QF | rest | runner | rest |
|---|---|---|---|---|
| train | 20.1% | 14.5% | 33.2% | 37.4% |
| val | 20.8% | 15.0% | 30.0% | 36.9% |

Gross is not worse in validation (+0.03 vs +0.02 A). The one pooled family that flags quick-fail has a
*negative* train/val correlation overall.

**6. Segments that tolerate chop but still produce runners.**
None can be identified.
- Chop does not separate segments. Crossings per minute do not replicate (answer 4).
- Within a segment, chop carries ≤ 2–4pp beyond location (answer 11).

**7. Segments that produce unusually many runners.**

**(a) Entry within 0.5 trade-ATR of the current 1h MFE extreme** (`b_ad_cur_mfe_1h_B [0,0.5)`, N 158):

| block | runner | rest | gross (A) | rest (A) |
|---|---|---|---|---|
| train | 47.1% | 36.8% | +0.23 | −0.05 |
| val | 61.5% (n 39) | 35.7% | +1.02 | −0.01 |

**(b) Alignment code OAO** (15m aligned, 5m and 1h opposed; N 282): 39.1% vs 36.9% in train, 50.0% vs 35.7% in
val (n 62). This is weaker.

**(c) State × structure cells.** Several cells in S|L|L|L, S|L|S|S and S|S|S|S carry +9 to +15pp runner, the
same sign in both blocks. The common theme with (a) is distance from the current higher-timeframe regime
extreme: near the extreme gives more runners, deep behind it gives fewer. That is a hypothesis, not a finding.

**8. Entry-exclusion candidates (`CANDIDATE_ENTRY_EXCLUSION`; not a rule).**

- **AAO: 5m and 15m aligned, 1h opposed** (N 503). It is **not** fast-fail-prone: QF 15.2% vs 15.0%. It is
  **runner-poor and partial-heavy.**

  | block | runner | rest | gross (A) | rest (A) |
  |---|---|---|---|---|
  | train | 32.8% | 37.4% | −0.31 | −0.02 |
  | val | 31.2% | 36.8% | −0.17 | +0.04 |

  The deficit **widens** after entry (answer 9). This is the strongest candidate.

- **Entry ≥ 2 1h-ATR behind the current 1h MFE** (from answer 5). It is QF-prone and runner-poor, but gross in
  validation is not worse. It is a weak candidate.

**9. Once a trade has survived 3/5/8/12 min, do segment priors still matter?**

- **The state dominates.** At 300 s, among trades still alive and below +2A, current P&L alone moves
  P(eventual runner) from **18%** (≤ −0.5A) to **89%** (+1.5 to +2A). The same holds at every checkpoint.
  - Survival time adds nothing on its own: the hazard is flat.
  - The flip risk in the next interval is likewise set by location: 45% vs 4–8% at 300 s.

- **One segment residual persists.** For the 8-code alignment family, the location-adjusted dispersion of
  P(eventual runner) is:

  | checkpoint | × the circular-shift null |
  |---|---|
  | 60 s | 1.9 |
  | 180 s | 3.8 |
  | 300 s | 5.1 |
  | 480 s | 3.6 |

  In effect size that is an RMS of 3–4pp against a null of about 1.7pp. It is carried by AAO:

  | alive at 300 s, below +2A | runner share (train / val) | pooled |
  |---|---|---|
  | AAO | 27.7% / 23.5% | 38.3% |

- **Ordering:** the MTF state's contribution is marginal before 480 s (ratio 2–3.4). The 1-D structural
  buckets add nothing at any checkpoint (ratio 0.9–1.3).

- **The terminal-loss dispersion across MTF states is direction drift, not structure.** Shorts lost −0.16A in
  train (2023-H1 up-trend) and +0.00A in val.

**10. Once a trade reaches +0.5/+1/+1.5A, do segment priors still matter?**
Pooled event transitions:

| anchor | P(next level before return to entry) | P(eventual +2A) | P(terminal loss) |
|---|---|---|---|
| +0.25A | 50.9% (→ +0.5A) | 43.0% | 60.5% |
| +0.5A | 49.0% (→ +1A) | 49.1% | 54.9% |
| +1A | 66.1% (→ +1.5A) | 62.9% | 42.7% |
| +1.5A | 73.8% (→ +2A) | 79.5% | 28.5% |
| +2A | 61.9% (→ +3A) | — | 15.9% (P(+3A) 64.9%) |

Segment residual at each touch:

| touch | MTF state | 1-D structure | alignment code (runner dispersion × null) |
|---|---|---|---|
| +0.5A | null | null | 2.9 |
| +1A | null | null | 4.4 |
| +1.5A | null | null | 3.3 |

- The alignment-code residual is about 3–4pp RMS and is again AAO:

  | at the +1A touch | P(eventual +2A) (train / val) | pooled |
  |---|---|---|
  | AAO | 56% / 54% | 63% |
  | OAO | 74% / 80% | 63% |

- The race to the next level is segment-independent everywhere except the +1.5A → +2A race for alignment code
  (3.5× null).

**11. Is chop measurable?**
Yes as geometry, but it carries almost nothing beyond location.
- **Every chop metric varies widely:** entry crossings (±0.1A hysteresis), ≥ 0.5A swings, path efficiency, time
  above/below entry, time since the last new MFE, 30/60 s return. For example, lifetime crossings run P25 1 to
  P75 7.
- **Measured at equal age and location**, it adds at most about 2–4pp to P(eventual runner) at 120–480 s in the
  lowest vs highest tercile.
  - Crossings and swings add +2–4pp to the runner probability.
  - Time above entry adds −1 to −2pp.
- **30/60 s return moves the next-interval flip risk by 3–6pp.** That is the known trailing geometry of the 1m
  flip trigger.
- **Slow/chop failures are not a distinct chop state.** At the same age with running MFE < 0.5A, eventual
  SLOW_FAIL and eventual RUNNER trades have the **same** crossings per minute and swing counts. They differ in
  **location**:

  | at 180 s | current P&L (median) | time above entry (median) |
  |---|---|---|
  | eventual SLOW_FAIL | −0.58A | 7% |
  | eventual RUNNER | −0.34A | 13% |

**12. Do the results support segment-specific dynamic management?**
No. Management-relevant information is post-entry location plus the moving flip boundary, and it has the same
shape in every segment. At most, a single additive segment term is justified: AAO, or distance to the 1h
extreme.

**13. Do they support segment-specific ML loss functions?**
No. The asymmetric-loss idea needs segments that differ in *failure mode* (many quick failures and few
chop → runner recoveries, versus the reverse).
- **Quick-fail share** is within null everywhere once duplication is controlled.
- **Slow-fail share** is within null too.
- **Chop → runner behaviour** does not replicate.

The only reproducible difference is runner share, which is a *level* shift. A shared loss with a segment offset
handles that; it does not call for a different loss.

**14. Does the current post-entry state overwhelm the T0 segment?**
Yes.
- **Location:** at 300 s, location moves P(eventual runner) by about 70pp.
- **The best T0 family:** it moves it by about 3–4pp RMS (AAO about −10 to −15pp).
- **Among undeveloped trades:** eventual QUICK/SLOW failures and eventual developers are separated by current
  P&L and MAE, not by segment or chop.

**15. The smallest next experiment justified.**
**One pre-declared, two-contrast test on already-collected data; no model, no rule.**
1. AAO vs rest: runner share (≥ 2A) and mean terminal gross, at T0 and among trades alive and below +2A at
   300 s.
2. Entry within 0.5 trade-ATR of vs ≥ 2 1h-ATR behind the current 1h MFE extreme: runner share and quick-fail
   share.

- **Proposed data:** the dark final 20% of 2023 (52 sessions, about 1,500 trades), where the frame and bars
  already exist.
  - Minimum detectable runner difference at AAO's size there (about 125 trades): about 12pp at 80% power. The effect seen here is 5–10pp, so
    this is a coarse test.
  - For a decisive power margin, 2024 would also be needed.
- **Both data sets need your approval.** The dark 20% and 2024 were out of scope here.
- **Proposed thresholds:** runner deficit ≥ 4pp, same sign.
- **If it replicates:** the justified follow-up is an AAO entry-exclusion **backtest** in a later study, not
  segment ML.
- **If it does not:** close the T0-segment line.

## REUSE_AND_WORKFLOW_ASSESSMENT

**What was reused, and what was recomputed:**

| step | source | runtime |
|---|---|---|
| population, entry price/time, `atr_entry_1m`, terminal bound, gross P&L, win, 5 favourable + 2 adverse first touches, split | `nq_post_entry_path_mechanism_2023/TRADE_EVENT_TIMELINE`, `nq_target_a_constrained_stationary_2023/TEMPORAL_SPLIT_2023.json` | reused, 0 s |
| complete T0 taxonomy: MTF state, alignment code, side, 51 structural bucket columns | `nq_mtf_regime_structural_geometry_atlas/atlas_2023_frame.parquet` | reused, 0 s |
| `study new` worktree | CLI | 7 s |
| **one raw 1s pass**: per-second path for all 6,024 trades, plus +0.25/+0.75/+4A and −0.25A touches | `extract_paths.py`, `CausalDataLoader` | **15.7 s**; parity 0 / 42,168 first-touch seconds + 0 entry mismatches vs the audited timeline |
| per-trade reduction: running MFE/MAE, crossings, swings, efficiency, time above/below, checkpoints to 1800 s, event anchors | `path_atlas.py` | 3.7 s |
| signatures, cluster-robust contrasts, transition tables | `path_atlas.py` | 12 s |
| circular-shift nulls (60 flag-count shifts, 20 replication shifts, 30 per state-dispersion test) | `path_atlas.py` | 222 s (92% of compute) |

**Split:**
- About 60% of the required variables came directly from existing artifacts: identity, T0, direction, ATR,
  terminal, MFE-to-level touches, MTF alignment and all bucket memberships.
- The other 40% (the checkpoints past 285 s, every chop metric, the +0.25/+0.75A touches) needed the
  per-second path.
- That path was not stored anywhere, but one raw-1s pass rebuilt it in **16 s**.

**Would recollection have added information?** No.
- The prior study reported "no checkpoints after +285 s (collector max_age 300 s)" as a *missing primitive*.
  The raw-1s pass removed that limit in seconds.
- A V2 recollection extending the checkpoint age would have taken hours and produced a subset of what the
  1s pass gives.

**Did the workflow slow this down?**
- **Compute took about 4.5 minutes; the rest of the time was reading and writing.** The normal V2 lifecycle
  would put hours of ceremony in front of a question that needs minutes of computation: compile → prepare →
  freeze → seal → preflight → collect → readiness → analysis harness, plus the test_delta commit gate.
- **None of those stages would have added integrity here.** Integrity came from three things:
  - exact parity against the audited timeline;
  - the dark 20% never being loaded;
  - a calibrated null plus block replication.
- **`ANALYSIS_HARNESS_GAP`:** `research/analysis/` cannot express either of these:
  - a per-trade raw-1s path reduction;
  - a circular-shift null.

  That is why this study, like the two path studies before it, uses a study-local script.
- **Recommendation:** add a sanctioned **exploratory lane**.
  - **Read-only inputs:** audited frames and timelines, plus raw 1s bars through `CausalDataLoader`.
  - **Required safeguards:** a parity check against the audited artifact, and a hard-coded development-session
    filter.
  - **Output:** a descriptive report with no seal.
  - **Graduation:** only confirmatory tests go through the full lifecycle.
- **Worth persisting:** the per-second path store (`_work/PATH_1S.parquet`, 39 MB, 4.5M rows) could become a
  shared, hash-pinned development artifact.

**Defects found and fixed during the run** (none reached the results):
1. **Column-name collision** with the audited touch columns. It crashed the run; now fixed.
2. **float32 A-unit level comparison.** It gave 1–2 of 30k first-touch mismatches. Touches are now computed
   with the kernel's price-level arithmetic during extraction; parity is 0.
3. **Degenerate rest-of-parent contrasts.** Flags compared a cell holding about 95% of its state against about
   20 residual trades. That inflated state × structure runner flags from a true 17 to 37. The fix requires the
   rest-of-parent to have N ≥ 150. The atlas had documented the same trap.

## Files

| file | content |
|---|---|
| `artifacts/PATH_ATLAS_SEGMENTS.parquet` | every segment: phenotype mix (+ sensitivities), durations, MFE/MAE, level reach/timing, adverse-first races, chop metrics, cluster-robust Δ / z / train Δ / val Δ, material/replicated flags |
| `artifacts/PATH_ATLAS_TRANSITIONS.parquet` | clock (9 checkpoints × 11 stratifiers, plus by state/code × current P&L) and event (6 anchors, pooled + by state/code) transitions |
| `artifacts/PATH_ATLAS_TRADES.parquet` | per-trade path summary + phenotype + taxonomy |
| `artifacts/DURATION_DISTRIBUTIONS.csv`, `TERMINAL_HAZARD.csv` | lifecycle |
| `artifacts/PHENOTYPE_BY_SEGMENT.csv`, `CHOP_METRICS_BY_SEGMENT.csv` | compact views |
| `artifacts/FLAG_COUNTS_VS_NULL.csv`, `SEGMENT_REPLICATION.csv`, `SEGMENT_MATTERS_BY_STATE.csv` | heterogeneity vs null |
| `artifacts/CHOP_INCREMENT_OVER_LOCATION.csv`, `UNDEVELOPED_CHOP_SIGNATURE_BY_EVENTUAL_PHENOTYPE.csv` | chop measurement |
| `artifacts/PATH_EXTRACT_AUDIT.json`, `RUN_TIMINGS.json` | parity, timings |
| `extract_paths.py`, `path_atlas.py` | full reproduction (≈ 4.5 min) |

```
T0_SEGMENT_PATH_HETEROGENEITY_WEAK
```
