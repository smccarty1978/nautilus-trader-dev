---
audit_type: "adversarial"
auditor: "independent adversarial reviewer (pass 03, re-verification)"
audited_head: "f64009e6"
previous_pass: "adversarial_pass_02.md @ 5ff9bc55 (BLOCKED, 2 CRITICAL / 5 WARNING / 5 NOTE)"
fix_commits: "de99f413, f64009e6"
---

# Adversarial red-team pass 03 — re-verification of the Platform V2 remediation branch

Second-pass re-run. Every attack script written by the previous reviewer at `5ff9bc55`
(`artifacts/platform_v2/redteam/adversarial/*.py`) was re-executed against `f64009e6`, plus five
new attacks aimed at the fixes themselves.

**Execution mechanics.** The originals derive the repo root as `Path(__file__).parents[4]` and
write their result JSON next to themselves. To re-run without overwriting pass-02 evidence, every
script was copied verbatim to `artifacts/platform_v2/redteam/adversarial/rerun_f64009e6/` with a
single mechanical edit — `parents[4]` → `parents[5]` (one directory deeper). One further minimal
adaptation was required and is called out in the table (A7). Nothing under `studies/`, `data/`,
the real model store (`~/.nt_research/models`) or the real lease directory
(`~/.nt_research/leases`) was written: the store was snapshotted before (476 model dirs) and after
(476, `added=[] removed=[]`, attack N5e) and the three live leases are untouched.

## Verdict: **CLEAR_WITH_WARNINGS** — 0 CRITICAL, 3 WARNING, 4 NOTE

Both pass-02 CRITICALs (C-A git-index authority, C-B strict-rule gap precedence) are closed
against the exact attacks that produced them and against every adjacent variant I could build.
Three warnings remain; none of them corrupts a scientific result, OOS boundary, causal contract,
authority decision, runtime identity or cross-study state without an actor who already holds write
access to the repository or the durable model store.

## Per-script re-run (all 10 executed)

| ID | Result @ f64009e6 | Was @ 5ff9bc55 | Exact evidence line |
|---|---|---|---|
| **A1** `a1_years.py` (30 cases) | **BLOCKED** | BLOCKED (+N-1, N-4) | `BYPASSED/UNEXPECTED: []`. N-1 closed: `plan lists 2032 in BOTH train and prohibited, requested=None (default path)` → `LifecycleV2Error: YEARS_NOT_AUTHORIZED: role years intersect prohibited (period=train role=train years=[2029, 2032] prohibited=[2032] overlap=[2032])`. N-4 closed: `2029.9` → `YEARS_NOT_AUTHORIZED: period=train non-integer year: 2029.9 is not an integral year`; `True` → `is a bool, not a year`. |
| **A1b** `a1b_wiring.py` (13 cases on a real compiled plan) | **BLOCKED** | BLOCKED | `BYPASSED: []` |
| **A2** `a2_closure.py` | **BLOCKED (stage isolation)** | PARTIAL | Per-module perturbation still moves the composite and only that module's own stage. Residual unhashed-but-imported set unchanged in kind (see NOTE-2). |
| **A2b** `a2b_omission.py` (12 candidates) | **PARTIAL → improved** | PARTIAL (W-4) | `research_workflow/seal.py hashed=True moves=True`, `research_workflow/workspace.py hashed=True moves=True` (both were `False/False`). Controls `host/outcomes.py`, `policy.py` still move. `features/registry.py`, `research/analysis/{spec,errors,loader}.py`, `capabilities.py`, `features/engine.py`, `utils/runner/data.py` still `hashed=False` on the **synthetic-host** golden study — see the separate verification below. |
| **A3** `a3_legacy_authority.py` (12 cases) | **BLOCKED** | PARTIAL / **BYPASSED → C-A** | `BYPASSED: []` (the one row listed is case (k), an `UNEXPECTED_REJECT`, i.e. a rejection). C-A cases now all refuse: (g) `git add`-only → `HISTORICAL_AUTHORITY_UNTRACKED: … is missing or not committed to git at HEAD`; (h) committed-then-rewritten-in-worktree → `HISTORICAL_AUTHORITY_MODIFIED_IN_WORKTREE: studies/v1_worktree_swap/artifacts/preexec_audit_seal.json was committed at HEAD but the working-tree bytes … differ from that commit`; (i) committed only on another branch → `HISTORICAL_AUTHORITY_UNTRACKED`. Control (b0) still `GRANTED`. |
| **A4** `a4_model_identity.py` (20 cases) | **BLOCKED** | PARTIAL / **BYPASSED → C-A** | `BYPASSED: []`. All three C-A adjacents refuse, and with a stronger reason than the minimum fix: `MODEL_IDENTITY_UNVERIFIABLE: legacy_v1_train_freeze requires an AUTHENTICATED historical seal for study 'totally_fabricated_v1_study' (a freeze with no seal grants no authority): HISTORICAL_AUTHORITY_UNTRACKED: …`. Fabricated `studies/model_registry/<id>.json` → `MODEL_IDENTITY_UNVERIFIABLE: HISTORICAL_AUTHORITY_UNTRACKED`. |
| **A4b** `a4b_bytes_golden.py` | **PARTIAL / BYPASSED (W-1 residual)** | PARTIAL (W-1) | Individual tampers all still caught (`GOLDEN_PREDICTION_MISMATCH: max_abs_diff=0.9374919632969413`, `GOLDEN_FRAME_CORRUPT`). Section A4c unchanged: `model_id unchanged: 58d96e05de30f330 / canonical sha before: 247b2d692f4b6859 after: 5fd204710539e766 / authenticate_model after substitution -> AUTHENTICATED`. See **WARN-1**. |
| **A5** `a5_tuning.py` | **BLOCKED** | BLOCKED | `BYPASSED: []`; `selected=#8 state=COMPLETE aggregate=0.701953 ; best PRUNED optuna_value=0.9181908037151095 ; n_pruned=5`; `aggregate=0.7019531409966334 mean(fold_scores)=0.7019531409966334`. |
| **A6** `a6_concurrency.py` | **BLOCKED** | BLOCKED | `BYPASSED: []`; 8-process lock race → one winner; `WRITER_LEASE_HELD_BY_OTHER`, `LEASE_RELEASE_REFUSED`, `WRITER_LEASE_HELD`, reclaim leaves a live lease live, `state=dead` when the worktree is gone. |
| **A7** `a7_sessions.py` (**adapted**) | **BLOCKED** | PARTIAL (W-3, N-2) | *Adaptation:* the N-2 probe called `session_windows(bad, "ETH")` unguarded; the fix now raises, aborting the script, so that one call is wrapped in `try/except` (a raise is recorded as BLOCKED). Result `BYPASSED: []`. N-2 closed: `SessionHaltInvalidError: SESSION_HALT_INVALID: session_date=2020-06-11 halt_end_ns=1591903800000000000 < rth_close=1591906500000000000`; inverted row → `SessionRowInvalidError: SESSION_ROW_INVALID: … close_ns=1631800800000000000 <= open_ns=1631826000000000000`. W-3 closed: the subset-declaration probe now yields `DatasetV2Error: REFERENCE_DIGEST_MISMATCH: computed 49272e8d… != declared 39fce523…`. |
| **A8** `a8_gap_precedence.py` (16 cases) | **BLOCKED** | PARTIAL / **BYPASSED → C-B**, W-2, N-3 | `BYPASSED: []`. C-B closed: `A8-ADJ1 strict + expiry=negative + a max_gap-exceeding gap straddling the horizon end` → `kernel=CENSORED/GAP oracle=CENSORED/GAP parity=True`; `A8-ADJ1'` (expiry=censor) likewise `CENSORED/GAP`. W-2 closed: `A8-ADJ6 … kernel=CENSORED/DATA_END oracle=CENSORED/DATA_END`. N-3 closed: `A8-ADJ4 the ENTRY bar itself is 500s after T` → `kernel=CENSORED/GAP oracle=CENSORED/GAP`. |
| **A9** `a9_a10_e2e.py` | **BLOCKED** | BLOCKED | `scan_study_python` unchanged; all nine controller stages without `--execute-authorized` → `blocker_code=EXECUTION_NOT_AUTHORIZED`, `actions=[]`, `lock_exists=False`; every direct leaf → `EXECUTION_NOT_AUTHORIZED: <stage> requires --execute-authorized`. Full run reached `run through=close: OK STUDY_CLOSED`. |
| **A10** `a10_deliverables.py` | **BLOCKED** | BLOCKED | `MISSING: []` — all 22 expanded deliverable paths present on disk after a real full golden run. |

**Separate W-4 verification (not possible from the golden fixture).** The golden study is
`features.host: synthetic`, so `_resolve_features` never reaches the `features/registry.py`
branch. Compiling the three real `features.host: features` v2 studies in memory (read-only, no
writes to `studies/`) confirms the conditional addition fires:
`v2_shape_c_barrier_race_fade → features/registry.py in closure: True (n=46)`, alongside
`features/trackers/{generic_arrival,generic_context,generic_rolling_productivity,generic_structural_geometry,host_bindings}.py`.

## New attacks against the fixes (5 executed)

Scripts: `rerun_f64009e6/n1_head_blob_authority.py`, `n2_post_freeze_substitution.py`,
`n3_horizon_shorter_than_max_gap.py`, `n4_reference_digest.py`, `n5_model_root_propagation.py`.

| ID | Attack | Result |
|---|---|---|
| **N1** | The C-A fix binds authority to the HEAD blob — attack the definition of HEAD. Forgery on an unchecked-out branch; **detached HEAD** parked on the forged commit; a **linked `git worktree`** of the same repo at the forged commit; forged commit as the tip of the checked-out branch; a study path that escapes and re-enters `repo_root`; `repo_root` = the parent of the real repo; a non-git directory. | **PARTIAL.** Blocked: unchecked-out branch (`HISTORICAL_AUTHORITY_UNTRACKED`), parent-dir `repo_root`, non-git directory. **Granted**: detached HEAD, linked worktree, and re-pointed branch — all three are the same primitive (*commit it, then check it out*). → **WARN-2**. The escape-and-re-enter path is normalised by `Path.resolve()` and grants only for the legitimate study, which is correct. |
| **N2** | W-1 residual, end to end: run the real golden lifecycle into a tmp `model_root`, `freeze`, then substitute a different LightGBM booster (refreshing `canonical.byte_sha256`, re-scoring the golden frame, refreshing `golden.expected_sha256`), then re-run the **governed** OOS-scoring stage. | **PARTIAL.** `N2-pre`: `model ac9c4cd3d257fa02 in tmp store: True; in REAL store: False` — **W-5 confirmed fixed**. `N2c`: `ModelStoreError: CANONICAL_SHA_MISMATCH: expected canonical_sha256='47a27aae…' but manifest records '1ee9da82…'` — the new `expect.canonical_sha256` works **when declared**. `N2a`: **BYPASSED** — `analyze()` completed on the substituted estimator (default `expect={"study_id": …}`), recording `model_authentication.canonical_sha256=1ee9da829e0ecd2c` while `train_experiment_freeze.model_canonical_sha256={'primary': '47a27aae…'}` still holds the pre-substitution value. Nothing compares the two. → **WARN-1**. |
| **N3** | The C-B fix measures the `strict` gap as `horizon_end - prev_ts > max_gap`. Attack that span: horizons at/below `max_gap`, with a tape that observes **nothing** inside the horizon (entry bar, then a 399 s hole). | **PARTIAL → WARN-3.** `N3a strict, horizon 10s <= max_gap 30s, no observation inside the horizon, expiry=negative` → `kernel=NEGATIVE/None oracle=NEGATIVE/None parity=True` (expected `CENSORED/GAP`); `N3a'` with `expiry=censor` → `CENSORED/TIMEOUT`; `N3d` (horizon 30 s) and `N3e` (31 s) likewise `NEGATIVE`. Controls hold: `N3c` (horizon 61 s > max_gap) → `CENSORED/GAP`; `N3f` dense tape → genuine `NEGATIVE`. `N3b` shows `first_bar_at_or_after` censors `GAP` on the *identical* tape. |
| **N4** | The W-3 fix now verifies the aggregate over the **full** catalog manifest, unconditionally — does it still validate the real committed specs, and can a manifest with extra/rewritten tables bind? | **BLOCKED (no regression).** `NQ_1S_V2 declared=0db1f14b… computed=0db1f14b… match=True`; `ES_1S_V2 declared=52df910a… computed=52df910a… match=True`; both load all six real reference tables. Phantom extra table → `REFERENCE_DIGEST_MISMATCH: computed 087925e8… != declared 0db1f14b…`; a *valid* tampered `sessions.parquet` with a refreshed manifest sha → `REFERENCE_DIGEST_MISMATCH: computed 82f6858a… != declared 0db1f14b…`. Residual: `N4e` — `compute_catalog_digest` is still `data/`-only → **NOTE-1**. |
| **N5** | Boundary of the W-5 `model_root` option: the out-of-process partition child, every model-store call site, and the operator CLI. | **PARTIAL (inert).** `N5b`: every `store_model`/`authenticate_model`/`read_manifest`/`score` call in `lifecycle_v2` forwards `opts.model_root`. `N5c`: `model-store names appearing in run_partition: []`. `N5a`: **BYPASSED** — the child builds `opts = V2Options(studies_root=…)` with no `--model-root` flag, so a partition child always resolves the real store; inert today because of N5c → **NOTE-3**. `N5e`: real store `before=476 after=476 added=[] removed=[]`. |

## Findings

### WARNING

**WARN-1 — W-1 residual: the governed OOS path still accepts a substituted estimator, and the new
freeze evidence is written but never checked.**
`expect.canonical_sha256` (`grammar/spec.py: ScoredModelExpectSpec`, enforced at
`model_store.authenticate_model`) is **optional**, and the single-model OOS path calls
`authenticate_model(models["model_id"], expect={"study_id": plan["study"]["id"]}, …)`
(`lifecycle_v2.py:816`) — no canonical binding. `freeze()` now records
`model_canonical_sha256` in `train_experiment_freeze.json` (`lifecycle_v2.py:768-781`), but
`grep -rn model_canonical_sha256` finds **only the writer**: no consumer anywhere re-compares it.
Executed: `analyze()` re-scored a substituted booster without error (N2a). Requires write access
to the model store, so it is not an authority or OOS-boundary break — but the detection is
manual-only. *Fix:* have `analyze()`/`_score_models` read `model_canonical_sha256` out of the
study's own TRAIN freeze and pass it as `expect.canonical_sha256`; then the evidence the fix
already writes actually binds.

**WARN-2 — "committed at HEAD" means *this checkout's* HEAD, and the granted evidence records no
commit identity.**
`policy.committed_blob` / `is_committed_identical` resolve `HEAD:<rel>` in whatever ref the
working copy currently points at. A forged study committed on a scratch branch and then reached by
`git checkout --detach <sha>`, by `git worktree add --detach <sha>`, or by re-pointing the checked
out branch, is **GRANTED** (N1b, N1c, N1d) — the forgery never has to exist on any reviewed or
pushed ref. The returned evidence dict is `{study_id, seal_sha256, seal_composite,
manifest_composite, git_tracked: True, markers}` — it does not record the HEAD commit sha, so a
downstream reviewer cannot tell which commit vouched. This is a genuine narrowing of C-A (index-
and worktree-only forgeries are now dead) but it stops at the boundary its error strings imply.
*Fix:* record `head_commit_sha` (and, where available, whether that commit is an ancestor of a
configured upstream ref) in the evidence dict, and surface it in the audit packet.

**WARN-3 — the C-B `strict` gap guard is vacuous when `max_gap_seconds >= horizon_seconds`, and
the two `horizon_end_rule`s then disagree on identical tapes.**
The fix measures the unobserved span as `horizon_end - prev_ts` (`host/outcomes.py`,
`target_replay_oracle.py`). When the horizon is no longer than the declared gap tolerance, that
span can never exceed `max_gap`, so a tape whose only observation inside the horizon is the entry
bar — followed by a 399 s hole — resolves through the expiry policy: `NEGATIVE` with
`expiry: negative`, `CENSORED/TIMEOUT` with `expiry: censor` (N3a, N3a', N3d, N3e). The effective
threshold is `horizon_seconds - (entry bar duration) <= max_gap_seconds`. This is defensible as
*"the in-horizon unobserved span is inside the declared tolerance"* — but the same tape under
`first_bar_at_or_after` censors `CENSORED/GAP` (N3b), so the label for an identical observation
history depends on a rule that is supposed to govern only the horizon *boundary*. No study in the
repository is affected today (`studies/deep_pullback_5s_reacceleration_model/study.yaml`:
`max_gap_seconds: 1` against `horizon_seconds: 300`). *Fix:* refuse (or at minimum warn) at
compile time when `max_gap_seconds >= horizon_seconds` for any barrier arm — a gap guard that
cannot bind is a parameterization error — and state the `strict` semantics in the outcome
contract alongside the N-3 entry-gap rule.

### NOTE

- **NOTE-1 (W-3 residual)** — `roots.compute_catalog_digest` still hashes only `<catalog>/data/**`
  (N4e), so `reference/` and `build_manifest.json` remain outside readiness R1's byte
  verification. The committed `DatasetSpec.reference_digest` is now a *hard* anchor over the whole
  manifest (N4b/N4d), so this is defense-in-depth only.
- **NOTE-2 (W-4 residual / pass-02 N-5)** — still imported during governed stages but unhashed:
  `research/analysis/{spec,errors,loader}.py`, `research_workflow/capabilities.py`,
  `features/engine.py`, `utils/runner/data.py` (a2b: `hashed=False composite_moves=False`).
  `seal.py`, `workspace.py`, `features/registry.py` and (on the frozen-external-score path)
  `research/schemas/study_spec.py` are now in. Inert for v2 `fit()` as pass 02 argued, but the
  category is not swept.
- **NOTE-3** — `V2Options.model_root` is not forwarded to the out-of-process partition child
  (`lifecycle_v2.main` builds `V2Options(studies_root=…)`, no `--model-root`; N5a). Inert today
  because `run_partition` touches no model-store API (N5c), but the isolation the option promises
  is not complete. `scripts/research.py` exposes no `--model-root` either, which is the intended
  default for production runs.
- **NOTE-4** — adding `seal.py`, `workspace.py` and `features/registry.py` to the closure moves the
  execution composite of all three closed v2 proof studies (`v2_shape_a_flip_180s
  7676acfb→9990135f`, `v2_shape_b_deep_pullback_5s 0db52eef→54f0905f`, `v2_shape_c_barrier_race_fade
  51bc1054→67cd233f`). They are terminal `STUDY_CLOSED` and their historical authority still
  authenticates (the seal is compared to its own frozen manifest, not to a recompile), so this is
  an expected consequence of any closure-module edit — recorded so it is not rediscovered as a
  defect later.

## What pass 02 flagged and is now genuinely closed

C-A (all four spoofing primitives, plus the three adjacent variants that produced it, plus the new
requirement that a `legacy_v1_train_freeze` study carry an AUTHENTICATED seal), C-B (both end
rules, both expiry policies, kernel and oracle in parity), W-2 (oracle `DATA_END`), W-3 (subset
declaration now binds; verified regression-free against both real catalogs), W-4 (`seal.py`,
`workspace.py` hashed; `features/registry.py` verified on a real features-host study), W-5
(`V2Options.model_root`, forwarded at every `lifecycle_v2` call site, asserted in the golden test),
N-1, N-2 (both `SESSION_ROW_INVALID` and `SESSION_HALT_INVALID`), N-3 (entry-gap censoring in
kernel and oracle), N-4.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR_WITH_WARNINGS", "audit_type": "adversarial", "auditor": "independent adversarial reviewer (pass 03)", "audited_head": "f64009e6", "critical": 0, "warning": 3, "note": 4, "attacks_executed": 15, "bypassed": ["A4b", "N1", "N2", "N3", "N4e", "N5a"]}
<!-- AUDIT_SUMMARY_V2_END -->
