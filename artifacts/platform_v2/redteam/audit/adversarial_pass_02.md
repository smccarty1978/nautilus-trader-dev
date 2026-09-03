---
audit_type: "adversarial"
auditor: "independent adversarial reviewer (pass 02)"
audited_head: "5ff9bc55"
base: "main c366aac4"
---

# Adversarial red-team pass 02 — Platform V2 remediation branch

Independent second pass. I wrote none of the repairs and used
`research_workflow/tests/test_redteam_v2_*.py` only as a map of intended invariants; every
result below comes from my own scripts under
`artifacts/platform_v2/redteam/adversarial/`, executed against
`chore/platform-v2-redteam-hardening` head `5ff9bc55`.

No file under `studies/` or `data/` was touched. The real writer-lease directory was never
written. One model *was* written into the real store by the golden end-to-end run before I
understood that `V2Options` has no `model_root` (finding W-5); it was located and removed
(`~/.nt_research/models/models/29a3683c…`, study_id `adv_e2e`), and every subsequent run
redirects `roots.resolve_model_root` to a tmp dir. The store and leases dir were re-verified
clean at the end.

## Verdict: **BLOCKED** — 2 CRITICAL, 5 WARNING, 5 NOTE

Every one of the nine original findings is genuinely closed against the attack that produced
it. Both CRITICALs below are *adjacent* to a closed finding: the same defect class, one step
outside the fix's boundary.

## Per-attack results

| ID | Executed | Result | Evidence (script → key line) |
|---|---|---|---|
| **A1** `--years` role expansion | Y | **BLOCKED-AS-EXPECTED** | `adversarial/a1_years.py` (30 cases) + `a1b_wiring.py` (13 cases on a real compiled plan). Cross-role, prohibited, empty, string, `None`-in-list, unknown-period, stale/tampered/deleted authorization artifact — all `LifecycleV2Error: YEARS_NOT_AUTHORIZED`. e.g. `YEARS_NOT_AUTHORIZED: period=oos requested=[2030] authorized=[2031] prohibited=[2032]`. Legal narrowings still succeed. Wiring confirmed at `lifecycle_v2.py:491,527,564,757`. One NOTE (N-1). |
| **A2** closure omission | Y | **PARTIAL** | `a2_closure.py`: perturbing each of `lifecycle_v2 / governed_controller_v2 / experiment / tuning / model_store / audit_packets_v2 / policy / locks / dataset_v2` moves the composite **and only its own stage** (`lifecycle`→lifecycle, `oos`→oos, `modeling`→modeling, `dataset_v2`→collection). `a2b_omission.py` + a full-lifecycle import trace found real omissions → **W-4**, **N-5**. |
| **A3** spoofed legacy authority | Y | **PARTIAL / BYPASSED (adjacent)** | `a3_legacy_authority.py`: (a) empty seal, (b) copied foreign seal, (c) stale composite, (d) untracked, (e) composite mismatch, (f) edited study id — all `OldRuntimePolicyError`. Junction-out-of-repo blocked. **3 adjacent bypasses → C-A.** |
| **A4** model identity | Y | **PARTIAL / BYPASSED (adjacent)** | `a4_model_identity.py` + `a4b_bytes_golden.py`: copied dir, in-place canonical corruption (`CANONICAL_BYTES_CORRUPT`), tampered/refreshed golden (`GOLDEN_PREDICTION_MISMATCH: max_abs_diff=0.5`), mutated golden frame (`GOLDEN_FRAME_CORRUPT`), reordered `ordered_inputs`, all five legacy/unknown `identity_rule`s with fabricated records, ledger tier (`MODEL_TIER_NOT_REUSABLE`), three `expect` mismatches, non-identity preprocessing — all blocked. **3 adjacent bypasses → C-A**, plus **W-1**. |
| **A5** tuning | Y | **BLOCKED-AS-EXPECTED** | `a5_tuning.py`: with a pruner that prunes exactly the highest-partial-value trials, `states={'COMPLETE':5,'PRUNED':5}`, best PRUNED `optuna_value=0.91819` vs `selected=#8 state=COMPLETE aggregate=0.70195` — and `aggregate == mean(fold_scores)` exactly. Planted COMPLETE trials with `value=0.999` and missing/short/null `fold_scores` are `NO_FOLD_SCORES`/`INCOMPLETE_FOLDS`/`NULL_FOLD_SCORE` ineligible. Identical identity resumes; a planted study-name collision raises `TUNING_RESUME_IDENTITY_MISMATCH: population_identity`. All-pruned raises `TUNING_NO_COMPLETE_TRIAL`. |
| **A6** concurrency | Y | **BLOCKED-AS-EXPECTED** | `a6_concurrency.py`: 8-process `locks.acquire_exclusive` race → exactly 1 winner, twice, lock payload = winner pid. 6-process `store_model` on one id → 1 model dir, 1 distinct canonical sha, 6 successes, no leftover `.staging`. Lease: live-past-creator-death, stale-past-TTL, `WRITER_LEASE_HELD_BY_OTHER` on foreign renew, `LEASE_RELEASE_REFUSED` on foreign release, `WRITER_LEASE_HELD` on a second writer, `ws_list --reclaim` leaves a live lease live, `dead` when the worktree is gone, v1 schema still readable. |
| **A7** sessions | Y | **PARTIAL** | `a7_sessions.py`: RTH `(08:30, 15:15]`, early close tightens to 12:15, holiday day absent, DST-safe (13:xxZ CDT / 14:xxZ CST), ETH post-segment starts at the declared 15:30 halt end, half-open attribution exact, `SESSION_CLOSE_UNDEFINED_FOR_LEGACY_ETH`, `REFERENCE_DIGEST_MISMATCH`, `REFERENCE_TABLE_CORRUPT`, `REFERENCE_TABLE_MISSING`, and both compiler refusals (`SEMANTIC_DECISION_REQUIRED` for legacy-ETH censoring and for `reference_tables` without `sessions`) all fire. **3 adjacent findings → W-3, N-2.** |
| **A8** gap precedence | Y | **PARTIAL / BYPASSED (adjacent)** | `a8_gap_precedence.py`, kernel + oracle on the same tapes: post-horizon bar beyond `max_gap` → `CENSORED/GAP` in both (with `expiry:negative` too); first post-horizon bar past the session close → `CENSORED/SESSION_END` in both; gap `== max_gap` is not a gap, `max_gap+1s` is; a bar closing exactly at the horizon end is touch-eligible (`POSITIVE`); session close before the horizon end → `SESSION_END`. **`strict` bypass → C-B**, plus **W-2**, **N-3**. |
| **A9** zero-python + execute gate | Y | **BLOCKED-AS-EXPECTED** | `a9_a10_e2e.py`: `scan_study_python` catches `helpers.py`, `sub/nested/deep.py`, `note.ipynb`, `SHOUT.PY`, `_work2/hidden.py`, `runs_x/sneak.py`, `pkg/__init__.py` and ignores only `_work/` and `runs/`; `.pyc` correctly not flagged; readiness → `READINESS_FAILED: R10_zero_study_python`; a `study.yaml`-declared `python_exception` is `INVALID_PARAMETERIZATION` at compile (`STUDY_PYTHON_EXCEPTIONS` is `{}` and platform-side only). Controller `run(through=…)` without `--execute-authorized` returns `blocker_code=EXECUTION_NOT_AUTHORIZED`, `actions_executed=[]`, `run.lock` never created — for all nine post-seal stages; every direct `V2Lifecycle.<leaf>()` raises `EXECUTION_NOT_AUTHORIZED: <stage> requires --execute-authorized`. |
| **A10** zero-prose deliverables | Y | **BLOCKED-AS-EXPECTED** | `a10_deliverables.py`: all 22 expanded paths from `deliverables_for_plan(plan)` (`{a,b}` and `<year>` expanded against the plan's own chronology) exist on disk after a real full golden run through `close`. `MISSING: []`. `audit_packets_v2` imports `lifecycle_v2.DELIVERABLES` — no second copy. |

---

## New findings

### CRITICAL

#### C-A — "git-tracked" means the INDEX, and the bytes are read from the working tree: every legacy-authority and legacy-model-identity check can be satisfied with fabricated evidence

`research_workflow/policy.py:86` `_git_tracked` runs `git ls-files --error-unmatch <path>`,
which succeeds for a file that was merely `git add`ed and **never committed**. Every consumer
then reads the **working-tree** bytes and validates them for **self-consistency only** —
`research_workflow/seal.py:61` `seal_body_hash` is a pure function of the seal's own
`file_hashes`, and the TRAIN-freeze / registry-record checks are likewise pure functions of the
attacker-supplied file. No committed blob is ever consulted. The error strings say
"not committed to git at HEAD", which is precisely what the check does not do.

Three separate authorities fall to the same primitive. All executed, all **GRANTED**:

1. `policy.assert_old_runtime_allowed` — fabricated v1 study, `git add` only:
   `GRANTED {"platform": "v1_historical", …, "study_id": "v1_index_only"}`.
2. `policy.assert_old_runtime_allowed` — a genuinely **committed** study whose seal + manifest
   are rewritten in the working tree, self-consistently, after the commit. Script printed
   `HEAD composite: 3118feb7f4bc838f  worktree composite: ec44a258c73b7155` — and authority was
   still granted. The grant therefore attests nothing about what was actually executed.
3. `model_store.py:425 _verify_legacy_v1_train_freeze` — a fabricated
   `studies/totally_fabricated_v1_study/artifacts/train_experiment_freeze.json`, `git add` only,
   in a directory that has **no `preexec_audit_seal.json` at all** (`fabricated study has a
   seal: False`): `authenticate_model` returns `AUTHENTICATED … identity_rule
   legacy_v1_train_freeze`. Answering the brief's question directly: the rule requires the
   freeze to be *index-tracked*, verifies the freeze's own `freeze_sha256` (self-recomputed),
   and **never checks the study's seal**. It also accepts a committed freeze rewritten in the
   working tree to vouch for a different `fit_identity_sha256` (`HEAD freeze_sha256:
   316910b17606c39a  worktree: 492c3028c5d88938` → AUTHENTICATED).
4. `model_store.py:484 _verify_legacy_v1_committed_registry` — fabricated
   `studies/model_registry/<id>.json`, `git add` only → AUTHENTICATED.

**Repro:** `python artifacts/platform_v2/redteam/adversarial/a3_legacy_authority.py` (cases g/h/i)
and `a4_model_identity.py` (the three ADJACENT cases). Both build their own throwaway git repos.

**Smallest fix:** in `_git_tracked`, resolve the blob at HEAD and compare it to the working-tree
bytes — `git rev-parse --verify HEAD:<rel>` vs `git hash-object <file>` — refusing when the path
is absent from HEAD or the hashes differ. Every caller (`verify_historical_authority`,
`_verify_legacy_v1_train_freeze`, `_verify_legacy_v1_committed_registry`) then means what its
error string already claims. `legacy_v1_train_freeze` should additionally require the freezing
study's own `preexec_audit_seal.json` to authenticate under `verify_historical_authority`.

#### C-B — `horizon_end_rule: strict` (the DEFAULT) bypasses GAP precedence at the horizon end; kernel and oracle manufacture the same NEGATIVE from an unobserved interval

`research_workflow/host/outcomes.py:323` takes the `strict` branch **before** the session-close
and gap checks:

```python
if past_end and self.c.horizon_end_rule == "strict":
    self._expire_arm(p, i)      # -> NEGATIVE when arm.expiry == "negative"
    continue
```

and `research_workflow/target_replay_oracle.py:120` mirrors it (`if end_rule !=
"first_bar_at_or_after": break` → falls through to `horizon_expiry_policy`). So a
`max_gap`-exceeding tape gap that **straddles** the horizon end resolves as a horizon expiry,
not as a gap — with `expiry: "negative"` that is a directional loss label backed by zero price
observation over the whole unobserved interval. This is the identical defect class the causal
pass fixed at `5ff9bc55` for `first_bar_at_or_after`; `strict` was not covered, and `strict` is
the **default** (`outcomes.py:88`, `grammar/spec.py`). Because kernel and oracle share it
verbatim, the parity harness cannot detect it — both sides agree and both are wrong.

**Executed** (`a8_gap_precedence.py`, case `A8-ADJ1`): last observation `T+10s`, next bar
`T+400s`, horizon end `T+61s`, `max_gap=30s`, `expiry=negative` →
`kernel=NEGATIVE/None  oracle=NEGATIVE/None  parity=True`, expected `CENSORED/GAP`.
With `expiry=censor` the same tape gives `CENSORED/TIMEOUT` in both — a data gap misattributed
as a horizon expiry in the censoring taxonomy, which silently corrupts any downstream analysis
that partitions censoring reasons.

**Repro:** `python artifacts/platform_v2/redteam/adversarial/a8_gap_precedence.py` → rows
`A8-ADJ1`, `A8-ADJ1'`.

**Smallest fix:** in both files, evaluate SESSION_END and GAP **before** the `strict`
expiry branch, exactly as the `first_bar_at_or_after` branch now does — i.e. when the first bar
observed at or after the horizon end is separated from `prev_ts` by more than `max_gap`, resolve
`CENSORED/"GAP"` regardless of `horizon_end_rule` and `expiry`. Add the mirror regression to
`test_redteam_v2_gap_precedence.py`.

### WARNING

#### W-1 — `authenticate_model` cannot detect a substituted estimator
`model_id` is `sha256(lineage)` only; it commits to no bytes. `canonical/*`,
`canonical.byte_sha256`, `golden/expected.json` and `golden.expected_sha256` all live in the
same writable model directory. Every *individual* tamper is caught (`CANONICAL_BYTES_CORRUPT`,
`GOLDEN_PREDICTION_MISMATCH`, `GOLDEN_FRAME_CORRUPT`), but writing a **different** LightGBM
booster, refreshing `byte_sha256`, re-scoring the golden frame with it and refreshing
`expected_sha256` authenticates identically under the unchanged `model_id`.
**Executed** (`a4b_bytes_golden.py`, section A4c): `model_id unchanged 58d96e05de30f330`,
`canonical sha before 247b2d692f4b6859 → after 5fd204710539e766`, still AUTHENTICATED.
*Fix:* fold `canonical.byte_sha256` (and the golden `frame_content_sha256` /
`expected_sha256`) into the id formula, or record the manifest hash in the study's seal so
substitution stales the seal.

#### W-2 — the oracle manufactures a directional label at data end (kernel/oracle parity divergence)
Tape ends before the horizon with `horizon_expiry_policy: negative`:
`kernel=CENSORED/DATA_END` vs `oracle=NEGATIVE/None`. The oracle's barrier path has no
DATA_END concept; it exits its loop and falls through to the expiry policy. Reproduced twice
(`A8-ADJ4` with a far-future entry bar, `A8-ADJ6` with a truncated tape).
*Fix:* the oracle must distinguish "the tape ran out before the horizon" from "the horizon
elapsed with observations throughout", and censor `DATA_END` for the former.

#### W-3 — the DatasetSpec `reference_digest` silently stops binding when a study declares a subset of the catalog's reference tables
`research_workflow/dataset_v2.py:162`: `if reference_digest is not None and set(declared) >=
set(ref_manifest)`. Declaring a strict subset makes the guard False and the aggregate check is
skipped with no diagnostic. **Executed** (`a7_sessions.py`): a catalog whose manifest builds
`{sessions, holidays}`, a study declaring only `["sessions"]`, and a stale single-table
aggregate digest → loaded, no `REFERENCE_DIGEST_MISMATCH`. Compounding:
`research_workflow/roots.py:145` `compute_catalog_digest` hashes only `<catalog>/data/**`, so
`reference/` **and** `build_manifest.json` sit outside readiness R1's byte verification — the
git-committed `reference_digest` is the *only* external anchor for the session windows that
drive every SESSION_END censoring decision and the population gate. Today's specs
(`research/datasets/NQ_1S_V2.yaml`, `ES_1S_V2.yaml`) declare all six tables so the check does
bind; adding a seventh table to a future catalog build disarms it for every existing study
without a single error.
*Fix:* verify the aggregate over the declared subset (recompute from the manifest entries for
`declared` only) instead of skipping, and extend `compute_catalog_digest` to cover
`reference/` + `build_manifest.json`.

#### W-4 — execution-closure omissions with governance or scientific reach
Perturbing each of these leaves the plan composite **unchanged** (`a2b_omission.py`; controls
`host/outcomes.py` and `policy.py` do move it):
- `research_workflow/seal.py` — `policy.verify_historical_authority` (lifecycle stage, hashed)
  calls `seal.seal_body_hash` as the *entire* self-consistency authority for legacy runtime
  provenance. The rule can be redefined without staling any seal.
- `research_workflow/workspace.py` — writer-lease state machine consumed by
  `governed_controller_v2._check_writer_lease`.
- `features/registry.py` — for a real `features.host: features` study this decides canonical
  feature identity, parameter validation and physical alias generation at compile time. Only
  the *result* lands in the plan, so the blast radius is bounded, but because the composite does
  not move, `_fresh_stage("compile")` will not recompile and R9 will not fail.
- `research/schemas/study_spec.py` — `DerivedCausalInputSpec`, parsed **at runtime** by
  `features/trackers/host_bindings.py:669-671` on the frozen-external-score path (that path adds
  `external_model_scoring.py` to the closure at `compiler.py:920` but not this).
*Fix:* add `research_workflow/seal.py` + `research_workflow/workspace.py` to the `lifecycle`
stage set; add `features/registry.py` and `research/schemas/study_spec.py` to `collection`
whenever the feature host / derived-score path is bound.

#### W-5 — a governed V2 `fit()` always writes to the operator's real durable model store
`V2Options` has no `model_root`, so `lifecycle_v2.fit()` → `model_store.store_model()` resolves
`roots.resolve_model_root()` unconditionally. Any throwaway run — a tmp study, a smoke run, and
the repository's own golden end-to-end test `research_workflow/tests/test_lifecycle_v2.py` —
permanently writes a model into the shared cross-study store. Confirmed: my first e2e run
created `~/.nt_research/models/models/29a3683c42723317…` with `lineage.study_id = "adv_e2e"`
(removed; store re-verified clean).
*Fix:* add `model_root: Optional[Path]` to `V2Options`, thread it into `fit()`/`_fit_score_mode`,
and have the golden test set it to `tmp_path`.

### NOTE

- **N-1** `lifecycle_v2.py:168` applies the prohibited-year check only to explicitly requested
  years. With `requested=None` (the default path, no `--years`), a chronology listing a year in
  both `train` and `prohibited` returns it: `authorized_years({"chronology":{"train":[2029,2032],
  "dev":[2031],"prohibited":[2032]}}, "train", None) -> [2029, 2032]`. Unreachable through the
  compiler (`grammar/compiler.py:927-929` raises `SEMANTIC_DECISION_REQUIRED` on the overlap), so
  defense-in-depth only. Cheap fix: subtract `prohibited` from `role_years` before returning.
- **N-2** `sessions.py:175` still does not validate `halt_end_ns >= rth_close` (the prior causal
  pass's open C8 note) — executed with `halt_end` 14:30 CT: ETH post-window
  `(1591903800…, 1591909200…]` overlaps RTH `(1591882200…, 1591906500…]`, and no
  `CALENDAR_SESSIONS_OVERLAP` fires because RTH and ETH tables are validated separately. Also,
  a row with `close_ns < open_ns` silently yields an RTH window `(08:30, 09:00]` that lies
  entirely outside the actual tape. Both sit behind the fail-closed reference-table hash, so
  they need a wrong-but-authentic sessions table.
- **N-3** `max_gap` is measured from `entry_ts`, never from `T`: an arbitrarily large tape gap
  between the decision epoch and the entry bar is never a GAP on either side (executed: entry
  bar 500 s after T with `max_gap=30s`). Both implementations agree, so this is a semantics
  question, not a parity break — but it should be stated in the outcome contract.
- **N-4** `authorized_years` `int()`-truncates floats (`[2029.9] -> [2029]`). Truncation can only
  land on an already-authorized year, so it is not exploitable; rejecting non-integers would be
  tidier.
- **N-5** `research/analysis/spec.py` and `research/analysis/errors.py` are module-level imports
  of the hashed `research/analysis/modeling.py` but are themselves unhashed. Inert today — v2
  `fit()` uses only `_build_estimator` and `frame_content_identity`, which depend on
  `SUPPORTED_ESTIMATORS` (defined in `modeling.py:42`) and `InvalidAnalysisSpec` — but any future
  v2 use of `AnalysisSpec`/`ModelArm` would be outside the closure.

## What I confirmed is genuinely closed

CRIT-1 (role authority, incl. stale/tampered/deleted authorization artifacts), CRIT-4
(COMPLETE-only tuning winners, over a constructed search where the pruned trials hold the best
partial value), CRIT-5 (8-process atomic lock, twice), CRIT-6 (durable lease: TTL, ownership,
reclaim, v1 schema), CRIT-9's `first_bar_at_or_after` branch (kernel/oracle parity on
GAP and SESSION_END, with `expiry:negative`), CRIT-8's calendar derivation and both compiler
refusals, WARN model-store same-id concurrency, WARN Optuna resume identity, WARN
`--execute-authorized` at both the controller and every lifecycle leaf, WARN zero-study-Python
(including the `.PY` and nested-directory bypasses and a self-declared study exception), and
WARN deliverables single-sourcing (all 22 expanded paths verified on disk after a real run).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "adversarial", "auditor": "independent adversarial reviewer (pass 02)", "audited_head": "5ff9bc55", "critical": 2, "warning": 5, "note": 5, "attacks_executed": 10, "bypassed": ["A3", "A4", "A7", "A8"]}
<!-- AUDIT_SUMMARY_V2_END -->
