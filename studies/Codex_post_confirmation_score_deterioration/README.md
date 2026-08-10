# Codex post-confirmation score deterioration

This is an isolated continuation of the armed-fade score-path program. It uses
the accepted predecessor's canonical confirmation/terminal ledger and the
accepted canonical score store; it does not modify either.

Run from the repository root:

```text
python studies/Codex_post_confirmation_score_deterioration/implementation/feasibility.py
python scripts/causal_lint.py --study studies/Codex_post_confirmation_score_deterioration --json studies/Codex_post_confirmation_score_deterioration/audit/lint.json
```

The study has a deliberately early observability gate. If the valid in-domain
new-regime stream cannot observe a representative share of early failures, the
remaining event tables are marked `NOT_EVALUABLE`; no out-of-domain fallback or
policy simulation is permitted.
