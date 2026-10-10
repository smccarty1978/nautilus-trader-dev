# nq_fair_pricing_reversion — TRAIN collection audit and descriptive report

**Verdict:** TRAIN_COLLECTION_PASS_WITH_QUALIFICATIONS

The full TRAIN population (2021–2023) is collected, complete and reconciled, and it carries the sealed identity. The qualifications are listed in §13.

Descriptively, A1 and A2 do not separate from A0. Only the A1∩A2 overlap differs, and it should be treated as a hypothesis, not a finding.

## 1. Recovery of existing work
- **Before this session:**
  - Governed state was `READY_TO_COLLECT`.
  - A first controller attempt failed: a `TimeoutExpired` after 600 s on partition 2021 (`failure_packet.json`, 03:18:14Z).
- **Relaunch (study lease owner `antigravity`, 03:18:38Z, PID 62500):**
  - Command: `run_governed_study.py --through merge --execute-authorized --chunked-batch-rows 50000 --max-runtime 86400 --stale-progress-timeout 1800`.
  - Before this session it had completed 2021 and 2022 and was running 2023.
- **This session:**
  - No collector was launched; the session waited for the existing job.
  - The controller finished at 05:16:07Z with collection, reconcile and merge PASS and state `READY_TO_FIT`. No fit was run.

## 2. Period and dataset
- TRAIN covers 2021-01-01 to 2023-12-31, with a 5-day warmup, as authorized in `experiment_authorization.json`.
- 2024 and later were not touched.
- Dataset `NQ_1S_V2_GLOBEX`, with byte verification VERIFIED.
- 772 sessions on the CME Globex calendar: 257, 258 and 257 per year. 24 of them are holiday or shortened sessions: 20 close at 13:00 ET and 4 at 13:15 ET.

## 3. Contract and provenance
- **Identity** (compiled plan, frozen manifest, seal, readiness, and all 3 partition manifests):
  - plan `9b9b80c6…`
  - composite `dad232b5…`
  - dataset `9e7aecb7…`
- **Audit state:** causal audit CLEAR (0 critical) and readiness PASS (R1, R3, R5, R8, R9, R10).
- **File hashes:**
  - The partition parquet hashes recompute to the values in their manifests.
  - Merged = the three partitions combined, row for row: candidates `606a4f4c…` and observations `f1a15a18…`.
  - Reconcile `passed: true` with no findings.
- `artifact_manifest.json` hashes 29 files.

## 4. Runtime
| Partition | Elapsed | 1s+1m bars | Epochs | Throughput |
|---|---|---|---|---|
| 2021 | 2,155 s | 12,392,181 | 356,228 | about 5,750 bars/s |
| 2022 | 2,500 s | 13,832,528 | 359,633 | about 5,530 bars/s |
| 2023 | 2,075 s | 12,755,826 | 358,875 | about 6,150 bars/s |

- Controller wall time, including reconcile and merge: about 1 h 57 m.
- Pending at the end: 0.
- Peak memory: not recorded by the controller, so unverified.

## 5. Counts (one row per candidate = one observation)
| Population | n | Sessions | Share of A0 | Per session |
|---|---|---|---|---|
| A0 | 69,369 | 772 | 100% | 89.9 |
| A1 | 3,960 | 770 | 5.7% | 5.1 |
| A2 | 3,450 | 767 | 5.0% | 4.5 |
| A1 only | 3,060 | 763 | 4.4% | 4.0 |
| A2 only | 2,550 | 751 | 3.7% | 3.3 |
| A1∩A2 | 900 | 538 | 1.3% | 1.2 |
| A0 with no signal | 62,859 | 772 | 90.6% | 81.4 |

## 6. Reconciliation (all pass; total 69,369 for every arm)
| Arm | Positive | Negative | Censored |
|---|---|---|---|
| tp38_sl25 | 23,656 | 38,408 | TIMEOUT 7,274; AMBIGUOUS_SAME_BAR_TOUCH 31 |
| anchor_sl25 | 25,126 | 35,244 | TIMEOUT 8,731; ANCHOR_ALREADY_CROSSED 144; AMBIGUOUS 124 |
| m25 / m50 / m75 / m100 | 55,185 / 45,672 / 38,517 / 32,996 | 0 | TIMEOUT for the remainder |

Other checks that passed:
- Candidate uniqueness.
- Observation timestamps fall on minute boundaries between 09:31 and 11:00 ET.
- Every resolution is after the observation and no later than 11:30 ET.
- No resolution is missing.
- Direction equals −sign(displacement) in every row.
- No candidate has zero displacement.
- A1 is exactly `is_displacement` ∧ `toward_anchor`; A2 is exactly `is_bos` ∧ `toward_anchor`.
- A1∪A2 splits exactly into A1-only, A2-only and the overlap.
- Milestones are monotone.
- The primary disposition matches tp38_sl25.

Most sessions have all 90 checkpoints. 96 have 87–89, consistent with minutes where price equals the anchor, which the spec excludes.

## 7–8. tp38_sl25 comparison
The resolved target-first rate is P/(P+N). Censored rows are reported, never dropped. The gross breakeven is 39.68%.

| Population | Target-first rate | 95% CI (day-cluster) | Δ vs no-signal A0 | Δ CI | Δ standardised¹ |
|---|---|---|---|---|---|
| A0 | 38.12% | 36.7–39.6 | — | — | — |
| A1 | 38.20% | 36.1–40.4 | +0.1 pp | −1.5 to +1.6 | +0.1 |
| A2 | 38.74% | 36.4–41.1 | +0.6 pp | −1.2 to +2.3 | +0.6 |
| A1 only | 37.05% | 34.7–39.4 | −1.1 pp | −2.8 to +0.7 | −1.1 |
| A2 only | 37.52% | 35.1–40.1 | −0.6 pp | −2.7 to +1.4 | −0.6 |
| A1∩A2 | 42.13% | 38.5–45.9 | +4.0 pp | +0.7 to +7.3 | +4.0 |
| A1∪A2 | 37.94% | 36.0–39.9 | −0.2 pp | −1.5 to +1.1 | −0.2 |

¹ No-signal A0 reweighted to each population's mix of time-of-day (3 bins) and distance from the anchor (5 bins). The bins were fixed in advance, not chosen from outcomes.

**anchor_sl25** (variable payoff; no breakeven applies):

| Population | Raw Δ vs no-signal | Standardised Δ |
|---|---|---|
| A2 | +3.0 pp (CI +1.5 to +4.7) | +1.4 |
| A1∩A2 | +4.5 pp | +3.5 |
| A1 | +1.0 pp | +0.4 |

The A2 anchor-arm advantage is about half composition: when and how far from the anchor the signal fires.

**Milestones** (rate of reaching each; median time is about 2, 5, 7 and 8 minutes for every population):

| Population | m25 | m50 | m75 | m100 |
|---|---|---|---|---|
| A0 | 79.6% | 65.8% | 55.5% | 47.6% |
| A1 | 79.9% | 66.5% | 56.3% | 48.1% |
| A2 | 80.7% | 67.8% | 58.1% | 49.9% |
| A1∩A2 | 82.2% | 69.7% | 60.4% | 52.0% |

**Resolution time (tp38, A0):**
- Target-first: median 600 s (IQR 300–1,200).
- Stop-first: median 420 s (240–900).
- Censored: median 3,000 s.
- The signal populations look the same.

## 9. Stability
**By year, target-first Δ vs no-signal:**

| Population | 2021 | 2022 | 2023 |
|---|---|---|---|
| A1 | −0.8 | −0.6 | +1.6 |
| A2 | −0.9 | +1.5 | +1.0 |
| A1∩A2 | +2.3 | +4.5 | +5.1 |

- **By month:** months with the signal above no-signal, out of 36: A1 21, A2 20, A1-only 15, A2-only 13, A1∩A2 22. The A1∩A2 count rests on small monthly samples (900 observations over 36 months).
- **Concentration:** no population depends on a few sessions.
  - The top 10 sessions hold at most 10% of target-first outcomes, and that maximum is the overlap.
  - Dropping the 5 busiest sessions changes the rates by 0.1 pp or less.
- **A0 by year:** 37.5%, 38.7% and 38.1%.

## 10. Censoring and timing
- **The tp38 censor rate rises late in the window:** 3.4%, 7.9% and 20.3% for 09:31–10:00, 10:01–10:30 and 10:31–11:00. This is because the 11:30 cutoff truncates the horizon.
- **Bounds:** for A0, counting censored rows as losses gives a target-first rate of 34.1%; counting them as wins gives 44.6%. Censor rates are similar across populations, 10–12%, so censoring does not create the contrasts.
- **Time of day:** A0 target-first is 38.7%, 39.3% and 36.1% by window.
- **2022 censoring** (about 4%) is much lower than in 2021 (17%) and 2023 (11%). That fits larger 2022 ranges reaching ±38/25 sooner.
- **Ambiguous same-bar touches are rare:** 31 for tp38 and 124 for the anchor arm.

## 11. Assessment
**Observed:**
- A1, A2, A1-only, A2-only and A1∪A2 have tp38 target-first rates within ±1.1 pp of A0. All their confidence intervals include zero, the result holds after standardising, and the direction varies by year.
- No population exceeds the 39.68% gross breakeven with confidence. A0 itself is at 38.1%.
- A1∩A2 is +4.0 pp (CI +0.7 to +7.3). It is positive in all 3 years and survives standardisation, with 900 observations over 538 sessions.

**Inferred:**
- The A1∩A2 difference is one of six contrasts, chosen here with no correction for multiple comparisons. A false positive at about this size is plausible.
- A1∩A2 at 42.1% is above breakeven only before costs, and its confidence interval includes breakeven.
- Neither signal alone carries information. Any effect lives only in the joint condition.

**Unverified:**
- Out-of-sample behaviour.
- Net-of-cost economics.
- Whether labels would change under 1s barrier sequencing; the 31 and 124 ambiguous rows are the only ones whose labels could change.
- Independence of consecutive-minute observations: overlapping outcome paths make the effective sample size much smaller than n. The day-cluster bootstrap partly allows for this.

**Next phase:**
- The evidence does not support A1 or A2 as signals.
- At most it supports a separately authorized, pre-registered test of A1∩A2 on held-out data, stated in advance as one hypothesis. Whether to run it is the owner's decision.
- No strategy is implied.

## 13. Limitations and qualifications
1. **The outcome stream is `nq_1m`.** The sealed plan's `outcome.stream` defaulted to the 1m epoch stream because `study.yaml` declares none, so barriers resolve on 1-minute OHLC, not with 1s sequencing.
   - It is still causal: entry is the next bar's open, and only bars after T are evaluated.
   - Labels match 1s sequencing except for same-minute double touches, which are censored as AMBIGUOUS (31 for tp38, 124 for the anchor arm).
   - Resolution times are rounded up to the minute.
2. **11:00 ET candidates (772, 1.1%) are admitted.** Their entries are stamped 11:00:00, the minute bar's event time, so the "print after 11:00:00 → ENTRY_PAST_CUTOFF" rule never fires. Under 1s entry, most of them would probably be rejected.
3. **The sealed contract is uncommitted.** Its `study.yaml` change from recovery to barrier arms, the compiled plan, the seal and the authorization exist only as uncommitted files in the study worktree (HEAD `e622784c`). The run is internally consistent with them, but git does not preserve them. The lease owner (`antigravity`) should commit them.
4. **Peak memory is not recorded.**
5. **The TRAIN years include 2021.** That is authorized by this study's own sealed chronology. The earlier "no 2021" constraint applied to the volume-profile G2 sprint.
6. **The milestone arms have no stop.** Their "reach" rates are not comparable to the bracket rates.
7. **The legacy flip-label columns** (`target_flip_within_horizon`, `flip_ts`) are present but unused.


**Correction (2026-10-10, 1m vs 1s audit):** �13 item 2 is wrong. In a bounded causal 1s replay, all 27 sampled 11:00 candidates had identical entry time and price under 1s and none were rejected. See `fpr1s/out/OUTCOME_CONTRACT_AUDIT.md`.
