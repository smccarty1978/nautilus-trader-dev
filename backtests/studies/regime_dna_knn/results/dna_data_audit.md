# DNA Pipeline Data Audit
**Overall: ALL PASS**


- PASS — ATR floor bounds payoff (no 90-ATR blow-ups). max |pt200 gross| = $8,090 (a 2-ATR target at floored ATR is bounded).
- PASS — atr_norm_at_flip strictly positive. min=0.534
- PASS — Session features are populated (not stubbed). vwap-dist std=8.107
- PASS — pt050_sl025 hit rate plausible. hit=0.336
- PASS — pt100_sl050 hit rate plausible. hit=0.328
- PASS — pt200_sl100 hit rate plausible. hit=0.284
- PASS — race bars strictly positive. min bars=0.03
- PASS — regime_id aligns with atlas state_rows. 143,560 shared regime_ids (merge feasible)
- PASS — bars 1-4 use uniform archetype prob (1/K). K=4
- PASS — archetype prob vectors sum to ~1. mean sum=1.0000
- PASS — OOS scores only from 2025/2026. OOS years=[np.int64(2025), np.int64(2026)]