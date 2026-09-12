# The test-failure baseline can never match, so `act only on NEW_FAILURE` does not work

    status:   RECORDED, NOT FIXED
    found by: the G7 chore session, 2026-09-11, after a 211-minute two-scope run
              produced zero usable classification
    surface:  scripts/test_delta.py (baseline_issues, line 73-82),
              config/test_failure_baseline.json, WORKFLOW.md §N.3 commit gate

## What happened

`python scripts/test_delta.py research_workflow/tests scripts/tests` ran 2258 tests in
**211m29s** and returned:

    "counts": {"NEW_FAILURE": 61, "KNOWN_BASELINE_FAILURE": 0, ...}
    "baseline_commit": "c480d8af...", "head": "3fb846b4", "baseline_issues": 1
    every one of the 61: "reason": "BASELINE_COMMIT_MISMATCH"

Zero of the 61 were classified. The gate the workflow prescribes — "act only on
`NEW_FAILURE`" — had nothing to act on and nothing to dismiss.

## The mechanism, and why it is not a usage error

`baseline_issues()` compares `baseline["platform_commit"]` against
**`merge-base HEAD main`**:

    reference = _git(['merge-base', 'HEAD', 'main']) if reference is None else reference
    if not reference or baseline.get('platform_commit') != reference:
        issues.append('BASELINE_COMMIT_MISMATCH')

On a chore branch cut from `main`, that merge-base is the branch point. On `main` itself
it is `HEAD`. Either way it names **one specific commit**, so the baseline is compatible
with exactly one repository state and goes stale on the next commit to `main`.

The current baseline was **stale the moment it landed**. It was committed *as* `451836f8`
but records `platform_commit: c480d8af` — `451836f8`'s parent, the commit the suite was
actually run against. Those can never be the same commit when the run's output is itself
committed. Checked on clean `main`, with no tests run at all:

    $ python scripts/test_delta.py --check-baseline research_workflow/tests
    {"STATUS": "BASELINE_INCOMPATIBLE", "issues": ["BASELINE_COMMIT_MISMATCH"], ...}

So this is not "the chore branch moved on". Classification has been unavailable on `main`
since `451836f8`, for every scope, for every agent.

## Cost already paid

This is the second recorded instance of the same failure. The `451836f8` re-record exists
*because* of the first one — its own commit message says "reference moved from ee16002e
(BASELINE_COMMIT_MISMATCH made every known failure NEW)". The re-record fixed that
instance and reintroduced the same condition, because the mechanism was never addressed.

The 61 failures were classified by hand for the G7 merge: 58 are baseline entries, 3 are
outside it, and all 3 pass on `main` and fail in a fresh worktree on one untracked
artifact (`.../clean_maturity_flip_model_rolling_productivity/artifacts/train_fitted_models.joblib`,
1.27 MB, untracked, present only in the main worktree). A set difference against
`config/test_failure_baseline.json` took seconds and gave the answer the 211-minute run
was supposed to give.

## What a fix has to decide

- **Anchor.** The reference cannot be a single commit that the baseline's own commit
  invalidates. Candidates: record the commit that *contains* the baseline (write the file,
  then stamp it with its own commit sha in a follow-up, or stamp at commit time via a
  hook); or anchor on a content hash of the tested tree rather than a commit; or treat the
  baseline as valid until explicitly invalidated and report drift as a warning, not as a
  blanket reclassification.
- **Failure mode.** Reclassifying every known failure as `NEW_FAILURE` on an anchor
  mismatch is the worst available default: it converts a 211-minute run into no
  information while *looking* like 61 regressions. `BASELINE_INCOMPATIBLE` should refuse
  before spending the three hours, or classify on the recorded node ids and mark the card
  `ANCHOR_STALE`.
- **Scope.** `--check-baseline` already detects this in under a second. Nothing calls it
  before a long run.

## Interim rule for agents

Run `python scripts/test_delta.py --check-baseline <scope>` **before** starting a broad
run. If it returns `BASELINE_INCOMPATIBLE`, the run will not classify: either re-record
deliberately on clean `main` first, or plan to diff the observed failure set against
`config/test_failure_baseline.json["expected_failures"]` by hand and verify anything
outside it against `main` in a second worktree.
