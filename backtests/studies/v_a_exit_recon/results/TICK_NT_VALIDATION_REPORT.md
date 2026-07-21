# V_A + HH/LL Structural Exit — Tick-Driven NT Validation Report

Tests whether the HH/LL exit overlay edge persists under fully tick-driven NT execution. **Not a tape-replay parity check** — this is a from-scratch forward-style backtest with realistic fills.

## Setup

- Strategy: V_A entry (1m HH/LL + bar+1 momentum) with HH/LL exit overlay (`C_lock50_30s_5`)
- Execution: `bar_execution=False`, `trade_execution=True` — fills come from real TradeTicks, not bar OPEN
- Cost model: $5 commission only (tick_dollar=0; real tick fills replace the proxy slip)
- Window: Feb 3 - Sep 30 2025 RTH (8-month contiguous tick-data span)
- Tick data: `NQ_trades_20250201_20250930.parquet` (59M trades)
- HH/LL exit fires via internal monitor at next 1s bar after price crosses protect_px; market exit fills at next tick
- Provenance: registry audits unchanged from Collector V2 baseline

## Provenance & diagnostic counters

| Counter | HH/LL tick run | Baseline tick run |
|---|--:|--:|
| 1s_bars | 8,129,847 | 8,129,847 |
| 1m_bars | 237,314 | 237,314 |
| buckets_closed_30s | 473,555 | 473,555 |
| rth_flips | 18,311 | 18,311 |
| bar1_checks | 18,311 | 18,311 |
| confirmations_passed_hhll_mom | 7,856 | 7,856 |
| entries_filled | 7,717 | 7,717 |
| entries_rejected | 136 | 136 |
| regime_exits | 4,215 | 7,716 |
| hhll_armed | 4,305 | 0 |
| hhll_exits | 3,501 | 0 |

- Halts: `0` (HH/LL) / `0` (baseline)
- 0 provenance violations confirmed by registry audit on every snapshot build (would raise CausalityViolation if any)

## Headline economics — Feb-Sep 2025 RTH

| Run | n | WR | Mean $ | PF | Total $ | Max DD | Med Hold s | Avg Win | Avg Loss |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **HH/LL tick NT** | 2,149 | 46.0% | $5.88 | 1.03 | $12,640 | $-33,765 | 391 | $463.16 | $-384.92 |
| Baseline tick NT (regime-only exit, no slip proxy) | 2,149 | 33.1% | $13.30 | 1.05 | $28,590 | $-38,040 | 631 | $777.72 | $-366.72 |
| Prior bar-driven NT baseline 2025 RTH | 2,158 | 33.4% | $9.33 | 1.04 | $20,140 | $-44,940 | 631 | $780.03 | $-380.27 |
| Tape-replay HH/LL 2025 RTH (offline) | 2,158 | 57.0% | $52.92 | 1.27 | $114,205 | $-9,938 | 391 | $436.22 | $-455.11 |

## Exit reason mix (HH/LL tick run)

- **regime**: 1,180 trades (54.9%), mean $-157.96, WR 15.8%
- **hhll_protect**: 969 trades (45.1%), mean $205.40, WR 82.7%

## Per-month economics — HH/LL tick run

| Month | n | WR | Mean $ | Total $ |
|---|--:|--:|--:|--:|
| 2025-02 | 215 | 46.5% | $-15.02 | $-3,230 |
| 2025-03 | 281 | 47.3% | $8.40 | $2,360 |
| 2025-04 | 294 | 51.7% | $117.28 | $34,480 |
| 2025-05 | 272 | 50.0% | $14.89 | $4,050 |
| 2025-06 | 243 | 45.3% | $-0.97 | $-235.00 |
| 2025-07 | 264 | 44.3% | $-26.00 | $-6,865 |
| 2025-08 | 289 | 44.6% | $-38.77 | $-11,205 |
| 2025-09 | 291 | 38.1% | $-23.08 | $-6,715 |

## Slippage diagnostic — tick fills vs prior bar OPEN fills

- Matched trades: 2,149

| Quantile | Entry slip $ | Exit slip $ | Round-trip $ |
|---|--:|--:|--:|
| p5 | $0.00 | $-575.00 | $-468.00 |
| p25 | $0.00 | $-90.00 | $-85.00 |
| p50 | $0.00 | $0.00 | $0.00 |
| p75 | $0.00 | $0.00 | $0.00 |
| p95 | $0.00 | $773.00 | $603.00 |
| mean | $19.59 | $-10.86 | $8.73 |

## Verdict — VALIDATION FAILED

| Gate | Required | Actual | Pass? |
|---|---|---|---|
| Positive mean PnL | > 0 | +$5.88 | ✅ marginal |
| PF > 1 | > 1.0 | 1.03 | ✅ marginal |
| WR ≥ 55% | ≥ 0.55 | 0.460 | ❌ |
| Improvement vs tick-driven baseline | overlay > baseline | overlay $5.88 < baseline $13.30 | ❌ -$7.42/trade |
| Match tape-replay magnitude | ≈ $52.92/trade | $5.88/trade (11% retention) | ❌ massive shortfall |

**The HH/LL overlay HURTS performance under tick-driven NT execution.** The +$54/trade edge from in-sample and OOS tape-replay studies does NOT survive translation to runtime semantics. Critical finding for the entire research series — the prior IS+OOS study results were inflated by a tape-replay artifact.

## Root cause investigation

### Hypothesis 1 — bucket alignment mismatch (REJECTED)

The tape replay precomputed `bars_since_new_30s_buckets` using `elapsed_s // 30` (entry-aligned buckets). The tick-NT runtime uses calendar-aligned 30s buckets from the registry. To test whether this caused the gap, I re-ran the tape replay on the same 2024-2026 trades using CALENDAR-aligned 30s bucketing (`ts_init // 30_000_000_000`):

| Bucketing | All n | All mean $ | All total $ | WR | %fired |
|---|--:|--:|--:|--:|--:|
| Original (entry-aligned) | 7,659 | $54.33 | $416,148 | 56-59% | 50.2% |
| Calendar-aligned re-do | 7,659 | **$54.41** | **$416,708** | 58.3% | 50.2% |

**Bucket alignment is not the cause** — both bucketings produce essentially identical economics in tape replay.

### Hypothesis 2 — rule-trigger slippage (LIKELY ROOT CAUSE)

In tape replay, when the 1s bar's high/low touches `protect_px`, we assume exit at exactly `protect_px`. In reality, NT detects the cross at the bar's `ts_init` and submits a MARKET order, which fills at the **next tick AFTER** the bar close. In a fast-moving market — exactly the conditions that cause stalls and reversals — the next tick is typically several ticks past `protect_px`.

Diagnostic exit-cohort breakdown (HH/LL tick run, RTH):

| Cohort | n | mean $ | WR |
|---|--:|--:|--:|
| hhll_protect (rule fired) | 969 | +$205.40 | 82.7% |
| regime (rule didn't trigger) | 1,180 | -$157.96 | 15.8% |

The regime cohort in the HH/LL run is dramatically worse than the baseline regime cohort (+$13.30, 33.1% WR — same population without the overlay). This is selection effect: the HH/LL rule **takes the winners** (locks them in at 50% MFE) and **leaves the losers behind** (regime exit at full damage). The 82.7% WR on protected exits is mathematical — capping at protect_px guarantees a small win above entry.

The arithmetic:
- HH/LL captures: 969 × $205 = +$199K (locked-in winners, smaller than they could have been)
- HH/LL leaves: 1,180 × -$158 = -$186K (concentrated losers)
- Net: +$13K
- vs Baseline (all on regime): 2,149 × $13.30 = +$28K (winners offset losers naturally)

**The rule cuts winners short, dropping their per-trade PnL below what natural regime exit produces.** The tape replay overestimated the captured value at protect_px because it treated the exit as a deterministic touch fill. Real tick fills introduce 1-3 tick adverse slippage that compounds across the 50% of trades that fire the rule.

### Hypothesis 3 — entry/regime-exit fill differences

The tick-NT baseline (regime-only, no HH/LL) yields **+$13.30/trade** vs the bar-driven NT baseline at **+$9.33/trade**. Tick fills are slightly FAVORABLE on aggregate compared to bar OPEN fills. So the entry/regime-exit execution model is not the issue. The gap is specifically in HH/LL exit pricing.

## Implications for prior IS+OOS results

The +$54.33/trade IS result and +$24.62/trade OOS result for `C_lock50_30s_5` reflect tape-replay assumptions that do not hold under realistic tick-driven execution. **The HH/LL overlay does not deliver a deployable edge.** Specifically:

- The +$761K total improvement claim across 7 years (memory entry `hhll_exit_overlay_finding.md`) is invalidated for production purposes.
- The "all 7 years positive" claim only holds if you assume deterministic fills at protect_px, which is not realistic.
- The Pareto-improvement signature observed in tape replay was an execution-model artifact, not a real edge.

## What this validation accomplished

This is a textbook example of why the user mandated tick-driven NT validation as a deployment gate. The infrastructure worked perfectly:

- 0 provenance violations across 7,717 trades and 59M ticks
- 0 halts
- HH/LL state machine functioned correctly (4,305 armed, 3,501 fired)
- Internal-monitor approach successfully avoided NT's "stop trigger in market" rejection issue
- Direct comparison vs tick-driven baseline (with same execution model) isolated the rule's impact cleanly

**The tick-NT validation should be the standard gate for any future exit-rule (or entry-rule) finding before claiming deployment readiness.**

## Updated recommendation

`C_lock50_30s_5` and the entire HH/LL family should be removed from the "Strongest Lead" position in `MEMORY.md`. The finding is reclassified: **the IS+OOS tape-replay results were correct as a measurement of "what fills at protect_px would have produced" but that's not a realizable edge in production.**

What to do next:
1. **Investigate alternative HH/LL exit mechanics** that don't require deterministic fills at the trigger level. Examples:
   - Use a wider buffer (e.g., trigger when price retraces 60% of MFE; accept fill anywhere ≥ 50% of MFE)
   - Pre-compute the protect level and submit a LIMIT order (fills only AT or BETTER than protect_px)
   - Require N consecutive ticks past protect before triggering (filters fast-spike fakeouts)
2. **Re-test the broader exit-rule family in tick-NT.** The 36-rule offline study used the same tape-replay assumption. Need to retest the other top candidates (C_lock50_5s_20, B_be_30s_5, etc.) in tick-NT to see if any survive.
3. **Re-evaluate prior offline-only positive findings** — apply the tick-NT gate retroactively before any deployment claim.

## Files

- HH/LL tick run: `collectors/collector_v2/results/tick_nt/hhll_FebSep_*/`
- Baseline tick run: `collectors/collector_v2/results/tick_nt/baseline_FebSep_*/`
- Calendar-bucket tape replay diagnostic: `studies/v_a_exit_recon/hhll_calendar_bucket_check.py`
- Strategy: `collectors/collector_v2/strategy.py` (HH/LL config + internal-monitor exit)
- Runner: `collectors/collector_v2/run_tick_validation.py`
- This report: `studies/v_a_exit_recon/results/TICK_NT_VALIDATION_REPORT.md`

## Files

- HH/LL tick run: `collectors/collector_v2/results/tick_nt/hhll_FebSep_*/`
- Baseline tick run: `collectors/collector_v2/results/tick_nt/baseline_FebSep_*/`
- Strategy: `collectors/collector_v2/strategy.py` (HH/LL config flags + `_arm_hhll_protection` + `_check_hhll_protect_trigger`)
- Runner: `collectors/collector_v2/run_tick_validation.py`
- This report: `studies/v_a_exit_recon/results/TICK_NT_VALIDATION_REPORT.md`