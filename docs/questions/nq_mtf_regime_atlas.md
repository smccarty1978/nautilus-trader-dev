# NQ MULTI-TIMEFRAME REGIME PATH ATLAS
## SUPERVISED PLATFORM V2 RESEARCH CONTRACT — DESCRIPTIVE STUDY

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
    EXPLORE:     2020, 2021, 2022, 2023, 2024, 2025
    PROHIBITED:  2026

2026 must remain untouched — not collected, not read, not summarized.

Owner decision, recorded: only 2026 is held out. Consequence, stated
once: any hypothesis this atlas generates can be tested cleanly on 2026
only. 2020-2025 will have been looked at.

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
NQ_MTF_REGIME_ATLAS_CARD

    dataset / digest:
    regime tracker identity:
    timeframes collected:
    rows per timeframe:
    unique regimes per timeframe:
    cluster (session-day) count:
    censored fraction per timeframe:
    ETH / RTH split:
    T1-T8 produced:            yes / no per table
    2026 accessed:             NO
    models fitted:             NONE
    economics simulated:       NONE

TERMINAL DECISION
    DESCRIPTIVE_ATLAS_COMPLETE

    Followed by: nothing in this atlas is a finding. Candidate
    hypotheses, if any, are listed for separate falsification studies
    against 2026.

============================================================
16. RECOMMENDED OPERATOR SEQUENCE
============================================================
Run a ONE-YEAR PILOT first as its own disposable study — 2023, same
contract, same nine timeframes. Not for the replay time, which is now
minutes, but to see the row counts. Nine timeframes with seven path
offsets across ETH may produce something unwieldy, and twenty minutes
is a cheaper way to learn that than six years.

Then the full study.

    python scripts/research.py supervise start \
      --question nq_mtf_regime_atlas.md \
      --study-id nq_mtf_regime_atlas \
      --provider claude \
      --execute-authorized

Use the exact current CLI syntax from the repository.

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

============================================================
OWNER AMENDMENT 01 — 2026-09-10 (carried from the 2023 pilot)
============================================================
Recorded here because it was taken against the pilot and carries
forward to this six-year study on the same terms.

CENSORING IS AT THE GLOBEX TRADING-DAY CLOSE. `population.session`
stays ALL -- the census spans ETH and RTH, distinguished by
`feature.session_membership` per §0 -- and censoring is at the close of
the Globex trading day the flip belongs to: the boundary
`NQ_1S_V2_GLOBEX` already defines in its committed `sessions` reference
table (1636 session rows), and the same session-day unit §9 clusters
on. §6's censoring rule stands as written.

The grammar today admits only `RTH | ETH | ALL` as a censoring session
and refuses `session_end: censor` when the session is ALL
(`research_workflow/sessions.py`: `AllSessionTable.session_close`
returns None). Closing that is a capability under §13, not a change to
this contract.

STILL OPEN FOR THIS STUDY: the nine-timeframe population of §3 and §4
needs a nine-way population fan-out the v2 grammar does not have (gap
G0 -- `population:` is single-anchored). The pilot was descoped to a
single 1m anchor with the other eight timeframes as alignment context;
this study's §3/§4 are NOT amended, and G0 is reassessed with the
completed pilot behind it.
