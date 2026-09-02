<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"causal","auditor":"lookahead-auditor","critical":0,"warning":0,"note":4,"study":"regime_transition_target_before_stop_v1","audited_execution_composite_sha256":"1a6eed85254d052ca84c823a4af5a3d643af83fac57310811720086807077c36"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 09

**Date** 2026-09-01 · **Scope** `studies/regime_transition_target_before_stop_v1/implementation/phase_d_modeling.py` (`load_phase_c_inputs` frame/column swap) + matching fixture in `tests/test_phase_d_modeling_driver.py`; regenerated `audit/{preflight,readiness,execution_manifest,frozen_execution_manifest,failure_packet}.json` and `artifacts/phase0_source_manifest.json` (seal/lifecycle — contract-checker scope) · **Scope hash** exec composite `1a6eed85254d052ca84c823a4af5a3d643af83fac57310811720086807077c36` · **Lint** 0 critical / 0 warning (preflight CAUSAL_LINT + CAUSAL_INVARIANTS PASSED, 8/8) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 4

Inputs verified: `audit/preflight.json` status `CLEAR` at this composite (8/8); `audit/readiness.json` `overall_status` PASS, `prepared_execution_identity` == audited composite; R2/R4 timestamp + callback-order PASS; R8 double-identity exact at this composite. Frozen manifest composite matches. The delta since pass 08 is exactly one behavioural change: in `load_phase_c_inputs`, the 13 causal features are now read from the `candidates` frame and `regime_direction` from the `observations` frame (previously reversed), with a new `PHASE_D_DIRECTION_COLUMN_AMBIGUOUS` guard. No feature tracker, label/barrier runtime, timestamp contract, session logic, fold definition, target-authority pin, or year gate is touched. `research_workflow/generic_collector.py`, `target_runtime.py`, `forward_outcomes/*`, `modeling.py`, `modeling_closure.py`, `modeling_drivers.py` are byte-identical to the pass-08 surface and absent from `changed_files`.

## Prior findings adjudicated (passes 01–08)

| # | Finding | Status | Evidence |
|---|---|---|---|
| P01–P06 | Candidate T on completed bars; 13 raw causal features completed-only; `next_bar_open` strictly `ts>T`; ATR frozen at `decision_ts`; first-touch ordered-barrier race; same-bar / session-end / gap / timeout → censor (`y=null`) | STILL CLEAN | Runtime files unchanged this pass; preflight CAUSAL_INVARIANTS PASSED at `1a6eed85`; R10 emitted features all past-looking (`prior_*`, `rolling_300s_*`, `arrival_*`, `ema_slope`) |
| P07/P08 [G2] | Phase-D target join is positional, authenticated by SHA pin not row key | STILL STANDS (note) | `phase_d_modeling.py:32-33,101-112,142-146` unchanged; re-stated N1 |
| P07/P08 [C3] | Selected-config metrics are post-selection, TRAIN-internal | STILL STANDS (note) | Grid `:40-47`; expanding folds `:36-39`; OOS still behind `assert_oos_open`; re-stated N2 |
| P08 N3 | Read-only catalog junction into worktree | STILL STANDS (note) | Dataset digest unchanged; re-stated N3 |
| P08 N4 | `load_authorization` staleness narrowed to year-roles | STILL STANDS (note) | `experiment.py` unchanged this pass; re-stated N4 |

Passes 01–08 raised no CRITICAL or WARNING; nothing to mark NOT FIXED.

## Critical findings
None.

## Warnings
None.

## Answers to referred questions

**1 — Does swapping features vs `regime_direction` source frame introduce misalignment or look-ahead? No.**
- The row-alignment guard is unchanged and still precedes the concat: `phase_d_modeling.py:123` (`len` equality across all three frames) and `:125-126` (`candidates[keys].equals(observations[keys])` on the exact identity triple `["observation_ts","regime_start_ns","checkpoint_index"]`, raising `PHASE_D_CANDIDATE_OBSERVATION_IDENTITY_OR_ORDER_MISMATCH`). Any order, length, or dtype divergence fails closed — it cannot produce a silently mis-joined row.
- The swap now matches the real Phase-C surface. `generic_collector._emit_observation:845-859` writes `regime_direction` onto the **observation** row; `output_manager.persist_collection:462-475` restricts the **candidate** surface to `feature_list ∪ declared_metadata ∪ candidate_key ∪ universe`, and `regime_direction` is not in this study's declared `metadata_columns` (audit packet `contracts.features.metadata_columns`) — confirmed by `readiness.json` R10 `recognized_metadata_columns` (8 cols, no `regime_direction`). So features are physically on candidates, `regime_direction` physically on observations. The prior (reversed) code would have hard-failed `PHASE_D_FEATURE_COLUMNS_MISSING` on the first real fit; no prior Phase-D result exists to invalidate.
- `pd.concat(axis=1)` at `:142-144` operates on three `reset_index(drop=True)` frames of asserted-equal length and row order; no reindex, sort, or `merge` is introduced. `PHASE_D_DUPLICATE_JOIN_COLUMN` (`:145`) still catches column collisions.
- Neither side is a forward quantity: `regime_direction` is the prevailing-regime sign at T (`generic_collector.py:727/751`, `cand_record.get("regime_direction", self.active_regime_dir)`), and it is the same value the ordered barrier was signed by (written from the same `cand` dict at `:848`). Reading it from observations is, if anything, the barrier-authoritative source.
- New `PHASE_D_DIRECTION_COLUMN_AMBIGUOUS` guard (`:140-141`) is strictly additive fail-closed safety.

**2 — Direction polarity: no inversion introduced.**
`_direction` (`:77-83`, `1→LONG`, `-1→SHORT`) and the cell-resolution path (`_cell_target_columns:155-160`, `_resolved_cell:163-173`) are untouched by the delta. Collector computes the ordered barrier with `direction = regime_direction` (SIGNED_BY_DIRECTION); the POSITIVE↔regime-continuation crosstab (577,723 vs 700) confirms favorable = regime direction. Driver maps `regime_direction 1 → LONG`, i.e. the LONG cell predicts favorable-before-adverse for a bullish prevailing regime. Consistent, no sign flip. The only change is which already-row-aligned frame supplies the (identical-valued) `regime_direction` column.

**3 — Pass-08 clean checks re-confirmed at `1a6eed85`.**
- Expanding folds strict: `FOLDS` (`:36-39`) unchanged — `fold_2022` fits (2021,)→validates 2022; `fold_2023` fits (2021,2022)→validates 2023; every fit year strictly precedes its validation year (`:304-305`).
- `_assert_group_integrity` (`:176-181`) unchanged — raises `PHASE_D_REGIME_GROUP_CROSSES_FOLD` if any `regime_start_ns` is in both fit and validation partitions; invoked per fold at `:303`.
- `fit_temporal_fold` gates: import `:24` unchanged; `SplitPolicy(kind="explicit_index")` `:255`; chronology assertion `:274-275` still requires `train==(2021,2022,2023)` and `2024∈dev`.
- Timestamp-evidence reuse anchored to the immutable seal: `_assert_target_authority` (`:101-112`), `AUTHORITATIVE_TARGET_SHA256` / `…_LOGICAL_SHA256` (`:32-33`), `resolve_modeling_closure` / `assert_declared_modeling_drivers` (`:26-27`) all unchanged.
- No 2024+ reachability: `OOS_YEARS` frozenset `{2024,2025,2026}` (`:30`); `PHASE_D_NONTRAIN_YEAR_READ` (`:147-150`) unchanged, now derives `_year` from `candidates.observation_ts` (`:142` places candidates first) — a candidate identity key, equal to the observation key by the `:125` assertion, so no change in effect. `assert_oos_open` remains the only OOS door (audit-packet invariant).

## Notes

**N1 [G2] — Phase-D target join authenticated by SHA pin, not row key (re-stated, disclosure).** `phase_d_modeling.py:101-112` binds `phase_c2_reconciled_targets.parquet` by `AUTHORITATIVE_TARGET_SHA256`; `:142-144` joins it positionally. The candidate/observation pair is now key-verified (`:125-126`); the third frame (targets) is still only digest-pinned, not key-joined. Unchanged risk profile from pass 08.

**N2 [C3] — Selected-config metrics are post-selection (re-stated, disclosure).** The 108-config LightGBM grid (`:40-47`) is scored on expanding TRAIN folds; the selected cell's reported metrics are in-sample to the selection and must be read as TRAIN-internal. OOS (2024) remains behind `assert_oos_open`.

**N3 — Read-only catalog junction into the worktree (re-stated, disclosure).** `readiness.json` resolves the catalog at the canonical main-repo path; dataset digest unchanged from prior audited surface. No dataset substitution; year reachability gated by the driver, not filesystem visibility.

**N4 — `load_authorization` staleness check narrowed to year-roles (re-stated, disclosure).** `research_workflow/experiment.py` (unchanged this pass) compares only `(train, oos, prohibited)` year sets against a fresh `authorize_experiment` derivation; `study_id` / `study_path` / `schema_version` drift versus `study.yaml` is no longer flagged. TRAIN/OOS/prohibited boundary itself is still fully re-derived and re-checked for disjointness.

## Referred to contract-checker
- Regenerated `audit/*.json`, `frozen_execution_manifest.json`, `failure_packet.json`, `artifacts/phase0_source_manifest.json` — verify seal freshness and that no prior seal pins a superseded composite; verify the fixture change still satisfies the deliverables/model-integrity contract.

## Clean checks
A1–A5, B1–B7, B9–B10, C1–C3, F1–F4, G1–G4, H1–H4 clean — the delta changes only which of two row-aligned, already-loaded Phase-C frames supplies a present-time column; it touches no timestamp, feature, label, barrier, session, data-integrity, or bracket-resolution code, and all frames fail closed on any alignment divergence.
