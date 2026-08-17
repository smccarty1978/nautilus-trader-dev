# Workflow Hardening — Final Bounded Remediation

Second independent Red Team pass on the repaired workflow. Four blockers plus seven
trust-chain warnings. Scope was deliberately narrow: no redesign, no ES run, no research.

**Branch:** `chore/workflow-hardening-remediation`
**Predecessor:** [`WORKFLOW_HARDENING_REMEDIATION_REPORT.md`](WORKFLOW_HARDENING_REMEDIATION_REPORT.md)

---

## RT-1 — Mandatory preflight completeness

| | |
| --- | --- |
| **Finding** | `research_preflight.py --skip-tests` emitted `status=CLEAR` / `required_next_action=READY_FOR_AUDIT` while mandatory `CAUSAL_INVARIANTS` never ran. |
| **Reproduced** | YES |
| **Failing regression** | `test_rt_blockers.py::test_rt1_diagnostic_run_cannot_masquerade_as_full_clear` drives the real CLI. |
| **Root cause** | The verdict was derived solely from "did any gate that *ran* fail?". A check that never executes cannot fail, so **skipping a mandatory gate made the preflight more likely to advertise readiness**, not less. |
| **Minimal fix** | Readiness became a two-part claim: every required check EXECUTED *and* PASSED. Per-check outcomes (`PASSED`/`FAILED`/`TIMEOUT`/`SKIPPED`/`NO_TESTS_SELECTED`/`NOT_EXECUTED`) are recorded; a skip is written down rather than omitted. New `INCOMPLETE` status and `RUN_FULL_PREFLIGHT_BEFORE_AUDIT` action. `audit_ready` is the single field consumers read. Diagnostic mode still exists — it just cannot claim readiness, and no longer supersedes a stale failure packet. |
| **Downstream** | `run_preexec_audits` (issuance) and `preexec_audit_seal` (sealing) call `assert_preflight_audit_ready()` and refuse incomplete evidence. An artifact predating the contract has no `audit_ready` key and is refused rather than assumed ready. |
| **Passing regression** | 9 tests: complete→ready, skipped→refused, timeout→refused, obsolete artifact→refused, missing→refused, corrupt→fail closed, real CLI→`INCOMPLETE` + exit≠0, plus both downstream guards. |

Completeness applies to a **compiled study** (one with `study.yaml`). A bare directory
path-lint can still be `CLEAR` but is never `audit_ready` — there is no study to be ready
for. Exit status reflects failure/incompleteness, not readiness.

## RT-2 — Execution closure: relative imports

| | |
| --- | --- |
| **Finding** | `from . import X` never entered the closure. `features/__init__.py` → `from . import shadow_exec` executes, yet edits to it left the composite unchanged and an old seal valid. |
| **Reproduced** | YES — `from . import X`, `from .. import Y`, `from ..pkg import Z` all missed; only `from .pkg import mod` worked. |
| **Failing regression** | `test_rt_blockers.py::test_rt2_relative_import_forms_enter_the_closure` (7 parametrised forms). |
| **Root cause** | The relative branch built `<parent_dir>.py` from `mod_base`. With `mod_base=None` (`from . import X`) that is a nonsense path that never matches; when the base was a package *directory* only `.py` was probed; and the names in `node.names` were never treated as possible submodules. |
| **Minimal fix** | The base of a relative import is a directory. All three things Python may execute there are probed: a module file, a package `__init__`, and each alias as a submodule/subpackage. `node.level` is walked correctly for `..`/`...`. An unresolvable **base** is recorded as unresolved, lowering coverage. |
| **Passing regression** | 12 tests covering `import x`, `import x.y`, `from x import y`, `from . import y`, `from .x import y`, `from .. import y`, `from ..x import y`; composite moves when a relatively-imported module changes; closure does not over-broaden; unresolved base reported. |

Not special-cased to `shadow_exec`; the synthetic fixture builds its own package tree.
Deliberate non-finding: `from . import name` where the package resolves but `name` is not
a submodule is **not** reported — `name` may be an attribute of `__init__.py`, and if it is
neither, Python raises ImportError so nothing executes unsealed.

## RT-3 — Durable audit lineage

| | |
| --- | --- |
| **Finding** | Deleting `audit/pass_ledger.json`, or rebuilding the audit directory, reset a study's audit history and made pass 01 available again. |
| **Reproduced** | YES |
| **Failing regression** | `test_rt_blockers.py::test_rt3_deleting_the_local_ledger_is_detected` and `..._the_whole_audit_directory_...`. |
| **Root cause** | The ledger lived *inside* the thing it protected. "No ledger" was read as "no history" — the exact state a careless rebuild (or an attacker) can manufacture with one `rm`. |
| **Minimal fix** | A durable anchor at `audit_lineage/<study_id>.json`, **outside every study directory**, authoritative for the high-water mark and integrity-bound by a hash over its entries. `resolve_effective_lineage()` reconciles anchor against local ledger and distinguishes three states: agreement; `AUDIT_LINEAGE_RESET_DETECTED` (anchor knows passes the ledger lost); `AUDIT_LINEAGE_UNANCHORED` (ledger claims passes the issuer never wrote — a copied directory or a hand edit). Issuance writes **both**. |
| **Passing regression** | 11 tests: same-pass/different-composite refused, reused/lower pass refused, identical retry idempotent, ledger deletion detected, audit-directory deletion detected, anchor survives that deletion, copied study explicit and safe, unanchored ledger refused, corrupt ledger fail-closed, corrupt anchor fail-closed, tampered anchor detected, identity mismatch detected. |

A study seen for the first time with a local ledger but no anchor bootstraps one, recorded
as `bootstrapped_from_local_ledger: true` — the one-time migration for studies predating
this control. A *copy* therefore bootstraps under its own new study id, which is correct:
that is a different study identity. Existing atomicity, sibling-status, report-reuse and
stale-composite checks were not touched.

## RT-4 — Feature grandfather baseline

| | |
| --- | --- |
| **Finding** | A new feature added to **both** `features/registry.py` and the baseline file bypassed promotion evidence. |
| **Reproduced** | YES — `check_feature_promotions` returned `passed=True` with a smuggled baseline entry. |
| **Failing regression** | `test_rt_blockers.py::test_rt4_adding_to_registry_and_baseline_is_refused`. |
| **Root cause** | The guard computed `baseline - registry`, which detects a *stale* baseline name. In the attack case that difference is **empty by construction** — the name is in both. The check was inverted relative to the threat. |
| **Minimal fix** | The baseline file now carries `pinned_original_verified` (immutable historical set, hashed into `BASELINE_PINNED_SHA256` in `check_feature_promotion.py`) and `baseline_verified` (active set). Rules: the pinned set must match the code-side pin, and the active set must be a **subset** of it. Removal is allowed; addition is refused. Growing the pinned set requires editing a governance-closure source file, which moves the execution composite and forces re-audit — the "explicit governed baseline migration". |
| **Passing regression** | 6 tests: existing grandfathered accepted, removal allowed, registry-only addition requires evidence, registry+baseline addition REFUSED, pinned-set edit detected (`PROMOTION_BASELINE_TAMPERED`), wick still provisional. |

No historical features were retro-demoted.

---

## Warnings

| ID | Finding | Reproduced | Minimal fix | Regression |
| --- | --- | --- | --- | --- |
| **W1** | `validate_smoke.py` kept its own hard-coded deliverable list; a missing `collection_manifest.json` passed. | YES | Consumes `config/deliverables_contract.json`; absent contract is a refusal, not a licence to substitute. | `test_smoke_deliverables_and_dates.py` (7) |
| **W2** | Feature-surface validation enforced only "declared ⊆ produced". | YES | Both directions. `UNDECLARED_FEATURE_COLUMN` for any column that is neither a declared feature nor declared metadata; metadata comes from the study contract, so legitimate non-feature columns are never rejected. | `test_feature_surface_validation.py` (4 new) |
| **W3** | Promotion evidence did not identify which implementation was reviewed. | YES | `reviewed_implementation_sha256` is required and compared against the feature's current implementation hash. Old evidence stops authorising changed feature code. | `test_feature_promotion.py` (3 new) |
| **W4** | Smoke date was a free CLI value defaulting to `2023-03-03`, never checked against the study. | YES | Validated against `execution.data_requirements.authorized_dates`; emitted candidate days are checked too. Studies declaring none are unaffected. | `test_smoke_deliverables_and_dates.py` (6) |
| **W5** | Any readable file passed to `--transcript` became `SESSION_BOUND`. | YES | **Option B.** Hashing a file proves the file existed, not that a review happened, and no audit-session evidence contract exists here. A supplied file is recorded as `attached_artifact` (hashed, for reference); strength stays `DECLARED_IDENTITY_ONLY`; `independence_proven` remains `false`. | `test_rt_blockers.py` (2), `test_audit_pass_immutability.py` (1 rewritten) |
| **W6** | Two more inline RTH windows ending at **15:00** in sealed feature infrastructure. | YES — `features/engine.py` ×2, `features/library.py` ×1 | All three route through `utils/session_boundaries.is_in_session`. The comment asking editors to "update both call sites in lockstep" was itself evidence they had not been. | `test_rt_blockers.py` (4) |
| **W7** | Seal not byte-reproducible across checkouts. | YES — `core.autocrlf=true`, no `.gitattributes`; blobs LF, worktree CRLF | `canonical_file_sha256`: text sources hashed line-ending-normalised, binary artifacts byte-exact. Seal and manifest share one implementation. | `test_rt_blockers.py` (8) |

**W7 note.** `.gitattributes` was considered and rejected: `* text=auto eol=lf` would
renormalise every file in the working tree on next checkout — a repo-wide rewrite the
brief prohibits. Canonical hashing fixes reproducibility while touching no file content.
Normalising line endings loses nothing for `.py`/`.json`/`.yaml`/`.md`; parquet and joblib
stay byte-exact, where a byte difference genuinely *is* a content difference.

---

## Documentation

- **`docs/RESEARCH_WORKFLOW.md` §6** — pandas/Polars are computation libraries, not an
  alternate governed workflow. Governed path stated; scratch results explicitly
  NON-AUTHORITATIVE; `ANALYSIS_HARNESS_GAP` is the required stop signal. Plus: no scratch
  wrappers around canonical runners, and do not launch a duplicate run while one is
  `RUNNING` unless confirmed terminal via `scripts/reconcile_runs.py`.
- **`AGENTS.md`** — new *Destructive Filesystem Safety* rule and lesson 8, prompted by the
  data-loss incident. Recursive deletion must fail closed if any descendant resolves
  outside the disposable root; junctions and reparse points are called out explicitly
  because `os.path.islink()` returns **False** for a Windows directory junction.
- **`scripts/safe_cleanup.py`** — one function, `assert_safe_to_delete`, implementing that
  check. Not a cleanup framework. Traversal inspects links rather than following them, and
  aborts the *entire* deletion on any escape: deleting "the safe part" of a tree you did
  not fully understand is the shape of the incident.

Junction-based tests run for real here (junctions need no elevation) and confirm the trap:
`is_symlink()` is False while the reparse attribute is True. Symlink variants skip.

---

## Test results

| Suite | Result |
| --- | --- |
| Blocker-specific targeted (`test_rt_blockers.py`) | **56 passed / 0 failed** |
| Combined workflow-governance targeted (13 files) | **231 passed / 0 failed**, 5 skipped |
| Broader relevant suite (`scripts/tests` + `tests`), run once | **715 passed / 1 failed**, 7 skipped |

**New test files:** `test_rt_blockers.py` (56), `test_smoke_deliverables_and_dates.py` (14),
`test_safe_cleanup.py` (12), `_preflight_fixture.py` (helper), `conftest.py` (lineage isolation).

### The one broader failure is pre-existing and unrelated

`test_nt_runner_collect.py::test_end_to_end_1day_collect_run_nonzero_candidates` fails with
`PREEXEC_AUDIT_STALE` on `backtests/nt_runtime/data_plan.py` for the unrelated study
`Gemini_clean_maturity_flip_rolling_5m_productivity`. Its seal expects `7838e76e6839`;
the file already hashed to `19a879b5d75f` at this task's **start commit** (`2d664e7`),
verified against both raw and canonical hashing. **Not fixed by re-sealing another
study**, as instructed.

### Test-fixture consequences of RT-1 and RT-3 (not weakenings)

Both new controls are fail-closed and correctly bit existing fixtures:

- Fixtures that seal or issue statuses now plant a compliant preflight artifact via
  `scripts/tests/_preflight_fixture.py` — the same pattern already used for compliant
  audit reports. Production paths still consult the real artifact, and `test_rt_blockers`
  drives the real CLI to prove a genuine `--skip-tests` run is refused.
- Scratch studies are very often all named `study`, and the anchor is keyed by study name,
  so one test's anchor was correctly reported as a lineage reset of the next test's empty
  ledger — a true positive about a false situation. `scripts/tests/conftest.py` redirects
  the anchor directory per test via `NT_AUDIT_LINEAGE_DIR`. Every production path is
  unchanged: the anchor is still written, read and integrity-checked; only its directory
  moves, and only under test.

---

## Files changed

**Blocker owners:** `scripts/research_preflight.py` · `scripts/resolve_execution_manifest.py` ·
`scripts/run_preexec_audits.py` · `scripts/preexec_audit_seal.py` ·
`scripts/check_feature_promotion.py` · `features/feature_lifecycle_baseline.json`

**Warning owners:** `scripts/validate_smoke.py` · `scripts/check_feature_surface.py` ·
`backtests/nt_runtime/output_manager.py` · `features/engine.py` · `features/library.py`

**New:** `scripts/safe_cleanup.py` · `scripts/tests/{test_rt_blockers,test_smoke_deliverables_and_dates,test_safe_cleanup}.py` ·
`scripts/tests/{_preflight_fixture,conftest}.py`

**Docs:** `AGENTS.md` · `docs/RESEARCH_WORKFLOW.md`

**Test fixtures updated:** `test_round2_invariants.py` · `test_audit_seal_guard.py` ·
`test_audit_provenance_redteam.py` · `test_audit_report_ingestion.py` ·
`test_audit_pass_immutability.py` · `test_feature_promotion.py` ·
`test_feature_surface_validation.py`

**Verified-good runtime areas modified: NONE.** The wick formula, 300s target semantics,
exact-horizon race fix, candidate terminal reconciliation, censoring implementation, ES
timestamp measurement, `utils/session_boundaries.py`, run lifecycle classification and
exact-date data-plan enforcement were **not** changed. `features/engine.py` and
`features/library.py` were changed only to *consume* the canonical session module rather
than re-derive a conflicting boundary — the canonical module itself is untouched.

**Parallel infrastructure created: NO.**

---

## State on handoff

The execution composite moved (governance and feature-infrastructure files changed), so
`studies/es_wick_imbalance_acceptance_v2`'s existing seal is **stale by design** — the
correct fail-closed state after execution-affecting changes. Re-preflight, re-audit and
re-seal belong to the next cycle, after Red Team mutation testing, not to this one. No ES
run was performed and no recovered data was touched beyond read-only verification.
