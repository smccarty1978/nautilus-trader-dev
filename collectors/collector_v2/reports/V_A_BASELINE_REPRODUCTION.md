# V_A Baseline Reproduction via Collector V2

V_A reference (1m HH/LL + momentum confirm, hold to opposing 1m regime flip) re-run through the new Collector V2 architecture for 2024 / 2025 / 2026.

**Baseline reference**: prior NT-validated V_A run in `studies/momentum_confirm_v1/results/nt_1m_momentum_<year>/`. Identical strategy logic; only the implementation differs (legacy vs new registry/aggregator/audit infrastructure).

## 2024

Snapshots: 14,350
Trades:    3,343

Provenance audit (must be all 0):

| TF | Violations |
|---|--:|
| 30s | 0 ✓ |
| 1m | 0 ✓ |
| 3m | 0 ✓ |
| 5m | 0 ✓ |

Trade performance — Collector V2 vs prior NT V_A baseline:

| Source | n | WR | Mean $ | Med $ | Avg Win | Avg Loss | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Collector V2 (this run) | 3,343 | 35.4% | $4.33 | $-130.00 | $557.09 | $-301.04 | 1.02 | $14,475 | $-46,130 |
| Prior NT V_A (baseline) | 3,343 | 35.2% | $5.64 | $-130.00 | $560.92 | $-297.49 | 1.03 | $18,840 | $-44,410 |

- Δ trade count: +0 (+0.0%)
- Δ mean $ / trade: **$-1.31**
- Δ total $: $-4,365

Snapshot mix:

- `bar1_check`: 7,175
- `regime_flip`: 7,175

Diagnostics:

- 1s_bars: 12,144,621
- 1m_bars: 357,715
- buckets_closed_30s: 713,417
- buckets_closed_1m: 357,713
- buckets_closed_3m: 119,273
- buckets_closed_5m: 71,564
- rth_flips: 7,175
- bar1_checks: 7,175
- confirmations_passed_hhll_mom: 3,343
- rejected_5m_misaligned: 0
- entries_filled: 3,343
- regime_exits: 3,343
- snapshots_emitted: 14,350

## 2025

Snapshots: 14,706
Trades:    3,313

Provenance audit (must be all 0):

| TF | Violations |
|---|--:|
| 30s | 0 ✓ |
| 1m | 0 ✓ |
| 3m | 0 ✓ |
| 5m | 0 ✓ |

Trade performance — Collector V2 vs prior NT V_A baseline:

| Source | n | WR | Mean $ | Med $ | Avg Win | Avg Loss | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Collector V2 (this run) | 3,313 | 34.2% | $16.57 | $-150.00 | $782.02 | $-384.80 | 1.07 | $54,880 | $-50,590 |
| Prior NT V_A (baseline) | 3,313 | 34.1% | $17.97 | $-150.00 | $783.68 | $-380.12 | 1.07 | $59,535 | $-53,020 |

- Δ trade count: +0 (+0.0%)
- Δ mean $ / trade: **$-1.41**
- Δ total $: $-4,655

Snapshot mix:

- `bar1_check`: 7,353
- `regime_flip`: 7,353

Diagnostics:

- 1s_bars: 12,171,792
- 1m_bars: 353,950
- buckets_closed_30s: 706,355
- buckets_closed_1m: 353,949
- buckets_closed_3m: 118,010
- buckets_closed_5m: 70,806
- rth_flips: 7,353
- bar1_checks: 7,353
- confirmations_passed_hhll_mom: 3,313
- rejected_5m_misaligned: 0
- entries_filled: 3,313
- regime_exits: 3,313
- snapshots_emitted: 14,706

## 2026

Snapshots: 4,264
Trades:    1,001

Provenance audit (must be all 0):

| TF | Violations |
|---|--:|
| 30s | 0 ✓ |
| 1m | 0 ✓ |
| 3m | 0 ✓ |
| 5m | 0 ✓ |

Trade performance — Collector V2 vs prior NT V_A baseline:

| Source | n | WR | Mean $ | Med $ | Avg Win | Avg Loss | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Collector V2 (this run) | 1,001 | 35.2% | $-19.15 | $-175.00 | $782.50 | $-454.65 | 0.93 | $-19,170 | $-29,920 |
| Prior NT V_A (baseline) | 1,001 | 35.2% | $-19.68 | $-180.00 | $781.72 | $-455.74 | 0.93 | $-19,700 | $-29,850 |

- Δ trade count: +0 (+0.0%)
- Δ mean $ / trade: **$0.53**
- Δ total $: $530.00

Snapshot mix:

- `bar1_check`: 2,132
- `regime_flip`: 2,132

Diagnostics:

- 1s_bars: 3,691,605
- 1m_bars: 103,240
- buckets_closed_30s: 205,406
- buckets_closed_1m: 103,239
- buckets_closed_3m: 34,532
- buckets_closed_5m: 20,730
- rth_flips: 2,132
- bar1_checks: 2,132
- confirmations_passed_hhll_mom: 1,001
- rejected_5m_misaligned: 0
- entries_filled: 1,001
- regime_exits: 1,001
- snapshots_emitted: 4,264

## Cross-year summary

| Year | n_snaps | n_trades_v2 | n_trades_prior | Δn | Mean $ V2 | Mean $ Prior | Δ Mean | Total V2 | Total Prior | Provenance OK |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 2024 | 14,350 | 3,343 | 3,343 | +0 | $4.33 | $5.64 | $-1.31 | $14,475 | $18,840 | ✓ |
| 2025 | 14,706 | 3,313 | 3,313 | +0 | $16.57 | $17.97 | $-1.41 | $54,880 | $59,535 | ✓ |
| 2026 | 4,264 | 1,001 | 1,001 | +0 | $-19.15 | $-19.68 | $0.53 | $-19,170 | $-19,700 | ✓ |

## Verdict

Provenance: ✓ all years 0 violations
Trade-count parity vs prior NT baseline (within 5%): ✓
