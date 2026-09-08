# Session 1 — restore the gate (baseline re-record)

    packet:   RESTORE THE GATE, THEN UNBLOCK MODULARITY — Session 1
    where:    canonical checkout, clean `main`; one broad `test_delta --update-baseline` run, detached
    status:   DONE — baseline re-recorded on main (schema 2, 64 entries, `test_delta --check-baseline` OK) after a test_delta defect was found, fixed and merged first

## What happened, in order

1. **Attempt 1 (08:21, main 68e0722a), discarded.** Ran alongside other test processes on the same host
   (the Session 3 surface run and Session 2 targeted runs, which share the machine-wide supervisor locks,
   slots and `~/.nt_research` state). It completed with **108 entries, 45 more than the committed 63**,
   and left the canonical checkout dirty (`features/engine.py` carrying a test's un-restored mutation,
   five ES study audit artifacts regenerated). The recorded messages of the 45 additions were not
   contention at all: they said `ModuleNotFoundError: No module named 'research.analysis'; 'research'
   is not a package` from every subprocess that launched a script under `scripts/`, plus the
   RUNTIME_FAILURE cascades that follow from it (lifecycle end-to-end, supervisor black-box, packet F,
   rt blockers, generated contracts, attestation, docs registry currency). Poisoned file kept as
   `evidence/baseline_rerecord_contended_POISONED.json`; the checkout was restored; nothing committed.
2. **Root cause found and reproduced.** `scripts/test_delta.py` (Wave 2, `e2e58fbf`) built the pytest
   subprocess environment as `PYTHONPATH = <tmp> + os.pathsep + os.environ.get('PYTHONPATH', '')`. With
   no `PYTHONPATH` set that leaves a trailing **empty** element, which CPython resolves to the current
   working directory. A test that then spawns `python scripts/<x>.py` gets `scripts/` first on
   `sys.path`, and `scripts/research.py` shadows the `research` package. Deterministic:
   `python scripts/write_train_provenance_attestation.py --help` succeeds with no `PYTHONPATH` or with
   `PYTHONPATH=<tmp>`, and fails with `PYTHONPATH=<tmp>;`. Every test that launches a script has failed
   under `test_delta` since Wave 2 merged; nothing had run the broad suite through it until this session.
3. **Attempt 2 (09:51, serial), killed at 5 minutes** once the root cause was known — it would have
   enshrined the same ~40 spurious entries as `pre_existing`. Its orphaned pytest children were killed
   too (killing the `test_delta` parent does not kill them on Windows) and the checkout restored again.
4. **Fix merged first**: `chore/test-delta-pythonpath` `7072c00b` → main `ee16002e`. One line
   (`os.pathsep.join([td] + [v for v in ... if v])`) and one regression test. Proof: the fixed script
   runs `research_workflow/tests/test_train_provenance_attestation.py` 31/31; the unfixed one on
   68e0722a fails 16/31 on the same scope. Merged without a broad gate because the broad gate is what it
   repairs; stated plainly.
5. **Attempt 3 (09:56, main ee16002e, serial, uncontended, clean environment)** — the run this report
   records.

## What moved in the known set, and why

| change | node | why |
|---|---|---|
| **+1 added** | `scripts/tests/test_session_efficiency.py::test_test_delta_classifies_against_committed_baseline` | expects the automatic environmental class that Wave 2 (`e2e58fbf`) deliberately removed; fails on clean main 68e0722a and ee16002e; a stale test of the old contract, not a regression of anything this packet touched |
| 0 removed | — | every one of the 63 legacy entries failed again with the same node and was re-attested with its full message, outcome and per-entry scope |
| **not moved: F1 / F2** | `test_stage3_integration::test_stage3_model_c_long_short_routing`, `test_runtime_bindings::test_episode_study_is_provider_host_mode_and_all_features_bind` | the packet expected them to surface as new; they did not, because the canonical checkout holds the git-ignored `train_fitted_models.joblib` and both pass there. They are `NEW_FAILURE` in any worktree without the artifact (they were in the Session 3 surface run). That is the corrected classifier behaving as specified: a missing file is never automatically environmental. Worktree provisioning (copying the ignored artifact) remains the operator's step |

Schema 1 → 2: every entry now carries `message`, `outcome`, `scopes`; the file records `environment`
(Python 3.13.7, Windows 11, pytest 9.0.2, numpy 2.3.3, pandas 2.3.3, psutil 7.1.3, pandas_market_calendars
5.4.0, nautilus_trader 1.230.0) and `platform_commit` = the exact main commit. Scopes widened from four to
five (`research/analysis/tests` added, 49 tests, no failures).

## Duration

**83m 14s** (4,994 s, process start 09:56:11 to card 11:19:25), five scopes, 2,389 tests, serial and
uncontended on NUCBOX_K10. Not comparable with the recorded 74m41s (two scopes, 2,088 tests): the three
added scopes account for about 300 tests, and the Wave 1 figure was measured while a partition replay ran
on the same host. Recorded in `docs/WORKFLOW_REFERENCE_FACTS.md`.

## Facts for `docs/WORKFLOW_REFERENCE_FACTS.md`

Written to `docs/WORKFLOW_REFERENCE_FACTS.md` ("Baseline re-record under the enforced classifier
(2026-09-08)") in the same commit as the baseline: command, commit, duration, counts, what moved, the
discarded attempts and the `test_delta` defect they exposed.
