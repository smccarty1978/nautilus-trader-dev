"""Collect Mode Orchestrator for NautilusTrader Generic Runtime.
=============================================================
Executes live ML research surface generation inside NautilusTrader event loop.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from backtests.nt_runtime.data_plan import resolve_data_plan
from backtests.nt_runtime.engine_builder import build_engine
from backtests.nt_runtime.output_manager import OutputManager
from backtests.nt_runtime.run_plan import RunStage, resolve_run_plan
from backtests.nt_runtime.strategy_binding import resolve_strategy_binding
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
) -> Dict[str, Any]:
    """Runs a study in 'collect' mode through the NautilusTrader BacktestEngine."""
    # 1. Load and validate compiled study
    study_data = load_compiled_study(study_path)
    spec = study_data.spec

    # 2. Cryptographic Pre-Execution Audit Seal Check (fail-closed)
    seal_data = verify_preexec_audit_seal(study_data.study_dir)

    # 3. Resolve bounded run plan & data plan
    run_plan = resolve_run_plan(study_data, stage=stage, reference_date=date_override)

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
        current_val_sha = hashlib.sha256(val_script_path.read_bytes()).hexdigest()
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

    data_plan = resolve_data_plan(study_data, start_date=run_plan.start_date, end_date=run_plan.end_date)

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
    )
    telemetry = CausalTelemetry()
    telemetry.start()

    # Everything from here on can fail, and a failure must leave a terminal status behind.
    # Without this the run directory keeps the RUNNING it was created with, and an
    # abandoned run becomes indistinguishable from one still in flight (H2).
    try:
        return _execute_collect(
            study_data, spec, data_plan, run_plan, strategy_binding,
            output_mgr, telemetry, log_level,
        )
    except KeyboardInterrupt as exc:
        output_mgr.finalize_failed(exc, status="ABORTED")
        raise
    except BaseException as exc:
        output_mgr.finalize_failed(exc, status="FAILED")
        raise


def _execute_collect(
    study_data,
    spec,
    data_plan,
    run_plan,
    strategy_binding,
    output_mgr,
    telemetry,
    log_level: str,
) -> Dict[str, Any]:
    """Runs the engine and persists results. Split out so the caller owns failure status."""
    # 5. Construct BacktestEngine and load bars in causal order
    engine, instrument = build_engine(data_plan, log_level=log_level, telemetry=telemetry)

    # 6. Build StrategyConfig
    cfg_kwargs = {
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
    if hasattr(strategy_binding.config_cls, "feature_list"):
        cfg_kwargs["feature_list"] = spec.features.feature_list
    # Session and censoring come from the compiled contracts, not from strategy defaults:
    # the runtime previously hard-coded a session window that disagreed with the contract,
    # and ignored the declared censoring policy entirely.
    if hasattr(strategy_binding.config_cls, "session"):
        cfg_kwargs["session"] = spec.population.session or "RTH"
    if hasattr(strategy_binding.config_cls, "session_end_censoring"):
        censoring = (study_data.contracts.get("target_contract", {}) or {}).get("censoring_policy", {})
        cfg_kwargs["session_end_censoring"] = bool(censoring.get("session_end_censoring", True))
    # Phase-zero authentication gate (fail-closed). A collector that declares this field
    # authenticates itself against a manifest at a study-relative path; this runtime never
    # knew about the field before, so it was always left at its "" default and every such
    # collector failed closed with "phase-zero authorization missing" regardless of whether
    # a valid manifest existed. The path is derived generically from study_data.study_dir,
    # not from any collector's own __file__, so this applies to any study using the pattern.
    if hasattr(strategy_binding.config_cls, "phase0_manifest_path"):
        cfg_kwargs["phase0_manifest_path"] = str(study_data.study_dir / "artifacts" / "phase0_source_manifest.json")

    strategy_config = strategy_binding.config_cls(**cfg_kwargs)
    strategy = strategy_binding.strategy_cls(strategy_config)
    engine.add_strategy(strategy)

    # 7. Execute in NautilusTrader event loop
    engine.run()

    # Extract collected surfaces from Strategy generically. Returns whether any
    # matching attribute/method was found at all, distinct from "found but empty" --
    # a strategy with no output interface is unverifiable, not merely unproductive.
    def _extract_df(strat: Any, attr_names: List[str]) -> Tuple[pd.DataFrame, bool]:
        for name in attr_names:
            val = getattr(strat, name, None)
            if val is not None:
                if callable(val):
                    res = val()
                    if isinstance(res, pd.DataFrame):
                        return res, True
                elif isinstance(val, pd.DataFrame):
                    return val, True
        return pd.DataFrame(), False

    candidates_df, candidates_interface_found = _extract_df(
        strategy, ["get_candidates_dataframe", "get_candidates_df", "candidates_df", "candidates_dataframe"]
    )
    observations_df, observations_interface_found = _extract_df(
        strategy, ["get_observations_dataframe", "get_observations_df", "observations_df", "observations_dataframe"]
    )

    # Fail closed rather than silently report zero activity: if the engine genuinely
    # loaded bars but the strategy exposes no output interface at all, we cannot tell
    # a legitimately empty result apart from real processing that was never surfaced
    # (see runs/20260818_174901_..._day, where 213K+ bars loaded and real regime
    # transitions were processed internally, yet candidates/observations silently
    # extracted as empty because the strategy predates this interface convention).
    bars_loaded_total = sum(telemetry.bars_loaded_by_tf.values())
    if bars_loaded_total > 0 and not candidates_interface_found:
        raise RuntimeError(
            f"STRATEGY_OUTPUT_INTERFACE_MISSING: {bars_loaded_total} bars were loaded into the "
            f"engine but {type(strategy).__name__} implements none of get_candidates_dataframe/"
            f"get_candidates_df/candidates_df/candidates_dataframe. Cannot verify whether the "
            f"loaded bars were processed; refusing to report a candidates count."
        )
    if bars_loaded_total > 0 and not observations_interface_found:
        raise RuntimeError(
            f"STRATEGY_OUTPUT_INTERFACE_MISSING: {bars_loaded_total} bars were loaded into the "
            f"engine but {type(strategy).__name__} implements none of get_observations_dataframe/"
            f"get_observations_df/observations_df/observations_dataframe. Cannot verify whether "
            f"the loaded bars were processed; refusing to report an observations count."
        )

    # Record bar callback breakdown
    b1s = getattr(strategy, "bars_1s_count", 0)
    b1m = getattr(strategy, "bars_1m_count", 0)
    if b1s > 0:
        telemetry.callbacks_by_tf["1s"] = b1s
    if b1m > 0:
        telemetry.callbacks_by_tf["1m"] = b1m
    telemetry.update_candidates(len(candidates_df))

    snapshot = telemetry.stop()

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
