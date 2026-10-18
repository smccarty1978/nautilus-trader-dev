"""unit: structural barrier arms -- absolute stop known at T, buffer away from the entry, tick rounding away from
the entry, R-multiple target on the EXECUTABLE entry-to-stop distance -- with independent replay-oracle parity.

Tick size is the NQ 0.25 point, declared explicitly on the arm (the kernel hardcodes no instrument).
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_workflow.host.interfaces import BarView, NS
from research_workflow.host.outcomes import (CENSORED, NEGATIVE, POSITIVE, BarrierArm, LabelOutcomeContract,
                                             LabelOutcomeKernel, STRUCTURAL_ARM_SUFFIXES)
from research_workflow.target_replay_oracle import replay as oracle_replay

T0 = 1_700_000_000 * NS            # decision epoch (bar close)
CLOSE = T0 + 6 * 3600 * NS         # session close far away unless a test says otherwise
TICK = 0.25


def _arm(rr=2.0, buf=0.25, tick=TICK, horizon_s=600, expiry="censor", aid="s"):
    # id != prefix and no primary -> the kernel emits the per-arm <prefix>_* columns this suite reads
    return BarrierArm(id=f"{aid}_arm", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=horizon_s * NS, expiry=expiry, prefix=aid,
                      unit="structural", reward_risk=rr, stop_buffer_points=buf, tick_size=tick)


def _kernel(arms, *, same_bar="adverse_first", session_close=CLOSE, session_end_rule="censor", max_gap_ns=None,
            session_cutoff=None, entry_cutoff=None, primary=None):
    c = LabelOutcomeContract(kernel="barrier", direction_ref="const:1", atr_ref=None, entry_reference="next_bar_open",
                             session_end_censoring=session_end_rule in ("censor", "truncate"), session_end_rule=session_end_rule,
                             max_gap_ns=max_gap_ns, same_bar_rule=same_bar, arms=tuple(arms),
                             primary_arm=primary, stop_ref="tracker.stop",
                             session_cutoff=session_cutoff, entry_cutoff=entry_cutoff)
    st = MagicMock()
    st.session_close.return_value = session_close
    return LabelOutcomeKernel(c, st)


def _bars(spec):
    """spec: [(seconds_after_T, open, high, low)] -> 1s bars (ts_event = ts_init - 1s)."""
    return [BarView("nq_1s", T0 + (s - 1) * NS, T0 + s * NS, o, h, lo, (h + lo) / 2, 1.0) for s, o, h, lo in spec]


def _run_kernel(arm, bars, *, direction=1, stop=99.0, **kw):
    k = _kernel([arm], **kw)
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, direction, atr=None,
           decision_price=100.0, stop_price=stop)
    for b in bars:
        k.on_bar(b)
    k.finalize() if hasattr(k, "finalize") else None
    rows = k.drain_rows()
    assert len(rows) == 1, rows
    return rows[0]


def _run_oracle(arm, bars, *, direction=1, stop=99.0, same_bar="adverse_first", session_close=CLOSE,
                session_end_rule="censor", max_gap_ns=None, expiry="censor"):
    barrier = {"id": arm.id, "unit": "structural", "reward_risk": arm.reward_risk, "stop_buffer_points": arm.stop_buffer_points,
               "tick_size": arm.tick_size, "horizon_seconds": arm.horizon_ns // NS, "horizon_expiry_policy": expiry,
               "same_bar_rule": same_bar, "session_end_rule": session_end_rule}
    contract = {"primitive": "ordered_barrier", "required_forward_outcomes": [
        {"entry_reference": "next_bar_open", "max_gap_seconds": (max_gap_ns // NS) if max_gap_ns else None,
         "ordered_barriers": [barrier]}]}
    cand = {"observation_ts": T0, "session_close_ts": session_close, "direction": direction, "stop_price": stop}
    evs = [{"ts": b.ts_init, "open": b.open, "high": b.high, "low": b.low} for b in bars]
    return oracle_replay(contract, cand, evs)


def _k(row, aid="s"):
    return {"disposition": row[f"{aid}_disposition"], "label": row[f"{aid}_label"], "reason": row[f"{aid}_censor_reason"],
            "stop": row[f"{aid}_stop_price"], "target": row[f"{aid}_target_price"], "risk": row[f"{aid}_risk_points"],
            "rr": row[f"{aid}_reward_risk_effective"], "amb": row[f"{aid}_ambiguous_same_bar"]}


def _o(res):
    return {"disposition": res["disposition"], "label": (None if res["label"] is None else float(res["label"])),
            "reason": res["censor_reason"], "stop": res.get("stop_price"), "target": res.get("target_price"),
            "risk": res.get("risk_points"), "rr": res.get("reward_risk_effective"), "amb": res.get("ambiguous_same_bar")}


def _parity(arm, bars, **kw):
    k = _k(_run_kernel(arm, bars, **{x: v for x, v in kw.items() if x not in ("expiry",)}), arm.prefix)
    o = _o(_run_oracle(arm, bars, **{x: v for x, v in kw.items() if x not in ("max_gap_ns_k",)}))
    for key in ("disposition", "label", "reason", "stop", "target", "risk", "amb"):
        assert k[key] == o[key] or (isinstance(k[key], float) and isinstance(o[key], float) and math.isclose(k[key], o[key])), \
            (key, k, o)
    if k["rr"] is not None:
        assert math.isclose(k["rr"], o["rr"])
    return k


# -- placement, symmetry, gaps, rounding ----------------------------------------------------------------------
def test_long_stop_buffer_and_r_target_on_executable_entry():
    # stop 99.0 - 0.25 = 98.75; entry = next 1s open 100.0; risk 1.25; target 100 + 2*1.25 = 102.5
    k = _parity(_arm(), _bars([(1, 100.0, 100.5, 99.75), (2, 100.5, 102.5, 100.25)]))
    assert (k["disposition"], k["stop"], k["risk"], k["target"], k["rr"], k["amb"]) == (POSITIVE, 98.75, 1.25, 102.5, 2.0, False)


def test_short_is_the_mirror():
    # short: stop 101.0 + 0.25 = 101.25; entry 100.0; risk 1.25; target 97.5; the stop is hit
    k = _parity(_arm(), _bars([(1, 100.0, 100.25, 99.5), (2, 100.0, 101.25, 99.75)]), direction=-1, stop=101.0)
    assert (k["disposition"], k["stop"], k["target"], k["risk"]) == (NEGATIVE, 101.25, 97.5, 1.25)


def test_entry_gap_risk_uses_the_executable_open_not_the_signal_close():
    # decision price 100.0 but the next bar opens at 100.5: risk 100.5 - 98.75 = 1.75; target 100.5 + 3.5 = 104.0
    k = _parity(_arm(), _bars([(1, 100.5, 100.75, 100.25)]))
    assert (k["risk"], k["target"], k["disposition"], k["reason"]) == (1.75, 104.0, CENSORED, "DATA_END")


def test_rounding_is_away_from_the_entry_on_both_barriers():
    # long: 98.9 - 0.1 = 98.8 -> 98.75 (down); target 100 + 1.5*1.25 = 101.875 -> 102.0 (up); effective R 1.6
    k = _parity(_arm(rr=1.5, buf=0.1), _bars([(1, 100.0, 100.25, 99.75)]), stop=98.9)
    assert (k["stop"], k["target"], k["risk"]) == (98.75, 102.0, 1.25) and math.isclose(k["rr"], 1.6)
    # short: 101.1 + 0.1 = 101.2 -> 101.25 (up); target 100 - 1.875 = 98.125 -> 98.0 (down)
    k = _parity(_arm(rr=1.5, buf=0.1), _bars([(1, 100.0, 100.25, 99.75)]), direction=-1, stop=101.1)
    assert (k["stop"], k["target"], k["risk"]) == (101.25, 98.0, 1.25) and math.isclose(k["rr"], 1.6)


def test_no_tick_size_means_no_rounding():
    k = _parity(_arm(rr=1.5, buf=0.1, tick=None), _bars([(1, 100.0, 100.25, 99.75)]), stop=98.9)
    assert math.isclose(k["stop"], 98.8) and math.isclose(k["target"], 100.0 + 1.5 * 1.2)


# -- invalid stops are excluded candidates with an explicit reason, never dropped ------------------------------
@pytest.mark.parametrize("stop,direction,reason", [
    (None, 1, "STRUCTURAL_STOP_MISSING"), (float("nan"), 1, "STRUCTURAL_STOP_MISSING"),
    (float("inf"), -1, "STRUCTURAL_STOP_MISSING"),
    (100.25, 1, "STRUCTURAL_STOP_ZERO_RISK"),        # 100.25 - 0.25 = 100.0 == entry
    (100.5, 1, "STRUCTURAL_STOP_WRONG_SIDE"),        # long stop above the entry
    (99.5, -1, "STRUCTURAL_STOP_WRONG_SIDE"),        # short stop below the entry
])
def test_invalid_structural_stops_are_censored_with_a_reason(stop, direction, reason):
    k = _parity(_arm(), _bars([(1, 100.0, 103.0, 97.0)]), stop=stop, direction=direction)
    assert (k["disposition"], k["reason"], k["target"], k["risk"], k["label"]) == (CENSORED, reason, None, None, None)
    if reason == "STRUCTURAL_STOP_MISSING":
        assert k["stop"] is None
    else:
        assert k["stop"] is not None


def test_entry_gap_through_the_stop_is_wrong_side_not_a_loss():
    k = _parity(_arm(), _bars([(1, 98.5, 98.75, 98.0)]))      # opens below the 98.75 stop
    assert (k["disposition"], k["reason"]) == (CENSORED, "STRUCTURAL_STOP_WRONG_SIDE")


# -- same-bar collisions ----------------------------------------------------------------------------------------
def test_same_bar_collision_is_stop_first_and_stays_auditable():
    bars = _bars([(1, 100.0, 102.5, 98.75)])                  # one bar spans stop and target
    k = _parity(_arm(), bars, same_bar="adverse_first")
    assert (k["disposition"], k["label"], k["reason"], k["amb"]) == (NEGATIVE, 0.0, None, True)
    k = _parity(_arm(), bars, same_bar="ambiguous_censor")
    assert (k["disposition"], k["reason"], k["amb"]) == (CENSORED, "AMBIGUOUS_SAME_BAR_TOUCH", True)


def test_clean_stop_is_not_flagged_ambiguous():
    k = _parity(_arm(), _bars([(1, 100.0, 100.5, 99.5), (2, 99.5, 99.75, 98.5)]))
    assert (k["disposition"], k["amb"]) == (NEGATIVE, False)


# -- time: horizon, session end, gaps, cutoffs -----------------------------------------------------------------
def test_timeout_is_censored_and_oracle_agrees():
    bars = _bars([(s, 100.0, 100.5, 99.5) for s in range(1, 13)])
    k = _parity(_arm(horizon_s=10), bars)
    assert (k["disposition"], k["reason"]) == (CENSORED, "TIMEOUT")


def test_session_close_truncates_and_censors_session_end():
    bars = _bars([(s, 100.0, 100.5, 99.5) for s in range(1, 8)])
    k = _parity(_arm(horizon_s=600), bars, session_close=T0 + 5 * NS, session_end_rule="truncate")
    assert (k["disposition"], k["reason"]) == (CENSORED, "SESSION_END")


def test_entry_gap_rule_precedes_stop_validation():
    bars = _bars([(120, 100.0, 103.0, 97.0)])
    k = _k(_run_kernel(_arm(), bars, stop=None, max_gap_ns=60 * NS))
    o = _o(_run_oracle(_arm(), bars, stop=None, max_gap_ns=60 * NS))
    assert k["reason"] == o["reason"] == "GAP" and k["stop"] is None


def test_session_cutoff_bounds_the_hold_kernel():
    import datetime
    import zoneinfo
    et = zoneinfo.ZoneInfo("America/New_York")
    t = datetime.datetime.fromtimestamp(T0 / NS, tz=et)
    cut = t + datetime.timedelta(seconds=5)
    spec = {"hour": cut.hour, "minute": cut.minute, "second": cut.second, "tz": "America/New_York"}
    row = _run_kernel(_arm(horizon_s=600), _bars([(s, 100.0, 100.5, 99.5) for s in range(1, 10)]), session_cutoff=spec)
    assert row["s_disposition"] == CENSORED and row["s_censor_reason"] in ("TIMEOUT", "SESSION_END")
    assert row["s_resolution_seconds"] <= 5 and row["s_risk_points"] == 1.25


def test_entry_cutoff_excludes_without_levels():
    import datetime
    import zoneinfo
    et = zoneinfo.ZoneInfo("America/New_York")
    t = datetime.datetime.fromtimestamp(T0 / NS, tz=et) - datetime.timedelta(seconds=1)   # entry instant T is past it
    spec = {"hour": t.hour, "minute": t.minute, "second": t.second, "tz": "America/New_York"}
    row = _run_kernel(_arm(), _bars([(1, 100.0, 103.0, 97.0)]), entry_cutoff=spec)
    assert row["s_censor_reason"] == "ENTRY_PAST_CUTOFF" and row["s_stop_price"] is None and row["s_target_price"] is None


# -- no lookahead: the stop is the value known at T and bars at/before T are never the entry --------------------
def test_stop_is_frozen_at_T_and_entry_is_strictly_after_T():
    k = _kernel([_arm()])
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, atr=None, decision_price=100.0, stop_price=99.0)
    # a bar closing AT T (already delivered) must neither be the entry nor touch the barriers
    k.on_bar(BarView("nq_1s", T0 - NS, T0, 90.0, 120.0, 80.0, 100.0, 1.0))
    p = k.pending[0]
    assert p.entry_resolved is False and p.stop_price == 99.0
    k.on_bar(BarView("nq_1s", T0, T0 + NS, 100.0, 100.5, 99.5, 100.0, 1.0))
    assert p.entry_price == 100.0 and p.arm_bad[0] == 98.75 and p.stop_price == 99.0


# -- legacy arms are untouched ----------------------------------------------------------------------------------
def test_legacy_points_arm_has_no_structural_columns_and_unchanged_semantics():
    arm = BarrierArm(id="p", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=600 * NS, expiry="censor", prefix="p",
                     unit="points", favorable_points=2.0, adverse_points=1.0)
    k = _kernel([arm], same_bar="ambiguous_censor", primary="p")
    assert not any(c.endswith(STRUCTURAL_ARM_SUFFIXES) for c in k.observation_columns)
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, atr=None, decision_price=100.0)
    for b in _bars([(1, 100.0, 102.0, 99.5)]):
        k.on_bar(b)
    row = k.drain_rows()[0]
    assert row["disposition"] == "LABELED_POSITIVE" and "p_stop_price" not in row


def test_legacy_atr_oracle_output_unchanged():
    contract = {"primitive": "ordered_barrier", "required_forward_outcomes": [
        {"entry_reference": "next_bar_open", "ordered_barriers": [
            {"id": "a", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 600}]}]}
    cand = {"observation_ts": T0, "session_close_ts": CLOSE, "direction": 1, "atr": 2.0}
    res = oracle_replay(contract, cand, [{"ts": T0 + NS, "open": 100.0, "high": 102.0, "low": 99.5}])
    assert res == {"disposition": "POSITIVE", "label": 1, "censor_reason": None}


# -- grammar / compiler ------------------------------------------------------------------------------------------
def _compile(outcome):
    from research_workflow.grammar.compiler import compile_study, load_spec
    root = Path(__file__).resolve().parents[2]
    spec = load_spec(root / "fixtures" / "parity" / "shape_c" / "study.yaml")
    spec["outcome"] = outcome
    return compile_study(spec, repo_root=root)


_BASE = {"kind": "label", "entry_reference": "next_bar_open", "horizon": "600s", "same_bar_rule": "adverse_first"}


def test_compiler_structural_arm_contract_and_columns():
    out = _compile({**_BASE, "stop_reference": "excursion.lowest_low",
                    "barrier": {"primary": "s2", "arms": [{"id": "s2", "unit": "structural", "reward_risk": 2.0,
                                                           "stop_buffer_points": 0.25, "tick_size": 0.25}]}})
    assert out.ok, out.card()
    o = out.plan.to_dict()["outcome"]
    assert o["stop_reference"] == "excursion.lowest_low"
    assert o["arms"][0]["reward_risk"] == 2.0 and o["arms"][0]["tick_size"] == 0.25
    c = LabelOutcomeContract.from_plan(o)
    assert c.stop_ref == "excursion.lowest_low" and c.arms[0].unit == "structural"


@pytest.mark.parametrize("outcome,where", [
    ({**_BASE, "barrier": {"primary": "s", "arms": [{"id": "s", "unit": "structural", "reward_risk": 2.0}]}}, "outcome.stop_reference"),
    ({**_BASE, "stop_reference": "epoch.price", "barrier": {"primary": "s", "arms": [{"id": "s", "unit": "structural", "reward_risk": 2.0}]}}, "outcome.stop_reference"),
    ({**_BASE, "stop_reference": "const:99.0", "barrier": {"primary": "s", "arms": [{"id": "s", "unit": "structural", "reward_risk": 2.0}]}}, "outcome.stop_reference"),
    ({**_BASE, "stop_reference": "excursion.lowest_low", "barrier": {"primary": "s", "arms": [{"id": "s", "unit": "structural"}]}}, "outcome.barrier.s"),
    ({**_BASE, "stop_reference": "excursion.lowest_low", "barrier": {"primary": "s", "arms": [{"id": "s", "unit": "structural", "reward_risk": 2.0, "adverse_points": 5.0}]}}, "outcome.barrier.s"),
    ({**_BASE, "stop_reference": "excursion.lowest_low", "barrier": {"primary": "p", "arms": [{"id": "p", "unit": "points", "favorable_points": 2.0, "adverse_points": 1.0}]}}, "outcome.stop_reference"),
])
def test_compiler_refuses_bad_structural_declarations(outcome, where):
    out = _compile(outcome)
    assert not out.ok and any(g.where == where for g in out.gaps.gaps), out.card()


def test_compiler_legacy_arms_get_no_new_keys():
    out = _compile({**_BASE, "barrier": {"primary": "p", "arms": [{"id": "p", "unit": "points", "favorable_points": 2.0, "adverse_points": 1.0}]}})
    assert out.ok, out.card()
    o = out.plan.to_dict()["outcome"]
    assert "stop_reference" not in o and not ({"reward_risk", "stop_buffer_points", "tick_size"} & set(o["arms"][0]))


# -- randomized kernel/oracle parity sweep (seeded; independent implementations must agree on every field) --------
def test_randomized_parity_sweep():
    import random
    rng = random.Random(20261018)
    outcomes = {}
    for case in range(400):
        direction = rng.choice((1, -1))
        same_bar = rng.choice(("adverse_first", "ambiguous_censor"))
        tick = rng.choice((TICK, None))
        rr = rng.choice((1.0, 1.5, 2.0, 3.0))
        buf = rng.choice((0.0, 0.25, 0.1, 0.5))
        px, spec, s = 100.0, [], 0
        for _ in range(rng.randint(1, 40)):
            s += rng.choice((1, 1, 1, 2, 5))
            o = round(px + rng.choice((-0.5, -0.25, 0.0, 0.25, 0.5)), 2)
            h = o + rng.choice((0.0, 0.25, 0.5, 1.0, 2.0))
            lo = o - rng.choice((0.0, 0.25, 0.5, 1.0, 2.0))
            spec.append((s, o, h, lo))
            px = rng.uniform(lo, h)
        dist = rng.choice((-0.5, 0.0, 0.25, 0.6, 1.0, 1.3, 2.0, 3.0))
        stop = rng.choice((None, float("nan"), 100.0 - direction * dist, 100.0 - direction * dist))
        horizon = rng.choice((5, 20, 600))
        k = _parity(_arm(rr=rr, buf=buf, tick=tick, horizon_s=horizon), _bars(spec), direction=direction, stop=stop,
                    same_bar=same_bar)
        outcomes[(k["disposition"], k["reason"])] = outcomes.get((k["disposition"], k["reason"]), 0) + 1
    # the sweep must actually exercise every branch, not just agree on one
    reasons = {r for (_, r) in outcomes}
    for needed in (None, "STRUCTURAL_STOP_MISSING", "STRUCTURAL_STOP_WRONG_SIDE", "STRUCTURAL_STOP_ZERO_RISK", "TIMEOUT"):
        assert needed in reasons, outcomes
    assert any(d == POSITIVE for d, _ in outcomes) and any(d == NEGATIVE for d, _ in outcomes)
