from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER = Path(__file__).resolve().parents[1] / "run_study.py"
SPEC = spec_from_file_location("w4_bracket_race", RUNNER)
mod = module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

NS = 1_000_000_000
BASE = 1_700_000_000_000_000_000


def bars(n=10, price=100.0):
    idx = pd.to_datetime(BASE + np.arange(n, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": price, "high": price + .25, "low": price - .25,
                         "close": price, "volume": 1.0}, index=idx)


def trade(direction=1, atr=4.0, entry_s=1, horizon_s=8):
    return pd.Series({"entry_fill_ts": BASE + entry_s * NS, "entry_fill_open": 100.0,
        "entry_direction": direction, "atr_at_checkpoint": atr,
        "scheduled_exit_decision_ts": BASE + horizon_s * NS})


def test_long_pt_first():
    raw = bars()
    raw.iloc[3, raw.columns.get_loc("high")] = 105.0
    out = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert out["outcome"] == "pt_first"
    assert out["time_to_resolution_s"] == 2


def test_long_sl_first():
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("low")] = 95.0
    out = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert out["outcome"] == "sl_first"


def test_short_pt_and_sl_geometry():
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("low")] = 95.0
    assert mod.first_touch(trade(direction=-1), raw, 1.25, "conservative")["outcome"] == "pt_first"
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("high")] = 105.0
    assert mod.first_touch(trade(direction=-1), raw, 1.25, "conservative")["outcome"] == "sl_first"


def test_conservative_same_bar_tie_is_loss():
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("high")] = 106.0
    raw.iloc[2, raw.columns.get_loc("low")] = 94.0
    out = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert out["same_bar_tie"]
    assert out["outcome"] == "sl_first"


def test_decisive_tie_requires_strictly_larger_favorable_overshoot():
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("high")] = 107.0
    raw.iloc[2, raw.columns.get_loc("low")] = 94.0
    assert mod.first_touch(trade(), raw, 1.25, "decisive")["outcome"] == "pt_first"
    raw.iloc[2, raw.columns.get_loc("high")] = 106.0
    assert mod.first_touch(trade(), raw, 1.25, "decisive")["outcome"] == "sl_first"


def test_entry_bar_is_included():
    raw = bars()
    raw.iloc[1, raw.columns.get_loc("high")] = 105.0
    out = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert out["outcome"] == "pt_first"
    assert out["time_to_resolution_s"] == 0


def test_unresolved_has_no_invented_pnl():
    out = mod.first_touch(trade(), bars(), 1.25, "conservative")
    assert out["outcome"] == "unresolved"
    assert np.isnan(out["net_pnl_usd"])


def test_fixed_symmetric_economics_include_cost():
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("high")] = 105.0
    win = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert win["gross_bracket_value_usd"] == 100.0
    assert win["net_pnl_usd"] == 90.0
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("low")] = 95.0
    loss = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert loss["net_pnl_usd"] == -110.0


def test_cost_adjusted_breakeven_respects_conditional_atr_payouts():
    assert mod.cost_adjusted_breakeven_rate(300.0, 280.0) == 0.5
    assert mod.cost_adjusted_breakeven_rate(250.0, 250.0) == 0.52


def test_pre_resolution_excursion_excludes_resolution_bar():
    raw = bars()
    raw.iloc[2, raw.columns.get_loc("high")] = 102.0
    raw.iloc[3, raw.columns.get_loc("low")] = 95.0
    out = mod.first_touch(trade(), raw, 1.25, "conservative")
    assert out["outcome"] == "sl_first"
    assert out["favorable_excursion_before_resolution_atr"] == .5


def test_tail_marks_runner_and_horizon_giveback():
    raw = bars(12)
    raw.iloc[2, raw.columns.get_loc("high")] = 105.0
    raw.iloc[4, raw.columns.get_loc("high")] = 112.0
    raw.iloc[8, raw.columns.get_loc("open")] = 104.0
    primary = pd.Series(mod.first_touch(trade(horizon_s=8), raw, 1.25, "conservative"))
    out = mod.tail_diagnostic(trade(horizon_s=8), primary, raw)
    assert out["pt_first_then_large_runner"]
    assert out["reached_3a"]
    assert out["eventual_regime_flip_pnl_atr"] == 1.0
    assert out["giveback_mfe_to_regime_exit_atr"] == 2.0


def test_sl_first_recovery_requires_later_bar():
    raw = bars(12)
    raw.iloc[2, raw.columns.get_loc("low")] = 95.0
    raw.iloc[4, raw.columns.get_loc("high")] = 105.0
    primary = pd.Series(mod.first_touch(trade(horizon_s=8), raw, 1.25, "conservative"))
    out = mod.tail_diagnostic(trade(horizon_s=8), primary, raw)
    assert out["sl_first_later_recovered_to_pt"]


def test_same_tie_bar_does_not_count_as_later_recovery():
    raw = bars(12)
    raw.iloc[2, raw.columns.get_loc("high")] = 105.0
    raw.iloc[2, raw.columns.get_loc("low")] = 95.0
    primary = pd.Series(mod.first_touch(trade(horizon_s=8), raw, 1.25, "conservative"))
    out = mod.tail_diagnostic(trade(horizon_s=8), primary, raw)
    assert primary.outcome == "sl_first"
    assert not out["sl_first_later_recovered_to_pt"]


def test_tail_labels_unavailable_when_race_resolves_after_horizon():
    raw = bars(12)
    raw.iloc[9, raw.columns.get_loc("high")] = 105.0
    primary = pd.Series(mod.first_touch(trade(horizon_s=8), raw, 1.25, "conservative"))
    out = mod.tail_diagnostic(trade(horizon_s=8), primary, raw)
    assert not out["primary_resolution_before_horizon"]
    assert pd.isna(out["pt_first_then_large_runner"])
    assert pd.isna(out["pt_first_then_immediate_reversal"])


def test_post_pt_entry_and_2a_same_bar_is_ambiguous():
    raw = bars(12)
    raw.iloc[2, raw.columns.get_loc("high")] = 105.0
    raw.iloc[3, raw.columns.get_loc("open")] = 100.5
    raw.iloc[3, raw.columns.get_loc("high")] = 100.75
    raw.iloc[3, raw.columns.get_loc("low")] = 100.25
    raw.iloc[3, raw.columns.get_loc("close")] = 100.5
    raw.iloc[4, raw.columns.get_loc("high")] = 108.0
    raw.iloc[4, raw.columns.get_loc("low")] = 99.0
    primary = pd.Series(mod.first_touch(trade(horizon_s=8), raw, 1.25, "conservative"))
    out = mod.tail_diagnostic(trade(horizon_s=8), primary, raw)
    assert out["pt_post_resolution_entry_2a_same_bar_ambiguous"]
    assert pd.isna(out["pt_first_then_immediate_reversal"])
