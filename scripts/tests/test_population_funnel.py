"""Regression tests for Phase 1 Packet E (population-funnel instrumentation).

Covers:
  - CleanFlipCollector._on_1s: each terminal population bucket (declared_contract_
    exclusion / implementation_only_exclusion / candidate_emitted) increments exactly
    the counter Packet E requires, without moving any existing gate
  - structural proof that implementation_only_exclusions has no reachable increment
    site in _on_1s (Requirement E3)
  - backtests.nt_runtime.output_manager.reconcile_population_funnel: exact identity
    reconciliation, hard failure on imbalance, candidate-count parity against the
    persisted (warmup-window-filtered) candidates_df
  - OutputManager.persist_collection: funnel fields actually land in status.json /
    collection_manifest.json / run_manifest.json, and strategies without funnel
    telemetry are unaffected (backward compatible with D1/D2)
"""
from __future__ import annotations

import inspect
import json
import re
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.output_manager import (
    CANDIDATE_KEY_COLUMNS,
    OutputManager,
    reconcile_population_funnel,
)
from backtests.nt_runtime.run_plan import RunPlan, RunStage
from backtests.nt_runtime.telemetry import CausalTelemetry
from research.schemas.study_spec import StudySpec
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import (
    NS, CleanFlipCollector,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# =============================================================================
# Part 1 -- collector-level funnel accounting (_on_1s)
# =============================================================================

class _NoOpFeatures:
    def update_1s(self, bar):
        pass

    def snapshot(self, names, ctx):
        return {n: 0.0 for n in names}


class _NoOpGeometry:
    def on_1s(self, *args):
        pass

    def snapshot(self, *args, **kwargs):
        return {}


class _NoOpRegistry:
    def audit_provenance(self, ts):
        pass

    def get(self, timeframe):
        return None


def _init_collector() -> CleanFlipCollector:
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    collector._authorized_years = {2024}
    collector._was_rth_decision = False
    collector._last_seen_1s_event_ns = None
    collector._last_seen_1s_decision_ns = None
    collector._last_seen_1m_init_ns = None
    collector._last_eligible_close = None
    collector._current_regime_start_atr = None
    collector._current_regime_start_ns = None
    collector._current_regime_anchor = None
    collector._regime = SimpleNamespace(regime=0, atr=1.0)
    collector._running_mfe_atr = 0.0
    collector._progress_windows = 0
    collector._last_progress_extreme_ns = None
    collector._next_checkpoint_index = 0
    collector.candidates_log = []
    collector._pending_labels = deque()
    collector._features = _NoOpFeatures()
    collector._geometry = _NoOpGeometry()
    collector._registry = _NoOpRegistry()
    collector._feature_regime = SimpleNamespace()

    collector.telemetry_total_checkpoints = 0
    collector.telemetry_rth_gate_pass = 0
    collector.telemetry_age_gate_pass = 0
    collector.telemetry_mfe_gate_pass = 0
    collector.telemetry_progress_gate_pass = 0
    collector.telemetry_retention_gate_pass = 0
    collector.telemetry_declared_population_eligible = 0
    collector.telemetry_candidates_emitted = 0
    collector.telemetry_declared_contract_exclusions = 0
    collector.telemetry_implementation_only_exclusions = 0
    return collector


def _bar(decision_ns: int, *, open_=100.0, high=101.0, low=99.0, close=101.0):
    return SimpleNamespace(
        ts_event=decision_ns - NS, ts_init=decision_ns,
        open=open_, high=high, low=low, close=close, volume=1.0,
    )


# 09:00 America/Chicago (CST, winter) -- inside RTH [08:30, 15:00).
T_RTH = int(pd.Timestamp("2024-01-02 15:00:00", tz="UTC").value)
# 18:00 America/Chicago the prior day -- outside RTH.
T_NON_RTH = int(pd.Timestamp("2024-01-01 00:00:00", tz="UTC").value)

assert T_RTH % (5 * NS) == 0
assert T_NON_RTH % (5 * NS) == 0


# ---------------------------------------------------------------------------
# 1. observed 5s-aligned callback increments total_population_checkpoints once
# ---------------------------------------------------------------------------

def test_5s_aligned_checkpoint_increments_total_exactly_once():
    collector = _init_collector()
    collector._on_1s(_bar(T_NON_RTH))
    assert collector.telemetry_total_checkpoints == 1


def test_non_5s_aligned_1s_bar_does_not_increment_total():
    collector = _init_collector()
    collector._on_1s(_bar(T_NON_RTH + NS))  # +1s -- not a 5s-aligned decision
    assert collector.telemetry_total_checkpoints == 0


# ---------------------------------------------------------------------------
# 2. non-RTH exclusion increments declared_contract_exclusions
# ---------------------------------------------------------------------------

def test_non_rth_checkpoint_is_a_declared_contract_exclusion():
    collector = _init_collector()
    collector._on_1s(_bar(T_NON_RTH))
    assert collector.telemetry_total_checkpoints == 1
    assert collector.telemetry_declared_contract_exclusions == 1
    assert collector.telemetry_implementation_only_exclusions == 0
    assert collector.telemetry_candidates_emitted == 0


# ---------------------------------------------------------------------------
# 3. missing established regime increments declared_contract_exclusions
# ---------------------------------------------------------------------------

def test_missing_established_regime_is_a_declared_contract_exclusion():
    collector = _init_collector()
    assert collector._current_regime_start_atr is None
    collector._on_1s(_bar(T_RTH))
    assert collector.telemetry_total_checkpoints == 1
    assert collector.telemetry_declared_contract_exclusions == 1
    assert collector.telemetry_implementation_only_exclusions == 0
    assert collector.telemetry_candidates_emitted == 0


# ---------------------------------------------------------------------------
# 4. qualification-fail branch increments declared_contract_exclusions
# ---------------------------------------------------------------------------

def test_qualification_fail_branch_is_a_declared_contract_exclusion():
    collector = _init_collector()
    decision_ns = T_RTH
    collector._current_regime_start_atr = 1.0
    # Age gate requires > 120s; 50s keeps every gate under test but age failing.
    collector._current_regime_start_ns = decision_ns - 50 * NS
    collector._on_1s(_bar(decision_ns))
    assert collector.telemetry_total_checkpoints == 1
    assert collector.telemetry_declared_contract_exclusions == 1
    assert collector.telemetry_declared_population_eligible == 0
    assert collector.telemetry_implementation_only_exclusions == 0
    assert collector.telemetry_candidates_emitted == 0


# ---------------------------------------------------------------------------
# 5. eligible candidate increments candidates_emitted
# ---------------------------------------------------------------------------

def test_eligible_checkpoint_emits_candidate():
    collector = _init_collector()
    decision_ns = T_RTH
    collector._regime.regime = 1
    collector._current_regime_start_atr = 1.0
    collector._current_regime_start_ns = decision_ns - 200 * NS  # age_pass
    collector._current_regime_anchor = 100.0
    collector._running_mfe_atr = 1.0  # mfe_pass
    collector._progress_windows = 2  # progress_pass
    # close=101 -> retained_mfe_ratio = (101-100)/1.0 / 1.0 = 1.0 >= 0.5 -> retention_pass
    collector._on_1s(_bar(decision_ns, close=101.0, high=101.0, low=99.0, open_=100.0))

    assert collector.telemetry_total_checkpoints == 1
    assert collector.telemetry_declared_population_eligible == 1
    assert collector.telemetry_candidates_emitted == 1
    assert collector.telemetry_declared_contract_exclusions == 0
    assert collector.telemetry_implementation_only_exclusions == 0
    assert len(collector.candidates_log) == 1


# ---------------------------------------------------------------------------
# 6 & 7. terminal categories are mutually exclusive; identity balances exactly
#         on a mixed synthetic sequence (non-RTH, missing-regime, qual-fail,
#         candidate -- one of each terminal bucket)
# ---------------------------------------------------------------------------

def test_mixed_sequence_terminal_buckets_mutually_exclusive_and_balance_exactly():
    collector = _init_collector()

    # A: non-RTH exclusion.
    collector._on_1s(_bar(T_NON_RTH))

    # B: missing-established-regime exclusion.
    collector._on_1s(_bar(T_RTH))

    # C: qualification-fail exclusion (regime now established, but too young).
    t_c = T_RTH + 5 * NS
    collector._current_regime_start_atr = 1.0
    collector._current_regime_start_ns = t_c - 50 * NS
    collector._on_1s(_bar(t_c))

    # D: eligible candidate.
    t_d = T_RTH + 10 * NS
    collector._regime.regime = 1
    collector._current_regime_start_ns = t_d - 200 * NS
    collector._current_regime_anchor = 100.0
    collector._running_mfe_atr = 1.0
    collector._progress_windows = 2
    collector._on_1s(_bar(t_d, close=101.0, high=101.0, low=99.0, open_=100.0))

    assert collector.telemetry_total_checkpoints == 4
    assert collector.telemetry_declared_contract_exclusions == 3
    assert collector.telemetry_implementation_only_exclusions == 0
    assert collector.telemetry_candidates_emitted == 1

    # E4/E6: exact, exhaustive, mutually exclusive identity.
    assert (
        collector.telemetry_total_checkpoints
        == collector.telemetry_declared_contract_exclusions
        + collector.telemetry_implementation_only_exclusions
        + collector.telemetry_candidates_emitted
    )


# ---------------------------------------------------------------------------
# 11. implementation_only_exclusions is structurally unreachable in _on_1s
# ---------------------------------------------------------------------------

def test_implementation_only_exclusion_branch_is_structurally_unreachable():
    """No branch in _on_1s increments implementation_only_exclusions. Every early
    `return` after the checkpoint-count increment is guarded by a
    declared_contract_exclusions increment; the only other exit is either a hard
    RuntimeError/RuntimeError-style raise (feature readiness) or falling through to
    candidate emission. If a future change adds an implementation-only suppression
    branch, it must increment the counter -- this test will then fail and must be
    updated alongside that change, not silently pass.
    """
    src = inspect.getsource(CleanFlipCollector._on_1s)
    assert "telemetry_implementation_only_exclusions" not in src

    lines = src.splitlines()
    # Scope the scan to AFTER the total_population_checkpoints increment: the
    # not-5s-aligned / no-eligible-close early return above it is outside the D8
    # population denominator entirely (it never counts as a checkpoint at all), so
    # it is correctly unguarded and must not be treated as an uncounted exclusion.
    counter_line = next(
        i for i, line in enumerate(lines) if "telemetry_total_checkpoints += 1" in line
    )
    population_lines = lines[counter_line:]
    bare_return_lines = [
        i for i, line in enumerate(population_lines) if re.fullmatch(r"\s*return\s*", line)
    ]
    assert len(bare_return_lines) == 3, (
        "expected exactly 3 early-return branches after the checkpoint-count increment "
        "in _on_1s (non-RTH, missing established regime, qualification-fail); found "
        f"{len(bare_return_lines)}"
    )
    for idx in bare_return_lines:
        window = "\n".join(population_lines[max(0, idx - 4):idx])
        assert "telemetry_declared_contract_exclusions += 1" in window, (
            f"return at line {idx} (post-counter) in _on_1s is not preceded by a "
            "declared_contract_exclusions increment"
        )


# =============================================================================
# Part 2 -- reconcile_population_funnel (output_manager)
# =============================================================================

def test_reconcile_population_funnel_none_when_no_telemetry():
    assert reconcile_population_funnel(
        total_population_checkpoints=None,
        declared_contract_exclusions_in_run=0,
        implementation_only_exclusions=0,
        candidates_emitted_raw=0,
        candidates_raw_count=0,
        candidates_persisted_count=0,
    ) is None


def test_reconcile_population_funnel_balances_on_matched_window():
    """7. Funnel identity balances exactly when nothing was trimmed by the
    collection-window filter."""
    report = reconcile_population_funnel(
        total_population_checkpoints=10,
        declared_contract_exclusions_in_run=6,
        implementation_only_exclusions=0,
        candidates_emitted_raw=4,
        candidates_raw_count=4,
        candidates_persisted_count=4,
    )
    assert report["reconciliation_passed"] is True
    assert report["declared_contract_exclusions"] == 6
    assert report["candidates_outside_collection_window"] == 0
    assert report["candidates_emitted"] == 4


def test_reconcile_population_funnel_folds_out_of_window_candidates_into_declared():
    """9. candidates_emitted must reconcile to the persisted row count -- a candidate
    trimmed by the warmup-window filter is folded into declared_contract_exclusions,
    not silently dropped from the identity."""
    report = reconcile_population_funnel(
        total_population_checkpoints=10,
        declared_contract_exclusions_in_run=6,
        implementation_only_exclusions=0,
        candidates_emitted_raw=4,
        candidates_raw_count=4,
        candidates_persisted_count=3,  # one candidate fell outside [start, end]
    )
    assert report["reconciliation_passed"] is True
    assert report["candidates_outside_collection_window"] == 1
    assert report["declared_contract_exclusions"] == 7
    assert report["candidates_emitted"] == 3


def test_reconcile_population_funnel_zero_candidate_run_reconciles():
    """10. A zero-candidate run reconciles correctly."""
    report = reconcile_population_funnel(
        total_population_checkpoints=5,
        declared_contract_exclusions_in_run=5,
        implementation_only_exclusions=0,
        candidates_emitted_raw=0,
        candidates_raw_count=0,
        candidates_persisted_count=0,
    )
    assert report["reconciliation_passed"] is True
    assert report["candidates_emitted"] == 0


def test_reconcile_population_funnel_missing_bucket_hard_fails():
    """8. Deliberately missing a bucket (declared exclusions undercounted by 1)
    causes reconciliation failure -- a hard raise, not a warning."""
    with pytest.raises(ValueError, match="POPULATION_FUNNEL_RECONCILIATION_FAILED"):
        reconcile_population_funnel(
            total_population_checkpoints=10,
            declared_contract_exclusions_in_run=5,  # should be 6
            implementation_only_exclusions=0,
            candidates_emitted_raw=4,
            candidates_raw_count=4,
            candidates_persisted_count=4,
        )


def test_reconcile_population_funnel_raw_count_mismatch_hard_fails():
    with pytest.raises(ValueError, match="POPULATION_FUNNEL_INCONSISTENT"):
        reconcile_population_funnel(
            total_population_checkpoints=10,
            declared_contract_exclusions_in_run=6,
            implementation_only_exclusions=0,
            candidates_emitted_raw=4,
            candidates_raw_count=3,  # inconsistent with candidates_emitted_raw
            candidates_persisted_count=3,
        )


# =============================================================================
# Part 3 -- OutputManager.persist_collection: funnel persists into artifacts
# =============================================================================

FULL_KEY_METADATA = ["observation_ts", "regime_start_ns", "checkpoint_index"]


def _spec():
    study_dict = {
        "study": {
            "id": "e_population_funnel_test", "type": "flip_prediction", "risk_tier": 2,
            "description": "Packet E population-funnel harness study.",
        },
        "operation": {"kind": "train_evaluate", "target_metric": "pr_auc"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {
            "type": "regime_state", "prevailing_regime": "bullish", "session": "RTH",
            "qualification": {"age_gate_seconds": 300, "established": True},
        },
        "target": {"type": "flip", "event": "confirmed_flip", "direction": "bearish", "horizon_seconds": 300},
        "features": {"feature_list": None, "feature_list_sha256": None, "metadata_columns": FULL_KEY_METADATA},
        "chronology": {"train": [2021, 2022, 2023, 2024], "dev": [2025], "prohibited": [2026]},
        "execution": {
            "runtime": "nautilustrader",
            "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
            "progress_seconds": 60, "bounded": True,
        },
    }
    return StudySpec.model_validate(study_dict)


def _output_manager(tmp_path: Path) -> OutputManager:
    spec = _spec()
    study_data = CompiledStudyData(
        study_id=spec.study.id, study_dir=tmp_path, study_type=spec.study.type,
        spec=spec, spec_sha256=spec.compute_sha256(), contracts={}, raw_compiled_json={},
    )
    # Wide-open window so small integer observation_ts test values are simple to
    # reason about (well inside [start_ns, end_ns] unless deliberately negative).
    start_dt = pd.Timestamp(0, tz="UTC")
    end_dt = pd.Timestamp("2100-01-01", tz="UTC")
    data_plan = DataPlan(
        symbol="NQ", venue="XCME", instrument_id="NQ.XCME", multiplier="20.0", price_increment="0.25",
        catalog_path=tmp_path / "fake_catalog", bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL", start_dt=start_dt, end_dt=end_dt,
        warmup_days=5, warmup_start_dt=start_dt - pd.Timedelta(days=5),
        raw_timestamp_semantic="OPEN_STAMPED", ts_init_delta_1s_ns=1_000_000_000, ts_init_delta_1m_ns=60_000_000_000,
    )
    run_plan = RunPlan(stage=RunStage.DAY, start_date="2023-10-02", end_date="2023-10-02")
    return OutputManager(study_data, data_plan, run_plan, output_base_dir=tmp_path / "runs")


def _telemetry(population_funnel: dict | None = None):
    t = CausalTelemetry()
    t.start()
    if population_funnel is not None:
        t.record_population_funnel(**population_funnel)
    return t.stop()


def _candidates_df(n: int) -> pd.DataFrame:
    return pd.DataFrame([
        {"observation_ts": i + 1, "regime_start_ns": 0, "checkpoint_index": i}
        for i in range(n)
    ])


def _observations_df(n: int) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "observation_ts": i + 1, "regime_start_ns": 0, "checkpoint_index": i,
            "disposition": "LABELED_POSITIVE",
        }
        for i in range(n)
    ])


# ---------------------------------------------------------------------------
# 12. funnel fields persist into governed output/result artifacts
# ---------------------------------------------------------------------------

def test_population_funnel_persists_into_status_and_manifests(tmp_path: Path):
    mgr = _output_manager(tmp_path)
    cands_df = _candidates_df(2)
    obs_df = _observations_df(2)
    telemetry = _telemetry({
        "total_checkpoints": 5,
        "declared_contract_exclusions": 3,
        "implementation_only_exclusions": 0,
        "candidates_emitted_raw": 2,
    })

    status = mgr.persist_collection(cands_df, obs_df, telemetry)

    assert status["status"] == "SUCCESS"
    assert status["population_funnel"]["reconciliation_passed"] is True
    assert status["population_funnel"]["candidates_emitted"] == 2 == len(cands_df)

    with open(mgr.collection_dir / "collection_manifest.json", "r", encoding="utf-8") as f:
        collection_manifest = json.load(f)
    assert collection_manifest["population_funnel"]["total_population_checkpoints"] == 5

    with open(mgr.manifest_path, "r", encoding="utf-8") as f:
        run_manifest = json.load(f)
    assert run_manifest["population_funnel_reconciliation_passed"] is True


def test_population_funnel_omitted_when_strategy_has_no_telemetry(tmp_path: Path):
    """13/14/15: a strategy without funnel instrumentation is unaffected -- the D1/D2
    surface stays exactly as before, and population_funnel is simply absent (None)."""
    mgr = _output_manager(tmp_path)
    cands_df = _candidates_df(2)
    obs_df = _observations_df(2)

    status = mgr.persist_collection(cands_df, obs_df, _telemetry())

    assert status["status"] == "SUCCESS"
    assert status["population_funnel"] is None

    with open(mgr.manifest_path, "r", encoding="utf-8") as f:
        run_manifest = json.load(f)
    assert run_manifest["population_funnel_reconciliation_passed"] is None


def test_population_funnel_zero_candidate_run_persists_and_reconciles(tmp_path: Path):
    """10 (integration variant): a genuinely empty collection with funnel telemetry
    still reconciles and persists."""
    mgr = _output_manager(tmp_path)
    cands_df = pd.DataFrame(columns=FULL_KEY_METADATA)
    obs_df = pd.DataFrame(columns=CANDIDATE_KEY_COLUMNS)
    telemetry = _telemetry({
        "total_checkpoints": 3,
        "declared_contract_exclusions": 3,
        "implementation_only_exclusions": 0,
        "candidates_emitted_raw": 0,
    })

    status = mgr.persist_collection(cands_df, obs_df, telemetry)

    assert status["status"] == "SUCCESS"
    assert status["population_funnel"]["reconciliation_passed"] is True
    assert status["population_funnel"]["candidates_emitted"] == 0


def test_population_funnel_mismatch_hard_fails_persist_collection(tmp_path: Path):
    """E4: a genuinely imbalanced funnel must hard-fail persist_collection, not
    silently persist a warning."""
    mgr = _output_manager(tmp_path)
    cands_df = _candidates_df(2)
    obs_df = _observations_df(2)
    telemetry = _telemetry({
        "total_checkpoints": 99,  # deliberately wrong
        "declared_contract_exclusions": 3,
        "implementation_only_exclusions": 0,
        "candidates_emitted_raw": 2,
    })

    with pytest.raises(ValueError, match="POPULATION_FUNNEL_RECONCILIATION_FAILED"):
        mgr.persist_collection(cands_df, obs_df, telemetry)


def test_population_funnel_out_of_window_candidate_still_reconciles(tmp_path: Path):
    """9 (integration variant): a candidate emitted during warmup (observation_ts
    before start_ns) is trimmed by persist_collection's existing date filter; the
    funnel must still reconcile against the persisted (trimmed) row count."""
    mgr = _output_manager(tmp_path)
    cands_df = pd.DataFrame([
        {"observation_ts": -1, "regime_start_ns": 0, "checkpoint_index": 0},  # before start_ns=0
        {"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 1},
    ])
    obs_df = pd.DataFrame([
        {"observation_ts": -1, "regime_start_ns": 0, "checkpoint_index": 0, "disposition": "LABELED_POSITIVE"},
        {"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 1, "disposition": "LABELED_POSITIVE"},
    ])
    telemetry = _telemetry({
        "total_checkpoints": 5,
        "declared_contract_exclusions": 3,
        "implementation_only_exclusions": 0,
        "candidates_emitted_raw": 2,  # raw, pre-window-filter count
    })

    status = mgr.persist_collection(cands_df, obs_df, telemetry)

    assert status["status"] == "SUCCESS"
    assert status["candidates_count"] == 1  # only observation_ts=1 survives the window
    assert status["population_funnel"]["candidates_emitted"] == 1
    assert status["population_funnel"]["candidates_outside_collection_window"] == 1
    assert status["population_funnel"]["declared_contract_exclusions"] == 4  # 3 + 1
    assert status["population_funnel"]["reconciliation_passed"] is True
