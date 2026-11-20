# Research lanes — routing audit and approval-ready design

Branch `chore/research_lanes`, from main `dcafca80`. **Design only.** Nothing in `WORKFLOW.md`, `research_workflow/`
or any study is changed by this commit. Two of the proposed changes conflict with existing golden rules. Under the
owner's instruction ("If a new policy exception or governance change requires separate approval, stop at that
gate"), this session stops here.

## 1. Audit: why exploratory work escalates into platform development

Each cause below is backed by repository evidence.

| # | Cause | Evidence | Cost on the volume-clock thread |
|---|---|---|---|
| R1 | **V2 has no study-local causal code path.** The repository has a "zero Python" rule: `WORKFLOW.md` §A ("If a study needs bespoke Python, that is a platform gap"), golden rules 7 and 9, the §N.1 ban on study Python, and CLAUDE.md §5. Under it, any observation the grammar cannot express compiles to `MISSING_CAPABILITY`, and `on_capability_gap: stop_and_handoff` forces the §M.3 capability flow. | `nq_developing_volume_clock` compile `5fb6e087`: 1 MISSING_CAPABILITY (`context.vclock`) plus 24 dependent references. `research_workflow/hooks/` holds only V1 population/target hooks; there is no V2 equivalent. | The whole capability chore |
| R2 | **One merge-gate size for every platform diff.** §N.3 requires "ONE broad relevant `test_delta`". In practice that means every suite. A purely additive tracker (new files plus an index entry) pays the same as a core-compiler change. | Broad gate at `c31d42ec`: 3,038 tests, 17,033 s (4.7 h). It found 0 attributable failures; all 63 are known. The `chore/tiered_gates` design (`000cbfc3`, never implemented) measured that additive trackers reach 34–35 test files. The modularity S3 report (`41bc969a`) puts an additive tier at about 14–59 min. | 4.7 h |
| R3 | **The bar for parity evidence is unstated.** §E only requires "parity/oracle evidence (a JSON artifact)". The full 556-session, three-scale, 631k-checkpoint parity was requested by the task prompts, not by the workflow. Nothing says when bounded-window oracle parity is enough. | `WORKFLOW.md` §E step 4; the volume-clock chore prompts. | 53 min replay, plus a lost stalled run |
| R4 | **A fast path exists but is ungoverned.** 15 `research/<id>` branches run pandas scripts outside the V2 host. Some use `sys.path` imports of sibling study code, which CLAUDE.md §5 prohibits. `WORKFLOW.md` does not mention them. They are fast but not NT-host causal and not production-transferable, which is why their findings had to be rebuilt as a tracker. | `research/nq_volume_burst_momentum/bm_collect.py` imports the frozen `vc_common` / `vc_clock` from the sibling worktree. The Phase F population collects in 35 s. | Duplicate implementation (Stage C script, then tracker) |
| R5 | **The governed fast path exists but is under-used.** The repository already has a lighter path: `stage: collect` → frame seal (causal audit only; no contract audit, deliverable gate, fit or closure) → `frame register` → `explore run`, which is re-runnable in seconds (§P). When a question is composable, that path already is FAST_OBSERVATION. It is not presented as the default. | `WORKFLOW.md` §P; `research_workflow/explore.py`, `frame_store.py`. | — |
| R6 | **Capability reuse already works.** `study compile` binds a promoted capability from the registry and does not re-validate it. The cost of re-proving a capability comes only from task prompts. | `research cap describe tracker.volume_clock.developing` on main (`dcafca80`). | — |

**Conclusion.** The escalation is caused by R1 (no governed study-local route) and R2 (no proportional merge gate), and
it is amplified by R3 (an unstated parity bar) and by prompts that ask for platform-grade proof up front. The
pieces of a fast lane already exist (R5, R6). The flaw is in routing, not in the platform's capabilities.

## 2. Lanes, mapped onto existing machinery

No new framework. Each lane names paths and gates that already exist, except where marked **NEW**.

| Lane | Default for | Path | Required gates | Not required |
|---|---|---|---|---|
| FAST_OBSERVATION | descriptive / distribution / regime / MFE-MAE / first-passage / conditional-probability / preliminary ML-feature studies composed from registered primitives | `study new`, `stage: collect` → frame → `explore` (§P); or **NEW** study-local observer (P3) | compile proof; causal audit; frozen definitions before outcomes (`research_decision.yaml`); targeted tests; bounded smoke; one full collection; `lane_manifest.json` (P2) | contract audit, broad regressions, capability promotion, unrelated parity, repeated replays |
| RESEARCH_VALIDATION | a FAST result worth confirming: chronological replication, independent population parity, candidate policy signal | full V2 study: seal, contract audit, train freeze, authorized OOS, closure | everything above, plus an independent reference where one exists (`find_first_parity_divergence.py`), §L.1 population/timestamp reconciliation, chronological validation, targeted integration tests | capability promotion, broad regressions (unless shared code changed) |
| EXECUTION_VALIDATION | a policy with RESEARCH_VALIDATION evidence | `backtests/run_backtest.py --strategy <id>`: the NT engine generates candidates, features, scores, orders, fills and exits live | independent NT candidate generation reconciled against research (missing / extra / duplicate / retimed candidates, feature/score diffs, triggers, orders, fills, exits, costs); top-of-book fills; session-end behaviour | — (expensive by design) |
| PLATFORM_CHANGE | a shared capability that is genuinely missing (§3 test fails) | §M.3 capability flow, chore worktree | contract, targeted causal tests, parity at the bar the consumer needs (P5), registry check, merge gate sized by diff class (P4) | full-history parity unless a consumer needs exact historical reproduction |

**Execution rule (already policy, now explicit):** a frozen precomputed trade schedule replayed through NT is not
EXECUTION_VALIDATION (memories: schedule-driven NT evaluation inflates PnL 2–3×; live-style NT is the gate).

## 3. Routing test (before any PLATFORM_CHANGE)

1. Can it be composed from registered capabilities (`cap search` / `describe`)? → FAST_OBSERVATION.
2. Can it be expressed with existing tracker fields plus predicates or the analysis DSL (§K "composition first")? → FAST_OBSERVATION.
3. Can a study-local causal observer produce it without changing shared code? → FAST_OBSERVATION (P3, needs approval).
4. Does it need persistent reusable state that more than one study will consume? Only then → PLATFORM_CHANGE.
5. Is platform work needed for correctness, or only convenient? If only convenient → stay in the study lane; promote later
   if a second study needs it.

## 4. Proposed change set (smallest first)

| Id | Change | Files | Conflicts with existing rules? | Needs approval |
|---|---|---|---|---|
| P1 | `WORKFLOW.md` new §Q "Research lanes": the table in §2, the routing test in §3, the budget in §5, the manifest in §6; one-line cross-links from §A, §N.1 and §M.3 | `WORKFLOW.md` | No — it describes existing paths. The P3 and P4 rows are marked "pending approval" | No |
| P2 | `research_workflow/research_lanes.py`: pure `route(facts) → lane`, `required_gates(lane, facts)`, `validate_execution_claim()` (refuses frozen schedules), `write_lane_manifest()`; optional `research_lane:` key in `research_decision.yaml`; `research study lane --study` (read-only report); `research_workflow/tests/test_research_lanes.py` (§7) | 2 new files, plus 1 CLI verb | No — it is advisory and gates nothing. `research_workflow/` sits in study execution closures (CLAUDE.md §3). It is a new module imported by nothing in the closure, so no closure goes stale; to be verified with `resolve_execution_manifest.py` | No |
| P3 | **Study-local causal observer:** `studies/<id>/observers/<name>.py` implements `features.trackers.base.BaseBinding`; `context.x: {tracker: "study_local:<name>"}`. The compiler loads it, hashes it into the closure composite and runs a mandatory generated prefix-invariance + future-perturbation harness (the volume-clock test pattern) at `tests`. It is not visible to other studies; reuse requires PLATFORM_CHANGE | compiler binding resolution, host tracker loader, causal lint scope | **Yes:** §A "zero Python", golden rules 7 and 9, §N.1, CLAUDE.md §5 "bespoke collector". It changes them for observers only; collectors, drivers and event loops stay prohibited | **Yes** |
| P4 | **Diff-classed merge gate:** a chore whose diff is ADDITIVE (new tracker / analysis op / feature module + its test + index entry; no edits to existing modules) runs `test_delta` over its own tests + the compiler / registry / host-binding suites + the derived reachable set, instead of all suites. CORE diffs keep the broad gate | §N.3, `scripts/test_delta.py` (derived scope; reuse `tiered_gates/evidence/tier_replay.py`) | **Yes:** §N.3 "ONE broad relevant run" | **Yes** |
| P5 | **Parity bar by consumer:** PLATFORM_CHANGE parity defaults to exact oracle parity on a bounded window that covers every reset/edge class (session classes, roll, gaps). Full history is required only when a frozen study's results must be reproduced exactly | §E step 4 | Tightens unstated practice; does not loosen a written rule | Recommended to confirm |
| P6 | **Status of `research/<id>` branches:** either (a) record them as historical, with no new ones; or (b) define them as an `OFFLINE_EXPLORATORY` sub-lane whose results can never be cited as NT-causal without a FAST_OBSERVATION re-derivation | `WORKFLOW.md`, `docs/DOCUMENT_MAP.md` | (b) legitimises `sys.path` sibling imports unless they are banned explicitly | **Owner decision** |

P1 + P2 alone fix the routing *advice*. Only P3 + P4 remove the cost seen on this thread: R1 and R2. Without P3, a
non-composable observation still has to go through PLATFORM_CHANGE.

## 5. Validation budget (selected by lane, before any long job)

| Gate | FAST_OBS | RESEARCH_VAL | EXECUTION_VAL | PLATFORM_CHANGE |
|---|---|---|---|---|
| synthetic causal tests (prefix invariance / future perturbation) | yes | yes | yes | yes |
| bounded real-data smoke of collect → compare → report (§M.3 step 3 lesson) | yes | yes | yes | yes |
| one full-history collection | if the question needs it | yes | yes | no |
| independent reference parity | no | where one exists | vs research expectations | at the P5 bar |
| contract audit / seal / OOS latch | no | yes | yes | no |
| NT order / fill / exit realism | no | no | yes | no |
| capability promotion | no | no | no | yes |
| broad `test_delta` | no | only if shared code changed | only if shared code changed | by diff class (P4) |
| re-proof of a consumed, unchanged promoted capability | **never** — cite registry id + promotion evidence sha | never | never | n/a |

## 6. Compact manifest (`lane_manifest.json`, one per study run; replaces restated provenance)

`study_id, lane, dataset_id, dataset_digest (catalog logical digest, read once), capability_versions
{id: registry sha + promotion evidence sha}, study_contract_sha (research_decision.yaml), plan_sha256, schema_version,
timestamp_convention, timezone, period, outputs [{path, rows, sha256}], validation {gate: PASS|FAIL|NOT_REQUIRED},
verdict (STOP | REFINE | VALIDATE | PROMOTE)`. Large unchanged inputs are referenced by digest, not re-hashed. There is
one human summary (`EXECUTIVE_SUMMARY.md`: hypothesis, population, measurements, caveats, evidence, decision).

## 7. Routing tests (`research_workflow/tests/test_research_lanes.py`, written with P2)

| # | Requirement | Fixture → assertion |
|---|---|---|
| 1 | descriptive study → FAST | `stage: collect`, registered primitives → FAST_OBSERVATION, gates exclude contract audit and broad tests |
| 2 | causal feature study on existing capabilities → FAST | compiled plan, all capabilities `verified` → FAST |
| 3 | first-passage outcome study is not PLATFORM_CHANGE | outcome kernel registered → FAST |
| 4 | promising candidate → RESEARCH_VALIDATION | prior lane manifest verdict VALIDATE → RESEARCH_VALIDATION; gates include independent parity and chronology |
| 5 | trading backtest → EXECUTION | `strategy_class` + order simulation declared → EXECUTION_VALIDATION |
| 6 | missing shared streaming capability → PLATFORM_CHANGE | CapabilityGap MISSING_CAPABILITY, `reuse_consumers >= 2`, or no study-local route → PLATFORM_CHANGE |
| 7 | unchanged validated capability reused | capability with promotion evidence sha → no promotion / parity gate in `required_gates` |
| 8 | study-local logic cannot bypass causal checks | study-local observer → required gates include the generated invariance harness and causal audit; their absence → REFUSED |
| 9 | no self-declared execution validation from a frozen schedule | `validate_execution_claim(schedule_source="precomputed")` → refused |
| 10 | expensive gates only by lane | broad / contract / full-history appear only in the lanes in §5 |
| 11 | frozen studies keep their evidence | a sealed or closed study → lane `HISTORICAL`, no gates re-selected, its contracts are not read for rewrite |
| 12 | Phase F resumes without re-collection | the population manifest with hash present → `collect` not in gates; `outcomes`/`analysis` only |

## 8. Volume-clock thread, re-routed in hindsight

A study-local observer under P3 would have run the developing clock in the study's own lane: a bounded synthetic
harness plus one collection. With the 35 s per collection measured on the Phase F path, that is minutes instead of
≈ 6 h of chore gates. Promotion to a shared tracker would follow only when a second study needed it. The full parity
done here stays valid and is now reusable evidence (R6).
