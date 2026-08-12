# P90 Entry Path × 5-Minute Regime Context

Descriptive-only context study. See `SPEC.md` for the full frozen contract.

## How to run

```bash
# 1. Build the causal 5m regime timeline (once; ~5 min, writes _work/)
python -m studies.p90_5m_regime_context.implementation.regime_5m

# 2. Parity-test the vectorised engine against a literal aggregator+engine replay
python -m pytest studies/p90_5m_regime_context/tests/ -v

# 3. Phase 0 lineage reconciliation (optional standalone check; run_study.py
#    also does this)
python -m studies.p90_5m_regime_context.implementation.lineage

# 4. Full study -- classification, Phases 1-11, gates, verdict
python scripts/run_bounded_study.py \
  --cmd "python -m studies.p90_5m_regime_context.run_study" \
  --timeout 600 --stale-timeout 180 \
  --out-status studies/p90_5m_regime_context/audit/run_status.json
```

Outputs land in `results/` (generated, not committed) and
`audit/run_status.json` (the bounded-runner status card — read this, not raw
logs). `results/summary.json` carries the mechanically computed verdict;
`results/validation_report.json` carries every gate.

## What this study does NOT do

No entry filter, no exit policy, no risk-management rule is built or used by
anything here (SPEC section 6/11). It classifies the accepted 8,950-arm P90
population against a newly built causal 5-minute regime and reports where (if
anywhere) that context materially separates outcomes. See `REPORT.md` for the
answered questions.
