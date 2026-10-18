"""tracker.volume_profile.rolling -- snapshot time vs observation time (regression).

Contract (research_workflow/capabilities/proposals/tracker.volume_profile.rolling.yaml, ``semantics``): minute T
holds the 1s bars with ts_init in (T - 60 s, T]; its snapshot "becomes readable when the minute is known complete:
on the bar with ts_init == T, else on the first later bar. snapshot_ts names the minute."

So a candidate row observed at ``observation_ts`` T carries the LATEST READABLE minute, which is T only when a 1s bar
is stamped exactly T (the host ingests a 1s bar before the 1m epoch bar at equal ts_init:
``host_runner.sort_bars_causal``). Otherwise it is an earlier open minute -- one minute back inside a session, the
previous session's last minute after a break. A 2026-10-09 scratch-vs-governed parity harness joined the governed
rows on observation time instead of ``profile.snapshot_ts``; 35% of the G2 pilot's rows then compared minute T with
minute T-1 and the difference was misreported as a data discrepancy. These tests pin the publication timing through
the real compiler and HostCore, and show that only the snapshot-time join compares like with like.

Synthetic tape only; no catalog, no replay of historical data. ``load_calendar`` is replaced by the synthetic
open-minute calendar, as in test_volume_profile_rolling.test_binding_exposes_latest_kernel_snapshot.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest
import yaml

import features.trackers.volume_profile_rolling as VPR
from features.trackers.volume_profile_rolling import VolumeProfileKernel, VolumeProfileSnapshot, open_minute_ends
from research_workflow.host.interfaces import BarView

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
M = 60 * NS
T0 = 1_893_456_000 * NS                                   # 2030-01-01T00:00Z
TD_ROWS = [(T0, T0 + 20 * M), (T0 + 30 * M, T0 + 50 * M)]  # two sessions, a 10-minute closure between them
OM = open_minute_ends(np.array([r[0] for r in TD_ROWS]), np.array([r[1] for r in TD_ROWS]))
PARAMS = dict(horizon_open_minutes=10, allocation="full_per_tick", a_window=20, a_min_live=3, min_window=3)
SCALARS = ("snapshot_ts", "window_minutes", "window_complete", "A", "sigma_ticks", "win_lo", "win_hi", "total_weight",
           "poc", "vah", "val", "n_hvn", "n_lvn", "hvns_json", "lvns_json")
# minutes whose boundary bar (ts_init == T) is moved to T - 1 s in the "missing" variant: one mid-session and the
# first minute after the closure (the previous readable minute is then the prior session's last, 11 minutes back)
MOVED = (int(T0 + 12 * M), int(T0 + 31 * M))


def _tape(missing: bool) -> Tuple[List[BarView], List[BarView]]:
    """1s bars at seconds 15/30/45/60 of every open minute (the 60 s bar is the boundary bar); 1m bars = their
    aggregate. Minute volumes differ minute to minute, so adjacent snapshots are never equal. The ``missing``
    variant moves the boundary bar of each MOVED minute 1 s earlier -- same minute, same values, same profiles;
    only the instant the minute becomes readable changes."""
    rng = np.random.default_rng(7)
    ones: List[BarView] = []
    mins: List[BarView] = []
    for T in OM.tolist():
        bars = []
        for off in (45, 30, 15, 0):
            ts = T - off * NS
            if missing and off == 0 and T in MOVED:
                ts = T - NS
            lo = 4000 + int(rng.integers(0, 24))
            h, l, c = (lo + int(rng.integers(0, 6))) * 0.25, lo * 0.25, (lo + int(rng.integers(0, 3))) * 0.25
            bars.append(BarView("1s", ts - NS, ts, c, h, l, c, float(rng.integers(1, 60))))
        ones += bars
        mins.append(BarView("1m", T - M, T, bars[0].open, max(b.high for b in bars), min(b.low for b in bars), bars[-1].close,
                            float(sum(b.volume for b in bars))))
    return ones, mins


def _contract_minute(ones: List[BarView], t: int):
    """The minute the contract says is readable at instant t: every open minute m with some 1s bar ts_init in
    [m, t] is complete; the latest such m (None before the first one)."""
    seen = [b.ts_init for b in ones if b.ts_init <= t]
    if not seen:
        return None
    k = int(np.searchsorted(OM, max(seen), side="right"))
    return int(OM[k - 1]) if k else None


def _kernel_minutes(ones: List[BarView]) -> Dict[int, Dict[str, Any]]:
    """Per minute: the real kernel's scalar snapshot and typed profile, captured AT the minute's close (the
    "scratch" side of a parity comparison, keyed by the minute it describes)."""
    p = PARAMS
    k = VolumeProfileKernel(OM, np.array([], np.int64), p["horizon_open_minutes"], p["allocation"], a_window=p["a_window"],
                            a_min_live=p["a_min_live"], min_window=p["min_window"])
    out: Dict[int, Dict[str, Any]] = {}

    def cb(q):
        s = k.snapshot()
        out[int(k.om[q])] = {"snap": s, "obj": k.profile_snapshot(s)}

    k.on_close = cb
    for b in ones:
        k.push(b.ts_init, b.high, b.low, b.close, b.volume)
    k.close_through(int(OM[-1]))
    return out


def _spec() -> Dict[str, Any]:
    meta = {"obs_T": "epoch.T", "vp_profile": "vp.profile"}
    meta.update({f"vp_{f}": f"vp.{f}" for f in SCALARS})
    return {
        "study": {"id": "vp_snapshot_timing", "tier": 2, "question": "profile snapshot time vs observation time"},
        "streams": [{"dataset": "SYN_A", "timeframes": ["1s", "1m"]}],
        "context": {"vp": {"tracker": "volume_profile.rolling", "bars": "1s", "dataset": "SYN_A", "emit_profile": True, **PARAMS}},
        "population": {"session": "RTH", "cadence": "completed_1m"},
        "triggers": "every_candidate",
        "features": {"metadata": meta},
        "outcome": "none",
        "chronology": {"train": [2030], "dev": [], "prohibited": []},
        "model": "none",
    }


def _compile(tmp: Path) -> Dict[str, Any]:
    from research_workflow.capabilities import load_registry
    from research_workflow.grammar.compiler import compile_study, load_spec
    ds = tmp / "datasets"
    ds.mkdir(parents=True)
    for p in (GOLDEN / "datasets").glob("*.yaml"):
        shutil.copy2(p, ds / p.name)
    a = yaml.safe_load((ds / "SYN_A.yaml").read_text(encoding="utf-8"))
    a["reference_tables"] = ["sessions"]
    a["coverage"] = {"start": "2030-01-01T00:00:00Z", "end": "2030-01-01T01:00:00Z"}
    (ds / "SYN_A.yaml").write_text(yaml.safe_dump(a, sort_keys=False), encoding="utf-8")
    study = tmp / "studies" / "vp_snapshot_timing"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(yaml.safe_dump(_spec(), sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, registry=load_registry(), datasets_dir=ds)
    assert out.ok, out.card()
    return out.plan.to_dict()


def _replay(plan: Dict[str, Any], missing: bool):
    """Replays the tape through HostCore; after every ingest records the tracker's readable minute."""
    from research_workflow.host.strategy import HostCore
    from research_workflow.host_runner import sort_bars_causal
    from research_workflow.sessions import TRADING_DAY, build_session_table
    keys = {s["timeframe"]: s["key"] for s in plan["streams"]}
    ones, mins = _tape(missing)
    rk = lambda k, b: BarView(k, b.ts_event, b.ts_init, b.open, b.high, b.low, b.close, b.volume)  # noqa: E731
    bars = [rk(keys["1s"], b) for b in ones] + [rk(keys["1m"], b) for b in mins]
    core = HostCore(plan, session_table=build_session_table(
        {"kind": "calendar", "session": "RTH", "rows": TD_ROWS, "rows_by_session": {"RTH": TD_ROWS, TRADING_DAY: TD_ROWS}}))
    trail = []
    for bar in sort_bars_causal(bars, {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}):
        core.ingest(bar)
        vp = core.trackers["vp"]
        trail.append((bar, vp.snapshot_ts, (vp.profile or {}).get("snapshot_ts")))
    cands, _ = core.finalize()
    rows = cands.to_dict("records") if hasattr(cands, "to_dict") else list(cands)
    return {"ones": ones, "rows": rows, "trail": trail, "keys": keys}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(VPR, "load_calendar", lambda ds: (OM, np.array([], np.int64)))
    try:
        plan = _compile(tmp_path_factory.mktemp("vpst"))
        return {v: _replay(plan, v) for v in (False, True)}
    finally:
        mp.undo()


def _profile(row) -> VolumeProfileSnapshot:
    return VolumeProfileSnapshot.from_struct(row["vp_profile"])


def _assert_same_snapshot(row: Dict[str, Any], ref: Dict[str, Any], ctx) -> None:
    """Every scalar field AND the typed profile of the row belong to the minute ``ref`` describes."""
    snap, obj = ref["snap"], ref["obj"]
    null = lambda x: x is None or (isinstance(x, float) and np.isnan(x))  # noqa: E731  (the sink stores None as NaN)
    for f in SCALARS:
        a, b = row[f"vp_{f}"], snap.get(f)
        assert (null(a) and null(b)) or a == b, (ctx, f, a, b)
    if obj is None:
        assert row["vp_profile"] is None, ctx
        return
    got = _profile(row)
    assert got.content_hash == obj.content_hash, ctx                          # weights, window, sigma, totals
    assert (got.snapshot_ts, got.window_end_ts) == (snap["snapshot_ts"], snap["snapshot_ts"]), ctx
    assert got.window_minutes == snap["window_minutes"] and got.sigma_ticks == snap["sigma_ticks"], ctx
    assert got.total_weight_fp / got.weight_scale == pytest.approx(snap["total_weight"], abs=0, rel=0), ctx
    rec = got.reconstruct_poc_va_nodes(va_frac=0.70)                         # POC / VA / node centres, edges, prominence
    for f in ("poc", "vah", "val", "n_hvn", "n_lvn", "hvns_json", "lvns_json"):
        assert rec[f] == snap[f], (ctx, f)


def _window_volume(ones: List[BarView], start: int, end: int) -> float:
    """Independent of the kernel: contract volume of the 1s bars whose minute (ceil(ts_init / 60 s)) is in
    [start, end]."""
    return float(sum(b.volume for b in ones if start <= -(-b.ts_init // M) * M <= end))


# ------------------------------------------------------------------ Test 1: exact minute-boundary publication
def test_boundary_bar_publishes_its_own_minute_at_that_bar_and_nothing_later(runs):
    r = runs[False]
    ones, ref = r["ones"], _kernel_minutes(r["ones"])
    for bar, snap_ts, prof_ts in r["trail"]:
        if bar.stream != r["keys"]["1s"] or bar.ts_init not in OM:
            continue
        # the boundary bar itself makes its minute readable -- at that bar, not later
        assert snap_ts == bar.ts_init, bar
        assert prof_ts in (None, bar.ts_init), bar
    rows = [x for x in r["rows"] if x["vp_profile"] is not None]
    assert len(rows) > 20
    for row in rows:
        T = row["observation_ts"]
        assert row["vp_snapshot_ts"] == T and _profile(row).snapshot_ts == T  # every minute here has a boundary bar
        _assert_same_snapshot(row, ref[T], T)
        p = _profile(row)
        assert p.total_source_volume == _window_volume(ones, p.window_start_ts, p.window_end_ts)   # no later bar in it
        assert all(b.ts_init <= T for b in ones if p.window_start_ts - M < b.ts_init <= p.window_end_ts)


# ------------------------------------------------------------------ Test 2: missing boundary bar
def test_missing_boundary_bar_keeps_the_prior_minute_until_the_first_later_bar(runs):
    r = runs[True]
    ones, ref = r["ones"], _kernel_minutes(r["ones"])
    one = r["keys"]["1s"]
    # at EVERY instant of the replay the readable minute is the contract's, never a fixed lag
    for bar, snap_ts, prof_ts in r["trail"]:
        want = _contract_minute(ones, bar.ts_init)
        assert snap_ts == want, bar
        assert prof_ts in (None, want), bar
    prev = {int(OM[i]): int(OM[i - 1]) for i in range(1, len(OM))}
    for T in MOVED:
        at = [(b, s) for b, s, _ in r["trail"] if T - NS <= b.ts_init <= T]
        assert at and all(s == prev[T] for _, s in at), T                   # T - 1 s bar and T epoch: still the prior minute
        later = next((b, s) for b, s, _ in r["trail"] if b.stream == one and b.ts_init > T)
        assert later[1] == T, (T, later)                                      # readable on the first later bar
    assert prev[MOVED[1]] == int(T0 + 20 * M)                                # across the closure: 11 minutes back, not 1
    by_T = {row["observation_ts"]: row for row in r["rows"]}
    for T in MOVED:
        row = by_T[T]
        assert row["observation_ts"] == T and row["vp_snapshot_ts"] == prev[T] != T
        assert _profile(row).snapshot_ts == prev[T]
        _assert_same_snapshot(row, ref[prev[T]], T)                         # the prior minute, all fields consistent
    for row in r["rows"]:                                                    # no future snapshot in any row
        assert row["vp_snapshot_ts"] <= row["observation_ts"]
        assert row["vp_snapshot_ts"] == _contract_minute(ones, row["observation_ts"])
        _assert_same_snapshot(row, ref[row["vp_snapshot_ts"]], row["observation_ts"])


# ------------------------------------------------------------------ Test 3: host observation-row alignment
@pytest.mark.parametrize("missing", [False, True])
def test_host_row_keeps_observation_time_and_snapshot_time_distinct(runs, missing):
    rows = runs[missing]["rows"]
    lagged = 0
    for row in rows:
        assert row["obs_T"] == row["observation_ts"]                           # the row records its own observation time
        if row["vp_profile"] is not None:
            assert _profile(row).snapshot_ts == row["vp_snapshot_ts"]          # scalar mapping agrees with the nested value
        lagged += row["vp_snapshot_ts"] != row["observation_ts"]
    # the host never relabels the snapshot as the observation minute
    assert lagged == (len(MOVED) if missing else 0)


# ------------------------------------------------------------------ Test 4: the historical comparison error
def test_parity_join_must_use_profile_snapshot_ts_not_observation_ts(runs):
    """The 2026-10-09 error: a scratch profile of minute T compared with the governed row observed at T."""
    r = runs[True]
    scratch = _kernel_minutes(r["ones"])
    rows = [x for x in r["rows"] if x["vp_profile"] is not None]

    def mismatches(key):
        bad = []
        for row in rows:
            ref = scratch[key(row)]
            if ref["obj"] is None or ref["obj"].content_hash != _profile(row).content_hash or \
                    ref["snap"]["total_weight"] != row["vp_total_weight"] or ref["snap"]["A"] != row["vp_A"]:
                bad.append(row["observation_ts"])
        return bad

    wrong = mismatches(lambda row: row["observation_ts"])
    right = mismatches(lambda row: _profile(row).snapshot_ts)
    assert sorted(wrong) == sorted(MOVED)          # observation-time join compares different minutes exactly there
    assert right == []                             # snapshot-time join: exact agreement on every row
    for row in rows:
        _assert_same_snapshot(row, scratch[_profile(row).snapshot_ts], row["observation_ts"])
    # the two adjacent profiles really are different snapshots (not a vacuous comparison)
    for T in MOVED:
        a, b = scratch[T]["snap"], scratch[int(OM[int(np.searchsorted(OM, T)) - 1])]["snap"]
        assert a["total_weight"] != b["total_weight"] and json.loads(a["hvns_json"]) != [] and a["snapshot_ts"] != b["snapshot_ts"]
