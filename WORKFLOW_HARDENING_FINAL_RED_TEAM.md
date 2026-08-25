<!-- DOC-STATUS-BANNER -->
> **[HISTORICAL]**
>
> A point-in-time record of red-team findings against the hardened workflow. It is not a description of the current system
> and not a source of instructions.
>
> Current authority: **`docs/RESEARCH_WORKFLOW.md`**. Classification: `docs/DOCUMENT_MAP.md`.

# Workflow Hardening — Final Independent Red Team

**Commit audited:** `33f5ad1` (`chore/workflow-hardening-remediation`)
**Baseline compared against:** `2d664e7`
**Mode:** adversarial falsification. Every claim in
`WORKFLOW_HARDENING_FINAL_REMEDIATION.md` treated as untrusted.
**Production code modified:** none. All mutation probes ran in a disposable
`git worktree` under the session scratchpad and in `tempfile` fixtures.

**Verdict: RED_TEAM_BLOCKED — 4 blocking defects, 8 warnings.**

The four named remediations are each *directionally* correct and each genuinely
closes the attack the previous Red Team ran. All four are still defeatable by an
adjacent case the fix did not generalise to. Three of the four failures share one
shape: **the control's own authority lives outside the thing that protects it.**

---

## Method / safety

- Disposable worktree: `git worktree add <scratchpad>/rt 33f5ad1 --detach`.
  Verified with `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT` that the
  worktree contained **no** junctions, symlinks or reparse points before any
  deletion. The repo's own `scripts/safe_cleanup.py::assert_safe_to_delete` was
  run against the worktree (0 escaping descendants) before `git worktree remove`.
- No link was ever created to real `data/`. Junction probes used two sibling
  directories inside `%TEMP%`, and the "pretend real data" file was verified
  present after every refusal.
- No ES run, no re-seal, no research analysis, no DEV/OOS access, no data rebuild.
- `git status` at the end is byte-identical to `git status` at the start.

---

## BLOCKING FINDINGS

### RT2-B1 — Multi-alias import from a namespace package silently drops every module after the first

| | |
| --- | --- |
| **ID** | RT2-B1 |
| **Severity** | **BLOCKING** — incomplete execution closure |
| **Responsible layer** | `scripts/resolve_execution_manifest.py:252-257` (`compute_ast_closure`, the `break` in the `ImportFrom` fallback branch) |
| **Existing test should have caught it?** | No. `test_execution_closure.py` and `test_rt_blockers.py::test_rt2_*` test one alias per statement only. The brief's own checklist item "multiple imports in one statement" is untested. |

**Exact attack.** `features/trackers/` is a PEP 420 namespace package (no
`__init__.py`) — the resolver's own docstring at line 111 says so. When
`mod_base` cannot resolve to a file or package, the resolver falls through to:

```python
for alias in node.names:
    sub_res = resolve_module_to_path(f"{mod_base}.{alias.name}", ...)
    if sub_res:
        _enqueue(sub_res)
        break            # <-- stops after the FIRST submodule
else:
    ... unresolved.append(...)
```

In the disposable worktree:

```python
# features/trackers/rt_probe_a.py, features/trackers/rt_probe_b.py
# rt_seed.py:
from features.trackers import rt_probe_a, rt_probe_b
```

**Observed result.**

```
== does it actually execute both? ==
1 2                                      <- both modules run
== closure ==
probe modules in closure: ['rt_probe_a.py']
unresolved: []                           <- and coverage stays 100%
```

Confirmed again on a synthetic package tree: `rtpkg.nspkg.nsb` appears in
`sys.modules` after a real import but is absent from the closure, with
`unresolved == []`.

**Expected invariant.** Every repo-local module that executes through the
declared entrypoint enters `file_hashes`; any module that cannot be resolved
lowers `coverage_pct` below 100.

**Why it is material, not theoretical.** `features/trackers/` currently holds all
nine bound feature trackers. One edit in `features/engine.py` from nine
single-alias lines to `from features.trackers import velocity, volume, wick`
would drop eight trackers out of the sealed identity, and every gate would still
report `governance_coverage_pct: 100.0`, `unresolved_dependencies: []`. The
`else:` clause that records an unresolved import is on the `for`, so a first
successful alias suppresses the honesty signal too. Composite would not move when
those trackers changed; the seal would stay valid across arbitrary rewrites of
feature computation code.

---

### RT2-B2 / RT4-B2 — Mandatory gates and the RT-4 pin execute from outside the sealed composite

| | |
| --- | --- |
| **ID** | RT2-B2 |
| **Severity** | **BLOCKING** — mandatory gate bypass without seal invalidation; falsifies the stated RT-4 defence |
| **Responsible layer** | `scripts/resolve_execution_manifest.py:412-425` (governance seed list) — the closure follows AST imports only, and the preflight invokes these gates by `subprocess` |
| **Existing test should have caught it?** | No. `test_execution_closure.py::test_causal_lint_consumes_the_expanded_closure` checks one specific file; nothing asserts that *every* script the preflight shells out to is inside the closure. |

**Exact attack.** `scripts/research_preflight.py` runs six mandatory gates via
`subprocess.run([sys.executable, ...])`. Four of them happen to also be listed as
governance seeds. Two are not, and neither is the data file one of them treats as
authoritative:

```
OUT scripts/check_feature_promotion.py       <- holds BASELINE_PINNED_SHA256
OUT scripts/select_required_tests.py         <- chooses which tests CAUSAL_INVARIANTS runs
OUT features/feature_lifecycle_baseline.json <- the grandfather set itself
IN  scripts/causal_lint.py / check_artifact_schema.py / check_research_decision_fidelity.py
IN  scripts/check_spec_fidelity.py / validate_smoke.py / preexec_audit_seal.py / run_preexec_audits.py
```

**Observed result.** The composite is exactly
`sha256(json.dumps(file_hashes, sort_keys=True))` — verified by recomputation
against the study's own `execution_manifest.json`. Since none of the three files
appears in `file_hashes`, **editing them cannot move the composite**, cannot make
a seal stale, and cannot force a re-audit.

Demonstrated end-to-end for RT-4: appending `rt_smuggled_feature` to *both*
`pinned_original_verified` and `baseline_verified`, plus the one-line edit to
`BASELINE_PINNED_SHA256` that an attacker makes anyway:

```
baseline accepted with smuggled name: True | n = 503
check_feature_promotion.py hashed into composite: False
feature_lifecycle_baseline.json hashed into composite: False
select_required_tests.py hashed into composite: False
```

**Expected invariant.** The remediation report states: *"Growing the pinned set
requires editing a governance-closure source file, which moves the execution
composite and forces re-audit."* That statement is **false as implemented**. The
pin file is not in the governance closure.

**Second consequence, independent of RT-4.** `select_required_tests.py` decides
which tests the mandatory `CAUSAL_INVARIANTS` gate executes. It is unsealed and
mutable. Narrowing it to a single trivially-passing test yields
`CAUSAL_INVARIANTS: PASSED`, `audit_ready: true`, and an *unchanged* composite —
so no existing seal is invalidated. Emptying it is fail-closed
(`NO_TESTS_SELECTED`), but narrowing it is not.

**Third consequence.** `governance_coverage_pct: 100.0` in every manifest is not
a true statement about governance code.

---

### RT1-B1 — Preflight evidence is an unauthenticated, unbound JSON file

| | |
| --- | --- |
| **ID** | RT1-B1 |
| **Severity** | **BLOCKING** — mandatory gate bypass; stale evidence acceptance |
| **Responsible layer** | `scripts/research_preflight.py::assert_preflight_audit_ready` (and its two callers in `run_preexec_audits.py:902`, `preexec_audit_seal.py:75`) |
| **Existing test should have caught it?** | Partially — `test_rt_blockers.py` proves the *producer* refuses to write `audit_ready: true` for a partial run, but nothing tests that the *consumer* can be fed a hand-written artifact. |

**Exact attack.** Ran a genuine full preflight on a disposable copy of the
acceptance study (correctly `BLOCKED`), then hand-edited
`audit/preflight.json`.

**Observed result.**

```
genuine_BLOCKED_artifact:        REFUSED -> PREFLIGHT_NOT_AUDIT_READY
ATTACK5_forged_preflight_json:   ACCEPTED
ATTACK8_two_key_stub:            ACCEPTED     # file content: {"audit_ready": true}
failure_packet still on disk:    True         # BLOCKED packet sitting beside it, never read
```

A two-key file, `{"audit_ready": true}`, satisfies the gate that RT-1 made
load-bearing for both audit issuance and sealing.

**Expected invariant.** *"Incomplete mandatory preflight can NEVER authorize
audit/seal readiness."* Verify downstream tooling independently checks
completeness rather than trusting a single field.

**Why this is a real gap and not "everything is forgeable".** Every other piece
of audit evidence in this workflow is bound. `status.json` and
`contract_status.json` carry `audit_report_sha256`, are cross-checked against a
re-parse of the report markdown, and are pinned to a composite via
`_verify_declared_binding`. `preflight.json` is the only mandatory-gate evidence
with **zero** integrity binding: not hash-bound, not composite-bound, not
cross-checked against the `failure_packet.json` in the same directory, and not
compared to its own recorded `code_hash`. It is therefore also accepted when
stale: a preflight run against composite A remains `audit_ready` after arbitrary
edits move the study to composite B (RT-1 attack 7), because nothing compares the
two.

---

### RT3-B1 — The durable anchor is deletable, untracked, and environment-redirectable

| | |
| --- | --- |
| **ID** | RT3-B1 |
| **Severity** | **BLOCKING** — audit-history reset sufficient to re-authorize pass 01 |
| **Responsible layer** | `scripts/run_preexec_audits.py::_lineage_path` / `read_lineage_anchor` / `resolve_effective_lineage` (anchor storage and durability, not its logic) |
| **Existing test should have caught it?** | No. The 11 RT-3 tests cover deletion of the *ledger* and the *audit directory*; none covers deletion of the anchor, rollback of both to an earlier valid snapshot, or the env override. |

**Exact attacks and results** (full battery, `NT_AUDIT_LINEAGE_DIR` pointed at a
temp dir; two passes issued first):

```
1_same_pass_diff_composite               REFUSED -> AUDIT_PASS_IMMUTABLE
2_lower_pass_number                      REFUSED -> AUDIT_PASS_IMMUTABLE
3_reuse_pass_after_higher (identical)    ACCEPTED (documented idempotent)
4_byte_identical_retry                   ACCEPTED (documented idempotent)
5_delete_local_ledger  -> pass 01        REFUSED -> AUDIT_LINEAGE_RESET_DETECTED
7_delete_audit_dir     -> pass 01        REFUSED -> AUDIT_LINEAGE_RESET_DETECTED
10_copied_study        -> pass 01        ACCEPTED (correct: new identity)
11_rebuild same identity -> pass 01      REFUSED -> AUDIT_LINEAGE_RESET_DETECTED
12_corrupt anchor                        REFUSED -> AUDIT_LINEAGE_UNREADABLE
14_anchor rollback only                  REFUSED -> AUDIT_LINEAGE_UNANCHORED
15_foreign study's anchor                REFUSED -> AUDIT_LINEAGE_IDENTITY_MISMATCH
16_renamed identity -> pass 01           REFUSED -> AUDIT_PASS_IMMUTABLE

13_DELETE THE ANCHOR   -> pass 01        ACCEPTED   <-- reset
14b_ROLLBACK BOTH anchor+ledger to the
    pass-01 snapshot, reissue pass 02
    against a DIFFERENT composite        ACCEPTED   <-- rollback
ENV_OVERRIDE (NT_AUDIT_LINEAGE_DIR) +
    delete local ledger -> pass 01       ACCEPTED   <-- traceless reset
```

**Expected invariant.** *"Once an established study identity has issued pass N,
local deletion or filesystem replacement cannot silently make pass 01 valid
again."*

**Aggravating facts, verified:**

1. `audit_lineage/` **does not exist in this repository**. `git ls-files
   audit_lineage` is empty, `git check-ignore audit_lineage` matches nothing, and
   the directory is absent from disk. The one study with a pass ledger
   (`es_wick_imbalance_acceptance_v2`) has **no anchor**. RT-3 is therefore
   currently *unarmed*: deleting that study's `audit/` today resets its history
   with nothing to object, exactly as before the fix. The anchor materialises only
   on the next issuance, via silent `bootstrapped_from_local_ledger`.
2. No document — `AGENTS.md`, `CLAUDE.md`, `docs/RESEARCH_WORKFLOW.md`, the
   remediation report — mentions committing `audit_lineage/`. It is untracked and
   not ignored, so `git clean -xdf` removes it and nothing records that it existed.
   The local ledger is committed; the anchor is not. The "durable" half is the
   ephemeral one.
3. `NT_AUDIT_LINEAGE_DIR` is documented as *"Production never sets it."* Nothing
   enforces that. An exported variable relocates the anchor to an empty directory
   with no filesystem change and no record in any artifact.
4. The integrity hash covers the anchor's own `entries` only. An **older,
   internally valid** anchor is cryptographically indistinguishable from the
   current one, so rollback (14b) is undetectable — there is no monotonic
   counter, no append-only external log, and no signature over time.

The fix is a real improvement — six previously-successful attacks now fail — but
the stated invariant does not hold.

---

## WARNINGS

### W-A — The authoritative deliverables contract is outside the seal
**Severity: WARNING** (borderline; promote to BLOCKING once a study is executing
against it). Layer: `scripts/resolve_execution_manifest.py::resolve_study_files`.

W1 made `config/deliverables_contract.json` the authority for what a collect run
must produce. The sealed study-file set is:

```
study:SPEC.md   study:study.yaml   study:compiled_study.json
study:research_decision.yaml   study:artifacts/phase0_source_manifest.json
study:tests/test_study_contracts.py
```

**No `studies/*/config/*.json` file is sealed.** `validate_smoke` verifies
`seal_hash == manifest_hash` at step 4 and then reads its deliverable list from a
file that the seal never covered. Reducing `deliverables_by_mode.collect` to
`["candidates.parquet"]` after sealing restores exactly the W1 defect
(`collection_manifest.json` missing passes silently) with the seal still valid.
This is the "mutable sidecar overrides authoritative state" pattern.

The good news, verified: the *smoke date* and *feature list* authorities
(`study.yaml`) **are** sealed, so W4 and W2 do not have this problem.

### W-B — The mandatory `CAUSAL_INVARIANTS` gate cannot finish inside its own budget
**Severity: WARNING.** Layer: `scripts/research_preflight.py` (120 s subprocess
timeout) × `scripts/select_required_tests.py` (40-file selection).

A genuine full preflight on a disposable copy of the acceptance study:

```
RESEARCH PREFLIGHT VERDICT: BLOCKED (125.08s)
Failed Gate: CAUSAL_INVARIANTS
Failure IDs: INVARIANT_TEST_TIMEOUT
```

The timeout is handled correctly (BLOCKED, `audit_ready: false`) — that part is a
PASS. The concern is that **no study in this repository currently has, or can
obtain, a `CLEAR` preflight**: the checked-in artifact for
`es_wick_imbalance_acceptance_v2` is `INCOMPLETE` / `diagnostic_mode: true`. A
mandatory gate that cannot succeed is the precise pressure that produces
`--skip-tests` runs and hand-edited evidence — which RT1-B1 shows is accepted.
The remediation's own "715 passed" figure was obtained by running pytest
directly, outside the 120 s budget the gate imposes.

### W-C — `authorized_dates` is fail-open by omission
**Severity: WARNING.** Layers: `scripts/validate_smoke.py:135-144`,
`backtests/nt_runtime/data_plan.py:69-71`.

Both the validation-side (W4) and execution-side date authorization are `if
authorized_dates:` / `if authorized is None: return None`. A study that simply
omits `execution.data_requirements.authorized_dates` gets **no date
authorization at all**, including acceptance of the hard-coded
`2023-03-03` CLI default. For `es_wick_imbalance_acceptance_v2` the dates *are*
declared (`2024-09-03/04/05`), `chronology.smoke_date` is absent, so the default
`2023-03-03` is correctly refused — this study is safe. Nothing makes the
declaration mandatory for the next one.

### W-D — Promotion evidence hashes raw bytes, defeating W7 for W3
**Severity: WARNING.** Layer: `scripts/check_feature_promotion.py:175`.

`feature_implementation_sha256` uses `hashlib.sha256(p.read_bytes())` on a `.py`
file, not `canonical_file_sha256`. W7 exists because this repo checks out with
`core.autocrlf=true` and no `.gitattributes`. A `reviewed_implementation_sha256`
recorded on a CRLF checkout will not match the same logical source on an LF
checkout, so valid promotion evidence would be rejected across checkouts.
Currently latent — `features/feature_lifecycle_promotions.json` is empty.

### W-E — The study's own contract test is sealed but never run by the mandatory gate
**Severity: WARNING.** Layer: `scripts/select_required_tests.py`.

`studies/<id>/tests/test_study_contracts.py` is inside the sealed composite, and
`scripts/create_study.py` generates a
`test_spec_md_renders_the_deliverables_contract` check. The mandatory
`CAUSAL_INVARIANTS` selection returns **zero** paths under `studies/`. So the
brief's "modify generated SPEC but not contract / contract but not SPEC" attacks
are not caught by preflight; they depend entirely on the LLM `contract-checker`
gate noticing.

### W-F — Feature-surface metadata falls back to a hard-coded list
**Severity: WARNING.** Layer: `scripts/check_feature_surface.py:44-58,142`;
duplicated at `backtests/nt_runtime/output_manager.py:242-246`.

W2 claims *"metadata comes from the study contract, so legitimate non-feature
columns are never rejected."* `es_wick_imbalance_acceptance_v2` declares
`features.metadata_columns: None`, so both call sites fall back to a 13-name
hard-coded list — the same "checker derives its own scope" shape W1 removed from
`validate_smoke`. The list is written out twice, in two files, and can drift.
Fail-closed today, but the contract is not actually the authority it is described
as. Separately, a study *may* whitelist arbitrary columns (including a target
column) as `metadata_columns`; that declaration is sealed and auditable, so it is
a review surface rather than a bypass.

### W-G — `assert_feature_surface` cannot pass `metadata_columns`
**Severity: WARNING.** Layer: `scripts/check_feature_surface.py:238-244`.
The public fail-closed wrapper's signature was not updated for W2, so any caller
using it is pinned to the hard-coded default regardless of the study contract.

### W-H — The governed analysis path does not exist
**Severity: WARNING.** Layer: `docs/RESEARCH_WORKFLOW.md` §6.

The new §6 makes `research/analysis/` the only route to an authoritative result.
`research/analysis/` is **not present in the main tree** (`research/` contains
`engines`, `schemas`, `study_types`, `capabilities.json` only). Every analysis
must therefore stop with `ANALYSIS_HARNESS_GAP`. That is fail-closed and the
doctrine is unambiguous — this is not a bypass — but the doc describes a
component that is not there, which invites an agent to conclude the doc is stale.

---

## NOTES (non-blocking)

- `utils/parity_sampler.py:84` still hard-codes `RTH close = 900 (15:00)`. It is
  imported by nothing, is outside every closure, and only selects rows for a
  parity sample. Not a blocker per the brief's own exclusion.
- `utils/session_boundaries.py:145,172` re-derive `datetime.time(15, 15, 0)`
  locally instead of using the module's own `RTH_START` / `RTH_END` constants.
  Same values today; same lockstep-edit hazard W6 was about.
- `find_escaping_paths` measures escape relative to the *delete target*, not the
  *disposable root*, so a link to a sibling inside the disposable root is flagged.
  Over-strict, fail-closed, harmless.
- The deliverables contract is a minimum set: an unexpected extra artifact in the
  run directory is not reported.
- Byte-identical pass retry is accepted (documented and correct as idempotent).
- A bare-directory preflight prints `CLEAR` with exit 0 while `audit_ready` is
  false. Documented, but the printed word a human reads is the misleading one.
- `checks_run` omits a skipped `CAUSAL_INVARIANTS` (it is recorded only in
  `check_outcomes`). No production consumer reads `checks_run`, so this is
  cosmetic — but it is the field a future reader is most likely to trust.

---

## Pre-existing suite failure — CONFIRMED

Claim: `test_nt_runner_collect.py::test_end_to_end_1day_collect_run_nonzero_candidates`
fails with `PREEXEC_AUDIT_STALE` on `backtests/nt_runtime/data_plan.py` for the
unrelated `Gemini_clean_maturity_flip_rolling_5m_productivity` study, and
predates this work.

Verified mechanically against git blobs, using the canonical hasher:

```
seal expects data_plan : 7838e76e6839
2d664e7 canonical      : 19a879b5d75f     <- task start commit
d2ed8c4 canonical      : 19a879b5d75f
33f5ad1 canonical      : 19a879b5d75f     <- target commit
worktree canonical     : 19a879b5d75f
```

`backtests/nt_runtime/data_plan.py` is not in `33f5ad1`'s changed-file list, and
the Gemini seal was already stale at the start commit. **PRE-EXISTING DEBT, not a
workflow-hardening regression.** (I verified the seal/hash divergence that causes
the failure; I did not re-execute the end-to-end collect test at both commits, to
avoid touching market data.)

---

## Attack matrix

| Attack | Expected | Actual | Result |
| --- | --- | --- | --- |
| **RT-1 preflight completeness** | | | |
| `--skip-tests` | not audit-ready | `INCOMPLETE` / `RUN_FULL_PREFLIGHT_BEFORE_AUDIT`, `audit_ready:false`, exit≠0 | PASS |
| `CAUSAL_INVARIANTS` missing from `checks_run` | refused | recorded as `SKIPPED` in `check_outcomes`, incomplete | PASS |
| mandatory check timeout | refused | real CLI run → `BLOCKED` / `INVARIANT_TEST_TIMEOUT` | PASS |
| mandatory check `SKIPPED` | refused | not in `PASSING_OUTCOMES` → incomplete | PASS |
| **forged / edited preflight JSON** | refused | **ACCEPTED** | **FAIL (RT1-B1)** |
| **`{"audit_ready": true}` two-key stub** | refused | **ACCEPTED** | **FAIL (RT1-B1)** |
| stale preflight from another composite | refused | no composite binding exists to detect it | **FAIL (RT1-B1)** |
| bare-directory path lint | never audit-ready | `CLEAR` but `audit_ready:false` | PASS |
| obsolete artifact (no `audit_ready` key) | refused | `PREFLIGHT_EVIDENCE_OBSOLETE` | PASS |
| missing / corrupt artifact | refused | `MISSING` / `MALFORMED` | PASS |
| **RT-2 execution closure** | | | |
| `import pkg` / `import pkg.mod` | in closure | in closure | PASS |
| `import pkg.mod as alias` | in closure | in closure | PASS |
| `from pkg import mod` (single) | in closure | in closure | PASS |
| `from . import mod` / `from .mod import sym` | in closure | in closure | PASS |
| `from .. import mod` / `from ..mod import sym` | in closure | in closure | PASS |
| ancestor `__init__.py` chain | in closure | in closure | PASS |
| imports triggered by `__init__.py` | in closure | in closure | PASS |
| conditional import on the normal path | in closure | in closure | PASS |
| **`from <namespace pkg> import a, b`** | both in closure | **only `a`; `unresolved:[]`; coverage 100%** | **FAIL (RT2-B1)** |
| unresolved base lowers coverage | coverage < 100 | coverage < 100 | PASS |
| changing a covered module moves composite | yes | yes (composite = `sha256(json(file_hashes))`) | PASS |
| **subprocess-invoked mandatory gates in closure** | yes | **`check_feature_promotion.py`, `select_required_tests.py` OUT** | **FAIL (RT2-B2)** |
| `governance_coverage_pct == 100` truthful | yes | **no** | **FAIL (RT2-B2)** |
| **RT-3 audit lineage** | | | |
| same pass, different composite | refused | `AUDIT_PASS_IMMUTABLE` | PASS |
| lower pass number | refused | `AUDIT_PASS_IMMUTABLE` | PASS |
| reused pass after higher / identical retry | idempotent | accepted (documented) | PASS |
| delete local pass report / ledger | detected | `AUDIT_LINEAGE_RESET_DETECTED` | PASS |
| delete / rename / recreate audit dir | detected | `AUDIT_LINEAGE_RESET_DETECTED` | PASS |
| copy study to another path | explicit + safe | new identity, bootstraps | PASS |
| rebuild study, same identity | detected | `AUDIT_LINEAGE_RESET_DETECTED` | PASS |
| corrupt lineage anchor | fail closed | `AUDIT_LINEAGE_UNREADABLE` | PASS |
| tampered anchor entries | detected | `AUDIT_LINEAGE_TAMPERED` | PASS |
| foreign study's anchor | detected | `AUDIT_LINEAGE_IDENTITY_MISMATCH` | PASS |
| edit study identity, keep artifacts | high-water preserved | `AUDIT_PASS_IMMUTABLE` | PASS |
| anchor rollback (anchor only) | refused | `AUDIT_LINEAGE_UNANCHORED` | PASS |
| **delete lineage anchor** | history survives | **pass 01 ACCEPTED** | **FAIL (RT3-B1)** |
| **rollback anchor + ledger together** | refused | **pass 02 reissued vs new composite** | **FAIL (RT3-B1)** |
| **`NT_AUDIT_LINEAGE_DIR` redirect** | no effect | **anchor protection removed, no trace** | **FAIL (RT3-B1)** |
| anchor exists for the real study | yes | **no — `audit_lineage/` absent, untracked** | **FAIL (RT3-B1)** |
| **RT-4 feature grandfathering** | | | |
| A. registry-only addition | needs evidence | refused (no promotion record) | PASS |
| B. registry **+** baseline addition | refused | `PROMOTION_BASELINE_EXTENDED` | PASS |
| C. grow pinned + active together | refused | `PROMOTION_BASELINE_TAMPERED` | PASS |
| D. swap a pinned identity, same count | refused | `PROMOTION_BASELINE_TAMPERED` | PASS |
| drop `pinned_original_verified` key | refused | `PROMOTION_BASELINE_MALFORMED` | PASS |
| baseline may shrink | allowed | allowed | PASS |
| E. remove then re-add a pinned name | allowed by design | allowed (subset rule) | PASS (noted) |
| F. stale promotion evidence | refused | impl-hash mismatch refused | PASS |
| G. change implementation after promotion | refused | `reviewed_implementation_sha256` mismatch | PASS |
| H. change tracker path after promotion | refused | new module hash → mismatch | PASS |
| `latest_1m_wick_imbalance` still provisional | yes | `status='provisional'`, no promotions file | PASS |
| **pin edit forces re-audit** | yes | **pin is outside the composite** | **FAIL (RT2-B2)** |
| **Deliverables contract** | | | |
| delete `collection_manifest.json` | refused | `MISSING_DECLARED_DELIVERABLE` | PASS |
| delete candidates / observations | refused | refused earlier in the validator | PASS |
| declare impossible artifact | refused | `MISSING_DECLARED_DELIVERABLE` | PASS |
| add required artifact, don't produce it | refused | `MISSING_DECLARED_DELIVERABLE` | PASS |
| absent contract | refusal, not substitution | `DELIVERABLES_CONTRACT_MISSING` | PASS |
| validator owns deliverable truth | contract, not hard-coded list | contract | PASS |
| SPEC changed, contract not (or vice versa) | caught | not caught by preflight (W-E) | WARNING |
| **contract editable after seal** | no | **yes — `config/*.json` unsealed** | **WARNING (W-A)** |
| unexpected extra artifact | — | not reported | NOTE |
| **Feature surface** | | | |
| declared column missing | refused | `FEATURE_COLUMN_MISSING` | PASS |
| declared column all NULL | refused | `FEATURE_NEVER_EMITTED` (under either policy) | PASS |
| partial NULL vs policy | refused | `FEATURE_NULL_POLICY_VIOLATION` | PASS |
| extra undeclared column | refused | `UNDECLARED_FEATURE_COLUMN` + `UNEXPECTED_OUTPUT_COLUMN` | PASS |
| changed feature order | refused | `FEATURE_SURFACE_IDENTITY_MISMATCH` + sha mismatch | PASS |
| duplicate feature column | refused | `DUPLICATE_OUTPUT_COLUMNS` | PASS |
| registry / contract disagreement | refused | `FEATURE_NOT_REGISTERED` | PASS |
| metadata authority is the contract | yes | falls back to hard-coded list when undeclared | WARNING (W-F) |
| **Smoke date authorization** | | | |
| authorized day | accepted | accepted | PASS |
| other TRAIN-year day / arbitrary 2024 day | refused | `UNAUTHORIZED_SMOKE_DATE` | PASS |
| default CLI date `2023-03-03` | refused | refused (not in authorized set) | PASS |
| emitted candidates outside authorized days | refused | `UNAUTHORIZED_CANDIDATE_DATES` | PASS |
| execution window beyond authorized span | refused | `UNAUTHORIZED_EXECUTION_DATE` (`data_plan`) | PASS |
| study omits `authorized_dates` | — | **no check at all** | WARNING (W-C) |
| **Transcript provenance** | | | |
| arbitrary text / empty / source file | no upgrade | `DECLARED_IDENTITY_ONLY`, `attached_artifact` only | PASS |
| nonexistent file | no upgrade, no crash | ignored | PASS |
| same artifact for both auditors | no upgrade | both `DECLARED_IDENTITY_ONLY` | PASS |
| `SESSION_BOUND` reachable at all | no | unreachable | PASS |
| `independence_proven` honest | `false` | `false`, with stated limitations | PASS |
| **Line endings / seal reproducibility** | | | |
| LF vs CRLF vs CR, same source | same hash | same hash | PASS |
| genuine content change | different hash | different hash | PASS |
| tab vs space indentation | different hash | different hash | PASS |
| binary (`.parquet`) | byte-exact, not normalised | byte-exact | PASS |
| seal and manifest share one hasher | yes | yes (also the audit-report hasher) | PASS |
| promotion evidence uses canonical hash | yes | **no — raw bytes** | WARNING (W-D) |
| **RTH consistency** | | | |
| `features/engine.py` (×2) | canonical module | routes to `utils/session_boundaries` | PASS |
| `features/library.py` | canonical module | routes to `utils/session_boundaries` | PASS |
| `strategies/flip_prediction_collector.py` | canonical module | routes to `utils/session_boundaries` | PASS |
| remaining 15:00 in governed execution | none | only `utils/parity_sampler.py` (unimported, unsealed) | PASS (NOTE) |
| **Analysis governance docs** | | | |
| could docs authorize scratch pandas as a conclusion | no | explicit `NON-AUTHORITATIVE` + `ANALYSIS_HARNESS_GAP` | PASS |
| scratch runner wrappers prohibited | yes | explicit | PASS |
| duplicate concurrent runs prohibited | yes | explicit, with `reconcile_runs.py` | PASS |
| named governed path exists | yes | **`research/analysis/` absent** | WARNING (W-H) |
| **Filesystem safety** | | | |
| written rule covers junctions/symlinks/mounts/reparse | yes | all four, explicitly | PASS |
| rule requires abort-entire-deletion on escape | yes | explicit | PASS |
| junction detected where `is_symlink()` is False | yes | `is_symlink=False`, reparse detected `True` | PASS |
| nested escaping junction | refuse whole delete | `UNSAFE_DELETION_ESCAPES_ROOT` | PASS |
| delete target is itself a junction | refused | `UNSAFE_DELETION_TARGET_OUTSIDE_ROOT` | PASS |
| external data survived every probe | yes | verified present after each refusal | PASS |
| guard wired into any real cleanup path | — | advisory only; no production caller | NOTE |
| **Pre-existing failure** | | | |
| Gemini seal stale at `2d664e7` | yes | `7838e76e…` vs `19a879b5…` at all three commits | CONFIRMED |

---

## Smallest responsible layers

1. **`scripts/resolve_execution_manifest.py`** — owns both RT2-B1 (the `break` in
   the `ImportFrom` fallback) and RT2-B2 (governance seed scope: subprocess-invoked
   gates and `studies/*/config/*.json` are never seeded). Two independent defects,
   one file.
2. **`scripts/research_preflight.py::assert_preflight_audit_ready`** — RT1-B1.
   The evidence it reads is bound to nothing.
3. **`scripts/run_preexec_audits.py` lineage anchor storage** — RT3-B1. The
   reconciliation *logic* is sound; the anchor's *durability* is not.

## MUST FIX BEFORE RESEARCH

- **RT2-B1** — remove the `break`; enqueue every alias; record unresolved aliases.
- **RT2-B2** — seed the closure with every script the preflight shells out to, and
  hash `features/feature_lifecycle_baseline.json`. Add a test asserting that the
  set of `subprocess`-invoked scripts in `research_preflight.py` is a subset of
  `file_hashes`.
- **RT1-B1** — bind `preflight.json` to the composite it was produced against
  (record `execution_composite_sha256`, and have both consumers recompute and
  compare), and refuse when a non-tombstoned `failure_packet.json` is present.
- **RT3-B1** — commit `audit_lineage/` (it is neither tracked nor ignored today),
  remove or restrict `NT_AUDIT_LINEAGE_DIR` to an explicit test-only marker, and
  treat a missing anchor for a study that has a *committed* ledger as
  `AUDIT_LINEAGE_ANCHOR_MISSING` rather than a silent bootstrap.
- **W-A** — seal `studies/*/config/*.json`, or make `validate_smoke` read the
  deliverables list from the sealed `compiled_study.json`.

## BACKLOG / DOES NOT BLOCK RESEARCH

W-B (gate timeout budget — but it blocks *use* of the workflow, so fix it early),
W-C, W-D, W-E, W-F, W-G, W-H, and all NOTES.

---

**Files modified: NONE** (this report added; no implementation, study, seal, audit
artifact or data file was changed).
