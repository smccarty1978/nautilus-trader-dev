# Architecture Decision Memo: autonomous, causal, defensible NT research

**Date:** 2026-11-20. **Reviewer:** Claude (Opus 5.5), independent adjudication. **Mode:** read-only. Nothing in the repository was modified.

**State checked today**

- `main` is at `dcafca80`. The tree is clean.
- `chore/research_lanes` is at `7ff5fdb7` and is **not merged**.
- The broad CORE gate for research_lanes is **still running**: PID 18476, started 11:38. It writes `%TEMP%\rl\broad.json`, which is still empty. I did not touch it.

**Inputs**

- Antigravity: `…\brain\81e0c0d6…\independent_architecture_audit.md`. I read all of it. There is no second-pass report in that folder; only `scratch/` exists.
- **Codex: the full report was NOT provided to this session.** I worked only from the 10-point summary in the prompt. Where I adjudicate a Codex claim, I verified the summary's claim against the code, not Codex's own reasoning. If you want Codex's reasoning checked as well, send me the report.

**Evidence labels used throughout**

- **DEMONSTRATED**: I executed it.
- **STATIC**: certain from reading the code.
- **PLAUSIBLE**: likely but not verified.
- **UNVERIFIED** / **DISPROVED**: as stated.

---

## A. Executive verdict

**Keep the compiler, the NT host, the governed controller and the frame/explore path.** Add four small things to them:

1. **One study-local extension point.** The research_lanes `study_local:` observer *is* Codex's "binding overlay": it uses the same compiler slot, host `_load` and closure. It needs two read-only inputs: (a) upstream tracker outputs and (b) a host-injected session calendar.
2. **An `explore` tier, declared in `study.yaml` so that it is hashed.** In that tier the controller runs the *existing deterministic* causal and contract reviews in-process instead of halting for an LLM audit packet. It runs through `close` without `--execute-authorized`. OOS, `dev` years and execution claims are hard-refused.
3. **Plan-bound audit freshness.** This fixes a **demonstrated** defect: a plan-only semantic change re-seals on the old CLEAR audits.
4. **`close` emits `RESULT_CARD.md` plus one ledger entry, and refuses to close without them.** The same ledger records data exposure and variant history. This is what distinguishes exploration from confirmation.

**Things not to remove or replace now:**

- The supervisor. It is already de facto bypassed: its last run was 2026-09-10.
- The regression suite.
- `merge_tier.py`.

None of them sits on the critical path of a study that never merges. Quarantining the 63 failures saves **1.8%** of the broad run's time (§C).

**Direction:** Codex's "reuse and simplify" direction is correct. Antigravity is correct about result surfacing, the explore tier and session discipline. It is wrong about where the regression time goes, and premature on deleting things.

---

## B. Antigravity vs. Codex adjudication

| # | Topic | Antigravity | Codex | Repository evidence | Conclusion | Conf. |
|---|---|---|---|---|---|---|
| 1 | Novel study calculations | Extend `study_observers.py` (session + tracker inputs) | Study-scoped binding overlay on host bindings | On the branch, `compiler.py` resolves `tracker: study_local:<name>` into the **same** tracker-binding slot. `host/strategy.py::_load` resolves it and refuses other studies. The observer file enters `plan.closure.files`. Shared trackers already declare `INPUTS = {"bars":"stream","regime":"tracker",…}` (`features/trackers/host_bindings.py:163,327`). The observer forbids non-stream inputs (`study_observers.py:123`) | **Same mechanism.** Lift the stream-only restriction to allow declared tracker inputs, and add an injected calendar. No second system is needed | High |
| 2 | Supervisor | Remove it (except `audit_brief.py`) | Keep it but make it replaceable; it duplicates lifecycle logic | `~/.nt_research/supervisor/*` was last touched 2026-09-10. Its protections (run lock, writer lease, OOS latch, freshness) are enforced independently in `governed_controller_v2.py:180-243`, `workspace`, `oos_access.py` and `_fresh_stage`. Only worker/heavy slots and attempt counters are supervisor-only. `derive.py` re-derives lifecycle position from artifacts, which partly duplicates `_fresh_stage` (PLAUSIBLE duplication) | **Bypass it (option C). Decide on retirement after the pilot.** Deleting it now buys nothing for research. Its tests are the one real cost (§C-F3) | High |
| 3 | 63 baseline failures | Quarantine them; the fast suite drops to "<5 min" | Reuse assurance evidence by dependency | `test_delta_broad.json` for the volume-clock merge: 3,038 tests, 17,001 s. **The 63 failures take 309 s (1.8%).** The top 50 tests take 12,520 s (74%). `test_supervisor_blackbox.py` alone takes 3,854 s, `test_lifecycle_v2.py` 1,743 s, and `test_redteam_packet_f.py` 1,573 s. All 63 are tagged NEW only because of `BASELINE_COMMIT_MISMATCH,BASELINE_ENVIRONMENT_MISMATCH` | Antigravity's time claim is **DISPROVED**. Obsolescence of the 63 is **UNVERIFIED**: some look like V1 artifacts (`test_stage3_integration` ×9, `test_nt_runner_backtest` ×6), but others (`test_population_qualification_strictness` ×5, `test_ordered_barrier_entry_reference` ×3) could be real V2 defects. Codex's direction is right, but the work is off the research path | High |
| 4 | `merge_tier.py` | Drop it | Dependency-aware reuse | 361 LOC. Building the coverage map takes ~325 s. It selected 76 of ~180 test files for an additive tracker. It is already built and is inside the branch's running gate | **Keep it as-is.** Stripping it now would force another ~5 h broad gate. It does not affect research | Med |
| 5 | Session per phase | Replace with machine checkpoints | Fresh sessions are not safeguards | `WORKFLOW.md` §N is a prompt rule. No code requires a new session. The real boundaries are hash bindings (`plan_sha256`, seal, frame `candidates_sha256`, OOS latch) | **Agree with both.** Make §N optional for the explore tier | High |
| 6 | Population freeze | New `population_freeze.json` | — | Already covered. The seal binds `plan_sha256` *before collection*: the candidate rule is frozen before any outcome exists. The frame record binds `candidates_sha256` and `observations_sha256`, and `explore` verifies them before and after (`explore.py:162-181`) | A new artifact is **redundant**. The missing piece is the *attempt history* (ledger), not the freeze | High |
| 7 | Audit freshness | — | Audits are composite-keyed; a plan change keeps a stale CLEAR | §C-D1 | **CONFIRMED DEFECT** (demonstrated) | High |
| 8 | Cross-study exposure | Ledger makes the count visible to a human | The OOS latch does not cover related studies | `oos_access.py:1-19`: the latch lives in each study's `artifacts/`, and "an amended evaluation is a new study" | **Confirmed (STATIC).** A new study ID resets every exposure control | High |
| 9 | Explore output identity | — | Runs can overwrite each other | `explore.py:169`: the output path is `frame_id/spec_sha[:12]`. `explore.json` records no analysis-code identity. *Different* specs never collide; the *same* spec re-run after an analysis-harness change silently overwrites | **Partially confirmed (STATIC).** Low severity, and cheap to fix inside the ledger work | High |
| 10 | Separate scientific, integration and execution validation | Yes (EXPLORE / CONFIRM / EXECUTE) | Yes | The branch already has `research_lanes.validate_execution_claim` (refuses precomputed schedules) | **Agree.** Keep three claim levels and enforce them in code (§E) | High |

---

## C. Verified defects and bottlenecks

### D1. Stale audits survive a plan-only semantic change: **CONFIRMED DEFECT (DEMONSTRATED)**

**Trace:**

1. **Packets carry the plan.** Both packets carry `plan_sha256` plus population, outcome semantics, chronology and model (`research_workflow/audit_packets_v2.py:144`, `:174`).
2. **The composite is code-only.** It hashes the closure files (`research_workflow/grammar/compiler.py:2058-2107`). `study.yaml` is not part of it.
3. **The issued audit status records only the composite.** It records `audited_execution_composite_sha256` and nothing else (`scripts/run_preexec_audits.py`, `issue_causal_audit_status_from_report` ~L1193 and `issue_contract_audit_status_from_report` ~L1264). The packet's `plan_sha256` and `packet_sha256` are dropped.
4. **Freshness ignores the plan.** `_audit_current` checks verdict + composite only (`research_workflow/governed_controller_v2.py:90-94`). The comment at `:116-117` states the design: "tests and the causal audit stay composite-keyed". The contract audit is also composite-keyed (`:139-141`).
5. **Sealing ignores the plan.** `seal()` checks `verdict == CLEAR and audited_execution_composite_sha256 == frozen` only (`research_workflow/lifecycle_v2.py:857`). It then writes a seal binding the **new** `plan_sha256` (`:860`).
6. **The repository's own test asserts this behavior.** After an `outcome.session_end` change, `test_a3_plan_only_change_stales_every_plan_bound_gate_and_nothing_closure_bound` (`research_workflow/tests/test_bucketing_and_gate.py:33-63`) asserts `causal_audit: True, contract_audit: True`. I ran it: it passes.

**Reproducer:** `scratchpad/repro_audit_freshness.py` (temp directory only; it writes nothing in the repo).

- It compiles `fixtures/parity/shape_b` as plan A and plan B, where B differs only in `session_end`. The composites are equal and the plan hashes differ.
- It writes CLEAR audits made against A, then calls the real `V2Lifecycle.seal()` on plan B.
- Result: **`seal status: PASS | seal binds plan B: True`**, with both audits' report hashes carried over.

**Why it matters:** the contract audit vouches for outcome semantics, year roles and deliverables. All of these are plan-level. A changed censoring rule, population qualifier or chronology inherits the earlier approval.

**Smallest fix:**

- Record `audited_plan_sha256` (taken from the packet) in both issued statuses.
- Require it to equal the current `plan_sha256` in `_audit_current` and in `seal()`.
- Statuses without the field are treated as stale (fail-closed).

**Regression test:**

- Invert the two `True`s in `test_a3` to `False`.
- Add a seal-level test (the reproducer above) that expects `AUDIT_NOT_CLEAR_OR_STALE`.

**Consequence:** every plan edit now forces a re-audit. That is affordable only if routine audits are deterministic, which is change F2.

### D2. Cross-study exposure is unrecorded: STATIC

The OOS latch is per-study (`research_workflow/oos_access.py:1-19`). `chronology.prohibited` is per-study as well. Nothing records which intervals have already been inspected, by which family, or with how many variants.

### D3. Explore runs carry no code identity: STATIC

Explore runs have no code identity, and a re-run with the same spec overwrites the previous output (`research_workflow/explore.py:169,183-195`).

### D4. The V2 controller halts at every audit stage for an external auditor: STATIC (main bottleneck)

- `governed_controller.py:371-378` emits a packet and returns, so a session or human must supply the audit.
- Deterministic reviewers already exist: `research_workflow/causal_audit.py:123 run_causal_review` and `contract_audit.py:118 run_contract_review`. Only the V1 `workflow_engine.py:49-51` calls them.
- Whether they handle a V2 compiled plan correctly is **UNVERIFIED**. A targeted test is the first task in F2.

### D5. Post-seal stages require `--execute-authorized`: STATIC

`governed_controller_v2.py:262-268`. This is a correct gate for confirmatory and OOS work, but routine friction for exploration on authorized TRAIN-role years.

### D6. Observers lack calendar and tracker inputs: STATIC

Branch limitation 3 is real. Trackers load the calendar from hash-verified reference tables (`features/trackers/volume_clock_developing.py:109-120`). An observer can do neither, so realistic intraday ideas still escalate to a PLATFORM_CHANGE.

### Other findings

- **F3. Broad-suite time is concentrated in passing tests.** 74% of it is in 50 tests, and 23% is in the supervisor black-box tests. Fixing this is optional and is not on the research path.
- **Disproved:**
  - "Quarantine → <5 min suite."
  - "A population freeze artifact is missing" (it is functionally present; see B-6).
- **Unverified (reported by Antigravity, not re-measured by me):**
  - Rehearsal 17.1 min.
  - Phase F compute 5.8 min.
  - "15 consecutive `research/*` studies."
  - Owner wait time 36%.

These are consistent with the memory index but were not re-measured.

---

## D. Minimal target architecture

```
hypothesis (natural language)
  └─ study new <id>  (worktree; study.yaml with  tier: explore,  family: <fam>,  chronology.train = inspected years)
      └─ compile  ── study_local observers bound into the tracker slot (+ declared tracker inputs, injected calendar)
      │             causality harness at compile time (determinism, prefix invariance, 3-cut perturbation, state bound)
      └─ prepare / readiness / preflight     (unchanged; dataset digest, forbidden-year/byte-scope guard)
      └─ causal_audit / contract_audit       explore tier: deterministic reviewers in-process, bound to plan_sha256
      └─ seal                                binds plan_sha256 ⇒ candidate + outcome definitions frozen BEFORE any row exists
      └─ smoke (bounded real-data window)    + study's own targeted test(s) of the observer on fixtures
      └─ collection → reconcile → merge      NT HostCore / StreamMux, single event loop, ts_init ordering
      └─ analyze  (research/analysis harness; session-block bootstrap, Holm/BH, EXPLORATORY watermark)
      └─ close    → RESULT_CARD.md (committed on the study branch) + ledger entry (machine-local, write-once)
                    close refuses without both; ledger stamps claim level from exposure history
```

**What stays, unchanged:**

- the compiler
- `HostCore` / host bindings
- the governed controller and its stage freshness
- `lifecycle_v2`
- the OOS latch
- frame store / explore (still the cheapest re-analysis path)
- `forward_outcomes/guard.py`
- `research/analysis`
- `study_closure`
- the writer lease and run lock

**What is bypassed:** the supervisor, the LLM audit packets (explore tier only), `--execute-authorized` (explore tier only), merging to main, the broad regression suite, and capability promotion.

**What is not built:** a new runner, a new supervisor, a new observer system, a dashboard, a population-freeze artifact, or an OOS v2.

---

## E. Scientific safeguards (machine-enforced, not bypassable by tier)

| # | Property | Enforcement (existing / new) | How it is validated without a human |
|---|---|---|---|
| S1 | One causal event loop: completed bars only, context strictly before T | Existing: `HostCore`, `CausalOrderViolation`, availability table in plan | Compile-time plan + smoke chronology receipt |
| S2 | Study-local code cannot see the future, other studies, files or catalogs | Existing (branch): AST allow-list, study-bound import, harness. New: tracker inputs/calendar are injected read-only; the harness runs the real upstream trackers on the tape | Harness verdict in `binding_proof`; failure = compile gap |
| S3 | Definitions frozen before outcomes | Existing: seal binds `plan_sha256`; partitions are valid only for the sealed plan (`lifecycle_v2.py:1076-1081`). **New: audits plan-bound (D1)** | Freshness recomputation on every controller run |
| S4 | No silent regeneration after inspection | Existing: frame hashes, OOS completion pin. New: ledger entries are write-once (O_EXCL); a changed plan is a new `run_id`, never an overwrite | Ledger append at `close`/`explore`; a duplicate `run_id` is refused |
| S5 | Forbidden data inaccessible | Existing: `prohibited` years, byte-scope receipt, `assert_oos_open`. New: explore tier refuses `chronology.dev`/OOS outright | Typed refusal |
| S6 | Claim level cannot exceed exposure | New: ledger computes the claim. `CONFIRMATORY` only if the windows are inside the researcher-declared **reserved** set *and* have no prior ledger exposure *and* the plan was frozen (sealed) before first access. Otherwise `HISTORICAL_REPLICATION` (prior-exposed, pre-registered config), `ROBUSTNESS` (other years, same frozen config), or `EXPLORATORY` | Computed at `close`; not settable by the agent |
| S7 | Analysis revisions recorded | New: every `analyze`/`explore` run appends (spec sha, code composite, result sha) to the ledger. The card shows "variant k of n in family F" | Mechanical |
| S8 | Production claims need production execution | Existing (branch): `validate_execution_claim`. Explore and confirm results are labelled non-executable | Typed refusal |
| S9 | Compute budget | New, small: `budget.max_partitions`/`max_wall_s` in `study.yaml`, checked before each partition launch | Controller refusal |

**What not to spend effort on:** per-phase human approval, fresh sessions, the LLM audit on null results, and broad regressions.

**When an LLM or human audit should fire:** only on escalation (a positive exploratory result proposed for confirmation), before opening reserved data, or for a platform merge.

---

## F. Implementation plan (estimates are estimates)

| Step | Change | Files | Depends on | Scientific risk | Targeted tests | Effort (est.) | Rollback |
|---|---|---|---|---|---|---|---|
| 0 | Let the running broad gate finish. Classify it against the 63 known node ids. If 0 attributable, merge research_lanes **as-is** (no stripping) | — | your merge approval | none new | the running gate | 30 min after the gate | `git revert -m1` |
| 1 | Plan-bound audit freshness (D1) | `scripts/run_preexec_audits.py`, `governed_controller_v2.py::_audit_current`, `lifecycle_v2.py::seal` | 0 (same closure files; avoids two re-freezes) | Fail-closed; any study with a pre-fix audit must re-audit | invert `test_a3` (`test_bucketing_and_gate.py:61`); new seal test from the reproducer; `test_audit_report_ingestion.py`, `test_audit_seal_guard.py` | 0.5 day | revert one commit |
| 2 | `tier: explore` in `study.yaml` (hashed): deterministic audits in-process; post-seal stages through `close` without `--execute-authorized`; refuse `dev`/OOS/execution claims | `governed_controller(_v2).py`, `grammar/spec.py` (field), `causal_audit.py`/`contract_audit.py` (V2 plan compatibility if the first test shows gaps) | 1 | An agent could mark a confirmatory study as explore. Mitigated: explore can never produce a claim above EXPLORATORY/HISTORICAL (S6) | **first:** deterministic reviewers on a compiled V2 fixture; tier refuses dev years; tier runs compile→close on the shape_b fixture with zero packets | 1–2 days | the field is opt-in; delete it to revert |
| 3 | Observer inputs: declared `tracker` inputs plus an injected read-only calendar (from `plan.session.reference_digest`) | `study_observers.py`, `compiler.py` (lift the stream-only check, reuse the existing tracker-input wiring), harness composes real upstream trackers | merged 0 | Upstream mutation; mitigated by passing frozen snapshots, and the perturbation harness covers the composed chain | leaky consumer of a tracker refused; calendar holiday-eve fixture; prefix invariance through the composed chain | 1–2 days | the observer still works without inputs |
| 4 | Result card + ledger, emitted by `close` and `explore run`; `research.py results list [--unread]`, also printed by `ws whoami` | `lifecycle_v2.py::close`, `explore.py` (add code composite to the record and the run id), new `research_workflow/ledger.py` (~150 LOC) | 2 | Card prose is agent-written. Mitigated: numbers are filled from analysis JSON; the prose fields are hypothesis, limitations and decision | close refuses without a card; ledger write-once; claim-level computation table test; same-spec re-run gets a new run id | 1–2 days | additive; remove the hook |
| 5 | Docs: WORKFLOW §N phase-per-session not required for the explore tier; §Q points to tiers | `WORKFLOW.md` | 2–4 | none | docs tests | 1 h | revert |
| 6 | Pilot (§G) | one study worktree | 1–4 | — | — | 0.5 day | discard the worktree |
| later | Optional: supervisor black-box tests behind an opt-in marker (−64 min per broad run); dependency-keyed reuse of test evidence; per-node review of the 63 | tests config | none | hiding a real regression | — | — | — |

**Closure impact:** steps 1–3 edit closure files. Before landing them, run `scripts/resolve_execution_manifest.py --study <each in-flight sealed study>`. Land 1–3 together on one chore branch, so in-flight studies re-freeze once, not three times.

**Merge gate:** under the current §N.3 that chore needs **one** broad gate (~5 h, unattended). This is the last broad gate on the research critical path. After it, studies never merge.

**Total estimated effort:** about 4–7 agent-days of implementation, plus one unattended broad gate.

---

## G. Pilot design

**Study:** `pilot_explore_tier`.

- Family `pilot`, `tier: explore`.
- Data: NQ 1s v.0, one already-inspected year (2024) as TRAIN-role.
- Smoke: one week.
- It is labelled EXPLORATORY by construction, so no assumption is made that any period is untouched.

**Novel calculation:** `close_location_streak`.

- It counts consecutive completed 1m bars whose close sits in the top or bottom 25% of the bar range.
- It is normalised by an existing ATR tracker output (a *tracker input*) and resets at session open (the *injected calendar*).
- Candidate event: streak ≥ k at bar close, RTH only.
- Outcome: existing ordered-barrier kernel, ±1 ATR, 30 min horizon, session-end censoring.

**Analysis and controls:**

- Hit-rate and expectancy versus a driftless baseline and a matched time-of-day placebo.
- Session-block bootstrap; Holm across 2 values of k.
- Expected result: likely null. A valid negative is a success.

**Deliberate failure paths (each must stop with a typed code; none may stop with a prompt):**

1. A copy of the observer that peeks at the next bar → compile-time harness gap.
2. After the first `analyze`, edit `outcome.session_end` → the audits become stale and re-run, and the ledger shows variant 2 of 2 (D1 regression).
3. Add `chronology.dev: [2026]` → explore-tier refusal.
4. Request `claim: confirmatory` → the ledger downgrades it to EXPLORATORY.

**Reconciliation:**

- An independent brute-force pandas reference of the streak and population computed from the frame (in the study's test).
- Pass criterion: exact row-set and value parity on the smoke week.
- Second check: re-run `analyze` and get an identical result sha.

**Success criteria:**

- All 13 items from the prompt's pilot list.
- Zero human interventions between `study new` and `close`.
- Zero merges.
- Zero broad runs.
- The RESULT_CARD exists and the ledger entry is present.

**Metrics to record** (wall clock from the ledger timestamps, agent turns/tokens from the CLI summary):

- time to first observation (smoke pass)
- time to first interpretable result (first `analyze`)
- time to close
- replays run
- human interventions
- failure-path stops

**About a 45-minute target:** it is an **estimate**, not a measurement. It is based on Antigravity's reported compute figures (Phase F 5.8 min, rehearsal 17.1 min), which I did not re-measure. The pilot produces the measurement.

---

## H. Decisions needed from you

1. **Merge research_lanes** once the running broad gate shows 0 attributable failures. This was already pending, and the merge is not pre-authorized.
2. **Approve the audit-binding policy change.** Plan edits will re-trigger audits, and routine audits become deterministic, with LLM or human audit reserved for escalation, reserved-data access and platform merges. This changes WORKFLOW policy and is your call.
3. **Declare the reserved-data set for confirmation.** Prior research has examined parts of 2026, so you must name the windows that count as genuinely reserved (for example "NQ from date X onward, never opened"). That is the only definition that can make S6 meaningful.
4. **Ledger location.** The ledger is machine-local under `~/.nt_research/` (like frames and leases) and is not in git. Decide whether you want it mirrored or backed up.

Everything else in this plan is ordinary engineering.

---

## I. What not to build

- A new or second supervisor, scheduler, or "orchestrator" agent loop.
- A parallel observer, tracker or binding registry. There is exactly one `study_local:` slot.
- A `population_freeze.json` beside the seal and frame hashes.
- A dashboard. `results list` plus RESULT_CARD.md is enough.
- An OOS v2. Instead, extend the claim computation through the ledger.
- Making suite cleanup (quarantine, baseline refresh, supervisor-test marker) a prerequisite for research.
- Stripping `merge_tier.py` out of a branch that is mid-gate.
- Using the telemetry pipeline Antigravity proposes beyond ledger timestamps.
- A per-phase-session rule for the explore tier, or LLM audits of null exploratory results.
- Any wrapper around the controller to retry or babysit it.
