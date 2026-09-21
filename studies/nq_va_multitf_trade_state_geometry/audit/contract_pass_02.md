# Contract audit — pass 02 (delta) — nq_va_multitf_trade_state_geometry

Delta pass over `contract_pass_01`. New composite `6bcee4347b33ab0d`, plan `247755a85abbf8fc`,
packet `83924d6bb5c4dec3`. Tests 158 passed / 0 failed.

---

## Δ1 — the superseded 2023 partition cannot be reused — CLEAR (the critical check)

A completed 2023 partition from the previous seal is still on disk, and it is **missing all 15
`terminal_*` columns**. Silently reusing it would reproduce the exact defect this re-seal exists to
fix, with every stage reporting PASS.

The packet confirms it cannot happen:

```
partition_reuse: declared {mode: off}  effective: off  would_reuse: []
  train-2023  reusable: False  reason: REPLAY_CLOSURE_CHANGED
              manifest_plan_sha256 82b230f2…  manifest_seal 48809ad8…
              recorded_replay_closure 930601e6…  expected_replay_closure e8520cfa…
  train-2024  reusable: False  reason: NO_PARTITION
```

Two independent reasons hold: reuse is declared `off`, and the recorded replay closure of the old
partition no longer matches the expected one. The old partition also carries its own provenance
(`manifest_plan_sha256 82b230f2`, `manifest_seal 48809ad8`), so it stays distinguishable from
whatever this seal produces. Both years will be collected fresh.

## Δ2 — chronology `train: [2023, 2024]`, `dev: []` — CLEAR on the contract, with K-4

Role sets remain pairwise disjoint: train `{2023, 2024}`, dev `{}`, diagnostic `{}`, prohibited
`{2025, 2026}`. No year carries two roles. `year_role_table` is null because no partition is reused
across roles — consistent with Δ1.

`model: null`, so no fit, tuning, freeze or OOS door exists to be mis-scoped. The TRAIN/tuning/
final-validation/OOS disjointness invariant is satisfied vacuously for the last three.

## Δ3 — observation column contract — CLEAR

93 observation columns, 15 `terminal_*`, `observed_seconds` last (A5 invariant intact).
28/28 primitives bound. `study_python: {python_files: [], exception: null}` — still zero study
Python after the fixture relocation. Feature and label spaces remain disjoint.

New this pass: `merge()` enforces the persisted schema against
`plan.outcome.observation_columns` and `identity.json` will carry both the declared and the
persisted column lists, so the frame becomes self-describing about its own schema.

---

## Findings

### NOTE K-4 — the year-role split is a contract obligation, not a runtime gate

With `dev: []` the controller has no mechanism that holds 2024 shut. The discovery (2023) versus
frozen-replication (2024) split is carried entirely by
`research_decision.yaml.two_year_replication_protocol`, which includes a call-by-call year table
and four binding obligations: definitions committed before any 2024 inspection; no classifier,
feature selection or threshold fitting; no pooling before the year-by-year result; post-2024
findings labelled EXPLORATORY and unable to alter the replication verdict.

This is the owner's explicit configuration and the alternative — a dummy model and a fake TRAIN
freeze purely to obtain an ML gate this study has no use for — was explicitly forbidden. Recorded
as a NOTE so the obligation is visible to the contract reader, not only to the decision-contract
reader. Mirrors causal NOTE C-4.

### NOTE K-5 — the seal's platform identity now includes three chore commits, none on `main`

The composite `6bcee4347b33ab0d` includes C1 (`7c4a2673`), the sink column-parity fix
(`e2169543`) and the merge persisted-schema assertion (`292c8ca4`), all on
`chore/fill_outcome_session` and none merged to `main` — because that branch also carries the
unaudited C0 fill-scope work. The study branch remains the sole authority for this seal, and
results collected under it are not reproducible from `main` until C1 lands there. Carried forward
and extended from K-2.

### NOTE K-6 — superseded evidence is retained, not deleted

`research_decision.yaml.superseded_evidence.collection_v2_rth_2023` records the previous collection
with its provenance, what remains valid (timing 7m38s, 12,805,413 bars, 282,196 epochs, 134,664
observations, 7,764 regimes, smoke PASS, the 64 `fp_*` columns) and what is invalid (all terminal
economics). The partition itself is left on disk. Correct handling of superseded evidence.

---

## Carried forward from contract_pass_01

Binding completeness, zero study Python, identity columns, outcome-columns-are-never-features
(including the `pnl_atr_*` naming note), and the deliverables table: all CLEAR and unchanged.
K-1 still applies — the claim stages have no declarations, and this study is sealed and run only
through merge.

## Verdict

**CLEAR.** Zero critical, zero warning, three notes.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "6bcee4347b33ab0d0c82ccd0cfd904b0a2ed0d269091c84b2718c4b1ad065853", "auditor": "claude-contract-pass02", "critical": 0, "note": 3, "study": "nq_va_multitf_trade_state_geometry", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->
