import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
policy = importlib.import_module("CODEX_5_X_run_established_fade")


def test_progress_windows_are_causal_and_monotonic():
    ts = np.arange(6, dtype=np.int64) * 60 * policy.NS
    mfe = np.array([0.1, 0.2, 0.2, 0.3, 0.31, 0.4])
    got = policy.progress_window_counts(mfe, ts)
    assert np.all(np.diff(got) >= 0)
    assert got.tolist() == [1, 1, 1, 2, 2, 2]


def test_direction_symmetric_stop_geometry():
    entry = 20000.0
    atr = 10.0
    long_stop = entry - 1 * 1.5 * atr
    short_stop = entry - (-1) * 1.5 * atr
    assert long_stop == 19985.0
    assert short_stop == 20015.0
    assert abs(entry - long_stop) / atr == 1.5
    assert abs(entry - short_stop) / atr == 1.5


def test_audit_gate_rejects_fail_report_containing_pass_words(tmp_path, monkeypatch):
    bad = tmp_path / "bad.md"
    bad.write_text(
        "**Status:** **FAIL**\n**Findings:** **1 CRITICAL, 0 WARNING**\n"
        "Execution would PASS after repair with 0 CRITICAL and 0 WARNING.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "PRE_POLICY_AUDIT", bad)
    monkeypatch.setattr(policy, "PRE_EXEC_AUDIT", bad)
    with pytest.raises(RuntimeError, match="exact clean PASS"):
        policy.require_passed_audits()


def test_dependency_seal_detects_any_changed_input():
    current = {"runner_sha256": "a", "raw_2025_sha256": "b"}
    policy.validate_2025_dependency_seal({"dependency_hashes_2025": current.copy()}, current)
    changed = current.copy()
    changed["runner_sha256"] = "changed"
    with pytest.raises(RuntimeError, match="hash mismatch"):
        policy.validate_2025_dependency_seal({"dependency_hashes_2025": current}, changed)


def test_frozen_2026_atlas_or_score_mutation_is_rejected():
    expected = {"2026": {"raw": "r", "atlas": "a", "scores": "s"},
                "common": {"manifest": "m", "bundle": "b", "first_open": "f"}}
    policy.validate_hash_map(expected, expected.copy())
    for field in ("atlas", "scores"):
        changed = {"2026": expected["2026"].copy(), "common": expected["common"].copy()}
        changed["2026"][field] = "changed"
        with pytest.raises(RuntimeError, match="input hash mismatch"):
            policy.validate_hash_map(expected, changed)


def test_strict_crossing_resets_at_each_regime():
    threshold = 0.7
    first_regime = [0.6, 0.7, 0.8]
    second_regime = [0.8, 0.6, 0.7]
    def crossings(values):
        previous = None
        out = []
        for value in values:
            out.append(policy.strict_threshold_cross(previous, value, threshold))
            previous = value
        return out
    assert crossings(first_regime) == [False, True, False]
    assert crossings(second_regime) == [False, False, True]


def _raw(rows):
    idx = pd.to_datetime([r[0] for r in rows], unit="s", utc=True)
    return pd.DataFrame(
        {"open": [r[1] for r in rows], "high": [r[2] for r in rows],
         "low": [r[3] for r in rows], "close": [r[4] for r in rows],
         "volume": 1.0}, index=idx,
    )


def _candidate(decision=0, confirm=10, direction=1):
    return pd.DataFrame([{
        "year": 2025, "regime_start_ns": -10 * policy.NS,
        "confirm_flip_ns": confirm * policy.NS, "prevailing_direction": -direction,
        "entry_direction": direction, "decision_ts": decision * policy.NS,
        "score_observation_ts": decision * policy.NS, "w4_score": 0.9,
        "direction_threshold": 0.7, "atr_at_entry": 10.0,
        "atr_at_checkpoint": 10.0, "regime_age_s": 120.0,
        "running_mfe_atr": 1.0, "running_mae_atr": 0.2,
        "new_progress_windows": 2, "retained_mfe_ratio": 0.5,
        "decision_session": "ETH",
    }])


def test_entry_bar_stop_is_active_and_fills_at_stop(monkeypatch):
    raw = _raw([(0, 100, 101, 84, 90), (10, 90, 95, 89, 94), (20, 94, 96, 93, 95)])
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS],
                             "regime_end_ns": [20 * policy.NS]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    trades, skipped = policy.simulate(2025, _candidate(), raw, policy.load_policy())
    assert skipped.empty
    assert trades.iloc[0].entry_bar_crosses_stop
    assert trades.iloc[0].exit_fill_ts == 0
    assert trades.iloc[0].exit_fill_px == 85.0
    assert trades.iloc[0].exit_reason == "stop_before_aligned_flip"


def test_gap_through_stop_fills_at_later_bar_open(monkeypatch):
    raw = _raw([(0, 100, 101, 90, 95), (1, 80, 82, 79, 81),
                (10, 90, 95, 89, 94), (20, 94, 96, 93, 95)])
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS],
                             "regime_end_ns": [20 * policy.NS]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    trades, _ = policy.simulate(2025, _candidate(), raw, policy.load_policy())
    assert trades.iloc[0].exit_fill_ts == policy.NS
    assert trades.iloc[0].exit_fill_px == 80.0


def test_scheduled_exit_open_precedes_exit_bar_stop_range(monkeypatch):
    raw = _raw([(0, 100, 101, 90, 95), (10, 95, 100, 90, 98),
                (20, 110, 111, 80, 90)])
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS],
                             "regime_end_ns": [20 * policy.NS]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    trades, _ = policy.simulate(2025, _candidate(), raw, policy.load_policy())
    assert trades.iloc[0].exit_reason == "opposite_flip_against_countertrade"
    assert trades.iloc[0].exit_fill_ts == 20 * policy.NS
    assert trades.iloc[0].exit_fill_px == 110.0


def test_checkpointless_confirming_regime_still_exits_at_known_next_flip(monkeypatch):
    raw = _raw([(0, 100, 101, 90, 95), (10, 95, 100, 90, 98),
                (20, 110, 111, 100, 109)])
    # The confirming start=10 need not have checkpoints; the complete timeline
    # still supplies its known end=20.
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS, 20 * policy.NS],
                             "regime_end_ns": [20 * policy.NS, None]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    trades, _ = policy.simulate(2025, _candidate(), raw, policy.load_policy())
    assert trades.iloc[0].exit_reason == "opposite_flip_against_countertrade"
    assert trades.iloc[0].exit_fill_ts == 20 * policy.NS


def test_short_gap_stop_path(monkeypatch):
    raw = _raw([(0, 100, 110, 99, 105), (1, 120, 121, 119, 120),
                (10, 110, 112, 100, 105), (20, 105, 106, 95, 100)])
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS],
                             "regime_end_ns": [20 * policy.NS]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    trades, _ = policy.simulate(2025, _candidate(direction=-1), raw, policy.load_policy())
    assert trades.iloc[0].stop_px == 115.0
    assert trades.iloc[0].exit_fill_ts == policy.NS
    assert trades.iloc[0].exit_fill_px == 120.0


def test_missing_confirming_regime_is_not_silently_censored(monkeypatch):
    raw = _raw([(0, 100, 101, 90, 95), (10, 95, 100, 90, 98)])
    timeline = pd.DataFrame({"regime_start_ns": [99 * policy.NS], "regime_end_ns": [None]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    with pytest.raises(RuntimeError, match="absent"):
        policy.simulate(2025, _candidate(), raw, policy.load_policy())


def test_overlap_candidate_is_skipped_until_first_trade_exit(monkeypatch):
    raw = _raw([(0, 100, 101, 90, 95), (5, 101, 102, 90, 96),
                (10, 95, 100, 90, 98), (20, 110, 111, 100, 109)])
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS],
                             "regime_end_ns": [20 * policy.NS]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    candidates = pd.concat([_candidate(decision=0), _candidate(decision=5)], ignore_index=True)
    candidates.loc[1, "regime_start_ns"] = -5 * policy.NS
    trades, skipped = policy.simulate(2025, candidates, raw, policy.load_policy())
    assert len(trades) == 1
    assert len(skipped) == 1
    assert skipped.iloc[0].reason == "decision_while_position_open"


def test_stop_bar_same_open_candidate_is_skipped(monkeypatch):
    raw = _raw([(0, 100, 101, 90, 95), (5, 100, 101, 84, 90),
                (10, 95, 100, 90, 98), (20, 110, 111, 100, 109)])
    timeline = pd.DataFrame({"regime_start_ns": [10 * policy.NS],
                             "regime_end_ns": [20 * policy.NS]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    first = _candidate(decision=0)
    second = _candidate(decision=5)
    second.loc[0, "regime_start_ns"] = -5 * policy.NS
    trades, skipped = policy.simulate(
        2025, pd.concat([first, second], ignore_index=True), raw, policy.load_policy())
    assert trades.iloc[0].exit_fill_ts == 5 * policy.NS
    assert skipped.iloc[0].reason == "decision_while_position_open"


def test_delayed_next_open_controls_fill_session(monkeypatch):
    decision = pd.Timestamp("2025-07-01 13:29:59.500", tz="UTC").value
    fill = pd.Timestamp("2025-07-01 13:30:00", tz="UTC").value  # 08:30 CT
    confirm = fill + 10 * policy.NS
    exit_ts = fill + 20 * policy.NS
    idx = pd.to_datetime([fill, confirm, exit_ts], unit="ns", utc=True)
    raw = pd.DataFrame({"open": [100, 101, 102], "high": [101, 102, 103],
                        "low": [99, 100, 101], "close": [100, 101, 102],
                        "volume": 1.0}, index=idx)
    timeline = pd.DataFrame({"regime_start_ns": [confirm], "regime_end_ns": [exit_ts]})
    monkeypatch.setattr(policy, "canonical_regime_timeline", lambda year, raw: timeline)
    c = _candidate()
    c.loc[0, "decision_ts"] = decision
    c.loc[0, "score_observation_ts"] = decision
    c.loc[0, "confirm_flip_ns"] = confirm
    c.loc[0, "decision_session"] = "ETH"
    trades, _ = policy.simulate(2025, c, raw, policy.load_policy())
    assert trades.iloc[0].entry_fill_ts == fill
    assert trades.iloc[0].entry_fill_delay_s == 0.5
    assert trades.iloc[0].decision_session == "ETH"
    assert trades.iloc[0].session == "RTH"


def test_timeline_from_flips_keeps_all_intermediate_regimes():
    starts = np.array([10, 20, 30], dtype=np.int64) * policy.NS
    got = policy.timeline_from_flips(starts, np.array([1, -1, 1], dtype=np.int8))
    assert got.regime_end_ns.tolist() == [20 * policy.NS, 30 * policy.NS, None]
    assert got.end_censored.tolist() == [False, False, True]


def test_malformed_raw_and_regime_inputs_fail_closed():
    duplicate = _raw([(0, 100, 101, 99, 100), (0, 100, 101, 99, 100)])
    with pytest.raises(RuntimeError, match="ordered and unique"):
        policy.validate_raw_bars(duplicate)
    bad_ohlc = _raw([(0, 100, 99, 101, 100)])
    with pytest.raises(RuntimeError, match="geometry"):
        policy.validate_raw_bars(bad_ohlc)
    with pytest.raises(RuntimeError, match="strictly increasing"):
        policy.timeline_from_flips(np.array([20, 10]), np.array([1, -1]))
    with pytest.raises(RuntimeError, match="alternate"):
        policy.timeline_from_flips(np.array([10, 20]), np.array([1, 1]))


def test_failed_reconciliation_blocks_before_output_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "RESULTS", tmp_path)
    with pytest.raises(RuntimeError, match="blocking reconciliation"):
        policy.require_clean_reconciliation({"closure_residual": 1, "blocking_errors": 1})
    assert list(tmp_path.iterdir()) == []
