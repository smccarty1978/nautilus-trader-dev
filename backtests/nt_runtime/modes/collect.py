"""Collect Mode Orchestrator for NautilusTrader Generic Runtime.
=============================================================
Executes live ML research surface generation inside NautilusTrader event loop.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from backtests.nt_runtime.data_plan import DataPlan, resolve_data_plan
from backtests.nt_runtime.engine_builder import build_engine
from research_workflow.output_manager import OutputManager, verify_strategy_output_interface
from backtests.nt_runtime.run_plan import RunPlan, RunStage, resolve_run_plan
from backtests.nt_runtime.strategy_binding import StrategyBinding, resolve_strategy_binding
from backtests.nt_runtime.telemetry import CausalTelemetry
from scripts.preexec_audit_seal import verify_preexec_audit_seal

repo_root = Path(__file__).resolve().parents[3]
REPO_ROOT = repo_root


def run_collect_mode(
    study_path: Union[str, Path],
    stage: Union[str, RunStage] = "day",
    date_override: Optional[str] = None,
    output_dir: Optional[Union[str, Path]] = None,
    log_level: str = "ERROR",
    feature_authority: str = "active",
    experiment_authorization: Optional[Dict[str, Any]] = None,
    date_range: Optional[Tuple[str, str]] = None,
    primary_interval: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """Runs a study in 'collect' mode through the NautilusTrader BacktestEngine."""
    # Closure is checked before even loading the compiled study / planning catalog IO.
    from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
    try:
        if load_study_closure(Path(study_path)) is not None:
            raise RuntimeError("STUDY_CLOSED: direct collection is prohibited")
    except StudyClosureInvalid as exc:
        raise RuntimeError(f"STUDY_CLOSURE_INVALID: {exc}") from exc
    # 1. Load and validate compiled study
    study_data = load_compiled_study(study_path)
    spec = study_data.spec

    # 2. Cryptographic Pre-Execution Audit Seal Check (fail-closed)
    if feature_authority not in {"active", "candidate"}:
        raise ValueError(f"UNKNOWN_FEATURE_AUTHORITY: {feature_authority!r}")
    if feature_authority == "active":
        from scripts.resolve_execution_manifest import verify_frozen_execution_identity
        verify_frozen_execution_identity(study_data.study_dir, REPO_ROOT)
        seal_data = verify_preexec_audit_seal(study_data.study_dir)
    else:
        # Candidate runs are explicit governance probes, never default runtime.
        from features.candidate_authority import load_authority
        load_authority("candidate")
        seal_data = {}

    # 3. Resolve bounded run plan & data plan
    authorized_dates_override = None
    if experiment_authorization is not None:
        from research_workflow.experiment import verify_runtime_authorization
        # Verify against the chronology-derived date range before asking the
        # lower-level planner to construct its bounded plan.
        period = str(experiment_authorization.get("period"))
        years = sorted(study_data.spec.chronology.train if period == "train" else study_data.spec.chronology.dev or [])
        if not years and date_range is None:
            raise RuntimeError(f"EXPERIMENT_AUTHORIZATION_EMPTY: {period}")
        requested_start, requested_end = date_range or (f"{years[0]}-01-01", f"{years[-1]}-12-31")
        verified = verify_runtime_authorization(study_data.study_dir, experiment_authorization, requested_start, requested_end)
        authorized_dates_override = verified["dates"]
    run_plan = resolve_run_plan(
        study_data, stage=stage, reference_date=date_override,
        authorized_dates=authorized_dates_override,
    )
    if date_range is not None:
        run_plan = RunPlan(
            stage=run_plan.stage,
            start_date=date_range[0],
            end_date=date_range[1],
            is_bounded=True,
            auto_expand=False,
        )

    # Enforce strict smoke gate before stage=FULL (R3-1)
    if run_plan.stage == RunStage.FULL:
        smoke_acc_file = study_data.study_dir / "artifacts" / "smoke_acceptance.json"
        if not smoke_acc_file.exists():
            raise RuntimeError(
                f"SMOKE_GATE_REQUIRED: Stage 'full' requires a validated smoke acceptance artifact: {smoke_acc_file}. "
                f"Run 1-day sealed smoke test first, verify candidate invariants via scripts/validate_smoke.py, and issue smoke acceptance."
            )
        import json
        with open(smoke_acc_file, "r", encoding="utf-8") as f:
            sacc = json.load(f)

        if not isinstance(seal_data, dict) or "composite_seal_hash" not in seal_data:
            raise RuntimeError("SMOKE_GATE_FAILED: seal_data missing required 'composite_seal_hash' key")

        seal_sha = seal_data["composite_seal_hash"]
        manifest_composite_sha = seal_data.get("execution_manifest_composite_sha256", seal_sha)

        # 1. Status must strictly be ACCEPTED
        if sacc.get("status") != "ACCEPTED":
            raise RuntimeError(f"SMOKE_ACCEPTANCE_INVALID: smoke_acceptance.json status={sacc.get('status')}")

        # 2. Study name check
        if sacc.get("study_name") != study_data.study_dir.name:
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_STUDY_MISMATCH: smoke_acceptance study={sacc.get('study_name')} != {study_data.study_dir.name}"
            )

        # 3. Seal hash match
        if sacc.get("sealed_composite_sha256") != seal_sha:
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_STALE: smoke_acceptance composite hash ({sacc.get('sealed_composite_sha256')}) "
                f"does not match current seal ({seal_sha}). Re-run sealed smoke and scripts/validate_smoke.py."
            )

        # 4. Manifest composite match
        if sacc.get("execution_manifest_composite_sha256") != manifest_composite_sha:
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_STALE: smoke_acceptance manifest hash ({sacc.get('execution_manifest_composite_sha256')}) "
                f"does not match current execution manifest ({manifest_composite_sha})."
            )

        # 5. Deterministic validation verified
        if sacc.get("deterministic_validation_verified") is not True:
            raise RuntimeError(
                "SMOKE_ACCEPTANCE_UNVERIFIED: smoke_acceptance.json deterministic_validation_verified is not True"
            )

        # 6. Current validator file hash match
        val_script_path = repo_root / "scripts" / "validate_smoke.py"
        if not val_script_path.exists():
            raise RuntimeError(f"SMOKE_VALIDATOR_MISSING: {val_script_path} does not exist")
        # Use the same canonical file hashing contract as validate_smoke_run;
        # Windows newline normalization must not make a freshly-issued acceptance
        # appear stale.
        from research_workflow.seal import _hash_file
        current_val_sha = _hash_file(val_script_path)
        if sacc.get("validator_file_sha256") != current_val_sha:
            raise RuntimeError(
                f"SMOKE_VALIDATOR_STALE: Validator SHA in smoke acceptance ({sacc.get('validator_file_sha256')}) "
                f"does not match current scripts/validate_smoke.py ({current_val_sha}). Re-validate smoke."
            )

        # 7 & 8 & 9. Causality measurements coverage
        if sacc.get("future_source_violations_count") != 0:
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_INVALID: future_source_violations_count={sacc.get('future_source_violations_count')}, expected 0"
            )

        if sacc.get("causality_coverage_pct") != 100.0:
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_INVALID: causality_coverage_pct={sacc.get('causality_coverage_pct')}, expected 100.0%"
            )

        if sacc.get("causality_rows_examined") != sacc.get("candidates_count_total"):
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_INVALID: causality_rows_examined ({sacc.get('causality_rows_examined')}) "
                f"!= candidates_count_total ({sacc.get('candidates_count_total')})"
            )

        obs_pol = (spec.execution.observation_policy or {}) if hasattr(spec.execution, "observation_policy") and spec.execution.observation_policy else {}
        req_relation = obs_pol.get("required_source_relation", "equal")
        if req_relation == "equal":
            if sacc.get("exact_timestamp_equality_verified") is not True:
                raise RuntimeError(
                    "SMOKE_ACCEPTANCE_INVALID: exact_timestamp_equality_verified is not True for exact_grid observation policy"
                )

        # Internal-consistency check independent of config: exact_timestamp_equality_verified must equal (future_source_violations_count == 0)
        if sacc.get("exact_timestamp_equality_verified") != (sacc.get("future_source_violations_count") == 0):
            raise RuntimeError(
                f"SMOKE_ACCEPTANCE_CONTRADICTORY: exact_timestamp_equality_verified ({sacc.get('exact_timestamp_equality_verified')}) "
                f"does not match future_source_violations_count == 0 ({sacc.get('future_source_violations_count') == 0})"
            )

        # 10 & 11. Run binding check
        smoke_run_dir = Path(sacc.get("run_dir", ""))
        if not smoke_run_dir.exists():
            raise RuntimeError(f"SMOKE_RUN_DIR_MISSING: smoke run directory does not exist: {smoke_run_dir}")
        smoke_run_manifest_file = smoke_run_dir / "run_manifest.json"
        if not smoke_run_manifest_file.exists():
            raise RuntimeError(f"SMOKE_RUN_MANIFEST_MISSING: missing {smoke_run_manifest_file}")
        with open(smoke_run_manifest_file, "r", encoding="utf-8") as f:
            smoke_run_m = json.load(f)
        if smoke_run_m.get("composite_seal_hash") != seal_sha:
            raise RuntimeError(
                f"SMOKE_RUN_SEAL_MISMATCH: run_manifest composite_seal_hash ({smoke_run_m.get('composite_seal_hash')}) "
                f"!= current seal ({seal_sha})"
            )

    data_plan = resolve_data_plan(
        study_data, start_date=run_plan.start_date, end_date=run_plan.end_date,
        authorized_dates_override=authorized_dates_override,
    )

    # 3. Resolve strategy binding
    binding_key = spec.execution.strategy_class or "flip_prediction_collector"
    strategy_binding = resolve_strategy_binding(
        binding_key,
        study_type=spec.study.type,
        mode="collect",
    )

    # 4. Initialize Telemetry & Output Manager with launch-time verified seal identity (R4-2)
    out_dir_path = Path(output_dir).resolve() if output_dir else None
    launch_seal_hash = seal_data.get("composite_seal_hash") if isinstance(seal_data, dict) else None
    launch_manifest_hash = seal_data.get("execution_manifest_composite_sha256", launch_seal_hash) if isinstance(seal_data, dict) else None

    output_mgr = OutputManager(
        study_data,
        data_plan,
        run_plan,
        output_base_dir=out_dir_path,
        composite_seal_hash=launch_seal_hash,
        execution_manifest_sha256=launch_manifest_hash,
        feature_authority=feature_authority,
    )
    telemetry = CausalTelemetry()
    telemetry.start()

    # Everything from here on can fail, and a failure must leave a terminal status behind.
    # Without this the run directory keeps the RUNNING it was created with, and an
    # abandoned run becomes indistinguishable from one still in flight (H2).
    try:
        return _execute_collect(
            study_data, spec, data_plan, run_plan, strategy_binding,
            output_mgr, telemetry, log_level, feature_authority,
            primary_interval,
        )
    except KeyboardInterrupt as exc:
        output_mgr.finalize_failed(exc, status="ABORTED")
        raise
    except BaseException as exc:
        output_mgr.finalize_failed(exc, status="FAILED")
        raise


def build_collector_config_kwargs(
    strategy_binding: StrategyBinding,
    spec: Any,
    study_data: Any,
    data_plan: DataPlan,
    *, feature_authority: str = "active",
    primary_interval: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """Resolves the StrategyConfig kwargs a governed collector is constructed with.

    Split out of ``_execute_collect`` so a second caller (READINESS R5) can construct the
    real collector's config identically -- through the same generic hasattr-gated wiring,
    not a second hand-maintained copy -- without running the NT event loop.
    """
    cfg_kwargs: Dict[str, Any] = {
        "instrument_id": data_plan.instrument_id,
        "bar_type_1s": data_plan.bar_type_1s,
        "bar_type_1m": data_plan.bar_type_1m,
    }
    if hasattr(strategy_binding.config_cls, "prevailing_regime"):
        cfg_kwargs["prevailing_regime"] = spec.population.prevailing_regime or "bullish"
    if hasattr(strategy_binding.config_cls, "target_direction"):
        cfg_kwargs["target_direction"] = spec.target.direction or "bearish"
    if hasattr(strategy_binding.config_cls, "horizon_seconds"):
        cfg_kwargs["horizon_seconds"] = spec.target.horizon_seconds or 300
    # qualification is a typed PopulationQualificationSpec (RT-06); collapse to the
    # historical dict of set keys so the .get(..., default) wiring below is unchanged.
    _q = spec.population.qualification
    qualification = _q.model_dump(exclude_none=True) if _q is not None and hasattr(_q, "model_dump") else (_q or {})
    if hasattr(strategy_binding.config_cls, "age_gate_seconds"):
        cfg_kwargs["age_gate_seconds"] = int(qualification.get("age_gate_seconds", 120))
    if hasattr(strategy_binding.config_cls, "established_required"):
        cfg_kwargs["established_required"] = bool(qualification.get("established", True))
    if hasattr(strategy_binding.config_cls, "checkpoint_interval_seconds"):
        cfg_kwargs["checkpoint_interval_seconds"] = int(qualification.get("cadence_seconds", 5))
    if hasattr(strategy_binding.config_cls, "running_mfe_atr_gte"):
        cfg_kwargs["running_mfe_atr_gte"] = float(qualification.get("running_mfe_atr_gte", 1.0))
    if hasattr(strategy_binding.config_cls, "new_progress_windows_gte"):
        cfg_kwargs["new_progress_windows_gte"] = int(qualification.get("new_progress_windows_gte", 2))
    if hasattr(strategy_binding.config_cls, "retained_mfe_ratio_gte"):
        cfg_kwargs["retained_mfe_ratio_gte"] = float(qualification.get("retained_mfe_ratio_gte", 0.5))
    if hasattr(strategy_binding.config_cls, "required_checkpoint_identities_path"):
        rel = qualification.get("required_checkpoint_identities_path")
        cfg_kwargs["required_checkpoint_identities_path"] = (
            str(study_data.study_dir / rel) if rel else ""
        )
    if hasattr(strategy_binding.config_cls, "episode_lifecycle"):
        # Compiled population_contract.episode_lifecycle -> generic population runtime.
        _pop = (study_data.contracts.get("population_contract", {}) or {})
        _el = _pop.get("episode_lifecycle") or {}
        if _el:
            cfg_kwargs["episode_lifecycle"] = dict(_el)
            # Stage 3: the ProviderHost feature contract.
            _fc = study_data.contracts.get("feature_contract", {}) or {}
            if _fc and hasattr(strategy_binding.config_cls, "feature_contract"):
                cfg_kwargs["feature_contract"] = dict(_fc)
    # RT-04: the ordered frozen derived-input scorers are population-agnostic -- pass the
    # runtime-scored declarations for a checkpoint-grid study too. A score_artifact_path-
    # only (pre-materialized, joined offline) form is NOT passed to the collector.
    _di = (spec.features.derived_inputs if spec.features else None) or []
    _runtime_di = [
        d for d in _di
        if getattr(d, "kind", None) == "frozen_external_model_score"
        and (getattr(d, "model_artifact_path", None) or getattr(d, "model_id", None))
    ]
    if _runtime_di and hasattr(strategy_binding.config_cls, "derived_inputs"):
        cfg_kwargs["derived_inputs"] = tuple(
            d.model_dump(mode="json") if hasattr(d, "model_dump") else dict(d) for d in _runtime_di
        )
    if hasattr(strategy_binding.config_cls, "feature_list"):
        cfg_kwargs["feature_list"] = spec.features.feature_list
    if hasattr(strategy_binding.config_cls, "feature_requirements"):
        from features.registry import derive_study_feature_requirements
        cfg_kwargs["feature_requirements"] = derive_study_feature_requirements(
            spec.features, authority=feature_authority,
        )
    # D2.3: only override when the study actually declares metadata_columns -- unlike
    # feature_list, a collector generally cannot function with an empty/None metadata set,
    # so a study that hasn't declared one keeps the config class's own default rather than
    # having it overwritten with nothing.
    if hasattr(strategy_binding.config_cls, "metadata_columns") and spec.features.metadata_columns:
        cfg_kwargs["metadata_columns"] = tuple(spec.features.metadata_columns)
    # Session and censoring come from the compiled contracts, not from strategy defaults:
    # the runtime previously hard-coded a session window that disagreed with the contract,
    # and ignored the declared censoring policy entirely.
    if hasattr(strategy_binding.config_cls, "session"):
        cfg_kwargs["session"] = spec.population.session or "RTH"
    if hasattr(strategy_binding.config_cls, "session_end_censoring"):
        # Authoritative source: the target contract's own resolved session policy
        # (research/engines/target_engine.resolve_session_end_censoring), surfaced at
        # target_contract.session_end_censoring. `censoring_policy.session_end_censoring`
        # is the same value in the historical shape; it is the fallback only for a
        # contract compiled before the top-level key existed. Never a hard-coded default.
        _tc = study_data.contracts.get("target_contract", {}) or {}
        if "session_end_censoring" in _tc:
            cfg_kwargs["session_end_censoring"] = bool(_tc["session_end_censoring"])
        else:
            _cp = _tc.get("censoring_policy", {}) or {}
            cfg_kwargs["session_end_censoring"] = bool(_cp.get("session_end_censoring", True))
    if hasattr(strategy_binding.config_cls, "target_contract"):
        cfg_kwargs["target_contract"] = dict(study_data.contracts.get("target_contract", {}) or {})
    # Phase-zero authentication gate (fail-closed). A collector that declares this field
    # authenticates itself against a manifest at a study-relative path; this runtime never
    # knew about the field before, so it was always left at its "" default and every such
    # collector failed closed with "phase-zero authorization missing" regardless of whether
    # a valid manifest existed. The path is derived generically from study_data.study_dir,
    # not from any collector's own __file__, so this applies to any study using the pattern.
    if hasattr(strategy_binding.config_cls, "phase0_manifest_path"):
        cfg_kwargs["phase0_manifest_path"] = str(study_data.study_dir / "artifacts" / "phase0_source_manifest.json")
    if hasattr(strategy_binding.config_cls, "feature_authority"):
        cfg_kwargs["feature_authority"] = feature_authority
    if primary_interval is not None:
        if hasattr(strategy_binding.config_cls, "primary_start_ts"):
            cfg_kwargs["primary_start_ts"] = int(primary_interval[0])
        if hasattr(strategy_binding.config_cls, "primary_end_ts"):
            cfg_kwargs["primary_end_ts"] = int(primary_interval[1])
    return cfg_kwargs


def _execute_collect(
    study_data,
    spec,
    data_plan,
    run_plan,
    strategy_binding,
    output_mgr,
    telemetry,
    log_level: str,
    feature_authority: str = "active",
    primary_interval: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """Runs the engine and persists results. Split out so the caller owns failure status."""
    # 5. Construct BacktestEngine and load bars in causal order
    engine = None
    try:
        engine, instrument = build_engine(data_plan, log_level=log_level, telemetry=telemetry)

        # 6. Build StrategyConfig
        cfg_kwargs = build_collector_config_kwargs(
        strategy_binding, spec, study_data, data_plan, feature_authority=feature_authority,
        primary_interval=primary_interval,
        )

        strategy_config = strategy_binding.config_cls(**cfg_kwargs)
        strategy = strategy_binding.strategy_cls(strategy_config)
        engine.add_strategy(strategy)

        # 7. Execute in NautilusTrader event loop
        engine.run()

    # Extract collected surfaces from Strategy generically, failing closed rather than
    # silently reporting zero activity if bars genuinely loaded but the strategy exposes
    # no output interface at all (see runs/20260818_174901_..._day, where 213K+ bars
    # loaded and real regime transitions were processed internally, yet candidates/
    # observations silently extracted as empty because the strategy predated this
    # interface convention). Shared with READINESS R6 via output_manager.py so this
    # contract has exactly one implementation.
        bars_loaded_total = sum(telemetry.bars_loaded_by_tf.values())
        candidates_df, observations_df = verify_strategy_output_interface(strategy, bars_loaded_total)

    # Record bar callback breakdown
        b1s = getattr(strategy, "bars_1s_count", 0)
        b1m = getattr(strategy, "bars_1m_count", 0)
        if b1s > 0:
            telemetry.callbacks_by_tf["1s"] = b1s
        if b1m > 0:
            telemetry.callbacks_by_tf["1m"] = b1m
        telemetry.update_candidates(len(candidates_df))

    # Population funnel (Packet E). Only strategies that implement
    # get_population_funnel() (currently the representative collector) contribute a
    # funnel; anything else leaves telemetry's population_* fields at None, which
    # OutputManager.persist_collection treats as "nothing to reconcile".
        get_funnel = getattr(strategy, "get_population_funnel", None)
        if callable(get_funnel):
            funnel = get_funnel()
            telemetry.record_population_funnel(
                total_checkpoints=funnel["total_population_checkpoints"],
                declared_contract_exclusions=funnel["declared_contract_exclusions"],
                implementation_only_exclusions=funnel["implementation_only_exclusions"],
                candidates_emitted_raw=funnel["candidates_emitted"],
            )

        snapshot = telemetry.stop()

    # 7b. Composite-target independent replay parity (composite studies only). The
    # collector accumulates raw causal inputs per emitted observation; the oracle
    # re-derives every label from the compiled contract. A divergence is a defect.
        get_parity = getattr(strategy, "get_composite_target_parity", None)
        if callable(get_parity):
            parity = get_parity()
            if parity is not None:
                import json as _json
                (output_mgr.run_dir / "composite_target_replay_parity.json").write_text(
                    _json.dumps(parity, indent=2, default=str) + "\n", encoding="utf-8"
                )
                if not parity.get("passed", False):
                    raise RuntimeError(
                        f"COMPOSITE_TARGET_REPLAY_PARITY_FAILED: "
                        f"{parity.get('disposition_mismatches')} disposition / "
                        f"{parity.get('binary_label_mismatches')} label / "
                        f"{parity.get('censoring_mismatches')} censoring mismatches over "
                        f"{parity.get('rows_compared')} rows"
                    )

    # 8. Persist artifacts & update run manifests
        status_data = output_mgr.persist_collection(candidates_df, observations_df, snapshot)

    # 9. Print deterministic summary card
        print(f"""======================================================================
NT RUN COMPLETED: {study_data.study_id} ({output_mgr.run_id})
======================================================================
Mode: collect
Stage: {run_plan.stage.value.upper()}
Dates: {run_plan.start_date} to {run_plan.end_date}
Wall time: {round(snapshot.elapsed_seconds, 2)}s
Total bars: {snapshot.total_bars_processed:,} (1s: {b1s:,}, 1m: {b1m:,})
Candidates: {len(candidates_df)}
Observations: {len(observations_df)}
Throughput: {round(snapshot.throughput_bars_per_sec, 0):,} bars/sec
Memory (RSS): baseline={snapshot.baseline_process_rss_mb} MB, peak={snapshot.peak_process_rss_mb} MB (delta={snapshot.rss_delta_mb} MB)
Output directory: {output_mgr.run_dir}

Next stage:
  NOT AUTOMATICALLY STARTED
=====================================================================""")

        return status_data
    finally:
        if engine is not None:
            dispose = getattr(engine, "dispose", None)
            if callable(dispose):
                dispose()
