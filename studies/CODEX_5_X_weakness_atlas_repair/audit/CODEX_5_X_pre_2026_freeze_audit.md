# CODEX 5.X — Pre-2026 Freeze Audit

**Scope:** frozen W4 manifest and bundle, exact dependency and 2021–2025 atlas hashes, training/selection/calibration chronology, H1/H2 regime purge, all four fitted structures and selection outputs, direction-specific isotonic calibrators and thresholds, score distributions/crossings, directional gate, full-2025 score export, ATR contract, and 2026 seal state.  
**Mode:** read-only artifact/source audit. No model, atlas, score, manifest, policy result, or 2026 artifact was modified or opened. This report and its authorization JSON are the only permitted writes.  
**Status:** **PASS — PRE-2026 FREEZE AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The repaired W4 model is validly frozen before 2026. Model fitting used 2021–2024 only. Structure selection used outcome-disjoint 2025 H1 regimes only. Direction-specific isotonic calibration and P90 threshold selection used purged 2025 H2 regimes only. The final full-2025 score file applies the already frozen structure, calibrators, and thresholds for development reporting; it does not feed back into selection or calibration.

The selected `directional_pair` follows the predeclared within-0.005 selection rule. Both directional H1 AUCs exceed 0.77, every H2 score is finite, both H2 crossing rates are nonzero, and their balance ratio is 1.0363. The manifest's PASS gate independently recomputes exactly.

All bundle, dependency, atlas, combined-atlas, score, and report hashes checked in this audit match their current files. The bundle preserves the exact 154-feature order and fixed seed. No 2026 CODEX artifact, score, model result, first-open ledger, or prior authorization existed during this audit.

The separate authorization JSON may therefore be issued. It authorizes the sealed 2026 atlas build/evaluation contract only; it does not authorize policy execution or any 2026-driven refit, recalibration, threshold change, or parameter selection.

## Frozen manifest and bundle integrity

Current manifest:

```text
SHA-256: 2b0cc6d0ffd7fdcf28f29a0a73e973fd6b5bc0a797121f23430d220e03dd2180
status: FROZEN_PRE_2026_GATE_PASSED
gate.pass: true
train_years: [2021, 2022, 2023, 2024]
selected_structure: directional_pair
no_2026_access: true
```

Current bundle:

```text
SHA-256: cd1243dc0dc0bd37f1141d9d42a732cf5d7e52fa900536f7b64b9acecb9dc237
```

The independently recomputed bundle hash equals `manifest.bundle_sha256`. The bundle contains:

- models: `pooled`, `long_only`, `short_only`, `pooled_interactions`;
- selected logical structure: `directional_pair`;
- 154 ordered base features, exactly equal to current `BASE_FEATURES`;
- five ordered interaction-local fields, exactly equal to current `INTERACTION_LOCAL`;
- calibrators keyed by directions `+1` and `-1`;
- thresholds keyed by directions `+1` and `-1`;
- fixed seed `42`.

Model dimensionality and fixed parameters are consistent:

| Fitted model | Input columns | Seed | Iterations | Max depth | Learning rate |
|---|---:|---:|---:|---:|---:|
| pooled | 154 | 42 | 100 | 5 | 0.05 |
| long_only | 154 | 42 | 100 | 5 | 0.05 |
| short_only | 154 | 42 | 100 | 5 | 0.05 |
| pooled_interactions | 160 | 42 | 100 | 5 | 0.05 |

The 160 interaction inputs are the 154 base features plus raw direction plus five `direction × local` interactions, exactly as declared.

## Dependency and atlas hash seal

Every one of the nine exact required dependency hashes was independently recomputed and matches the manifest:

| Dependency | SHA-256 |
|---|---|
| `CODEX_5_X_common.py` | `302fab7b64178ee7626300048e9d1b66ab04b64c4a429a3fcbcd48175523e1c7` |
| `CODEX_5_X_build_regime_history.py` | `48f32e322a6c77bec4c5d2a925c962c1c39b8c77ac4b0134383a71bf32bca75b` |
| `CODEX_5_X_build_repaired_atlas.py` | `93710ef4573c1c1bde6fe945635e4f9e0d424b03a1129b43c97e544113d27633` |
| `CODEX_5_X_train_repaired_w4.py` | `1ae959f8f8c410708ead631b6dc354eb149ac2559badef2ab3327c5d095f8fed` |
| `build_weakness_atlas.py` | `1450546a1282d30e030dad5982087bbc12d23c50fbd0405f63b073433d17b58b` |
| `train_weakness_model.py` | `396abfbbda4e38b89dd3634b7f76e68e6160cbb5b7d6e90ee1b6f7937f6b6da5` |
| `reproduce_regimes.py` | `33823e22055836aa0c4914474ee01724e3e18c432a723079e9bf7a2c011137da` |
| `build_median_centers.py` | `6bcfc94503b92ceffd5b9dfa28064d4b787e7eca09a0f2a4c058ab2213bd40fd` |
| `build_regime_sequence.py` | `b35ad953a19eba82be3850c63f3aa76d053a47182b03d71ac95ad05873b926f6` |

The required dependency key set is exact; there are no missing or extra keys.

All five repaired atlas hashes independently match the manifest:

| Year | SHA-256 |
|---:|---|
| 2021 | `32732ef8f18dac5acdfebaf3974e86cc038407f1220f0f2db40e9617a56a44a4` |
| 2022 | `99dfde8430e3920e07d73b85d305448f339fe438f77083306a629326a64b877b` |
| 2023 | `d8c1f198098a2b58922ec4e4b12a37e5ce712f0db58b4b5ff463f9bd54dde88a` |
| 2024 | `067b32d63f594e2d56f53b3eb5019509f5514d2f743ba576b42cc8a51c21fac1` |
| 2025 | `c654da5016f7ec4bf26be11a390992dff851d38e81684a2a19f0bbed90ad9ce7` |

The combined 2021–2025 atlas contains 6,485,508 rows and independently matches its audit hash:

```text
2fc9f5f46aab1a8360d27281e41476423c3d5522657b8120e402e7de27f2bb45
```

## Fit chronology: 2021–2024 only

`train_and_freeze` loads exactly `TRAIN_YEARS=(2021, 2022, 2023, 2024)` for fitting, then explicitly fails if the maximum training year exceeds 2024. The fitted population after the declared NaN gate is:

| Training year | Rows |
|---:|---:|
| 2021 | 638,930 |
| 2022 | 638,648 |
| 2023 | 638,387 |
| 2024 | 635,277 |
| **Total** | **2,551,242** |

Only after fitting all four models is 2025 loaded. The source hash authenticating this chronology is sealed in the manifest. No 2025 row is supplied to `.fit()` for any `HistGradientBoostingClassifier`.

## Exact H1/H2 regime purge and disjointness

The 2025 atlas was independently reduced using the exact persisted `regime_start_ns` and unique `regime_end_ns` contract:

| Window | Eligible regimes | Rows |
|---|---:|---:|
| H1 selection | 13,165 | 1,940,932 |
| H2 calibration | 13,971 | 1,993,302 |

One regime starts at `1751327880000000000` and crosses the July 1 boundary. It contains 32 checkpoints and is absent from both windows. H1 and H2 regime-key sets are exactly disjoint. Every regime has one unique end timestamp.

The independently recomputed purge object equals the manifest:

```json
{
  "boundary_ns": 1751328000000000000,
  "selection_regime_count": 13165,
  "calibration_regime_count": 13971,
  "purged_regime_count": 1,
  "purged_regime_start_ns": [1751327880000000000]
}
```

The H1 and H2 row counts plus the 32 purged rows equal the complete 3,934,266-row 2025 development atlas.

## Four structures and selection rule

The implementation fits four physical model structures:

1. pooled W4;
2. long-only W4;
3. short-only W4;
4. pooled W4 with direction and five direction-local interactions.

The logical `directional_pair` routes prevailing-long rows to `long_only` and prevailing-short rows to `short_only`. The H1 structure output contains pooled, pooled-interactions, long-only, short-only, and combined directional-pair metrics. No H2 metric enters selection.

Independent candidate reconstruction from the H1 directional AUCs gives:

| Candidate | Macro directional AUC | Direction gap | Complexity rank |
|---|---:|---:|---:|
| pooled | 0.771889 | 0.002672 | 0 |
| pooled_interactions | 0.771706 | 0.002503 | 1 |
| directional_pair | 0.771250 | 0.002309 | 2 |

All candidates are within 0.005 of the best macro AUC. Sorting eligible candidates by smaller directional gap, then lower complexity rank, selects `directional_pair`. This exactly matches the implementation, candidate Parquet, bundle, manifest, and report.

The selected H1 directional AUCs reproduce the gate:

- prevailing long: `0.7724045456570982`;
- prevailing short: `0.7700956826699066`.

Both are materially above the required 0.50.

## Direction-specific H2 calibration and frozen thresholds

Only `raw_scores(models, selected, calibration)` from the purged H2 frame is supplied to `calibrate_and_threshold`. Separate `IsotonicRegression` objects are fit for directions `+1` and `-1`, with `out_of_bounds="clip"`, `y_min=0`, and `y_max=1`.

The bundle contains exactly two calibrators:

- long calibrator: 342 learned X thresholds;
- short calibrator: 338 learned X thresholds.

The direction-specific 90th percentiles independently recomputed from the H2 calibrated score export equal the bundle and manifest exactly:

| Direction | H2 rows | P90 frozen threshold |
|---:|---:|---:|
| Long `+1` | 1,023,184 | `0.6883498713708196` |
| Short `-1` | 970,118 | `0.7183653372722797` |

The full-year 2025 long P90 is higher (`0.7002111189303307`), but the stored long threshold remains the H2 value. This confirms full-year reporting did not overwrite the calibration threshold.

## Score distributions, crossings, and W4 gate

Strict crossings were independently recomputed from the stored score exports using stable `(regime_start_ns, observation_time)` order and the required previous-below/current-at-or-above rule.

### H2 calibration

| Direction | Checkpoints | Finite rate | Strict crosses | Regimes | Crossed regimes | Regime crossing rate |
|---:|---:|---:|---:|---:|---:|---:|
| Short `-1` | 970,118 | 1.000 | 17,755 | 6,990 | 5,915 | 0.84620886981402 |
| Long `+1` | 1,023,184 | 1.000 | 18,456 | 6,981 | 6,122 | 0.8769517261137373 |

The balance ratio independently recomputes as:

```text
0.8769517261137373 / 0.84620886981402 = 1.036330104063402
```

It is below the required maximum of 2.0. Both rates are nonzero, both finite-score rates exceed 0.99, and both selected H1 AUCs exceed 0.50. The manifest's `gate.pass=true` is therefore correct.

### Full 2025 development export

The frozen model/calibrators/thresholds produce one score for every 2025 atlas row:

| Direction | Checkpoints | Finite rate | Strict crosses | Regimes | Crossed regimes | Regime crossing rate |
|---:|---:|---:|---:|---:|---:|---:|
| Short `-1` | 1,919,630 | 1.000 | 35,624 | 13,571 | 11,627 | 0.8567533711590892 |
| Long `+1` | 2,014,636 | 1.000 | 36,662 | 13,566 | 11,994 | 0.8841220698805838 |

Counts, crossings, regimes, rates, quantiles, and thresholds reproduce `CODEX_5_X_w4_score_distribution_crossings_2025.parquet`. The full export has 3,934,266 unique checkpoint scores and is development reporting only.

## ATR contract in frozen scores

Both H2 and full-2025 score exports carry:

- historical `atr`;
- `atr_at_entry`;
- `atr_at_checkpoint`.

Across both exports:

- `atr == atr_at_checkpoint` exactly;
- both explicit ATR fields are finite and strictly positive;
- local excursion features retain the entry-ATR denominator;
- sequence/context features retain checkpoint ATR;
- no ATR field is a target.

The manifest records this exact contract.

## Reproducibility hashes for frozen outputs

| Artifact | SHA-256 |
|---|---|
| Model selection candidates | `6c044a7376fd482fd065d0579b2aadc2e85eeddf45302ada59692b172843dd31` |
| Model structure comparison | `742188748340e94c317834e74ee34fa38f2a4990f4619752f3675be2e10f3226` |
| H2/full crossing distributions | `6f8bf896297bfdded4928bb42519bbec8673005355ff72ff66db9b56a9f892c5` |
| H2 score export | `949946e8d2cfb127a587912e12f19a8fa9a94171a507dbc1aa968ecc798875fb` |
| Full-2025 score export | `f97c4e739cb11b19dbaaa3954175bb4f44b8346b7cc10d791dde22a122edeac9` |
| Freeze report | `8a6099b1f34ba25b376da40f849f4fc9e56f6dfd2eb114f01a2059d1e8cde4ba` |
| Atlas completion audit | `ca969578656b200657f46adedae55f28c9bfb436bc0c104268ed885a8220a9ff` |

The bundle retains ordered features, interaction definitions, thresholds, calibrators, all four fitted models, and fixed seed. The manifest seals code and input artifacts. These are sufficient to reproduce and verify the frozen evaluation contract.

## No 2026 access and no policy execution

Before authorization creation, a recursive check found:

- no repaired 2026 atlas;
- no 2026 score, distribution, report, or policy artifact;
- no `CODEX_5_X_first_2026_open.json` ledger;
- no prior pre-2026 authorization file.

The freeze code refuses refitting if a first-open ledger or 2026 atlas exists. The manifest states `no_2026_access=true`, and artifact chronology is consistent with that statement. This audit did not read raw 2026 data and did not execute any policy.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The W4 model structure, calibrators, and thresholds are validly frozen using pre-2026 data only. A hash-bound `CODEX_5_X_pre_2026_authorization.json` may be issued. The sealed 2026 build/evaluation may proceed only through `require_frozen_pre_2026_contract`, which must create or validate the immutable first-open ledger. No 2026 result may alter this frozen contract.
