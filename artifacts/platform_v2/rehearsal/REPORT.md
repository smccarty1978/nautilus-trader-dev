# THE REHEARSAL — one full-scale supervised study, one feature definition added mid-study

    packet:   THE REHEARSAL (2026-09-09). RECORD. DO NOT FIX.
    study:    rehearsal_checkpoint_norm (disposable; deleted after this report), NQ_1S_V2_GLOBEX,
              TRAIN 2023 (full year) / OOS 2024 (full year), single lightgbm fit, tail_lift on the
              study's own scores with TRAIN-frozen thresholds
    platform: main 8bf26857, clean before and after; nothing merged to main by this packet
    driver:   `supervise start --provider claude --execute-authorized`, human-attended owner
    evidence: evidence/ (study artifacts, controller receipts, audit reports, supervisor events,
              every worker result card and report, the question file)

## 0. The four answers first

1. **The mid-study feature addition did not complete, and it cannot complete on this platform.** A
   pure catalogue definition (the cleanest possible additive case: the value was already emitted by
   the structural adapter) never reaches the compiler, because the compiler binds feature identity
   through the feature authority bundle, which only a sealed study can extend. Closed loop. This is
   the packet's §7 escalation: the registration boundary holds for the resolver and does not hold for
   the compile path.
2. **Under the mechanical rule it is not ADDITIVE_CAPABILITY.** CORE_SURFACE under the rule as written;
   still CORE_SURFACE with the three known path updates applied (details §2).
3. **A retry re-scoped the science.** The second implementer turned the requested feature into a
   parameter of an existing verified feature by editing the resolver. The merge gate stopped it as a
   file-surface violation. Nothing noticed it as a substitution. On a real study this silently alters
   the question. This is a fidelity finding, above everything else in §3.
4. **Everything else ran.** Once the owner withdrew the feature, the study went seal → two audits →
   smoke → two full years of collection → fit → freeze → OOS → analysis → STUDY_CLOSED with 23.5 min of
   machine time and under $8 of AI. It closed `REHEARSAL_COMPLETE` on the first analysis decision.

**One sentence:** I would run a real study on this platform tomorrow if every primitive it needs is
already registered and I sit within reach of the decision cards; I would not run one that needs a new
feature definition, and I would not leave one unattended past its first audit block.

## 1. Cycle measurements

Question to closure: **12:16:24Z → 14:37:28Z = 2 h 21 min.** The Supervisor V1 reference run
(supv1_shape_a_flip_180s_r2, no capability gap, no intervention) was 73.5 min, $8.28, 4 workers.

| split | minutes | share | detail |
|---|---:|---:|---|
| AI workers (7 sessions) | 63.8 | 45 % | design 7.1 · capability 16.1 + 14.1 · causal audit 5.1 · contract audit 5.1 · repair 9.1 · analysis 7.1 |
| replay / controller jobs (no AI) | 23.5 | 17 % | seal 3.0 + 1.0 + 0.3 · heavy job 17.1 (smoke 0.8, TRAIN 2023 collection 7.9, reconcile+merge+fit+freeze 0.2, OOS 2024 collection+score 7.8, analyze 0.1) · close 2.0 |
| waiting on the owner | 50.4 | 36 % | escalation 1 raised 12:55 answered 13:31 (36.5) · escalation 2 raised 13:56 answered 14:10 (13.9, ~8 of it the owner's manual re-audit path) |
| supervisor overhead | ~3 | 2 % | ticks, claims, briefs, lease hand-offs |

| cost | value |
|---|---:|
| workers launched / turns / cost | 7 / 301 / **$27.33** |
| of which the two FAILED capability workers | 2 / 155 / **$15.05** |
| of which the audit-block recovery (contract audit + repair) | 2 / 63 / $5.64 |
| of which the study that closed (design, causal audit, analysis) | 3 / 83 / $6.64 |
| owner-side contract pass 02 (this session's agent, 59 s) | not priced by the supervisor |
| typed decision cards | 2 (both `SUPERVISOR_ESCALATION_REQUIRED`) |
| owner actions | 3: withdraw the feature by hand; run contract pass 02 by hand; answer the two cards |

Gate machinery is cheap: seal-through-tests 3 min, each auditor ≈ 5 min and ≈ $1.6, close 2 min. The
money went to agents that could not succeed.

Research plane (not science, one study, no interval): TRAIN 877 040 rows, OOS 867 422 scored /
859 153 evaluable (8 269 non-binary excluded, 0.95 %), 6 680 OOS regime episodes; OOS tail lift over
base rate 0.327 at the TRAIN-frozen 0.9 / 0.95 / 0.975 quantiles: **1.53 / 1.70 / 1.98**, tail shares
9.75 / 4.73 / 2.28 %. Model golden replay max_abs_diff 0.0. Reconcile passed with 0 findings.

## 2. The feature addition — the headline

Design: `structural_max_expansion_checkpoint_atr` (max structural expansion normalized by the
decision-epoch ATR). The structural adapter already emits it (`research_workflow/provider_host.py`
`_SNAPSHOT_KEYS`), the tracker already computes it; only the canonical definition was missing. Compile:
`MISSING_CAPABILITY UNKNOWN_CANONICAL_FEATURE` plus a cascaded `UNSUPPORTED_COMPOSITION` (F2 below).

| packet question | answer | evidence |
|---|---|---|
| Classified ADDITIVE_CAPABILITY under the mechanical rule? | **No.** As written (`chore/tiered_gates` `tier_replay.py`): CORE_SURFACE, `features/definitions/canonical.py` "not on any allowlist" (the classifier predates the boundary; parked finding 2 of the boundaries report). With the three path updates applied to a scratch copy: `canonical.py` → MODIFIED_CAPABILITY ("existing statements changed": the catalogue is a `for _name in (...)` tuple, so an added name is a changed statement, never an insertion-only registration), regenerated `features/tests/golden/feature_resolution.json` → CORE_SURFACE (no allowlist covers a golden fixture) ⇒ CORE_SURFACE either way. Derived surface 11 files / 101 tests (the boundaries report measured 10 / 121 for a synthetic `_add` in `physical_catalogue.py`). | `evidence/supervisor/002_*.report.md`; classifier runs in this session |
| Required a host or lifecycle edit? | **Yes, in effect.** The definition alone does not change compile. `compiler.py:491` resolves identity via `_canonical_bundle("active")` (`features/authority/active.json` → `candidate/`, last materialized 2026-08-28). The bundle is written only by `scripts/materialize_feature_candidate.py`, whose `verified` sources are the legacy-alias parity inventory (closed for a new feature) or a scoped promotion record that needs an authorizing study's frozen manifest and pre-exec seal. The study cannot seal because it cannot compile. Re-materializing is not idempotent (53 `provider_sha256` drifts, an unrelated definition, 143 → 145). The first implementer stopped here, correctly, with `FEATURE_AUTHORITY_PROMOTION_PATH_ABSENT` and three routes, all platform work. | `evidence/supervisor/002_*.report.md` |
| Gate cost in wall time | Merge gate itself: seconds (diff surface, `cap generate --check`, worker-reported `new_failures`). The worker's targeted `test_delta features/tests` (77 tests): minutes. The 59-minute additive tier was never reached. The gate would have been red regardless of the diff: targeted `test_delta` at merge-base 8bf26857 reports 2 NEW with `BASELINE_COMMIT_MISMATCH` (baseline pinned at ee16002e), both reproducing on clean main. | `evidence/supervisor/003_*.result.json`, USER_DECISION_01 |
| Friction of gate-card classification | The four known-but-NEW broad entries did not appear (broad never ran). The two baseline-mismatch NEWs cost the worker a reproduce-on-clean-HEAD proof inside its 88 turns and still counted as `new_failures=2`, so the mechanical gate cannot pass on this platform commit at all until the baseline is re-recorded. | same |

What the second attempt did instead (`037e0645`): reverted the definition, made the ATR denominator a
`normalizer` parameter of `structural_max_expansion_atr` (already verified in the bundle), and edited
`features/registry.py` (`generate_physical_alias`) to render it. Classifier: CORE_SURFACE, 140 files /
1 922 tests. Merge gate RED: three files outside the claimed surface (the claim listed the pre-boundary
files: library, library_mtf, registry, host_bindings, compiler, predicates, predicate_eval, provider_host;
none is where a definition goes) and `new_failures=2`. **The gate catches surface violations** — the
open question from the previous session is answered.

## 3. Every friction point, recurrence and cost

Fidelity first, then platform, then owner.

| id | what stopped / slowed | kind | cost | recurs? |
|---|---|---|---|---|
| **X1** | **Retry re-scoped the request.** Attempt 2 substituted a parameter on an existing feature for the requested new feature, to fit the platform. Blocked only because the file layout put it outside the claimed surface; no check compares what was asked with what was built. R2 (a study stays what it was proposed as) has a path around it through the capability flow. | fidelity | $6.89, 14 min; on a real study, a silently altered question | every retry of a capability that cannot be built as asked |
| **X2** | **Feature definitions are not compile-visible without a sealed study.** Authority bundle loop (§2). | platform, structural | $15.05, 30 min of workers, 36 min of owner waiting, the feature | every genuinely new feature |
| F1 | Handoff `_SUGGESTED_FILES` for `features.` gaps predates the registration boundary; the chore write surface omits `features/definitions/`. Every correct definition diff is a surface violation. | stale assumption across subsystems | one attempt burned | every feature gap |
| F2 | One unregistered feature produces two gap kinds: `UNSUPPORTED_COMPOSITION` on `features.structural_snapshot_ready` cascades because the compiler skips the feature host after a feature fails. Inflates `gap_kinds` and the claimed surface (adds compiler/predicates/predicate_eval). Both the design worker and the implementer spent turns proving it downstream. | compiler diagnostics | ~2 worker-minutes per worker that meets it | every feature gap in a spec with `features.*` predicates |
| F3 | No re-audit route after a study-side repair: `supervisor/derive.py:203-223` sends any BLOCKED audit pinned to an unchanged composite to `_launch_repair` only; the controller keys audit currency on the composite (`governed_controller.py:372-376`), so the repair can never clear it. Loops to MAX_ATTEMPTS, escalates. Workaround: the manual §D path (owner runs the auditor gate, `research audit ingest`, `--through seal`, `decide {"retry": true}`, `resume`). | supervisor, structural | $4.12 repair worker + 14 min owner | every study-side contract or causal BLOCK under supervision |
| F4 | No governed way to abandon a capability: `decide` offers retry or terminal. The owner had to out-edit the handoff (compile newer than handoff) and leave `active_capability`, the chore claim and the chore worktree dangling. | supervisor | ~5 min, manual cleanup | every abandoned capability |
| F5 | The supervisor relaunches the SAME task after a BLOCKED card whose `next_state` names an owner decision (`OWNER_DECISION_REQUIRED`, and later the exact re-audit needed). Worker-declared next actions are not typed codes, so a second paid attempt runs before escalation. | supervisor | $6.89 (attempt 2) | every non-deterministic block |
| F6 | Targeted `test_delta` at any HEAD ≠ baseline commit reports pre-existing failures as NEW (`BASELINE_COMMIT_MISMATCH`); the merge gate reads `new_failures` literally. No additive merge can be green on this platform commit. | test baseline | proof-on-clean-HEAD turns in every worker; gate red | every targeted run until a re-record |
| F7 | `cap generate --check` fails `CAPABILITY_REGISTRY_STALE` on first run in a fresh worktree; `cap generate` then changes nothing. | tooling false negative | 1 turn | every fresh worktree |
| F8 | Owner intervention edited only `study.yaml` (lowest precedence) while `research_decision.yaml`/`SPEC.md` kept the contrast. Contract audit CRITICAL-1, WARNING-2 (vocabulary could not detect it), WARNING-3 (selection protocol with no candidate set resolves to nulls — latent in the gate study spec too). The gate worked; the owner was wrong. | owner | $5.64, 14 min + escalation | whenever an owner edits one document of three |
| F9 | After a repair the controller's audit packet on disk is stale (still the pre-repair plan) because the controller stops at the blocked stage before regenerating it. An auditor trusting the packet audits the wrong contract. | controller | caught by pass 02 reading the documents | every repaired study |
| F10 | `research audit ingest` writes `contract_status.json` but does not file the pass report into `audit/` (the supervisor does the copy itself). | CLI | 1 min | every manual ingest |
| F11 | The supervisor never commits `studies/<id>/audit/` or the closure/freeze artifacts; both were untracked at STUDY_CLOSED. The merged study would lack its own closure and audits. | supervisor | commit by hand | every supervised study |
| F12 | A single fixed-parameter fit records no held-out metric: freeze `metrics` all null, analyze payload carries only the declared op. The question asked for OOS ROC AUC; nothing produced it. | lifecycle | none here | every study without a validation block |
| F13 | `supervise list` reports `loop_alive: true` on a dead loop when the pid was reused (OpenConsole.exe); three closed studies report `CLOSURE_INVALID` (closure validity is R3; whether Wave 1 changed what closure binds or something else did is not investigated here). | supervisor status | cosmetic | every listing |
| F14 | `state.json` `question_path` points at the launching session's scratchpad; the design worker is relaunched after a capability merge and re-reads it. Durable copy made by hand. | supervisor | 1 min | every `supervise start` from a temp path |
| F15 | Owner discovery before launch: ~35 min reading WORKFLOW/AGENTS/reports/supervisor code to design a rehearsal that could not be composed from the docs alone (which feature is emitted-but-undeclared, how the merge gate trusts `--tests-json`). | onboarding | 35 min | first study per owner |

Deferred items touched by this session, evidence only: the additive tier (never reached; F6 makes it
moot on this commit), the single-signature baseline refresh (F6), the golden fixture's OOS year (not
touched), `test_delta` at the baseline's own commit (not touched).

## 4. What ran cleanly, stated plainly

From the moment the withdrawn-feature spec compiled: seal and both audit packets in 3 min; causal audit
CLEAR in 5 min; the two-year replay, fit, freeze, authorized OOS and declared analysis in 17 min with no
AI alive; the analysis worker decided `REHEARSAL_COMPLETE` from the declared vocabulary with the feature
surface verified against four artifacts; close in 2 min; every artifact bound to composite `73db2ed0…`
and plan `9eb2ff0d…`. Main was never touched. That is the platform working as designed, and it is the
part a real study on registered primitives would use.

## 5. Cleanup performed

Study worktree, branch `study/rehearsal_checkpoint_norm`, the capability chore worktree and branch
`chore/rehearsal_checkpoint_norm-missing_capability` deleted after safety inspection; their leases and
claims released; the `collection_latency` worktree untouched. Supervisor state for the study left under
`~/.nt_research/supervisor/rehearsal_checkpoint_norm/` (machine-local evidence, copied to `evidence/`).
