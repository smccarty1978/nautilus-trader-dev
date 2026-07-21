ADAPTIVE WALK-FORWARD STUDY:
COMPLETE

FINAL RESERVED BLOCK:
2026-03-01 through 2026-04-29

STATIC R4 FINAL EV LIFT:
$-4.28

BEST ADAPTIVE POLICY:
A4, 6m

BEST ADAPTIVE FINAL EV LIFT:
$2.70

BEST ADAPTIVE 95% CI:
($-3.27, $8.35)

BEST ADAPTIVE TOP-DECILE RUNNER RETENTION:
93.8%

BEST ADAPTIVE MATCHED-RANDOM P:
0.4040

MONTHS POSITIVE:
7/16

RETAINED-TRADE PARITY:
PASS

PROVENANCE AUDIT:
PASS

VERDICT:
INCONCLUSIVE

NEXT STEP:
Treat as a fragile/marginal result; do not deploy without further out-of-sample confirmation beyond this single reserved block.

---

## Decision criteria detail

| Criterion | Met |
|---|---|
| A4 EV lift > static R4 EV lift | YES |
| A4 EV lift > 0 (vs R0) | YES |
| top-decile runner retention >= 95% | no |
| matched-random empirical p <= 0.10 | no |
| most months neutral/positive | no |
| not driven by top 1-2 avoided losses | YES |
| no execution/provenance violations | YES |

Criteria met: 4/7

Note: the single best-performing adaptive policy overall (by EV lift vs R0, any family) is **a1_3m** at $4.77/eligible signal. The summary block above and the verdict are keyed to the best-performing **A4** window specifically (a4_6m), since the task's decision criteria are framed around A4 vs static R4 -- A1/A2 are reported in full in the tables below for comparison.

## Final reserved block (2026-03 .. 2026-04): all policies

| policy | eligible_signals | filled_trades | skip_rate | ev_per_eligible_signal | ev_per_filled_trade | net_pnl | win_rate | profit_factor |
|---|---|---|---|---|---|---|---|---|
| a1_3m | 1951 | 1667 | 0.1425 | -16.1097 | -18.8542 | -31430.0000 | 0.3377 | 0.9105 |
| a1_6m | 1951 | 1730 | 0.1102 | -18.0395 | -20.3439 | -35195.0000 | 0.3370 | 0.9039 |
| a4_6m | 1951 | 1789 | 0.0800 | -18.1881 | -19.8351 | -35485.0000 | 0.3376 | 0.9052 |
| a4_3m | 1951 | 1740 | 0.1051 | -19.0108 | -21.3161 | -37090.0000 | 0.3351 | 0.8984 |
| a1_12m | 1951 | 1811 | 0.0687 | -20.2435 | -21.8084 | -39495.0000 | 0.3346 | 0.8958 |
| a2_6m | 1951 | 1852 | 0.0477 | -20.3716 | -21.4606 | -39745.0000 | 0.3337 | 0.8967 |
| r0 | 1951 | 1945 | 0.0000 | -20.8842 | -20.9486 | -40745.0000 | 0.3332 | 0.8982 |
| a2_12m | 1951 | 1887 | 0.0297 | -21.0149 | -21.7276 | -41000.0000 | 0.3328 | 0.8953 |
| a4_12m | 1951 | 1849 | 0.0492 | -21.1123 | -22.2769 | -41190.0000 | 0.3348 | 0.8932 |
| a2_3m | 1951 | 1815 | 0.0666 | -21.4992 | -23.1102 | -41945.0000 | 0.3328 | 0.8895 |
| static_r2 | 1951 | 1879 | 0.0338 | -23.3803 | -24.2762 | -45615.0000 | 0.3342 | 0.8828 |
| static_r4 | 1951 | 1840 | 0.0538 | -25.1691 | -26.6875 | -49105.0000 | 0.3332 | 0.8723 |

## Pooled 2025 (Jan-Dec) results

| policy | eligible_signals | filled_trades | skip_rate | ev_per_eligible_signal | net_pnl | win_rate | profit_factor |
|---|---|---|---|---|---|---|---|
| a1_12m | 11680 | 10154 | 0.1258 | 2.7907 | 32595.0000 | 0.3356 | 1.0199 |
| a2_12m | 11680 | 10912 | 0.0609 | 2.2710 | 26525.0000 | 0.3324 | 1.0153 |
| a4_12m | 11680 | 10620 | 0.0859 | 2.2393 | 26155.0000 | 0.3346 | 1.0154 |
| a2_6m | 11680 | 11003 | 0.0531 | 1.9773 | 23095.0000 | 0.3324 | 1.0133 |
| a1_6m | 11680 | 10343 | 0.1096 | 1.7136 | 20015.0000 | 0.3326 | 1.0122 |
| a4_6m | 11680 | 10749 | 0.0748 | 1.2102 | 14135.0000 | 0.3326 | 1.0083 |
| static_r4 | 11680 | 10796 | 0.0708 | 1.0128 | 11830.0000 | 0.3340 | 1.0068 |
| static_r2 | 11680 | 11149 | 0.0406 | 0.0809 | 945.0000 | 0.3314 | 1.0005 |
| a2_3m | 11680 | 11022 | 0.0515 | -1.2898 | -15065.0000 | 0.3293 | 0.9914 |
| r0 | 11680 | 11623 | 0.0000 | -1.4217 | -16605.0000 | 0.3297 | 0.9910 |
| a1_3m | 11680 | 10382 | 0.1062 | -2.5959 | -30320.0000 | 0.3287 | 0.9819 |
| a4_3m | 11680 | 10743 | 0.0753 | -2.6537 | -30995.0000 | 0.3291 | 0.9820 |

## Paired bootstrap (final reserved block)

| policy | comparator | n_episodes | paired_ev_lift | ev_lift_ci_lo | ev_lift_ci_hi |
|---|---|---|---|---|---|
| a1_3m | r0 | 1951 | 4.7745 | -4.1672 | 13.1319 |
| a2_3m | r0 | 1951 | -0.6151 | -6.9914 | 5.1026 |
| a2_3m | static_r2 | 1951 | 1.8811 | -6.1124 | 9.7490 |
| a4_3m | r0 | 1951 | 1.8734 | -5.6484 | 8.7982 |
| a4_3m | static_r4 | 1951 | 6.1584 | -3.1550 | 16.0663 |
| a1_6m | r0 | 1951 | 2.8447 | -3.9928 | 9.2722 |
| a2_6m | r0 | 1951 | 0.5126 | -4.4209 | 4.9593 |
| a2_6m | static_r2 | 1951 | 3.0087 | -3.9749 | 10.5283 |
| a4_6m | r0 | 1951 | 2.6961 | -3.2731 | 8.3548 |
| a4_6m | static_r4 | 1951 | 6.9810 | -1.6147 | 16.2405 |
| a1_12m | r0 | 1951 | 0.6407 | -6.3199 | 6.4610 |
| a2_12m | r0 | 1951 | -0.1307 | -3.2829 | 2.8011 |
| a2_12m | static_r2 | 1951 | 2.3655 | -3.8033 | 9.3465 |
| a4_12m | r0 | 1951 | -0.2281 | -6.8405 | 4.9081 |
| a4_12m | static_r4 | 1951 | 4.0569 | -2.1017 | 10.6741 |

## Matched-random controls (final reserved block)

| block | policy | n_sims | real_ev_lift | random_median | random_p95 | fraction_random_ge_real | empirical_p_value |
|---|---|---|---|---|---|---|---|
| 2026_MarApr_final_reserved | a1_3m | 1000 | 4.7745 | 0.9828 | 8.0587 | 0.1890 | 0.1890 |
| 2026_MarApr_final_reserved | a2_3m | 1000 | -0.6151 | 1.3288 | 6.1761 | 0.7130 | 0.7130 |
| 2026_MarApr_final_reserved | a4_3m | 1000 | 1.8734 | 1.1468 | 7.1736 | 0.4300 | 0.4300 |
| 2026_MarApr_final_reserved | a1_6m | 1000 | 2.8447 | 1.2878 | 6.9585 | 0.3400 | 0.3400 |
| 2026_MarApr_final_reserved | a2_6m | 1000 | 0.5126 | 0.9892 | 4.9001 | 0.5750 | 0.5750 |
| 2026_MarApr_final_reserved | a4_6m | 1000 | 2.6961 | 1.8811 | 7.0142 | 0.4040 | 0.4040 |
| 2026_MarApr_final_reserved | a1_12m | 1000 | 0.6407 | -0.0564 | 3.9675 | 0.3950 | 0.3950 |
| 2026_MarApr_final_reserved | a2_12m | 1000 | -0.1307 | 0.3344 | 3.5615 | 0.5860 | 0.5860 |
| 2026_MarApr_final_reserved | a4_12m | 1000 | -0.2281 | 0.0487 | 3.6217 | 0.5400 | 0.5400 |

## Tail dependence (final reserved block)

| block | policy | full_ev_lift_per_episode | ev_lift_ex_top1_avoided_loss | ev_lift_ex_top2_avoided_losses | largest_avoided_loss | largest_skipped_winner | n_avoided_losses | driven_by_top2_pct |
|---|---|---|---|---|---|---|---|---|
| 2026_MarApr_final_reserved | static_r2 | -2.4962 | -3.1974 | -3.7840 | -1365.0000 | 3260.0000 | 46 | -51.5928 |
| 2026_MarApr_final_reserved | static_r4 | -4.2850 | -4.9974 | -5.4053 | -1385.0000 | 4500.0000 | 70 | -26.1461 |
| 2026_MarApr_final_reserved | a1_3m | 4.7745 | 3.9026 | 3.1221 | -1705.0000 | 3325.0000 | 192 | 34.6082 |
| 2026_MarApr_final_reserved | a2_3m | -0.6151 | -1.1538 | -1.6213 | -1050.0000 | 3325.0000 | 86 | -163.6036 |
| 2026_MarApr_final_reserved | a4_3m | 1.8734 | 1.0000 | 0.4618 | -1705.0000 | 2635.0000 | 140 | 75.3509 |
| 2026_MarApr_final_reserved | a1_6m | 2.8447 | 2.2897 | 1.8189 | -1085.0000 | 2345.0000 | 150 | 36.0606 |
| 2026_MarApr_final_reserved | a2_6m | 0.5126 | 0.0410 | -0.4105 | -920.0000 | 2200.0000 | 63 | 180.0821 |
| 2026_MarApr_final_reserved | a4_6m | 2.6961 | 2.1410 | 1.6701 | -1085.0000 | 2345.0000 | 112 | 38.0544 |
| 2026_MarApr_final_reserved | a1_12m | 0.6407 | 0.0641 | -0.4926 | -1125.0000 | 4500.0000 | 92 | 176.8788 |
| 2026_MarApr_final_reserved | a2_12m | -0.1307 | -0.5513 | -0.8235 | -820.0000 | 1335.0000 | 38 | -530.0576 |
| 2026_MarApr_final_reserved | a4_12m | -0.2281 | -0.7846 | -1.1827 | -1085.0000 | 4500.0000 | 67 | -418.5091 |

## Runner retention (final reserved block, top-decile)

| block | policy | tier | n_runner_trades | n_retained | retention_rate | largest_skipped_winner_in_tier |
|---|---|---|---|---|---|---|
| 2026_MarApr_final_reserved | static_r2 | top10pct | 194 | 185 | 0.9536 | 3260.0000 |
| 2026_MarApr_final_reserved | static_r4 | top10pct | 194 | 181 | 0.9330 | 4500.0000 |
| 2026_MarApr_final_reserved | a1_3m | top10pct | 194 | 172 | 0.8866 | 3325.0000 |
| 2026_MarApr_final_reserved | a2_3m | top10pct | 194 | 182 | 0.9381 | 3325.0000 |
| 2026_MarApr_final_reserved | a4_3m | top10pct | 194 | 176 | 0.9072 | 2635.0000 |
| 2026_MarApr_final_reserved | a1_6m | top10pct | 194 | 176 | 0.9072 | 2345.0000 |
| 2026_MarApr_final_reserved | a2_6m | top10pct | 194 | 184 | 0.9485 | 2200.0000 |
| 2026_MarApr_final_reserved | a4_6m | top10pct | 194 | 182 | 0.9381 | 2345.0000 |
| 2026_MarApr_final_reserved | a1_12m | top10pct | 194 | 183 | 0.9433 | 4500.0000 |
| 2026_MarApr_final_reserved | a2_12m | top10pct | 194 | 187 | 0.9639 | 1335.0000 |
| 2026_MarApr_final_reserved | a4_12m | top10pct | 194 | 187 | 0.9639 | 4500.0000 |

## Provenance / execution audit

```json
{
  "critical_execution_violations": 0,
  "critical_provenance_violations": 0,
  "retained_trade_parity_pct": 100.0,
  "retained_trade_parity_pass": true,
  "missing_pnl_for_filled_trades": 0,
  "duplicate_episode_ids": 0,
  "duplicate_trade_fills": 0,
  "unresolved_episodes_per_policy": 68,
  "unresolved_identical_across_all_policies": true,
  "insufficient_data_folds": 0,
  "total_folds": 48,
  "n_policies": 12,
  "n_eligible_episodes": 15629,
  "assertions": {
    "critical_execution_violations == 0": true,
    "critical_provenance_violations == 0": true,
    "retained_trade_parity == 100%": true,
    "missing_pnl == 0 for filled trades": true,
    "duplicate_episode_ids == 0": true
  },
  "all_assertions_pass": true
}
```

Retained-trade parity overall: 100.0000% (0 mismatches across 159084 retained trades)

## Model quality (validation AUC by fold)

| window_name | mean | min | max | count |
|---|---|---|---|---|
| 12m | 0.5257 | 0.4691 | 0.6004 | 16 |
| 3m | 0.5101 | 0.4463 | 0.5722 | 16 |
| 6m | 0.5173 | 0.4683 | 0.5637 | 16 |

Note: fold-level validation AUCs cluster near 0.50 (little to no genuine out-of-sample discrimination month-to-month), consistent with this project's prior finding that this feature family's OOS AUC is weak and unstable (see memory: static_p4_robustness_real_but_fragile, v_a_1m_flip_signal_class_dead). Any adaptive EV lift found here should be read against that backdrop.
