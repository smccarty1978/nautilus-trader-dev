# Workflow Hardening — Final Bounded Remediation

**Baseline audited:** `33f5ad1` (`chore/workflow-hardening-remediation`)
**Input:** `WORKFLOW_HARDENING_FINAL_RED_TEAM.md` — `RED_TEAM_BLOCKED`, 4 blocking defects, 8 warnings.
**Scope:** the six named items only. Every Red Team finding was reproduced before any code changed.

---

## Reproduction first

| Item | Reproduced? | Observed before the fix |
| --- | --- | --- |
| RT2-B1 | yes | `from features.trackers import a, b` — real Python executes both; closure held `['a.py']`; `unresolved: []` |
| RT2-B2 | yes | `select_required_tests.py`, `check_feature_promotion.py`, `feature_lifecycle_baseline.json` all `False` in `file_hashes` (66-file composite) |
| RT1-B1 | yes | `assert_preflight_audit_ready` **ACCEPTED** a file whose entire content was `{"audit_ready": true}` |
| RT3-B1 | yes | `audit_lineage/` absent from the repo and from `git ls-files`; the one study with a pass ledger had no anchor; `NT_AUDIT_LINEAGE_DIR` relocated production state |
| W-A | yes | no `studies/*/config/*.json` in the sealed set; post-seal deliverable narrowing left the seal valid |
| W-B | yes | 35 files / 616 tests / **246.7 s** against a **120 s** subprocess timeout → `BLOCKED / INVARIANT_TEST_TIMEOUT` every run |

---

## 1. RT2-B1 — multi-alias / namespace / relative import closure

**Owner:** `scripts/resolve_execution_manifest.py::compute_ast_closure`

The `break` in the `ImportFrom` fallback branch stopped after the first alias that
resolved, and the honesty signal lived in the `for`/`else`, so one successful alias both
dropped every later module from the closure *and* suppressed the unresolved report.

Both alias loops — the absolute fallback and the relative branch — now resolve **every**
alias independently. Unresolved aliases are reported per alias when the base contributed
no executable file (a PEP 420 namespace directory can expose nothing but submodules, so a
missing alias there is a real gap). When the base *does* execute an `__init__`, an
unresolved alias is a legitimate attribute and is not reported — fail-closed must not mean
cry-wolf, and `test_rt2b1_attribute_import_from_a_real_package_is_not_a_false_gap` pins
that boundary. No special-casing of `features.trackers`.

Covered forms, each proven against what the interpreter actually executes:
`from pkg import a, b` · `from . import a, b` · `from .. import a, b` ·
`from namespace_pkg import a, b`. For each: closure contains every executed repo-local
module, unresolved aliases are reported, and editing any included module moves the
composite. The Red Team's stated material case — all nine real trackers in one statement —
is asserted against the real repository.

## 2. RT2-B2 — governance authority is sealed

**Owner:** `scripts/resolve_execution_manifest.py`

The closure follows AST imports; the preflight reaches its gates by `subprocess.run`. An
import edge the AST cannot see is an execution edge all the same.

`discover_subprocess_gate_scripts()` **derives** the gate set from
`scripts/research_preflight.py`'s own AST rather than re-listing it by hand — a second
hand-maintained list is the same defect one edit later. All six derived gates are now
seeded into the governance closure, so each gate's own transitive imports are followed
too. `features/feature_lifecycle_baseline.json` and `feature_lifecycle_promotions.json`
are added as static authority files: they are data, so no AST edge reaches them, but the
baseline **is** the grandfather set the promotion gate enforces.

Composite: 66 → 77 files. `test_rt2b2_extractor_agrees_with_the_preflight_source` is the
falsifiability check on the check — if the extractor silently stopped finding gates, the
subset assertion would pass vacuously.

## 3. RT1-B1 — preflight evidence binding

**Owner:** `scripts/research_preflight.py`, consumed by `run_preexec_audits.py` and
`preexec_audit_seal.py`

Evidence now records `evidence_schema_version`, `study_id`,
`execution_composite_sha256`, `check_outcomes`, `preflight_run_id`, `generated_at_utc`
and a self-binding `evidence_sha256`. The consumer runs seven independent checks and
trusts `audit_ready` for none of them.

The required-check **set** is deliberately read from `REQUIRED_STUDY_CHECKS` in module
source, never from the artifact: reading expected and actual from the same mutable file is
circular. `test_rt1b1_incomplete_check_set_is_refused_even_if_internally_consistent`
proves it by rewriting `required_checks` *and* recomputing the binding hash.

All six named attacks refused:

```
{"audit_ready": true}                       PREFLIGHT_EVIDENCE_OBSOLETE
edited CLEAR artifact                       PREFLIGHT_EVIDENCE_TAMPERED
preflight from old composite                PREFLIGHT_EVIDENCE_STALE
preflight from another study                PREFLIGHT_EVIDENCE_FOREIGN
incomplete check set                        PREFLIGHT_REQUIRED_CHECKS_INCOMPLETE
CLEAR beside a live BLOCKED failure packet  PREFLIGHT_CONTRADICTED_BY_FAILURE_PACKET
```

A real edit to closure code (not a doctored field) also invalidates evidence —
`test_rt1b1_real_code_edit_makes_existing_evidence_stale`.

**Stated limit, in the source:** this binds evidence to state; it does not authenticate
the producer. There is no key in this repository, so a consistent forgery remains possible
for anyone who can run the resolver. What is removed is the far larger class of stale,
partial, hand-edited and cross-study evidence.

## 4. RT3-B1 — durable audit lineage

**Owner:** `scripts/run_preexec_audits.py`, plus `scripts/bootstrap_audit_lineage.py` (new)
and `audit_lineage/README.md` (new)

The durability substrate is **git** — the only durable, integrity-bound,
repository-visible store this repo has. Stated plainly rather than dressed up.

- **B.** The anchor lives at `audit_lineage/<study_id>.json`, inside the repository, not
  git-ignored, with a README. `AGENTS.md` § Commit protocol now requires committing it
  with the pass it anchors and exempts it from the "never commit generated data" rule.
- **A.** A study with issued passes and no anchor **fails closed**
  (`AUDIT_LINEAGE_ANCHOR_MISSING`). Silent bootstrap is gone — it was indistinguishable
  from `rm audit_lineage/<id>.json`, which is how the anchor was reset.
- **C.** `NT_AUDIT_LINEAGE_DIR` is **removed**. Anchor location is derived from the study
  path alone: inside the repo → `<repo>/audit_lineage/`; outside the repo → beside the
  study. Not an override, takes no input from the environment or the command line, and
  does not cross a subprocess boundary. Every governed study lives under `<repo>/studies/`,
  so production placement is fixed. The in-process `set_test_lineage_dir` hook refuses
  outside a pytest process.
- **D.** The anchor carries a monotonic `issuance_counter` and a `chain_sha256` hash chain,
  and every read compares the working tree against `HEAD`'s committed anchor **and**
  committed ledger. Rolling both back together is `AUDIT_LINEAGE_ROLLBACK_DETECTED`.
- **E.** `scripts/bootstrap_audit_lineage.py` requires explicit intent —
  `--adopt-ledger` (this identity owns that history) or `--fresh-identity` (a copied
  directory; history does not transfer). Guessing either way is a real failure: one
  launders history, the other loses it.

All twelve regression attacks are covered and refuse: delete anchor / ledger / both,
rollback anchor / ledger / both, foreign anchor, corrupt anchor, edited entries, env
redirect, recreated same identity, copied new identity. A genuinely fresh study still
proceeds — `test_rt3b1_fresh_study_with_no_history_is_not_blocked` pins that fail-closed
does not mean fail-always.

**Not claimed:** no signature, no trusted time, no defence against a rewritten git history.
The durability boundary is the commit, and `audit_lineage/README.md` says so.

The real acceptance study now has an anchor: `audit_lineage/es_wick_imbalance_acceptance_v2.json`
(high_water `{causal: 3, contract: 2}`), bootstrapped explicitly from its committed ledger.
No historical audit report was rewritten.

## 5. W-A — sealed deliverable contract

**Owner:** `scripts/resolve_execution_manifest.py`, `scripts/validate_smoke.py`

Both halves, with a single authority:

- **Authority (option B).** `validate_smoke` reads `contracts.deliverables_contract` from
  the already-sealed `compiled_study.json`. The sidecar
  `config/deliverables_contract.json` is verified to match and raises
  `DELIVERABLES_CONTRACT_DRIFT` if it does not — it is never consulted for a decision, so
  there are not two authorities.
- **Integrity (option A).** `studies/<id>/config/*.json` is now inside the sealed study
  identity, so a post-seal edit invalidates the seal instead of silently changing what a
  validator requires.

Generic across studies (`config/*.json` glob, `compiled_study.json` contract block); no ES
special-casing. Deleting a required `collection_manifest.json` remains blocked.

## 6. W-B — the mandatory gate is executable

**Owner:** `scripts/research_preflight.py`

Measured before choosing anything. After the fixes, on the reference machine, running
exactly what the gate runs:

```
test files selected     36
tests executed          680   (671 passed, 7 skipped, 2 deselected)
wall clock              385.1 s
slowest single test     3.6 s   — no dominant outlier; cost is broad and flat
```

36 files of deterministic framework governance tests with no hot spot, so there is nothing
redundant to remove — narrowing the selection would be "weakening required tests", which
was excluded. `CAUSAL_INVARIANTS_BUDGET_SECONDS = 900` (2.34× the measurement), recorded
alongside `CAUSAL_INVARIANTS_MEASURED_SECONDS = 385.1` so the number stays falsifiable: a
regression asserts ≥2× headroom and a bounded ceiling, so suite growth forces a
re-measurement rather than a quiet bump. The constant lives in the governance closure, so
raising it moves the composite and invalidates every seal.

Timeout still fails **closed**: `test_wb_timeout_still_blocks` drives the budget to 1 ms
and asserts `TIMEOUT` / `BLOCKED` / `audit_ready: false`. `--skip-tests` remains
non-audit-ready and is now refused by the bound-evidence consumer as well.

**End-to-end proof, no bypass flags:**

```
$ python scripts/research_preflight.py --study studies/es_wick_imbalance_acceptance_v2
RESEARCH PREFLIGHT VERDICT: CLEAR (404.73s)
Checks Run: EXECUTION_MANIFEST, CAUSAL_LINT, ARTIFACT_SCHEMA, FEATURE_PROMOTION,
            RESEARCH_DECISION_FIDELITY, CAUSAL_INVARIANTS
Audit Ready: True
exit=0
```

This is the first `CLEAR` preflight any study in this repository has obtained. The
artifact carries `evidence_schema_version: 2`, its study id, composite
`2f2cd6510fa8…`, all six `PASSED` outcomes and a matching `evidence_sha256`; the
consumer independently re-verifies it and accepts.

---

## Incidental finding, fixed as part of RT3-B1

Removing the environment variable exposed that the subprocess-driven CLI tests had been
relying on it for isolation, and were writing **real anchors into the repository**
(`audit_lineage/Gemini_clean_maturity_flip_rolling_5m_productivity.json` appeared during
the first combined run). Isolation is now structural — out-of-repo studies anchor beside
themselves — and `scripts/tests/conftest.py` was inverted from *creating* isolation to
*asserting* it: any test that mutates the repository's durable lineage now fails. The
stray anchor was removed.

Study copies in tests moved to `scripts/tests/_study_copy.py::copy_study_as_fresh_identity`,
which drops the inherited pass ledger — the honest expression of what those tests want,
and the same semantics as the production tool's `--fresh-identity`.

---

## Results

**RT2-B1 multi-alias closure:** FIXED
**RT2-B2 governance closure:** FIXED
**RT1-B1 preflight binding:** FIXED
**RT3-B1 durable lineage:** FIXED
**W-A deliverables authority:** FIXED
**W-B mandatory preflight budget:** FIXED

**Targeted tests:** 56 passed / 0 failed
(`scripts/tests/test_rt_final_blockers.py`, 1 slow test deselected)

**Combined governance tests:** 318 passed / 0 failed / 1 skipped
(13 files: RT final blockers, RT blockers, round-2 invariants, audit provenance, pass
immutability, seal guard, report ingestion, execution closure, test selection, feature
promotion, smoke deliverables, generated contracts, research preflight)

**Broader relevant suite:** 671 passed / 0 failed / 9 skipped
(full mandatory `select_required_tests.py` selection, 36 files, one run, 382.7 s)
The pre-existing `test_nt_runner_collect.py::test_end_to_end_1day_collect_run_nonzero_candidates`
failure reported by the Red Team passes in this run.

**Verified runtime areas changed:** NONE
No change to 300 s target logic, exact-boundary race correction, candidate reconciliation,
session-end censoring, ES timestamp measurement, canonical session boundaries, the feature
wick formula, run lifecycle, exact-date enforcement, or feature-surface behaviour.

**Backlog items touched:** NONE
W-C, W-D, W-E, W-F, W-G, W-H, `parity_sampler` RTH constant, `session_boundaries` lockstep
cleanup, extra-deliverable reporting and the cosmetic `CLEAR`/`checks_run` wording are all
untouched and remain open.

**Parallel infrastructure:** NO
No new runner, engine, collector or analysis path. One new script
(`scripts/bootstrap_audit_lineage.py`) and two test helpers; everything else is a change
inside an existing owner module.

**Final status: READY_FOR_FINAL_RED_TEAM**

---

## Files changed

```
scripts/resolve_execution_manifest.py     RT2-B1, RT2-B2, W-A
scripts/research_preflight.py             RT1-B1, W-B
scripts/run_preexec_audits.py             RT3-B1 (+ repo_root threaded to the consumer)
scripts/preexec_audit_seal.py             repo_root threaded to the consumer
scripts/validate_smoke.py                 W-A
scripts/bootstrap_audit_lineage.py        NEW — explicit lineage bootstrap
audit_lineage/README.md                   NEW — durability model and its boundary
audit_lineage/es_wick_...v2.json          NEW — the acceptance study's anchor
AGENTS.md                                 commit protocol: the anchor commits with its pass
scripts/tests/test_rt_final_blockers.py   NEW — 57 regressions across the six groups
scripts/tests/_study_copy.py              NEW — fresh-identity study copy helper
scripts/tests/_preflight_fixture.py       fixture now produces BOUND evidence
scripts/tests/conftest.py                 asserts lineage isolation instead of creating it
scripts/tests/test_rt_blockers.py         RT-1 tests use bound evidence; copied-study semantics
scripts/tests/test_{round2_invariants,audit_provenance_redteam,audit_report_ingestion,
                    audit_seal_guard,smoke_deliverables_and_dates}.py
                                          fresh-identity copies; W-A message assertions
```

## For the Red Team

Suggested places to push hardest:

1. An `ImportFrom` form none of the four parameterised cases covers — conditional imports,
   `importlib`, or a `__getattr__`-based lazy module. The closure is AST-only by design.
2. Forged preflight evidence built by *running the resolver* rather than hand-editing.
   That is the acknowledged limit, not a claimed defence.
3. Lineage state that has never been committed. Everything before the first commit is
   working-tree durability only, and the README says so — test whether the workflow
   actually reaches a commit before the window matters.
4. A study deliberately placed outside the repository. The intended failure mode is
   `AUDIT_LINEAGE_UNANCHORED` when its artifacts are carried back; verify that holds.
5. Whether `900 s` is defensible on slower hardware, and whether the 2× headroom assertion
   fires before the gate does.
