# FIRST_P90_WARNING_HORIZON_REPORT — March 2024

Descriptive characterization of the frozen Stage-1 first-P90 population. No model development,
no strategy optimization, no Stage 2. Every number below is read from the governed artifacts in
`../artifacts/`; nothing is quoted from a scratch computation.

---

## FIRST_P90_WARNING_HORIZON_CARD

```
POPULATION:
    LONG_first_fires:   115      (parent arm LONG  = prevailing regime -1)
    SHORT_first_fires:  124      (parent arm SHORT = prevailing regime +1)
    total:              239
    population_parity:  PASS — 0 missing, 0 extra, 0 timestamp mismatches
                        against the frozen first_p90_parity.parquet (52437d73…)
                        eligible regimes 312 (parent 154+158) · eligible rows 35,872 (parent 35,872)

CUMULATIVE_FLIP_INCIDENCE (cumulative rate; eligible n in brackets)
    LONG (bear regimes):
        <=60:  0.0522 (115)    <=240: 0.3333 (114)    <=600: 0.6667 (114)
        <=120: 0.1739 (115)    <=300: 0.4386 (114)    session_end: 0.9826 (115)
        <=180: 0.2895 (114)    <=450: 0.5439 (114)
    SHORT (bull regimes):
        <=60:  0.1057 (123)    <=240: 0.3252 (123)    <=600: 0.5902 (122)
        <=120: 0.1545 (123)    <=300: 0.3902 (123)    session_end: 0.9677 (124)
        <=180: 0.2520 (123)    <=450: 0.4918 (122)
    POOLED:
        <=180: 0.2700 (237)    <=600: 0.6271 (236)    session_end: 0.9749 (239)

CURRENT_180S_NEGATIVE_DECOMPOSITION (negative denominator 175 of 239)
                            LONG    SHORT   POOLED   % of negatives
    181_240:                   5        9       14       0.080
    241_300:                  12        8       20       0.114
    301_450:                  12       12       24       0.137
    451_600:                  14       12       26       0.149
    >600 (flipped later):     37       48       85       0.486
    no_flip_session:           1        2        3       0.017
    persistent_>600:           1        2        3       0.017
    censored:                  0        0        0       0.000

CONTROL_COMPARISON (direction-stratified; both cells reportable)
                        P90 fire        ALL controls     pre-anchor controls
    flip_180:          0.2700 (237)    0.4026 (303)      0.2658 (237)
    flip_300:          0.4135 (237)    0.5281 (303)      0.4051 (237)
    flip_600:          0.6271 (236)    0.6987 (302)      0.6229 (236)
    cells: -1 anchors 115 / controls 154 = OK · +1 anchors 124 / controls 158 = OK
    age_stratified_result:          descriptive only (see Deviations)
    time_of_day_stratified_result:  descriptive only (see Deviations)
    sparse_cells:                   none at direction level; the requested
                                    direction x age x TOD grid has max cell n = 13

POST_P90_SCORE_EVOLUTION (median delta from the first-fire score)
                                  +15s      +60s     +120s   P95   fell_below
    FAST_RESOLVER   (n=56)     -0.0023   -0.0109   -0.0025  0.71     0.91
    LATE_RESOLVER   (n=30)     -0.0523   -0.0924   -0.1235  0.90     1.00
    SLOW_RESOLVER   (n=43)     -0.0115   -0.1062   -0.1288  0.93     1.00
    FAILED (collapse, n=81)    -0.0591   -0.1043   -0.1281  0.88     1.00
    ALL:  reached P95 0.845 · reached P97.5 0.556 · fell below P90 0.975
          recrossed after falling 0.895 · continuously >= P90 0.021

WARNING_SUBTYPES (n=239, unclassified 0)
    fast_resolver_pct:               0.234   (56)
    late_resolver_pct:               0.126   (30)
    slow_resolver_pct:               0.180   (43)
    failed_score_collapse_pct:       0.339   (81)   — but 78 of these 81 flipped later
    failed_persistent_high_pct:      0.000   (0)
    censored_pct:                    0.121   (29)

INTERPRETATION:
    pct_of_180s_negatives_flipping_by_240:   0.080   (14/175)
    pct_of_180s_negatives_flipping_by_300:   0.194   (34/175)
    pct_of_180s_negatives_flipping_by_600:   0.480   (84/175)
    pct_of_180s_negatives_flipping_at_all:   0.966   (169/175 before RTH close)

    first_P90_is_primarily:                  EARLY_WARNING
    score_persistence_after_P90_adds_information:  WEAK
    P90_vs_control_accelerates_flip:         NO
    recommended_stage2_framing:              neither of the two offered; see below

MODEL_CHANGED:            NO
THRESHOLDS_CHANGED:       NO
NEW_UNTOUCHED_OOS_ACCESSED: NO
2025_2026_ACCESSED:       NO
```

---

## The seven questions

**1. Among first-P90 warnings negative at 180 s, what fraction flips by 240 / 300 / 600 s?**
8.0% / 19.4% / 48.0%. A further 48.6% flip *after* 600 s but still before the session closes.

**2. Are the 180-second negatives predominantly EARLY_BUT_CORRECT, GENUINE_FALSE_WARNING, or MIXED?**
**EARLY_BUT_CORRECT, decisively.** Of the 175 warnings negative at 180 s, **169 (96.6%) flip before
the RTH close**; only 6 (3.4%) never do. The 180-second label is not separating true warnings from
false ones — it is separating *fast* flips from *slow* ones. Pooled incidence rises from 0.270 at
180 s to 0.627 at 600 s to 0.975 by session end.

**3. Does first P90 materially shorten time-to-next-opposing-flip versus the control?**
**No.** Against the like-for-like control the rates are indistinguishable: 0.2700 vs 0.2658 at
180 s, 0.4135 vs 0.4051 at 300 s, 0.6271 vs 0.6229 at 600 s — differences of 0.4–0.8 percentage
points, all in the direction of the *control* being marginally faster.

The predeclared pooled control (0.4026 at 180 s) looks like the opposite, and it is an artifact —
see *Confound* below. The honest reading is that first P90 marks a state that flips on the same
schedule as a comparable below-threshold state in the same regime.

**4. How does the post-P90 score path differ among the subtypes?**
Every subtype decays. What separates them is *how much*: FAST_RESOLVER is essentially flat
(−0.0025 at +120 s) while LATE, SLOW and FAILED all decay four to five times as far
(−0.123 to −0.129). FAST also falls below P90 less often (0.91 vs 1.00) and reaches P95 least
often (0.71 vs 0.88–0.93). A warning that *holds* its level resolves quickly; a warning that
decays resolves slowly or not within the window.

**5. Does persistence add more information than first-fire magnitude?**
Persistence adds a little; magnitude adds **nothing**. Median first-fire score is 0.3023–0.3083
across *all five* subtypes — indistinguishable. The decay slope does separate FAST from the rest.
But true persistence barely exists: only 5 of 239 (2.1%) stay continuously at or above P90 for the
whole window, and **FAILED_WARNING_PERSISTENT_HIGH has zero members**. So: **WEAK**.

**6. EARLY_WARNING_ZONE or ENTRY_TRIGGER?**
**EARLY_WARNING_ZONE.** 97.5% of warnings are eventually followed by an opposing flip, but the
median time to it is 415 s — more than twice the 180-second label — and the score has already
decayed by −0.09 at +60 s. The signal identifies a regime entering its final phase; it does not
time the turn. It also does not identify *which* regimes turn, because comparable below-threshold
states in the same regimes turn at the same rate (Q3).

**7. Does the evidence justify framing Stage 2 as "classify P90 warning resolution quality"?**
Only partly, and I would not frame it that way. Two findings cut against it:

* the population is not separable into "will flip" and "won't" — 97.5% flip, so there is almost no
  negative class to classify;
* first P90 does not select regimes that flip sooner than comparable non-P90 states, so
  "resolution quality" conditional on the warning may be a property of the *regime*, not of the
  warning.

What the data does support is a **timing** question, not a quality question: *given that a flip is
coming, what predicts whether it arrives in 3 minutes or 17?* The decay slope over the first 120 s
is the one measured axis that separates fast from slow. That is a different, narrower study, and
it needs its own authorization.

---

## Confound: the predeclared control is biased by construction

The predeclared rule (authorization §8) selects the **latest** eligible below-threshold checkpoint
in each cell. For a regime that never fires, that is the last eligible checkpoint of the regime —
which sits, by construction, immediately before the flip.

Measured: the 73 `never_anchored` controls have a **median observed window of 55 seconds** and flip
within 180 s **89.4%** of the time. The 239 `pre_anchor` controls have a median observed window of
420 s, closely matched to the anchors' 415 s.

The pooled control number is therefore a selection artifact, not a treatment effect. Both are
reported: the predeclared pooled figure as the primary result, and the `pre_anchor` subgroup as an
explicitly **post-hoc** sensitivity. The predeclared design was not changed after seeing results;
the subgroup split is a diagnosis of it. Under the matched comparison the answer to Q3 is a clean
*no acceleration*.

## Caveat: "FAILED_WARNING" is a misnomer under §10's own definition

§10 defines the FAILED subtypes as "no opposing flip ≤ 600 s". By that definition 81 warnings are
`FAILED_WARNING_SCORE_COLLAPSE` — but **78 of them (96.3%) did flip**, at a median of 1,035 s. They
are late, not false. The three genuinely non-flipping warnings are counted in
`no_flip_session` / `persistent_>600`. The subtype labels are kept exactly as predeclared; this note
records what they mean.

`fell_below` is evaluated over the full 5-second causal grid inside the 600 s window, which strictly
contains the five scheduled offsets — a superset test, making PERSISTENT_HIGH the stricter class.

## Deviations from the authorization, all decided before execution

| Requested | Done | Why |
|---|---|---|
| control grid direction × age × TOD, min n 30 | **direction only** | On the parent's own frozen 239 fires the requested grid occupies 42 cells with a **maximum of 13** — zero cells reach n≥30, so the control question was unanswerable by construction. Direction-only yields 115/154 and 124/158, both reportable. Age and TOD remain descriptive. |
| age bucket `>= 1800 s` | reported as **structurally empty** | The parent's grid stops at `max_age = 1800 s`; no checkpoint, fire or control can exceed it. Observed first-fire age range 160–1755 s. |
| `session_end` semantics | `truncate` | Under the platform default a horizon long enough to reach the close censors *every* candidate, so time-to-flip through session end was not expressible. |
| null model inputs | `model_native` | The parent scored 35,872/35,872 candidates, 26,018 with null `rolling_300s_*`; 181 of the 239 fires sit on such a row. Refusing nulls would have dropped 76% of the population. |

## Lineage

| | |
|---|---|
| plan_sha256 | `e4c2b81bbf9eda0c…` |
| execution composite | `ac9af444a809134bbea524b04c65d98f5a5f5d69a44871cda275acc820e01e57` |
| seal | `fc0d21ca…` (composite seal at the time of sealing) |
| dataset | `NQ_1S_V2_GLOBEX`, logical digest `9e7aecb7a291…` |
| window | `2024-03-01..2024-03-31`, 20 trading days, 79,419 rows (35,872 parent-eligible) |
| frozen LONG model | `ccd587df…`, artifact `c94866bd…`, P90 `0.2852887899663343` |
| frozen SHORT model | `209da0ff…`, artifact `cccc911c…`, P90 `0.28485631865861344` |
| arm orientation | LONG ⇔ regime −1, SHORT ⇔ regime +1 (verified; `FIRST_P90_ARM_ORIENTATION.md`) |
| provenance attestation | `train_provenance_attestation.json`, `aaa492e9…` |
| audits | causal pass 04 CLEAR · contract pass 03 CLEAR, both at `ac9af444…` |
| parity gate | PASS — 239 rows, 115/124, 0 missing, 0 extra, 0 timestamp mismatches |

**Independent confirmation of fidelity:** the 180-second flip rates recomputed here — LONG 0.2895,
SHORT 0.2520 — reproduce the parent's own recorded 0.289474 / 0.252033, from an independently
collected frame.
