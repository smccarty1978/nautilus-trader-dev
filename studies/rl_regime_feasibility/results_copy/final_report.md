# RL Regime Feasibility Study — Final Report

## Study Design
- **Signal**: 1m regime flip (EMA3/EMA9 on NQ.v.0 1s bars)
- **Observation**: every 5 seconds from flip through episode end
- **Features**: 28 features across 5 families (path, volatility/volume, momentum, multi-TF regime, structural)
- **Horizons**: 5s, 15s, 30s, 60s, 120s, 300s
- **Catastrophic stop**: 1.50 × ATR (from flip close)
- **Episode max duration**: 30 minutes
- **Cost**: $5 RT base commission

## Data Splits
| Period | Dates | Role |
|--------|-------|------|
| Train | 2024-01-01 to 2024-12-31 | Model fitting |
| Validation | 2025-01-01 to 2025-02-28 | Threshold selection |
| Historical test | 2025-03-01 to 2025-05-31 | Gate 2 evaluation |

## Gate 1: Conditional Predictability
**Criterion**: val_AUC >= 0.54 on at least 2 horizons

**Result**: Best val_AUC=0.5634, passing horizons=9

**Verdict**: PASS ✓

## Gate 2: Causal Policy vs Oracle
**Criterion**: best causal policy EV >= 50% of oracle EV on test set

**Oracle test EV**: +166.82/episode

**Result**: Best policy=ml_ridge_log_h300s  EV/ep=-6.46  (-6.5% of oracle)

**Verdict**: FAIL ✗

## RL Recommendation
**DO NOT PROCEED** — Insufficient predictability or policy headroom. OHLCV features on 1m regime flip are not sufficient. Next step: order flow / footprint data as additional feature families.

## Key Caveats
- Models trained on OHLCV-derived features only; no order flow
- Bar execution mode (1s bar open fills) may overstate slightly vs tick execution
- Regime-capped labels assume exact flip-time exit; real exit has 5s delay
