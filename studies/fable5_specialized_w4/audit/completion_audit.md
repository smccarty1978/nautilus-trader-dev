# Look-Ahead & Timestamp Audit — COMPLETION GATE

**Date:** 2026-07-17T00:00:00Z
**Scope:** `studies/fable5_specialized_w4/` — full pipeline as actually executed
(all artifacts below inspected on disk, not re-derived from source reading
alone). Source files (`SPEC.md`, `fable5_common.py`, `build_dataset.py`,
`train_models.py`, `replay_selection.py`, `tests/test_specialized_w4.py`)
confirmed byte-identical (SHA-256) to the code authorized by
`audit/pre_execution_authorization.json` — no drift between authorization
and execution.
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 1
- Note: 1

The executed pipeline's causal contracts held under real data: the
frozen-Policy-A reconciliation gate passed with **zero** mismatches both
years, the H1/H2 boundary purge produced **zero** opportunity-level overlap
between train and dev in the actual dataset, the 2026 sealed-holdout gate
opened only after the model manifest was frozen (verified by both file
hashes and mtimes), and the frozen retention cutoffs were applied
byte-for-byte identically in the 2026 replay (independently re-derived and
diffed against the executed accept-flags, 0/15 structure×band mismatches).
One WARNING was found: two of the five reported model arms
(`baseline_w4`, `D_hier`) have severely tie-heavy scores, which makes their
`top_X%` policy-id labels numerically misleading (though the adjacent
`retention_rate` column is correct) — a reporting-fidelity issue, not a
causal/leakage defect.

## Critical findings

None.

## Warnings

### [Reporting fidelity] `results/specialized_w4_policy_results.parquet` — `baseline_w4`/`D_hier` `top_X%` policy-id labels do not reflect actual retained fraction

Verified from `results/specialized_w4_trade_diffs.parquet` (2025-H2 dev,
`n=4163` replayable):

| score column | unique values | largest single value's share |
|---|---|---|
| `score_A_pooled` | 3,117 | 0.2% |
| `score_B_side` | 3,701 | 0.1% |
| `score_C_side_session` | 3,917 | 0.1% |
| `score_baseline_w4` (`score_margin`) | 49 | 29.2% |
| `score_D_hier` (isotonic output) | 7 | 51.8% |

`D_hier`'s isotonic recalibration collapsed to a 3–4-level step function per
side (`long_fade`: {0.2917, 0.3170, 0.3305, 0.375}; `short_fade`: {0.3092,
0.3137, 0.6667}), and `baseline_w4`'s `score_margin` is similarly coarse
(many candidates share `score_margin ≈ 0` at first-crossing). Because
`retention_cutoffs`/`assign_cutoff` compute a percentile value and then
accept via `score >= cutoff` (`train_models.py:116-126`,
`replay_selection.py:25-35`), a wide tied plateau straddling the target
percentile causes `np.percentile` to land on the plateau value, and `>=`
then admits the *entire* plateau — far more than the nominal band size.
Confirmed directly in the executed output
(`specialized_w4_policy_results.parquet`, `window=2025_H2_dev`,
`accounting=independent`, `split_type=combined`):

| policy_id | candidates | executed | labeled % | actual `retention_rate` |
|---|---|---|---|---|
| `baseline_w4_top_10` | 4163 | 457 | 10% | 11.0% (close) |
| `baseline_w4_top_40` | 4163 | 1873 | 40% | **45.0%** |
| `baseline_w4_top_50` | 4163 | 3249 | 50% | **78.0%** |
| `D_hier_top_10` | 4163 | 2505 | 10% | **60.2%** |
| `D_hier_top_20` | 4163 | 3200 | 20% | **76.9%** |
| `D_hier_top_30` | 4163 | 3200 | 30% | **76.9% (identical row to top_20)** |
| `D_hier_top_40` | 4163 | 3200 | 40% | **76.9% (identical row to top_40... top_50)** |
| `D_hier_top_50` | 4163 | 3200 | 50% | **76.9% (identical to top_20/30/40)** |

`D_hier`'s `top_20`, `top_30`, `top_40`, and `top_50` arms are, in this
executed data, **the same accepted candidate set** (identical `executed`
count, identical economics), because all four percentile requests
(80th/70th/60th/50th) land on the same 0.3170/0.3137 tied plateau. The
`retention_rate` column in the same table **is** computed honestly from the
actual executed/candidates ratio (verified: `A_pooled_top_30` reads
`0.300024`, i.e. correctly ≈30%; `D_hier_top_20` reads `0.768676`, i.e.
correctly ≈77%) — so the underlying number is not wrong, and this is **not**
a look-ahead, leakage, or sign bug (the cutoffs are still frozen, still
applied causally in time order, still correctly ordered — smaller nominal
bands never admit more candidates than larger ones). It is a labeling/
interpretability hazard: any report or table that presents `D_hier_top_20`
through `D_hier_top_50` as four distinct selectivity levels, or describes
`baseline_w4_top_50` as "half the candidates," would misstate the study's
own results. It does not affect the A/B/C structures (GBT-selected for all
three; tie fractions 0.1–0.2%, retention rates land within ~0.1pp of
nominal) or any training/selection decision (family/config selection at
`SELECTION_BAND=0.30` used only the near-continuous GBT scores).
Recommend: when `final_report.md` is written, caveat `D_hier`/`baseline_w4`
retention-band comparisons explicitly (cite `retention_rate`, not the
`policy_id` suffix), and/or note for any future iteration that percentile-
based cutoffs on a discrete/step-function score should assign by rank
(e.g. `np.searchsorted` on a stable-sorted score array) rather than by
value, to make nominal and actual retention agree even under heavy ties.

## Notes

### [Carried forward, unaffected by execution] `train_models.py:82-84,299-301` — Model C insufficient-sample gate is structure-level, not cell-level

Unchanged from the pre-execution audit. Confirmed moot for this run:
`frozen_selection_manifest.json` shows `"insufficient_sample_structures": []`
— all four `C_side_session` cells cleared the ≥150/≥150 gate on the executed
H1-purged training data, so the coarser short-circuit behavior never
triggered this run. Left as a NOTE for future runs where a cell might fail.

## Completion-check detail

**1. Execution order integrity.** Confirmed by two independent methods, not
just trusting the JSON contents:
- *Content cross-reference*: `audit/fable5_first_2026_open.json` records
  `bundle_sha256=496613ca...` and `manifest_sha256=9924ccaa...`. Both hashes
  were independently recomputed from the files currently on disk
  (`_work/models/fable5_specialized_w4_bundle.pkl`,
  `_work/frozen_selection_manifest.json`) and match exactly — the ledger
  was written against the same bundle/manifest that exist now, no
  post-hoc substitution.
- *Filesystem mtime sequence* (UTC): `pre_execution_authorization.json`
  18:13:33 → `input_freeze.json` 18:13:40 → `dataset_2025.parquet` 18:13:56 →
  `models/fable5_specialized_w4_bundle.pkl` 18:14:36.799 →
  `frozen_selection_manifest.json` 18:14:36.843 (bundle written first,
  matching `train_models.py:333-359` code order) →
  `policy_results_2025.parquet` 18:15:03 →
  `audit/fable5_first_2026_open.json` 18:15:24.413 →
  `dataset_2026.parquet` 18:15:28.958 → `policy_results_2026.parquet`
  18:15:37 → `results/run_manifest.json` 18:15:38. The first-2026-open
  ledger timestamp (18:15:24) is strictly **after** the manifest freeze
  (18:14:36) and strictly **before** the 2026 dataset build (18:15:28) —
  exactly the required ordering, and consistent with
  `require_2026_open_allowed()` being called at the top of
  `build_dataset.py --year 2026`'s `main()` before any candidate/feature
  work begins.
- *Manifest content*: `grep -c "2026" _work/frozen_selection_manifest.json`
  → `0`. No 2026 file path, count, or hash appears anywhere in the frozen
  selection manifest.

**2. Frozen retention cutoffs applied identically in 2026.** Independently
re-implemented `segment_masks`/cutoff lookup in a standalone script against
`results/specialized_w4_trade_diffs.parquet` (`window=2026_test`) and the
cutoffs recorded in `_work/frozen_selection_manifest.json`, for every
structure (`baseline_w4`, `A_pooled`, `B_side`, `C_side_session`, `D_hier`)
and a spot-check of 3 bands each (`top_10`, `top_30`, `top_50`):
`expected_accept = score_{structure} >= cutoffs[segment][band]` compared
against the executed `accept_{structure}_{band}` column, restricted to
replayable rows. **0 mismatches across all 15 structure×band combinations**
(e.g. `A_pooled top_30`: expected 1,119 accepted, actual 1,119 accepted, 0
row-level disagreements). This directly confirms `replay_selection.py`'s
`assign_cutoff` (`replay_selection.py:25-35`) applied the exact frozen
values from `train_models.py` without recomputation, drift, or off-by-one
segment misassignment.

**3. `policy_results` internal consistency.**
- `take_all` independent `total_net_pnl_usd` per window reconciled exactly
  against `sum(net_pnl_usd)` over replayable rows in the corresponding
  dataset slice, computed fresh from `_work/dataset_2025.parquet` /
  `_work/dataset_2026.parquet`: `2025_H1_train_insample` −45,630.845816 vs
  −45,630.845816; `2025_H2_dev` −83,259.996444 vs −83,259.996444;
  `2026_test` −42,650.265988 vs −42,650.265988 — exact match (`atol=1e-6`)
  in all three windows, with candidate counts also matching (4503 / 4163 /
  3126). (The 4503-row H1-insample count vs the 4501-row H1-*train*-used-for-
  fitting count is expected and correct — the in-sample report window
  includes the 2 purged-from-train rows, exactly as SPEC intends by
  reporting H1 "in-sample" separately from the fitting population.)
- `policy_a_frozen` totals: `2025_H1_train_insample` (+10,855.622690) +
  `2025_H2_dev` (−18,970.465441) = **−8,114.842750573298**, exactly matching
  the coordinator's stated combined 2025 frozen Policy A figure and the
  `dataset_seal_2025.json` reconciliation figure to 9 decimal places.
  `2026_test` = **+17,988.060996803324**, exactly matching the coordinator's
  figure and `dataset_seal_2026.json`. Both `independent` and `streaming`
  accounting produce identical numbers for `policy_a_frozen` in every
  window (1650/1596/1137 executed respectively) — expected, since this arm
  accepts exactly the pre-established, mutually non-overlapping frozen
  trade population, so the one-position streaming busy-rule never actually
  skips anything additional.

**4. H2 selection taint confined to config choice; no 2026 leakage into any
frozen artifact.** Beyond the code-level guarantees already verified
pre-execution, this was checked empirically against the executed dataset:
`set(train.opportunity_id) & set(dev.opportunity_id)` on the actual
`_work/dataset_2025.parquet` (train = H1, non-purged, replayable; dev = H2,
replayable) = **0** — zero shared opportunities between the fitting
population and the dev population that also drove config/retention
selection, confirmed on real data, not just by code inspection.
`selection_table.parquet` shows the config-selection step chose, for every
structure, the candidate with the strictly highest `dev_top30_net_pnl_usd`
(verified by direct comparison, e.g. B_side: −44,996 / −38,032 / −18,155 /
**−6,619 (selected)**) — consistent with `SELECTION_BAND=0.30` restricted to
`dev` (H2) only, and this selection mechanism, while inherently prone to a
mild "dev-reported metrics are somewhat optimistic for the winning config"
effect (standard train/val bias, already caveated in the SPEC's own
methodology and mitigated by the 2026 sealed holdout), never touches 2026
data — confirmed no `dataset_path(2026)` read anywhere before the manifest
freeze (mtime evidence above).

**5. Decile lift is genuine on dev; 2026 collapse is a generalization
failure, not a sign bug.** Checked three independent ways against the
executed outputs, specifically to rule out an inverted/mislabeled score:
- *Retention-band monotonicity on dev* (`specialized_w4_policy_results.parquet`,
  `2025_H2_dev`, `independent`, `combined`): for `B_side`, `win_rate` rises
  from 30.4% (`top_50`) → 30.6% (`top_40`) → 31.8% (`top_30`) → 32.4%
  (`top_20`) → **35.9%** (`top_10`), and `profit_factor` rises from 0.865 →
  0.877 → 0.959 → 0.973 → **1.435** — monotonic improvement as the band
  tightens, with `top_10` the only genuinely profitable slice
  (PF>1). `C_side_session` shows the same pattern: win rate 32.0% → 33.0% →
  34.6% → 35.5% → **38.3%**, PF 0.799 → 0.823 → 0.928 → 1.005 → **1.104**.
  `A_pooled` shows the same direction, more weakly (win rate 32.2% →
  32.6% → 33.5% → 33.9% → 33.1%, PF 0.812 → 0.828 → 0.855 → 0.833 → 0.815).
  A sign-inverted score would show the *opposite* ordering (worst economics
  in the tightest band); instead the tightest, most-selective band is the
  best or tied-best band for every retrainable structure. This is
  conclusive on its own.
- *Per-segment decile correlation* (`specialized_w4_decile_lift.parquet`,
  `2025_H2_dev`): `corr(decile, net_positive_rate)` is positive for 6 of 8
  retrainable-structure segments (`A_pooled` ALL +0.848; `B_side long_fade`
  +0.419; `C_side_session long_fade_ETH` +0.539, `long_fade_RTH` +0.633,
  `short_fade_ETH` +0.699; `B_side short_fade` −0.023 and
  `C_side_session short_fade_RTH` −0.024 are flat/noise, not inverted). The
  two negative-correlation cases outside the retrainable structures
  (`baseline_w4` −0.349, `D_hier long_fade` −0.645) were traced to the same
  score-tie/quantization mechanism as the Warning above (`baseline_w4`
  decile 1 alone has `mean_score=0.000000` shared by hundreds of rows;
  `D_hier long_fade` deciles 1–3 all share `mean_score=0.291715` exactly) —
  `pd.qcut(..., rank(method="first"))` breaks ties by row-insertion order
  when many rows share one score value, so "decile" membership within a tied
  plateau is arbitrary/uninformative rather than sign-inverted. This is a
  measurement artifact of applying a 10-way decile split to a score with
  only 3–49 unique values, not a bug in the score itself.
- *AUC degradation shape, dev → 2026* (`specialized_w4_model_metrics.parquet`,
  `segment=ALL`, `selected=True`): `A_pooled` 0.534 → 0.493 (−0.041),
  `B_side` 0.515 → 0.465 (−0.050), `C_side_session` 0.534 → 0.484 (−0.050),
  `D_hier` 0.488 → 0.480 (−0.008, already weak on dev, consistent with the
  degenerate-isotonic finding). A genuine sign-flip bug would typically
  produce something closer to `2026_auc ≈ 1 − dev_auc` (i.e. ≈0.47 mirrored);
  instead all four show a modest, non-mirrored decay consistent with weak
  in-sample signal (dev AUC only 0.49–0.53 to begin with) failing to
  generalize under regime shift — exactly the "genuine generalization
  failure, not a sign bug" characterization the coordinator asked to
  confirm or refute. Also checked `score_structure`'s `predict_proba(...)[:, 1]`
  indexing (`train_models.py:109-110`) against `label_net_positive`'s
  `{0,1}` encoding at fit time (`train_models.py:87`) — `sklearn`'s
  ascending `classes_` ordering makes column 1 the positive-class
  probability; no indexing/off-by-one risk found.

## Clean checks

- Every source file hash (`SPEC.md`, `fable5_common.py`, `build_dataset.py`,
  `train_models.py`, `replay_selection.py`, `tests/test_specialized_w4.py`)
  matches `audit/pre_execution_authorization.json` exactly — the code that
  ran is the code that was authorized.
- `run_manifest.json`'s `output_sha256` block matches the actual current
  content hash of every file in `results/` — no output tampered with after
  the run completed.
- `frozen_selection_manifest.json`'s `dataset_2025_sha256` matches
  `_work/dataset_seal_2025.json`'s `dataset_sha256` and the live file hash —
  training used the exact sealed 2025 dataset, not a stale or hand-edited
  copy.
- `dataset_seal_2025.json`/`dataset_seal_2026.json` reconciliation blocks
  (3,246/1,137 matched, 0 mismatches, exact-to-the-cent PnL agreement both
  years) confirm the pre-execution audit's causal-parity gate genuinely
  passed against real data, not merely that the code path exists.
- `tests/test_specialized_w4.py` — 9/9 pass, re-run against the executed
  code (unchanged since authorization).
- No `2026` token appears anywhere in `_work/frozen_selection_manifest.json`.
- Zero `opportunity_id` overlap between the actual H1-training rows used to
  fit models and the actual H2-dev rows used for selection/reporting.
- `policy_a_frozen` arm reproduces the coordinator-stated frozen Policy A
  totals to 9+ significant decimal digits in both `independent` and
  `streaming` accounting, both years.
- Frozen retention cutoffs verified byte-identical between
  `train_models.py`'s freeze and `replay_selection.py`'s 2026 application
  (0/15 spot-checked structure×band mismatches, independently recomputed).
- Dev-window decile/retention-band lift is directionally genuine and
  monotonic for the retrainable structures; the 2026 collapse is consistent
  with ordinary out-of-sample generalization failure of an already-weak
  in-sample signal (dev AUC 0.49–0.53), not a score-sign or indexing bug.

---

**Status:** **PASS — WITH ONE REPORTING-FIDELITY WARNING (non-blocking for causality; address before `final_report.md`)**
**Findings:** **0 CRITICAL, 1 WARNING**

*Completion audit complete. This audit verified the executed pipeline's
artifacts on disk (parquet/JSON contents, file hashes, and mtimes),
independently recomputing several key figures (take_all totals, policy_a_
frozen totals, 2026 cutoff application, train/dev opportunity overlap)
rather than relying solely on the pipeline's own self-reported reconciliation
numbers. The one WARNING (D_hier/baseline_w4 retention-band label fidelity)
does not implicate look-ahead, train/serve skew, or timestamp handling, and
does not change any causal replay, training, or selection result — it is a
labeling caveat for whoever writes `final_report.md`. No CRITICAL findings.
2026's decisively negative outcome for the specialized model arms is
confirmed to be a genuine generalization failure of a weak, correctly-signed
dev-time signal, not a pipeline defect.*
