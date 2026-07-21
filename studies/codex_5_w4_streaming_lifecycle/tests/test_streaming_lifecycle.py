from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER = Path(__file__).resolve().parents[1] / "run_study.py"
SPEC = spec_from_file_location("streaming_lifecycle", RUNNER)
mod = module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

NS = 1_000_000_000
BASE = 1_700_000_000_000_000_000


def bars(seconds=30, price=100.0):
    idx = pd.to_datetime(BASE + np.arange(seconds, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": price, "high": price + 1, "low": price - 1,
                         "close": price, "volume": 1.0}, index=idx)


def candidate(**updates):
    values = {"year": 2025, "opportunity_id": "o1", "candidate_id": "o1_c001",
        "candidate_seq": 1, "regime_start_ns": BASE, "confirm_flip_ns": BASE + 20 * NS,
        "prevailing_direction": -1, "entry_direction": 1,
        "candidate_time": BASE + 2 * NS, "candidate_fill_time": BASE + 3 * NS,
        "candidate_fill_price": 100.0, "w4_score": 0.8, "threshold": 0.7,
        "score_margin": 0.1, "atr_at_checkpoint": 4.0, "regime_age_s": 600.0,
        "running_mfe_atr": 2.0, "running_mae_atr": 0.5, "new_progress_windows": 2,
        "retained_mfe_ratio": 0.5, "direction": "long_fade", "session": "ETH",
        "opportunity_end_ts": BASE + 18 * NS, "opportunity_end_reason": "filter_end",
        "candidate_count_in_opportunity": 2}
    values.update(updates)
    return pd.Series(values)


def test_immediate_gate_uses_frozen_next_open():
    g = mod.gate_candidate(candidate(), bars(), 0)
    assert g["accepted"]
    assert g["entry_fill_ts"] == BASE + 3 * NS
    assert g["entry_fill_px"] == 100.0


def test_r10_uses_completed_close_and_strictly_later_open():
    raw = bars(40)
    raw.iloc[12, raw.columns.get_loc("close")] = 101.0
    g = mod.gate_candidate(candidate(), raw, 10)
    assert g["accepted"]
    assert g["confirmation_mark_ts"] == BASE + 12 * NS
    assert g["entry_fill_ts"] == BASE + 14 * NS
    assert g["virtual_directional_pnl_points"] == 1.0


def test_r10_adverse_response_rejects_and_consumes_wait():
    raw = bars(40)
    raw.iloc[12, raw.columns.get_loc("close")] = 99.0
    g = mod.gate_candidate(candidate(), raw, 10)
    assert not g["accepted"]
    assert g["reason"] == "adverse_virtual_response"
    assert g["consume_through_ts"] == BASE + 13 * NS


def test_alignment_at_confirmation_is_rejected():
    c = candidate(confirm_flip_ns=BASE + 13 * NS)
    g = mod.gate_candidate(c, bars(40), 10)
    assert not g["accepted"]
    assert g["reason"] == "regime_ended_before_confirmation"


def test_immediate_horizon_boundary_candidate_remains_valid():
    c = candidate(candidate_time=BASE + 18 * NS, candidate_fill_time=BASE + 19 * NS,
                  opportunity_end_ts=BASE + 18 * NS, confirm_flip_ns=BASE + 25 * NS)
    g = mod.gate_candidate(c, bars(40), 0)
    assert g["accepted"]
    assert g["entry_fill_ts"] == BASE + 19 * NS


def test_stop_is_active_on_entry_bar():
    raw = bars(40)
    raw.iloc[3, raw.columns.get_loc("low")] = 94.0
    c = candidate()
    out = mod.simulate_path(c, BASE + 3 * NS, 100.0, raw, BASE + 30 * NS, None)
    assert out["exit_reason"] == "stop_before_aligned_flip"
    assert out["exit_fill_ts"] == BASE + 3 * NS
    assert out["exit_fill_px"] == 95.0


def test_open_timestamp_w4_exit_precedes_same_bar_stop_range():
    raw = bars(40)
    raw.iloc[22, raw.columns.get_loc("open")] = 101.0
    raw.iloc[22, raw.columns.get_loc("low")] = 90.0
    c = candidate(confirm_flip_ns=BASE + 20 * NS, opportunity_end_ts=BASE + 30 * NS)
    signal = candidate(candidate_id="o2_c001", opportunity_id="o2",
        regime_start_ns=BASE + 20 * NS, confirm_flip_ns=BASE + 30 * NS,
        entry_direction=-1, direction="short_fade", candidate_time=BASE + 21 * NS,
        candidate_fill_time=BASE + 22 * NS)
    out = mod.simulate_path(c, BASE + 3 * NS, 100.0, raw, BASE + 30 * NS, signal)
    assert out["exit_reason"] == "opposite_w4_signal_exit"
    assert out["exit_fill_px"] == 101.0


def test_timeout_exits_at_next_open_not_timeout_bar():
    raw = bars(330)
    c = candidate(confirm_flip_ns=BASE + 320 * NS, opportunity_end_ts=BASE + 325 * NS)
    out = mod.simulate_path(c, BASE + 3 * NS, 100.0, raw, BASE + 325 * NS, None)
    assert out["exit_reason"] == "confirmation_timeout_exit"
    assert out["exit_fill_ts"] == BASE + 304 * NS


def test_opposite_signal_must_belong_to_aligned_regime():
    c1 = candidate(candidate_id="bad", regime_start_ns=BASE, entry_direction=-1,
                   candidate_time=BASE + 21 * NS, candidate_fill_time=BASE + 22 * NS)
    c2 = candidate(candidate_id="good", regime_start_ns=BASE + 20 * NS, entry_direction=-1,
                   candidate_time=BASE + 23 * NS, candidate_fill_time=BASE + 24 * NS)
    found = mod.opposite_w4_candidate(1, BASE + 20 * NS, BASE + 30 * NS,
                                      pd.DataFrame([c1, c2]))
    assert found.candidate_id == "good"


def test_same_direction_signal_is_not_lifecycle_exit():
    c = candidate(candidate_id="same", regime_start_ns=BASE + 20 * NS, entry_direction=1,
                  candidate_time=BASE + 21 * NS, candidate_fill_time=BASE + 22 * NS)
    assert mod.opposite_w4_candidate(1, BASE + 20 * NS, BASE + 30 * NS,
                                     pd.DataFrame([c])) is None


def test_stop_gap_fill_is_conservative():
    assert mod.stop_fill(1, 95.0, 93.0) == 93.0
    assert mod.stop_fill(-1, 105.0, 107.0) == 107.0
    assert mod.stop_fill(1, 95.0, 100.0) == 95.0


def test_attempt_accounting_buckets_later_attempts():
    rows = []
    for policy in ("BASELINE", "S1", "S2", "S3", "S4"):
        rows.extend([
            {"policy_id": policy, "year": 2025, "opportunity_id": "o1", "attempt_number": 1,
             "exit_reason": "stop_before_aligned_flip", "reached_aligning_flip": False,
             "net_pnl_usd": -100.0},
            {"policy_id": policy, "year": 2025, "opportunity_id": "o1", "attempt_number": 2,
             "exit_reason": "original_opposing_flip_exit", "reached_aligning_flip": True,
             "net_pnl_usd": 300.0},
        ])
    out = mod.attempt_accounting(pd.DataFrame(rows))
    s1 = out[(out.policy_id == "S1") & (out.split == "combined")]
    assert int(s1[s1.attempt_bucket == "attempt_2"].attempt_count.iloc[0]) == 1
    attempt_2 = s1[s1.attempt_bucket == "attempt_2"].iloc[0]
    assert int(attempt_2.opportunities_early_stop_recovered_by_this_attempt) == 1
    assert int(attempt_2.opportunities_early_stop_recovered_total) == 1
    assert float(attempt_2.cumulative_pnl_before_final_success_usd) == -100.0
