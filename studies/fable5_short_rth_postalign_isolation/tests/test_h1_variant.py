"""Fixtures: H1 removes ONLY the post-alignment stop; H0==H1 off that path."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(STUDY.parent / "fable5_specialized_w4"))
from run_isolation import simulate  # noqa: E402
import fable5_common as F  # noqa: E402

NS = 1_000_000_000
T0 = 1_735_689_600_000_000_000
ATR = 10.0
DIR = -1          # short
ENTRY = 100.0
N = 460


def arrays(mut=None):
    ts = T0 + NS * np.arange(N, dtype=np.int64)
    opens = np.full(N, ENTRY)
    highs = np.full(N, ENTRY + 0.2)
    lows = np.full(N, ENTRY - 0.2)
    if mut:
        mut(opens, highs, lows)
    return ts, opens, highs, lows


def test_aligned_h0_stops_h1_holds():
    # aligns at +60s (<=300s timeout); post stop = 115 breached at +120s;
    # opposing flip scheduled at +400s.
    def mut(o, h, l):
        h[120] = 116.0     # breaches 1.50 post stop (115)
    ts, o, h, l = arrays(mut)
    align_ts, sched = T0 + 60 * NS, T0 + 400 * NS
    h0 = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, True)
    h1 = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, False)
    assert h0["exit_reason"] == "original_stop_after_aligned_flip"
    assert h0["exit_px"] == 115.0 and h0["exit_ts"] == T0 + 120 * NS
    assert h0["net_pnl"] == (115.0 - 100.0) * DIR * 20 - 10   # -310
    # H1 ignores the post stop and holds to the opposing flip at +400s
    assert h1["exit_reason"] == "original_opposing_flip_exit"
    assert h1["exit_ts"] == T0 + 400 * NS
    assert h1["net_pnl"] == (o[400] - 100.0) * DIR * 20 - 10  # ~ -10 (flat)
    assert h1["net_pnl"] > h0["net_pnl"]


def test_never_aligns_identical():
    # align_ts after timeout -> never aligns -> timeout at +300s; H0==H1
    ts, o, h, l = arrays()
    align_ts, sched = T0 + 400 * NS, T0 + 450 * NS
    h0 = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, True)
    h1 = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, False)
    assert h0["exit_reason"] == "confirmation_timeout_exit"
    assert h0 == h1


def test_pre_stop_before_align_identical():
    # pre stop 112.5 breached at +30s, before the +60s alignment; H0==H1
    def mut(o, h, l):
        h[30] = 113.0
    ts, o, h, l = arrays(mut)
    align_ts, sched = T0 + 60 * NS, T0 + 400 * NS
    h0 = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, True)
    h1 = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, False)
    assert h0["exit_reason"] == "preflip_policy_stop"
    assert h0["exit_px"] == 112.5
    assert h0 == h1


def test_h0_matches_audited_engine():
    # simulate(post_stop_enabled=True) must equal the audited engine on the
    # same tape (post-alignment stop path, the case where the flag matters).
    def mut(o, h, l):
        h[120] = 116.0
    ts, o, h, l = arrays(mut)
    align_ts, sched = T0 + 60 * NS, T0 + 400 * NS
    mine = simulate(ts, o, h, l, T0, ENTRY, DIR, ATR, align_ts, sched, True)
    ref = F.simulate_trade_arrays(ts, o, h, l, T0, ENTRY, DIR, ATR,
                                  align_ts, sched)
    for k in ("exit_reason", "exit_fill_ts", "reached_aligning_flip"):
        rk = {"exit_reason": "exit_reason", "exit_fill_ts": "exit_ts",
              "reached_aligning_flip": "aligned"}[k]
        assert ref[k] == mine[rk], (k, ref[k], mine[rk])
    assert ref["net_pnl_usd"] == mine["net_pnl"]
    assert ref["exit_fill_px"] == mine["exit_px"]
