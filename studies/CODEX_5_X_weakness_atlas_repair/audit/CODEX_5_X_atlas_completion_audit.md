# CODEX 5.X Weakness Atlas — Completion Audit Before W4 Training

**Scope:** completed 2021–2025 repaired year Parquets and rebuild JSONs, the pre/post excursion distribution Parquet/gate/report, the 2021 scalar/batch equivalence JSON and its authenticated inputs, and the current pre-execution audit.  
**Mode:** read-only artifact completion audit with independent streaming scans, hash recomputation, full-key reconciliation, and raw-path spot checks. No source, result, model, manifest, authorization, ledger, or policy artifact was modified. This report is the only file created.  
**Status:** **PASS — ATLAS COMPLETION GATE SATISFIED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The repaired 2021–2025 weakness atlases are complete, causal, internally consistent, and reproducible enough to enter W4 training. Across 6,485,508 repaired checkpoint rows, independent full scans found:

- zero duplicate full checkpoint keys;
- zero rebuilt-only legacy-parity keys;
- zero negative repaired excursion cells;
- zero within-regime MFE/MAE monotonicity violations;
- zero `current`/`running` alias differences;
- zero ATR alias or validity violations;
- zero feature-bar availability violations;
- zero opposing-flip endpoint rows;
- direction domain exactly `{-1, +1}` in every year.

The 2021 scalar/batch artifact comparison is an authenticated PASS with exact equality across the complete ordered 154-input W4 matrix. The repaired distribution gate is PASS. No CODEX 2026 atlas, score, model, audit output, first-open ledger, freeze manifest, or authorization artifact exists.

W4 training may proceed using 2021–2024 training and the already declared purged 2025 selection/calibration chronology. This report does not authorize opening 2026.

## Per-year artifact reconciliation

| Year | Legacy rows | Repaired rows | Removed endpoint | Removed no-path gap | Rebuilt-only | Repaired Parquet SHA-256 |
|---:|---:|---:|---:|---:|---:|---|
| 2021 | 664,524 | 638,930 | 25,580 | 14 | 0 | `32732ef8f18dac5acdfebaf3974e86cc038407f1220f0f2db40e9617a56a44a4` |
| 2022 | 663,494 | 638,648 | 24,843 | 3 | 0 | `99dfde8430e3920e07d73b85d305448f339fe438f77083306a629326a64b877b` |
| 2023 | 664,162 | 638,387 | 25,770 | 5 | 0 | `d8c1f198098a2b58922ec4e4b12a37e5ce712f0db58b4b5ff463f9bd54dde88a` |
| 2024 | 660,440 | 635,277 | 25,156 | 7 | 0 | `067b32d63f594e2d56f53b3eb5019509f5514d2f743ba576b42cc8a51c21fac1` |
| 2025 | 3,959,663 | 3,934,266 | 24,832 | 565 | 0 | `c654da5016f7ec4bf26be11a390992dff851d38e81684a2a19f0bbed90ad9ce7` |
| **Total** | **6,612,283** | **6,485,508** | **126,181** | **594** | **0** | — |

For every year:

```text
legacy_rows - endpoint_removals - no_path_removals == rebuilt_rows == output_rows
```

The two removal classes sum exactly to `legacy_only_noncausal_keys_removed`; their audited classifier is mutually exclusive and fail-closed. All fresh rebuilt keys exist in the legacy identity frame.

An independent reconstruction of legacy `regime_start_ns` from integral `regime_age` confirmed zero rebuilt-only full keys for `(year, regime_start_ns, observation_time, direction)`. It directly recovered the endpoint/gap classification for all legacy-only rows whose regime contract persists in repaired output. Twelve rows belong to wholly suppressed no-checkpoint regimes, so their entry/end contracts cannot be recovered from the final row artifact; their 11 endpoint and 1 no-path classifications reconcile exactly to the immutable per-year rebuild audits produced while those contracts were resident. No unexplained common-contract row was found.

## Rebuild audit integrity and raw provenance

The five rebuild JSONs are present and parse cleanly. Their SHA-256 hashes are:

| Year | Rebuild audit SHA-256 | Raw input hash independently matched |
|---:|---|:---:|
| 2021 | `eaeb01bd3932ea8f06dc935f714e88bd60c6a0bf6066d1a36e28a95baf328f5f` | Yes |
| 2022 | `f64e6e5e755eddc475c23b8aca8295639111bdb6fe168e66c907ef0be46da5e3` | Yes |
| 2023 | `4be857dfb21136b62e8f3cc845584b9b5c2a955051aa09902616d018eb774d28` | Yes |
| 2024 | `7e50b3586be84cb86a71dd36e54be5dc9cb6720c3d5b42a44442c0d411057bd2` | Yes |
| 2025 | `bf2fb0d8403c8f7702c2be49ce9b068a44d744799ac03145aca185a774330923` | Yes |

Every JSON identifies the same legacy atlas hash, the raw causal context source, `atr_at_entry` as the excursion denominator, and `atr_at_checkpoint` as the historical `atr` alias. Independently recomputed raw Parquet hashes match each JSON exactly.

## Direct stored-row invariant scan

Every row of every repaired year Parquet was scanned over the exact persisted contract columns.

### Identity and chronology

- No duplicate `(regime_start_ns, observation_time, direction)` key exists.
- `feature_bar_ts_event < observation_time` for all 6,485,508 rows.
- `observation_time < regime_end_ns` for all rows.
- `entry_ts_event >= flip_decision_ns` for all rows.
- Each year contains both and only directions `-1` and `+1`.

Thus no unavailable checkpoint bar, opposing-flip endpoint, invalid direction, or duplicate identity survived the build.

### Excursions and aliases

- `current_mfe`, `current_mae`, `running_mfe`, and `running_mae` contain zero negative cells.
- `current_mfe == running_mfe` for every row.
- `current_mae == running_mae` for every row.
- Stable sorting by exact regime start/checkpoint produced zero negative within-regime differences for running MFE or MAE.

The persisted aliases therefore retain the intended cumulative observed-so-far meaning.

### ATR contract

- `atr_at_entry` and `atr_at_checkpoint` are finite and strictly positive in every row.
- Historical `atr == atr_at_checkpoint` exactly in every row.
- The feature timestamp check proves checkpoint ATR comes from a completed causal context row.

## Independent raw-path formula verification

Twelve deterministic artifact rows were selected across 2021 and 2025: three temporal locations for each of bullish and bearish directions in each year. For every sample, raw one-second bars were independently loaded over:

```text
[entry_ts_event, observation_time)
```

The following were recomputed without using stored excursion values:

- raw first open versus `entry_open`;
- directional current PnL from the final completed close;
- bullish MFE/MAE from running high/low;
- bearish MFE/MAE from running low/high;
- normalization by stored `atr_at_entry`.

All 12 samples matched exactly: maximum absolute error was `0.0` for entry open, current PnL, MFE, and MAE. Sample path lengths ranged from 22 to 1,440 one-second bars, exercising both directions and varied regime ages.

## Complete 154-input inventory

The canonical W4 declarations contain:

- 49 unique center/activity fields;
- 100 unique sequence fields;
- 5 unique local fields;
- 154 total and 154 unique model inputs.

All 154 columns are present in every repaired year schema. Each year has the same 186-column artifact schema and includes `feature_bar_ts_event`, both explicit ATR fields, timing contracts, future labels, and provenance columns. Labels and ATR provenance columns are not silently inserted into the 154-feature matrix.

## Scalar/batch completion gate

`CODEX_5_X_batched_scalar_equivalence_2021.json` reports:

- status `PASS`;
- 638,930 paired rows in 13 normalized batches;
- zero key mismatches;
- zero value mismatches across all 154 features;
- zero ATR alias mismatches;
- zero invalid ATR cells;
- maximum absolute difference `0.0` for every compared feature.

The report SHA-256 is:

```text
e6bc7841f6a48286a2bd4ad1bc5e1702e0bf8cf3f8a63998089bea6f8f52a84e
```

All authenticated hashes were independently recomputed and match the JSON:

- scalar reference: `f0fa632c6a64a62c95dcb6a82157f0a64eec843e0548f4cb8a07b3c2bc2669c0`;
- batched 2021 artifact: `32732ef8f18dac5acdfebaf3974e86cc038407f1220f0f2db40e9617a56a44a4`;
- comparator source: `08c32475ce4996aeeb8ce08ef727aee2d68822b015afe8703a8618fc7dd51af9`;
- canonical feature source: `396abfbbda4e38b89dd3634b7f76e68e6160cbb5b7d6e90ee1b6f7937f6b6da5`.

This establishes artifact-level equivalence of the optimized center/activity, sequence, and local matrix to the scalar reference.

## Distribution gate and plausibility

The distribution artifacts are present and internally consistent:

- gate JSON SHA-256: `4a43eadf9195993b1e33d17312cbe490dd50a97fde6a440d4c95e1c12f35bb34`;
- distribution Parquet SHA-256: `3d0d79eba4366568d3cdbed1f1b09f74a3af4998def984276a806779ea4e2c88`;
- report SHA-256: `8cb6082f07ce428de810d187cdf58f6b6a8413089dedb451bf5f777939e073c0`.

The Parquet contains the complete `2 versions × 5 years × 2 directions × 4 excursion variables = 80` rows. Repaired per-direction counts exactly equal the corresponding year-atlas row counts.

The repaired gate reports zero negative cells and zero monotonicity violations. The directional distributions are plausible:

- repaired bearish median MFE ranges from 1.563 to 1.680 ATR and median MAE from 0.610 to 0.632 ATR;
- repaired bullish median MFE ranges from 1.511 to 1.602 ATR and median MAE from 0.576 to 0.611 ATR;
- repaired long/short medians are similar in scale and stable across years;
- the legacy bearish negative rate is 95.1%–98.5%, while repaired bearish negative rate is zero;
- the legacy bullish distributions remain close to repaired bullish values, as expected for a bearish sign-specific defect.

This is the expected signature of correcting the documented bearish sign inversion, not an implausible collapse or inflation of both directions.

## Pre-execution gate and 2026 seal

The current main pre-execution audit is present with SHA-256:

```text
783a052209e3cf8eaf79766b2064502422611b830dc0cf18cd524fda9abd0227
```

It states `PASS — PRE-EXECUTION AUDIT GATE SATISFIED` and `0 CRITICAL, 0 WARNING` after the completed activity/comparator test correction.

A recursive scope check found no CODEX filename containing `2026`. Specifically absent are:

- repaired 2026 year atlas;
- 2026 score/distribution artifact;
- frozen model manifest or bundle;
- pre-2026 audit authorization;
- `CODEX_5_X_first_2026_open.json` ledger.

Therefore this atlas work did not open the untouched 2026 test. Raw 2026 data remains outside this completed artifact scope and is still protected by the existing seal.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The 2021–2025 repaired atlas is complete and passes the mandatory artifact-level lookahead, sign, parity, equivalence, provenance, and chronology audit. W4 training may proceed. Do not access 2026 until the pre-2026 model freeze, passing W4 gate, independent authorization, and first-open ledger requirements are satisfied.
