# RESEARCH SUPERVISOR V1 — implementation packet

> Task packet for a fresh implementing session (any provider: Claude, Codex, Gemini, Antigravity).
> Written 2026-09-05 from the measured session-cost evidence and the `WORKFLOW.md` §N mechanisms.
> Sections 0-11 are the full specification; section 10 is the discipline the implementing session
> itself must follow. This file is a packet, not platform documentation: when V1 is merged, the
> authoritative description moves to `WORKFLOW.md` §O and this file is marked `[HISTORICAL]`.

PLATFORM V2 — AUTONOMOUS MULTI-SESSION RESEARCH SUPERVISOR (V1) — IMPLEMENTATION PACKET

You are the implementer of one bounded platform capability: a thin, deterministic RESEARCH SUPERVISOR
that sits above the existing governed controller and turns one research prompt into a chain of short,
disposable AI worker sessions plus detached deterministic jobs.

Read first, in this order (do not re-derive them, they are current):
    WORKFLOW.md §N (session budget, phases, STOP-AT-CAPABILITY-GAP, handoffs, test_delta, chore ownership)
    WORKFLOW.md §M (concurrent studies, writer leases), §D (normal study), §A (lifecycle one-pager)
    research_workflow/governed_controller_v2.py      the controller: stage order, status cards, run lock, writer gate
    research_workflow/handoff.py                     CAPABILITY_GAP_HANDOFF + SESSION_HANDOFF cards (reuse, extend)
    research_workflow/workspace.py                   writer identity (v3 leases), ws claim, chore claims, require_agent
    scripts/research.py                              operator CLI (study new/compile/status/handoff/run, ws *, cap *)
    scripts/test_delta.py + config/test_failure_baseline.json
    docs/AI_AGENTS.md, .claude/agents/*.md, scripts/sync_agents.py (canonical role source + Codex/Antigravity generation)
    scripts/launch_antigravity.ps1                   how identity is injected into a launched process
    PLATFORM_STATE.json

Measured problem (2026-09-04): two study sessions of 735 and 773 assistant messages re-read ~389M and
~356M cached input tokens because ONE agent session stayed alive across design, capability work, tests,
audits, long jobs and analysis. The fix is not manual session rotation. It is a persistent deterministic
supervisor with disposable workers.

============================================================
0. NON-NEGOTIABLE CLARIFICATIONS
============================================================
1. ONE PROVIDER PER SUPERVISOR RUN. The supervisor launches workers ONLY with the provider it was started
   with (default: the provider of the shell that started it, via research_workflow.workspace.writer_identity;
   override `--provider claude|codex|gemini|antigravity`). It NEVER launches a different provider. A Claude
   supervisor spawns Claude workers only; a Codex supervisor spawns Codex workers only. Cross-provider
   orchestration is out of scope and must not be built.
2. ANY PROVIDER MUST BE ABLE TO DROP IN. The supervisor, its state, the packets and the result cards are
   provider-neutral files in the repo. Switching IDE/harness means starting (or resuming) the supervisor
   under that provider; it picks up the same persisted state. That is why role definitions exist for
   Claude, Codex and Gemini/Antigravity (.claude/agents canonical -> scripts/sync_agents.py).
3. Antigravity has no headless run mode (it is a VS Code fork IDE; verified). For provider=antigravity the
   supervisor runs in ATTENDED mode: it prepares the worker packet, prints the exact instruction for the
   human-attended Antigravity session, and waits for that session's result card. Do not invent a CLI.
4. Do NOT replace, wrap or duplicate governed_controller_v2. The supervisor answers one question only:
   "which fresh AI worker, if any, runs next, or which deterministic job is launched/awaited?"
5. This is a THIN orchestrator: cheap Python, file-state polling, no scheduler framework, no service.

============================================================
1. ARCHITECTURE (three layers)
============================================================
RESEARCH SUPERVISOR (new, scripts/research_supervisor.py + research_workflow/supervisor/)
    derives study state from artifacts, routes typed states, launches fresh worker processes or the
    detached controller, waits cheaply, escalates only typed intervention states
AI WORKER SESSIONS (existing role definitions; headless, disposable)
    bounded reasoning/implementation/audit/interpretation; write a result card FILE; EXIT
GOVERNED CONTROLLER (existing, untouched)
    deterministic lifecycle: compile->prepare->readiness->preflight->tests->audits->seal->smoke->collection
    ->reconcile->merge->fit->freeze->oos->analyze->close; status cards; run lock

STATE PRINCIPLE: derive, do not invent. On every tick and on every resume the supervisor recomputes each
study's position from: `research study status` card, compiled_plan.json, CAPABILITY_GAP_HANDOFF.json,
_work/handoff/*.json, worker result cards, lease/chore registries, git branch/head. It persists ONLY what
artifacts cannot tell it: attempt counters, active worker/job process identity, task ids, timestamps,
user-decision cards. No scientific meaning may exist only in supervisor state.

============================================================
2. ENTRYPOINT (repo convention: scripts/research.py verbs; thin script may exist alongside)
============================================================
    python scripts/research.py supervise start --question question.md [--study-id <id>] [--provider <p>] [--execute-authorized] [--detach]
    python scripts/research.py supervise resume <study_id>
    python scripts/research.py supervise status <study_id> | supervise list
    python scripts/research.py supervise stop <study_id>
    python scripts/research.py supervise tick [<study_id>]        # one deterministic step (used by tests)
    python scripts/research.py supervise decide <study_id> --answer <file>   # supply a USER_DECISION answer

`start` creates the study workspace (study new, with the supervisor's provider identity), persists state,
and by default DETACHES the supervisor loop (Windows: subprocess.Popen with CREATE_NEW_PROCESS_GROUP |
DETACHED_PROCESS, stdout/stderr to a log, pid file). The user's terminal returns immediately. The same
detached spawn helper launches the controller's long jobs. Nothing runs in a foreground shell for minutes.
`--execute-authorized` is the ONLY way post-seal stages ever run (it is forwarded to the controller); it is a
conscious user choice at start, persisted per study.

Supervisor state dir (machine-local, outside the repo like leases): ~/.nt_research/supervisor/<study_id>/
    state.json (atomic write via tmp+replace), events.jsonl (append-only), packets/, results/, logs/, pid

state.json fields: schema_version, study_id, question_path, question_sha256, platform_commit_at_start,
provider, study_branch, study_worktree, execute_authorized, derived_state, derived_from (artifact paths +
hashes), current_phase (A/B/C/D), last_completed_deterministic_artifact, active_worker {role, task_id,
provider, session_id (NT_RESEARCH_AGENT_SESSION), pid, started_at_utc, packet_path, result_path,
deadline_utc}, active_job {kind, pid, started_at_utc, expected_artifact}, active_capability {topic, chore_branch,
chore_worktree, handoff_path}, attempts {<state_or_task>: n}, last_blocker_code, blocker_streak,
user_intervention_required, user_decision {code, question, card_path, answered}, next_action, updated_at_utc.

============================================================
3. WORKER MODEL
============================================================
Every worker is a NEW PROCESS with a SMALL POINTER PACKET (packets/<task_id>.md, <= a few KB), never a
conversation replay. Packet contents: exact role, exact task, study id/branch/worktree, the files to read
(WORKFLOW.md §N and the relevant §; PLATFORM_STATE.json; research_decision.yaml; study.yaml;
compiled_plan.json or status card when applicable; previous handoff/result card), exact allowed write
surface, exact stop conditions, the result-card path it MUST write, and the identity it runs as.

Session types (each a fresh process; a worker never continues into another role):
    STUDY_DESIGN_COMPILE, CAPABILITY_IMPLEMENTATION, PREPARE_SEAL, CAUSAL_AUDIT, CONTRACT_AUDIT,
    EXECUTION_TRIAGE, ANALYSIS_DECISION, DETERMINISTIC_REPAIR
Map each to the existing canonical role definition (implementer, lookahead-auditor, contract-checker,
analysis-decider, primary-owner rules in docs/AI_AGENTS.md); do not author a parallel role set.

Provider adapter interface (research_workflow/supervisor/providers.py):
    launch_worker(provider, role, worktree, packet_path, identity, result_path, *, read_only, timeout_s) -> LaunchHandle
    poll(handle) -> running | exited(code)
Adapters: `claude`, `codex`, `gemini` (headless), `antigravity` (attended: print instructions, wait for
result card), and `scripted` (test-only: runs a Python script that writes a prescribed result card).
INSPECT EACH REAL CLI WITH --help BEFORE USING ANY FLAG. Known non-interactive surfaces to verify:
Claude Code print mode (`claude -p`, JSON output, a max-turns cap, permission mode flags), `codex exec`,
`gemini -p`. Use only flags the installed version prints in --help. Each write-capable launch sets
NT_RESEARCH_AGENT=<provider> and a fresh NT_RESEARCH_AGENT_SESSION uuid so the v3 writer lease is per
worker; read-only auditors get an identity but never claim. Apply a wall-clock cap per worker; on expiry
kill the process tree and record WORKER_TIMEOUT.

Result card contract (file, versioned, validated; prose in the model's stdout is non-authoritative):
    ~/.nt_research/supervisor/<study_id>/results/<task_id>.result.json   (NOT inside studies/<id>; see §11.C)
    schema_version, task_id, study_id, worker_role, provider, session_id, source_commit, branch, status
    (DONE | BLOCKED | FAILED), blocker_code, changed_files, commits, tests {command, new_failures, known, fixed},
    artifacts, scientific_decisions_changed, protected_data_accessed (must be false unless authorized stage),
    next_state, next_exact_action, notes
Missing/invalid card => worker FAILED (counts toward the bounded retry). Reuse research_workflow/handoff.py
for the schema and writer helper; add `research study result --task <id> --packet <path> ...` so workers write
cards through the CLI rather than by hand (the CLI resolves the results dir from the packet).

============================================================
4. TYPED ROUTING (derived_state -> action)
============================================================
    NO_SPEC / DRAFT                       -> STUDY_DESIGN_COMPILE worker (phase A)
    CAPABILITY_GAP {MISSING_CAPABILITY, UNSUPPORTED_COMPOSITION, UNAVAILABLE_STREAM needing a build}
                                          -> CAPABILITY flow (§5)
    CAPABILITY_GAP {INVALID_PARAMETERIZATION} -> fresh STUDY_DESIGN_COMPILE worker
    CAPABILITY_GAP {AMBIGUOUS_TEMPORAL_SEMANTICS, SEMANTIC_DECISION_REQUIRED}
                                          -> fresh STUDY_DESIGN_COMPILE worker IF research_decision.yaml
                                             (terminal_decisions / autonomy_decisions) resolves it; else USER_DECISION_REQUIRED
    COMPILED                              -> controller --through seal (deterministic; the controller stops at NEEDS_*)
    NEEDS_CAUSAL_AUDIT                    -> fresh CAUSAL_AUDIT worker (read-only) -> research audit ingest -> controller again
    NEEDS_CONTRACT_AUDIT                  -> fresh CONTRACT_AUDIT worker (read-only) -> ingest -> controller again
    DETERMINISTIC blocker (preflight/readiness/tests failing, NEW_FAILURE from test_delta)
                                          -> bounded DETERMINISTIC_REPAIR worker
    READY_TO_SMOKE / READY_TO_COLLECT / READY_TO_FIT / any stage after seal
                                          -> detached controller job (only with execute_authorized); NO AI alive
    RUNNING (controller run lock live)     -> wait (poll file/process state on a backoff); NO AI alive
    STALE_FREEZE after a required capability merge -> controller recompile/reseal per lifecycle; fresh auditors
    EXECUTION blocker needing reasoning   -> EXECUTION_TRIAGE worker (reads cards/logs, writes card; never re-runs by hand)
    READY_FOR_ANALYSIS                    -> fresh ANALYSIS_DECISION worker
    STUDY_CLOSED                          -> terminal; write final SESSION_HANDOFF phase D; optional merge to main (see §5 gate)
User intervention ONLY for typed codes: SCIENTIFIC_SEMANTIC_DECISION_REQUIRED, AUTHORIZATION_AMBIGUITY,
PROTECTED_OOS_AUTHORIZATION_REQUIRED, DATA_SAFETY_RISK, CAUSAL_DEFINITION_AMBIGUOUS, RESEARCH_CONTRACT_CONFLICT,
DESTRUCTIVE_ACTION_REQUIRES_APPROVAL, SUPERVISOR_ESCALATION_REQUIRED. If autonomy_decisions already answers
the question, do not ask. Never ask for: deterministic bugs, test failures, capability details, stale
freezes, audit regeneration, merge/recompile decisions, long-job completion.

============================================================
5. CAPABILITY FLOW (the only place shared platform code is written)
============================================================
1. study worker wrote CAPABILITY_GAP_HANDOFF and exited (compile already does this)
2. supervisor: `ws chore claim <topic> --paths <suggested files> --surface ...` under the supervisor's identity;
   if PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT -> wait on that chore (poll registry), never build a competitor
3. create chore/<topic> worktree from current main; launch fresh CAPABILITY_IMPLEMENTATION worker with the
   handoff as packet; write surface = claimed paths only
4. worker: implement ONLY the capability, targeted tests, `python scripts/test_delta.py <scopes>`,
   `research cap generate --check`, cap promotion when the capability flow requires it, commit, result card
5. MERGE GATE (default: approval required): the supervisor merges chore -> main with --no-ff ONLY if the
   result card is DONE, the diff is confined to the claimed write surface, test_delta new_failures == 0,
   `cap generate --check` is clean, and the study's research_decision.yaml declares
   autonomy_decisions.platform_merge: auto_if_green. Otherwise persist DESTRUCTIVE_ACTION_REQUIRES_APPROVAL
   (the user runs `supervise decide`). Loosening later is cheap; unwinding a bad merge is not.
6. release the chore claim; merge main into the study worktree (`git merge --no-ff main`); launch fresh
   STUDY_DESIGN_COMPILE worker; if a seal existed, the controller's stale-freeze path recompiles/reseals.

============================================================
6. RETRY / ESCALATION (persisted counters, never in AI context)
============================================================
    DETERMINISTIC_REPAIR attempts per blocker: 2      capability implementation attempts: 2
    audit passes: the existing platform cap            worker timeouts: 1 retry
    same blocker_code after an independent repair attempt -> SUPERVISOR_ESCALATION_REQUIRED (user card)
No replacement-agent chains: a worker that FAILED twice on the same task stops the study's progression.

============================================================
7. MULTI-STUDY, RESOURCES, NOTIFICATIONS
============================================================
One supervisor process per machine loops over every study under ~/.nt_research/supervisor/ (or one
instance per study with a shared heavy-job semaphore file); never touch a worktree whose lease belongs to
another writer (use ws claim / check_writer_access). `max_heavy_jobs` (default 2) bounds concurrent
detached controller jobs; `max_workers` (default 2) bounds concurrent AI workers. A study in
USER_DECISION_REQUIRED stops; the others continue. Notification: a Windows toast via PowerShell plus the
`supervise status` card; do not build an external service.

============================================================
8. TESTS AND PROOF (no data replay, no real model tokens in tests)
============================================================
`scripted` provider: a worker script that writes a prescribed result card (and optionally a handoff) so the
whole orchestration runs deterministically in seconds. Black-box test (scripts/tests/test_supervisor_blackbox.py):
synthetic study (docs/examples/registry_blind_draft.yaml triggers MISSING_CAPABILITY) ->
design worker exits -> gap handoff -> chore claim + capability worker (scripted) -> merge gate (auto_if_green
declared in the fixture) -> fresh compile worker -> controller to NEEDS_CAUSAL_AUDIT (use the synthetic
lifecycle fixtures from research_workflow/tests/test_lifecycle_v2.py) -> causal worker -> contract worker ->
detached deterministic stage with NO worker alive (assert active_worker is None while the job runs) ->
analysis worker -> STUDY_CLOSED. Record and assert: worker_count, distinct session ids == worker_count
(no session spans two roles), max packet size, AI sessions alive during the deterministic wait == 0,
user interventions == 0. Second scenario: SEMANTIC_DECISION_REQUIRED not covered by autonomy_decisions ->
exactly one USER_DECISION_REQUIRED card, progression stops, `supervise decide` resumes it.
Crash/resume tests: kill supervisor while a worker runs / while the controller runs; restart -> state derived
from artifacts, no completed stage re-run; stale worker pid reaped; a result card completed while the
supervisor was offline is consumed; a capability merged while offline is detected from git.
Run targeted tests while implementing; ONE `python scripts/test_delta.py research_workflow/tests scripts/tests`
before commit; act only on NEW_FAILURE. Real-provider smoke: exactly one `claude` (or the current provider)
worker launch on the synthetic study, once, at the end.

============================================================
9. DOCUMENTATION
============================================================
WORKFLOW.md: new §O "Supervised research (default)"; §D and §N become the manual/debug fallback and say so.
docs/QUICKSTART.md: the normal flow is `supervise start --question question.md` then `supervise status`.
docs/AI_AGENTS.md: workers are launched by the supervisor with a packet and a result-card contract; a
human-attended session (any provider) can act as a worker by following the same packet. Role files
(.claude/agents/*.md): add the result-card duty; regenerate with scripts/sync_agents.py. Keep the docs
tests (research_workflow/tests/test_concurrent_research_docs.py, test_docs_v2.py) green; extend them.

============================================================
10. DISCIPLINE FOR THIS IMPLEMENTING SESSION
============================================================
- Work on chore/research-supervisor in its own worktree; first: `python scripts/research.py ws whoami --expect <your agent>`
  and `python scripts/research.py ws chore claim research-supervisor --paths research_workflow/supervisor/ scripts/research_supervisor.py scripts/research.py research_workflow/handoff.py WORKFLOW.md docs/ --surface "research supervisor v1" --as <your agent>`.
- Do not touch governed_controller_v2.py except a read-only status accessor if one is missing; do not touch
  studies/ or any live-leased worktree (controlled_feature_family_180s is live under another session).
- Build order: (1) state derivation + tick loop + detached spawn + scripted provider + black-box test;
  (2) real adapter for the CURRENT provider only, one smoke run; (3) multi-study loop + semaphores;
  (4) docs flip. Commit at each step with test_delta green. Merge to main with --no-ff when the black-box
  proof passes; write `research study handoff --phase A --note SUPERVISOR_V1_COMPLETE`.
- Context budget: hand off (write the SESSION_HANDOFF + this packet's remaining items) before ~100k tokens.

============================================================
11. REQUIRED V1 HARDENING ADDENDUM (verified against the repo; two corrections noted)
============================================================
A. GLOBAL MAIN-MERGE LOCK
   Any supervisor operation that reads-then-mutates canonical `main` (capability merge, closed-study merge,
   merging main into a study worktree) holds ~/.nt_research/locks/main_merge.lock for the bounded operation
   only. Reuse research_workflow/locks.py acquire_exclusive (O_EXCL create, is_stale = holder pid dead or
   lock older than a bounded age). Holder without the lock -> WAIT_MERGE_LOCK, no AI worker alive while
   waiting. Multiprocess race test: two supervisors with two green capability branches -> exactly one
   merges at a time, main history is linear per merge, both land, no interleaved index state.
B. PACKET / RESULT STALENESS BINDING
   Every packet carries: task_id, packet_sha256 (canonical JSON of the packet body), study_id,
   study_contract_sha256 (sha256 over research_decision.yaml + study.yaml bytes), compiled_plan_sha256
   (when present), source_commit, platform_commit (main), expected_branch, expected_worktree. Every result
   card repeats them; the supervisor validates ALL before consuming. Mismatch -> STALE_WORKER_RESULT: never
   ingest, merge, audit or advance from it (it counts as a failed attempt, with the mismatching field named).
C. READ-ONLY WORKER OUTPUT LOCATION  (CORRECTED for `research audit ingest`)
   Result cards and raw auditor reports are written under ~/.nt_research/supervisor/<study_id>/results/,
   never under studies/<id>/, so causal/contract auditors are genuinely read-only with respect to the
   governed study. BUT `research audit ingest` does NOT copy the report: lifecycle_v2.ingest_audit_report
   binds `audit_report_path` (relative if inside the study, else the absolute machine-local path) and its
   sha256 into studies/<id>/audit/status.json. A report left outside the repo would make the study's audit
   evidence uncommittable and would break the closed-study authority (audit passes are committed with the
   study). Therefore the deterministic supervisor, after validating the auditor's result card:
       1. copies the report into studies/<id>/audit/pass_NN.md or contract_pass_NN.md (next free NN),
       2. calls `research audit ingest --study <dir> --type <causal|contract> --report <that in-study path>`,
       3. records the copied path + sha in the result consumption event.
   Ingest also refuses AUDITOR_ROLE_REUSE: the causal and contract auditors must be distinct identities.
   Give each auditor worker a distinct `auditor` string in its packet (role + session id) and pass it as
   the report's auditor / `--author`.
   Study-side handoff cards (CAPABILITY_GAP_HANDOFF, SESSION_HANDOFF) stay in the study: they are written
   by write-capable study workers, not by auditors.
D. ADOPT EXISTING STUDIES
   `python scripts/research.py supervise adopt --study studies/<id> [--provider <p>] [--execute-authorized]`
   creates supervisor state for an existing study by deriving its position from artifacts (status card,
   compiled_plan, handoffs, audits, seal, closure, git). It never recreates the study, rewrites contracts or
   re-runs completed stages. ADDITION: if the study worktree carries a live writer lease held by another
   session, adopt records the state but progression waits (WAIT_STUDY_LEASE) until the lease is released;
   the supervisor never force-releases a foreign live lease. Black-box: progress a synthetic study manually
   to NEEDS_CONTRACT_AUDIT, delete supervisor state, adopt, assert next action == launch CONTRACT_AUDIT and
   no earlier stage re-runs.
E. MACHINE-WIDE RESOURCE LEASES
   `max_workers` and `max_heavy_jobs` are enforced across supervisor processes via atomic slot files under
   ~/.nt_research/locks/slots/{workers,heavy}/<n>.slot (O_EXCL, holder pid + started_at; dead-pid slots
   reclaimable). No slot -> WAIT_RESOURCE with no AI alive. Crash/resume test: kill a supervisor holding a
   slot; a second supervisor reclaims it once the pid is dead.
F. PROVIDER CAPABILITY DETECTION
   At startup (and via `python scripts/research.py supervise providers`) probe each configured provider's
   installed CLI (`--version`, `--help`) and record: AVAILABLE, HEADLESS_SUPPORTED, ATTENDED_SUPPORTED,
   WRITE_SUPPORTED, READ_ONLY_SUPPORTED, SESSION_IDENTITY_SOURCE, CLI_VERSION, probe_output_sha256.
   Never assume a flag from documentation; only what the installed binary prints. A worker whose required
   capability is absent fails BEFORE launch with PROVIDER_CAPABILITY_UNAVAILABLE. Antigravity stays ATTENDED
   (no headless interface exists on this machine) until a real one is proven; a `human` attended provider
   is the same code path.

Build-order impact: A, B, C, D, E belong to step (1) with the black-box test (they are orchestration
logic and are proven by the scripted provider); F belongs to step (2) with the real adapter.

FINAL CARD additions:
MAIN_MERGE_LOCK: atomic / concurrent_merge_test:
WORKER_STALENESS: packet_hash_bound / stale_result_refused:
READ_ONLY_WORKERS: study_worktree_mutated: NO / external_result_area / report_copied_then_ingested:
ADOPT_EXISTING: implemented / resume_without_rerun_proven / foreign_live_lease_waits:
RESOURCE_LIMITS: machine_wide / crash_reclaim / ai_alive_while_waiting: 0
PROVIDER_DISCOVERY: command / Claude / Codex / Gemini / Antigravity:

============================================================
DO NOT
============================================================
replace or wrap governed_controller_v2 · create a second lifecycle · keep scientific state only in
supervisor state · bypass leases/chore ownership · let study workers write platform code · poll with an
AI session · launch a provider other than the one the supervisor started with · auto-decide genuine
scientific ambiguity · auto-merge platform code without the green gate + declared policy · build a
distributed task system · invent CLI flags not shown by the installed tools' --help

============================================================
FINAL CARD
============================================================
RESEARCH_SUPERVISOR_V1_CARD
ENTRYPOINT / START_COMMAND / STATUS_COMMAND / RESUME_COMMAND / STOP_COMMAND:
SUPERVISOR: deterministic / persistent_state / restart_safe / state_derived_from_artifacts:
CONTROLLER: existing_controller_reused / duplicated_lifecycle: NO
WORKER_SESSIONS: disposable / phase_bounded / result_card_schema / prose_scraping_required: NO
ROUTING: capability_gap / causal_audit / contract_audit / long_job / analysis / user_decision:
PROVIDER: single_provider_per_run / current_provider_adapter / attended_mode_for_antigravity:
WRITER_OWNERSHIP: study_leases / chore_leases / per_worker_session_identity:
LONG_JOBS: ai_session_alive_while_waiting: 0 / detached_resume_proven:
RETRY_POLICY: bounded / repeated_blocker_escalation:
MERGE_GATE: default_requires_approval / auto_if_green_when_declared:
MULTI_STUDY: proven / concurrent_example:
BLACK_BOX: complete / worker_sessions / distinct_session_ids / max_packet_bytes / user_interventions / AI_SESSION_DURING_LONG_WAIT:
TESTS: passed / failed / new_failures (test_delta):
MAIN_COMMIT / CLEAN:
READY_FOR_ONE_PROMPT_AUTONOMOUS_RESEARCH: true / false
KNOWN_LIMITATIONS:
RECOMMENDED_NEXT_STEP: one sentence
