"""Synthetic-fixture tests for tracker.volume_profile.rolling.

(1) availability: a snapshot of minute T is a function of the bars with ts_init <= T only; (2) Friday ->
Sunday continuity in open-minute time; (3) roll truncation; (4) full-window eligibility and the null
policy; (5) incremental add / subtract == scratch rebuild, bit for bit; (6) volume conservation per
allocation; (7) the binding exposes the kernel's latest snapshot. R0 parity against the stored study
ledgers is the separate artifact artifacts/parity/volume_profile_rolling_r0_<block>.json.
"""
import numpy as np
import pytest

import features.trackers.volume_profile_rolling as VPR
from features.trackers.volume_profile_rolling import (FP, MIN_NS, NS, VolumeProfileKernel, VolumeProfileRollingBinding,
                                                       VolumeProfileSnapshot, open_minute_ends)
from research_workflow.host.interfaces import BarView

H = 10
SMALL = dict(a_window=20, a_min_live=3, min_window=3)
FRI_OPEN = 1_641_513_600 * NS                     # arbitrary minute-aligned instant
SUN_OPEN = FRI_OPEN + 49 * 3600 * NS               # 49 h closed gap ("weekend")
SESSIONS = (np.array([FRI_OPEN, SUN_OPEN]), np.array([FRI_OPEN + 15 * MIN_NS, SUN_OPEN + 15 * MIN_NS]))
OM = open_minute_ends(*SESSIONS)                    # 30 open minutes: 15 Friday + 15 Sunday


def _bars(seed=0, per_minute=3, minutes=OM):
    """Deterministic 1s bars strictly inside each open minute (ts_init in (T-60s, T-1s])."""
    rng = np.random.default_rng(seed)
    out = []
    for i, T in enumerate(minutes):
        offs = np.sort(rng.choice(np.arange(1, 59), per_minute, replace=False))[::-1]
        for o in offs:
            lo = 4000 + int(rng.integers(0, 40))
            out.append((int(T - o * NS), (lo + int(rng.integers(0, 6))) * 0.25, lo * 0.25, (lo + int(rng.integers(0, 3))) * 0.25, float(rng.integers(1, 50))))
    return out


def _run(bars, rolls=(), alloc="range_uniform", h=H, origin=None):
    k = VolumeProfileKernel(OM, np.array(rolls, np.int64), h, alloc, origin_ns=origin, **SMALL)
    snaps, xs = {}, {}

    def cb(p):
        snaps[p] = k.snapshot()
        lo = min(int(w[1].min()) for w in k.win) if k.win else None
        xs[p] = None if lo is None else {int(t): int(k.X[t - k.base]) for t in np.flatnonzero(k.X) + k.base}

    k.on_close = cb
    for b in bars:
        k.push(*b)
    k.close_through(int(OM[-1]))
    return k, snaps, xs


def _scratch(bars, k, p, alloc):
    """Window profile rebuilt from scratch: the bars of the window's minutes, same per-bar quantisation."""
    start = max(p - k.h_min + 1, k.reset_pos(p))
    lo_T, hi_T = OM[start], OM[p]
    X = {}
    for ts, h, l, c, v in bars:
        mk = -(-ts // MIN_NS) * MIN_NS
        if not lo_T <= mk <= hi_T:
            continue
        lt, ht, ct = round(l / 0.25), round(h / 0.25), round(c / 0.25)
        if alloc == "close":
            X[ct] = X.get(ct, 0) + int(np.round(v * FP))
        else:
            n = ht - lt + 1
            w = int(np.round((v / n if alloc == "range_uniform" else v) * FP))
            for t in range(lt, ht + 1):
                X[t] = X.get(t, 0) + w
    return {t: w for t, w in X.items() if w}


# ------------------------------------------------------------------------------------------- availability
def test_snapshot_at_T_is_immutable_to_later_bars():
    bars = _bars(1)
    T = int(OM[20])
    later = [(T + 5 * NS, 2000.0, 990.0, 1000.0, 1e6)] + [b for b in bars if b[0] > T + 5 * NS]
    _, a, _ = _run(bars)
    _, b, _ = _run([x for x in bars if x[0] <= T] + later)
    for p in range(21):
        assert {k: v for k, v in a[p].items() if k != "dropped_bars"} == {k: v for k, v in b[p].items() if k != "dropped_bars"}
    assert a[21] != b[21]                                                    # the altered minute itself does change


def test_bar_at_minute_end_closes_that_minute_and_next_ns_belongs_to_next():
    k = VolumeProfileKernel(OM, np.array([], np.int64), H, **SMALL)
    T = int(OM[0])
    assert k.push(T - 30 * NS, 1000.25, 1000.0, 1000.0, 1.0) == []
    assert k.push(T, 1000.25, 1000.0, 1000.25, 2.0) == [0]                  # ts_init == T: last member of minute T
    assert k.v.a[0] == 3.0
    assert k.push(T + 1, 1000.25, 1000.0, 1000.0, 5.0) == []                 # T + 1 ns -> minute T + 60 s
    assert k.close_through(int(OM[1])) == [1] and k.v.a[1] == 5.0


# ---------------------------------------------------------------------------------------- Friday -> Sunday
def test_friday_to_sunday_is_continuous_in_open_minutes():
    bars = _bars(2)
    k, snaps, _ = _run(bars)
    assert len(snaps) == 30                                                  # no synthetic weekend minutes
    p = 18                                                                   # 4th Sunday minute
    s = snaps[p]
    assert s["window_minutes"] == H and s["window_complete"] and not s["roll_truncated"]
    win = set(OM[9:19].tolist())                                             # 6 Friday + 4 Sunday minutes
    assert sum(1 for m in win if m < SUN_OPEN) == 6
    exp = sum(v for ts, *_, v in bars if -(-ts // MIN_NS) * MIN_NS in win)
    assert s["total_source_volume"] == exp
    first_sunday = [b for b in bars if b[0] > SUN_OPEN][0]
    k2 = VolumeProfileKernel(OM, np.array([], np.int64), H, **SMALL)
    for b in bars:
        if b[0] > SUN_OPEN:
            break
        k2.push(*b)
    assert k2.push(*first_sunday) == [14]                                   # only Friday's last minute closes; no gap minutes


# --------------------------------------------------------------------------------------------- rolls
def test_roll_truncates_window_and_A_and_minute_at_roll_stays_old():
    bars = _bars(3)
    roll = int(OM[12])                                                        # roll timestamp == end of minute 12
    _, snaps, _ = _run(bars, rolls=[roll])
    assert snaps[12]["window_complete"] and not snaps[12]["roll_truncated"]
    assert snaps[13]["window_minutes"] == 1 and snaps[13]["roll_truncated"] and snaps[13]["poc"] is None
    s15 = snaps[15]
    assert s15["window_minutes"] == 3 and s15["roll_truncated"] and not s15["window_complete"]
    assert s15["total_source_volume"] == sum(v for ts, *_, v in bars if OM[12] < ts <= OM[15])
    trs = []
    for m in (13, 14, 15):
        mb = [b for b in bars if OM[m] - MIN_NS < b[0] <= OM[m]]
        h, l = max(b[1] for b in mb), min(b[2] for b in mb)
        pc = [b for b in bars if b[0] <= OM[m - 1]][-1][3]
        trs.append(h - l if m == 13 else max(h - l, abs(h - pc), abs(l - pc)))
    assert s15["A"] == pytest.approx(np.mean(trs), rel=0, abs=1e-12)        # A restarts at the roll too
    assert snaps[22]["window_minutes"] == H and snaps[22]["window_complete"] and not snaps[22]["roll_truncated"]


# --------------------------------------------------------------------------------------- eligibility / null
def test_full_window_eligibility_and_null_policy():
    _, snaps, _ = _run(_bars(4))
    assert snaps[1]["poc"] is None and snaps[1]["window_minutes"] == 2 and not snaps[1]["window_complete"]
    assert snaps[2]["poc"] is not None and not snaps[2]["window_complete"]
    assert [p for p, s in snaps.items() if s["window_complete"]] == list(range(H - 1, 30))
    assert all(s["window_minutes"] == min(p + 1, H) for p, s in snaps.items())


def test_empty_open_minute_counts_and_carries_close():
    bars = [b for b in _bars(5) if not OM[5] - MIN_NS < b[0] <= OM[5]]      # minute 5 has no bar
    k, snaps, _ = _run(bars)
    assert snaps[5]["window_minutes"] == 6 and k.v.a[5] == 0.0
    assert k.h.a[5] == k.l.a[5] == k.c.a[5] == k.c.a[4] and k.tr.a[5] == 0.0


# ------------------------------------------------------------------------------- incremental == scratch
@pytest.mark.parametrize("alloc", ["range_uniform", "full_per_tick", "close"])
def test_incremental_equals_scratch_bit_for_bit(alloc):
    bars = _bars(6, per_minute=5)
    k, _, xs = _run(bars, rolls=[int(OM[20])], alloc=alloc)
    for p in range(30):
        assert xs[p] == _scratch(bars, k, p, alloc), p


def test_volume_conservation_by_allocation():
    bars = _bars(7, per_minute=4)
    p = 25
    win = (OM[p - H], OM[p])
    vb = [b for b in bars if win[0] < b[0] <= win[1]]
    ru = _run(bars, alloc="range_uniform")[1][p]
    cl = _run(bars, alloc="close")[1][p]
    fp = _run(bars, alloc="full_per_tick")[1][p]
    vol = sum(b[4] for b in vb)
    assert cl["total_weight"] == vol == ru["total_source_volume"]
    assert abs(ru["total_weight"] - vol) <= sum(round(b[1] / .25) - round(b[2] / .25) + 1 for b in vb) * 2.0 ** -32
    assert fp["total_weight"] == sum(b[4] * (round(b[1] / .25) - round(b[2] / .25) + 1) for b in vb)   # NOT conserving
    assert fp["va_weight_fraction"] >= 0.70


# --------------------------------------------------------------------------------------------- binding
def test_binding_exposes_latest_kernel_snapshot(monkeypatch):
    monkeypatch.setattr(VPR, "load_calendar", lambda ds: (OM, np.array([], np.int64)))
    with pytest.raises(ValueError):
        VolumeProfileRollingBinding({"dataset": "X"}, {"bars": "s"})
    b = VolumeProfileRollingBinding({"dataset": "X", "horizon_open_minutes": H, **SMALL}, {"bars": "s"})
    assert all(getattr(b, f) is None for f in b.FIELDS)
    k = VolumeProfileKernel(OM, np.array([], np.int64), H, **SMALL)
    for ts, h, l, c, v in _bars(8):
        b.on_bar("bars", BarView("s", ts - NS, ts, c, h, l, c, v))
        if k.push(ts, h, l, c, v):
            snap = k.snapshot()
            assert all(getattr(b, f) == snap.get(f) for f in b.FIELDS if f != "dropped_bars")
    assert [e.name for e in b.drain_events()].count("minute_closed") == 29  # minute 29 closes only via close_through


# ------------------------------------------------------------------------------- exact tie resolution
def test_rounding_cannot_break_an_exact_value_area_tie():
    """Up pair = three bar contributions of 1/3 (exactly 1); down pair = 1. Rounded per bar the up pair is one unit
    short, so a plain fixed-point walk would add only the lower pair. The bounded walk must flag the step and the
    exact walk must add both pairs (oracle rule: tie adds both)."""
    from fractions import Fraction
    from features.trackers.volume_profile_rolling import value_area_exact, value_area_int
    third = int(np.round(FP / 3))
    X = np.array([int(FP), 0, 4 * int(FP), 3 * third, 0], np.int64)
    C = np.array([1, 0, 1, 3, 0], np.int64)
    assert 3 * third != int(FP)
    *_, amb = value_area_int(X, C, 2, 0.70, float(X.sum()), float(C.sum()))
    assert amb
    E = [Fraction(1), Fraction(0), Fraction(4), Fraction(1, 3) * 3, Fraction(0)]
    lo, hi, _ = value_area_exact(E, 2, 0.70)
    assert (lo, hi) == (0, 4)


# ------------------------------------------------------------------------------ profile emission (G2)
def _run_capture(bars, target_p, alloc="range_uniform", rolls=(), emit=True):
    """Kernel run that snapshots minute ``target_p`` AT the moment it closes (never after later
    minutes have mutated the rolling window arrays)."""
    k = VolumeProfileKernel(OM, np.array(rolls, np.int64), H, alloc, **SMALL)
    out: dict = {}

    def cb(p):
        if p == target_p:
            out["snap"] = k.snapshot()
            out["obj"] = k.profile_snapshot(out["snap"]) if emit else None

    k.on_close = cb
    for b in bars:
        k.push(*b)
    k.close_through(int(OM[-1]))
    return k, out.get("snap"), out.get("obj")


@pytest.mark.parametrize("alloc", ["range_uniform", "full_per_tick", "close"])
def test_profile_object_reconstructs_scalar_outputs_exactly(alloc):
    bars = _bars(10, per_minute=5)
    k, snap, obj = _run_capture(bars, 20, alloc=alloc)
    assert snap["poc"] is not None and obj is not None
    rec = obj.reconstruct_poc_va_nodes(va_frac=k.va_frac)
    for key in ("poc", "vah", "val", "va_weight_fraction", "raw_poc", "raw_vah", "raw_val", "n_hvn", "n_lvn", "hvns_json", "lvns_json"):
        assert rec[key] == snap[key], (alloc, key)


def test_profile_object_reconstructs_scalar_outputs_through_an_exact_value_area_tie():
    """Object-level regression on the SAME oracle tie fixture as
    ``test_rounding_cannot_break_an_exact_value_area_tie``: a rounded-weight vector whose bounded
    walk is ambiguous reconstructs the full-width (0, 4) value area only because
    ``exact_triplets`` carries the pre-rounding rational per-tick volumes."""
    from features.trackers.volume_profile_rolling import VolumeProfileSnapshot
    third = int(np.round(FP / 3))
    X = (int(FP), 0, 4 * int(FP), 3 * third, 0)
    C = (1, 0, 1, 3, 0)
    trips = ((0, 1, 1), (2, 1, 4), (3, 3, 3))                            # -> exact fractions [1, 0, 4, 1, 0]
    obj = VolumeProfileSnapshot.build(
        snapshot_ts=0, segment_start_ts=0, horizon_open_minutes=H, allocation="range_uniform",
        window_minutes=H, window_complete=True, roll_truncated=False, window_start_ts=0, window_end_ts=0,
        tick=1.0, lo_tick=0, n_bins=5, win_lo_tick=0, win_hi_tick=4, weights_fp=X, contributions=C, weight_scale=int(FP),
        total_weight_fp=int(sum(X)), total_source_volume=0.0, volume_conserving=True, sigma_a=0.0,
        sigma_ticks=1e-9, exact_triplets=trips)
    rec = obj.reconstruct_poc_va_nodes(va_frac=0.70)
    assert rec["val"] == 0.0 and rec["vah"] == 4.0


def test_profile_object_reconstructs_close_allocation_whose_occupied_range_is_narrower_than_the_bar_range():
    """D1 regression (real-tape minute 2022-02-01..04, allocation=close, horizon_open_minutes=120):
    a bar's close need not be its high or low, so the CLOSE allocation's occupied-weight range
    (``lo_tick`` / ``n_bins``) can be strictly narrower than the window's bar range (``win_lo_tick``
    / ``win_hi_tick``). The live kernel's value-area walk array is sized from the bar range; padding
    the reconstruction from the occupied range alone clamps the walk's array-boundary stop rule at a
    nearer edge and silently shifts ``vah`` (observed: 15172.25 reconstructed vs 15172.75 live on one
    real minute before this fix; the fixture below pins a second, independently captured real minute).
    """
    import json
    from pathlib import Path

    from features.trackers.volume_profile_rolling import VolumeProfileSnapshot

    fx = json.loads((Path(__file__).parent / "golden" / "volume_profile_rolling_close_alloc_real_tape_minute.json").read_text())
    assert fx["lo_tick"] != fx["win_lo_tick"] or fx["lo_tick"] + fx["n_bins"] - 1 != fx["win_hi_tick"], \
        "fixture no longer exercises the narrower-occupied-range-than-bar-range case"
    obj = VolumeProfileSnapshot.build(**{k: (tuple(v) if isinstance(v, list) and k != "exact_triplets" else
                                            (tuple(tuple(t) for t in v) if k == "exact_triplets" and v is not None else v))
                                          for k, v in fx.items() if k not in ("note", "expected")})
    rec = obj.reconstruct_poc_va_nodes()
    for key, expected in fx["expected"].items():
        assert rec[key] == expected, (key, rec[key], expected)


def test_emit_profile_false_leaves_every_existing_output_byte_identical(monkeypatch):
    monkeypatch.setattr(VPR, "load_calendar", lambda ds: (OM, np.array([], np.int64)))
    scalar_fields = [f for f in VolumeProfileRollingBinding.FIELDS if f not in ("profile_json", "profile_hash")]
    bars = _bars(11)
    off = VolumeProfileRollingBinding({"dataset": "X", "horizon_open_minutes": H, **SMALL}, {"bars": "s"})
    on = VolumeProfileRollingBinding({"dataset": "X", "horizon_open_minutes": H, "emit_profile": True, **SMALL}, {"bars": "s"})
    for ts, h, l, c, v in bars:
        off.on_bar("bars", BarView("s", ts - NS, ts, c, h, l, c, v))
        on.on_bar("bars", BarView("s", ts - NS, ts, c, h, l, c, v))
    for f in scalar_fields:
        assert getattr(off, f) == getattr(on, f), f
    assert off.profile_json is None and off.profile_hash is None


def test_profile_hash_is_deterministic_and_matches_an_identical_rebuild():
    bars = _bars(12, per_minute=4)
    _, _, obj1 = _run_capture(bars, 20)
    _, _, obj2 = _run_capture(bars, 20)
    assert obj1.content_hash == obj2.content_hash == VolumeProfileSnapshot.from_json(obj1.to_json()).content_hash
    assert obj1.to_json() == obj2.to_json()


def test_profile_object_is_causal_to_later_bars():
    bars = _bars(13)
    T = int(OM[20])
    later = [(T + 5 * NS, 2000.0, 990.0, 1000.0, 1e6)] + [b for b in bars if b[0] > T + 5 * NS]
    _, _, obj_a = _run_capture(bars, 20)
    _, _, obj_b = _run_capture([x for x in bars if x[0] <= T] + later, 20)
    assert obj_a.content_hash == obj_b.content_hash
    _, _, obj_a21 = _run_capture(bars, 21)
    _, _, obj_b21 = _run_capture([x for x in bars if x[0] <= T] + later, 21)
    assert obj_a21.content_hash != obj_b21.content_hash                 # the altered minute itself does change


def test_profile_object_null_before_min_window_and_roll_truncated_flag():
    bars = _bars(14)
    roll = int(OM[12])
    _, snap13, obj13 = _run_capture(bars, 13, rolls=[roll])
    assert snap13["poc"] is None and obj13 is None
    _, snap15, obj15 = _run_capture(bars, 15, rolls=[roll])
    assert obj15 is not None and obj15.roll_truncated and obj15.window_minutes == 3


def test_profile_object_states_conservation_by_allocation():
    bars = _bars(15, per_minute=4)
    _, snap_ru, obj_ru = _run_capture(bars, 25, alloc="range_uniform")
    _, snap_cl, obj_cl = _run_capture(bars, 25, alloc="close")
    _, snap_fp, obj_fp = _run_capture(bars, 25, alloc="full_per_tick")
    assert obj_ru.volume_conserving and obj_cl.volume_conserving and not obj_fp.volume_conserving
    assert obj_ru.total_weight_fp / obj_ru.weight_scale == pytest.approx(snap_ru["total_weight"], rel=0, abs=1e-9)
    assert obj_cl.total_weight_fp == int(round(snap_cl["total_weight"] * obj_cl.weight_scale))
    assert obj_fp.total_weight_fp == int(round(snap_fp["total_weight"] * obj_fp.weight_scale))


# --------------------------------------------------------------------- discoverability / compile gap
def test_binding_declares_emit_profile_param_and_profile_fields():
    assert "emit_profile" in VolumeProfileRollingBinding.PARAMS
    assert VolumeProfileRollingBinding.PARAMS["emit_profile"] is False
    assert "profile_json" in VolumeProfileRollingBinding.FIELDS and "profile_hash" in VolumeProfileRollingBinding.FIELDS
    assert VolumeProfileRollingBinding.FIELD_REQUIRES_PARAM["profile_json"] == ("emit_profile", True)
    assert VolumeProfileRollingBinding.FIELD_REQUIRES_PARAM["profile_hash"] == ("emit_profile", True)


def test_referencing_profile_field_without_emit_profile_is_a_compile_gap():
    from research_workflow.grammar.compiler import _check_field_requires_param

    class _StubCtx:
        def __init__(self, params):
            self.trackers = [{"id": "vp", "params": params}]
            self.gaps_seen = []

        def gap(self, kind, where, msg, **kw):
            self.gaps_seen.append((kind, where, msg))

    off = _StubCtx({"emit_profile": False})
    assert _check_field_requires_param(off, VolumeProfileRollingBinding, "vp", "profile_json", "context.vp.profile_json") is False
    assert off.gaps_seen and "requires parameter emit_profile" in off.gaps_seen[0][2]

    on = _StubCtx({"emit_profile": True})
    assert _check_field_requires_param(on, VolumeProfileRollingBinding, "vp", "profile_json", "context.vp.profile_json") is True
    assert not on.gaps_seen

    unrelated = _StubCtx({"emit_profile": False})
    assert _check_field_requires_param(unrelated, VolumeProfileRollingBinding, "vp", "poc", "context.vp.poc") is True
    assert not unrelated.gaps_seen
