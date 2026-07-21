"""Fixture tests: Policy A sim parity, streaming busy rule, window purge."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))

import fable5_common as C  # noqa: E402
from build_dataset import assign_windows  # noqa: E402
from replay_selection import streaming_execution  # noqa: E402

sys.path.insert(0, str(C.MULTI))
from run_study import simulate_trade as upstream_simulate_trade  # noqa: E402

NS = C.NS


def make_raw(start_ns: int, opens, highs, lows) -> pd.DataFrame:
    n = len(opens)
    index = pd.to_datetime(start_ns + NS * np.arange(n), utc=True)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": opens, "volume": np.ones(n)}, index=index)


def both(raw, entry_ts, entry_px, direction, atr, align_ts, scheduled):
    ts, opens, highs, lows = C.raw_arrays(raw)
    mine = C.simulate_trade_arrays(ts, opens, highs, lows, entry_ts, entry_px,
                                   direction, atr, align_ts, scheduled)
    c = pd.Series({"actual_entry_fill_ts": entry_ts,
                   "actual_entry_fill_price": entry_px,
                   "entry_direction": direction,
                   "atr_at_checkpoint": atr, "confirm_flip_ns": align_ts})
    theirs = upstream_simulate_trade(c, raw, scheduled)
    return mine, theirs


CASES = []
START = 1_735_689_600_000_000_000  # arbitrary aligned origin

# Case 1: long fade hits the 1.25 ATR pre-flip stop intra-bar.
n = 700
opens = np.full(n, 100.0)
highs = opens + 0.5
lows = opens - 0.5
lows[5] = 80.0  # breach pre-stop (100 - 1.25*10 = 87.5)
CASES.append(("preflip_stop_touch", opens, highs, lows, 1, 10.0,
              START + 400 * NS, START + 600 * NS))

# Case 2: gap open beyond the stop fills at the open, not the trigger.
opens2 = np.full(n, 100.0)
highs2, lows2 = opens2 + 0.5, opens2 - 0.5
opens2[6], highs2[6], lows2[6] = 80.0, 80.5, 79.5
CASES.append(("preflip_stop_gap_open", opens2, highs2, lows2, 1, 10.0,
              START + 400 * NS, START + 600 * NS))

# Case 3: no alignment, exits on confirmation timeout at the next open.
opens3 = np.full(n, 100.0)
CASES.append(("confirmation_timeout", opens3, opens3 + 0.2, opens3 - 0.2,
              1, 50.0, START + 650 * NS, START + 680 * NS))

# Case 4: aligns inside timeout, later hits the 1.5 ATR post-flip stop.
opens4 = np.full(n, 100.0)
highs4, lows4 = opens4 + 0.2, opens4 - 0.2
lows4[200] = 84.0  # post-stop 85.0 (pre-stop 87.5 never touched before align)
CASES.append(("postflip_stop", opens4, highs4, lows4, 1, 10.0,
              START + 100 * NS, START + 600 * NS))

# Case 5: aligned and survives to the opposing-flip next-open exit.
opens5 = np.linspace(100.0, 110.0, n)
CASES.append(("opposing_flip_exit", opens5, opens5 + 0.2, opens5 - 0.2,
              1, 50.0, START + 100 * NS, START + 500 * NS))

# Case 6: short fade mirror with pre-flip stop on the high side.
opens6 = np.full(n, 100.0)
highs6, lows6 = opens6 + 0.5, opens6 - 0.5
highs6[7] = 120.0
CASES.append(("short_preflip_stop", opens6, highs6, lows6, -1, 10.0,
              START + 400 * NS, START + 600 * NS))

# Case 7: alignment lands exactly at the timeout boundary (counts as aligned).
opens7 = np.full(n, 100.0)
CASES.append(("align_at_timeout", opens7, opens7 + 0.2, opens7 - 0.2,
              1, 50.0, START + 300 * NS, START + 640 * NS))


@pytest.mark.parametrize("name,opens,highs,lows,direction,atr,align,sched",
                         CASES, ids=[c[0] for c in CASES])
def test_sim_parity(name, opens, highs, lows, direction, atr, align, sched):
    raw = make_raw(START, np.asarray(opens, float), np.asarray(highs, float),
                   np.asarray(lows, float))
    mine, theirs = both(raw, START, float(opens[0]), direction, atr, align,
                        sched)
    for key in ("entry_fill_ts", "entry_fill_px", "reached_aligning_flip",
                "exit_fill_ts", "exit_fill_px", "exit_reason", "gross_pnl_pts",
                "net_pnl_usd"):
        assert mine[key] == theirs[key], (name, key, mine[key], theirs[key])


def test_streaming_busy_rule():
    d = pd.DataFrame({
        "candidate_fill_time": [START, START + 10 * NS, START + 11 * NS,
                                START + 30 * NS],
        "candidate_seq": [1, 1, 2, 1],
        "exit_fill_ts": [START + 10 * NS, np.nan, START + 20 * NS,
                         START + 40 * NS],
        "exit_reason": ["preflip_policy_stop", "", "original_opposing_flip_exit",
                        "confirmation_timeout_exit"],
    })
    # Trade 0 exits by stop at +10s -> busy until +11s. The +10s candidate is
    # skipped (position open through exit+1s); the +11s candidate executes.
    executed, skipped = streaming_execution(d)
    assert executed.tolist() == [True, False, True, True]
    assert skipped.tolist() == [False, True, False, False]

    # Non-stop exit frees the slot at the exit timestamp itself.
    d2 = pd.DataFrame({
        "candidate_fill_time": [START, START + 20 * NS],
        "candidate_seq": [1, 1],
        "exit_fill_ts": [START + 20 * NS, START + 40 * NS],
        "exit_reason": ["original_opposing_flip_exit", "preflip_policy_stop"],
    })
    executed2, _ = streaming_execution(d2)
    assert executed2.tolist() == [True, True]


def test_window_purge():
    b = C.BOUNDARY_NS
    d = pd.DataFrame({
        "candidate_time": [b - 100 * NS, b - 100 * NS, b + 100 * NS],
        "exit_fill_ts": [b - 50 * NS, b + 5 * NS, b + 200 * NS],
        "opportunity_end_ts": [b - 10 * NS, b - 10 * NS, b + 300 * NS],
    })
    out = assign_windows(2025, d.copy())
    assert out.window.tolist() == ["2025_H1_train", "2025_H1_train",
                                   "2025_H2_dev"]
    assert out.purged_from_train.tolist() == [False, True, False]
