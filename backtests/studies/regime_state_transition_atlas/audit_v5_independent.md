# Independent Audit v5 — Regime State Transition Atlas

**Date:** 2026-06-11
**Auditor:** Claude (independent manual read of all 6 scripts + results + prior audits v1–v4), not the prior lookahead-auditor.
**Question posed:** Are the scripts valid and leak-proof? User is "seeing interesting results and reluctant to trust the agent."

---

## Bottom line

**The pipeline is substantially leak-resistant. The "interesting result" is NOT a leak artifact — it is real but near-tautological and does not translate to money.** The agent's `state_memory_summary.md` verdict ("**Memory Edge Confirmed**") is the thing to distrust: it overstates a trivial autocorrelation. Every policy variant is net-negative out-of-sample.

- Leak audit: **0 edge-manufacturing leaks found.** Scoring is properly walk-forward; features are causal (provenance-guarded); labels are forward-from-next-open with the trigger bar excluded.
- Minor causal issues found (do **not** create the result): (1) regime-exit label is back-dated ~1s; (2) `query_similar_states.py` uses the full IS pool (footgun, but unused by the results); (3) gapped-minute fallback fill (already flagged v4).
- The headline "monotonic OOS calibration" is on a **near-tautological label** (next-bar continuation ≈ regime persistence, and the KNN **exact-matches `bar_index_in_regime`**). The **tradeable** label (PT-before-SL race) calibrates **flat**. PnL is net-negative in every decile and every policy.

---

## What is clean (verified by reading, not trusting prior audits)

**Scoring is walk-forward causal** (`analyze_state_memory.py:54-193`). Each year is scored only against strictly-prior years (2022←2021, 2023←2021-22, 2024←2021-23, 2025/2026←2021-24). The z-scaler mean/std is fit on the training db and applied to queries (`:79-89`). Same-`regime_id` neighbors are excluded (`:145`). Predictions are means of **neighbors'** outcomes; the query's own label is never used to score it. This is correct.
- Note: `query_similar_states.py` (a *separate* interactive tool) instead uses the **entire** IS pool (`df_all[year<2025]`) for all queries, which is NOT as-of-time. It does not feed the results pipeline, but anyone querying through it in-sample would get future-contaminated neighbors. **Footgun — add a temporal `bar_ts < query.bar_ts` filter or delete it.**

**State features are causal** (`build_state_rows.py`). `_snapshot_features` opens with `self._reg.audit_provenance(completed_1m.close_ts)` (`:307`) — the hard MTF guard. `_1m_regime_high/low` are updated in `on_1s` **after** `agg.on_1s_bar` returns (`:300-302`), so at snapshot the regime extremes reflect bars through the prior 1s only; `made_continuation` compares the just-closed bar's H/L to `_1m_regime_high_prior` (updated *after* the snapshot, `:237-243`). Volume deque is appended **after** the snapshot (`:277`), so `volume_percentile_20` / `bar_volume_vs_20avg` compare current-vs-past. EMAs/slopes are on closed bars. No feature reads forward.

**Forward labels are forward-from-next-open** (`build_forward_labels.py`). `base_px = next_1s_open` (`:190`) is the 2nd 1s open after the checkpoint; `trigger_cutoff = checkpoint_ts + 1s` (`:178`) excludes the triggering bar from every label, race, and excursion window (`:193, 220, 254, 285, 365`). Races resolve on the 1s path strictly after the cutoff. This is the train/serve-consistent base the v3/v4 audits established.

**Strong negative evidence of a price leak:** the **PT-before-SL race calibration is FLAT** (`state_memory_summary.md` §B/§C: predicted 35→60% → actual ~47–51%). If forward prices leaked into features/labels, the pure-price race label would calibrate well. It doesn't. This is independent confirmation that the 1s price path is **not** leaking.

---

## The real problem: the "edge" is a tautology, not a leak

`next_bar_makes_continuation` calibrates almost perfectly OOS (predicted 0–5%→actual 2.0% … 70–75%→78.9%, tens of thousands per bucket). This is what looks impressive. But:

1. The KNN **exact-matches `bar_index_in_regime`** and matches on `mfe_so_far`, `continuation_count_so_far`, `consecutive_no_continuation_bars`, `last_3_bar_pattern`. The predicted "continuation rate" is therefore essentially **"how young / strong / un-stalled is this regime"**, which **mechanically** determines whether the next bar prints a new extreme. Early regimes continue ~75%; stalled regimes continue ~3%. The 2%→79% curve is just the **persistence/autocorrelation of the continuation process** — a known, trivial regularity, not new predictive content.
2. The **tradeable** outcomes do **not** inherit this. The 0.50/1.00 ATR race calibrations are flat (~49%). So the score predicts a near-tautological structural label but **cannot rank PT-before-SL outcomes**.
3. **PnL is negative everywhere.** OOS (`policy_v2_results.md` §3): all 12 score×percentile combos net-negative. Best is `score_opportunity` Top-2% at **−$8,158 net (−$2.09/tr, PF 1.03, 1/2 yrs)**; gross +$5.41/tr is eaten by the $7.50 cost. The `payoff_aware_summary.md` "champion" (Top-1%) is **−$7,332 OOS (−$3.59/tr, PF 1.02 ≈ breakeven)**. The benchmark loses far more (−$378,810), so the policy "wins" only by trading 17× less on a losing population.

**Therefore the agent's "Memory Edge Confirmed" is misleading.** A monotonic calibration on a structural label is being presented as a tradeable edge; the money (flat race calibration + uniformly negative net PnL) says there is none. The adjudication logic itself is weak: `analyze_state_memory.py:446-463` flips to "edge confirmed" merely if the **pt050** actual-rate range exceeds 3pp — but the pt050 curve is flat, so even that gate should read NULL; the printed "Memory Edge Confirmed" appears to be driven by the continuation curve, not the race curve it claims to test. Worth re-checking which curve set the flag.

---

## Concrete issues to fix

1. **[Minor leak] Regime-exit label back-dated ~1s.** `build_forward_labels.py:145` evaluates the checkpoint with `exit_px = o` (the triggering bar's open), which is ~1s before the flip is confirmable. Slight favorable bias in `forward_pnl_to_regime_exit_*` (feeds scores + the calibration PnL column, **not** the policy backtest, which uses next-open exits). Fix: exit at the next-open of the new regime's first executable bar, matching the entry convention.
2. **[Footgun] `query_similar_states.py` neighbor pool is the full IS set,** not as-of-time. Add a `cand.bar_ts < query.bar_ts` (or year < query_year) filter, or remove the tool, so no one draws in-sample contaminated neighbors from it.
3. **[Validity] Replace the "Memory Edge Confirmed" verdict** with a money-based test: the edge claim should require the **race/PnL** calibration to be monotonic AND a policy to be net-positive OOS. The continuation curve should be explicitly labeled "structural persistence, not tradeable."
4. **[Minor]** v4's gapped-minute fallback (`:185`) and the dead `pullback_depth_current_bar` (`:355`) remain.

## Verdict

Trust the **leak-proofing** (it is sound) and trust the **PnL** (uniformly negative OOS). Do **not** trust the **"Memory Edge Confirmed"** headline — the impressive calibration is a tautology on a non-tradeable label and is contradicted by the flat race calibration and negative net PnL in the same outputs. No deployable edge is present.

---

## Rerun outcome (after fixes applied)

All four fixes applied; pipeline fully rebuilt (1,618,561 fresh forward-label rows → walk-forward re-scored, 1,314,501 rows).

- **New money-based verdict (`state_memory_summary.md`):** *"No tradeable edge."* Continuation calibration spans 76.9pp (tautological — KNN exact-matches `bar_index_in_regime`); the **tradeable** PT-before-SL race calibration is flat; the **top OOS opportunity decile is −$12.12/trade after cost (0/10 deciles net-positive).**
- **Strict gate (`policy_gate_results.md`):** OOS net>0 AND 2025>0 AND 2026>0 AND PF>1.05. **0 of 24 configurations pass** (both re-entry and first-entry-only modes). Least-bad: first-entry `score_opportunity` Top-1% = −$1.02/trade, PF 1.00, 2026 −$1,342. The only per-year-positive cell (re-entry opp Top-2%, 2025 +$6,402) is wiped by 2026 (−$9,542) — a one-year artifact.
- **first-entry-only is uniformly equal-or-worse** than re-entry → the apparent edge was partly re-entry churn, not entry skill.
- **Tick/NT parity not built — moot.** Parity can only reduce edge; a net-negative offline policy with PF≤1.00 cannot pass it.

**Final: leak-fixed, rerun, and definitively non-deployable at the offline gate.**
