# autonomous_explore: implementation and pilot report

Branch `chore/autonomous_explore`, built from `chore/research_lanes` (`7ff5fdb7`). One consolidated branch.

## Pilot results (real NQ_1S_V2_GLOBEX data)

| Pilot | Study (branch `study/<id>`) | Wall time | Human interventions | Outcome |
|---|---|---|---|---|
| 1. Novel causal calculation | `pilot_close_location_streak` (2024-01-02..03-28) | **3 min 42 s** controller (12:30:06 → 12:33:48); 5 min 2 s from `study new` | 0 | **SUPPORTED** (EXPLORATORY): aligned >=3-bar 1m close-location streak, flip-within-30-min rate −4.06 pp, 95% session-clustered CI [−8.00, −0.12] pp, 63 sessions, n=454 vs 18,708 |
| 2. Deliberate scientific failure | `pilot_leaky_observer` | 18 s | 0 | **Refused at compile**: `OBSERVER_DETERMINISTIC_FAILED` from the generated causality harness. No seal, no data access, no ledger exposure |
| 3. Same definition, new data | `pilot_cls_robustness_q2` (2024-04-01..06-28) | 3 min 52 s | 0 | **SUPPORTED**, claim level computed as **CHRONOLOGICAL_ROBUSTNESS** (the ledger matched the identical scientific definition under a new study id): −5.68 pp, CI [−10.06, −1.29] pp, 65 sessions, n=439 vs 19,575 |

### Independent reconciliation of Pilot 1

- **Method:** brute-force pandas over catalog 1m bars, with no code shared with the observer or the host. The RTH window is taken from the Chicago clock, 08:30–15:15 CT.
- **Feature:** `streak` 20,827/20,827 exact, `session_bar` 20,827/20,827 exact.
- **Availability:** `seen_ts == observation_ts` on every row (a completed 1m bar, never later).
- **Population:** every row is RTH with session bar >= 15. All 63 sessions are present.
- **Script:** `reconcile_pilot1.py` (copied here).

### Scientific interpretation (author's caveat, not computed)

Both quarters point the same way and pass the pre-registered rule. The result still **must not** be read as an edge.

- **Possible mechanical confound.** An aligned extreme-close streak moves price away from the dual-EMA pair, so the next flip is mechanically further away. The control is not matched on price-to-EMA distance or regime age.
- **Data reuse.** 2024 has been examined extensively by earlier, pre-ledger research.
- **Recommendation.** The machine recommendation is ESCALATE_FOR_INDEPENDENT_REVIEW_THEN_CONFIRM. The reviewer's first question should be a matched control on price-to-EMA distance and regime age (`analysis.control.cell_matched`). Until that control exists, treat this as STOP or REFINE, not CONFIRM.

## What changed (one consolidated branch)

| Area | Files | Change |
|---|---|---|
| D1 audit freshness | `scripts/run_preexec_audits.py`, `lifecycle_v2.ingest_audit_report`, `governed_controller_v2._audit_current`, `lifecycle_v2.seal`, `governed_controller.py` (BLOCKED re-check) | Statuses record `audited_plan_sha256` (the packet's plan). Freshness and the seal refuse an audit of another scientific definition. Pre-fix statuses are stale (fail-closed) |
| Observers | `study_observers.py`, `compiler.py`, `host/strategy.py` | Declared `tracker` inputs arrive as a read-only FIELDS view; `SESSION = True` adds a read-only view of the published schedule. The harness rebuilds the real upstream chain for prefix-invariance and future-perturbation checks |
| Study tests | `grammar/spec.py` (`study_tests`), `compiler.py`, `lifecycle_v2` (R10 + `tests` stage), controller freshness | Tests are declared, hashed into the plan and run by the `tests` stage. They are exempt from R10 only while bound. Catalog, process and other-study access is refused at compile |
| `tier: explore` | `grammar/spec.py`, `grammar/plan.py`, `compiler.py`, `governed_controller(_v2).py` | Hashed into the plan. Deterministic causal and contract checks run in place of packets. Post-seal stages run without `--execute-authorized`, and the card records the authority. The grammar refuses dev/OOS, a model, outcome `none`, and a missing pre-registered rule |
| Ledger + result | `research_workflow/research_ledger.py` (new), `governed_controller_v2._before_stage`, `lifecycle_v2.close` | Write-once exposure event before smoke; result event at close. Attempt identity, cross-study exposure, computed claim level, pre-registered verdict, `RESULT_CARD.md` + `artifacts/result.json`, per-attempt snapshots, closure `isolation: CLOSED_ISOLATED` |

## Limitations

- **Ledger storage.** The ledger lives in `~/.nt_research/ledger`, which is machine-local and not itself backed up. Every event is mirrored into the study's `artifacts/ledger/` and is recoverable from committed study branches (`rebuild_from_mirrors`). Ledger history begins 2026-11-20, and earlier research exposure is NOT recorded, so "0 prior exposures" never means "unseen".
- **No reserved data.** No reserved confirmation windows are declared (`reserved_windows` in `~/.nt_research/config.yaml`), so CONFIRMATORY is unreachable by design.
- **Harness scope.** The harness supports upstream trackers whose own inputs are streams. An observer whose upstream consumes trackers is refused (`OBSERVER_HARNESS_UNSUPPORTED_UPSTREAM`).
- **Pre-registered rule.** It is one primary clustered difference. Multiple primaries or Holm correction are not built.
- **Session-day clustering.** The card reports sessions as n_clusters. Overlapping 30-minute horizons within a session are handled by the clustering, not by thinning.

## Validation

| Check | Result |
|---|---|
| `test_autonomous_explore.py` (new, 10 tests) | **10 passed**. Covers the primary compile→CLOSED_ISOLATED path, leaky-observer refusal, OOS/rule grammar refusals, reserved-data refusal, D1 semantic changes (session_end / population / chronology) refused at reseal, unchanged plan reuses its approval, code change stales, exposure write-once, cross-study exposure and claim levels |
| Targeted regression (18 files, 4 parallel shards, 15 min) | Only main's 2 known `test_runtime_bindings` failures remain. 16 `test_oos_access_latch` setup errors came from the new fail-closed binding (the fixture wrote audits without a plan); the fixture was fixed, 18/18 pass. 2 failures (`test_lifecycle_v2` outcome-none, `test_audit_seal_guard` unrelated-dataset) were a **parallel-shard race** with tamper-canary tests that mutate real source files (`test_audit_pass_immutability` appends to `features/engine.py`); both pass serially on this branch (15m37s) and on the base |
| Broad CORE gate | 209 files as 6 parallel `test_delta --json` shards plus the 8 tamper-canary files run **serially after** them. Estimated 64 + 43 min (was ~4.7 h serial). Results: `test_delta_broad_*.json` here |
| `research_lanes` | The broad gate run started for `research_lanes` was stopped at the owner's direction. This branch contains `research_lanes` unchanged plus the work above, so its single broad gate covers both. 1 test (`OBSERVER_INPUTS_INVALID`) was updated because tracker inputs are now allowed |
