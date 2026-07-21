# Smoke Parity Report — Jan 8-15, 2024

**Window**: 2024-01-05 (warmup) to 2024-01-15 23:59:59 UTC.
**Strategy**: Collector V2 V_A reference (1m HH/LL + momentum
confirm, hold to opposing 1m regime flip).
**Modes**: Mode 1 (research / no orders) and Mode 2 (trading), both
running the same `CollectorV2Strategy` code path.

## Result

✅ **PASS** — Mode 1 and Mode 2 emit byte-identical snapshots; zero
provenance violations across all 4 timeframes.

## Diagnostics

| Counter | Mode 1 | Mode 2 |
|---|--:|--:|
| 1s bars processed | 316,486 | 316,486 |
| 1m bars seen | 9,419 | 9,419 |
| Buckets closed — 30s | 18,822 | 18,822 |
| Buckets closed — 1m | 9,419 | 9,419 |
| Buckets closed — 3m | 3,140 | 3,140 |
| Buckets closed — 5m | 1,884 | 1,884 |
| RTH flips | 183 | 183 |
| Bar+1 confirmation checks | 183 | 183 |
| Confirmations passed (HH/LL + momentum) | 75 | 75 |
| Snapshots emitted | 366 | 366 |
| Entries filled | 0 | 75 |
| Regime exits | 0 | 75 |
| Runtime (s) | 5.4 | 5.5 |

## Provenance

`last_<tf>_close_ts <= decision_ts` checked on every snapshot row.

| TF | Mode 1 violations | Mode 2 violations |
|---|--:|--:|
| 30s | **0** | **0** |
| 1m | **0** | **0** |
| 3m | **0** | **0** |
| 5m | **0** | **0** |

Total provenance proofs verified: 366 × 4 × 2 = **2,928 zero-violation checks**.

## Snapshot parity (Mode 1 vs Mode 2)

| Metric | Value |
|---|--:|
| Joined on (decision_ts, kind, bar_ts_event) | — |
| Matched rows | **366 / 366** |
| Only in Mode 1 | 0 |
| Only in Mode 2 | 0 |
| Columns compared (excluding `event_id` and `became_trade`) | 48 |
| Mismatched columns | **0** |

## Trade summary (Mode 2 only)

75 trades over 6 RTH days (Jan 8 / 9 / 10 / 11 / 12 / 15 — Jan 13/14
weekend). All trades had a snapshot row with `became_trade=True`
linked via `event_id` to the bar+1 confirmation that produced the
entry decision.

## Foundation tests

10 / 10 unit tests pass (`collectors/collector_v2/tests/test_provenance.py`):

T1 monotonic-update guard · T2 audit raises on violation · T3 no
partial closes · T4 engine writes only on close · T5 boundary 09:01
· T6 boundary 09:04 · T7 boundary 09:05 · T8 frozen state · T9
micro-feed close_ts progression · T10 NT-arrival semantics (1s
causality buffer = exactly 1s)

## Architecture confirmation

The pass demonstrates:

- The same code path produces the same snapshots whether or not
  trades are executed.
- The registry/aggregator/engine chain is causally correct under
  real NT timing (1m bar event arrives BEFORE the 1s bar that
  triggers the 1m bucket close; V_A logic correctly drives off the
  1s trigger bar's `ts_init`).
- 3m and 5m timeframes are first-class — provenance audited every
  row, no leakage of in-progress buckets.
- The 1s causality buffer (≥1s between calendar close and NT
  arrival) is the natural enforcement mechanism for the
  `close_ts <= decision_ts` invariant.

## Files

- Mode 1 snapshots: `collectors/collector_v2/results/smoke_jan2024/mode1_research/snapshots.parquet`
- Mode 2 snapshots: `collectors/collector_v2/results/smoke_jan2024/mode2_trading/snapshots.parquet`
- Mode 2 trades: `collectors/collector_v2/results/smoke_jan2024/mode2_trading/trades.parquet`
- Diag JSON: `collectors/collector_v2/results/smoke_jan2024/{mode1_research,mode2_trading}/diag.json`
- Full report JSON: `collectors/collector_v2/results/smoke_jan2024/smoke_report.json`
