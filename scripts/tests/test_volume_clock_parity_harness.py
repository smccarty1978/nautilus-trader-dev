"""Verification of the parity harness itself (scripts/parity/volume_clock_developing_parity.py).

The comparison must detect every defect class it vouches for, on small synthetic fixtures, and scale linearly:
altered value, missing key, extra key, duplicate key, timestamp mismatch, volume / progress mismatch, empty and
incomplete sessions, and the independent reference must agree with the tracker on a hand-built session.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from features.trackers.volume_clock_developing import RthSession, VolumeClockKernel

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vcd_parity", ROOT / "scripts/parity/volume_clock_developing_parity.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
NS, MIN = P.NS, P.MIN_NS


def _cps(n_sessions=3, bars=4):
    rows = []
    for d in range(n_sessions):
        for b in range(1, bars + 1):
            for q in (0.25, 0.5, 0.75):
                rows.append({"date": f"2030-01-{d + 1:02d}", "bar_seq": b, "level": q, "ts": 10**18 + d * 10**12 + b * 10**9 + int(q * 100)})
    df = pd.DataFrame(rows)
    df["ts"] = df["ts"].astype("Int64")
    return df


K, V = ["date", "bar_seq", "level"], ["ts"]


def test_identical_frames_pass():
    r = P.compare_keyed(_cps(), _cps(), K, V, "x")
    assert r["pass"] and r["matched"] == 36 and r["first_divergence"] is None


def test_altered_timestamp_is_detected_with_first_divergence():
    t = _cps()
    t.loc[17, "ts"] = t.loc[17, "ts"] + 1                 # 1 ns: int64 compare, no float rounding
    r = P.compare_keyed(_cps(), t, K, V, "x")
    assert not r["pass"] and r["field_mismatches"]["ts"] == 1
    assert r["first_divergence"] == {k: t.loc[17, k] for k in K}


def test_missing_extra_and_duplicate_keys_are_detected():
    ref = _cps()
    r = P.compare_keyed(ref, ref.drop(index=[5]), K, V, "missing")
    assert not r["pass"] and r["only_ref"] == 1 and r["only_trk"] == 0
    extra = pd.concat([ref, pd.DataFrame([{"date": "2030-01-09", "bar_seq": 1, "level": 0.25, "ts": 1}])], ignore_index=True)
    r = P.compare_keyed(ref, extra.astype({"ts": "Int64"}), K, V, "extra")
    assert not r["pass"] and r["only_trk"] == 1
    dup = pd.concat([ref, ref.iloc[[3]]], ignore_index=True)
    r = P.compare_keyed(ref, dup, K, V, "dup")
    assert not r["pass"] and r["dup_trk"] == 2 and r["only_trk"] == 0


def test_volume_and_progress_mismatch_and_null_policy():
    ref = pd.DataFrame({"date": ["d"] * 4, "t": pd.array([1, 2, 3, 4], dtype="Int64"),
                        "consumed": pd.array([1, 2, None, 4], dtype="Int64"), "frac": [0.1, 0.2, np.nan, 0.4]})
    trk = ref.copy()
    assert P.compare_keyed(ref, trk, ["date", "t"], ["consumed", "frac"], "x")["pass"]      # NaN == NaN
    trk.loc[1, "consumed"] = 3
    trk.loc[3, "frac"] = 0.4 + 1e-15                     # no tolerance: a 1e-15 difference is a mismatch
    trk.loc[2, "frac"] = 0.3                              # value where the reference is null
    r = P.compare_keyed(ref, trk, ["date", "t"], ["consumed", "frac"], "x")
    assert r["field_mismatches"] == {"consumed": 1, "frac": 2} and not r["pass"]


def test_empty_frames_compare_but_cannot_vouch():
    e = _cps().iloc[0:0]
    r = P.compare_keyed(e, e, K, V, "empty")
    assert r["pass"] and r["matched"] == 0                 # the caller's non-empty guard turns this into a failure


def test_comparison_is_linear_not_quadratic():
    def frame(n):
        return pd.DataFrame({"date": np.repeat(np.arange(n // 1000), 1000).astype(str), "bar_seq": np.tile(np.arange(1000), n // 1000),
                             "level": 0.5, "ts": pd.array(np.arange(n, dtype=np.int64) * 7, dtype="Int64")})
    a, b = frame(100_000), frame(400_000)
    P.compare_keyed(a, a, K, V, "warm")
    t0 = time.perf_counter(); P.compare_keyed(a, a.copy(), K, V, "n"); t1 = time.perf_counter()
    P.compare_keyed(b, b.copy(), K, V, "4n"); t2 = time.perf_counter()
    assert (t2 - t1) < 12 * max(t1 - t0, 0.02), (t1 - t0, t2 - t1)   # 4x rows: linear ~4x, quadratic ~16x


def _session_fixture():
    """5 warm sessions (one 10-contract row per minute -> T 10) and a hand-built session with carry, a collapsed
    completion, zero-volume rows, a gap and an incomplete (residual) final bar."""
    base = 1_893_456_000 * NS
    cal = [RthSession(f"2030-01-{i + 1:02d}", base + i * 86_400 * NS, base + i * 86_400 * NS + 405 * MIN, "FULL", False) for i in range(7)]
    k = VolumeClockKernel(cal)
    for s in cal[:5]:
        for m in range(405):
            k.push(s.start_ns + m * MIN, s.start_ns + m * MIN + NS, 100, 100, 100, 100, 10)
    S = cal[5].start_ns
    vols = [0, 3, 8, 0, 13, 2, 0, 9, 1, 1, 25, 4, 0, 6, 7]
    rows, states, ev = [], {}, []
    k.drain()
    t = S
    px = 100.0
    for i, v in enumerate(vols):
        o = px
        px += [0.25, -0.5, 0.0, 0.75][i % 4]
        row = (t, o, max(o, px) + 0.25, min(o, px) - 0.25, px, v)
        k.push(t, t + NS, *row[1:])
        rows.append(row)
        states[t + NS] = dict(k.state)
        ev += k.drain()
        t += (1 if i != 8 else 40) * NS                   # one 39-second gap
    bars = [p for n, p in ev if n == "bar_completed"]
    frozen = pd.DataFrame({"bar_seq": [b["bar_seq"] for b in bars], "avail_ts": [b["avail_ts"] for b in bars],
                           "end_ts": [b["end_ts"] for b in bars], "close": [np.nan if b["close"] is None else b["close"] for b in bars]})
    cps = sorted((p["bar_seq"], p["level"], p["ts"]) for n, p in ev if n == "checkpoint")
    r_exp = np.full(405, 10 / 60)
    pre = np.array([[cal[4].start_ns + 404 * MIN + NS, 100.0]])
    return rows, states, frozen, cps, r_exp, pre, S


def test_reference_agrees_with_the_tracker_on_a_hand_built_session_including_the_incomplete_bar():
    rows, states, frozen, cps, r_exp, pre, S = _session_fixture()
    ref_states, ref_cps = P.ref_session(np.asarray(rows, dtype=np.float64), S, 10, frozen, r_exp, pre, sample_every=1)
    assert len(ref_states) == len(rows) and len(frozen) == 7 and any(np.isnan(frozen.close))      # 79 contracts: 7 bars incl. a collapsed one
    assert sorted(ref_cps) == cps and max(c[0] for c in cps) == 8                                  # residual bar 8 (9 of 10) crossings
    ref = pd.DataFrame(ref_states, columns=["t", *P.STATE_FIELDS]).assign(date="d")
    trk = pd.DataFrame([{"t": t, **{f: st.get(f) for f in P.STATE_FIELDS}} for t, st in states.items()], columns=["t", *P.STATE_FIELDS]).assign(date="d")
    for f in ("t", *P.INT_STATE):
        ref[f] = pd.array(ref[f].astype(object).where(ref[f].notna(), None), dtype="Int64")
        trk[f] = pd.array(trk[f].astype(object).where(trk[f].notna(), None), dtype="Int64")
    r = P.compare_keyed(ref, trk, ["date", "t"], list(P.STATE_FIELDS), "hand")
    assert r["pass"], r["examples"]
    trk.loc[4, "consumed"] = trk.loc[4, "consumed"] + 1                                            # a planted defect is caught
    assert P.compare_keyed(ref, trk, ["date", "t"], list(P.STATE_FIELDS), "hand")["field_mismatches"]["consumed"] == 1


def test_derived_quality_flags_on_a_known_sequence():
    b = pd.DataFrame({"scale": "V1", "date": "d", "bar_seq": [1, 2, 3, 4], "start_ts": [0, 5, 9, 10], "end_ts": [5, 9, 9, 12],
                      "duration_s": [6, 4, 1, 3]})
    f = P._derived_flags(b)
    assert f.start_partial.tolist() == [False, True, True, False]
    assert f.end_partial_cmp.tolist()[:3] == [True, True, False] and pd.isna(f.end_partial_cmp.iloc[3])
    assert f.shared_second_completions.tolist() == [1, 2, 2, 1]
    assert f.completion_speed.tolist() == [10.0, 15.0, 60.0, 20.0]
