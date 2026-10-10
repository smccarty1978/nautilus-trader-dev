"""Targeted unit tests for G1 cutoffs (session_cutoff, entry_cutoff) and G3 multi-unit arms (points, reference)."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock
import zoneinfo
import pytest

from research_workflow.host.interfaces import BarView, NS
from research_workflow.host.outcomes import (
    BarrierArm,
    CENSORED,
    LabelOutcomeContract,
    LabelOutcomeKernel,
    NEGATIVE,
    POSITIVE,
)

ET = zoneinfo.ZoneInfo("America/New_York")


def _ns(y, m, d, hh, mm, ss=0):
    dt = datetime.datetime(y, m, d, hh, mm, ss, tzinfo=ET)
    return int(dt.timestamp() * NS)


def _bar(ts_event, ts_init, o, h, l, c):
    return BarView("stream_1m", ts_event, ts_init, o, h, l, c, 100.0)


def test_entry_cutoff_rejection():
    # Signal at 11:00 ET (bar 10:59-11:00, ts_init = 11:00:00).
    # Entry cutoff is 11:00:00 America/New_York.
    # Next bar is 11:00-11:01 (ts_event = 11:00:00, ts_init = 11:01:00).
    # If entry print timestamp is > 11:00:00, it should be rejected with ENTRY_PAST_CUTOFF.
    # If entry print timestamp is == 11:00:00, it should be accepted.
    t_signal = _ns(2023, 10, 2, 11, 0, 0)
    cutoff_spec = {"hour": 11, "minute": 0, "second": 0, "tz": "America/New_York"}
    arms = (
        BarrierArm(id="tp_sl", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=1800 * NS, expiry="censor", prefix="arm0", unit="points", favorable_points=38.0, adverse_points=25.0),
    )
    contract = LabelOutcomeContract(
        kernel="barrier",
        direction_ref="const:1",
        atr_ref=None,
        entry_reference="next_bar_open",
        session_end_censoring=True,
        max_gap_ns=None,
        same_bar_rule="ambiguous_censor",
        arms=arms,
        entry_cutoff=cutoff_spec,
        entry_observation=True,
    )
    session_table = MagicMock()
    session_table.session_close.return_value = _ns(2023, 10, 2, 16, 0, 0)

    # Case A: Next bar opens exactly at 11:00:00 ET (ts_event = 11:00:00) -> Accepted
    k_accepted = LabelOutcomeKernel(contract, session_table)
    k_accepted.open({"observation_ts": t_signal, "regime_start_ns": t_signal, "checkpoint_index": 0}, t_signal, 1, atr=10.0)
    bar_on_time = _bar(_ns(2023, 10, 2, 11, 0, 0), _ns(2023, 10, 2, 11, 1, 0), 15000.0, 15010.0, 14995.0, 15005.0)
    k_accepted.on_bar(bar_on_time)
    assert k_accepted.pending[0].entry_resolved is True
    assert k_accepted.pending[0].arm_state[0] is None # Still pending, not rejected

    # Case B: Next bar opens at 11:00:01 ET (delayed print / gap past 11:00:00) -> Rejected
    k_rejected = LabelOutcomeKernel(contract, session_table)
    k_rejected.open({"observation_ts": t_signal, "regime_start_ns": t_signal, "checkpoint_index": 0}, t_signal, 1, atr=10.0)
    bar_delayed = _bar(_ns(2023, 10, 2, 11, 0, 1), _ns(2023, 10, 2, 11, 1, 1), 15000.0, 15010.0, 14995.0, 15005.0)
    k_rejected.on_bar(bar_delayed)
    # The candidate is completely resolved and emitted immediately!
    assert len(k_rejected.pending) == 0
    rows = k_rejected.drain_rows()
    assert len(rows) == 1
    assert rows[0]["censor_reason"] == "ENTRY_PAST_CUTOFF"
    assert rows[0]["executable_entry_unavailable_reason"] == "ENTRY_PAST_CUTOFF"


def test_session_cutoff_and_flat_expiry():
    # Signal at 10:00 ET. Horizon is 2 hours (until 12:00 ET).
    # Mandatory flat cutoff is 11:30 ET.
    # The arm end should be clamped to 11:30 ET without arm_truncated being set (so it expires as TIMEOUT, not SESSION_END).
    t_signal = _ns(2023, 10, 2, 10, 0, 0)
    session_cutoff_spec = {"hour": 11, "minute": 30, "second": 0, "tz": "America/New_York"}
    arms = (
        BarrierArm(id="tp_sl", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=7200 * NS, expiry="censor", prefix="arm0", unit="points", favorable_points=38.0, adverse_points=25.0),
    )
    contract = LabelOutcomeContract(
        kernel="barrier",
        direction_ref="const:1",
        atr_ref=None,
        entry_reference="next_bar_open",
        session_end_censoring=True,
        max_gap_ns=None,
        same_bar_rule="ambiguous_censor",
        arms=arms,
        session_cutoff=session_cutoff_spec,
    )
    session_table = MagicMock()
    session_table.session_close.return_value = _ns(2023, 10, 2, 16, 0, 0)

    k = LabelOutcomeKernel(contract, session_table)
    k.open({"observation_ts": t_signal, "regime_start_ns": t_signal, "checkpoint_index": 0}, t_signal, 1, atr=10.0)

    # Bar 1: Entry fill at 10:01 ET
    k.on_bar(_bar(_ns(2023, 10, 2, 10, 0, 0), _ns(2023, 10, 2, 10, 1, 0), 15000.0, 15005.0, 14995.0, 15000.0))
    p = k.pending[0]
    expected_cutoff_ts = _ns(2023, 10, 2, 11, 30, 0)
    assert p.arm_end[0] == expected_cutoff_ts
    assert p.arm_truncated[0] is False # Clamped by cutoff, not session_close truncate

    # Bar at 11:30 ET (closing exactly at cutoff without hitting 15038 or 14975)
    k.on_bar(_bar(_ns(2023, 10, 2, 11, 29, 0), _ns(2023, 10, 2, 11, 30, 0), 15000.0, 15010.0, 14990.0, 15005.0))
    assert p.arm_state[0] == CENSORED
    assert p.arm_reason[0] == "TIMEOUT" # Normal expiry policy reached cutoff, NOT SESSION_END!


def test_anchor_target_and_already_crossed_censoring():
    t_signal = _ns(2023, 10, 2, 10, 0, 0)
    anchor_px = 15050.0 # Anchor above entry
    arms = (
        BarrierArm(id="anchor_arm", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=1800 * NS, expiry="censor", prefix="anchor", unit="reference", adverse_points=25.0),
    )
    contract = LabelOutcomeContract(
        kernel="barrier",
        direction_ref="const:1", # Long reversion toward anchor
        atr_ref=None,
        entry_reference="next_bar_open",
        session_end_censoring=True,
        max_gap_ns=None,
        same_bar_rule="ambiguous_censor",
        arms=arms,
        reference_ref="rth_open",
    )
    session_table = MagicMock()
    session_table.session_close.return_value = _ns(2023, 10, 2, 16, 0, 0)

    # Subtest 1: Entry fill at 15000 (below anchor 15050, direction long +1). Target is 15050, Stop is 14975.
    k1 = LabelOutcomeKernel(contract, session_table)
    k1.open({"observation_ts": t_signal, "regime_start_ns": t_signal, "checkpoint_index": 0}, t_signal, 1, atr=10.0, reference_price=anchor_px, decision_price=14990.0)
    # Entry bar
    k1.on_bar(_bar(_ns(2023, 10, 2, 10, 0, 0), _ns(2023, 10, 2, 10, 1, 0), 15000.0, 15010.0, 14995.0, 15005.0))
    p1 = k1.pending[0]
    assert p1.arm_good[0] == 15050.0
    assert p1.arm_bad[0] == 14975.0
    assert p1.arm_state[0] is None

    # Next bar touches 15055 -> POSITIVE
    k1.on_bar(_bar(_ns(2023, 10, 2, 10, 1, 0), _ns(2023, 10, 2, 10, 2, 0), 15005.0, 15055.0, 15000.0, 15050.0))
    assert p1.arm_state[0] == POSITIVE

    # Subtest 2: Entry fill at 15055 (direction long +1, but ep >= anchor 15050). Already crossed!
    k2 = LabelOutcomeKernel(contract, session_table)
    k2.open({"observation_ts": t_signal, "regime_start_ns": t_signal, "checkpoint_index": 0}, t_signal, 1, atr=10.0, reference_price=anchor_px, decision_price=14990.0)
    k2.on_bar(_bar(_ns(2023, 10, 2, 10, 0, 0), _ns(2023, 10, 2, 10, 1, 0), 15055.0, 15060.0, 15050.0, 15052.0))
    assert len(k2.pending) == 0
    rows2 = k2.drain_rows()
    assert len(rows2) == 1
    assert rows2[0]["censor_reason"] == "ANCHOR_ALREADY_CROSSED"


def test_mixed_arms_bracket_with_recovery_points_reference():
    # Test all 6 arms simultaneously:
    # m25, m50, m75, m100 (unit: recovery)
    # tp38_sl25 (unit: points)
    # anchor_sl25 (unit: reference)
    # No ATR provided (atr=None) -> should succeed without error because no arm has unit: atr!
    t_signal = _ns(2023, 10, 2, 10, 0, 0)
    anchor_px = 15000.0
    dec_px = 14900.0  # displaced -100 pts below anchor -> recovery direction is +1 (long)
    horizon = 5400 * NS
    session_cutoff_spec = {"hour": 11, "minute": 30, "second": 0, "tz": "America/New_York"}

    arms = (
        BarrierArm(id="m25", favorable_atr=0.25, adverse_atr=0.0, horizon_ns=horizon, expiry="censor", prefix="m25", unit="recovery"),
        BarrierArm(id="m50", favorable_atr=0.50, adverse_atr=0.0, horizon_ns=horizon, expiry="censor", prefix="m50", unit="recovery"),
        BarrierArm(id="m75", favorable_atr=0.75, adverse_atr=0.0, horizon_ns=horizon, expiry="censor", prefix="m75", unit="recovery"),
        BarrierArm(id="m100", favorable_atr=1.00, adverse_atr=0.0, horizon_ns=horizon, expiry="censor", prefix="m100", unit="recovery"),
        BarrierArm(id="tp38_sl25", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=horizon, expiry="censor", prefix="tp38_sl25", unit="points", favorable_points=38.0, adverse_points=25.0),
        BarrierArm(id="anchor_sl25", favorable_atr=0.0, adverse_atr=0.0, horizon_ns=horizon, expiry="censor", prefix="anchor_sl25", unit="reference", adverse_points=25.0),
    )
    contract = LabelOutcomeContract(
        kernel="barrier",
        direction_ref="const:1",
        atr_ref=None,
        entry_reference="next_bar_open",
        session_end_censoring=True,
        max_gap_ns=None,
        same_bar_rule="ambiguous_censor",
        arms=arms,
        primary_arm="tp38_sl25",
        reference_ref="features.rth_open",
        session_cutoff=session_cutoff_spec,
    )
    session_table = MagicMock()
    session_table.session_close.return_value = _ns(2023, 10, 2, 16, 0, 0)

    kernel = LabelOutcomeKernel(contract, session_table)
    # Opening without ATR:
    kernel.open(
        {"observation_ts": t_signal, "regime_start_ns": t_signal, "checkpoint_index": 0},
        t_signal,
        direction=1,
        atr=None,
        reference_price=anchor_px,
        decision_price=dec_px,
    )
    assert len(kernel.pending) == 1
    p = kernel.pending[0]

    # Bar 1: Entry at 10:01 ET. Entry fill open = 14910.0.
    # Targets & stops expected:
    # m25: target = 14900 + 0.25 * 100 = 14925.0, stop = -inf
    # m50: target = 14900 + 0.50 * 100 = 14950.0, stop = -inf
    # m75: target = 14900 + 0.75 * 100 = 14975.0, stop = -inf
    # m100: target = 15000.0, stop = -inf
    # tp38_sl25: target = 14910 + 38 = 14948.0, stop = 14910 - 25 = 14885.0
    # anchor_sl25: target = 15000.0, stop = 14910 - 25 = 14885.0
    bar_entry = _bar(_ns(2023, 10, 2, 10, 0, 0), _ns(2023, 10, 2, 10, 1, 0), 14910.0, 14920.0, 14905.0, 14915.0)
    kernel.on_bar(bar_entry)

    assert p.arm_good[0] == 14925.0
    assert p.arm_good[1] == 14950.0
    assert p.arm_good[2] == 14975.0
    assert p.arm_good[3] == 15000.0
    assert p.arm_good[4] == 14948.0
    assert p.arm_bad[4] == 14885.0
    assert p.arm_good[5] == 15000.0
    assert p.arm_bad[5] == 14885.0

    # Bar 2: High touches 14930.0 -> Hits m25 (14925.0), none of the others
    bar_m25 = _bar(_ns(2023, 10, 2, 10, 1, 0), _ns(2023, 10, 2, 10, 2, 0), 14915.0, 14930.0, 14912.0, 14928.0)
    kernel.on_bar(bar_m25)
    assert p.arm_state[0] == POSITIVE
    assert p.arm_state[1] is None
    assert p.arm_state[4] is None

    # Bar 3: High touches 14955.0 -> Hits m50 (14950.0) and tp38_sl25 (14948.0)!
    bar_tp = _bar(_ns(2023, 10, 2, 10, 2, 0), _ns(2023, 10, 2, 10, 3, 0), 14928.0, 14955.0, 14925.0, 14950.0)
    kernel.on_bar(bar_tp)
    assert p.arm_state[1] == POSITIVE
    assert p.arm_state[4] == POSITIVE
    assert p.arm_state[2] is None
    assert p.arm_state[3] is None
    assert p.arm_state[5] is None

    # Bar 4: High touches 15005.0 -> Hits m75 (14975), m100 (15000), anchor_sl25 (15000)!
    bar_anchor = _bar(_ns(2023, 10, 2, 10, 3, 0), _ns(2023, 10, 2, 10, 4, 0), 14950.0, 15005.0, 14948.0, 15002.0)
    kernel.on_bar(bar_anchor)

    # All 6 arms should now be POSITIVE
    assert len(kernel.pending) == 0
    rows = kernel.drain_rows()
    assert len(rows) == 1
    r = rows[0]
    assert r["m25_label"] == 1.0
    assert r["m50_label"] == 1.0
    assert r["m75_label"] == 1.0
    assert r["m100_label"] == 1.0
    assert r["tp38_sl25_label"] == 1.0
    assert r["anchor_sl25_label"] == 1.0
    assert r["target_flip_within_horizon"] == 1  # Primary arm is tp38_sl25
    assert r["disposition"] == "LABELED_POSITIVE"


def test_compiler_mixed_arms_compilation():
    from pathlib import Path
    from research_workflow.grammar.compiler import compile_study, load_spec

    root = Path(__file__).resolve().parents[2]
    spec = load_spec(root / "fixtures" / "parity" / "shape_c" / "study.yaml")
    spec["outcome"] = {
        "kind": "label",
        "reference": "const:15000.0",
        "entry_reference": "next_bar_open",
        "entry_cutoff": "11:00:00 America/New_York",
        "session_cutoff": "11:30:00 America/New_York",
        "session_end": "truncate",
        "horizon": "5400s",
        "barrier": {
            "primary": "tp38_sl25",
            "arms": [
                {"id": "m25", "unit": "recovery", "favorable_atr": 0.25},
                {"id": "m50", "unit": "recovery", "favorable_atr": 0.50},
                {"id": "m75", "unit": "recovery", "favorable_atr": 0.75},
                {"id": "m100", "unit": "recovery", "favorable_atr": 1.00},
                {"id": "tp38_sl25", "unit": "points", "favorable_points": 38.0, "adverse_points": 25.0},
                {"id": "anchor_sl25", "unit": "reference", "adverse_points": 25.0},
            ],
        },
    }
    out = compile_study(spec, repo_root=root)
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert plan["outcome"]["contract"] == "label"
    assert plan["outcome"]["kernel"] == "barrier"
    assert plan["outcome"]["reference"] == "const:15000.0"
    assert len(plan["outcome"]["arms"]) == 6
    assert plan["outcome"]["primary_arm"] == "tp38_sl25"
    assert plan["outcome"]["session_cutoff"] == {"hour": 11, "minute": 30, "second": 0, "tz": "America/New_York"}
    assert plan["outcome"]["entry_cutoff"] == {"hour": 11, "minute": 0, "second": 0, "tz": "America/New_York"}


