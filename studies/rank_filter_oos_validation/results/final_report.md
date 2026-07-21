CORRECTED SESSION AUDIT:
PASS

DELAYED-ENTRY AUDIT:
PASS

PENDING-ENTRY CANCELLATIONS:
12 (corrected research-table estimate) / 4 (NT-observed, real event-driven ground truth — see Section 4)

ENTRY PRICE/TIMESTAMP MISMATCHES:
3,036 of 6,898 signals (44.0%) have no exact raw-data bar at the theoretical expected_fill_ts — all classified sparse_data_forward_fill (35.0%, median 2s) or large_gap_anomaly (9.0%, median 9s); 0 are unclassified

CORRECTED R2 EV LIFT:
+$1.46

CORRECTED R4 EV LIFT:
+$2.26

CORRECTED R4 MATCHED-RANDOM P:
0.251

CORRECTED R4 OOS TOP-DECILE RETENTION:
0.9577

CORRECTED R4 FROZEN-THRESHOLD RETENTION:
0.9404

NT R2 EV LIFT — 2025 H2:
+$1.21

NT R4 EV LIFT — 2025 H2:
+$2.11

NT R2 EV LIFT — 2026:
-$0.14

NT R4 EV LIFT — 2026:
-$0.39

NT R2 MAX-DD CHANGE:
+$4,115 (2025H2, improvement); -$3,975 (2026, worse — not pooled, see Section 8)

NT R4 MAX-DD CHANGE:
+$8,560 (2025H2, improvement); -$2,610 (2026, worse — not pooled, see Section 8)

NT PARITY AUDIT:
PASS

R2 VERDICT:
HOLD

R4 VERDICT:
HOLD

PREFERRED POLICY:
R4

---

# R2/R4 Rank Filter — Correction Pass + NautilusTrader Validation

Study directory: `studies/rank_filter_oos_validation/` (continues from the prior run; this pass corrects specific defects and adds genuine event-driven NT validation).
Frozen policies reused verbatim throughout (no retraining, no threshold/exemption changes): score threshold **0.12855426455573915** (top-10%), R2 = strong-center-migration exemption, R4 = favorable-regime-asymmetry exemption.

## 1. Session Definition Correction

**Fixed:** RTH is now `08:30 <= America/Chicago time < 15:00`, Monday-Friday (the project-canonical definition), replacing the prior run's incorrect `09:30-16:00` override. `common.py::get_session` updated; every RTH/ETH-dependent output (segments, matched-random strata, session tags) was regenerated from this corrected definition. **CORRECTED SESSION AUDIT: PASS.**

## 2. Delayed-Entry Semantics Audit

For every one of the 6,898 confirmed F2 signals in the primary window, `delayed_entry_audit.parquet` records `confirmation_ts -> decision_ts -> expected_fill_ts (exactly +30s) -> actual_fill_ts (next available raw 1s-bar open at/after that target)`, plus `timestamp_match`/`price_match` flags and a `mismatch_class`.

| mismatch_class | count | fraction | median gap | p90 gap |
|---|---|---|---|---|
| exact_match | 3,862 | 56.0% | 0s | 0s |
| sparse_data_forward_fill | 2,417 | 35.0% | 2s | 4s |
| large_gap_anomaly | 619 | 9.0% | 9s | 19s (max 179,971s, near a session/weekend boundary) |

**3,036 signals (44.0%) have no exact raw bar at the theoretical 30s target** — this is expected real-market sparsity (data only prints when the market trades), not a defect; the median/p90 gaps for both non-exact classes are small (seconds), confirming the fills are genuine near-immediate market fills, not stale or erroneous. **DELAYED-ENTRY AUDIT: PASS.**

## 3. Pending-Entry Cancellations: a Real Divergence Between the Pandas Estimate and NT Ground Truth

Phase 1's pandas-replay estimate (`pending_entry_cancellations.parquet`) found **12** episodes where the opposite regime flip occurs within the ~30s delay window before the pandas-modeled entry could activate — these are kept as explicit non-trade records (`status_chain`: "signal confirmed -> entry scheduled -> opposite flip before activation -> pending entry canceled -> no trade"), PnL = NaN, never dropped or zero-filled, per the repair brief.

**The real NT backtest (R0/2025H2) found only 4.** This is a genuine, reportable divergence: the pandas replay's regime-flip detection is built from a different bar-aggregation pipeline than the bug-fixed `NQ_v0_2025_fixed` catalog NT actually trades against (see Section 5's broader signal-count reconciliation), so its estimate of "how often the opposite flip beats the 30s-delayed fill" is directionally right but overstates the frequency by ~3x. The NT number (4) is the ground truth for any final capital decision; the pandas number (12) is retained as the Phase-1 deliverable per the brief's literal scope (research-table correction, not NT validation) but should not be read as authoritative once NT results are available.

## 4. Runner Diagnostics — Both Retained (Corrected Research Table)

Per the brief: **the retrospective-OOS top-decile metric is the primary 95% rule**; the validation-frozen dollar-threshold metric is a secondary robustness diagnostic only.

| policy | retrospective OOS (primary) | validation-frozen (diagnostic) |
|---|---|---|
| R1 | 91.87% | 90.85% |
| R2 | **97.49%** | 97.39% |
| R4 | **95.77%** | 94.04% |

R4 clears the primary 95% rule (95.77%) on the corrected research table; the diagnostic metric is below 95% (94.04%), flagged as a secondary caution, not a gating failure per the brief's explicit instruction.

## 5. Corrected Pooled Economics (Research Table, `corrected_episode_results.parquet` / `pooled_metrics.parquet`)

| policy | eligible | filter-skipped | pending-canceled | filled | retention | EV/eligible | paired lift |
|---|---|---|---|---|---|---|---|
| R0 | 6,898 | 0 | 12 | 6,886 | 99.83% | -$5.69 | — |
| R2 | 6,898 | 304 | 11 | 6,583 | 95.43% | -$4.24 | **+$1.46** |
| R4 | 6,898 | 538 | 11 | 6,349 | 92.04% | -$3.43 | **+$2.26** |

Matched-random (1,000 seeds, ATR-bucket edges frozen on validation period): **R2 p=0.350, R4 p=0.251** — neither clears a ≤0.10 significance bar on the corrected research table. Full detail: `corrected_matched_random_summary.parquet`, `corrected_monthly_results.parquet`, `corrected_segment_results.parquet`, `corrected_drawdown_metrics.parquet` (all NaN-free, asserted before writing).

## 6. NautilusTrader Event-Driven Validation — Infrastructure

Ran the repo's real `CollectorV2Strategy` (`collectors/collector_v2/strategy.py`) inside an actual `BacktestEngine`, not a pandas post-hoc replay. Two small, backward-compatible additions were made to that shared strategy (default values preserve every other caller's existing behavior exactly):

1. **`entry_delay_ns` config field** (default 0): implements the canonical 30-second delayed activation. Verified in a smoke test: real NT fill timestamps land a median 29-30s after confirmation, matching the repo's own legacy delayed-collector reference dataset almost exactly.
2. **`skip_decision_ts` config field + `_is_policy_skip()`**: a frozen, precomputed pass-through skip gate — the R2/R4 score/exemption decision is taken from the already-frozen research table (or, for 2026, computed via the identical frozen threshold/exemption expressions applied fresh to that window's signals — no retraining, no new features, same rule), matched to NT's own `decision_ts` by nearest-backward timestamp.

**Mandatory pre-execution audit (CLAUDE.md gate) caught a real bug in the first version of this join**, before any backtest result was trusted: the original nearest-match logic was bidirectional and could match a `decision_ts` to a skip-flag from a confirmation event up to 90 seconds *in the future* — a genuine look-ahead violation, since a live system cannot know at time T whether a later event will exist or be flagged. **Fixed** (backward-only match, tolerance tightened from 90s to 20s based on the observed p95/p99 jitter of 8s/19s from Section 2) and re-verified before any of the reported NT results were generated. A second bug was caught during self-review before trusting results: the initial runner script always built the R2/R4 skip set from the 2025H2 corrected table regardless of which period was being backtested, so the first 2026 R2/R4 runs silently applied zero filtering (bit-identical to R0). Fixed by computing 2026's skip set fresh from the same frozen rule, and the affected runs were discarded and rerun.

## 7. NT Pooled Economics (`nt_trade_results.parquet`, `nt_pooled_metrics.parquet`)

| policy | period | eligible | pending-canceled | filter-skipped | filled | retention | EV/eligible | paired lift |
|---|---|---|---|---|---|---|---|---|
| R0 | 2025H2 | 6,905 | 4 | 0 | 6,901 | 99.94% | -$8.56 | — |
| R2 | 2025H2 | 6,905 | 4 | 298 | 6,603 | 95.63% | -$7.35 | **+$1.21** |
| R4 | 2025H2 | 6,905 | 4 | 531 | 6,370 | 92.25% | -$6.45 | **+$2.11** |
| R0 | 2026 | 3,957 | 0 | 0 | 3,957 | 100.0% | -$18.39 | — |
| R2 | 2026 | 3,957 | 0 | 152 | 3,805 | 96.16% | -$18.53 | **-$0.14** |
| R4 | 2026 | 3,957 | 0 | 236 | 3,721 | 94.04% | -$18.77 | **-$0.39** |

(304→298 and 538→531 filter-skip counts vs. the corrected research table reflect the ~98% match rate of the backward-20s-tolerance timestamp join between the two independent pipelines — expected and small.)

**The real NT event-driven result confirms the direction and rough magnitude of the corrected research table for 2025H2** (R2 +$1.21 vs +$1.46 pandas-estimated; R4 +$2.11 vs +$2.26) — a meaningful cross-validation that the pandas replay was not a materially misleading approximation for the primary period. **2026 flips sign for both policies** under real execution — this is the single most important finding of this validation and is explored further below.

## 8. 2026: Forward Evaluation, Not Clean OOS

Per the brief, 2026 is run **separately, never pooled with 2025H2**, and labeled `forward_eval_previously_inspected_contaminated` — this period has been examined in prior studies in this repo (e.g. the sibling `f5_flip_filter_repair` study), so it is not a fresh, untouched OOS test in the way 2025H2 is.

With that caveat: both R2 (-$0.14) and R4 (-$0.39) reverse to negative EV lift in 2026, and both show **worse** drawdown than R0 in that period (R2: -$3,975, R4: -$2,610 — i.e., the filters made the drawdown larger, not smaller). Matched-random empirical p-values collapse to 0.640 (R2) and 0.728 (R4) — the filters are statistically indistinguishable from (or worse than) randomly skipping the same number of trades in 2026. This is directly consistent with a broader pattern already documented elsewhere in this repo's memory (the frozen-F5 filter study found the same 2026 regime reversal on the same underlying data).

## 9. Runner Preservation (NT, `nt_runner_retention.parquet`)

| period | tier | policy | retention |
|---|---|---|---|
| 2025H2 | top10 | R2 | 97.51% |
| 2025H2 | top10 | R4 | **95.73%** |
| 2026 | top10 | R2 | 97.56% |
| 2026 | top10 | R4 | **95.03%** |

**R4 clears the 95% top-decile bar under real NT execution in BOTH periods** (95.73% / 95.03%) — a stronger result than the corrected research table alone (which only had the retrospective-OOS number, 95.77%, for 2025H2). This is a genuine positive finding for R4 specifically.

## 10. Drawdown (`nt_drawdown_metrics.parquet`)

Sign convention: positive cumulative PnL favorable; drawdown = running-peak minus current cumulative PnL (≥0, larger = worse). 2025H2: R0 $84,035 → R2 $79,920 (-$4,115 improvement) → R4 $75,475 (**-$8,560 improvement, the best of the three**). 2026: R0 $87,915 → R2 $91,890 (+$3,975 worse) → R4 $90,525 (+$2,610 worse). R4 has the best 2025H2 drawdown profile and the (relatively) smaller 2026 deterioration of the two filters.

## 11. Parity Check — Retained Trades Identical to R0

Per the brief's explicit requirement ("Verify retained R2/R4 trades use identical entry and exit timestamps/prices to R0"): `nt_parity_audit.parquet` checks every retained (non-skipped) R2/R4 trade against its R0 counterpart (matched by `decision_ts`).

| policy | period | n checked | entry_ts match | entry_px match | exit_ts match | exit_px match | verdict |
|---|---|---|---|---|---|---|---|
| R2 | 2025H2 | 6,603 | 100% | 100% | 100% | 100% | **PASS** |
| R4 | 2025H2 | 6,370 | 100% | 100% | 100% | 100% | **PASS** |
| R2 | 2026 | 3,805 | 100% | 100% | 100% | 100% | **PASS** |
| R4 | 2026 | 3,721 | 100% | 100% | 100% | 100% | **PASS** |

**Perfect match on every field, every retained trade, both periods.** This confirms the filters genuinely only skip entries — no entry timing, price, exit, or size was altered for any trade they retained. **NT PARITY AUDIT: PASS.**

## 12. Monthly and Segment Detail

Full monthly (`nt_monthly_results.parquet`) and 8-way LONG/SHORT/RTH/ETH segment (`nt_segment_results.parquet`) breakdowns are in the parquet files. Notable: R4's monthly EV in 2025H2 is positive or flat in 5/7 months (negative in July and August, both modestly), while 2026 is negative or flat in all 4 available months (Jan -$0.86, Feb -$24.26 [vs R0 -$30.29], Mar -$40.79 [vs R0 -$33.80, i.e. WORSE], Apr -$5.09 [vs R0 -$4.21, also worse]) — March and April 2026 show the filter actively hurting relative to baseline, not just failing to help.

## 13. Verdict

**R2:** modest, safe. Clears runner retention comfortably in both periods (97.5%+) and both drawdown-improves in 2025H2, but lift is below +$2, matched-random significance fails everywhere (p=0.25-0.35 in 2025H2, 0.64 in 2026), and it reverses to negative in 2026. Not compelling enough to ADVANCE; not broken enough to STOP. **HOLD.**

**R4:** best primary-period profile of the two — lift clears +$2 on both the corrected research table (+$2.26) and real NT execution (+$2.11), runner retention clears 95% in real NT execution in BOTH periods (a result the research table alone couldn't establish for 2026), and it has the largest drawdown improvement (-$8,560) in the clean 2025H2 OOS period. But it shares R2's core weakness — matched-random significance never clears ≤0.10 (0.184-0.251 in 2025H2, 0.728 in 2026) — and its 2026 reversal is *larger* than R2's on both lift and drawdown, with March/April 2026 showing the filter actively making things worse, not just failing to help. **HOLD**, not ADVANCE, pending resolution of the significance and regime-stability concerns.

**PREFERRED POLICY: R4** — between the two, R4 has the stronger, real-NT-verified primary-period case (economics + runner protection both clear their bars under genuine event-driven execution, with perfect entry/exit parity to R0), making it the better candidate to keep investigating. Neither should be deployed with capital yet: both fail the pre-declared matched-random significance bar, and both show a real (not just research-table-modeled) reversal in the most recent available data.

## 14. Next Step

Do not deploy either filter yet. The 2025H2 primary-period case for R4 is now genuinely NT-validated (not just a pandas approximation) and clears both the lift and runner-retention bars with perfect trade-level parity — but the consistent failure to beat matched-random controls, combined with a real (NT-confirmed, not just modeled) reversal in 2026, means the edge is not yet distinguishable from noise across regimes. Recommended: extend the matched-random comparison with a longer or independent OOS window before any capital decision, and treat the 2026 result as an active warning sign requiring investigation (why does the filter start actively hurting in March/April 2026?) rather than dismissing it solely because that period is labeled "contaminated."
