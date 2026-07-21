from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "run_isolation.py"
SPEC = importlib.util.spec_from_file_location("isolation", PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

BASE, NS = 1_800_000_000_000_000_000, 1_000_000_000
S = {"policy_id": "S", "preflip_stop_atr": 1.25, "timeout_enabled": False}
T = {"policy_id": "T", "preflip_stop_atr": 1.5, "timeout_enabled": True}
A = {"policy_id": "A", "preflip_stop_atr": 1.25, "timeout_enabled": True}


def bars(count: int = 401) -> pd.DataFrame:
    index = pd.to_datetime(BASE + np.arange(count, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                         "close": 100.0, "volume": 1.0}, index=index)


def trade(confirm_s: int = 350, scheduled_s: int = 400, fill_s: int | None = None,
          fill_px: float = 100.0) -> pd.Series:
    fill_s = scheduled_s if fill_s is None else fill_s
    return pd.Series({"entry_fill_ts": BASE, "entry_fill_open": 100.0, "entry_direction": 1,
        "atr_at_checkpoint": 10.0, "confirm_flip_ns": BASE + confirm_s * NS,
        "scheduled_exit_decision_ts": BASE + scheduled_s * NS,
        "exit_fill_ts": BASE + fill_s * NS, "exit_fill_px": fill_px,
        "exit_reason": "opposite_flip_against_countertrade"})


def test_baseline_replays_original_scheduled_open():
    result = mod.simulate(trade(), bars(), None)
    assert result["new_exit_fill_ts"] == BASE + 400 * NS
    assert result["new_net_pnl_usd"] == -10.0


def test_stop_only_has_no_timeout_and_uses_1p25_preflip_stop():
    raw = bars()
    raw.iloc[320, raw.columns.get_loc("low")] = 87.0
    result = mod.simulate(trade(), raw, S)
    assert result["new_exit_fill_ts"] == BASE + 320 * NS
    assert result["new_exit_fill_px"] == 87.5
    assert result["new_exit_reason"] == "preflip_policy_stop"


def test_timeout_only_retains_1p5_stop_and_fills_next_open():
    raw = bars()
    raw.iloc[250, raw.columns.get_loc("low")] = 87.0  # through 1.25 but not 1.50
    raw.iloc[301, raw.columns.get_loc("open")] = 102.0
    result = mod.simulate(trade(), raw, T)
    assert result["new_exit_fill_ts"] == BASE + 301 * NS
    assert result["new_exit_fill_px"] == 102.0
    assert result["new_exit_reason"] == "confirmation_timeout_exit"


def test_combined_uses_tighter_stop_before_timeout():
    raw = bars()
    raw.iloc[250, raw.columns.get_loc("low")] = 87.0
    result = mod.simulate(trade(), raw, A)
    assert result["new_exit_fill_ts"] == BASE + 250 * NS
    assert result["new_exit_reason"] == "preflip_policy_stop"


def test_flip_exactly_at_timeout_suppresses_timeout_and_reverts_stop():
    raw = bars()
    raw.iloc[300, raw.columns.get_loc("low")] = 86.0
    result = mod.simulate(trade(confirm_s=300), raw, A)
    assert result["new_exit_reason"] == "original_opposing_flip_exit"
    assert result["reached_aligning_flip"]


def test_within_window_flip_during_raw_gap_suppresses_timeout():
    raw = bars().drop(bars().index[295:306])
    result = mod.simulate(trade(confirm_s=298), raw, T)
    assert result["new_exit_reason"] == "original_opposing_flip_exit"
    assert result["reached_aligning_flip"]


def test_late_flip_during_gap_does_not_cancel_prior_timeout_order():
    raw = bars().drop(bars().index[300:306])
    raw.iloc[300, raw.columns.get_loc("open")] = 103.0  # row now corresponds to t=306
    result = mod.simulate(trade(confirm_s=303), raw, T)
    assert result["new_exit_fill_ts"] == BASE + 306 * NS
    assert result["new_exit_fill_px"] == 103.0
    assert not result["reached_aligning_flip"]


def test_late_gap_flip_before_scheduled_fill_is_reached_only_without_timeout():
    raw = bars().drop(bars().index[351:400])
    t = trade(confirm_s=375)
    baseline = mod.simulate(t, raw, None)
    stop_only = mod.simulate(t, raw, S)
    timeout_only = mod.simulate(t, raw, T)
    combined = mod.simulate(t, raw, A)
    assert baseline["reached_aligning_flip"]
    assert stop_only["reached_aligning_flip"]
    assert not timeout_only["reached_aligning_flip"]
    assert not combined["reached_aligning_flip"]


def test_scheduled_decision_gap_uses_first_available_open():
    raw = bars().drop(bars().index[400])
    extra = pd.DataFrame({"open": [103.0], "high": [104.0], "low": [102.0], "close": [103.0],
                          "volume": [1.0]}, index=pd.to_datetime([BASE + 405 * NS], utc=True))
    raw = pd.concat([raw, extra]).sort_index()
    result = mod.simulate(trade(fill_s=405, fill_px=103.0), raw, None)
    assert result["new_exit_fill_ts"] == BASE + 405 * NS


def test_interaction_attribution_is_exact():
    rows = []
    for year, base in ((2025, 0.0), (2026, 0.0)):
        for policy_id, delta in (("POLICY_S_STOP_ONLY_1P25", 10.0),
                                 ("POLICY_T_TIMEOUT_ONLY_300S", 20.0),
                                 ("POLICY_A_COMBINED_1P25_300S", 35.0)):
            rows.append({"year": year, "policy_id": policy_id, "net_pnl_change_usd": delta})
    output = mod.attribution(pd.DataFrame(rows)).set_index("component")
    assert output.loc["interaction effect", "net_change_2025_usd"] == 5.0
    assert output.loc["interaction effect", "net_change_combined_usd"] == 10.0
    assert output.loc["interaction effect", "interpretation"] == "positive synergy"


def test_small_interaction_is_labeled_additive_not_synergy():
    rows = []
    for year in (2025, 2026):
        for policy_id, delta in (("POLICY_S_STOP_ONLY_1P25", 100.0),
                                 ("POLICY_T_TIMEOUT_ONLY_300S", 100.0),
                                 ("POLICY_A_COMBINED_1P25_300S", 202.0)):
            rows.append({"year": year, "policy_id": policy_id, "net_pnl_change_usd": delta})
    output = mod.attribution(pd.DataFrame(rows)).set_index("component")
    assert output.loc["interaction effect", "interpretation"] == "approximately zero; additive"


def test_interaction_label_boundary_is_inclusive_and_just_above_is_synergy():
    def label(combined_per_year: float) -> str:
        rows = []
        for year in (2025, 2026):
            for policy_id, delta in (("POLICY_S_STOP_ONLY_1P25", 100.0),
                                     ("POLICY_T_TIMEOUT_ONLY_300S", 100.0),
                                     ("POLICY_A_COMBINED_1P25_300S", combined_per_year)):
                rows.append({"year": year, "policy_id": policy_id, "net_pnl_change_usd": delta})
        return mod.attribution(pd.DataFrame(rows)).set_index("component").loc[
            "interaction effect", "interpretation"]
    assert label(205.0) == "approximately zero; additive"
    assert label(205.005) == "positive synergy"


def test_trade_sequence_drawdown_is_entry_order_peak_to_trough():
    assert mod.max_trade_sequence_drawdown(pd.Series([10.0, -4.0, -9.0, 8.0])) == 13.0


def test_avoided_loss_definition_excludes_unchanged_breakeven():
    assert not mod.planned_loser_avoided("opposite_flip_exit_loser", 0.0, 0.0)
    assert mod.planned_loser_avoided("opposite_flip_exit_loser", -10.0, 0.0)
