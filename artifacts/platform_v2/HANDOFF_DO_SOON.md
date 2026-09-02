# Platform-v2 handoff checkpoint — DO NOW complete, DO SOON next

Written 2026-09-02 at the end of the DO NOW phase. This is the resume point for the next
session. Read this file first, then `CLAUDE.md` → `AGENTS.md` → `docs/RESEARCH_WORKFLOW.md`.
Do not re-derive anything recorded here; verify a fact only if you are about to act on it.

## 1. Where the repository is

| Fact | Value |
|---|---|
| `main` | `df26b12`, clean, 95 commits ahead of `origin/main` at handoff time (push pending) |
| Tags | `baseline/2026-09-platform` (8172755, Phase 0) · `baseline/2026-09-platform-v2-do-now` (f9150f2) · `baseline/2026-09-platform-v2-do-now-closed` (df26b12, contract CLEAR + causal pass 04 CLEAR) · `archive/governed-study-controller-v1` |
| Worktrees | main repo only, plus `../Nautilus Trader-regime-transition-target` (branch `study/regime-transition-target-before-stop-v1` @ edd5560, merged; KEEP — it holds the original 468 model byte files, 282 MB, gitignored) |
| Branches | `main`, `study/regime-transition-target-before-stop-v1`, ~29 older `study/*` branches untouched |
| Machine config | `~/.nt_research/config.yaml` → `catalog_roots: [<repo>/data/catalog]`, `model_root: ~/.nt_research/models` (468 models, verified), `leases_dir`, `worktree_root: C:/Users/Scott McCarty/Projects` |
| Design authority | Architecture review artifact https://claude.ai/code/artifact/e88489e9-adc5-461e-a05a-321387de040e · Amendment review (accepted verdicts) https://claude.ai/code/artifact/f7ea1309-9f6e-4dd7-b154-0726f27f8444 |

## 2. What DO NOW delivered (all on main)

| Item | Where | Notes |
|---|---|---|
| 02 Roots | `research_workflow/roots.py`; `research/datasets/{NQ_v0_2020_2026,ES_v0_2020_2026,YM_v0_2024}.yaml` carry `logical_digest`; `data_plan.resolve_catalog_plan`/`resolve_data_plan` and READINESS R1 route through it | dataset_id + committed digest → configured root; no repo-relative fallback when configured; `verify_dataset_files` on every resolve, `verify_dataset_bytes` at R1 and at **every collect/backtest launch** (`data_plan.verify_launch_dataset_bytes`) |
| 03 Model store v2 | `research_workflow/model_store.py`, `model_migration.py`; CLI `research model list/validate/export/migrate` | `<model_root>/models/<model_id>/manifest.json` (schema 2), canonical native LightGBM text, `registry` vs `ledger` tiers, 256-real-row golden frame, exports verified per format. v1 `studies/model_registry/*.json` and `model_artifacts.py` remain authoritative for legacy readers; `persist_models` mirrors into v2; `model_selection._fit_and_score` writes ledger rows |
| 04 Controller | `research_workflow/governed_controller.py`, `controller_actions.py`; `scripts/run_governed_study.py`; docs in `docs/GOVERNED_STUDY_CONTROLLER.md` | Stages: compile prepare readiness preflight tests causal_audit contract_audit seal **smoke collection reconcile merge fit freeze oos analyze close**; receipts under `studies/<id>/_work/controller/receipts/`; fit label column is declared or `--label-column`, never guessed; `run_research_workflow.py`, `run_partitioned_train_collection.py`, `reconcile_study_capabilities.py` are deprecation shims |
| 05 Capability registry | `research_workflow/capabilities.py`, seed `capabilities_index.yaml`, generated `research_workflow/capabilities/registry.json` (179 entries, 0 broken); CLI `research cap list/describe/search/generate --check` | features + datasets/streams introspected; trackers/triggers/outcomes/entry refs/model drivers/validation protocols seeded and verified at generation |
| 06 Regime tracker | `features/trackers/regime_dual_ema.py` (`tracker.regime.dual_ema`) | generic_collector `RegimeEngine`, collector_v2 `RegimeStateEngine`, `LiteRegimeEngine` all delegate; exact parity incl. frozen 2021-01 regime store (`features/tests/test_regime_dual_ema_parity.py`) |
| 07 Performance | `bench/baseline_v0.json`, `bench/measurements_07_hot_path.json`, `bench/measure_07_output_parity.json`; driver `scripts/bench_baseline.py` | full-surface 2,747 → ~2,815 events/s (+2.5%); **ordered-barrier/composite target runtime ≈ 92% of replay time** — the DO SOON perf target |
| 08 Workspace | `research_workflow/workspace.py`; CLI `research study new <id>`, `research ws list` | branch + sibling worktree + lease + skeleton, no junctions (roots resolve datasets) |
| 09 Closure hashing v2 | `research_workflow/closure_hash.py`; `scripts/resolve_execution_manifest.py` (`hash_algorithm`), `research_workflow/prepare.py` records it | v2 = docstring-stripped AST (and `__all__`-stripped unless the module is star-imported); sealed v1 manifests keep v1 |
| 10 Audits | `artifacts/platform_v2/audit/` (causal 01–04, contract 01, `DO_NOW_CAUSAL_CLOSURE.json`) | contract CLEAR; causal pass 04 CLEAR |

Checkpoints per item: `artifacts/platform_v2/checkpoints/01..10_*.json`. Phase 0 record: `artifacts/platform_reconciliation/`.

## 3. Facts the next session must not re-learn

- **Test isolation.** Root `conftest.py` redirects the model store to a tmp root (`NT_RESEARCH_MODEL_ROOT`) for the whole suite; catalog roots stay live. Tests that exercise legacy repo-relative resolution set `NT_RESEARCH_CONFIG` to an absent path themselves.
- **Pre-existing test failures (not ours).** 61 tests fail identically at the Phase 0 base; the list is `scripts/tests/…` families `test_rt_final_blockers`, `test_stage3_integration`, `test_nt_runner_backtest` (STALE_COMPILED_STUDY on `Gemini_/Codex_clean_maturity…`), `test_population_qualification_strictness`, `test_modeling_driver_lineage`, `test_preserved_timestamp_reuse` (KeyError), `test_ordered_barrier_timeout_gap_ambiguous_and_exact_boundary`, `test_collector_contains_no_inline_session_boundary`, plus 2 in `features/tests` (stale expectation of 129 definitions vs 143). Classify any failure against these before treating it as new.
- **Running tests mutates study files** (fidelity reports, workflow_state.json, es_wick audit files). `git checkout -- studies` after a test run, before committing.
- **Sealed study drift is expected.** `regime_transition_target_before_stop_v1` seal composite `1a6eed85…` re-resolves on current main as `7a297eac…` (v1). Its execution authority is tag `baseline/2026-09-platform`. Never re-seal it to make it compile.
- **Scientific authorities:** TRAIN target `21d598a823fd6430459380b3c9f6a75f2b90b61048d78cd7ff840b3f54218b0e`; Phase D DIAGNOSTIC_NEGATIVE (max val ROC-AUC 0.5183); 2024 never accessed; no models retrained. Do not change any of these.
- **Bench discipline.** Never benchmark with tests running. `python scripts/bench_baseline.py --series full --skip-decomposition --output bench/<name>.json` (3 runs, in-process children); `--series parity` runs one real day with persistence and the seal check bypassed (for byte-for-byte output comparison against `bench/_work/smoke_runs/` in the main repo). `clean_maturity_flip_model_rolling_productivity` is STALE_COMPILED_STUDY; ablation controls run on the regime-transition study.
- **Heredoc pitfall on this shell.** Python code passed via bash heredocs turned `\\n` into real newlines inside string literals twice. Write patch scripts to the scratchpad with the Write tool and run them; avoid inline heredocs containing escaped newlines.
- **Windows path pitfall.** `python -c` given `/c/...` paths fails; use `C:/...`.
- **Controller inspect on a study fails WORKTREE_CONTAMINATION** whenever untracked files exist outside `--owned-path`. Commit or pass `--owned-path`.
- **ONNX exports** were not run for the 12 registry models (`research model export <id> --format onnx`; exporter installed, family table in `model_store.FAMILY_AUTHORITY`).
- **Legacy reference** `backtests/run_staged_backtest.py` builds its own engine and bypasses launch verification; frozen reference, out of governed scope (causal pass 04 residual note).

## 4. DO SOON — what already exists to build on

| DO SOON deliverable | Existing pieces to reuse (do not rewrite) |
|---|---|
| Grammar + static compiler | `research/schemas/study_spec.py` (current union schema — to be replaced), `research_workflow/compiler.py`, `study_spec_compiler.py` (typed field resolution enums), `capabilities.py` registry (resolve kinds), `roots.py` (datasets without opening catalogs), `provider_host.py` (adapter requirements/cadence), `target_expression.py` (compiled outcome trees) |
| Thin runtime host | `generic_collector.py` (what to replace; its `on_bar`, `_handle_1s_bar`, checkpoint grid, `_resolve_ordered_barriers`, `_sweep_elapsed_horizons` are the semantics to reproduce), `provider_host.py` dispatch/routing table, `population_runtime.py` + `episode_population.py` (state machine semantics for Shape B), `target_runtime.py` + `target_replay_oracle.py` (kernel + independent oracle), `completed_regime_state.py`/`collectors/collector_v2/aggregator.py` (bucket aggregation), `utils/session_boundaries.py` (integer session table), `features/trackers/regime_dual_ema.py` |
| Three-shape parity | `scripts/find_first_parity_divergence.py` (mandatory first step on divergence), `research/analysis/modeling.frame_content_identity`, Shape A reference `studies/clean_maturity_flip_model_180s_horizon` (closed), Shape B `studies/deep_pullback_5s_reacceleration_model` (closed, episode contract sealed), Shape C `studies/regime_transition_target_before_stop_v1` (merged TRAIN frames in the regime worktree `_work/train_merged_collection/`, 12 selected models in the store) |
| Dataset V2 | `research_workflow/roots.py` (manifest/digest), `scripts/build_dense_1s.py` (calendar via pandas_market_calendars, 2021-06 maintenance-break rule), `backtests/nt_runtime/catalog_materializer.py`, `data_plan.PRODUCT_CATALOGS`, R2 in `readiness.py` (5m derived from 1m), memory notes on roll-day tape artifacts and `closed='left'` resampling |
| Performance | `bench/baseline_v0.json` decomposition (checkpoint_only 37k · full_no_target 32.9k · full 2.7k events/s) |

## 5. Suggested first hour of the DO SOON session

1. `git fetch && git status` — confirm `main` = `df26b12` and clean; `git worktree list` shows only main + the regime worktree.
2. `python scripts/research.py data roots` and `research cap generate --check` — confirm roots and registry are current.
3. `python scripts/research.py study new` is for studies; for platform work create the branch/worktree manually: `git worktree add "../Nautilus Trader-platform-v2-do-soon" -b chore/platform-v2-do-soon baseline/2026-09-platform-v2-do-now-closed` (no junction needed: roots resolve datasets).
4. Build the golden fixture (deliverable 7 of the prompt) before touching the host; the fixture plus `target_replay_oracle` are the only trustworthy judges of the new host.
5. Write `artifacts/platform_v2_do_soon/checkpoints/<NN>.json` after each deliverable; commit each logical stage; keep the two morning cards' format.
