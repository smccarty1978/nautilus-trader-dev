# SESSION HANDOFF — chore/research_lanes

## UPDATE 2026-11-20: P3–P6 approved and implemented at `9463711e` (see IMPLEMENTATION.md)

- Targeted gate: 250 ran, 2 failed. Both are main's known node ids, so 0 attributable.
- The required broad gate (this chore is CORE_SURFACE) was launched once, detached:
  `test_delta.py research_workflow/tests scripts/tests research/analysis/tests features/tests --tier-base main --json`.
  Output goes to `$TEMP/rl/broad.json`, with the exit line in `$TEMP/rl/broad.err`. Expect about 5 h.
- Next session:
  1. Read the card and classify NEW failures against `../volume_clock_tracker/test_delta_broad.json` (63 known node ids).
  2. Copy the card to `test_delta_broad.json` here.
  3. With 0 attributable failures and the owner's merge approval: under `main_merge.lock`, merge `--no-ff` to main and run `cap generate --check`.
  4. Release the claim `research_lanes`.
- Merge is NOT pre-authorized by the design approval; confirm with the owner.

---

## Earlier state (Gate B; superseded)

## Gate status

| Gate | Status |
|---|---|
| A: volume-clock integration | **DONE.** Merged to main as `dcafca80` (`--no-ff`, under `main_merge.lock`). The merged tree equals promoted `df84868c` (0-line diff). `cap generate --check` OK (237 entries, 0 broken, registry sha `75472cf5…`). `cap describe` lists the tracker. 39 tracker + harness tests pass on main, and 6 `test_capability_modularity` tests pass. CAPABILITY_COMPLETE handoff written in the study worktree. Chore claim `volume_clock_tracker` released |
| B: routing audit | **DONE.** See `DESIGN.md` §1 (causes R1–R6) |
| C: implement | **STOPPED.** P3 and P4 conflict with golden rules (§A / 7 / 9, §N.1, §N.3, CLAUDE.md §5) and need owner approval. P6 needs an owner decision. P1 + P2 are compatible, but their shape depends on the P3 and P4 answers, so they are not built yet |
| D: routing tests | Specified in `DESIGN.md` §7; written with P2 |
| E: Phase F handoff | Below |

## Decisions needed from the owner

1. **P3**: approve study-local causal observers in V2 (observers only, harness-gated, closure-hashed, not shareable)?
2. **P4**: approve the diff-classed merge gate (ADDITIVE chores skip the all-suites broad run)?
3. **P5**: confirm bounded-window oracle parity as the PLATFORM_CHANGE default?
4. **P6**: retire `research/<id>` pandas branches as historical (a), or keep them as OFFLINE_EXPLORATORY (b)?

## Next session (after the answers)

`ws chore claim research_lanes` is still held by this session (`--paths` listed in the claim). In this worktree:
1. Implement P1 + P2 and the approved parts of P3 / P4 / P5.
2. Write the 12 tests in `DESIGN.md` §7.
3. Run `python scripts/resolve_execution_manifest.py` on any in-flight sealed study, to prove the closure is untouched.
4. Run targeted `test_delta` on the new tests. P3 and P4 touch the compiler, host and `test_delta`, so they are CORE diffs:
   one broad run before merge is still required for them under the current §N.3.
5. Merge with `--no-ff` after approval.

## Phase F (`research/nq_volume_burst_momentum`): already complete. Do not re-run it

The premise "future outcomes have not yet been evaluated" is out of date. On that branch:
- `f8e44bea`: contract frozen before outcomes
- `614c3029`: population (H1 5,969 / 5,506, H2 554 / 502, grid 767,600)
- `c41fdde9`: outcome resolution
- `63f9ddf6`: analysis and `EXECUTIVE_DECISION.md`

Verdicts:

| Hypothesis | Verdict | Result |
|---|---|---|
| H1 MOMENTUM_CONTINUATION | NEGATIVE | P1 2025 −0.37 pp [−1.93, +1.15] |
| H2 LOW_PROGRESS_EXHAUSTION | INCONCLUSIVE | 2025 +7.5 pp Holm-significant, but 2024 −1.35 pp, the opposite sign |
| INCREMENTAL_VOLUME_BAR_VALUE | NEGATIVE | — |
| DETECTION_LATENCY_VALUE | NOT_POSITIVE | V1 fires a median 9 s after rv30 |

The worktree holds untracked rerun outputs (`out/analysis_run2/`, `out/outcomes_run2/`, `out/outcomes_smoke/`), which
were left untouched.

**Lanes:**
- H1 is closed: no further lane.
- H2 is the only open thread. Confirming it would be a new registered study in **RESEARCH_VALIDATION**: chronological
  replication on a year not used. Inside the authorized data that leaves only 2023-11..12 (2026 is prohibited). That
  sample is likely too small (Phase F required ≥ 200 per year), so H2 confirmation is probably infeasible without
  new data. The next step is a researcher decision, not an automatic session.
- `nq_developing_volume_clock` (dvc_v1) can now resume: the capability is on main. Its session must:
  1. merge main into the study worktree;
  2. add `dataset: NQ_1S_V2_GLOBEX`, `bars: 1s` to `vclock`;
  3. check that the warmup covers ≥ 10 eligible sessions;
  4. recompile.

  Lane: its design fits a train-2024 / dev-2025 model, so **RESEARCH_VALIDATION**. Under the current rules it has to
  run as a full V2 study; collect → explore (FAST) is available if the owner wants a cheaper first look. Its
  `research_decision.yaml` is DESIGN_APPROVED.

## Worktree notes

The `chore/volume_clock_tracker` worktree still holds test side effects: 7 modified study audit files under three
studies, plus `research_workflow/tests/first_passage_parity.json`. They are uncommitted, left untouched and not part
of the merge.
