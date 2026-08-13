# P90 Entry Path × 5-Minute Regime Context — Frozen Specification

**Study:** `p90_5m_regime_context` · **Frozen:** 2026-08-12, before implementation.
**Branch:** `study/p90_5m_regime_context`
**Predecessors:** `studies/p90_5s_regime_impulse/` (F4), `studies/p90_conditional_losing_5s_exit/` (G4)
**Substrate:** `data/canonical/regime_complete_v1/`
**Population:** the frozen **8,950** Top-10 (P90) arms · 2021–2025 RTH · **2026 sealed**

---

## 0. The narrow question

The 5s conditional-failure study (G4) established that a losing adverse 5s flip
is real signal (PPV 0.664 vs. 0.478 prevalence) but cannot separate a failing
P90 attempt from a healthy trade taking a normal 5s counter-wiggle: ATR saved
on failures and ATR sacrificed on good trades came out to a 1.018 ratio — a
wash.

> Does the prevailing **5-minute** regime, and where a P90 arm sits in that
> regime's lifecycle, explain which short-term adverse moves are noise and
> which are real failure?

This is a **descriptive context study only**. No entry filter, no exit policy,
no optimization is produced here. It classifies the existing accepted P90
population against a newly built causal 5-minute regime and reports where (if
anywhere) separation shows up. A resulting policy is an explicitly
out-of-scope follow-up study.

---

## 1. Inherited verbatim — NOT rebuilt

| Item | Source |
|---|---|
| P90 ≡ Top-10 arm definition and the 8,950-arm population, including `full_*` FULL-lifecycle economics and `walk_a_*` confirmation fields for all 8,950 arms as native columns | `armed_fade_score_path_progression/results/armed_regime_score_paths.parquet` |
| Adverse 5s flip failure signal (`is_losing`, `current_return_atr`, PPV 0.6638) | `p90_conditional_losing_5s_exit/results/adverse_5s_flip_events.parquet` (imported, not recomputed) |
| 1.00 / 0.75 ATR stop-distance baselines | `p90_conditional_losing_5s_exit/results/baseline_100.parquet` / `baseline_075.parquet` (imported, not recomputed) |
| Sticky EMA3/EMA9 regime rule and the two-clock (bucketing vs. availability) causal convention | `collectors/collector_v2/regime_engine.py::RegimeStateEngine`, reproduced offline per `p90_5s_regime_impulse/implementation/regime_5s.py`'s pattern |
| Cost / session / ATR conventions | shared engine; not used here — this study performs no trade-lifecycle simulation |

**No trade-lifecycle simulator is built in this study.** Verified against
source: `armed_regime_score_paths.parquet` already carries
`full_gross_atr, full_net_atr, full_mfe_atr, full_mae_atr, terminal_label_full,
walk_a_confirm_ns, walk_a_confirm_reached_censored, walk_a_seconds_to_confirm,
walk_a_mae_to_confirm_atr, walk_a_mfe_to_confirm_atr, walk_a_return_at_confirm_atr,
regime_age_at_arm_s, arm_score, arm_top10_ns, arm_price, arm_atr, direction,
side, entry_year, regime_id` as native columns for all 8,950 arms — confirmed
by reading `p90_conditional_losing_5s_exit/implementation/lineage.py`, which
reads them directly off the loaded parquet rather than computing them. Phase 0
here is therefore load-and-reconcile only.

`direction` is the intended TRADE direction (±1), directly comparable to the
regime engine's ±1 output — this is the same convention
`p90_5s_regime_impulse/implementation/policy.py::alignment_at_arm` uses for
the 5s alignment classification, reused unchanged for the 5-minute
classification here.

---

## 2. The 5-minute regime — newly built, reconciled

**Definition (frozen).** The *same* sticky EMA3/EMA9 high/low/close rule
`RegimeStateEngine` uses, applied to 5-minute buckets built by
`TimeframeAggregator`'s bucketing (`TIMEFRAME_TO_BUCKET_NS["5m"]`, already a
supported timeframe). Binary/sticky after warmup: no NEUTRAL state exists.

**Build.** Directly adapted from `p90_5s_regime_impulse/implementation/regime_5s.py`
— only `BUCKET_NS = 5*60*1_000_000_000` changes. Reused unchanged:
- **Bucketing clock vs. availability clock, kept separate.** Buckets form on
  `path_event_ns` (bar OPEN); `bucket_id = ts // BUCKET_NS`; a bucket's state
  becomes available only at `close_ts = (bucket_id+1) * BUCKET_NS`. Every
  lookup uses only `close_ts`.
- **Continuous across RTH+ETH** for warmup validity; entries/classification
  are gated to the RTH P90 arms downstream, but the regime *state* itself is
  never restarted at session open.
- **Source:** `data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet`
  (`path_event_ns, high, low, close`).
- **The final in-progress bucket is discarded**, exactly as the aggregator
  never closes a trailing partial bucket.

**Additions over the 5s build** (5m has ~300–500k closed buckets over 5 years,
cheap to keep in full, unlike 5s's 12M rows):
- `_work/regime_5m_buckets.parquet` — every closed bucket, `close_ts`-ordered,
  giving a monotonic bar index.
- `Regime5m.age_seconds_at(t)` = `t - flip_ts_at(t)` (mirrors
  `p90_5s_regime_impulse`'s `_age_5s`).
- `Regime5m.age_bars_at(t)` = bar-index of the last closed bucket ≤ t minus
  bar-index of the flip bucket, plus 1 (reproduces `RegimeStateEngine`'s
  `bars_in_regime` counting convention, which starts at 1 on the flip bar).
- **"5m regime age in seconds" and "seconds since last 5m regime flip" are
  the same quantity under this engine's semantics** (both equal
  `t - flip_ts_at(t)`) — one column, `regime_age_s_at_p90`, satisfies both
  phrasings.

**Reconciliation (required before running the full study).**
`backtests/studies/1m_regime_collector_v2/collector.py` independently
snapshots a 5-minute regime (`regime_5m_direction`, `regime_5m_aligned`,
`regime_5m_duration_bars`) at every 1m-flip signal, repeated at multiple
checkpoint offsets (`checkpoint_s` = 0, 30, 60, ... seconds after the
signal), into
`backtests/studies/1m_regime_collector_v2/results/v2_feature_snapshots_<year>.parquet`.
`regime_5m.py` filters to **`checkpoint_s == 0`** (the row AT `signal_time`
itself, confirmed present, ~9k rows/year) before comparing — any later
checkpoint reflects a later regime state and would corrupt the comparison
(fixed in the pass-1 lookahead-auditor adjudication, audit/pass_01.md,
F1/A1 — the SPEC previously did not pin the checkpoint offset). It then
reports `Regime5m.state_at(signal_time)` agreement against
`regime_5m_direction` in `_work/regime_5m_build.json`. **Treated as
non-blocking / informational**: that collector is a separate implementation,
not provably the same code path as `RegimeStateEngine`, so a mismatch is a
finding to report, not proof this study's engine is wrong. A WARNING (not
CRITICAL) is raised if agreement falls below 95%; the authoritative causal
correctness check is the parity test (§2.1), not this cross-check.

### 2.1 Parity gate — mandatory before any classification runs

`tests/test_regime_5m_parity.py`, a direct copy of
`p90_5s_regime_impulse/tests/test_regime_5s_parity.py` with `BUCKET_NS` and
the import swapped: bucket-boundary equality, OHLC equality, exact regime
equality bar-for-bar, sticky-binary-after-warmup, and the causal-boundary
tests (`test_bucket_contains_only_past_bars`,
`test_lookup_never_reads_an_incomplete_bucket`) against a literal
`TimeframeAggregator(timeframes=("5m",))` + `RegimeStateEngine` +
`CompletedBarRegistry` replay over a 200,000-row slice of the canonical 1s
store (enough for dozens of closed 5m buckets and multiple regime changes).
**A failure here ABORTS before any classification is computed.**

---

## 3. Primary 5m classification — causal contract

At the P90 arm timestamp:
```text
with_5m_at_p90    = direction == Regime5m.state_at(arm_top10_ns)
against_5m_at_p90 = direction != Regime5m.state_at(arm_top10_ns)   AND state != 0
uninit_at_p90     = Regime5m.state_at(arm_top10_ns) == 0   (5m engine not yet warmed up)
```
`Regime5m.state_at(t)` resolves only flips with `close_ts <= t` —
structurally identical to the invariant `CompletedBarRegistry.audit_provenance`
enforces online (`state.close_ts <= decision_ts`). `UNINIT` is a first-class
third category (mirroring `p90_5s_regime_impulse`'s `UNINIT` alignment state),
never silently folded into `AGAINST_5M`.

At the Walk-A confirmation timestamp (confirming trades only):
```text
with_5m_at_confirm = direction == Regime5m.state_at(walk_a_confirm_ns)
```
Same causal guarantee, evaluated at `walk_a_confirm_ns` instead of
`arm_top10_ns`.

### 3.1 The ten audit items

| # | Item | Enforced by |
|---|---|---|
| 1 | 5m state at P90 uses only completed 5m information | `state_at` never resolves `close_ts > decision_ts`; gate V-CAUSAL-1 |
| 2 | 5m state at confirmation uses only info available by confirmation | same lookup, evaluated at `walk_a_confirm_ns`; gate V-CAUSAL-2 |
| 3 | Future 5m flip timing is label-only | Phase 6 output isolated in a separate frame, every column `label_only_`-prefixed; gate V-LABEL |
| 4 | No eventual MaxMFE or terminal outcome enters classification | `p90_classification.parquet` schema allowlist excludes `full_*`/`walk_a_*` outcome fields; gate V-SCHEMA |
| 5 | 5m regime age is causal | `age_seconds_at`/`age_bars_at` both derived from `flip_ts_at`, itself `close_ts <= t`-bounded; gate V-CAUSAL-1 |
| 6 | No partial 5m bucket is used | final in-progress bucket discarded at build time; bucket/row reconciliation; gate V-BUILD |
| 7 | Population remains all 8,950 P90 arms | every output traced to `armed_regime_score_paths.parquet`, height-asserted; gate V1 |
| 8 | 2026 remains sealed | `max(entry_year) < 2026` on every output; no `state_at`/`age_*` call issued a 2026+ timestamp; gate V-SEALED |

---

## 4. Phases

### Phase 0 — Lineage
Load `armed_regime_score_paths.parquet`, assert `height == 8950`, diff
`terminal_label_full` counts, `entry_year`/`side` breakdowns, and
`walk_a_confirm_reached_censored` rate against the frozen references already
established by the predecessor: `FULL_LABEL_COUNTS` (STOPPED_BEFORE_CONFIRM
4245, FINAL_FLIP_EXIT_WINNER 2350, FINAL_FLIP_EXIT_LOSER 1359,
CONFIRMED_THEN_STOPPED 822, SESSION_EXIT 174), `YEAR_TARGETS` (2021: 1828,
2022: 1825, 2023: 1763, 2024: 1771, 2025: 1763), confirm rate 0.5202 →
4,656 confirming, MAE-to-confirm references (p50 0.330, p75 0.596, p80 0.660,
p90 0.818, p95 0.907), tolerance 0.002. No population changes. A mismatch on
any check ABORTS — these are references, not repair targets.

### Phase 1 — 5m context at P90
`n` / `%` for WITH_5M / AGAINST_5M / UNINIT, broken out by LONG/SHORT/year.
5m regime age in seconds, in completed 5m bars, bucketed with frozen broad
buckets: 0–5 / 5–15 / 15–30 / 30–60 / >60 minutes. Boundaries are not
optimized.

### Phase 2 — Pre-confirm outcome
For WITH_5M / AGAINST_5M: `n`, `P(confirm before 1 ATR SL)` (=
`walk_a_confirm_reached_censored` rate), `P(stop before confirmation)`,
seconds-to-confirmation (mean/median/p25/p75/p90 of
`walk_a_seconds_to_confirm`), MAE-to-confirm (mean/p50/p75/p80/p90/p95 of
`walk_a_mae_to_confirm_atr`), MFE-to-confirm (mean/median/p75/p90 of
`walk_a_mfe_to_confirm_atr`), return-at-confirm (mean/median of
`walk_a_return_at_confirm_atr`). **Also broken out by `entry_year` and by
`side`** (a `stratum` column distinguishes `ALL` / per-`entry_year` /
per-`side` rows in the same table) — this is what §7's M1 verdict condition
("same sign in ≥4/5 years and both sides") reads from; added in the pass-1
contract-checker adjudication (audit/contract_pass_01.md, C1).

### Phase 3 — Confirmation speed
For WITH_5M / AGAINST_5M, bucket eventual confirmation by
`walk_a_seconds_to_confirm`: ≤60s / 61–120s / 121–300s / >300s / NO_CONFIRM.
Report `n`, confirmation rate, MAE, MFE, return-at-confirm,
`full_mfe_atr` (eventual MaxMFE), `full_net_atr` (eventual terminal return).

### Phase 4 — Post-confirm MFE quality
Confirming trades only. Bucket `full_mfe_atr` (favorable excursion from
entry, FULL lifecycle): <1.0 / 1.0–2.0 / 2.0–3.0 / 3.0–4.0 / ≥4.0 ATR. Report
WITH_5M-at-P90 % and AGAINST_5M-at-P90 % within each bucket, and each 5m
group's distribution across buckets. Uses the full confirming population, not
only flip-exit winners.

### Phase 5 — 5m state at 1m confirmation — the transition matrix
`{WITH,AGAINST}@P90 → {WITH,AGAINST}@confirm`, 4 groups, confirming trades
only. Per group: `n`, `%` of confirming trades, return-at-confirm, MFE-at-confirm
(`walk_a_mfe_to_confirm_atr`), MAE-to-confirm, seconds-to-confirm, subsequent
additional MFE (`full_mfe_atr - walk_a_mfe_to_confirm_atr`, floored at 0),
eventual MaxMFE (`full_mfe_atr`), terminal return (`full_net_atr`), final
flip-exit win rate (`terminal_label_full == FINAL_FLIP_EXIT_WINNER` rate among
those reaching a flip exit), `CONFIRMED_THEN_STOPPED` %, `SESSION_EXIT` %,
mean/median giveback (`full_mfe_atr - full_net_atr`).

**Special interest — AGAINST→WITH.** Not assumed best. Compared explicitly
against WITH→WITH and AGAINST→AGAINST on confirmation speed, MAE,
return-at-confirm, eventual MaxMFE, P(MFE≥3 ATR), P(MFE≥4 ATR), terminal
economics.

### Phase 6 — Timing relative to 5m flip (label-only)
For every P90 arm: does P90 occur AFTER an existing 5m flip into trade
direction, or while still against 5m with a future 5m flip into direction
eventually occurring? **The future-flip timestamp is an outcome label only**
and is walled off (§5). Where a future flip occurs, bucket
`label_only_p90_to_5m_flip_s`: ≤60 / 61–120 / 121–300 / 301–600 / >600 /
no flip before terminal. Report confirmation rate, confirmation timing, MFE,
MAE, final economics per bucket.

### Phase 7 — 5m regime age
For WITH_5M / AGAINST_5M separately, using Phase 1's frozen age buckets:
`P(confirm)`, MAE-to-confirm, return-at-confirm, eventual MaxMFE, P(MFE≥3 ATR),
terminal return. Age boundaries are not optimized; this looks only for an
obvious structural relationship.

### Phase 8 — 5m context × 5s failure signal
Reuses `p90_conditional_losing_5s_exit/results/adverse_5s_flip_events.parquet`
(90,437 rows, `is_losing`, `current_return_atr`, `before_confirm`) — not
recomputed. For P90 trades experiencing an adverse 5s flip with
`current_return_atr < 0` before confirmation, split by 5m state at that exact
flip's `flip_ns`: `FAILURE_SIGNAL_WITH_5M` / `FAILURE_SIGNAL_AGAINST_5M`.
Report confirm %, failure %, PPV for failure, conditional exit return,
accepted continuation return. Repeated using 5m state at P90 instead of at
the flip. See §4.1 (the 8,379-of-8,950 gap) for denominator handling.

### Phase 9 — 0.75 ATR stop context
Descriptive only; no stop distance is optimized. Reuses
`p90_conditional_losing_5s_exit/results/baseline_100.parquet` /
`baseline_075.parquet` — not recomputed. Within WITH_5M / AGAINST_5M: how many
confirming trades have `mae_atr > 0.75`, and how much failure loss reduction
`0.75` vs. `1.00` would imply. See §4.1 for denominator handling.

### Phase 10 — Full economic outcome
For WITH_5M / AGAINST_5M, using the FULL lifecycle (`full_*` columns) over
all 8,950 arms (0.0 contribution for non-entries, matching the predecessor's
per-arm convention): expectancy/arm, gross, net, profit factor, win rate,
MaxDD, mean winner, mean loser, `FINAL_FLIP_EXIT_WINNER`/`LOSER` %,
`CONFIRMED_THEN_STOPPED` %, MFE, MAE, giveback, capture ratio
(`full_net_atr / full_mfe_atr` where `full_mfe_atr > 0`). Broken out by year
and LONG/SHORT.

### Phase 11 — Matched context control
Descriptive stratification (exposure-weighted delta across cells), **not** a
fitted propensity model — consistent with §6's "no optimization." Strata:
`entry_year` (5 levels), `side` (2 levels), a frozen time-of-day bucket
(RTH session quartered into four fixed CT windows: 08:30–10:00, 10:00–11:30,
11:30–13:00, 13:00–15:00, derived from `arm_top10_ns`), `arm_score` quartiles
(frozen edges computed once on the full 8,950 population), and
`regime_age_at_arm_s` (the **existing 1m** regime age column — distinct from
the new 5m age field) bucketed with the Phase 1 age scheme. Within each cell,
compute the WITH−AGAINST delta on confirm rate / return-at-confirm /
P(MFE≥3 ATR); aggregate across cells via an exposure-weighted average.
Matching uses only quantities available at `arm_top10_ns` — never an outcome
field.

---

## 5. Causal contract

- **Decision timestamps:** `arm_top10_ns` is the ONLY timestamp used for the
  WITH_5M/AGAINST_5M/UNINIT **grouping variable** (`with_5m_at_p90`), used
  throughout Phases 1, 2, 3, 4, 6, 7, 10, 11 — including Phase 2/3/4, whose
  outcome tables report what eventually happens (confirmation, its timing,
  its MAE/MFE) to trades already grouped by their state AT P90. Grouping by
  `walk_a_confirm_ns` there would be circular: that timestamp is undefined
  for the 4,294 non-confirming arms, and Phase 2's own headline metric
  (`P(confirm before 1 ATR SL)`) requires the grouping to exist BEFORE
  confirmation is known. `walk_a_confirm_ns` is used only (a) as the
  **outcome-metric anchor** within those same tables (e.g.
  `walk_a_mae_to_confirm_atr` is a value, not a grouping key) and (b) as the
  second **decision timestamp** for the Phase-5 transition matrix's
  `with_5m_at_confirm` variable, itself restricted to the 4,656 confirming
  trades. Fixed in the pass-1 lookahead-auditor adjudication
  (audit/pass_01.md, C2) — this was a SPEC wording defect; `classify.py`'s
  design already grouped by `with_5m_at_p90` throughout, per §4's phase
  descriptions.
- **Snap rule:** 5m regime state uses `close_ts <= decision_ts`; nothing reads
  an in-progress bucket (§2.1).
- **The one legitimate forward-looking lookup:** Phase 6's future-5m-flip
  timing. Isolated by construction — `classify.phase6_future_flip_labels(...)`
  is the only function permitted to call `Regime5m.next_change_after`, returns
  a **separate** frame (`phase6_timing.csv`) never merged into
  `p90_classification.parquet`. The `label_only_` prefix applies to the raw
  future-flip timing/relationship columns themselves
  (`label_only_p90_relative_to_5m_flip`, `label_only_p90_to_5m_flip_s`) —
  the only columns that are *computed from* a forward-looking lookup.
  Backward-looking outcome aggregates keyed by the resulting (label-only)
  bucket (`confirm_rate`, `mfe_mean`, `mae_mean`, `terminal_return_mean`) are
  ordinary outcome statistics grouped by that bucket and are exempt from the
  prefix, since they carry no forward information themselves — clarified in
  the pass-1 contract-checker adjudication (audit/contract_pass_01.md, W2).
  `validate.py` scans every non-Phase-6 output frame's column names for the
  `label_only_` prefix and fails the gate if one leaks in.
- **Censoring:** nothing is dropped. Non-entries and censored arms stay in
  every denominator (`baseline_must_include_prefilter_losers`).
- **Load-bearing checklist rules:** A, B, C1–C3, F, G, H.

### 5.1 The 8,950 vs. 8,379 gap

Only Phase 8 (needs `adverse_5s_flip_events.parquet`) and Phase 9 (needs
`baseline_075/100.parquet`) depend on artifacts scoped to the 8,379
5s-aligned-entered subset of the 8,950 arms. Every other phase uses
`walk_a_*`/`full_*` columns defined for all 8,950. Phase 8/9 tables
**left-join** onto the full 8,950-row classification and report the 571
unmatched arms as an explicit `NOT_5S_ENTERED` category — never a silently
shrunk denominator. Every rate in those two tables is reported alongside
`n_total_8950` / `n_5s_entered_8379` / `n_not_5s_entered_571`.

---

## 6. No policy — descriptive only

Forbidden in this study: any entry filter ("trade only WITH_5M"); any
risk-management rule ("use 0.75 SL AGAINST_5M"); any exit-timing rule ("exit
AGAINST_5M trades early"); any threshold optimization on regime age,
time-of-day buckets, or MFE buckets. Phases 1–11 are all descriptive. A
resulting policy is an explicitly out-of-scope follow-up study, gated on the
verdict below.

---

## 7. Decision classification — computed, not asserted

`determine_verdict()` returns a **primary** verdict plus a `secondary_signals`
list (M1–M4 are candidate next-study directions, not mutually exclusive,
unlike the predecessors' single-label G-verdicts). A raw WITH/AGAINST
separation is only **credited** to a verdict if Phase 11's stratified delta
also excludes zero in the same direction — otherwise it routes to M5 with a
"confounded by P90 context" note, mirroring the predecessor's
placebo-decides-attribution rule.

**Thresholds below are frozen illustrative defaults for this run, not settled
science** — reviewed during the pre-execution audit, computed mechanically in
`validate.py`, never left to post-hoc narrative judgment (this project's gates
read `audit/status.json`, never prose).

| Verdict | Condition | Next step |
|---|---|---|
| `M1_STRONG_ENTRY_CONTEXT` | confirm-rate delta ≥5pp AND median return-at-confirm delta ≥0.10 ATR, same sign in ≥4/5 years and both sides, Phase 11 delta excludes zero same-direction | context-specific entry/risk policies |
| `M2_POST_CONFIRM_CONTEXT` | pre-confirm deltas below M1's bar, but P(MFE≥3 ATR) delta ≥5pp OR mean giveback delta ≥0.15 ATR, both read as `WITH_WITH` vs. `AGAINST_AGAINST` from `transition_matrix.csv`'s `p_mfe_ge_3atr`/`giveback_mean` (item #7) — the two well-populated transition groups, not `WITH_AGAINST`/`AGAINST_WITH`, which are too thinly populated (n<10) to support a threshold comparison | context-specific runner management |
| `M3_TRANSITION_PATH_MATTERS` | static WITH/AGAINST below M1's bar, but AGAINST→WITH separates from {WITH→WITH, AGAINST→AGAINST} by ≥M2's magnitude on ≥3/≥4 ATR runner rate | transition-aware management |
| `M4_5S_SPECIFICITY_IMPROVED` | failure-PPV delta between `FAILURE_SIGNAL_WITH_5M`/`FAILURE_SIGNAL_AGAINST_5M` ≥0.08–0.10 | revisit conditional failure exit with frozen 5m context |
| `M5_NO_MATERIAL_INFORMATION` | none of the above survive Phase 11 stratification | do not build context-specific policies |
| `ABORT_LINEAGE_FAILURE` | any gate fails, or any §9 stop condition trips | fix and re-run |

---

## 8. Deliverables Manifest <!-- frozen before implementation -->

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/lineage_reconciliation.json` | json | population/label/year/side/confirm-rate/MAE checks, each `expected`/`observed`/`match` |
| 2 | `results/p90_classification.parquet` | table | `regime_id, direction, side, entry_year, arm_top10_ns, with_5m_at_p90(bool), against_5m_at_p90(bool), uninit_at_p90(bool), regime_age_s_at_p90, regime_age_bars_at_p90, age_bucket, with_5m_at_confirm(bool, null if not confirming)` |
| 3 | `results/p90_5m_context.csv` | table | Phase 1: `group(WITH_5M/AGAINST_5M/UNINIT), side, entry_year, n, pct_population, age_bucket_n, age_bucket_pct` |
| 4 | `results/pre_confirm_outcome.csv` | table | Phase 2: `stratum(ALL/side/entry_year), stratum_value, group, n, p_confirm_lt_1atr, p_stop_before_confirm, sec_to_confirm_mean, sec_to_confirm_median, sec_to_confirm_p25, sec_to_confirm_p75, sec_to_confirm_p90, mae_to_confirm_mean, mae_to_confirm_p50, mae_to_confirm_p75, mae_to_confirm_p80, mae_to_confirm_p90, mae_to_confirm_p95, mfe_to_confirm_mean, mfe_to_confirm_median, mfe_to_confirm_p75, mfe_to_confirm_p90, return_at_confirm_mean, return_at_confirm_median` |
| 5 | `results/confirmation_speed.csv` | table | Phase 3: `group, speed_bucket, n, confirm_rate, mae_to_confirm_mean, mfe_to_confirm_mean, return_at_confirm_mean, eventual_maxmfe_mean, terminal_return_mean` |
| 6 | `results/mfe_quality.csv` | table | Phase 4: `mfe_bucket, group, n, pct_of_group, pct_of_bucket` |
| 7 | `results/transition_matrix.csv` | table | Phase 5: `transition, n, pct_of_confirming, return_at_confirm_mean, mfe_at_confirm_mean, mae_to_confirm_mean, sec_to_confirm_mean, subsequent_additional_mfe_mean, eventual_maxmfe_mean, terminal_return_mean, flip_exit_win_rate, confirmed_then_stopped_pct, session_exit_pct, giveback_mean, giveback_median, p_mfe_ge_3atr, p_mfe_ge_4atr` (all 4 groups) |
| 8 | `results/against_with_deep_dive.csv` | table | Phase 5 special interest: `transition(WITH_WITH/AGAINST_WITH/AGAINST_AGAINST), n, confirmation_speed_median_s, mae_mean, return_at_confirm_mean, eventual_maxmfe_mean, p_mfe_ge_3atr, p_mfe_ge_4atr, terminal_return_mean` |
| 9 | `results/phase6_timing.csv` | table | one row per arm (8,950): `regime_id, direction, side, entry_year, label_only_p90_relative_to_5m_flip, label_only_p90_to_5m_flip_s, timing_bucket, confirmed(bool), mfe_atr, mae_atr, terminal_return_atr`. Per-bucket confirmation rate/MFE/MAE/terminal-return reported by Phase 6's prose are obtained by grouping this table on `timing_bucket` — implementation amendment, recorded during code-writing after the granularity mismatch (per-arm raw columns vs. per-bucket aggregate columns in one flat table) was noticed; see `implementation/analysis.py::phase6_timing`. |
| 10 | `results/regime_age_outcomes.csv` | table | Phase 7: `group, age_bucket, n, p_confirm, mae_to_confirm_mean, return_at_confirm_mean, eventual_maxmfe_mean, p_mfe_ge_3atr, terminal_return_mean` |
| 11 | `results/five_m_x_5s_failure.csv` | table | Phase 8: `join_point(AT_5S_FLIP/AT_P90), group(FAILURE_SIGNAL_WITH_5M/FAILURE_SIGNAL_AGAINST_5M/NOT_5S_ENTERED — row-level category), n, n_total_8950, n_5s_entered_8379, n_not_5s_entered_571, confirm_pct, failure_pct, ppv_failure, conditional_exit_return_mean, accepted_continuation_return_mean` |
| 12 | `results/stop_075_context.csv` | table | Phase 9: `group(WITH_5M/AGAINST_5M/NOT_5S_ENTERED — row-level category), n_confirming, n_total_8950, n_5s_entered_8379, n_not_5s_entered_571, pct_mae_gt_075, failure_loss_reduction_075_vs_100` |
| 13 | `results/full_economics.csv` | table | Phase 10: `group, n_arms, expectancy_per_arm, gross_atr_total, net_atr_total, profit_factor, win_rate, max_dd_atr, mean_winner, mean_loser, flip_exit_winner_pct, flip_exit_loser_pct, confirmed_then_stopped_pct, mfe_mean, mae_mean, giveback_mean, capture_ratio_mean` |
| 14 | `results/full_economics_by_year.csv` | table | as #13 + `entry_year` |
| 15 | `results/full_economics_by_side.csv` | table | as #13 + `side` |
| 16 | `results/matched_stratified_control.csv` | table | Phase 11: `stratum_vars, n_cells, n_with, n_against, raw_delta_confirm_rate, stratified_delta_confirm_rate, raw_delta_return_at_confirm, stratified_delta_return_at_confirm, raw_delta_p_mfe_ge_3atr, stratified_delta_p_mfe_ge_3atr, delta_ci_low, delta_ci_high, ci_excludes_zero` |
| 17 | `results/primary_table.csv` | table | the top-of-report summary: `metric, WITH_5M, AGAINST_5M` rows for P90 arms, %, P(confirm<1ATR), median sec to confirm, MAE p50/p75/p90, median return@confirm, median eventual MaxMFE, P(MFE≥3ATR), P(MFE≥4ATR), baseline net ATR/arm, MaxDD |
| 18 | `results/validation_report.json` | json | every gate, `expected`/`observed`/`pass` |
| 19 | `results/summary.json` | json | verdict, `secondary_signals`, headline numbers |
| 20 | `results/partition_manifest.json` | json | input paths + sizes + row counts, code hash, seeds, frozen constants (age buckets, time-of-day windows, score quartile edges) |
| 21 | `_work/regime_5m_build.json` | json | build reconciliation + runtime cross-check agreement rate |
| 22 | `SPEC.md` / `README.md` / `REPORT.md` | docs | this contract; how to run; the answered questions |
| 23 | `audit/status.json` | json | roll-up with a key per agent; `critical: 0` required |

`*.parquet`/`*.csv` under `results/` and `_work/` are generated and **not
committed**. JSON manifests and `SPEC.md`/`README.md`/`REPORT.md` are
committed. All are regenerable from `run_study.py`.

### 8.1 Domain & completeness contract

- **Expected partition grid:** every output table partitions the 8,950 (or the
  4,656-confirming, or the 8,379-entered, as declared per §5.1) population
  exactly — no silent row loss.
- **Boundary convention:** age buckets and time-of-day windows are closed on
  the left, open on the right (`[a, b)`), except the final unbounded bucket.
- **Zero-row / missing-partition behavior:** applies to every bucketed table
  in §8 (Phase 1 age×side×year, Phase 3 speed buckets, Phase 4 MFE buckets,
  Phase 6 timing buckets, Phase 7 age buckets, Phase 11 strata) — an empty
  bucket/cell is retained with `n=0` in its row, not silently omitted; Phase
  11 additionally excludes `n=0` cells from the exposure-weighted average.
- **Global validation:** row counts across every WITH/AGAINST/UNINIT split
  reconcile to 8,950 (Phase 1, 6, 7, 10, 11), 4,656 (Phase 2–5), or the
  8,950/8,379/571 split of §5.1 (Phase 8, 9) before finalization; checked in
  `validate.py`.

### 8.2 Terminal decision labels

See §7's table — `M1`–`M5` and `ABORT_LINEAGE_FAILURE` are the complete,
exhaustive set of reachable labels.

---

## 9. Stop conditions — abort rather than produce a weak result

1. Armed population height ≠ 8,950 → **ABORT**.
2. Lineage reconciliation (labels/years/sides/confirm-rate/MAE refs) fails any
   check → **ABORT**.
3. 5m bucket/row reconciliation (§2) fails — i.e. `buckets_reconcile` or
   `rows_reconcile` in `_work/regime_5m_build.json` is `false` — → **ABORT**.
4. Parity test (§2.1) fails → **ABORT before any classification runs**.
5. Any P90- or confirm-timestamp query resolves a flip with
   `close_ts > decision_ts` → **ABORT**.
6. A `label_only_` column appears outside `phase6_timing.csv` → **ABORT**.
7. Any `state_at`/`age_*` call is issued a 2026+ timestamp → **ABORT**.

---

## 10. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/p90_5m_regime_context` exits 0.
- Pre-execution: `lookahead-auditor` scoped to §2–§5 (5m engine causality,
  P90/confirm classification, Phase 6 label-only isolation, Phase 11's
  no-future-outcome matching).
- Pre-execution: `contract-checker` scoped to §7–§9 (Deliverables Manifest,
  terminal-label reachability, verdict thresholds marked as frozen
  illustrative defaults rather than silently authoritative).
- Completion: both re-run against final `results/`; new numbered pass files
  each time (`audit/pass_NN.md`, `audit/contract_pass_NN.md`), prior findings
  adjudicated first, max 3 new CRITICALs per pass; `audit/status.json` shows
  `critical: 0`.
- Executed via `scripts/run_bounded_study.py` wrapping `run_study.py`; status
  read from its JSON card, never raw logs.

---

## 11. No optimisation

Forbidden: any entry filter, exit rule, or stop-distance rule derived from
this study's findings; tuning of age buckets, time-of-day windows, MFE
buckets, or `arm_score` quartile edges to maximize any separation; treating
Phase 6's future-flip timestamp as anything but a label. Phases 1–11 are all
descriptive and may not produce a rule used by any policy — there is no
policy in this study to use one.
