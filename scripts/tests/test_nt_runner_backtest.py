"""Tests for the B1/B2 standalone backtest harness.

Covers the contract surface that the Red Team is asked to attack:
  * generic catalog plan vs study-bound plan (no collector OOS leakage)
  * execution-mode contract validity and collector-default preservation
  * virtual vs simulated-order output contracts
  * unknown parameter / unregistered strategy rejection
  * sealed-study strategy override rejection
  * required-artifact failure behaviour
  * golden equivalence against frozen baselines (opt-in, see RUN_GOLDEN)

The golden-equivalence test replays a full year and is therefore gated behind
``RUN_GOLDEN_EQUIVALENCE=1`` so the default suite stays fast.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtests.nt_runtime.data_plan import (  # noqa: E402
    DataPlan,
    UnauthorizedExecutionDomainError,
    resolve_catalog_plan,
    resolve_data_plan,
)
from backtests.nt_runtime.engine_builder import (  # noqa: E402
    ExecutionMode,
    InvalidExecutionModeError,
)
from backtests.nt_runtime.modes.backtest import (  # noqa: E402
    MissingArtifactError,
    SealedStudyOverrideError,
    UnknownParameterError,
    _assert_required_artifacts,
    assert_strategy_matches_sealed_study,
    coerce_params,
    extract_virtual_outputs,
    resolve_backtest_plan,
    summarize_simulated,
    summarize_virtual,
)
from backtests.nt_runtime.strategy_binding import (  # noqa: E402
    STRATEGY_REGISTRY,
    UnregisteredStrategyBindingError,
    registered_order_handling,
    resolve_strategy_binding,
)
from scripts.capture_baseline_fixtures import (  # noqa: E402
    compare_normalized,
    find_latest_baseline,
    normalized_parquet_identity,
)

SEALED_STUDY = "studies/Gemini_clean_maturity_flip_rolling_5m_productivity"


# ---------------------------------------------------------------------------
# ScoreFanning config: mutable-default regression
# ---------------------------------------------------------------------------

# The legacy policy list, reproduced here independently of the strategy module so
# the test would fail if the strategy's values were changed rather than just its
# default mechanism.
LEGACY_SCORE_FANNING_POLICIES = [
    {"name": "R5", "threshold": 0.62, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0},
    {"name": "R2.5", "threshold": 0.50, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0},
]


def test_score_fanning_config_imports_and_instantiates():
    """msgspec rejects a non-empty mutable collection as a field default.

    Before the fix this raised TypeError at class-creation time, so the module
    could not even be imported and the legacy fixture failed at startup.
    """
    from strategies.score_fanning_strategy import ScoreFanningConfig, ScoreFanningStrategy  # noqa: F401

    cfg = ScoreFanningConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
    )
    assert cfg.instrument_id == "NQ.XCME"


def test_score_fanning_default_policies_preserve_legacy_values_exactly():
    from strategies.score_fanning_strategy import ScoreFanningConfig

    cfg = ScoreFanningConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
    )
    assert cfg.policies == LEGACY_SCORE_FANNING_POLICIES
    # Ordering matters: evaluators are constructed in list order.
    assert [p["name"] for p in cfg.policies] == ["R5", "R2.5"]
    # The R5 threshold is what makes results_R5.parquet legitimately absent
    # (the strategy emits a constant dummy_score of 0.55).
    assert cfg.policies[0]["threshold"] == 0.62
    assert cfg.policies[1]["threshold"] == 0.50


def test_score_fanning_default_policies_are_not_shared_between_instances():
    """The reason msgspec rejects mutable defaults: shared state across configs."""
    from strategies.score_fanning_strategy import ScoreFanningConfig

    kwargs = dict(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
    )
    a = ScoreFanningConfig(**kwargs)
    b = ScoreFanningConfig(**kwargs)
    assert a.policies == b.policies
    assert a.policies is not b.policies


def test_score_fanning_other_defaults_unchanged():
    """The fix must not have moved output paths or any other default."""
    from strategies.score_fanning_strategy import ScoreFanningConfig

    cfg = ScoreFanningConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
    )
    assert cfg.checkpoint_dir == "backtests/results/checkpoints"


def test_score_fanning_explicit_policies_still_override_the_default():
    from strategies.score_fanning_strategy import ScoreFanningConfig

    custom = [{"name": "X", "threshold": 0.9, "sl_atr_mult": 1.0, "pt_atr_mult": 1.0}]
    cfg = ScoreFanningConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        policies=custom,
    )
    assert cfg.policies == custom


# ---------------------------------------------------------------------------
# Generic catalog plan vs study-bound plan
# ---------------------------------------------------------------------------


def test_resolve_catalog_plan_is_generic_and_has_no_chronology_gates():
    """A prohibited-for-the-collector year must be fine for an unrelated backtest."""
    plan = resolve_catalog_plan("NQ", "2025-03-01", "2025-03-31", warmup_days=5)
    assert isinstance(plan, DataPlan)
    assert plan.symbol == "NQ"
    assert plan.start_dt.year == 2025
    assert plan.warmup_start_dt == plan.start_dt - pd.Timedelta(days=5)


def test_study_bound_plan_still_blocks_prohibited_years():
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study

    study = load_compiled_study(REPO_ROOT / SEALED_STUDY)
    with pytest.raises(UnauthorizedExecutionDomainError, match="UNAUTHORIZED_EXECUTION_DOMAIN"):
        resolve_data_plan(study, "2025-03-01", "2025-03-01")


def test_study_bound_plan_still_blocks_locked_dev_year():
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study

    study = load_compiled_study(REPO_ROOT / SEALED_STUDY)
    with pytest.raises(UnauthorizedExecutionDomainError, match="OOS_LOCKED_UNTIL_FREEZE"):
        resolve_data_plan(study, "2024-06-01", "2024-06-01")


def test_study_bound_plan_allows_authorized_year_and_matches_generic_geometry():
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study

    study = load_compiled_study(REPO_ROOT / SEALED_STUDY)
    bound = resolve_data_plan(study, "2023-03-03", "2023-03-03")
    generic = resolve_catalog_plan("NQ", "2023-03-03", "2023-03-03")
    # The split must not change any resolved value; only the gates differ.
    assert bound == generic


def test_catalog_plan_rejects_unsupported_product_and_inverted_dates():
    with pytest.raises(ValueError, match="Unsupported product"):
        resolve_catalog_plan("XYZ", "2023-01-01", "2023-01-02")
    with pytest.raises(ValueError, match="cannot be after"):
        resolve_catalog_plan("NQ", "2023-05-01", "2023-01-02")


# ---------------------------------------------------------------------------
# Execution mode contract
# ---------------------------------------------------------------------------


def test_collector_default_execution_mode_matches_nt_add_venue_defaults():
    """Introducing the contract must not change collector behaviour."""
    import inspect

    from nautilus_trader.backtest.engine import BacktestEngine

    params = inspect.signature(BacktestEngine.add_venue).parameters
    mode = ExecutionMode.collector_default()
    assert mode.bar_execution == params["bar_execution"].default
    assert mode.bar_adaptive_high_low_ordering == params["bar_adaptive_high_low_ordering"].default


def test_legacy_backtest_mode_enables_adaptive_high_low_ordering():
    """Both legacy runners pass bar_adaptive_high_low_ordering=True."""
    mode = ExecutionMode.legacy_backtest("simulated_orders")
    assert mode.bar_adaptive_high_low_ordering is True
    assert mode.bar_execution is True


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"order_handling": "bogus"}, "INVALID_ORDER_HANDLING"),
        ({"fill_model": "nope"}, "INVALID_FILL_MODEL"),
        ({"fill_model": "tick"}, "UNSUPPORTED_FILL_MODEL"),
        ({"run_window_mode": "sideways"}, "INVALID_RUN_WINDOW_MODE"),
        ({"oms_type": "WAT"}, "INVALID_OMS_TYPE"),
        ({"account_type": "WAT"}, "INVALID_ACCOUNT_TYPE"),
        ({"base_currency": "EUR"}, "UNSUPPORTED_BASE_CURRENCY"),
    ],
)
def test_invalid_execution_mode_is_rejected_with_actionable_error(kwargs, match):
    with pytest.raises(InvalidExecutionModeError, match=match):
        ExecutionMode(**kwargs)


def test_execution_mode_records_warmup_dispatched_as_observation_not_assumption():
    mode = ExecutionMode.legacy_backtest("virtual")
    assert mode.warmup_dispatched is None
    observed = mode.with_observation(warmup_dispatched=True)
    assert observed.warmup_dispatched is True
    assert observed.to_dict()["run_window"]["warmup_dispatched"] is True


# ---------------------------------------------------------------------------
# Strategy binding safety
# ---------------------------------------------------------------------------


def test_backtest_mode_blocks_arbitrary_import_strings():
    with pytest.raises(UnregisteredStrategyBindingError, match="UNREGISTERED_STRATEGY_IMPORT_BLOCKED"):
        resolve_strategy_binding("os.path.join", mode="backtest")


def test_collect_mode_still_allows_study_declared_dotted_paths():
    """Collect mode is authorized by a compiled+sealed contract; do not break it."""
    binding = resolve_strategy_binding(
        "strategies.flip_prediction_collector.FlipPredictionCollector", mode="collect"
    )
    assert binding.class_name == "FlipPredictionCollector"


def test_registered_fqn_resolves_through_the_registry_in_backtest_mode():
    binding = resolve_strategy_binding("strategies.w4_exit_strategy.W4ExitStrategy", mode="backtest")
    assert binding.binding_id == "w4_exit_strategy"
    assert binding.config_class_name == "W4ExitConfig"


def test_registry_declares_order_handling_for_backtest_strategies():
    for key, entry in STRATEGY_REGISTRY.items():
        if "backtest" in entry.get("supported_modes", []):
            assert registered_order_handling(key) in ("virtual", "simulated_orders"), key


def test_collector_strategy_is_not_runnable_in_backtest_mode():
    with pytest.raises(UnregisteredStrategyBindingError, match="does not support mode"):
        resolve_strategy_binding("flip_prediction_collector", mode="backtest")


# ---------------------------------------------------------------------------
# Sealed study protection
# ---------------------------------------------------------------------------


def test_sealed_study_strategy_override_is_blocked():
    with pytest.raises(SealedStudyOverrideError, match="SEALED_STUDY_STRATEGY_OVERRIDE_BLOCKED"):
        assert_strategy_matches_sealed_study(REPO_ROOT / SEALED_STUDY, "w4_exit_strategy")


def test_sealed_study_accepts_its_own_declared_strategy():
    declared = assert_strategy_matches_sealed_study(
        REPO_ROOT / SEALED_STUDY, "strategies.flip_prediction_collector.FlipPredictionCollector"
    )
    assert declared == "strategies.flip_prediction_collector.FlipPredictionCollector"


def test_running_w4_under_the_sealed_study_is_blocked_end_to_end():
    with pytest.raises(SealedStudyOverrideError):
        resolve_backtest_plan(
            "w4_exit_strategy", "NQ", "2023-01-01", "2023-12-31",
            study_path=REPO_ROOT / SEALED_STUDY,
        )


# ---------------------------------------------------------------------------
# Typed parameters
# ---------------------------------------------------------------------------


def test_unknown_parameter_is_rejected():
    from strategies.w4_exit_strategy import W4ExitConfig

    with pytest.raises(UnknownParameterError, match="UNKNOWN_PARAMETER"):
        coerce_params(W4ExitConfig, {"not_a_field": "1"})


def test_declared_parameters_are_type_coerced():
    from strategies.w4_exit_strategy import W4ExitConfig

    out = coerce_params(
        W4ExitConfig,
        {"year": "2023", "theta": "0.62", "N": "10", "policy": "B1", "use_trailing_stop": "false"},
    )
    assert out == {
        "year": 2023, "theta": 0.62, "N": 10, "policy": "B1", "use_trailing_stop": False,
    }
    assert isinstance(out["year"], int) and isinstance(out["theta"], float)


def test_bad_parameter_value_is_rejected_not_silently_coerced():
    from strategies.w4_exit_strategy import W4ExitConfig

    with pytest.raises(UnknownParameterError, match="INVALID_PARAMETER_VALUE"):
        coerce_params(W4ExitConfig, {"year": "not_a_year"})
    with pytest.raises(UnknownParameterError, match="INVALID_PARAMETER_VALUE"):
        coerce_params(W4ExitConfig, {"use_trailing_stop": "maybe"})


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


class _FakeTrade:
    def __init__(self, tid, pnl, is_open, reason):
        self.trade_id = tid
        self.entry_time = 1_000 + tid
        self.entry_px = 100.0 + tid
        self.direction = -1
        self.qty = 1
        self.atr_at_entry = 15.0
        self.exit_time = None if is_open else 2_000 + tid
        self.exit_px = None if is_open else 101.0
        self.exit_reason = reason
        self.pnl = pnl
        self.is_open = is_open


class _FakeEvaluator:
    def __init__(self, name, closed, active):
        self.name = name
        self.trade_history = closed
        self.active_trades = active


class _FakeVirtualStrategy:
    def __init__(self, evaluators):
        self.evaluators = evaluators


def test_virtual_contract_emits_one_table_per_evaluator_with_open_state():
    strategy = _FakeVirtualStrategy([
        _FakeEvaluator("R2.5", [_FakeTrade(1, 50.0, False, "PT"), _FakeTrade(2, -20.0, False, "SL")],
                       [_FakeTrade(3, 0.0, True, None)]),
        _FakeEvaluator("R5", [], []),
    ])
    tables = extract_virtual_outputs(strategy)

    assert set(tables) == {"R2.5", "R5"}
    assert len(tables["R2.5"]) == 3
    assert tables["R5"].empty
    assert list(tables["R2.5"].columns) == [
        "trade_id", "entry_time", "entry_px", "direction", "qty", "atr",
        "exit_time", "exit_px", "exit_reason", "pnl", "is_open",
    ]

    summary = summarize_virtual(tables)
    r25 = summary["per_policy"]["R2.5"]
    assert r25["trade_count"] == 3
    assert r25["open_count"] == 1
    assert r25["closed_count"] == 2
    assert r25["gross_pnl"] == pytest.approx(30.0)
    assert r25["win_rate"] == pytest.approx(0.5)
    assert r25["exit_reason_distribution"] == {"PT": 1, "SL": 1}
    assert summary["per_policy"]["R5"]["trade_count"] == 0


def test_virtual_contract_rejects_a_strategy_with_no_evaluators():
    from backtests.nt_runtime.modes.backtest import BacktestContractError

    class _NoEvaluators:
        pass

    with pytest.raises(BacktestContractError, match="VIRTUAL_CONTRACT_UNSATISFIED"):
        extract_virtual_outputs(_NoEvaluators())


def test_simulated_summary_splits_closed_and_open_and_computes_profit_factor():
    closed = pd.DataFrame({"realized_pnl": ["100.0 USD", "-40.0 USD", "60.0 USD"]})
    outputs = {
        "closed_positions": closed,
        "open_positions": pd.DataFrame({"realized_pnl": ["0.0 USD"]}),
        "strategy_trades": pd.DataFrame({"x": [1, 2]}),
        "positions_report_rows": 4,
    }
    s = summarize_simulated(outputs)
    assert s["closed_position_count"] == 3
    assert s["open_position_count"] == 1
    assert s["positions_report_rows"] == 4
    assert s["strategy_trade_count"] == 2
    assert s["gross_pnl"] == pytest.approx(120.0)
    assert s["profit_factor"] == pytest.approx(160.0 / 40.0)
    assert s["win_rate"] == pytest.approx(2 / 3)


def test_virtual_and_simulated_contracts_produce_different_shapes():
    """The whole point of keying on order_handling: the outputs are not interchangeable."""
    virtual = summarize_virtual({"R5": pd.DataFrame(columns=["pnl", "is_open", "exit_reason"])})
    simulated = summarize_simulated({
        "closed_positions": pd.DataFrame(), "open_positions": pd.DataFrame(),
        "strategy_trades": pd.DataFrame(), "positions_report_rows": 0,
    })
    assert virtual["order_handling"] == "virtual" and "per_policy" in virtual
    assert simulated["order_handling"] == "simulated_orders" and "closed_position_count" in simulated
    assert "per_policy" not in simulated


# ---------------------------------------------------------------------------
# Artifact completeness
# ---------------------------------------------------------------------------


def test_missing_required_artifact_blocks_success(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
    # resolved_config.json / execution_metrics.json / summary.json deliberately absent
    with pytest.raises(MissingArtifactError, match="REQUIRED_ARTIFACTS_MISSING"):
        _assert_required_artifacts(run_dir, "virtual", {})


def test_simulated_run_without_trades_artifact_blocks_success(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "logs").mkdir(parents=True)
    for name in ("run_manifest.json", "resolved_config.json", "execution_metrics.json", "summary.json"):
        (run_dir / name).write_text("{}", encoding="utf-8")
    with pytest.raises(MissingArtifactError, match="trades.parquet"):
        _assert_required_artifacts(run_dir, "simulated_orders", {})


def test_complete_artifact_set_passes(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "logs").mkdir(parents=True)
    for name in ("run_manifest.json", "resolved_config.json", "execution_metrics.json", "summary.json"):
        (run_dir / name).write_text("{}", encoding="utf-8")
    _assert_required_artifacts(run_dir, "simulated_orders", {"trades": "x"})


# ---------------------------------------------------------------------------
# CLI / config validation
# ---------------------------------------------------------------------------


def test_cli_rejects_unknown_config_keys(tmp_path):
    from backtests.run_backtest import ConfigError, load_backtest_config

    p = tmp_path / "c.yaml"
    p.write_text("strategy: w4_exit_strategy\nnot_a_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="CONFIG_UNKNOWN_KEYS"):
        load_backtest_config(p)


def test_cli_rejects_missing_config_file(tmp_path):
    from backtests.run_backtest import ConfigError, load_backtest_config

    with pytest.raises(ConfigError, match="CONFIG_NOT_FOUND"):
        load_backtest_config(tmp_path / "nope.yaml")


def test_cli_rejects_malformed_param():
    from backtests.run_backtest import ConfigError, parse_params

    with pytest.raises(ConfigError, match="INVALID_PARAM"):
        parse_params(["theta"])
    with pytest.raises(ConfigError, match="INVALID_PARAM"):
        parse_params(["=0.62"])
    assert parse_params(["theta=0.62", "policy=B1"]) == {"theta": "0.62", "policy": "B1"}


def test_cli_requires_explicit_inputs_no_implicit_latest():
    from backtests.run_backtest import main

    rc = main(["--strategy", "w4_exit_strategy"])  # no symbol/dates
    assert rc == 2


def test_cli_rejects_resume_as_unsupported():
    from backtests.run_backtest import main

    rc = main([
        "--strategy", "w4_exit_strategy", "--symbol", "NQ",
        "--start-date", "2023-01-01", "--end-date", "2023-01-02", "--resume",
    ])
    assert rc == 2


def test_shipped_w4_config_is_valid_and_pins_every_inherited_field():
    from backtests.run_backtest import load_backtest_config
    from strategies.w4_exit_strategy import W4ExitConfig

    cfg = load_backtest_config(REPO_ROOT / "backtests/configs/w4_exit_b1_2023.yaml")
    assert cfg["execution_mode"]["run_window_mode"] == "from_start"
    assert cfg["execution_mode"]["bar_adaptive_high_low_ordering"] is True
    assert cfg["params"]["year"] == 2023
    assert cfg["params"]["entry_qty"] == 1  # policy-derived: 2 only for B4

    # Every pinned value must equal the legacy default it claims to pin.
    reference = W4ExitConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        year=2023, entry_qty=1, policy="B1", theta=0.62, N=10,
    )
    for key, value in cfg["params"].items():
        assert getattr(reference, key) == value, f"{key} does not match the legacy default"


def test_shipped_configs_resolve_into_plans():
    from backtests.run_backtest import load_backtest_config

    cfg = load_backtest_config(REPO_ROOT / "backtests/configs/w4_exit_b1_2023.yaml")
    plan = resolve_backtest_plan(
        cfg["strategy"], cfg["symbol"], cfg["start_date"], cfg["end_date"],
        warmup_days=cfg["warmup_days"],
        params={k: str(v) for k, v in cfg["params"].items()},
        run_window_mode=cfg["execution_mode"]["run_window_mode"],
    )
    d = plan.to_dict()
    assert d["execution_mode"]["order_handling"] == "simulated_orders"
    assert d["execution_mode"]["run_window"]["mode"] == "from_start"
    # Matches the legacy load window exactly.
    assert d["dates"]["load_start"].startswith("2022-12-27")
    assert d["dates"]["load_end"].startswith("2023-12-31")


def test_dry_run_resolves_without_executing(tmp_path):
    from backtests.nt_runtime.modes.backtest import run_backtest_mode

    result = run_backtest_mode(
        strategy="w4_exit_strategy", symbol="NQ",
        start_date="2023-01-01", end_date="2023-12-31",
        params={"year": "2023", "policy": "B1"},
        run_window_mode="from_start", dry_run=True, output_dir=tmp_path,
    )
    assert result["status"] == "RESOLVED"
    assert result["plan"]["execution_mode"]["order_handling"] == "simulated_orders"
    assert not list(tmp_path.iterdir())  # nothing written


# ---------------------------------------------------------------------------
# Golden equivalence (opt-in: replays a full year)
# ---------------------------------------------------------------------------

RUN_GOLDEN = os.environ.get("RUN_GOLDEN_EQUIVALENCE") == "1"


def _baseline_or_fail(fixture_id: str):
    """Never let an equivalence test silently 'prove' equivalence against nothing."""
    baseline = find_latest_baseline(fixture_id)
    assert baseline is not None, (
        f"no valid baseline for {fixture_id}; run scripts/capture_baseline_fixtures.py"
    )
    return baseline


def _ref_identities(baseline) -> dict:
    return {
        Path(t["target_path"]).name: t
        for t in baseline["targets"]
        if t.get("normalized_identity") and "normalized_sha256" in t["normalized_identity"]
    }


def test_both_fixtures_have_valid_baselines():
    """Both legacy fixtures must run unmodified before equivalence means anything."""
    for fixture_id in ("fixture_1_score_fanning", "fixture_2_w4_b1"):
        baseline = _baseline_or_fail(fixture_id)
        assert baseline["status"] == "SUCCESS"
        assert baseline["baseline_valid"] is True


def test_baseline_closures_record_complete_provenance():
    """A baseline is only trustworthy if its source closure is complete."""
    f1 = _baseline_or_fail("fixture_1_score_fanning")["source_closure"]
    f2 = _baseline_or_fail("fixture_2_w4_b1")["source_closure"]

    # Regression: utils/__init__.py executes on `from utils.runner...` and was
    # previously missing from the closure entirely.
    assert "utils/__init__.py" in f1["discovery"]
    assert f1["discovery"]["utils/__init__.py"] == "package_init"
    assert "strategies/score_fanning_strategy.py" in f1["discovery"]

    assert "strategies/w4_exit_strategy.py" in f2["discovery"]
    assert "backtests/baseline_flip_parity/strategy.py" in f2["discovery"]

    for closure in (f1, f2):
        assert closure["stable_across_run"] is True
        assert closure["drifted_files"] == []
        assert closure["file_count"] == len(closure["hashes_before"])
        assert all(v for v in closure["hashes_before"].values()), "unhashed closure file"


@pytest.mark.skipif(not RUN_GOLDEN, reason="set RUN_GOLDEN_EQUIVALENCE=1 (replays market data)")
def test_score_fanning_harness_matches_frozen_baseline(tmp_path):
    """Fixture 1: virtual-evaluator contract against the frozen baseline."""
    from backtests.nt_runtime.modes.backtest import run_backtest_mode
    from backtests.run_backtest import load_backtest_config

    baseline = _baseline_or_fail("fixture_1_score_fanning")
    ref = _ref_identities(baseline)
    assert "results_R2.5.parquet" in ref, "baseline has no usable results_R2.5 identity"

    cfg = load_backtest_config(REPO_ROOT / "backtests/configs/score_fanning_2023_03_03.yaml")
    result = run_backtest_mode(
        strategy=cfg["strategy"], symbol=cfg["symbol"],
        start_date=cfg["start_date"], end_date=cfg["end_date"],
        warmup_days=cfg["warmup_days"],
        run_window_mode=cfg["execution_mode"]["run_window_mode"],
        order_handling=cfg["execution_mode"]["order_handling"],
        output_dir=tmp_path,
        trader_id="STAGED-BACKTESTER",
    )

    produced = Path(result["artifacts"]["results_R2.5"])
    comparison = compare_normalized(
        ref["results_R2.5.parquet"]["normalized_identity"], normalized_parquet_identity(produced)
    )
    assert comparison["equivalent"], (
        f"GOLDEN_EQUIVALENCE_FAILED for results_R2.5.parquet: {comparison['differences']}\n"
        f"baseline={baseline['_capture_dir']}\nharness run={result['run_dir']}"
    )

    # The virtual contract's other half: R5 produces no table, and NT places no orders.
    assert "results_R5" not in result["artifacts"]
    assert "R5" in result["summary"]["evaluator_tables_empty"]
    assert result["summary"]["nt_positions_report_empty"] is True

    # And the baseline agrees that R5 was legitimately absent.
    r5 = next(t for t in baseline["targets"] if t["target_path"].endswith("results_R5.parquet"))
    assert r5["status"] == "expected_absent_verified"


@pytest.mark.skipif(not RUN_GOLDEN, reason="set RUN_GOLDEN_EQUIVALENCE=1 (replays a full year)")
def test_w4_harness_matches_frozen_baseline(tmp_path):
    from backtests.nt_runtime.modes.backtest import run_backtest_mode
    from backtests.run_backtest import load_backtest_config

    baseline = find_latest_baseline("fixture_2_w4_b1")
    assert baseline is not None, "no valid fixture_2 baseline; run scripts/capture_baseline_fixtures.py"

    ref = {
        Path(t["target_path"]).name: t
        for t in baseline["targets"]
        if t.get("normalized_identity") and "normalized_sha256" in t["normalized_identity"]
    }
    assert "trades.parquet" in ref, "baseline has no usable trades.parquet identity"

    cfg = load_backtest_config(REPO_ROOT / "backtests/configs/w4_exit_b1_2023.yaml")
    result = run_backtest_mode(
        strategy=cfg["strategy"], symbol=cfg["symbol"],
        start_date=cfg["start_date"], end_date=cfg["end_date"],
        warmup_days=cfg["warmup_days"],
        params={k: str(v) for k, v in cfg["params"].items()},
        run_window_mode=cfg["execution_mode"]["run_window_mode"],
        order_handling=cfg["execution_mode"]["order_handling"],
        output_dir=tmp_path,
        # Reproducing the legacy fixture includes reproducing its trader identity.
        # NT composes client order ids as O-<date>-<time>-<trader-suffix>-<seq>, so a
        # generated trader_id would change opening_order_id/closing_order_id even
        # though every economic field is identical. Pinning it lets the comparison
        # cover the order-id columns instead of excluding them.
        trader_id="W4-BACKTESTER",
    )

    produced = Path(result["artifacts"]["trades"])
    candidate = normalized_parquet_identity(produced)
    comparison = compare_normalized(ref["trades.parquet"]["normalized_identity"], candidate)

    assert comparison["equivalent"], (
        f"GOLDEN_EQUIVALENCE_FAILED for trades.parquet: {comparison['differences']}\n"
        f"baseline={baseline['_capture_dir']}\nharness run={result['run_dir']}"
    )

    # The strategy's own blended-PnL log must match too, not just the positions report.
    if "strategy_trades.parquet" in ref and "strategy_trades" in result["artifacts"]:
        st = normalized_parquet_identity(Path(result["artifacts"]["strategy_trades"]))
        st_cmp = compare_normalized(ref["strategy_trades.parquet"]["normalized_identity"], st)
        assert st_cmp["equivalent"], (
            f"GOLDEN_EQUIVALENCE_FAILED for strategy_trades.parquet: {st_cmp['differences']}"
        )
