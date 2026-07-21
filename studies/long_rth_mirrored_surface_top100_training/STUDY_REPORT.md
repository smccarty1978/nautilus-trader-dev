# Study Report — Mirrored Long-Side Pure-Flip Surface Build + Top-100 Training

## Decision

**`LONG_SURFACE_TOP100_SIGNAL_STRONG_PARITY`**

The mirrored long-side (prevailing-bearish, `direction == -1`) checkpoint surface
was built for all six years, the frozen top-100 feature set was applied, and the
top-100 model's predictive quality is statistically indistinguishable from the
short-side bearish-flip benchmark on both the 2025 selection year and the sealed
2026 test year. All minimum-viable and strong-parity gates pass on the
**causally-corrected** data (see "Audit & remediation").

## Headline numbers (selected model = GBT, strict causal convention)

| Metric | Long (corrected) | Short-side benchmark |
|---|---:|---:|
| 2025 AUC (dev/select) | 0.6682 | 0.671 |
| 2026 AUC (sealed test) | 0.6512 | 0.670 |
| 2025 top-decile flip rate | 51.1% | 50.5% |
| 2026 top-decile flip rate | 53.7% | 50.5% |
| 2025 / 2026 top-decile lift | 1.94× / 1.91× | ~2× |
| 2026 monthly AUC (Jan–Apr) | 0.63 / 0.68 / 0.64 / 0.64 | — |
| Regime-level AUC (2025/2026) | 0.50 / 0.47 | ~0.50 (chance) |

Logreg (secondary): 2025 AUC 0.666, 2026 0.642. GBT selected by higher 2025 AUC.

**Gate outcomes** (`results/viability_gates.json`): minimum-viable PASS (all 5),
strong-parity PASS (all 5, incl. every 2026 month AUC > 0.58).

## Answers to the 12 required questions

1. **Was the direction==-1 surface built?** Yes — 6 years, 898,837 established+RTH
   bearish-regime checkpoints (2021 164,940 / 2022 189,071 / 2023 167,721 /
   2024 161,220 / 2025 163,397 / 2026 52,488 YTD), from the pre-existing 5s atlas
   (both directions) — **no atlas rebuild needed**. The prior POC's "three full
   pipelines" fear was based on searching for a materialized surface; the atlas
   substrate already held direction==-1 regimes with correct bearish excursions.
2. **Top-100 reused exactly?** Yes. `feature_source_sha256 6c6ceba7…`,
   `ordered_feature_list_sha256 f2a6db0b…`, verified identical to the prior
   `long_rth_pure_flip_top100_training` manifest.
3. **Which raw features expanded into encoded columns?** None. All 100 raw
   features are numeric (0 object-dtype columns, verified in the gate every year);
   no one-hot expansion was required or performed.
4. **Bullish-flip target built correctly?** Yes — pure arithmetic
   `bullish_regime_flip_within_300s = (confirm_flip_ns − observation_time)/1e9 ≤ 300`,
   the exact mirror of the short-side bearish label. 0 censored rows all years
   (`confirm_flip_ns` always defined for completed regimes). Independent of
   stop/PnL/timeout/entry/exit.
5. **Directional feature semantics verified?** Yes, with code proof
   (`results/directionality_audit.csv`): 44 center/slope features are
   regime-direction-relative (auto-bearish for this population — the same feats
   the short side used on its long regimes); 29 ohlcv-delta are absolute (no
   direction param on either side); 26 price features are absolute signed-distance;
   exactly **1** feature (`pct_levels_behind_trade`) is genuinely direction-
   normalized and is computed with `direction=+1` (long). The surface builder's
   self-validation guard independently re-derived the bearish-favorable excursion
   and matched the atlas `current_mfe` to 1e-9 at **10,253,579 checkpoints across both
   atlas sources, 0 failures** — a hard proof of correct directionality.
6. **Row counts & positive rates by year?** See `results/data_readiness.csv` /
   `label_quality_by_year.csv`. Positive rates 0.294/0.252/0.272/0.266/0.263/0.280
   (2021→2026) — stable, ~same ballpark as the short side (0.257 in 2021). The
   slightly higher long-side rate (bearish regimes revert to bullish a bit faster
   under upward market drift) is a small, expected asymmetry.
7. **2025 & 2026 AUC?** 0.6682 (2025) / 0.6512 (2026), GBT.
8. **Top-decile flip rates & lifts?** 51.1%/53.7% flip; 1.94×/1.91× lift.
   Bottom-decile 9.5%/12.5%; decile monotonicity 1.00 (2025), 0.988 (2026) — not
   inverted.
9. **2026 monthly AUC stable?** Yes: 0.63, 0.68, 0.64, 0.64 — all > 0.58.
10. **Closeness to short-side model?** Essentially identical: 2025 AUC within
    0.0028, 2026 within 0.019; top-decile flip within 0.6pp/3.2pp. And this is a
    **conservative** comparison — the short-side benchmark still carries the same
    inherited 1s look-ahead this study removed, so a like-for-like corrected short
    side would sit even closer.
11. **Which feature families mattered most?** Same structure as the short side:
    center/slope/alignment dominates (family |importance| 0.068), then price-level
    (0.019), then ohlcv-delta (0.0075). The #1 feature `aligned_price_minus_center_15m`
    is identical to the short side's rank-1. 9/25 of the long top-25 are in the
    short top-25; all 25 are in the short top-100.
12. **Strong enough to justify next studies?**
    - Long counter-regime entry tests: **Yes, at the same standing as the short
      side** — but note the regime-level AUC is ~0.50 (chance), identical to the
      short side. Like the short model, the edge is a **within-regime timing
      signal** (median lead time to bullish flip ~40–45 s), not a regime-selection
      signal. Any entry study must exploit it as timing inside qualified bearish
      regimes, not as a regime filter (mirrors `[[pure_flip_prediction_inconclusive]]`
      and `[[row_level_vs_entity_level_auc_rule]]`).
    - Short-exit warning tests: **Yes** — a symmetric bullish-flip probability is
      a natural early-warning signal for exiting shorts.
    - Reversal/counter-trade studies: **conditionally** — justified to prototype,
      but subject to the same unproven-economics caveat: this study did NO trade
      economics, stops, or NT validation (out of scope by design). Predictive
      parity ≠ monetizable edge (`[[flip_score_entry_policy_weak_but_useful]]`).

## Audit & remediation

A completion-gate `lookahead-auditor` pass found **1 CRITICAL + 2 WARNING**:
- **CRITICAL** — the feature-attach bar-snap inherited `searchsorted(..., side="right")-1`
  from the upstream short-side `attach_features.py`, inclusive of a bar at
  `ts_event == observation_time`. Because raw 1s bars are open-labelled
  (`[t, t+1s)`), that bar is still forming → up to 1 s look-ahead on the 56
  ohlcv+price features (the 44 atlas center features were always strict/clean).
  **Fixed**: strict `side="left"` snap matching the atlas convention, provenance
  invariant tightened to strict (`latest_source_ts_used < observation_time`).
  Attach + assemble + gate + train re-run on corrected data; every year now
  verified strict (min gap exactly 1 s, 0 equalities, 0 violations). **Impact was
  tiny** (2025 AUC 0.6713→0.6682, 2026 0.6539→0.6512), confirming the edge was
  never the look-ahead — it is carried by the always-clean center features (whose
  importance share actually rose after the fix).
- **WARNING W1** — silent `atlas.drop_duplicates` in assembly → replaced with a
  fail-loud duplicate-key check.
- **WARNING W2** — 3 `TIMING_UNVERIFIED` features (`regime_first_half_vol`,
  `regime_abs_delta_per_atr_moved`, `regime_price_change_atr`) inherited from the
  reduction study → disclosed in the gate verdict as a non-blocking residual,
  same treatment as the deployed short-side model.

A confirmatory re-audit after remediation returned **0 CRITICAL / 0 WARNING /
3 NOTE**, verifying each fix by independent recomputation from the artifacts (not
the implementer's logs) and finding no regressions (see `audit/audit.md`). The
mandatory audit gate is therefore cleared at 0 CRITICAL.

**Disclosed limitation**: the short-side benchmark this study compares against
still carries the same 1s look-ahead (it uses the un-fixed upstream attach), so
its 0.671/0.670 figures are mildly optimistic; the long-side comparison is
therefore conservative, and strong parity holds with margin.

## Scope honesty

No NautilusTrader, no MBP-1, no trade economics, no stop/exit/entry/threshold
optimization — none were in scope. This study establishes **predictive parity of
the mirrored long-side flip signal only**. Selection used 2025; 2026 was opened
only for sealed evaluation and never for any fit/selection/calibration decision.
