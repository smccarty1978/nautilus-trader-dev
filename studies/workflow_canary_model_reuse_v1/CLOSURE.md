# CLOSURE — workflow_canary_model_reuse_v1

**Status:** CLOSED · **Outcome:** CLOSED_STUDY_MODEL_REUSE_PASS · **Terminal decision:** REUSE_VERIFIED
**Closed:** 2026-08-28 · disposable / test-only

Second disposable canary. Exercises only the frozen-external-model reuse path: references
the preserved model of the CLOSED study `workflow_canary_ordered_barrier_v1` by immutable
`model_id` (`be1bda56e1e60cd578bb064be209560c76955b6127bed6d0e3eff6e6554e4818` — the
corrected **composite-target** canary model, re-verified 2026-08-29; the pre-fix
barrier-only model `88fbba95…` is superseded and retained only as forensic history).

No market-data collection. Verified:

- `DerivedCausalInputSpec` parses the `frozen_external_model_score` declaration
  (`model_id` binding, `retrain_prohibited: true`).
- `FrozenExternalModelScorer.bind(...)` resolves the model through
  `studies/model_registry/` (artifact + golden hash verified) **without reopening the
  closed source study's lifecycle**.
- The same golden inputs reproduce identical scores (≤1e-12) through both the
  preserved-model path (`score_preserved_model`) and the frozen-external-model scorer
  bind path.
- No runtime code changed for the reuse.

`WorkflowEngine.advance()` → `terminal_state = STUDY_CLOSED`, `next_deterministic_action = null`.

Disposable — safe to delete with the parent canary.
