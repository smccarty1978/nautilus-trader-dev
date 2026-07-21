# failure_mode_report.md

- Baseline pooled ppt $-25.78 (n 102,065).
- Best combined: ml40_hccomb pooled ppt $-42.14.
- ML filter removes 30-50% of trades but per-trade expectancy is essentially unchanged (baseline -$25.8/tr; ml20 -$24.5; ml40 -$25.1). It shrinks the loss by trading less, NOT by selecting positive-EV entries. Model B is not a positive-EV entry gate (corroborates post_bar3_survivor_opportunity).
- hC management: sizing-UP on high-hC is the single most damaging rule (hc_sizing -$38.5/tr, Δ-$1.30M) — confirms hC-high is the WORST cohort, so doubling it amplifies losses. Only low-health collapse-reduce helps marginally (hc_collapse Δ+$95k, -$24.9/tr) but stays deeply negative. DETER action ~inert. Combined is worst (sizing dominates).
- They do NOT combine constructively: ml40_hccomb -$42.1/tr is worse than either component alone.
- Any strategy net-positive in BOTH 2025 and 2026: **False** (every variant negative every year).
- No deployable candidate. Least-bad = ml20 / hc_collapse (~-$24.5 to -$24.9/tr pooled) — still deeply unprofitable, not carry-forward material.

# FINAL VERDICT

**NO — fails OOS under corrected NT execution**

1. Does Model B provide useful entry selection after costs? — see ml_entry_filter_report (ppt vs baseline).
2. Does hC improve trade management after costs? — see hc_management_report Δnet.
3. Do they combine constructively? — see combined_strategy_report.
4. Robust in both 2025 and 2026? — see OOS-focus table (both>0 column).
5. Single best candidate to carry forward: NONE is deployable. Mechanically least-bad is hc_collapse (low-health reduce, the only +Δnet rule) or ml20, but both are ~-$24/tr — deeply negative. Do not carry forward on OHLCV-derived signals.