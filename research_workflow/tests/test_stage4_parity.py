"""Stage 4 formal parity audits.

FLAG A -- the population runtime's EpisodePopulationEngine arm and the canonical
GenericEpisodeGeometryProvider arm are the SAME event on the same stream.

FLAG B -- the ProviderHost Family-A inputs are byte/value identical to the frozen
Model-C parent's compact runtime feature path on the same deterministic stream.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
DEEP = REPO / "studies" / "deep_pullback_5s_reacceleration_model"
PARENT = REPO / "studies" / "clean_maturity_flip_model_rolling_productivity"
NS = 1_000_000_000


# =========================================================================== #
# FLAG A
# =========================================================================== #
def _episode_runtime():
    from research_workflow.population_runtime import resolve_population_runtime
    el = json.loads((DEEP / "compiled_study.json").read_text())["contracts"]["population_contract"]["episode_lifecycle"]
    return resolve_population_runtime({"episode_lifecycle": el})


def _drive(rt, prevailing, start_price, price_fn, *, atr_fn, seconds, start_ns=100 * NS):
    rt.on_prevailing_regime(direction=prevailing, start_ns=start_ns, start_price=start_price)
    checks = []
    for sec in range(seconds):
        p0, p1 = price_fn(sec), price_fn(sec + 1)
        hi, lo = max(p0, p1) + 0.05, min(p0, p1) - 0.05
        rt.on_completed_1s(ts_event=(sec) * NS, ts_init=(sec + 1) * NS, open=p0, high=hi, low=lo,
                           close=p1, volume=10.0, completed_1m_atr=atr_fn(sec))
        geom_ep = rt._geom._episode
        checks.append({
            "ts": (sec + 1) * NS,
            "engine_arm_ts": rt._arm_ts,
            "geom_arm_ts": (geom_ep.arm_ts if geom_ep is not None else None),
            "engine_pb_start": rt._pullback_start_ts,
            "geom_pb_start": (geom_ep.start_ns if (geom_ep is not None and geom_ep.arm_ts is not None) else None),
            "engine_frozen_atr": rt._frozen_atr_arm,
            "geom_arm_atr": (geom_ep.arm_atr if geom_ep is not None else None),
        })
    return checks


@pytest.mark.parametrize("prevailing", [1, -1])
def test_flag_a_engine_and_geometry_arm_are_the_same_event(prevailing):
    rt = _episode_runtime()

    def price(sec):
        # rise 60s, then a pullback whose depth crosses 1.0 ATR mid-way
        base = 20000.0
        if sec <= 60:
            return base + prevailing * 0.5 * sec
        if sec <= 110:
            return base + prevailing * (30.0 - 0.6 * (sec - 60))   # ~ -30 pts over 50s
        return base + prevailing * (0.0 + 0.5 * (sec - 110))

    checks = _drive(rt, prevailing, price(0), price, atr_fn=lambda s: 10.0, seconds=140)
    armed = [c for c in checks if c["engine_arm_ts"] is not None]
    assert armed, "the engine never armed on this stream"
    first = armed[0]
    # arm event coincides -- no one-bar / one-event offset
    assert first["engine_arm_ts"] == first["geom_arm_ts"]
    assert first["engine_pb_start"] == first["geom_pb_start"]
    assert first["engine_frozen_atr"] == pytest.approx(first["geom_arm_atr"])
    # and stays coincident for every later bar of the arming cycle
    for c in armed:
        assert c["engine_arm_ts"] == c["geom_arm_ts"]
        assert c["engine_frozen_atr"] == pytest.approx(c["geom_arm_atr"])


def test_flag_a_boundary_just_below_at_and_just_above_one_atr():
    # a pullback that bottoms at exactly ~1.0 ATR: engine and geometry agree on whether
    # (and when) it arms at every boundary.
    for depth_atr, expect_arm in ((0.98, False), (1.00, True), (1.05, True)):
        rt = _episode_runtime()
        peak = 20100.0

        def price(sec, _d=depth_atr):
            if sec <= 40:
                return 20000.0 + 2.5 * sec            # -> 20100 peak
            if sec <= 60:
                return peak - (_d * 10.0) * (sec - 40) / 20.0   # linear to depth
            return peak - (_d * 10.0) + 0.5 * (sec - 60)

        checks = _drive(rt, 1, price(0), price, atr_fn=lambda s: 10.0, seconds=90)
        engine_armed = any(c["engine_arm_ts"] is not None for c in checks)
        geom_armed = any(c["geom_arm_ts"] is not None for c in checks)
        assert engine_armed == geom_armed == expect_arm, (depth_atr, engine_armed, geom_armed)
        if expect_arm:
            a = next(c for c in checks if c["engine_arm_ts"] is not None)
            assert a["engine_arm_ts"] == a["geom_arm_ts"]


def test_flag_a_atr_change_after_arm_does_not_desync_frozen_atr():
    rt = _episode_runtime()

    def price(sec):
        if sec <= 40:
            return 20000.0 + 2.5 * sec
        if sec <= 60:
            return 20100.0 - 1.2 * (sec - 40)   # ~24 pt pullback @ ATR 10 -> arms
        return 20076.0 + 0.6 * (sec - 60)

    def atr_fn(sec):
        return 10.0 if sec <= 60 else 30.0     # ATR jumps right after the arm window

    checks = _drive(rt, 1, price(0), price, atr_fn=atr_fn, seconds=100)
    a = next(c for c in checks if c["engine_arm_ts"] is not None)
    assert a["engine_frozen_atr"] == pytest.approx(10.0)
    assert a["geom_arm_atr"] == pytest.approx(10.0)
    # unchanged for the rest of the cycle despite ATR = 30
    for c in checks:
        if c["engine_frozen_atr"] is not None:
            assert c["engine_frozen_atr"] == pytest.approx(10.0)
            assert c["geom_arm_atr"] == pytest.approx(10.0)


def test_flag_a_rearm_cycle_restarts_both_from_the_same_bar():
    rt = _episode_runtime()

    def price(sec):
        if sec <= 40:
            return 20000.0 + 2.5 * sec               # -> 20100
        if sec <= 60:
            return 20100.0 - 1.2 * (sec - 40)         # arm cycle 1
        if sec <= 120:
            return 20076.0 + 0.6 * (sec - 60)         # recover ABOVE 20100 -> new extreme
        if sec <= 145:
            return 20112.0 - 1.2 * (sec - 120)        # arm cycle 2
        return 20082.0 + 0.6 * (sec - 145)

    checks = _drive(rt, 1, price(0), price, atr_fn=lambda s: 10.0, seconds=180)
    arm_ts_seen = sorted({c["engine_arm_ts"] for c in checks if c["engine_arm_ts"] is not None})
    assert len(arm_ts_seen) == 2, f"expected two distinct arming cycles, got {arm_ts_seen}"
    for c in checks:
        if c["engine_arm_ts"] is not None:
            assert c["engine_arm_ts"] == c["geom_arm_ts"]
            assert c["engine_pb_start"] == c["geom_pb_start"]


# =========================================================================== #
# FLAG B
# =========================================================================== #
def _parent_compact_collector():
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study
    from backtests.nt_runtime.data_plan import resolve_data_plan
    from backtests.nt_runtime.run_plan import resolve_run_plan
    from backtests.nt_runtime.strategy_binding import resolve_strategy_binding
    from backtests.nt_runtime.modes.collect import build_collector_config_kwargs
    from research_workflow.phase0 import build_phase0_manifest
    sd = load_compiled_study(PARENT)
    build_phase0_manifest(sd.study_dir)
    # The parent authorizes 2023-10-02; only used here to build the config for a
    # synthetic-bar parity comparison, not a real run.
    rp = resolve_run_plan(sd, stage="day", reference_date="2023-10-02")
    dp = resolve_data_plan(sd, start_date=rp.start_date, end_date=rp.end_date)
    b = resolve_strategy_binding(sd.spec.execution.strategy_class, study_type=sd.spec.study.type, mode="collect")
    ck = build_collector_config_kwargs(b, sd.spec, sd, dp)
    ck["established_required"] = False  # every checkpoint emits -> a dense parity sample
    coll = b.strategy_cls(b.config_cls(**ck))
    return coll, sd


class _Bar:
    __slots__ = ("bar_type", "ts_event", "ts_init", "open", "high", "low", "close", "volume")

    def __init__(self, bt, te, ti, o, h, l, c, v):
        self.bar_type, self.ts_event, self.ts_init = bt, te, ti
        self.open, self.high, self.low, self.close, self.volume = o, h, l, c, v


def _b_price(sec: int) -> float:
    if sec <= 3600:
        return 20000.0 + 0.08 * sec
    if sec <= 4200:
        return 20288.0 - 0.18 * (sec - 3600)
    return 20180.0 + 0.10 * (sec - 4200)


def test_flag_b_family_a_runtime_parity_with_frozen_model_c_parent():
    from research_workflow.provider_host import (
        ProviderHost, STREAM_COMPLETED_1S, STREAM_COMPLETED_1M, STREAM_COMPLETED_5M,
        EVENT_REGIME_TRANSITION_1M,
    )
    from research_workflow.completed_regime_state import CompletedRegimeStateFeed

    coll, sd = _parent_compact_collector()
    surface = list(json.loads((PARENT / "compiled_study.json").read_text())["contracts"]["feature_contract"]["feature_list"])
    assert len(surface) == 13
    host = ProviderHost.from_feature_contract({"contracts": {"feature_contract":
        json.loads((PARENT / "compiled_study.json").read_text())["contracts"]["feature_contract"]}})
    feed = CompletedRegimeStateFeed(["5m"])

    bt1s, bt1m = coll._bar_type_1s, coll._bar_type_1m
    t0 = pd.Timestamp("2023-10-02 09:00:00", tz="America/Chicago").value

    def dispatch_host_regime_transition():
        # mirror what the episode collector does at a 1m flip
        pass

    prev_regime = 0
    compared, mismatches = 0, []
    for sec in range(0, 120 * 60):
        p0, p1 = _b_price(sec), _b_price(sec + 1)
        hi, lo = max(p0, p1) + 0.3, min(p0, p1) - 0.3
        te = t0 + sec * NS
        n_before = len(coll.candidates_log)
        coll.on_bar(_Bar(bt1s, te, te + NS, p0, hi, lo, p1, 20.0))
        host.dispatch(STREAM_COMPLETED_1S, {"ts_init": te + NS, "open": p0, "high": hi, "low": lo,
                                            "close": p1, "volume": 20.0})
        for tr in feed.on_completed_1s_bar(ts_event=te, ts_init=te + NS, open=p0, high=hi, low=lo,
                                           close=p1, volume=20.0):
            s = tr.current
            if int(s.regime) in (-1, 1) and s.atr is not None and s.atr == s.atr and s.atr > 0:
                host.dispatch(STREAM_COMPLETED_5M, {"close_ts": int(s.close_ts), "available_ts": te + NS,
                                                    "direction": int(s.regime), "open": float(s.open),
                                                    "high": float(s.high), "low": float(s.low),
                                                    "close": float(s.close), "atr": float(s.atr)})

        # a parent checkpoint row was just emitted at this exact 1s ts -> snapshot the
        # ProviderHost NOW (same T, same completed state) and compare Family A row-by-row
        for pr in coll.candidates_log[n_before:]:
            T = int(pr["observation_ts"])
            regime_frozen_atr = float(coll.regime_frozen_atr)
            hs = host.snapshot(decision_ts=T, price=_b_price((T - t0) // NS), atr=regime_frozen_atr,
                               episode_state={"prevailing_direction": int(coll.active_regime_dir)},
                               family_a_atr=regime_frozen_atr)
            compared += 1
            for name in surface:
                a, b = pr.get(name), hs.get(name)
                if a is None and b is None:
                    continue
                if a is None or b is None or abs(float(a) - float(b)) > 1e-9:
                    mismatches.append((sec, name, a, b))

        if (sec + 1) % 60 == 0:
            ps = [_b_price(x) for x in range(sec + 1 - 60, sec + 2)]
            mte = t0 + (sec + 1 - 60) * NS
            coll.on_bar(_Bar(bt1m, mte, mte + 60 * NS, ps[0], max(ps), min(ps), ps[-1], 1200.0))
            new_regime = coll.regime_engine.regime
            atrv = coll.regime_engine.atr or 0.0
            host.dispatch(STREAM_COMPLETED_1M, {"ts_init": mte + 60 * NS, "close_ts": mte + 60 * NS,
                                                "direction": int(new_regime), "open": ps[0], "high": max(ps),
                                                "low": min(ps), "close": ps[-1], "volume": 0.0, "atr": atrv})
            if new_regime != prev_regime and new_regime != 0 and atrv > 0:
                host.dispatch(EVENT_REGIME_TRANSITION_1M, {"direction": int(new_regime),
                              "start_ns": mte + 60 * NS, "start_price": ps[0], "atr_start": atrv,
                              "prior_end_close": coll.last_close or ps[-1]})
            prev_regime = new_regime

    assert coll.candidates_log, "the parent compact collector produced no checkpoint rows"
    assert compared >= 5, f"only {compared} rows comparable"
    assert not mismatches, f"Family-A parity mismatches ({len(mismatches)}): {mismatches[:10]}"

