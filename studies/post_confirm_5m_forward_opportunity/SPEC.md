# Post-Confirmation 5m Context × Forward Opportunity — Frozen Specification

**Study:** `post_confirm_5m_forward_opportunity` · **Frozen:** 2026-08-13, before implementation.
**Branch:** `study/post_confirm_5m_forward_opportunity`
**Predecessors:** `studies/p90_5m_regime_context/` (verdict M2), `studies/post_confirm_forward_opportunity/` (verdict E)
**Population:** the frozen **4,656** measurable confirmed P90 trades · 2021–2025 · **2026 sealed**

---

## 0. The narrow question

`p90_5m_regime_context` (M2) found a thin post-confirmation difference:
WITH_5M confirmers beat AGAINST_5M confirmers by +0.33 ATR terminal return
and +5.6pp on P(MFE≥3ATR). It said nothing about *when* that extra
opportunity is realized. `post_confirm_forward_opportunity` (E) built and
validated a complete forward-path map from confirmation for this exact
population, but never conditioned it on 5m regime alignment.

> After a P90 trade reaches accepted 1m confirmation, does 5-minute regime
> alignment (WITH_5M vs AGAINST_5M **at confirmation**) predict WHEN the
> remaining favorable opportunity is realized — not just how much?

This is **descriptive only**. No exit policy, no optimization, no
deployable rule. Do not repeat M2 (entry selection is already closed) or E
(the unconditioned forward map is already closed). This study's only new
axis is conditioning the already-built map on 5m alignment.

**Do not center this study on 5m transitions.** M2 already showed actual 5m
state transitions between P90 and confirmation are rare (WITH→AGAINST n=9,
AGAINST→WITH n=6). The primary comparison is WITH_5M_AT_CONFIRM vs.
AGAINST_5M_AT_CONFIRM among already-confirmed trades — both a
transition-inclusive definition (**629/4,027** — corrected, see §4 Phase 0's
disclosure note) and a stable-state-only definition (623/4,018, excluding
the two tiny transition cells) are reported side by side (§4, Phase 0), and
this study must show conclusions are unchanged between them, not merely
assert it.

---

## 1. Inherited verbatim — NOT rebuilt

| Item | Source | Causal status |
|---|---|---|
| P90 population, FULL/Walk-A lifecycle economics | `armed_fade_score_path_progression/results/armed_regime_score_paths.parquet` | accepted; 8,950 arms |
| 5m WITH/AGAINST classification at P90 and at confirmation | `p90_5m_regime_context/results/p90_classification.parquet` | accepted, parity-tested engine, M2 verdict |
| Causal 5m regime engine | `p90_5m_regime_context/implementation/regime_5m.py::Regime5m` | audited clean, reused unchanged (new call site only, §3) |
| Forward-opportunity observation grid (dense, confirm+15s..confirm+600s, 15s steps) | `post_confirm_forward_opportunity/results/observation_panel.parquet` | accepted; 14+1 validation gates passed; verdict E |
| Dual-track (stop-live / unconstrained) causal contract | `post_confirm_forward_opportunity/SPEC.md` §5 (D1–D9) | accepted; inherited unchanged, see §3 |

**Verified, not assumed:** `observation_panel.parquet`'s 4,656 distinct
`regime_id` values are **identical** (100% overlap, 0 mismatches either
direction) to `p90_classification.parquet`'s `with_5m_at_confirm`-non-null
population. This study performs **no trade-lifecycle simulation** — it is a
join and stratified aggregation of two already-closed, already-audited
artifacts, plus exactly two new pieces of logic: (a) 5m regime age/state **at
confirmation** (§3), and (b) the opportunity-capture time-to-X%-realized scan
(§4, Phase 6).

### 1.1 Reused columns, by source

`armed_regime_score_paths.parquet` (by `regime_id`): `side, direction,
entry_year, arm_score, walk_a_confirm_ns` (time zero, §2), `walk_a_seconds_to_confirm,
walk_a_mae_to_confirm_atr, walk_a_mfe_to_confirm_atr` (= `MFE_CONFIRM`
baseline — the panel's own dense grid starts at confirm+15s, has no offset=0
row), `walk_a_return_at_confirm_atr, regime_age_at_arm_s` (1m regime age —
**at P90 only**; no at-confirmation 1m-age source exists in this repo and
building a new engine for a secondary diagnostic field is out of scope,
disclosed in every output that carries it).

`p90_classification.parquet` (by `regime_id`): `with_5m_at_p90,
with_5m_at_confirm`.

`observation_panel.parquet` (by `regime_id`, further keyed by `offset_s`):
`offset_s` (dense grid is always `dense=True` in this file — the sparse
+900..2400s extension lives in a separate, never-pooled `extended_horizon.parquet`
which this study does not read), `alive_stop_live`, `return_from_entry_atr,
return_since_confirm_atr` (Phase 3), `running_mfe_from_entry_atr,
running_mfe_since_confirm_atr` (**is** Phase 4's incremental MFE, verbatim),
`running_mae_from_entry_atr, drawdown_from_running_max_atr` (**is** Phase 9's
giveback, verbatim), `n_new_favorable_extremes_since_confirm,
another_favorable_extreme` (Phase 7), `race_<fav>_before_<adv>` /
`race_<fav>_before_<adv>_ambiguous` (10 frozen pairs, Phase 8 — **note the
direction**: these resolve TRUE when the *favorable* level is touched first;
Phase 8 wants the *adverse-first* framing, computed as the complement, §4),
`eventual_max_mfe_atr, runner_bucket` (`<1/1-2/2-3/>=3`, matches Phase 11's
scheme verbatim), `cv_stop_live_atr, cv_unconstrained_atr` (**is** Phase 10's
continuation value, verbatim), `trade_nat_net_atr, trade_nat_giveback_atr`
(trade-level constants, terminal return / terminal giveback), `entry_year,
side` (also natively present on the panel, redundant with the arm table,
used for Phase 13 joins directly).

---

## 2. Anchor — time zero is causal confirmation

Time zero is `walk_a_confirm_ns` for every forward clock in this study.
**Never** the P90 arm, the P90 fill, a 5m bar close after confirmation, or a
future 5m flip. This is inherited unchanged from `post_confirm_forward_opportunity`'s
D3 decision instant.

---

## 3. The one new causal computation — 5m state at confirmation

`p90_classification.parquet` stores 5m regime age **at the P90 arm**
(`regime_age_s_at_p90`), not at confirmation. This study needs the
at-confirmation value. Computed by loading `Regime5m` (already built,
parity-tested on `p90_5m_regime_context`) and calling, at `walk_a_confirm_ns`
instead of `arm_top10_ns`:

```text
regime_age_s_at_confirm     = Regime5m.age_seconds_at(walk_a_confirm_ns)
regime_age_bars_at_confirm  = Regime5m.age_bars_at(walk_a_confirm_ns)
```

("Seconds since the most recent causal 5m flip" is the same quantity as
`regime_age_s_at_confirm` under this engine's semantics — one column serves
both phrasings, exactly as `regime_age_s_at_p90` did in the predecessor.) No
new engine code: three existing method calls at a new timestamp. The causal
guarantee (`close_ts <= walk_a_confirm_ns`, i.e. `state_at`/`age_*` never
resolve a flip after the decision instant) is inherited from the
already-parity-tested `Regime5m.state_at` family and re-verified at this new
call site by `tests/test_join_causality.py`.

**Uninitialized-state disclosure.** `age_seconds_at`/`age_bars_at` return
`NaN`/`-1` when no 5m flip has occurred before `t_ns` (inherited unchanged
from `regime_5m.py`, same convention `regime_age_s_at_p90` already used).
Low-probability at confirmation — P90 arms occur well after the 5m engine's
warmup — but not asserted impossible; any such row is retained (not
dropped) and disclosed in `results/confirmation_state.parquet` as-is, never
imputed.

### 3.1 The audit items

| # | Item | Enforced by |
|---|---|---|
| 1 | Time zero is causal confirmation | every landmark table keyed off `walk_a_confirm_ns`; gate V-ANCHOR |
| 2 | 5m state uses only the latest completed 5m state available at confirmation | `Regime5m.age_seconds_at(walk_a_confirm_ns)` structurally bounded; gate V-CAUSAL |
| 3 | No future MFE / future 5m flip / terminal return / future survival enters causal classification | Phase 0/1's grouping variables (`with_5m_at_p90`, `with_5m_at_confirm`) are both confirmation-time-or-earlier; gate V-NOFUTURE |
| 4 | Remaining MFE, future-new-extreme, and MFE-quality-bucket fields are explicitly LABEL_ONLY | Phase 5/6/7/11 output columns flagged in the manifest (§7); gate V-LABEL. **LABEL_ONLY means: never used as a CAUSAL GROUPING KEY** (i.e. never gates the WITH/AGAINST classification itself, never filters which trades enter a table). It does **not** forbid using a retrospective field as a **descriptive stratification axis reported as an outcome cross-tab** — that is Phase 11's entire purpose (bucket eventual MFE via the trade-level `runner_bucket`, then report WITH/AGAINST *within* each bucket). Gate V-LABEL checks the former (retrospective field driving `with_5m_at_p90`/`with_5m_at_confirm` or any row-inclusion filter), never the latter. |
| 5 | Primary landmark tables do not silently condition on survival | Phase 2/3 report `n_alive`/`terminal`/`attrition_pct` against the constant denominator at every offset; gate V-SURVIVAL |
| 6 | Matching uses confirmation-time variables only | Phase 12 stratum columns sourced exclusively from the Phase-1 confirmation-state frame; gate V-MATCH |
| 7 | 2026 remains sealed | `max(entry_year) < 2026` on every output; gate V-SEALED |
| 8 | Reproduce predecessor transition counts before analysis | Phase 0 gate V1/V2 |
| 9 | Phase 8's 3-way race tabulation (ADVERSE/FAVORABLE/UNRESOLVED) is complete and not silently miscounted | `p_adverse_before_favorable_<pair> + p_favorable_before_adverse_<pair> + p_unresolved_<pair> == 1` per pair, checked in `validate.py`; gate V-RACE. Unlike Phases 3/4/9/10 (pure column reads), Phase 8 performs genuinely new derived logic — tabulating a 3-way categorical plus a separate ambiguous-tie sub-flag, verified directly against the actual panel schema during SPEC-writing (not assumed boolean) — and is explicitly in the lookahead-auditor's scope (§9), not exempted as a pass-through. |

---

## 4. Phases

### Phase 0 — Lineage
Reproduce 8,950 arms → 4,705 confirmed → 4,245 stopped-before-confirm →
4,656 measurable confirmed (49 `SESSION_CLOSE_UNRESOLVED` excluded) from
`armed_regime_score_paths.parquet` (first four; already verified during M2)
and `observation_panel.parquet`'s own `n_unique(regime_id)` (the fifth).
Cross `with_5m_at_p90` × `with_5m_at_confirm` on the 4,656 → assert the
4-cell transition matrix exactly: WITH→WITH 623, WITH→AGAINST 9, AGAINST→WITH
6, AGAINST→AGAINST 4,018. Derive **both** population definitions as columns
on the same 4,656-row frame — `group_transition` (WITH_5M_AT_CONFIRM **629**
/ AGAINST **4,027**) and `group_stable` (WITH→WITH 623 / AGAINST→AGAINST
4,018, others excluded) — never as separate table sets.

**Correction, recorded rather than silently applied.** The originating brief
stated `WITH_5M_AT_CONFIRM 632 / AGAINST_5M_AT_CONFIRM 4,024`. Verified
directly against `p90_classification.parquet` — both a raw `value_counts` of
`with_5m_at_confirm` among the 4,656 confirming trades, and the transition
cross-tab sum, independently agree on **629/4,027**. `WITH_5M_AT_CONFIRM` is
`{WITH→WITH, AGAINST→WITH} = 623 + 6 = 629` (every cell where the trade IS
with the 5m regime at confirmation, regardless of its P90-time state); 632
would be `623 + 9` (`WITH_WITH + WITH_AGAINST`), which incorrectly includes
`WITH_AGAINST` — a cell that is AGAINST at confirmation by definition. The
transition matrix itself (623/9/6/4,018) reproduces exactly and is
unaffected; only the two-way collapse was mis-summed in the brief. `validate.py`
gate V1/V2 asserts 629/4,027, not 632/4,024.

Every Phase 2-11/13 output
carries a `population_definition ∈ {TRANSITION, STABLE_STATE}` column, so
"conclusions are unchanged" is a literal row-level diff, not a narrative
claim. No population changes. 2026 sealed.

### Phase 1 — State at confirmation
Freeze, one row per confirmed trade: 5m regime direction/alignment at
confirmation (`with_5m_at_confirm`), `regime_age_s_at_confirm`,
`regime_age_bars_at_confirm` (§3, new), `side, entry_year, arm_score,
walk_a_seconds_to_confirm, walk_a_mae_to_confirm_atr,
walk_a_mfe_to_confirm_atr, walk_a_return_at_confirm_atr,
regime_age_at_arm_s` (1m age, disclosed at-P90). No future quantity enters
this freeze.

### Phase 2 — Fixed forward landmarks
Measure at +30/60/120/180/300/600s after confirmation, plus natural
terminal. **Inherits the predecessor's D2 convention exactly:** a row exists
at an offset only if the trade is alive on the **UNCONSTRAINED** path there
(§5 D1) — no carry-forward of a terminal value. Attrition tracked against
the **constant denominator** (4,656 / 629 / 4,027 / 623 / 4,018 depending on
population/group) at every offset: `n_alive, n_terminal, attrition_pct`.
Alive-only (i.e. `alive_stop_live=True`) columns reported as a clearly
labelled SECONDARY, survival-conditioned view — never the primary read.

### Phase 3 — Mark-to-market path
`return_from_entry_atr` (landmark mark) and `return_since_confirm_atr` (Δ
return from confirmation, the key object) — both native panel columns, no
new computation. Mean/median/p25/p75 for WITH_5M vs AGAINST_5M at each
landmark, both population definitions.

### Phase 4 — Incremental MFE after confirmation
`running_mfe_since_confirm_atr` **is** `incremental_MFE` by construction
(panel D4: `max(bar_hi[confirm..j]) − mark[confirm]`) — zero new
computation. Mean/median/p75/p90 and P(incremental MFE ≥0.25/0.50/1.00/2.00)
for WITH vs AGAINST. Primary table.

### Phase 5 — Remaining MFE
`REMAINING_MFE = eventual_max_mfe_atr − running_mfe_from_entry_atr`, new but
trivial arithmetic on two existing columns. **LABEL_ONLY** — uses the
retrospective `eventual_max_mfe_atr` label, never a causal grouping key.
Mean/median/p75/p90 and P(remaining ≥0.25/0.50/1.00/2.00) for WITH vs
AGAINST at each landmark.

### Phase 6 — Opportunity capture curve
`POST_CONFIRM_TOTAL_MFE = eventual_max_mfe_atr − walk_a_mfe_to_confirm_atr`
(`walk_a_mfe_to_confirm_atr` is the sole authoritative "MFE at confirmation"
source — the panel's dense grid starts at confirm+15s, so it has no offset=0
row and therefore no independent value at the confirmation instant itself to
reconcile against; a naive comparison against the panel's offset=15s
`running_mfe_from_entry_atr` would be confounded by 15 real seconds of
possible additional favorable movement, not a genuine cross-engine
discrepancy — verified by inspection before writing this contract, not
assumed). **Sanity check (exact, not a fuzzy tolerance), mandatory:**
`running_mfe_from_entry_atr` at each trade's first offset (15s) must be
`>= walk_a_mfe_to_confirm_atr` for **100% of trades** — running MFE is
monotonic non-decreasing by construction (panel D4), so 15 additional
seconds can only extend it, never reduce it; any violation is a genuine
data-quality defect (gate V-RECONCILE), not a tolerance question.
`fraction_realized(t) = running_mfe_since_confirm_atr(t) / POST_CONFIRM_TOTAL_MFE`,
denominator floored (`< 0.05 ATR` → `UNMEASURABLE`, never divided). **The
one genuinely new derived-logic block:** a per-trade scan across that
trade's own offset sequence for the first crossing of 25/50/75/90%. Trades
that never cross a threshold within the dense ≤600s grid are reported as
`UNMEASURABLE` with disclosed coverage % — never silently dropped, never
extended into the sparse +900-2400s horizon for primary reporting (mirrors
the predecessor's dense/sparse separation).

### Phase 7 — New favorable extreme
`n_new_favorable_extremes_since_confirm > 0` at landmark answers "P(new
extreme since confirmation)" (native). `P(new extreme in NEXT
30/60/120/300s)` — a **descriptive outcome label only** — computed via a
small self-join across a trade's own future offset rows. Distinguishes
"theoretical MFE remains" (Phase 5) from "actually still printing new
highs" (this phase).

### Phase 8 — Adverse path after confirmation
`drawdown_from_running_max_atr, running_mae_from_entry_atr` native. The four
requested pairs (0.25 drawdown before 0.25 favorable, 0.50 before 0.25, 0.50
before 0.50, 1.00 before 0.50) map onto the panel's frozen D6 race columns
(`race_0_25_before_0_25`, `race_0_5_before_0_25`, `race_0_5_before_0_5`,
`race_1_0_before_0_5`) — **verified directly against the actual data (not
assumed):** each is a 3-way categorical string ∈
`{ADVERSE, FAVORABLE, UNRESOLVED}`, plus a separate boolean
`race_<pair>_ambiguous` sub-flag marking exact ties (a tie is already
counted `ADVERSE` in the categorical column per the panel's own D6
convention; `_ambiguous` exists only to let the optimistic/FAVORABLE-counted
bound be reported as a sensitivity, never to change the primary count).
Phase 8's "adverse before favorable" = `P(race_<pair> == "ADVERSE")`,
"favorable before adverse" = `P(race_<pair> == "FAVORABLE")`,
`P(UNRESOLVED)` reported separately (never folded into either side) — no
boolean complement, no new race computation, just a 3-way tabulation of an
existing column. Not turned into stops.

### Phase 9 — Giveback timing
`drawdown_from_running_max_atr` **is** current giveback (HWM − mark) by
construction (panel D4). `trade_nat_giveback_atr` **is** eventual terminal
giveback (trade-level constant). Mean/median/p75/p90 for WITH vs AGAINST at
each landmark, plus the terminal value.

### Phase 10 — Forward value from each landmark (continuation value)
`cv_stop_live_atr` (**PRIMARY**, null past the stop-live terminal, never
imputed) and `cv_unconstrained_atr` (secondary) — both native, matching this
phase's definition (`natural_terminal_return − executable_return_at_landmark`)
verbatim. Mean/median/bootstrap CI (trade-clustered, §4 Phase 13's method),
P(continuation value > 0), P(< 0), for WITH vs AGAINST at each landmark.

### Phase 11 — MFE quality buckets
`runner_bucket` native (`R0 <1, R1 1-2, R2 2-3, R3 >=3` ATR) —
**retrospective, LABEL_ONLY** (built on `eventual_max_mfe_atr`, gate
V-LABEL), **verified constant per trade** (0 of 4,656 trades carry more
than one distinct value across their own offset rows — confirmed directly
against the data). Re-run Phases 3/4/5/6/9/10's aggregations crossed with
this bucket × WITH/AGAINST. Determines whether the WITH/AGAINST distinction
is merely "WITH has more large runners" or a within-bucket behavioral
difference. Bucket membership is a descriptive label, never a causal
predictor.

**Correction, recorded rather than silently applied.** The panel's `mfe_bucket`
column is NOT the retrospective field this phase needs — verified during
the completion audit that it is bucketized from `running_mfe_from_entry_atr`,
a **contemporaneous, per-offset** value: 2,823 of 4,656 trades (60.6%)
occupy more than one distinct `mfe_bucket` across their own offset rows,
since running MFE only grows as a trade lives longer. Using it for Phase 11
would have made the crosstab compare "current incremental MFE" against a
bucket built from a MFE-adjacent quantity at the same instant — not a
look-ahead violation (the column is causally available at each row's own
timestamp) but a mischaracterization that would have made the table
near-circular rather than answering the stated question. `runner_bucket` is
the correct, trade-level source and is what `implementation/analysis.py::phase11_mfe_quality_buckets`
uses. **Distinct from, and never interchangeable with, Phase 12's
`confirm_mfe_bucket`** (below) — that one buckets a confirmation-time-only
variable, this one buckets a retrospective terminal outcome.

### Phase 12 — Confirmation quality control (MANDATORY)
WITH trades arrive at confirmation stronger (median return ~1.011 ATR vs.
AGAINST ~0.824 ATR, per M2). Stratify on **confirmation-time-only**
variables: `side`, `entry_year`, `walk_a_return_at_confirm_atr` bucket,
`walk_a_mfe_to_confirm_atr` bucket — named **`confirm_mfe_bucket`**, reusing
the `<1/1-2/2-3/>=3` edge scheme but a distinct column, never aliased with
Phase 11's retrospective `runner_bucket` (§4 Phase 11) —,
`walk_a_mae_to_confirm_atr` bucket, `walk_a_seconds_to_confirm` bucket
(reuse the `<=60/61-120/121-300/>300` speed cohorts), `arm_score` quartile
(frozen edges on the full 8,950 population), time-of-day (reuse the 4-window
RTH scheme from `p90_5m_regime_context`). Exposure-weighted stratified delta
+ trade-clustered bootstrap CI (direct reuse of
`p90_5m_regime_context/implementation/analysis.py::phase11_matched_control`'s
method), applied to five outcome metrics: incremental MFE at +300s/+600s,
remaining MFE at +300s/+600s, P(new extreme since confirm) at +300s,
continuation value (`cv_stop_live_atr`) at +300s/+600s, terminal return. One
row per outcome metric. **If this control removes the difference, this
study rejects the M2-era hypothesis that 5m alignment (rather than
confirmation strength) explains the post-confirm gap** — see §6, C3.

### Phase 13 — Year / side stability
`entry_year, side` native on the panel. Trade-clustered bootstrap (D8:
resample trades not observation-rows, 1,000 draws, seed `20260811` reused
from the predecessor) applied to Phases 4/5/6/10's headline metrics at
+120/+300/+600s. Every table reports **both** `n_obs` and `n_unique_trades`
(D8). A pooled difference that repeatedly reverses across year or side is
not reported as actionable.

---

## 5. Causal contract — the dual-track convention (inherited, unchanged)

Per `post_confirm_forward_opportunity`'s D1, settled and reused without
modification:

| Surface | Path used | Reason |
|---|---|---|
| Observation grid (Phase 2), all forward-opportunity labels (Phases 3–9, 11, 13) | **UNCONSTRAINED** — 1.00 ATR stop released | Terminating the grid at the stop is the censored-population defect that understated required stop room 5× in a prior study (`censored_population_cannot_answer_its_own_premise`) |
| Continuation value (Phase 10) | **BOTH** — `cv_stop_live` PRIMARY, `cv_unconstrained` secondary | The accepted economic baseline has the stop live |

Every observation carries `alive_stop_live`. `cv_stop_live` is null where
the stop-live path has already terminated, never imputed.

---

## 6. Decision classification — computed, not asserted

Thresholds below are **frozen illustrative defaults for this run**, not
settled science — reviewed during the pre-execution audit, computed
mechanically in `validate.py`. **C3 is evaluated before C2/C4** (mirrors the
predecessor's placebo-decides-attribution precedent): if Phase 12's
stratified-delta CI includes zero on the majority of its five outcome
metrics, the raw WITH/AGAINST advantage is attributed to confirmation
quality, not 5m context, regardless of how clean the pooled curves look.

| Verdict | Condition | Next step |
|---|---|---|
| `C1_STRONG_CONTEXT_SPECIFIC_TIMING` | WITH's median time-to-50%-capture (Phase 6) exceeds AGAINST's by ≥60s, AND WITH's remaining-MFE-at-+300s (Phase 5) exceeds AGAINST's by ≥0.15 ATR, AND AGAINST's median giveback-onset (Phase 9, first offset where median `drawdown_from_running_max_atr` exceeds 0.10 ATR) occurs ≥60s earlier than WITH's, AND Phase 12 survives (stratified delta excludes zero, same direction) on the majority of its 5 metrics, AND direction holds in ≥4/5 years and both sides (Phase 13) | test 2 simple context-specific exit architectures |
| `C2_RUNNER_QUALITY_NOT_TIMING` | Phase 11's within-`runner_bucket` capture-curve shapes (time-to-50%/75%) differ by <20% between WITH/AGAINST despite a pooled difference (i.e. the pooled gap is explained by bucket composition, not within-bucket timing) | 5m may help runner classification, not exit timing |
| `C3_EXPLAINED_BY_CONFIRMATION_QUALITY` | Phase 12's stratified-delta CI includes zero on the majority of its 5 outcome metrics, even though the raw (unstratified) delta is nonzero | use confirmation-state variables directly; drop 5m context |
| `C4_WEAK_UNSTABLE_CONTEXT_EFFECT` | pooled delta nonzero and survives C3's bar, but Phase 13 shows sign reversal in ≥2/5 years OR a LONG/SHORT inversion, OR Phase 12's CI spans both a materially-positive and materially-negative reading (width > 2× the point estimate) | do not build a policy from 5m context |
| `C5_NO_POST_CONFIRM_5M_INFORMATION` | none of C1-C4 match, AND pooled Phase 3/4/5/9 median deltas < 0.05 ATR at every landmark | close the 5m branch |
| `ABORT_LINEAGE_FAILURE` | any gate fails, or any §8 stop condition trips | fix and re-run |

**Evaluation order (single, authoritative — the per-row conditions above are
written to be checked in this order, not independently):** C1 (hardest bar)
→ C3 (kills attribution outright) → C2 → C4 (residual "something but not
clean") → C5 (the residual fallback, reached only if C1-C4 all fail to
match AND the pooled curves are already flat — never a pre-Phase-12
shortcut; Phase 12 always runs regardless of how flat the pooled curves
look, since C3's attribution check requires it).

---

## 7. Deliverables Manifest <!-- frozen before implementation -->

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/lineage_reconciliation.json` | json | Phase 0 checks, each `expected`/`observed`/`match` |
| 2 | `results/transition_matrix.csv` | table | `transition, n, group_transition_label, group_stable_label` — 4 rows, one per transition cell, e.g. `WITH_WITH, 623, WITH_5M, WITH_5M`; `WITH_AGAINST, 9, AGAINST_5M, null` (excluded from the stable definition) |
| 3 | `results/confirmation_state.parquet` | table | one row/confirmed trade: `regime_id, side, direction, entry_year, with_5m_at_confirm, group_transition, group_stable, regime_age_s_at_confirm, regime_age_bars_at_confirm, arm_score, walk_a_confirm_ns, walk_a_seconds_to_confirm, walk_a_mae_to_confirm_atr, walk_a_mfe_to_confirm_atr, walk_a_return_at_confirm_atr, regime_age_at_arm_s` |
| 4 | `results/landmark_attrition.csv` | table | `population_definition, group, offset_s, n_denominator, n_alive_unconstrained, n_terminal, attrition_pct, n_alive_stop_live` |
| 5 | `results/mark_to_market.csv` | table | `population_definition, group, offset_s, n_obs, n_unique_trades, return_from_entry_mean/median/p25/p75, return_since_confirm_mean/median/p25/p75` |
| 6 | `results/incremental_mfe.csv` | table | `population_definition, group, offset_s, n_obs, n_unique_trades, incr_mfe_mean/median/p75/p90, p_incr_ge_025/050/100/200` |
| 7 | `results/remaining_mfe.csv` | table | `population_definition, group, offset_s, n_obs, n_unique_trades, remaining_mfe_mean/median/p75/p90, p_remaining_ge_025/050/100/200` — LABEL_ONLY |
| 8 | `results/opportunity_capture.csv` | table | `population_definition, group, offset_s, n_obs, median_fraction_realized, pct_unmeasurable_denominator` — LABEL_ONLY (denominator uses retrospective `eventual_max_mfe_atr`) |
| 9 | `results/opportunity_capture_time_to_threshold.csv` | table | `population_definition, group, threshold_pct, n_reached, n_unreached_unmeasurable, coverage_pct, median_time_to_threshold_s` — LABEL_ONLY (same denominator) |
| 10 | `results/new_extreme_probability.csv` | table | `population_definition, group, offset_s, p_new_extreme_since_confirm, p_new_extreme_next_30s/60s/120s/300s` — the `NEXT`-window columns are LABEL_ONLY (forward-window outcome, §3.1 item 4); `p_new_extreme_since_confirm` (backward-looking from the landmark) is not |
| 11 | `results/adverse_path.csv` | table | `population_definition, group, offset_s, incr_mae_mean/median, drawdown_mean/median, p25/p75, p_adverse_before_favorable_<pair>, p_favorable_before_adverse_<pair>, p_unresolved_<pair>, p_ambiguous_<pair>` (4 pairs) — the panel's native `race_<fav>_before_<adv>` is a 3-way categorical (`ADVERSE`/`FAVORABLE`/`UNRESOLVED`, verified directly against the data, not boolean); `p_adverse_before_favorable` and `p_favorable_before_adverse` are its two resolved-outcome shares, `p_unresolved` its third; `p_ambiguous` is the separate native `_ambiguous` tie sub-flag's share (already included within `p_adverse_before_favorable` per the panel's own convention — reported alongside as a disclosed sensitivity, never subtracted out) |
| 12 | `results/giveback_timing.csv` | table | `population_definition, group, offset_s, giveback_mean/median/p75/p90, terminal_giveback_mean/median` |
| 13 | `results/continuation_value.csv` | table | `population_definition, group, offset_s, basis(stop_live/unconstrained), cv_mean/median, ci_low, ci_high, p_positive, p_negative` |
| 14 | `results/mfe_quality_buckets.csv` | table | `population_definition, group, runner_bucket, offset_s, metric, value` (long format across Phases 3/4/5/6/9/10) — `runner_bucket`, NOT the panel's contemporaneous `mfe_bucket` (§4 Phase 11 correction) |
| 15 | `results/matched_confirmation_control.csv` | table | `population_definition, outcome_metric, n_cells, n_cells_both_present, raw_delta, stratified_delta, delta_ci_low, delta_ci_high, ci_excludes_zero` |
| 16 | `results/year_side_stability.csv` | table | `population_definition, slice_kind(year/side), slice, metric, offset_s, n_obs, n_unique_trades, value` |
| 17 | `results/primary_table.csv` | table | `population_definition, group, metric, value` (long format) — `metric` spans `n_confirmed, confirm_return_median, confirm_mfe_median, confirm_mae_median`, then per landmark ∈ {60,120,180,300,600}: `delta_mark_median, incr_mfe_median, remaining_mfe_median, p_new_extreme_next_60s, continuation_value_median`, then `terminal_return, terminal_giveback` |
| 18 | `results/opportunity_capture_summary.csv` | table | `population_definition, group, metric, value` (long format) — `metric` spans `time_to_25pct_s, time_to_50pct_s, time_to_75pct_s, time_to_90pct_s` (each with a paired `_coverage_pct`) and, per landmark ∈ {60,120,180,300,600}: `remaining_mfe_median` |
| 19 | `results/validation_report.json` | json | every gate, `expected`/`observed`/`pass` |
| 20 | `results/summary.json` | json | verdict, facts, headline numbers |
| 21 | `results/partition_manifest.json` | json | input paths + row counts, code hash, seed, frozen bucket edges |
| 22 | `SPEC.md` / `README.md` / `REPORT.md` | docs | this contract; how to run; the answered questions |
| 23 | `audit/status.json` | json | roll-up with a key per agent; `critical: 0` required |

`*.parquet`/`*.csv` under `results/` are generated, **not committed**. JSON
manifests and `SPEC.md`/`README.md`/`REPORT.md` are committed.

### 7.1 Domain & completeness contract

- **Partition grid:** 5 years × 2 sides × 2 population definitions × 2
  groups (WITH/AGAINST) = 40 cells minimum per landmark table; every cell
  retained with `n=0` if empty, never dropped (mirrors `p90_5m_regime_context`
  §8.1's generalized zero-row rule, applied here across Phases 3-11, 13).
- **Boundary convention:** offsets closed-left/open-right on bucket
  assignments (`confirm_mfe_bucket`, speed cohorts, etc.; `runner_bucket` is
  consumed as-is from the panel, not re-bucketed here), matching upstream.
- **Missing/unmeasurable handling:** Phase 6 threshold-crossing coverage <
  100% is disclosed as a percentage, never imputed or silently excluded from
  the denominator.
- **Global validation:** row counts reconcile to 4,656 (population-wide
  tables) or 629/4,027 (transition definition) or 623/4,018 (stable
  definition) at every phase; `validate.py` checks all three.

### 7.2 Terminal decision labels

See §6 — `C1`–`C5` and `ABORT_LINEAGE_FAILURE` are the complete, exhaustive
set of reachable labels.

---

## 8. Stop conditions

1. Phase 0 fails to reproduce 8,950/4,705/4,245/4,656/49 or the 4-cell
   transition matrix → **ABORT**.
2. `observation_panel.parquet`'s trade set doesn't 100%-match
   `p90_classification.parquet`'s confirming subset → **ABORT** (upstream
   artifact drift).
3. Any `Regime5m` call at `walk_a_confirm_ns` resolves a flip with
   `close_ts > walk_a_confirm_ns` → **ABORT**.
4. A retrospective/future-derived column (`eventual_max_mfe_atr`,
   `runner_bucket`, any `NEXT`-window field) is used as a grouping or filter
   key anywhere outside its declared LABEL_ONLY role → **ABORT** (gate
   V-LABEL, §3.1 item 4). See §4 Phase 11's explicit carve-out above (a
   retrospective field used purely as a descriptive post-hoc stratification
   axis, never fed back into the WITH/AGAINST group definition, is
   permitted; used to define or filter that group definition, it is not).
5. Phase 12 stratification reads any post-confirmation offset-indexed
   column → **ABORT** (gate V-MATCH, §3.1 item 6; verified clean by
   inspection of the stratum list in §4 Phase 12 — every variable is
   confirmation-time-or-earlier — and enforced at runtime by
   `implementation/validate.py`'s `V_MATCH_confirmation_time_only` gate,
   which asserts every Phase 12 stratum column name is a member of the
   frozen confirmation-time-only column set. Corrected citation: this gate
   is NOT covered by `tests/test_join_causality.py`, which only covers stop
   condition 3 — the completion-time lookahead-auditor pass flagged the
   original citation as inaccurate, downgraded from WARNING to NOTE since
   the actual gate runs and passes regardless of the test file's scope).
6. 2026 appears in any output → **ABORT** (gate V-SEALED, §3.1 item 7).
7. Any audit CRITICAL survives → **ABORT**.

No new parity test is a stop condition here — the upstream engines' parity
(`Regime5m`, the panel's own 14+1 validation gates) is inherited by
reference-reproduction (conditions 1–2), not re-proven.

---

## 9. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/post_confirm_5m_forward_opportunity`.
- Pre-execution: `lookahead-auditor` scoped narrowly to the genuinely new
  surface — §3's at-confirmation `Regime5m` calls, Phase 5/6/7's LABEL_ONLY
  framing and non-leakage, Phase 6's capture-curve derived-scan logic, Phase
  8's 3-way race tabulation (§3.1 item 9 — genuinely new derived logic, NOT
  exempted as a pass-through), and Phase 12's confirmation-time-only
  matching. Phases 3/4/9/10 are direct reads of an already-causally-audited
  artifact and need only provenance/join-key verification, not a fresh
  causal proof.
- Pre-execution: `contract-checker` scoped to §7's Deliverables Manifest and
  §6's C1–C5/ABORT reachability.
- Completion: both re-run against final `results/`; new numbered pass files
  each time, prior findings adjudicated first, max 3 new CRITICALs per
  pass; `audit/status.json` shows `critical: 0`.
- Executed via `scripts/run_bounded_study.py` wrapping `run_study.py`.

---

## 10. No optimisation

Forbidden: any exit rule, trailing stop, profit target, drawdown threshold,
score threshold, or timing rule derived from this study's findings; tuning
of any bucket edge, stratum boundary, or capture-curve threshold to maximize
a separation; treating Phase 5/7's retrospective fields as anything but
labels. Phases 0–13 are all descriptive. A subsequent study testing simple
context-specific exit architectures is explicitly out of scope here, gated
on the C1–C5 verdict.
