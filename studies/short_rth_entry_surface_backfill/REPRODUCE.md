# Reproduce — Short-RTH Entry Surface Backfill

Scope executed so far: 2025-2026 reconciliation smoke, then 2021-2024
per-year 5s-cadence backfill (atlas rebuild + surface funnel + feature
completeness + seq-1 Policy A feasibility), then assembly into a combined
2021-2024 training surface. **No model training, no feature selection, no
threshold tuning** — this study only builds and validates a dataset. All
commands below assume `cd studies/short_rth_entry_surface_backfill`.

## 1. 2025-2026 reconciliation smoke

```bash
python run_reconciliation.py
```

Reads the existing 2025/2026 repaired atlases and raw 1s bars (no rebuild).
Builds the score-independent surface (`entry_surface.build_surface`) and
reconciles it against the known W4-threshold-crossing candidate population
via `fable5_short_rth_threshold_ladder/run_ladder.py` (score touched only
here, never inside the surface builder).

Writes:
- `results/reconciliation_2025_2026_summary.md`
- `results/reconciliation_2025_2026_counts.csv`
- `results/reconciliation_2025_2026_manifest.json`
- `results/reconciliation_2025_2026_surface.parquet`

Expected: `DECISION: BACKFILL_RECONCILIATION_PASS`, 650/650 (2025) and
222/222 (2026) crossing candidates reproduced, 0 missing, 0 mismatched.
Runtime ~2-3 minutes.

## 2. 2021 5s-cadence atlas rebuild smoke

```bash
python build_5s_atlas_smoke.py --year 2021
```

Forks `CODEX_5_X_build_repaired_atlas.build_raw_checkpoints` with
`step_s=5` forced (instead of the year-gated 30s), reusing
`attach_causal_w4_context` verbatim, and replaces the legacy-atlas parity
comparison with the same intrinsic causal/monotonicity/ATR assertions that
function already enforces.

Writes:
- `_work/atlas_5s_backfill_2021.parquet` (not the canonical repaired-atlas
  path — this is a study-local artifact, not a production replacement)
- `results/smoke_2021_manifest.json` (atlas-build stats; overwritten by
  step 3 below with the fuller consolidated manifest)
- `results/smoke_2021_counts.csv`

Expected: ~3.96M checkpoints across ~27.8K regimes, 0 negative excursion
cells, 0 monotonicity violations, 149/149 feature columns present. Runtime
~4-5 minutes.

## 3. 2021 surface funnel + feature completeness + Policy A feasibility

```bash
python smoke_2021_surface.py
```

Requires step 2's output to exist. Builds the score-independent surface on
the new 2021 5s atlas, scans raw bars for >300s gaps, checks feature
completeness (NaN rates) over both the full atlas and the surface subset,
and labels the first established/RTH/valid-fill checkpoint per regime
(seq-1 equivalent) with Policy A via `fable5_common.simulate_trade_arrays` —
a feasibility check, not a training dataset.

Writes (overwrites step 2's manifest/counts with the consolidated version):
- `results/smoke_2021_summary.md`
- `results/smoke_2021_counts.csv`
- `results/smoke_2021_manifest.json`
- `_work/surface_2021.parquet`

Expected: surface funnel structurally similar in shape to 2025/2026
(established -> RTH -> valid-fill survival rates in the same ballpark), 379
gaps >300s all attributable to weekends/holidays (largest: Dec 23-26
Christmas, Apr 2-4 Good Friday, Nov 26-28 Thanksgiving), 0 feature-column
gaps, 1,762 seq-1 candidates all labeled without error.

## 4. 2022-2024 per-year backfill

```bash
python build_5s_atlas_smoke.py --year 2022   # idempotent: skips rebuild if
python build_5s_atlas_smoke.py --year 2023   # the atlas parquet already
python build_5s_atlas_smoke.py --year 2024   # exists (recomputes audit only)
python run_year_backfill.py --year 2022
python run_year_backfill.py --year 2023
python run_year_backfill.py --year 2024
```

`run_year_backfill.py` calls `build_5s_atlas_smoke.build_raw_checkpoints_5s`/
`intrinsic_causal_audit` and `entry_surface.build_surface` itself, so the
separate `build_5s_atlas_smoke.py --year YYYY` invocation above is optional
(only useful if you want the atlas rebuilt as a standalone step first). It
also imports `smoke_2021_surface.gap_scan` / `feature_completeness` /
`policy_a_feasibility` directly — **the exact same functions used for
2021**, not reimplementations — plus one new read-only diagnostic
(`classify_gap`: weekend/holiday/daily-maintenance vs suspicious-intraday).

Writes per year:
- `_work/atlas_5s_backfill_{year}.parquet`, `_work/surface_{year}.parquet`
- `results/backfill_{year}_summary.md`
- `results/backfill_{year}_counts.csv`
- `results/backfill_{year}_manifest.json`

Expected: ~3.93-3.96M checkpoints and ~190K-205K surface rows per year, 0
causal-audit violations, 149/149 feature columns, 0 Policy-A label errors.
2022-2024 each flag a handful of `SUSPICIOUS_INTRADAY` gaps (7/8/8
respectively; 2021 predates the classifier and was reviewed via its own
top-10 list, which showed none) — all manually verified to be CME
early-close holiday sessions (MLK, Presidents Day, Memorial Day, Juneteenth,
July 4th, Labor Day, Thanksgiving), not data-quality problems. Runtime ~4-5
minutes/year.

## 5. Assemble the 2021-2024 training surface

```bash
python assemble_training_surface.py
```

Requires all four years' `_work/atlas_5s_backfill_{year}.parquet` and
`_work/surface_{year}.parquet` to exist (2021 via steps 2-3, 2022-2024 via
step 4). Pure aggregation — no rebuild, no new causal logic beyond a schema-
stability check and a hash-based provenance manifest. Verifies the 149-column
feature schema is identical across all 4 years, checks the acceptance gate,
and concatenates the four per-year surfaces.

Writes:
- `_work/training_surface_2021_2024.parquet` (813,972 combined rows)
- `results/training_surface_2021_2024_summary.md`
- `results/training_surface_2021_2024_counts.csv`
- `results/training_surface_2021_2024_manifest.json`

Expected: `DECISION: BACKFILL_TRAINING_SURFACE_READY`, schema stable across
all 4 years, 0 label errors, 0 causal violations, combined row count
813,972 (2021: 212,241 / 2022: 192,378 / 2023: 204,742 / 2024: 204,611).

## 6. Full-surface Policy A labeling

```bash
python label_full_surface.py --sample 2000 --years 2022   # optional benchmark first
python label_full_surface.py                               # all 4 years, full surface
```

Labels **every** row of the assembled surface (813,972 total) as an
independent hypothetical short entry — not a one-position replay; rows
overlap heavily within a regime by design. Reuses
`fable5_common.simulate_trade_arrays` verbatim for entry/exit/PnL
determination; MAE/MFE and the pre/post-alignment excursion split are a
post-hoc numpy scan over the already-determined `[entry_i, exit_i]` window.

Runs a mandatory acceptance gate before accepting results: every seq-1 row
(the subset already labeled by step 4/2021's smoke) must reproduce, exactly,
the original seq-1 manifest's exit-reason counts and net-PnL sum for that
subset (`seq1_aggregate_reconciliation`). Also runs data-quality checks
(negative hold time, exit-before-entry, alignment-after-exit, stop on the
wrong side for a short) and censoring (rows whose scheduled resolution falls
outside the available raw year are coded `censored_end_of_data`, never
silently dropped).

Writes:
- `results/full_surface_labels_{2021,2022,2023,2024}.parquet`
- `results/full_surface_labeling_summary.md`
- `results/full_surface_labeling_counts.csv`
- `results/full_surface_labeling_manifest.json`
- `results/training_surface_2021_2024_labeled.parquet` (combined, 813,972 rows)
- `results/training_surface_2021_2024_labeled_manifest.json`

Expected: `DECISION: FULL_SURFACE_LABELING_PASS`, 813,972/813,972 labeled, 0
censored, 0 errors, seq-1 aggregate reconciliation exact on all 4 years, all
data-quality checks clean. Runtime ~35s/year (raw-load-dominated; per-row
compute is fast). Combined aggregate net PnL across all 813,972 rows is
**descriptive only, not deployable strategy PnL** — it mixes every eligible
checkpoint in a regime, most of which a real one-position strategy would
never enter.

**Polarity note:** the full-surface `avoid_pre_alignment_stop` column = 1
when the row DID hit the pre-alignment stop (per explicit spec — read as
"this is a case to avoid"). This is the OPPOSITE polarity of the seq-1
feasibility check's own `avoid_pre_alignment_stop` field (1 = did NOT hit
the stop, from `smoke_2021_surface.py`/`run_year_backfill.py`). Do not mix
the two columns.

## Lookahead audit

`audit/audit.md` — PASS, 0 CRITICAL, 1 WARNING (fixed post-audit, see the
"Remediation" section appended to that file), covering `entry_surface.py`
and `run_reconciliation.py`. Not separately re-run for
`build_5s_atlas_smoke.py`, `smoke_2021_surface.py`,
`run_year_backfill.py`, `assemble_training_surface.py`, or
`label_full_surface.py` — these reuse already-audited rebuild/surface/
labeling functions verbatim (including `simulate_trade_arrays` for the full
labeling pass); the only new logic across all five (`intrinsic_causal_audit`'s
legacy-parity removal, `gap_scan`, `classify_gap`, the assembly script's
schema check, and the labeling script's MAE/MFE post-hoc scan + seq-1
reconciliation gate) is read-only diagnostics, descriptive statistics over
an already-determined exit window, or intrinsic-invariant assertions — not
new causal decision logic. See `audit/audit.md`'s "2022-2024 expansion" and
"Full-surface labeling" notes for the explicit non-re-audit rationale.

## Order dependency

Step 1 has no dependency on steps 2-6. Step 3 requires step 2's atlas
parquet. Step 4's `run_year_backfill.py --year YYYY` requires no prior step
for that year (it rebuilds the atlas itself if missing) but does require
`smoke_2021_surface.py` to exist as an importable module (it does, unconditionally,
regardless of whether 2021 has been (re-)run). Step 5 requires all of
2021-2024's atlas + surface parquets to exist (steps 2-4). Step 6 requires
step 5's per-year `_work/surface_{year}.parquet` files and, for the
reconciliation gate, the original per-year manifests from steps 3/4
(`results/smoke_2021_manifest.json`, `results/backfill_{year}_manifest.json`).

## Not done

Model training. Feature selection. Threshold tuning. 2025/2026 in the
assembled dataset. Any change to Policy A, the RTH definition, checkpoint
feasibility subset. No model training. No feature selection. No threshold
tuning. No change to Policy A or the RTH/established-regime definitions. No
2025/2026 data in the assembled surface.
