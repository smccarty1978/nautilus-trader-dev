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
