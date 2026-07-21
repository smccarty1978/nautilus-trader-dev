# HH/LL Tick-NT — Guarded vs Unguarded Comparison

Compares the original tick-NT HH/LL run against a version with live-tradable guardrails:

- **No new entries after 14:45 CT** (no_entry_after_min_ct=885)
- **Force flat at 14:58 CT** (force_flat_at_min_ct=898)

Both HH/LL and baseline (regime-only) variants are run with and without guardrails for clean attribution.

Window: NQ RTH Feb-Sep 2025, $5 commission, tick-driven execution

## Diagnostic counters

| Counter | hhll_unguarded | baseline_unguarded | hhll_guarded | baseline_guarded |
|---|---|---|---|---|
| entries_filled | 7,717 | 7,717 | 5,043 | 5,043 |
| entries_rejected | 136 | 136 | 97 | 97 |
| rejected_after_no_entry_cutoff | 0 | 0 | 2,716 | 2,716 |
| regime_exits | 4,215 | 7,716 | 2,682 | 5,020 |
| hhll_armed | 4,305 | 0 | 2,884 | 0 |
| hhll_exits | 3,501 | 0 | 2,357 | 0 |
| force_flat_exits | 0 | 0 | 4 | 23 |

## Headline economics — NQ RTH Feb-Sep 2025

| Run | n | WR | Mean $ | PF | Total $ | Max DD | Med Hold s | Avg Win | Avg Loss |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **hhll_unguarded** | 2,149 | 46.0% | $5.88 | 1.03 | $12,640 | $-33,765 | 391 | $463.16 | $-384.92 |
| **baseline_unguarded** | 2,149 | 33.1% | $13.30 | 1.05 | $28,590 | $-38,040 | 631 | $777.72 | $-366.72 |
| **hhll_guarded** | 2,054 | 45.9% | $6.54 | 1.03 | $13,425 | $-30,745 | 393 | $465.62 | $-384.86 |
| **baseline_guarded** | 2,054 | 33.2% | $11.98 | 1.05 | $24,605 | $-34,065 | 631 | $772.05 | $-366.35 |

## Δ HH/LL guarded − HH/LL unguarded

- Trade count: 2,054 vs 2,149 (-95 from cutoffs)
- Mean $/trade: $6.54 vs $5.88 ($0.65)
- Total $: $13,425 vs $12,640 ($785.00)
- WR: 45.9% vs 46.0%

## HH/LL overlay impact under guardrails

- HH/LL guarded: $6.54/trade, $13,425 total
- Baseline guarded: $11.98/trade, $24,605 total
- **Δ (HH/LL − baseline) under guardrails**: $-5.44/trade, $-11,180 total

## Exit reason mix — HH/LL guarded

- **regime**: 1,123 trades (54.7%), mean $-169.76, WR 15.6%
- **hhll_protect**: 927 trades (45.1%), mean $204.77, WR 82.4%
- **force_flat**: 4 trades (0.2%), mean $3,561, WR 100.0%

## Forensic — top-5 worst-slip contribution (from prior audit)

Note: positive slip = A FAVORABLE vs first-cross. So top-5 'worst' here is actually FAVORABLE to A. Adverse-tail (large negative slip) is what would hurt A.

Top-5 most FAVORABLE slips for A:
- 2025-09-18 08:54:31 CT, slip +467 ticks ($2,335), min→RTH-close -366
- 2025-04-08 14:27:38 CT, slip +231 ticks ($1,155), min→RTH-close -33
- 2025-03-20 09:07:01 CT, slip +164 ticks ($820.00), min→RTH-close -353
- 2025-03-11 09:00:08 CT, slip +84 ticks ($420.00), min→RTH-close -360
- 2025-04-14 08:51:20 CT, slip +67 ticks ($335.00), min→RTH-close -369

Top-5 most ADVERSE slips for A:
- 2025-03-20 13:56:31 CT, slip -115 ticks ($-575.00), min→RTH-close -64
- 2025-03-20 12:43:35 CT, slip -76 ticks ($-380.00), min→RTH-close -137
- 2025-06-18 14:41:01 CT, slip -76 ticks ($-380.00), min→RTH-close -19
- 2025-06-19 09:58:03 CT, slip -72 ticks ($-360.00), min→RTH-close -302
- 2025-06-09 14:50:00 CT, slip -59 ticks ($-295.00), min→RTH-close -10

- Total top-5 favorable: $5,065
- Total top-5 adverse: $-1,990

## Final verdict — guardrails do NOT rescue HH/LL

**Direct answer to the user's question:**

> Is the HH/LL failure caused by normal stop execution, or by a small number of non-tradable/session-gap/data-quality events?

**Answer: Normal stop execution. The forensic + guarded re-run rules out session/halt/data-quality artifacts as the cause.**

### Forensic evidence (from prior audit)

Across 1,051 crossed armed trades on Feb-Sep 2025 RTH:
- **0 trades held past 16:00 CT** (ETH close)
- **0 trades crossed an ETH session boundary**
- **0 trades after 15:00 CT** (RTH close)
- **0 tick gaps > 1s** near high-slip events
- **0 tick gaps > 60s** (no halts)
- High-slip events occurred during **normal trading hours**, median 10:31 CT

The 467-tick worst slip happened at 08:54 CT — peak liquidity. The next tick was 0.01s later. Not a data anomaly; just a fast favorable mean-reversion that A's reactive monitor benefited from.

### Guarded re-run economics

Even with **no entries after 14:45 CT** and **force flat at 14:58 CT**:

| Run | n | Mean $ | Total $ | PF |
|---|--:|--:|--:|--:|
| HH/LL unguarded | 2,149 | +$5.88 | +$12,640 | 1.03 |
| HH/LL guarded | 2,054 | +$6.54 | +$13,425 | 1.03 |
| Baseline unguarded | 2,149 | +$13.30 | +$28,590 | 1.05 |
| Baseline guarded | 2,054 | +$11.98 | +$24,605 | 1.05 |

**HH/LL overlay impact under guardrails: -$5.44/trade vs baseline.** The unguarded gap was -$7.42/trade. Guardrails reduce the gap by $2/trade — within noise. **The overlay still HURTS even under live-tradable conditions.**

### Diagnostic stats
- 95 trades cut by no-entry cutoff (4.4% of population)
- Only 4 force-flat exits in HH/LL run (most trades resolved before 14:58 anyway)
- Median hold time unchanged (393s guarded vs 391s unguarded)
- HH/LL fire rate unchanged (45.1% guarded vs 45.1% unguarded)

### Conclusion

Three independent tests have now confirmed the same answer:
1. **Initial tick-NT validation**: HH/LL +$5.88 vs baseline +$13.30 → overlay hurts by $7
2. **Attribution audit**: A and C_realistic equivalent (Δ -$6/trade); the +$54 tape-replay edge is the C_strict − C_realistic gap, which is unrealizable
3. **Forensic + guardrails**: No session/halt/gap artifacts. Guardrails don't change the picture (Δ improves only $2 → still -$5.44/trade)

**The HH/LL rule does not have a deployable edge.** The tape-replay's +$54/trade was a fill-convention artifact (assumed exits at exactly protect_px, which no real broker delivers). This is now triple-confirmed.

User's commitment was: *"If guarded results still fail, I'll accept it."* Guarded results failed. Branch confirmed dead.

### Methodology lesson (now in MEMORY.md as critical rule)

Tape-replay's "fill at trigger" convention overstates ALL trigger-based exit economics by a structural multiplier. Required: tick-NT validation as deployment gate for ANY rule that exits at intra-bar trigger levels (hard SL, trailing stops, lock-percent rules, target prices). The 36-rule offline study used this convention; ALL of them likely have similar artifacts.

## Files

- This report: `studies/v_a_exit_recon/results/HHLL_GUARDED_COMPARE.md`
- Forensic detail: `studies/v_a_exit_recon/results/HHLL_FORENSIC_SLIPPAGE.md`
- Attribution audit: `studies/v_a_exit_recon/results/HHLL_ATTRIBUTION_AUDIT.md`
- Original tick validation: `studies/v_a_exit_recon/results/TICK_NT_VALIDATION_REPORT.md`
- Per-trade audit data: `studies/v_a_exit_recon/results/hhll_forensic_audit_full.parquet`
- Strategy + guardrails: `collectors/collector_v2/strategy.py`
