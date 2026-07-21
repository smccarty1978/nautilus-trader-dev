# 2025-2026 Short-RTH Entry Surface — Reconciliation Smoke

## Decision: `BACKFILL_RECONCILIATION_PASS`

Score-independent surface builder (`entry_surface.py`) reconciled 
against the known W4-threshold-crossing candidate population.

| Year | Crossing candidates | Expected control | Gate | Missing from surface | Mismatched identity |
|--|--:|--:|--|--:|--:|
| 2025 | 650 | 650 | PASS | 0 | 0 |
| 2026 | 222 | 222 | PASS | 0 | 0 |

## Attrition (checkpoints / distinct regimes)

### 2025

| Stage | Checkpoints | Distinct regimes |
|--|--:|--:|
| all | 3934266 | 27137 |
| bullish_regime | 2014636 | 13566 |
| established | 698801 | 5822 |
| rth | 198255 | 1678 |
| valid_fill | 198255 | 1678 |
| rth_boundary_divergence | 0 | 0 |

### 2026

| Stage | Checkpoints | Distinct regimes |
|--|--:|--:|
| all | 1289840 | 8921 |
| bullish_regime | 653438 | 4463 |
| established | 223785 | 1870 |
| rth | 63021 | 532 |
| valid_fill | 63021 | 532 |
| rth_boundary_divergence | 0 | 0 |

## Runtime

- 2025: 152.8s
- 2026: 28.7s

## Notes

- The surface builder never reads a W4 score. The crossing comparator reads the frozen score for 2025-2026 only, purely to prove the surface contains every known crossing opportunity with identical fill identity (ts/px/ATR).
- `gate_candidate` (imported unmodified from `fable5_short_rth_threshold_ladder/run_ladder.py`) independently checks the crossing population itself against the audited multi-candidate-reentry 650/222 population.