# Look-Ahead & Timestamp Audit — COMPLETION GATE (analysis layer)

**Date:** 2026-07-09
**Scope:** `studies/adaptive_rank_filter_walkforward/build_episode_status.py`,
`parse_nt_results.py`, `compute_metrics.py`, `compute_retention_tail.py`,
`compute_bootstrap.py`, `compute_matched_random.py`, `build_parity_audit.py`,
`build_provenance_audit.py`, `write_final_report.py`, `run_all_analysis.py`,
plus `results/final_report.md` (numbers claimed) and direct empirical
recomputation from `_work/*.parquet` and `results/*.parquet`.
**Trigger:** Mandatory completion gate per CLAUDE.md, covering the analysis
layer built and run *after* the pre-execution gate
(`results/pre_execution_lookahead_audit.md`, which covered the training/NT
wiring only and did not review this layer).
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 2
- Note: 3

**Verdict: PASS_WITH_WARNINGS.** The fixed `merge_asof` join in
`build_episode_status.py` is safe and correctly reasoned — verified
empirically, not just by code reading. No exact-equality atlas-vs-NT
timestamp join was found anywhere downstream of that file. The
`write_final_report.py` criteria-evaluation fix is internally consistent and
independently reproduced from raw parquet files. Two WARNINGs are flagged:
one documentation-accuracy issue in a study whose entire premise is
timestamp-join correctness, and one about the matched-random control's
stratification variable (already self-disclosed in the docstring, assessed
here for materiality). Neither changes the reported verdict (INCONCLUSIVE,
4/7 criteria met) or corrupts any number in `final_report.md`.

## Findings

### [Item 1] `build_episode_status.py:44-57` — `merge_asof(direction="nearest")` is safe here; empirically verified, not just reasoned

**Is `nearest` (vs `backward`) safe for this post-hoc join?** Yes, and more:
`backward` would have been *actively wrong*, not merely a stricter-but-safe
alternative. I pulled the raw matched gaps (`confirmation_ts - decision_ts`)
for every r0 match and found the distribution is **always negative**
(mean -1.75s, min -1s, max -20s, n=15,559) — i.e. the atlas's
`observation_time` is *systematically earlier* than NT's `decision_ts` by
1–20 seconds, never later. `merge_asof(direction="backward")` only matches
`other` rows at or *before* `base`'s timestamp; since NT's `decision_ts` is
always *after* the atlas's `confirmation_ts` here, `direction="backward"`
would find **zero matches**, silently reproducing the exact class of bug
this fix was written to resolve. `direction="nearest"` (or `"forward"`) is
the only correct choice given the empirical sign of the cross-pipeline
offset. `CollectorV2Strategy`'s own live skip-matching uses `backward`
for a different reason entirely (a live decision must never consult a
skip-list entry that arrives after the decision instant) — that constraint
does not apply here because both sides of this join are already fully
realized, historical, and known in full at analysis time. No look-ahead risk
exists in a join between two already-complete datasets; `nearest` is the
right tool for closest-logical-match reconciliation, not a causal-order
lookup, and using `backward` here would have been the actual bug.

**Could a single NT-side record match multiple atlas episodes (double
counting)?** No — verified empirically, not just estimated. The minimum gap
between any two consecutive eligible atlas `confirmation_ts` values (sorted,
n=15,629) is **120 seconds**, i.e. zero atlas episodes are within 40 seconds
(2x the 20s tolerance) of each other, and zero are within 20 seconds. This
makes it structurally impossible for one NT record's 20s tolerance window to
overlap two different atlas episodes' tolerance windows. Independently
re-ran the join's own `asof_join` helper for the r0 policy and confirmed
`matched['decision_ts'].duplicated().sum() == 0` across all 15,559 matches —
no NT decision_ts was consumed by more than one atlas row. **Confirmed
clean.**

### [Item 2] No exact-equality atlas-vs-NT timestamp join found downstream of `build_episode_status.py`

Read all of `parse_nt_results.py`, `compute_metrics.py`,
`compute_retention_tail.py`, `compute_bootstrap.py`,
`compute_matched_random.py`. All operate exclusively on `confirmation_ts`
(the atlas-native key, copied unchanged into every policy's row of
`episode_status.parquet` by `build_episode_status.py`) as the join/index key
— e.g. `compute_retention_tail.py:34-35`'s `r0.set_index("confirmation_ts")`
/ `pol.set_index("confirmation_ts")`, `compute_bootstrap.py:58-59`,
`compute_matched_random.py:32-33`. None of these re-derive or re-join
against raw atlas `observation_time` or raw NT `decision_ts` directly — they
consume the already-resolved `episode_status.parquet`. Confirmed no
duplicate-index blowup risk in these joins either, since `confirmation_ts`
is unique across the full 15,629-row eligible population (verified:
`eligible['observation_time'].duplicated().sum() == 0`) and filtering to a
contiguous date block preserves uniqueness.

`build_parity_audit.py:30-40` **does** perform an exact-equality join on
`decision_ts` (`pol_idx.join(r0_idx, ...)`), but this is NT-vs-NT (two
independent `BacktestEngine` runs of the same underlying causal event
stream, comparing policy X's trade record to R0's trade record for the same
`period_key`), not atlas-vs-NT. Both sides come from the same deterministic
replay engine driven by identical catalog data, so `decision_ts` for the
same logical signal should be bit-identical across runs regardless of
position-occupancy differences — and this is exactly what was found:
0 mismatches, 0 "not in r0 at all" across all 22 policy x period-key
combinations (`nt_parity_audit.parquet`, independently re-read and
tabulated). Exact equality is the *correct* choice here, not a repeat of the
atlas-vs-NT bug class.

`parse_nt_results.py`'s module docstring (line 3-4) claims the file's output
is "joined back to the F2 atlas via decision_ts == confirmation_ts" — **this
join does not actually happen in this file** (it only loads/concatenates raw
NT parquet outputs and tags `deploy_month`; the real join is in
`build_episode_status.py`). This is stale/inaccurate documentation, not a
behavioral bug — flagged as a NOTE below given how directly relevant
accurate documentation is to this exact bug class.

### [Item 3] `compute_matched_random.py` — global ATR tercile stratification variable: WARNING, immaterial to the reported verdict

Confirmed the module docstring (lines 10-14) explicitly and clearly
discloses that `atr_bucket_static` is a single global tercile split over the
full Jan2025-Apr2026 population, distinct from the per-fold
validation-frozen ATR edges recorded in `model_training_audit.parquet`
(confirmed these are genuinely different columns that never mix: `atr_bucket`
in `train_adaptive_models.py:117` is written only to
`adaptive_skip_decisions.parquet` and never carried into
`eligible_population.parquet` / `episode_status.parquet`; `atr_bucket_static`
is computed independently in `build_episode_status.py:69` via `pd.qcut`).

Assessment: this is **not a leakage issue** in the classic sense — ATR is a
causal feature (known at signal time), not an outcome, so using a
whole-sample view of its distribution to define stratification bucket
*edges* does not inject future outcome information into any trade decision
or into the real (non-random) policies' PnL. It is, however, a deviation
from the task brief's literal "validation-frozen ATR bucket" framing: the
matched-random control's strata are coarser/differently-bounded than the
buckets some of the real per-fold models were actually conditioned against
(via `R2_EXEMPT_COL`/`R4_EXEMPT_COL` thresholds, which are unrelated to ATR
tercile boundaries anyway — so the practical divergence is likely smaller
than it sounds). Given the actual matched-random p-values reported for the
verdict-driving policy (`a4_6m`: p=0.4040, and all nine adaptive policies'
final-reserved p-values range 0.19–0.71 — nowhere near a decision boundary
like 0.05 or 0.10), this simplification would need to be very substantially
wrong to flip any conclusion. **WARNING, not CRITICAL** — flag as a
documented simplification whose imprecision does not change the verdict in
this run, but should be tightened (recompute strata from the correct
per-fold frozen edges) if this control is ever relied on for a
closer-to-threshold result in a future study.

### [Item 4] `write_final_report.py` — criteria/verdict fix verified correct and internally consistent by independent recomputation

Independently recomputed, from raw parquet files (not by re-reading the
report's own printed numbers), the following claims in `final_report.md` and
confirmed exact agreement:

- `STATIC R4 FINAL EV LIFT: $-4.28` = `static_r4.ev_per_eligible_signal
  (-25.1691) - r0.ev_per_eligible_signal (-20.8842)` = `-4.2849` ✓ (from
  `final_reserved_results.parquet`, recomputed directly)
- `BEST ADAPTIVE FINAL EV LIFT: $2.70` (a4_6m vs r0) — recomputed
  `mean(a4_6m contrib) - mean(r0 contrib)` directly from
  `episode_status.parquet` for the `2026_MarApr_final_reserved` block:
  `-18.1881 - (-20.8842) = 2.6961` ✓, matches `paired_bootstrap.parquet`'s
  real_lift for `(a4_6m, r0)` exactly.
- `a4_6m` vs `static_r4` lift `$6.98` — recomputed directly from
  `episode_status.parquet`: `-18.1881 - (-25.1691) = 6.9810` ✓, matches
  bootstrap table exactly.
- `MONTHS POSITIVE: 7/16` — recomputed from `monthly_results.parquet`
  filtered to `policy == "a4_6m"`: exactly 7 of 16 months have
  `ev_per_eligible_signal >= 0` ✓.
- `BEST ADAPTIVE TOP-DECILE RUNNER RETENTION: 93.8%` — matches
  `runner_retention.parquet`'s `a4_6m`/`top10pct` row (`0.9381`) exactly ✓.
- `BEST ADAPTIVE MATCHED-RANDOM P: 0.4040` — matches
  `matched_random_summary.parquet`'s `a4_6m` row exactly ✓.

Checked every entry in the `criteria` dict (`write_final_report.py:111-119`)
for the same "evaluated against the wrong policy" bug class described for
the pre-fix version: all seven criteria (`a4_vs_static_lift`,
`a4_own_lift_vs_r0`, `top_decile_retention`, `matched_p`,
`monthly_positive_count(monthly, best_policy)`, `driven_by_tail`) are
computed by filtering on `policy == best_policy` (the best-performing A4
window, `a4_6m`), consistently — no criterion silently references
`overall_best`/`a1_3m` or any other policy. The one exception,
`"no execution/provenance violations"`, is intentionally global
(study-wide execution integrity, not a per-policy comparison) — appropriate,
not a bug. Verdict logic (`n_criteria_met == len(criteria)` /
`a4_vs_static_lift <= 0 and a4_own_lift_vs_r0 <= 0` / else `INCONCLUSIVE`)
was traced by hand against the actual criteria values (4/7 met, both lift
values positive) and correctly produces `INCONCLUSIVE`, matching the report.
**Confirmed correct and internally consistent.**

Minor code-hygiene note (not flagged as a finding requiring a fix): the
`static_r4_lift` parameter passed into `best_adaptive_policy()`
(`write_final_report.py:29-31`) is unused inside that function body — dead
parameter, harmless.

### [Item 5] `net_pnl` cost-basis and units: confirmed consistent, $10/RT everywhere used in aggregation

Traced `net_pnl`'s origin to `CollectorV2Strategy._finalize_trade`
(`collectors/collector_v2/strategy.py:1143-1151`): `cost =
commission_per_rt (5.0) + tick_dollar (5.0) = 10.0`; `net_pnl = gross_pnl -
cost`. Grepped every analysis-layer file for `baseline_pnl` — it appears
only in `build_episode_status.py:74` (carried through as a descriptive
column into `episode_status.parquet`, never read again after that) and in
`train_adaptive_models.py` (used only for in-fold threshold/ev_lift
selection on the *validation* month during training — out of this pass's
scope, previously covered by the pre-execution gate). No downstream
metrics file (`compute_metrics.py`, `compute_retention_tail.py`,
`compute_bootstrap.py`, `compute_matched_random.py`, `write_final_report.py`)
references `baseline_pnl` at all — confirmed by direct grep, zero hits.
`net_pnl` ($10/RT, NT-executed) is exclusively what's summed/averaged
everywhere in `final_report.md`. **Confirmed clean — no cost-basis mixing.**

## Note-level observations (not findings requiring action)

### `episode_status.parquet` has a uniform, symmetric 68-episode (0.44%) "unresolved" residual across all 12 policies — does not bias comparisons, but is not surfaced anywhere in the report

Direct computation: every one of the 12 policies has exactly 68 unresolved
episodes (neither skipped, canceled, nor filled within the 20s tolerance),
and — critically — it is the **same 68 confirmation_ts values** for all 12
policies (verified: 100% overlap with r0's unresolved set for every other
policy, zero policy-specific unresolved episodes). Of r0's 68, 47 have
`trade_status == "filled"` in the atlas (i.e., the atlas expected a fill but
no NT trade matched within tolerance) and 21 are
`pending_entry_canceled`. Several cluster at exactly `16:00:00` local time
(session-close-adjacent), suggesting a genuine execution/session-boundary
divergence rather than a borderline tolerance miss (gaps here are likely
much larger than 20s, since raising the tolerance wouldn't plausibly recover
session-boundary non-fills). Because the set is identical across all 12
policies and both sides of every comparison (`basic_metrics`,
`build_pairs`, `matched_random_sim`) treat unresolved episodes as a
0-contribution row in a shared denominator, this has **zero effect on any
relative comparison, lift, CI, or p-value** in the report — it only
marginally affects the absolute magnitude of `ev_per_eligible_signal` for
every policy equally (by a fixed, uniform ~0.44% dilution). Flagging as a
transparency gap only: `provenance_audit.json`'s assertions do not include
an explicit "unresolved episode count" check, and `final_report.md` never
surfaces this number. Recommended (not applied): add an
`unresolved_episode_count` field to `provenance_audit.json` and a line in
`final_report.md` so this residual is visible rather than only discoverable
by direct inspection of `episode_status.parquet`.

### `parse_nt_results.py:3-4` docstring is stale — claims a join that doesn't happen in this file

See Item 2 above. Recommended (not applied): update the docstring to say
the atlas join happens in `build_episode_status.py`, not here — in a study
whose central bug was a timestamp-join defect, a docstring that describes a
join the file doesn't actually perform is exactly the kind of thing that
could mislead a future reader (or auditor) into skipping the file that
actually needs scrutiny.

### Matched-random boundary case: one r0 match sits at exactly the 20s tolerance edge

The empirical gap distribution's max is exactly `-20.0` seconds (i.e. right
at `JOIN_TOLERANCE_NS`). Given the 120s minimum atlas-episode spacing proven
above, this edge match is still unambiguous (no competing candidate within
100s), so it is not a defect — noting only because a tolerance parameter
whose actual usage grazes its own boundary is worth knowing about if the
tolerance is ever tightened in a future study.

## Clean checks

- **`merge_asof(direction="nearest")` safety** — proven both by reasoning
  (post-hoc reconciliation of two fully-realized datasets has no causal
  look-ahead exposure) and by two independent empirical checks (120s minimum
  atlas-episode spacing rules out double-matching; zero duplicated
  `decision_ts` assignments found directly).
- **No exact-equality atlas-vs-NT join reintroduced anywhere downstream**
  of `build_episode_status.py` — confirmed by direct reading of all five
  downstream analysis files plus `build_parity_audit.py`.
- **`build_parity_audit.py`'s exact-equality join is the correct tool** for
  its NT-vs-NT (not atlas-vs-NT) use case — confirmed 0 mismatches, 0
  unmatched-in-r0 across all 22 policy x period combinations, consistent
  with `CollectorV2Strategy` producing deterministic `decision_ts` values
  independent of per-run position-occupancy differences.
- **`net_pnl` ($10/RT) vs `baseline_pnl` ($5/RT) cost-basis separation** —
  confirmed no downstream analysis file references `baseline_pnl`; all
  reported EV/PnL figures derive exclusively from NT-executed `net_pnl`.
- **`write_final_report.py` criteria dict** — all seven criteria verified
  evaluated against the same policy (`best_policy` = best-performing A4
  window) except the intentionally-global provenance/parity check; verdict
  logic hand-traced and correctly reproduces `INCONCLUSIVE`.
- **Five independently recomputed report numbers** (static R4 lift, best
  adaptive lift vs R0, best adaptive lift vs static R4, months-positive
  count, top-decile retention, matched-random p) all reproduced exactly
  from raw parquet files, not merely re-read from the report.
- **`atr_bucket` (per-fold, training-frozen) vs `atr_bucket_static` (global
  tercile, analysis-layer)** — confirmed these are genuinely separate
  columns that are never accidentally merged or substituted for one another.
- **`run_all_analysis.py` step ordering** — confirmed each step's inputs are
  produced by an earlier step in the chain (`parse_nt_results` ->
  `build_episode_status` -> `build_parity_audit` -> `compute_metrics` ->
  `compute_retention_tail` -> `compute_bootstrap` -> `compute_matched_random`
  -> `build_provenance_audit` -> `write_final_report`); no step reads a file
  produced by a later step.

---

*Audit complete. Findings reflect read-only static analysis plus direct
empirical verification (pandas re-reads of `_work/*.parquet` and
`results/*.parquet`, independent recomputation of 5+ headline numbers,
direct execution of the join helper functions against the real data). This
audit did not re-execute any NT backtest and did not re-derive the causal
correctness of the 149 upstream features or the training/fold logic
(covered by `pre_execution_lookahead_audit.md`) — it is scoped to the
analysis layer (parse -> join -> metrics -> report) built after that gate.*
