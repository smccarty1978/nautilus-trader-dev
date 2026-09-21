"""tracker.regime.prior_level_snapshot -- causal contract.

Two layers:

* hand-derived unit cases on a stub regime (every expected number is written out below), and
* an end-to-end replay of a synthetic 1s/1m tape through the real compiler, StreamMux and HostCore with
  5m/15m/1h dual-EMA regimes on host-derived closed windows -- the study's composition -- checked against a
  TEST-ONLY oracle that rebuilds every completed regime from the raw 1m tape (its own window aggregation and
  zero-volume fill; the dual-EMA engine is reused only for the regime DIRECTION, which is not under test).

``python -m features.tests.test_regime_prior_level_snapshot --write-parity <json>`` writes the parity artifact.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

from features.trackers.base import BaseBinding
from features.trackers.host_bindings import RegimeExcursionBinding
from features.trackers.regime_prior_level_snapshot import SNAPSHOT_FIELDS, RegimePriorLevelSnapshotBinding
from research_workflow.host.interfaces import BarView, EmittedEvent

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
M = 60 * NS
CAP = "tracker.regime.prior_level_snapshot"


# =========================================================================== unit layer (stub regime)
class _StubRegime:
    """What the binding reads from its regime input: ``changed``, ``bars_in_regime``, ``changed_seq``."""

    def __init__(self) -> None:
        self.changed = False
        self.bars_in_regime = 0
        self.changed_seq = 0


class _Driver:
    """Drives a snapshot binding AND a sibling canonical excursion exactly as HostCore does: source bars on
    ``bars``; per regime bar, ``regime_bar`` then (on a change) ``changed``, routed after the regime updated."""

    def __init__(self) -> None:
        self.regime = _StubRegime()
        self.snap = RegimePriorLevelSnapshotBinding({}, {"bars": "s1m", "regime": self.regime})
        self.sib = RegimeExcursionBinding({}, {"bars": "s1m", "regime": self.regime})

    def bar(self, ts_init: int, o: float, h: float, l: float, c: float) -> None:
        b = BarView("s1m", ts_init - M, ts_init, o, h, l, c, 1.0)
        self.snap.on_bar("bars", b)
        self.sib.on_bar("bars", b)

    def regime_bar(self, close_ts: int, *, change: Optional[Tuple[int, float, float, float]] = None) -> None:
        """``change = (direction, open, close, atr)`` for the bar that establishes a new regime."""
        r = self.regime
        r.changed = change is not None
        if change is None:
            r.bars_in_regime += 1
        else:
            r.bars_in_regime = 0
            r.changed_seq += 1
        self.snap.on_event("regime", EmittedEvent("regime_bar", {"close_ts": close_ts}))
        if change is not None:
            d, o, c, atr = change
            ev = EmittedEvent("changed", {"direction": d, "prev_direction": 0, "start_ns": close_ts, "close_ts": close_ts,
                                          "start_price": o, "close_price": c, "atr_start": atr, "prior_end_close": c})
            self.snap.on_event("regime", ev)
            self.sib.on_event("regime", ev)


S0 = 1_893_456_000 * NS          # 2030-01-01T00:00Z; 5m regime bars
TF = 5 * M


def _two_regimes() -> Tuple[_Driver, Dict[str, Any]]:
    """Regime A (+1, open 100, ATR 2) established at S0, survives two 5m bars, terminated at S0+3TF."""
    d = _Driver()
    d.regime_bar(S0, change=(1, 100.0, 100.5, 2.0))
    d.bar(S0, 100.0, 101.0, 99.5, 100.5)                 # the establishing window's last 1m bar: regime A's
    d.bar(S0 + M, 100.5, 103.0, 100.0, 102.5)
    d.regime_bar(S0 + TF)
    d.bar(S0 + TF + M, 102.5, 102.75, 98.75, 99.0)
    d.regime_bar(S0 + 2 * TF)
    pre = {"dir": d.sib.dir, "start_price": d.sib.start_price, "frozen_atr": d.sib.frozen_atr, "hh": d.sib.highest_high,
           "ll": d.sib.lowest_low, "last_close": d.sib.last_close, "last_ts": d.sib.last_ts, "mfe_atr": d.sib.mfe_atr,
           "mae_atr": d.sib.mae_atr, "pnl_atr": d.sib.pnl_atr}
    d.regime_bar(S0 + 3 * TF, change=(-1, 99.25, 97.0, 2.5))   # terminates A; establishes B
    return d, pre


A_EXPECTED = {
    "dir": 1, "start_ns": S0, "end_ns": S0 + 3 * TF, "start_price": 100.0,
    "end_price": 99.0, "end_price_ts": S0 + TF + M,          # the last 1m close regime A's accumulator saw
    "transition_close": 97.0,                                # the terminating 5m bar's close: NOT end_price
    "frozen_atr": 2.0, "duration_s": 900.0, "bars": 2,
    "mfe_price": 103.0, "mae_price": 98.75,
    "mfe_atr": (103.0 - 100.0) / 2.0, "mae_atr": (100.0 - 98.75) / 2.0,
    "terminal_displacement_atr": (99.0 - 100.0) / 2.0,
    "regime_seq": 1, "frozen_at_ns": S0 + 3 * TF, "rotation_seq": 1,
}


def test_no_prior_before_the_first_completed_regime():
    d = _Driver()
    assert d.snap.snapshot() == {**{f: None for f in SNAPSHOT_FIELDS}, "rotation_seq": 0}
    d.regime_bar(S0 - TF)                                            # warmup regime bar, regime still 0
    d.bar(S0 - M, 100.0, 100.5, 99.5, 100.0)
    d.regime_bar(S0, change=(1, 100.0, 100.5, 2.0))                  # 0 -> +1 completes nothing
    d.bar(S0, 100.0, 101.0, 99.5, 100.5)
    assert d.snap.snapshot() == {**{f: None for f in SNAPSHOT_FIELDS}, "rotation_seq": 0}


def test_freeze_at_transition_equals_the_completed_accumulator_before_its_reset():
    d, pre = _two_regimes()
    assert d.snap.snapshot() == A_EXPECTED
    s = d.snap
    # bit-equal to the canonical excursion state immediately before the reset (invariants 2, 5, 6, 7)
    assert (s.dir, s.start_price, s.frozen_atr, s.end_price, s.end_price_ts) == (pre["dir"], pre["start_price"], pre["frozen_atr"], pre["last_close"], pre["last_ts"])
    assert (s.mfe_price, s.mae_price) == (pre["hh"], pre["ll"])
    assert (s.mfe_atr, s.mae_atr, s.terminal_displacement_atr) == (pre["mfe_atr"], pre["mae_atr"], pre["pnl_atr"])
    # ...and the sibling has since reset to regime B: the snapshot is not the current regime
    assert (d.sib.dir, d.sib.start_price, d.sib.frozen_atr) == (-1, 99.25, 2.5)
    assert s.dir == 1 and s.frozen_atr == 2.0                         # completed regime's direction and ATR, not B's


def test_immutable_and_uncontaminated_until_the_next_transition():
    d, _ = _two_regimes()
    frozen = d.snap.snapshot()
    H = S0 + 3 * TF
    d.bar(H, 99.25, 99.5, 96.5, 97.0)                                # the terminating window's last 1m bar -> B
    d.bar(H + M, 97.0, 110.0, 80.0, 95.0)                            # far beyond A's MFE and MAE
    d.regime_bar(H + TF)
    d.bar(H + TF + M, 95.0, 120.0, 70.0, 90.0)
    d.regime_bar(H + 2 * TF)
    assert d.snap.snapshot() == frozen
    assert d.sib.highest_high == 120.0 and d.sib.lowest_low == 70.0  # the current regime did move


def test_successive_replacement_is_whole_and_exactly_once():
    d, _ = _two_regimes()
    H = S0 + 3 * TF
    d.bar(H, 99.25, 99.5, 96.5, 97.0)
    d.regime_bar(H + TF)
    d.bar(H + TF + M, 97.0, 98.0, 94.0, 95.5)
    seq_before = d.snap.rotation_seq
    d.regime_bar(H + 2 * TF, change=(1, 95.5, 96.0, 3.0))              # B completes
    assert d.snap.rotation_seq == seq_before + 1
    assert d.snap.snapshot() == {
        "dir": -1, "start_ns": H, "end_ns": H + 2 * TF, "start_price": 99.25,
        "end_price": 95.5, "end_price_ts": H + TF + M, "transition_close": 96.0,
        "frozen_atr": 2.5, "duration_s": 600.0, "bars": 1,
        "mfe_price": 94.0, "mae_price": 99.5,                          # dir -1: MFE is the low
        "mfe_atr": (99.25 - 94.0) / 2.5, "mae_atr": (99.5 - 99.25) / 2.5,
        "terminal_displacement_atr": -1 * (95.5 - 99.25) / 2.5,
        "regime_seq": 2, "frozen_at_ns": H + 2 * TF, "rotation_seq": 2,
    }
    # nothing of A survives in the new snapshot
    assert d.snap.start_ns != A_EXPECTED["start_ns"] and d.snap.frozen_atr != A_EXPECTED["frozen_atr"]


def test_unwarmed_atr_nulls_the_ratios_never_zero_and_keeps_raw_prices():
    d = _Driver()
    d.regime_bar(S0, change=(1, 100.0, 100.5, 0.0))                  # established before ATR warmup
    d.bar(S0, 100.0, 101.0, 99.5, 100.5)
    d.regime_bar(S0 + TF, change=(-1, 100.5, 99.0, 1.5))
    s = d.snap
    assert (s.frozen_atr, s.mfe_atr, s.mae_atr, s.terminal_displacement_atr) == (None, None, None, None)
    assert (d.sib.frozen_atr, ) == (1.5, )                           # (the sibling reports 0.0 ratios while unwarmed)
    assert (s.mfe_price, s.mae_price, s.start_price, s.end_price) == (101.0, 99.5, 100.0, 100.5)


def test_a_regime_no_source_bar_reached_has_no_end_price():
    d = _Driver()
    d.bar(S0 - M, 99.0, 99.5, 98.5, 99.25)                           # before regime A: must not become its end
    d.regime_bar(S0, change=(1, 100.0, 100.5, 2.0))
    d.regime_bar(S0 + TF, change=(-1, 100.5, 99.0, 2.0))             # gap: no 1m bar during A
    s = d.snap
    assert (s.end_price, s.end_price_ts, s.terminal_displacement_atr) == (None, None, None)
    assert (s.mfe_price, s.mae_price, s.mfe_atr, s.mae_atr) == (100.0, 100.0, 0.0, 0.0)   # seeded with the start price


# =========================================================================== end-to-end layer
T0 = 1_893_456_000 * NS            # 2030-01-01T00:00Z
DAYS = 2
TD_ROWS = [(T0, T0 + 30 * 3600 * NS), (T0 + 32 * 3600 * NS, T0 + DAYS * 86400 * NS + 3600 * NS)]   # a 2h closure at 30h


def _tape(*, gaps: bool) -> Tuple[List[BarView], List[BarView]]:
    """Deterministic 1m tape (three sinusoids + LCG noise, 0.25 tick) and a sparse 1s tape inside it
    (seconds 15/30/45/60 of every minute; the 1m bar is their aggregate). ``gaps`` removes a 47-minute
    hole inside a trading day (zero-volume fill territory) and the whole 2h closure."""
    seed = 12345
    px = 1000.0
    ones: List[BarView] = []
    mins: List[BarView] = []
    for i in range(DAYS * 1440):
        t_open = T0 + i * M
        if gaps and (1500 <= i < 1547 or 30 * 60 <= i < 32 * 60):
            continue
        target = 1000 + 25 * math.sin(2 * math.pi * i / 47) + 50 * math.sin(2 * math.pi * i / 181) + 110 * math.sin(2 * math.pi * i / 613)
        o = px
        hs: List[float] = []
        ls: List[float] = []
        for k in range(4):
            seed = (1103515245 * seed + 12345) % (2 ** 31)
            noise = (seed / 2 ** 31 - 0.5) * 3.0
            step_to = o + (target - o) * (k + 1) / 4 + noise
            c = round(step_to * 4) / 4
            seed = (1103515245 * seed + 12345) % (2 ** 31)
            wick = round((seed / 2 ** 31) * 4) / 4
            prev = o if k == 0 else ones[-1].close
            h, l = max(prev, c) + wick, min(prev, c) - wick
            ones.append(BarView("1s", t_open + (15 * (k + 1) - 1) * NS, t_open + 15 * (k + 1) * NS, prev, h, l, c, 1.0))
            hs.append(h)
            ls.append(l)
        mins.append(BarView("1m", t_open, t_open + M, o, max(hs), min(ls), ones[-1].close, 4.0))
        px = ones[-1].close
    return ones, mins


def _spec(*, with_prior: bool = True) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "regime_1m": {"tracker": "regime.dual_ema", "timeframe": "1m"},
        "regime_5m": {"tracker": "regime.dual_ema", "timeframe": "5m"},
        "regime_15m": {"tracker": "regime.dual_ema", "timeframe": "15m"},
        "regime_1h": {"tracker": "regime.dual_ema", "timeframe": "1h"},
        "excursion_5m": {"tracker": "regime.excursion", "bars": "1m", "regime": "regime_5m"},
        "excursion_15m": {"tracker": "regime.excursion", "bars": "1m", "regime": "regime_15m"},
        "excursion_1h": {"tracker": "regime.excursion", "bars": "1m", "regime": "regime_1h"},
    }
    meta: Dict[str, str] = {}
    for tf in ("5m", "15m", "1h"):
        meta.update({f"dir_{tf}": f"regime_{tf}.dir", f"start_ns_{tf}": f"regime_{tf}.start_ns",
                     f"start_price_{tf}": f"regime_{tf}.start_price", f"bars_{tf}": f"regime_{tf}.bars_in_regime",
                     f"atr_{tf}": f"regime_{tf}.atr", f"frozen_atr_{tf}": f"excursion_{tf}.frozen_atr",
                     f"hh_{tf}": f"excursion_{tf}.highest_high", f"ll_{tf}": f"excursion_{tf}.lowest_low",
                     f"mfe_atr_{tf}": f"excursion_{tf}.mfe_atr", f"mae_atr_{tf}": f"excursion_{tf}.mae_atr",
                     f"changed_seq_{tf}": f"regime_{tf}.changed_seq"})
    if with_prior:
        for tf in ("5m", "15m", "1h"):
            ctx[f"prior_{tf}"] = {"tracker": "regime.prior_level_snapshot", "bars": "1m", "regime": f"regime_{tf}"}
            for f in RegimePriorLevelSnapshotBinding.FIELDS:
                meta[f"prior_{f}_{tf}"] = f"prior_{tf}.{f}"
        ctx["prior_5m_own"] = {"tracker": "regime.prior_level_snapshot", "bars": "5m", "regime": "regime_5m"}
        ctx["geometry_5m"] = {"tracker": "test.completed_geometry", "regime": "regime_5m"}
    return {
        "study": {"id": "prls_e2e", "tier": 2, "question": "prior_level_snapshot end-to-end"},
        "streams": [{"dataset": "SYN_A", "timeframes": ["1s", "1m", "5m", "15m", "1h"]}],
        "context": ctx,
        "population": {"session": "RTH", "cadence": {"every": "15s", "anchor": "regime_1m.start_ns", "max_age": "300s"},
                       "direction": "regime_1m.dir", "anchor_identity": "regime_1m.start_ns"},
        "triggers": "every_candidate",
        "features": {"host": "synthetic", "metadata": meta},
        "outcome": {"kind": "label", "event": "regime_1m.flipped", "horizon": "60s", "direction": "regime_1m.dir",
                    "session_end": "censor"},
        "chronology": {"train": [2030], "dev": [], "prohibited": []},
        "model": "none",
    }


class _CompletedGeometryBinding(BaseBinding):
    """TEST-ONLY: feeds the production regime-geometry adapter's provider exactly as
    ``research_workflow.provider_host`` does (``on_completed_bar`` per ``regime_bar`` with direction and
    positive ATR), so its ``_prior`` can be compared field by field."""
    CAPABILITY = "tracker.test.completed_geometry"
    PARAMS: Dict[str, Any] = {}
    INPUTS = {"regime": "tracker"}
    FIELDS = ()
    SUBSCRIBES = ("regime_bar",)

    def __init__(self, params, inputs):
        super().__init__(params, inputs)
        from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider
        self.provider = GenericCompletedRegimeGeometryProvider()
        self.priors: List[dict] = []

    def on_event(self, input_key, event):
        p = event.payload
        d, atr = int(p.get("direction") or 0), float(p.get("atr") or 0.0)
        if d not in (-1, 1) or not math.isfinite(atr) or atr <= 0.0:
            return
        before = self.provider._prior.get("5m")
        self.provider.on_completed_bar(timeframe="5m", close_ts=int(p["close_ts"]), direction=d, open_=float(p["open"]),
                                       high=float(p["high"]), low=float(p["low"]), close=float(p["close"]), atr=atr)
        after = self.provider._prior.get("5m")
        if after is not None and after is not before:
            self.priors.append(dict(after))


def _registry() -> Dict[str, Any]:
    """The real registry; while the capability is still a scaffold candidate (its own promotion runs this
    file) the copy marks it verified so the runtime semantics can be exercised before promotion."""
    from research_workflow.capabilities import load_registry
    reg = copy.deepcopy(load_registry())
    for e in reg.get("kinds", {}).get("trackers", []):
        if e.get("id") == CAP and e.get("status") == "candidate":
            e["status"] = "verified"
    return reg


def _compile(tmp: Path, body: Dict[str, Any]):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    ds = tmp / "datasets"
    if not ds.exists():
        ds.mkdir(parents=True)
        for p in (GOLDEN / "datasets").glob("*.yaml"):
            shutil.copy2(p, ds / p.name)
        a = yaml.safe_load((ds / "SYN_A.yaml").read_text(encoding="utf-8"))
        a["reference_tables"] = ["sessions"]                            # a calendar dataset: closed-window fill on
        a["coverage"] = {"start": "2030-01-01T00:00:00Z", "end": "2030-01-03T01:00:00Z"}
        (ds / "SYN_A.yaml").write_text(yaml.safe_dump(a, sort_keys=False), encoding="utf-8")
    study = tmp / "studies" / body["study"]["id"]
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, registry=_registry(), datasets_dir=ds,
                        extra_bindings={**SYNTHETIC_BINDINGS, "tracker.test.completed_geometry": _CompletedGeometryBinding})
    assert out.ok, out.card()
    return out.plan.to_dict()


def _session():
    from research_workflow.sessions import TRADING_DAY, build_session_table
    return build_session_table({"kind": "calendar", "session": "RTH", "rows": TD_ROWS, "rows_by_session": {"RTH": TD_ROWS, TRADING_DAY: TD_ROWS}})


def _run(plan: Dict[str, Any], *, gaps: bool):
    """Replays the tape through HostCore; after every ingest records each prior tracker's snapshot and each
    sibling excursion's state (the state after ingest k-1 is the state immediately before a reset in k)."""
    from research_workflow.host.strategy import HostCore
    from research_workflow.host_runner import sort_bars_causal
    keys = {s["timeframe"]: s["key"] for s in plan["streams"]}
    ones, mins = _tape(gaps=gaps)
    rekey = lambda k, b: BarView(k, b.ts_event, b.ts_init, b.open, b.high, b.low, b.close, b.volume)
    bars = [rekey(keys["1s"], b) for b in ones] + [rekey(keys["1m"], b) for b in mins]
    core = HostCore(plan, session_table=_session())
    trail: List[Tuple[int, Dict[str, dict], Dict[str, dict]]] = []
    for bar in sort_bars_causal(bars, {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}):
        core.ingest(bar)
        snaps = {tid: core.trackers[tid].snapshot() for tid in core.trackers if tid.startswith("prior_")}
        excs = {}
        for tf in ("5m", "15m", "1h"):
            e = core.trackers[f"excursion_{tf}"]
            excs[tf] = {"dir": e.dir, "start_price": e.start_price, "frozen_atr": e.frozen_atr, "hh": e.highest_high,
                        "ll": e.lowest_low, "last_close": e.last_close, "last_ts": e.last_ts, "mfe_atr": e.mfe_atr,
                        "mae_atr": e.mae_atr, "pnl_atr": e.pnl_atr}
        trail.append((bar.ts_init, snaps, excs))
    candidates, _obs = core.finalize()
    return {"core": core, "trail": trail, "candidates": candidates, "mins": mins}


# --------------------------------------------------------------------------- the test-only oracle
def _oracle(mins: List[BarView], tf_ns: int) -> List[Dict[str, Any]]:
    """Every completed regime of the ``tf_ns`` dual-EMA regime, rebuilt from the raw 1m tape.

    Windows: 1m bars keyed by ``ts_event // tf_ns``; an empty window between two published windows is a
    zero-volume bar at the previous close iff it overlaps a trading-day row. Regime k is established by the
    window closing at S (open O, ATR at that window) and terminated by the window closing at H. Its bar set
    is the 1m bars with S <= ts_init < H (the mux publishes a closed window before the source bar that
    closed it, so the terminating window's last 1m bar is the successor's)."""
    from features.trackers.regime_dual_ema import DualEmaRegimeTracker
    groups: Dict[int, List[BarView]] = {}
    for b in mins:
        groups.setdefault(b.ts_event // tf_ns, []).append(b)
    ids = sorted(groups)
    windows: List[Tuple[int, float, float, float, float]] = []
    last_close = None
    for j, k in enumerate(ids):
        if j:
            for e in range(ids[j - 1] + 1, k):
                o, c = e * tf_ns, (e + 1) * tf_ns
                if any(ro < c and o < rc for ro, rc in TD_ROWS):
                    windows.append((c, last_close, last_close, last_close, last_close))
        g = groups[k]
        windows.append(((k + 1) * tf_ns, g[0].open, max(x.high for x in g), min(x.low for x in g), g[-1].close))
        last_close = g[-1].close
    eng = DualEmaRegimeTracker()
    regimes: List[Dict[str, Any]] = []
    cur = None
    seq = 0
    bars_in = 0
    out: List[Dict[str, Any]] = []
    for close_ts, o, h, l, c in windows:
        u = eng.observe(h, l, c)
        changed = u.regime != u.previous_regime and u.regime != 0
        if changed:
            seq += 1
            if cur is not None:
                out.append(_oracle_complete(cur, mins, close_ts, c, bars_in))
            atr = float(u.atr) if u.atr is not None else 0.0
            cur = {"dir": u.regime, "S": close_ts, "O": o, "atr": atr if atr > 0 else 0.0, "seq": seq}
            bars_in = 0
        else:
            bars_in += 1
    return out


def _oracle_complete(r: Dict[str, Any], mins: List[BarView], H: int, transition_close: float, bars_in: int) -> Dict[str, Any]:
    own = [b for b in mins if r["S"] <= b.ts_init < H]
    hh = max([r["O"]] + [b.high for b in own])
    ll = min([r["O"]] + [b.low for b in own])
    d, O, atr = r["dir"], r["O"], r["atr"]
    end = own[-1].close if own else None
    ok = atr > 0
    mfe = (max(0.0, hh - O) if d == 1 else max(0.0, O - ll)) / atr if ok else None
    mae = (max(0.0, O - ll) if d == 1 else max(0.0, hh - O)) / atr if ok else None
    return {"dir": d, "start_ns": r["S"], "end_ns": H, "start_price": O, "end_price": end,
            "end_price_ts": own[-1].ts_init if own else None, "transition_close": transition_close,
            "frozen_atr": atr if ok else None, "duration_s": (H - r["S"]) / NS, "bars": bars_in,
            "mfe_price": hh if d == 1 else ll, "mae_price": ll if d == 1 else hh, "mfe_atr": mfe, "mae_atr": mae,
            "terminal_displacement_atr": (d * (end - O)) / atr if (ok and end is not None) else None,
            "regime_seq": r["seq"], "frozen_at_ns": H}


def _expected_at(oracle: List[Dict[str, Any]], T: int) -> Dict[str, Any]:
    done = [s for s in oracle if s["frozen_at_ns"] <= T]
    if not done:
        return {**{f: None for f in SNAPSHOT_FIELDS}, "rotation_seq": 0}
    return {**done[-1], "rotation_seq": len(done)}


TFS = {"5m": 5 * M, "15m": 15 * M, "1h": 60 * M}


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prls")
    plan = _compile(tmp, _spec())
    base_plan = _compile(tmp / "base", _spec(with_prior=False))
    runs = {g: _run(plan, gaps=g) for g in (False, True)}
    return {"plan": plan, "base_plan": base_plan, "runs": runs, "tmp": tmp}


@pytest.mark.parametrize("gaps", [False, True])
def test_every_published_snapshot_equals_the_raw_tape_oracle_at_every_instant(e2e, gaps):
    """Price parity (6), availability clock (5), timestamp/price boundary (8), successive replacement (4)."""
    run = e2e["runs"][gaps]
    for tf, tf_ns in TFS.items():
        oracle = _oracle(run["mins"], tf_ns)
        assert len(oracle) >= {"5m": 20, "15m": 8, "1h": 4}[tf], (tf, len(oracle))   # the tape really rotates every timeframe
        for ts, snaps, _ in run["trail"]:
            assert snaps[f"prior_{tf}"] == _expected_at(oracle, ts), (tf, ts)


def test_invariants_hold_on_every_completed_regime(e2e):
    for gaps, run in e2e["runs"].items():
        for tf, tf_ns in TFS.items():
            for s in _oracle(run["mins"], tf_ns):
                if s["end_price"] is not None:
                    lo, hi = sorted((s["mfe_price"], s["mae_price"]))
                    assert lo <= s["end_price"] <= hi
                    assert s["end_price_ts"] < s["end_ns"]
                if s["frozen_atr"] is not None and s["terminal_displacement_atr"] is not None:
                    assert -s["mae_atr"] <= s["terminal_displacement_atr"] <= s["mfe_atr"]
                assert s["start_ns"] < s["end_ns"]
                if not gaps:
                    assert s["duration_s"] == (s["bars"] + 1) * tf_ns / NS     # no gap: establishing + survived bars


def test_snapshot_equals_the_sibling_canonical_excursion_immediately_before_its_reset(e2e):
    """ATR parity (7) and raw-extreme parity (5) against the separately bound regime.excursion, bit for bit."""
    checked = 0
    for run in e2e["runs"].values():
        trail = run["trail"]
        for tf in TFS:
            for k in range(1, len(trail)):
                before, after = trail[k - 1][1][f"prior_{tf}"], trail[k][1][f"prior_{tf}"]
                if after["rotation_seq"] == before["rotation_seq"]:
                    assert after == before                                  # immutability between rotations (3)
                    continue
                assert after["rotation_seq"] == before["rotation_seq"] + 1  # replaced exactly once (4)
                pre = trail[k - 1][2][tf]
                assert after["dir"] == pre["dir"] and after["start_price"] == pre["start_price"]
                assert after["frozen_atr"] == (pre["frozen_atr"] if pre["frozen_atr"] > 0 else None)
                assert (after["end_price"], after["end_price_ts"]) == (pre["last_close"], pre["last_ts"])
                assert after["mfe_price"] == (pre["hh"] if pre["dir"] == 1 else pre["ll"])
                assert after["mae_price"] == (pre["ll"] if pre["dir"] == 1 else pre["hh"])
                if pre["frozen_atr"] > 0:
                    assert (after["mfe_atr"], after["mae_atr"], after["terminal_displacement_atr"]) == (pre["mfe_atr"], pre["mae_atr"], pre["pnl_atr"])
                now = trail[k][2][tf]
                assert now["dir"] == -after["dir"]                           # direction parity: completed, not successor
                checked += 1
    assert checked > 60, checked


def test_timeframes_rotate_independently(e2e):
    """(9) a rotation of one timeframe never touches another timeframe's snapshot."""
    trail = e2e["runs"][False]["trail"]
    solo = 0
    for k in range(1, len(trail)):
        moved = {tf for tf in TFS if trail[k][1][f"prior_{tf}"] != trail[k - 1][1][f"prior_{tf}"]}
        for tf in TFS:
            if tf not in moved:
                assert trail[k][1][f"prior_{tf}"] == trail[k - 1][1][f"prior_{tf}"]
        solo += len(moved) == 1
    assert solo > 20
    core = e2e["runs"][False]["core"]
    assert len({id(core.trackers[f"prior_{tf}"]) for tf in TFS}) == 3


def test_replay_is_bit_identical(e2e):
    """(10) two replays of the same event stream produce identical snapshot sequences (repr-level, so -0.0/0.0
    and int/float would differ)."""
    again = _run(e2e["plan"], gaps=True)
    digest = lambda run: hashlib.sha256(repr([(ts, sorted(s.items())) for ts, s, _ in run["trail"]]).encode()).hexdigest()
    assert digest(again) == digest(e2e["runs"][True])


def test_subsequent_1m_flip_checkpoints_read_the_frozen_snapshots_through_features_metadata(e2e):
    """Request test 10: the compiled plan's metadata columns carry the snapshot at every 1m-flip checkpoint,
    equal to the oracle's snapshot as of the checkpoint T -- including checkpoints inside a terminating HTF
    window, which must still read the older snapshot."""
    import pandas as pd
    cand = e2e["runs"][True]["candidates"]
    mins = e2e["runs"][True]["mins"]
    assert len(cand) > 500
    inside = 0
    for tf, tf_ns in TFS.items():
        oracle = _oracle(mins, tf_ns)
        ends = [s["end_ns"] for s in oracle]
        for _, row in cand.iterrows():
            T = int(row["observation_ts"])
            exp = _expected_at(oracle, T)
            for f in RegimePriorLevelSnapshotBinding.FIELDS:
                got = row[f"prior_{f}_{tf}"]
                want = exp[f]
                if want is None:
                    assert got is None or (isinstance(got, float) and math.isnan(got)), (tf, f, T, got)
                elif f in ("start_ns", "end_ns", "end_price_ts", "frozen_at_ns"):
                    assert int(got) == want, (tf, f, T, got, want)          # ns precision survives the sink
                else:
                    assert got == want, (tf, f, T, got, want)
            inside += any(H - tf_ns < T < H for H in ends)
    assert inside > 50


def test_observing_the_snapshot_changes_no_existing_regime_or_excursion_value(e2e, tmp_path):
    """Non-regression: the same tape with and without the prior trackers gives identical current-regime
    direction, start state, frozen ATR, excursion extremes and transition timing at every checkpoint."""
    import pandas as pd
    base = _run(e2e["base_plan"], gaps=True)["candidates"]
    full = e2e["runs"][True]["candidates"]
    shared = [c for c in base.columns if c in full.columns]
    assert len(shared) > 30 and len(base) == len(full)
    pd.testing.assert_frame_equal(base[shared].reset_index(drop=True), full[shared].reset_index(drop=True), check_exact=True)


def test_overlap_with_the_completed_regime_geometry_provider(e2e):
    """GenericCompletedRegimeGeometryProvider keeps its own ``_prior`` from completed 5m regime bars. Bound to
    the SAME stream (``bars: 5m``) every overlapping field agrees exactly; bound to 1m the extremes and end
    close differ only because the bar SET differs (1m constituents vs whole 5m bars) -- asserted, not blessed."""
    core = e2e["runs"][False]["core"]
    priors = core.trackers["geometry_5m"].priors
    own = e2e["runs"][False]["trail"]
    seen = {}
    for _, snaps, _ in own:
        s = snaps["prior_5m_own"]
        if s["rotation_seq"]:
            seen[s["end_ns"]] = s
    assert len(priors) > 20
    compared = 0
    for p in priors:
        s = seen.get(p["end_ns"])
        if s is None or s["start_ns"] != p["start_ns"]:
            continue       # the provider skips unwarmed bars, so its first regime starts later; no overlap there
        assert (s["dir"], s["start_price"], s["frozen_atr"]) == (p["direction"], p["start_price"], p["atr_start"])
        assert (s["mfe_price"], s["mae_price"]) == ((p["high"], p["low"]) if p["direction"] == 1 else (p["low"], p["high"]))
        assert s["end_price"] == p["end_close"]
        compared += 1
    assert compared >= len(priors) - 1


# =========================================================================== parity artifact
def build_parity_artifact(tmp: Path) -> Dict[str, Any]:
    plan = _compile(tmp, _spec())
    out: Dict[str, Any] = {"capability": CAP, "fixture": "synthetic 2-day 1s/1m tape (features/tests/test_regime_prior_level_snapshot.py::_tape)",
                           "oracle": "test-only raw-1m-tape rebuild (_oracle): own window aggregation + zero-volume fill; dual-EMA engine for direction only",
                           "runtime_path": "compile_study -> HostCore -> StreamMux(closed_window, zero_volume_in_trading_day)", "scenarios": {}}
    passed = True
    for gaps in (False, True):
        run = _run(plan, gaps=gaps)
        sc: Dict[str, Any] = {}
        for tf, tf_ns in TFS.items():
            oracle = _oracle(run["mins"], tf_ns)
            mism = sum(1 for ts, snaps, _ in run["trail"] if snaps[f"prior_{tf}"] != _expected_at(oracle, ts))
            sc[tf] = {"completed_regimes": len(oracle), "instants_checked": len(run["trail"]), "mismatches": mism,
                      "null_end_price": sum(1 for s in oracle if s["end_price"] is None),
                      "null_atr": sum(1 for s in oracle if s["frozen_atr"] is None)}
            passed &= mism == 0
        sc["replay_sha256"] = hashlib.sha256(repr([(ts, sorted(s.items())) for ts, s, _ in run["trail"]]).encode()).hexdigest()
        sc["empty_windows_published"] = run["core"].mux.empty_windows_published()
        out["scenarios"]["gaps" if gaps else "no_gaps"] = sc
    out["passed"] = bool(passed)
    return out


if __name__ == "__main__":
    import tempfile
    if len(sys.argv) == 3 and sys.argv[1] == "--write-parity":
        with tempfile.TemporaryDirectory() as d:
            art = build_parity_artifact(Path(d))
        Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)
        Path(sys.argv[2]).write_text(json.dumps(art, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"passed": art["passed"], "path": sys.argv[2]}))
        sys.exit(0 if art["passed"] else 1)
    sys.exit("usage: python -m features.tests.test_regime_prior_level_snapshot --write-parity <json>")
