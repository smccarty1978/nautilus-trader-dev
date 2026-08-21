# Post-Confirmation 5m Context × Forward Opportunity

Descriptive-only study. See `SPEC.md` for the full frozen contract.

## How to run

```bash
# Prerequisites (already built by predecessor studies, read-only inputs):
#   studies/p90_5m_regime_context/_work/regime_5m_flips.parquet (+ _buckets.parquet)
#   studies/p90_5m_regime_context/results/p90_classification.parquet
#   studies/post_confirm_forward_opportunity/results/observation_panel.parquet

# 1. Phase 0 lineage reconciliation (optional standalone check; run_study.py
#    also does this)
python -m studies.post_confirm_5m_forward_opportunity.implementation.lineage

# 2. Full study -- Phase 1 freeze, Phases 2-13, gates, verdict
python scripts/run_bounded_study.py \
  --cmd "python -m studies.post_confirm_5m_forward_opportunity.run_study" \
  --timeout 600 --stale-timeout 180 \
  --out-status studies/post_confirm_5m_forward_opportunity/audit/run_status.json
```

Outputs land in `results/` (generated, not committed) and
`audit/run_status.json`. `results/summary.json` carries the mechanically
computed C1-C5/ABORT verdict; `results/validation_report.json` carries every
gate.

## What this study does NOT do

No exit rule, trailing stop, profit target, or timing policy is built or
used by anything here (SPEC section 10). It classifies the already-closed
`post_confirm_forward_opportunity` forward-path map by 5m regime alignment
at confirmation and reports whether that context predicts the *timing* of
remaining opportunity. See `REPORT.md` for the answered questions.
