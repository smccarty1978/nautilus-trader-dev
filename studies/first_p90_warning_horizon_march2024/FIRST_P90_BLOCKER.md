# BLOCKER — frozen-model derived-input binding

**State:** the study is authored, compiled, readiness PASS, preflight CLEAR, 73 platform tests
green, causal audit **CLEAR** (0 critical / 1 warning / 2 notes) bound to execution composite
`6e438b9c47c72e2fe0d24c213e5ecfadac4eda76b8e0c8b212c24df707569bc1`.
`plan_sha256 = a5843a3699c9ed9d9aed34277a613154631eb58a5e69b22ec1d10ece90e5a4eb`.

**It cannot collect.** Both governed ways to bind the parent's frozen Stage-1 models as
`frozen_external_model_score` derived causal inputs are blocked — by defects in the **closed
parent study's own artifacts**, not by anything in this study or in the new platform capabilities.
Every fact below was read from bytes.

---

## Path 1 — `model_id` binding: `PRESERVED_MODEL_NATIVE_BOOSTER_CORRUPT`

`research_workflow/model_artifacts.py::resolve_model` verifies the preserved native booster
before returning. `studies/model_registry/<id>.json`'s `native_booster_sha256` matches **no byte
state that exists**:

| model | recorded | git blob (LF) | worktree (CRLF) |
|---|---|---|---|
| `ccd587df…` (LONG, P90 0.28528879) | `3686a5d2b25b` | `f969037b2b4f` | `dba28363f7b1` |
| `209da0ff…` (SHORT, P90 0.28485632) | `dc134a9aecb6` | `8dab82c25ddc` | `085c111c763a` |

The `.joblib` artifacts **do** hash exactly as recorded and load correctly
(`artifact_sha_ok: true` for both). The boosters were re-exported (file mtime Sep 2) after the
registry recorded them (commit `b35b17ba`, Aug 31) — byte-different, numerically identical.

Everything upstream of this check passes: the `diagnostic_reuse_policy` authenticates cleanly
against the parent's closure (file sha `80510086…`, identity `eb740767…` recomputed and
self-consistent; `model_scientific_assessment.assessment == VALID_DIAGNOSTIC`; `reuse_policy`
carries both required phrases; `bound_evidence.causal_audit` and `.contract_audit` both CLEAR;
`train_freeze_sha256` present). The governance chain is intact. Only the byte check fails.

## Path 2 — legacy artifact binding: `parent TRAIN freeze is not TRAIN_ONLY`

`FrozenExternalModelScorer.bind` without `model_id` never touches the native booster — it binds to
the `.joblib` bytes plus the parent's TRAIN freeze, which is arguably *stronger* provenance. It
fails on one field: `train_experiment_freeze_long.json` and `train_experiment_freeze_short.json`
both have `provenance: None`, and the binder requires `"TRAIN_ONLY"`.

Everything else the legacy path needs is present and correct:
`feature_sets["C"]` (the 13-column ordered surface), `model_hashes["C"]` matching the bundle's
`fit_identity_sha256` (`25737fcd…` / `3c480aff…`), `preprocessing_manifest.json`, and
`preprocessing_hash 96ebac89…` matching.

## Separate repo-wide defect — every checkout corrupts every preserved booster

There is no `.gitattributes`, so `core.autocrlf` rewrites the tracked `.booster.txt` LightGBM
text models to CRLF. **CRLF makes them unparseable** — LightGBM reports
`Model format error, expect a tree here` and its fatal handler *aborts the process* rather than
raising, so the failure is not catchable in-process.

Folding CRLF back to LF, both boosters parse (100 and 200 trees) and reproduce their joblib
estimator's predictions **exactly — `max_abs_delta = 0.0`**. So the models are scientifically
intact and the native-booster recovery path is silently dead in every worktree on this machine.

Note also: `research model validate <id>` cannot see these models. They live in the legacy
`studies/model_registry/`, not the durable store `~/.nt_research/models` — two different
registries.

---

## Options (a researcher decision — all three touch closed-study authority or repo-wide policy)

1. **Re-record `native_booster_sha256`** from the current bytes, carrying the delta-0.0 parity
   evidence against the hash-verified `.joblib`. Unblocks path 1 for every future consumer.
   Mutates a closed study's registry record.
2. **Stamp `provenance: TRAIN_ONLY`** on the two per-direction freezes. Unblocks path 2 without
   touching the booster at all. Also mutates closed-study artifacts.
3. **`.gitattributes` (`*.booster.txt -text`) + re-checkout.** Not a mutation of authority and it
   fixes real, silent corruption in every worktree — but on its own it does **not** unblock this
   study, because the recorded hash matches neither byte state.

Option 3 is worth doing regardless of 1 or 2. Do **not** relax the booster check: it caught a
genuine integrity problem and is behaving correctly.
