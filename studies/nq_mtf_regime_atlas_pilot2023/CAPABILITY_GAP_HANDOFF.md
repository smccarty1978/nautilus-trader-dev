# CAPABILITY_GAP_HANDOFF — nq_mtf_regime_atlas_pilot2023

Generated 2026-09-10T23:19:25.705892+00:00 on platform commit `4f37a50796a69ae7f54bf59a8d45185601838341`, branch `study/nq_mtf_regime_atlas_pilot2023`.

**STUDY OWNER: STOP. Do not implement this capability in the study session. Commit this file and END THE SESSION.**

## Research question

# NQ MULTI-TIMEFRAME REGIME PATH ATLAS — ONE-YEAR PILOT (2023)
## SUPERVISED PLATFORM V2 RESEARCH CONTRACT — DESCRIPTIVE STUDY

This is the DISPOSABLE PILOT called for in the full contract's §16. It is the
same contract with one narrowing: the chronology is 2023 only (§10 below).
Its purpose is to see the row counts and prove the composition compiles,
seals and analyses end to end. It is not the deliverable; the six-year study
`nq_mtf_regime_atlas` is. Close it and delete it.

============================================================
0. WHAT THIS STUDY IS
============================================================
DESCRIPTIVE ORIENTATION. Not falsification.

There is no hypothesis, no prediction direction, and no kill criteria.
The deliverable is a map of how NQ regimes move, at nine timeframes,
with their MFE/MAE paths, normalized to ATR.

Nothing found here is a finding. Anything that looks like edge becomes
a hypothesis for a separate study with a clean test on prohibited data.
State this in the closure.

    Instrument:   NQ only (assumption — say so if ES was intended)
    Sessions:     ETH and RTH, both, distinguished not merged

============================================================
1. RESEARCH QUESTIONS
============================================================
All descriptive. Each must resolve to a declared output in §8.

Q1  For flips that end positive, what is mean MFE in ATR versus mean
    realized outcome in ATR? Same for flips that end negative.
    (The gap between the two is giveback.)

Q2  How fast do losers resolve, relative to winners?
    Distribution of time-to-resolution by outcome.

Q3  Is the early path different between eventual winners and eventual
    losers? Compare MFE/MAE at fixed early offsets.

Q4  Is the early path different when the flip is AGAINST the prevailing
    higher-timeframe regime versus WITH it?

Q5  Does a 1m flip behave differently when aligned with 5m / 15m / 1h
    than when not? Broken out by which higher timeframes agree.

============================================================
2. AUTHORITIES TO RESOLVE
============================================================
Resolve from governed repository authority; do not infer from this
document if registered artifacts specify more precisely:

    regime tracker identity and parameters (the accepted EMA band
        agreement definition, sticky until opposite conditions met)
    ATR identity (Wilder 14 unless authority says otherwise)
    session/calendar authority (Globex, RTH boundaries)
    completed-bar and ts_init semantics
    Databento close-time alignment shifts

Dataset: NQ 1s Globex V2. Verify through DatasetSpec/registry.
Do not substitute V0 or legacy catalogs.

============================================================
3. TIMEFRAMES
============================================================
    5s, 30s, 1m, 3m, 5m, 15m, 30m, 1h, 4h

Nine timeframes, the SAME regime definition on each. Do not vary the
tracker per timeframe.

5s is included deliberately. Recorded fact, not an objection: 5s EMA
regime flips are a closed line for entries. Here 5s serves as a context
and volume-of-observation timeframe, not as a candidate entry.

Host-derive completed higher-timeframe bars. Only completed bars are
visible at any decision epoch.

============================================================
4. POPULATION
============================================================
One row per regime flip, per timeframe, ETH and RTH.

    decision epoch T = the close of the bar on which the flip is
                       confirmed for that timeframe
    direction        = the new regime's direction
    identity         = timeframe + regime start

No filtering. No minimum age, no MFE floor, no retention gate. This is
a census, not a qualified population. Every flip is a row.

============================================================
5. NORMALIZATION — TWO DENOMINATORS
============================================================
PRIMARY: the flip's OWN timeframe ATR at T.
Every distance, MFE, MAE and outcome for a 5m flip is expressed in 5m
ATR.

SECONDARY: the same quantities in 1h ATR at T.

Both are required. "This 1m regime ran 3x its own ATR" and "it ran 0.2x
the 1h ATR" are different facts, and the second is closer to what
alignment is about.

Also record raw ATR values so the denominators are auditable.

============================================================
6. OUTCOME AND PATH
============================================================
OUTCOME
    Realized return from the flip bar CLOSE to the next flip bar CLOSE
    on that same timeframe, signed by direction, in own-timeframe ATR.

    Bar close, not threshold level. This is a standing standard.

    Sign determines winner/loser for Q1.

PATH — fixed offsets, in bars OF THAT TIMEFRAME
    Record MFE and MAE in ATR at offsets: 1, 2, 3, 5, 10, 20, and
    terminal (next flip).

    Fixed offsets are what make Q3 and Q4 answerable. Terminal MFE/MAE
    alone cannot distinguish early path shape.

ORDERING — required, not optional
    time to MFE
    time to MAE
    which occurred FIRST
    MFE retained at regime end (giveback ratio)
    MAE-before-MFE flag

    The program's most complete prior falsification was correct
    geometry with a large dollar loss from giveback. Path ordering is
    the first-class question, not a diagnostic.

CENSORING
    Regimes still open at session end, at a data gap, or at the
    chronology boundary are CENSORED and flagged, never treated as
    resolved. Declare the rule explicitly.

============================================================
7. FEATURES AT T
============================================================
All available at the decision epoch. No reconstruction after the fact.

ALIGNMENT — this is the study, record it, do not derive it later
    For each of the other eight timeframes, at T:
        current regime direction
        current regime age
        agrees / disagrees with the flipping timeframe
    Age matters as much as direction. A 1h regime four minutes old is
    not the same as one six hours old.

VOLATILITY CONTEXT
    ATR at T, per timeframe
    ATR percentile vs trailing 20-day, per timeframe

SESSION AND TIME
    session bucket (Asia / London / NY pre / open / lunch / PM / close)
    minutes from RTH open, minutes to RTH close
    day of week
    ETH / RTH flag

VOLUME
    relative volume vs same-time-of-day trailing 20-day baseline
    flip-bar volume vs prior N bars
    Raw volume is not comparable across 2020-2025. Do not use it alone.

VWAP
    distance from session VWAP in ATR
    side of VWAP
    VWAP slope

PRIOR STATE
    prior regime on the same timeframe: outcome, efficiency, MFE, duration
    flip count so far in session on that timeframe
    overnight gap in ATR
    distance to prior session high / low in ATR

============================================================
8. REQUIRED OUTPUTS
============================================================
Declare EVERY table here. The deliverable-producer gate fails at compile
if any has no producer — which is the point. Discover a missing
analysis op in seconds, not after a multi-hour collection.

    T1  Q1: mean/median MFE in ATR vs mean/median realized outcome in
        ATR, split by outcome sign, by timeframe.
    T2  Q2: time-to-resolution distribution by outcome sign, by
        timeframe.
    T3  Q3: MFE/MAE at offsets 1,2,3,5,10,20 by eventual outcome sign,
        by timeframe.
    T4  Q4: T3 broken out by with / against the prevailing higher
        timeframe.
    T5  Q5: 1m flip outcome and path by alignment state across
        5m/15m/1h — each combination reported separately.
    T6  Population census: flips per timeframe per year, censored
        counts, ETH vs RTH.
    T7  Giveback: MFE-retained distribution by timeframe and outcome.
    T8  Session-bucket breakdown of T1 and T2.

If a required statistic has no registered producer, route the typed
analysis capability gap. Do not create study-local analysis Python.

============================================================
9. STATISTICAL REQUIREMENT — NOT OPTIONAL
============================================================
Overlapping regimes across nine timeframes are NOT independent
observations. The same price move appears in every timeframe's rows.

Every mean or difference reported must carry an uncertainty estimate
CLUSTERED BY SESSION DAY. Report the cluster count alongside the row
count.

This program has already corrected a t of ~14 down to ~1.39 from
exactly this error. Naive per-observation statistics on this dataset
will be wrong by a large factor.

============================================================
10. CHRONOLOGY
============================================================
    EXPLORE:     2023 only
    NOT OPENED BY THIS PILOT: 2020, 2021, 2022, 2024, 2025
    PROHIBITED:  2026

This is the pilot narrowing of the full contract's chronology. 2026 must
remain untouched -- not collected, not read, not summarized. The other
EXPLORE years of the full contract are simply not run here; the pilot does
not change their authority, and the six-year study opens them.

============================================================
11. NO ECONOMICS, NO MODELS
============================================================
Do NOT:
    fit any model
    simulate entries or exits
    optimize brackets, stops or targets
    model fills, slippage or costs
    derive thresholds
    declare edge

This study ends at description.

============================================================
12. INTEGRITY
============================================================
    causal availability of every feature at T
    completed-bar semantics on every derived timeframe
    Databento close-time shifts applied and evidenced
    no all-null feature columns
    feature variance checks
    censoring flags present and correct
    unique regime counts distinct from row counts
    2026 unopened, provable

If a timeframe legitimately cannot supply a feature, report it and fail
per canonical null semantics. Do not impute.

============================================================
13. AUTONOMY
============================================================
on_capability_gap:
    MISSING_CAPABILITY / UNSUPPORTED_COMPOSITION
        -> supervisor launches a fresh capability worker
        -> generic chore branch, targeted tests, governed promotion
        -> recompile, reseal, resume
    A new feature definition follows the promotion path: golden values,
    causal availability, determinism. It does NOT need a sealed study.
    INVALID_PARAMETERIZATION
        -> fresh study-design worker repairs the declarative spec
    semantics already resolved by this contract
        -> use this contract, do not ask again
deterministic_defect:      auto-repair, bounded
audit_fixable_defect:      auto-repair, regenerate packet, bounded re-audit
platform_merge:            approval_required
protected_data:            never broaden chronology authority
long_jobs:                 detached, no AI worker waiting

Note for the supervisor: a blocked contract audit currently has no
re-audit route and will loop to escalation. The manual path is an
independent pass, ingest, re-run through seal, resume.

============================================================
14. ASK THE OWNER ONLY FOR
============================================================
    SCIENTIFIC_SEMANTIC_DECISION_REQUIRED not resolved above
    PROTECTED_DATA_AUTHORIZATION beyond this contract
    CAUSAL_DEFINITION_AMBIGUOUS
    RESEARCH_CONTRACT_CONFLICT
    a required output in §8 with no producer and no reasonable
        capability route
    repeated escalation after bounded repairs

Do NOT ask about: implementation defects, capability details, test
failures, stale seals, audit regeneration, merge mechanics, long-job
completion, or semantics this contract already fixed.

============================================================
15. CLOSURE
============================================================
NQ_MTF_REGIME_ATLAS_PILOT_CARD

    dataset / digest:
    regime tracker identity:
    timeframes collected:
    rows per timeframe:
    unique regimes per timeframe:
    cluster (session-day) count:
    censored fraction per timeframe:
    ETH / RTH split:
    T1-T8 produced:            yes / no per table
    years accessed:            2023 ONLY
    2026 accessed:             NO
    models fitted:             NONE
    economics simulated:       NONE

TERMINAL DECISION
    DESCRIPTIVE_ATLAS_COMPLETE  (pilot scope: 2023)

    Followed by: nothing in this atlas is a finding. Candidate
    hypotheses, if any, are listed for separate falsification studies
    against 2026.

============================================================
16. OPERATOR SEQUENCE
============================================================
This IS the pilot. When it reaches STUDY_CLOSED, read the T6 census
first: rows and unique regimes per timeframe for one year, censored
fraction, ETH vs RTH. Nine timeframes with seven path offsets across ETH
may be unwieldy; that is what this run is for. Report the counts, then
start the six-year study `nq_mtf_regime_atlas` from
`docs/questions/nq_mtf_regime_atlas.md`.

Any capability added to make this pilot compile and seal is added to the
platform once and is already present for the full study.

============================================================
APPENDIX A — RECONNAISSANCE (added by the operator, non-authoritative)
============================================================
Facts established against `main` at 14e30315 before the study was
started. They are evidence, not authority: verify each at compile.
Where this appendix and §0-§16 disagree, §0-§16 wins.

A1. TIMEFRAMES ARE EXPRESSIBLE. `research_workflow/grammar/compiler.py`
    derives any timeframe that is an integer multiple of a declared
    external stream (`aggregation: complete_bucket`). `NQ_1S_V2_GLOBEX`
    declares external 1s and 1m, so 5s and 30s derive from 1s and
    3m/15m/30m/1h/4h derive from 1m. `duration_seconds` accepts the
    `s|m|h` units, so `1h` and `4h` parse. The seed capability index
    listing only `.1s/.1m/.5m` streams is a seed list, not a limit.
    Each non-1m/5m timeframe still needs a regime-bar source in context
    (a `tracker.regime.dual_ema` on that timeframe, or a
    `tracker.regime_bar.calendar_bucket`) or the compiler raises the
    "feature surface needs a <tf> regime-bar source" gap.

A2. REGISTERED AND USABLE for §7: `feature.regime_direction`,
    `feature.regime_age`, `feature.regime_alignment`,
    `feature.regime_efficiency`, `feature.regime_mfe_atr`,
    `feature.relative_volume`, `feature.session_membership`,
    `feature.session_elapsed`,
    `feature.distance_to_completed_range_high_atr` /
    `..._low_atr`, `feature.range_atr`, `feature.price_change_atr`.
    145 feature ids are registered; `research cap search` is the
    authority, not this list.

A3. NOT REGISTERED anywhere in `features/` (grep returned nothing):
      - VWAP, in any form. §7's three VWAP features have no provider.
      - ATR percentile vs a trailing 20-day window. No percentile
        feature exists.
    Both are MISSING_CAPABILITY on the feature-definition path
    (`features/definitions/canonical/<name>.py` + golden evidence +
    `research feature verify|promote`, per `WORKFLOW.md` §E). This is
    the governed route and it does NOT need a sealed study.

A4. THE ANALYSIS SURFACE IS THE REAL GAP. Nine analysis ops are
    registered: `analysis.path.anchored_offsets`,
    `analysis.incidence.cumulative`, `analysis.decomposition.buckets`,
    `analysis.anchor.first_threshold_crossing`,
    `analysis.control.cell_matched`, `analysis.classify.precedence`,
    `analysis.metric.tail_lift`, `analysis.gate.population_parity`,
    `analysis.gate.arm_delta_integrity`.
      - T3 / T4 map onto `analysis.path.anchored_offsets`.
      - T2 maps partly onto `analysis.incidence.cumulative`.
      - T1, T6, T7, T8 have NO generic grouped-summary producer
        (mean / median / quantiles by group).
      - §9 has NO producer at all: `grep -rn cluster research/analysis/`
        returns nothing. There is no cluster-robust standard error
        anywhere in the analysis harness, and §9 makes one mandatory on
        every reported mean and difference.
    Expect the compile-time deliverable-producer gate to fail on T1,
    T6, T7, T8 and on §9, and expect the capability flow to add one
    grouped-descriptive op and one session-day-clustered uncertainty op
    before this study can seal. §13 authorizes exactly that; §8 says
    route it as a typed analysis capability gap rather than writing
    study-local Python.

A5. PLATFORM FREEZE. The platform is under a declared freeze after
    `f136a469` (2026-09-10): no platform work until three real studies
    have run. This study is one of those real studies and §13
    authorizes capability workers under `platform_merge:
    approval_required`, so the freeze does not block it — but every
    capability merge here is an owner-approved exception, not routine.

## Gaps (compiler evidence)

- `AMBIGUOUS_TEMPORAL_SEMANTICS` at `outcome.session`: session-end censoring needs a session with a close; declare outcome.session (e.g. RTH) or session_end: ignore

## Requested semantics (from study.yaml at each gap)

- `outcome.session` -> `"session-end censoring needs a session with a close; declare outcome.session (e.g. RTH) or session_end: ignore"`

## Affected YAML fields

- outcome.session

## Existing nearest capabilities

- none named by the compiler; use `research cap search`

## Scientific decisions already resolved

```json
{
  "terminal_decisions": {
    "study_class": "DESCRIPTIVE ORIENTATION, not falsification (contract section 0). No hypothesis, no prediction direction, no kill criteria. Nothing found here is a finding; any apparent edge becomes a hypothesis for a separate falsification study on prohibited data. model: none, and no economics are simulated (contract section 11).\n",
    "instrument": "NQ only (contract section 0, stated assumption; ES is not collected).",
    "sessions": "ETH and RTH both, distinguished not merged. population.session: ALL; the ETH/RTH flag is feature.session_membership(session=RTH), never a filter.\n",
    "population": "Census, not a qualified population (contract section 4). NO population.qualify: no minimum age, no MFE floor, no retention gate. One row per regime flip, per timeframe; identity is (timeframe, regime start); direction is the NEW regime's direction; the decision epoch T is the close of the bar on which that timeframe's flip is confirmed.\n",
    "normalization": "PRIMARY denominator is the flip's OWN timeframe ATR at T; SECONDARY is the 1h ATR at T (contract section 5). Both are required. The raw ATR of all nine timeframes is recorded as metadata (atr_5s .. atr_4h) so both denominators are auditable.\n",
    "outcome": "Realized return from the flip bar CLOSE to the NEXT flip bar CLOSE on the same timeframe, signed by direction, in own-timeframe ATR. Bar close, not a threshold level. Encoded as outcome.kind: label with event: <flipping tracker>.flipped and entry_reference: decision_close.\n",
    "censoring_rule": "A regime still open at the session end, at a data gap, or at the chronology boundary is CENSORED and flagged, never treated as resolved (contract section 6). Encoded as session_end: censor plus max_gap: 300s. outcome.horizon: 24h is an OBSERVATION BOUND ONLY -- it is longer than any Globex trading day, and SESSION_END precedes HORIZON_EXPIRY in the compiled resolution_precedence, so the session close is what censors. The horizon is NOT a scientific truncation of the terminal. This encoding is currently REFUSED by the compiler (gap_inventory.G2) and has NOT been silently traded for session_end: ignore.\n",
    "path_ordering": "time-to-MFE, time-to-MAE, which occurred FIRST, MFE retained at regime end (giveback ratio) and the MAE-before-MFE flag are FIRST-CLASS, not diagnostics (contract section 6). They are read off the per-bar checkpoint sequence of the running excursion columns (mfe_atr_<tf> / mae_atr_<tf> / pnl_atr_<tf> / retained_<tf>), which is causal at every checkpoint; they are NOT reconstructed from a terminal-only summary.\n",
    "path_offsets": "MFE and MAE in ATR at offsets 1, 2, 3, 5, 10, 20 bars OF THE FLIPPING TIMEFRAME plus terminal (next flip), via analysis.path.anchored_offsets over the per-bar checkpoint rows. The per-timeframe checkpoint cadence is part of gap_inventory.G1; population.cadence: completed_1s in study.yaml is a compile placeholder, NOT the declared science, and must not survive into a sealed study.\n",
    "chronology": "EXPLORE 2023 only. 2026 PROHIBITED -- not collected, not read, not summarized. 2020 / 2021 / 2022 / 2024 / 2025 are NOT declared prohibited: they are simply not partitions of this pilot. Declaring 2022 prohibited would conflict with chronology.warmup.days_before_partition (5 calendar days of lead-in immediately before 2023-01-01 fall in 2022), and the pilot does not change those years' authority for the six-year study nq_mtf_regime_atlas.\n",
    "statistics": "Overlapping regimes across nine timeframes are NOT independent observations (contract section 9). Every mean or difference reported must carry an uncertainty estimate CLUSTERED BY SESSION DAY, with the cluster count reported alongside the row count. This is mandatory, not optional, and no registered analysis op provides it (gap_inventory.G5).\n",
    "terminal_label": "DESCRIPTIVE_ATLAS_COMPLETE (pilot scope 2023)."
  },
  "autonomy_decisions": {
    "on_capability_gap": "stop_and_handoff",
    "platform_change_required": "chore_branch_and_fresh_session",
    "deterministic_defect": "auto_fix",
    "calendar_reference_parity": "common_interval_exact",
    "frozen_parent_model": "rescore_if_authenticated",
    "protected_period": "never_expand_authority",
    "platform_merge": "approval_required"
  }
}
```

## Prohibited for the study owner

- modifying research_workflow/ (grammar, compiler, host, controller, outcomes, provider bindings)
- modifying features/ or the capability registry seeds from the study branch
- building the missing capability inside the study session
- patching around the gap with study Python
- continuing to accumulate context after this handoff: END THE SESSION

## Suggested platform files (hint)

- research_workflow/grammar/spec.py
- research_workflow/host/outcomes.py
- research_workflow/target_replay_oracle.py

## Next action

Study owner: END THIS SESSION. Do not implement. Commit study.yaml + research_decision.yaml + this handoff on the study branch first.

Capability session (fresh, short):

- python scripts/research.py ws chore claim nq_mtf_regime_atlas_pilot2023-ambiguous_temporal_semantics --paths research_workflow/grammar/spec.py research_workflow/host/outcomes.py research_workflow/target_replay_oracle.py --surface "<one line>" --as <agent>
- git worktree add "../<repo>-nq_mtf_regime_atlas_pilot2023-ambiguous_temporal_semantics" -b chore/nq_mtf_regime_atlas_pilot2023-ambiguous_temporal_semantics main
- implement ONLY the capability named above; targeted tests; research cap generate --check; audit/promotion if the capability flow requires it
- git switch main && git merge --no-ff chore/<topic>; write CAPABILITY_COMPLETE card (research study handoff --study <study> --phase A --note CAPABILITY_COMPLETE:<topic>)
- python scripts/research.py ws chore release nq_mtf_regime_atlas_pilot2023-ambiguous_temporal_semantics

Resume session (fresh):

- git -C <study worktree> merge --no-ff main
- python scripts/research.py ws claim nq_mtf_regime_atlas_pilot2023 --as <agent>
- python scripts/research.py study compile --study studies/nq_mtf_regime_atlas_pilot2023

---

## OWNER ADDENDUM (written by the Phase A study-design worker, not by the compiler)

**Read this before scoping the chore.** The compiler card above lists **one** gap. That is a
short-circuit artifact, not the size of the problem: `outcome.session` is raised inside
`_resolve_streams`, and `compile_study` returns immediately after that stage
(`research_workflow/grammar/compiler.py`, the first `if not ctx.gaps.ok`). The trackers, features,
population, outcome, analysis and deliverable stages were never reached in that run.

They were reached in two committed probe compiles at the same platform commit
(`4f37a507`), both produced with `study compile --dry-run` from copies of this study.yaml:

| evidence | scope | gaps |
|---|---|---|
| `CAPABILITY_GAP_HANDOFF.inventory.json` | compiler blocks 1-2 (trackers, features, population, outcome) | **100** |
| `CAPABILITY_GAP_HANDOFF.analysis_probe.json` | compiler block 3 (analysis, deliverables) | **6** |
| `CAPABILITY_GAP_HANDOFF.json` | the committed study.yaml, as compiled above | 1 |

Both probe cards are committed next to this file (`_work/` is gitignored, so they are not left
there). To reproduce them from the committed `study.yaml`:

- **inventory** — copy `study.yaml` to a scratch dir, change the single line `session_end: censor`
  to `session_end: ignore` (this clears G2 only, so the compile reaches blocks 1-2), then
  `python scripts/research.py study compile --study <scratch dir> --dry-run`.
- **analysis probe** — take `docs/examples/checkpoint_classifier.yaml`, set `model: none` and
  `chronology: {train: [2023], dev: [], prohibited: [2026], authorized_dates: ['2023-10-02']}`,
  graft this study's `analysis:` and `deliverables:` blocks onto it verbatim, and compile
  `--dry-run`. The borrowed earlier blocks are known-good, so only the analysis surface gaps.

**106 gaps in six categories.** `studies/nq_mtf_regime_atlas_pilot2023/research_decision.yaml`
→ `gap_inventory` is the authority; the categories are:

- **G0** multi-timeframe population fan-out — MISSING_CAPABILITY / UNSUPPORTED_COMPOSITION.
  `population:` is single-anchored; the contract needs nine simultaneous candidate streams in one
  collection. Blocks every question and every table.
- **G1** an unknown `completed_<name>` cadence raises `ValueError` out of
  `compiler.py:746` instead of returning the typed `UNAVAILABLE_STREAM` gap — and when it
  crashes, **no handoff is written at all**. Deterministic platform defect.
- **G2** the gap on the card above: `session: ALL` + `session_end: censor` is refused even on a
  calendar dataset that does define a Globex trading-day close (1636 sessions). Neither
  `outcome.session: RTH` nor `session_end: ignore` was taken, because both change the science.
- **G3** the canonical **feature** timeframe domain is `['5s','1m','5m']` only (`regime_direction`
  is `['5m']` alone; `regime_alignment` is `['1m','5m']`). Contract Appendix A1 is right about
  streams and trackers and **wrong about the feature surface**. 64 + 10 gaps.
- **G4** 18 unregistered features (VWAP ×3, ATR percentile ×9, session bucket, day of week,
  minutes-to-RTH-close, overnight gap, prior-session high/low) — confirms Appendix A3.
- **G5** the analysis surface: **one** grouped-descriptive op (produces T1/T5/T6/T7/T8) and
  **one** session-day-clustered uncertainty op (contract section 9, mandatory on every reported
  number) — confirms Appendix A4. `analysis.path.anchored_offsets` (T3/T4) and
  `analysis.incidence.cumulative` (T2) already compile cleanly with the declared parameters.

Scoping the chore to G2 alone would resolve one category per freeze cycle, which is the failure
mode `CLAUDE.md` section 5 names explicitly. Sweep G0-G5 as one set.
