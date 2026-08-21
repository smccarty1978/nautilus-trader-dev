"""Regression tests for the target/censoring contract (Finding E).

``config/target_contract.json`` declares::

    "censoring_policy": {"session_end_censoring": true, "max_horizon_seconds": 300}

The runtime implemented none of it. Pending candidates were resolved only when an
opposing flip arrived, and anything still pending when the run ended was silently
dropped -- it appeared in ``candidates.parquet`` and simply had no row in
``observations.parquet``. A population that loses precisely its unresolved members is
conditioned on the future.

The invariant under test:

    every emitted candidate  ==  labeled positive + labeled negative + explicitly censored

These tests drive the collector's disposition machinery directly with synthetic
timestamps rather than through a BacktestEngine, so each lifecycle case is isolated.
"""

from __future__ import annotations

import pandas as pd
import pytest

from strategies.flip_prediction_collector import (
    CENSOR_DATA_END,
    CENSOR_SESSION_END,
    DISPOSITION_CENSORED,
    DISPOSITION_NEGATIVE,
    DISPOSITION_POSITIVE,
    FlipPredictionCollector,
)
from utils.session_boundaries import session_close_ns

NS = 1_000_000_000
HORIZON = 300


def ct_ns(day: str, hhmmss: str) -> int:
    """CT wall-clock -> UTC nanoseconds."""
    return int(pd.Timestamp(f"{day} {hhmmss}", tz="America/Chicago").tz_convert("UTC").value)


class _Collector(FlipPredictionCollector):
    """Instantiates the disposition machinery without a NautilusTrader engine."""

    def __init__(self, session_end_censoring: bool = True):
        class _Cfg:
            horizon_seconds = HORIZON
            session = "RTH"
        _Cfg.session_end_censoring = session_end_censoring
        self.cfg = _Cfg()
        self.is_both_directions = True
        self.target_dir = 0
        self.pending_candidates = []
        self.observations_log = []
        self.last_ts_seen = None
        self.active_regime_dir = 1
        # Fields _on_regime_flip resets after resolving.
        self.regime_start_ns = 0
        self.regime_start_close = 0.0
        self.regime_frozen_atr = 1.0
        self.highest_high_since_flip = 0.0
        self.lowest_low_since_flip = 0.0
        self.mfe_progress_previous_extreme = 0.0
        self.mfe_progress_last_extreme_ts = None
        self.mfe_progress_count = 0
        self.next_checkpoint_index = 0

    def add_candidate(self, T: int):
        self._track_pending(
            {"observation_ts": T, "regime_start_ns": T - 600 * NS,
             "regime_direction": 1, "checkpoint_index": 0},
            T,
        )


DAY = "2024-09-03"


def dispositions(c: _Collector):
    return [o["disposition"] for o in c.observations_log]


# ---------------------------------------------------------------------------
# The seven declared lifecycle cases
# ---------------------------------------------------------------------------

def test_1_target_positive_resolves_inside_the_horizon():
    """E.1 -- an opposing flip inside 300s is a positive label."""
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    c._on_regime_flip(new_regime=-1, flip_ts=T + 120 * NS,
                      open_price=1.0, close_price=1.0, atr_val=1.0)
    assert dispositions(c) == [DISPOSITION_POSITIVE]
    obs = c.observations_log[0]
    assert obs["target_flip_within_horizon"] == 1
    assert obs["time_to_flip_seconds"] == pytest.approx(120.0)
    assert obs["censored"] == 0


def test_2_no_event_during_the_full_horizon_is_a_negative():
    """E.2 -- a fully elapsed in-session horizon with no flip is a real negative."""
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    # One tick past the inclusive endpoint: at exactly horizon_end a coincident flip is
    # still entitled to resolve this candidate (see test_2c).
    c._sweep_elapsed_horizons(T + (HORIZON + 1) * NS)
    assert dispositions(c) == [DISPOSITION_NEGATIVE]
    obs = c.observations_log[0]
    assert obs["target_flip_within_horizon"] == 0
    assert obs["flip_ts"] is None, "a negative must not carry a flip it never saw"


def test_2c_flip_landing_exactly_on_the_horizon_boundary_is_positive():
    """Same-tick race between horizon expiry and an opposing flip (causal audit pass 01).

    Candidates sit on a 5s grid from a minute-aligned regime start and the horizon is
    300s, so every 12th candidate has a horizon_end that falls exactly on a minute
    boundary -- which is precisely when flips occur. The 1s-before-1m dispatch convention
    means the 1s bar closing at T is handled before the 1m bar closing at the same T, so
    an eager sweep resolves the candidate NEGATIVE moments before the flip is seen.

    The horizon is inclusive of its endpoint, so a flip at exactly horizon_end is a
    POSITIVE. Roughly 1 candidate in 12 was exposed to this.
    """
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    horizon_end = T + HORIZON * NS

    # 1s bar closing at the horizon boundary arrives first.
    c._sweep_elapsed_horizons(horizon_end)
    assert c.observations_log == [], (
        "candidate was resolved by the 1s sweep before the coincident 1m flip was seen"
    )

    # The 1m bar closing at the same instant carries the flip.
    c._on_regime_flip(-1, horizon_end, 1.0, 1.0, 1.0)
    assert dispositions(c) == [DISPOSITION_POSITIVE]
    assert c.observations_log[0]["time_to_flip_seconds"] == pytest.approx(float(HORIZON))


def test_2d_boundary_candidate_still_resolves_negative_when_no_flip_arrives():
    """Deferring by one tick must not leave the candidate unresolved."""
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    horizon_end = T + HORIZON * NS

    c._sweep_elapsed_horizons(horizon_end)          # deferred
    c._sweep_elapsed_horizons(horizon_end + NS)     # next 1s bar, no flip came
    assert dispositions(c) == [DISPOSITION_NEGATIVE]


def test_2e_boundary_candidate_at_run_end_is_labeled_not_censored():
    """A horizon that fully elapsed by the last observed bar is a label, not a censor."""
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    horizon_end = T + HORIZON * NS

    c._sweep_elapsed_horizons(horizon_end)   # deferred
    c.last_ts_seen = horizon_end
    c.on_stop()
    assert dispositions(c) == [DISPOSITION_NEGATIVE], (
        "the horizon completed within observed data, so the outcome is known"
    )


def test_2b_negative_is_not_emitted_before_the_horizon_elapses():
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    c._sweep_elapsed_horizons(T + (HORIZON - 1) * NS)
    assert c.observations_log == []
    assert len(c.pending_candidates) == 1


def test_3_session_ends_before_the_full_horizon_is_censored():
    """E.3 -- the declared session_end_censoring rule.

    A candidate at 15:12 has a horizon reaching 15:17, past the 15:15 RTH close. It
    cannot be labeled from in-session data in either direction.
    """
    c = _Collector()
    T = ct_ns(DAY, "15:12:00")
    c.add_candidate(T)
    c._sweep_elapsed_horizons(T + (HORIZON + 1) * NS)
    assert dispositions(c) == [DISPOSITION_CENSORED]
    obs = c.observations_log[0]
    assert obs["censor_reason"] == CENSOR_SESSION_END
    assert obs["target_flip_within_horizon"] is None, "a censored candidate has no label"


def test_3b_candidate_whose_horizon_just_fits_is_labeled_not_censored():
    """The boundary is the horizon end, not proximity to the close."""
    c = _Collector()
    T = ct_ns(DAY, "15:10:00")           # horizon ends exactly at 15:15:00
    c.add_candidate(T)
    c._sweep_elapsed_horizons(T + (HORIZON + 1) * NS)
    assert dispositions(c) == [DISPOSITION_NEGATIVE]


def test_4_data_ends_before_the_full_horizon_is_censored():
    """E.4 -- the run stops mid-horizon; the candidate is censored, never dropped."""
    c = _Collector()
    T = ct_ns(DAY, "10:00:00")
    c.add_candidate(T)
    c.last_ts_seen = T + 100 * NS
    c.on_stop()
    assert dispositions(c) == [DISPOSITION_CENSORED]
    assert c.observations_log[0]["censor_reason"] == CENSOR_DATA_END


def test_5_regime_change_resolves_only_pending_candidates():
    """E.5 -- a flip disposes the pending set exactly once and leaves nothing behind."""
    c = _Collector()
    T1 = ct_ns(DAY, "10:00:00")
    T2 = ct_ns(DAY, "10:00:05")
    c.add_candidate(T1)
    c.add_candidate(T2)
    c._on_regime_flip(-1, T1 + 60 * NS, 1.0, 1.0, 1.0)
    assert dispositions(c) == [DISPOSITION_POSITIVE, DISPOSITION_POSITIVE]
    assert c.pending_candidates == []
    # A second flip must not re-emit anything.
    c._on_regime_flip(1, T1 + 400 * NS, 1.0, 1.0, 1.0)
    assert len(c.observations_log) == 2


def test_6_candidate_emitted_near_session_end_is_censored_even_if_a_flip_lands():
    """E.6 -- a flip inside the horizon does not rescue a horizon that left the session.

    Otherwise censoring would apply only to the negatives, which would bias the label
    distribution rather than remove an unanswerable population.
    """
    c = _Collector()
    T = ct_ns(DAY, "15:14:00")
    c.add_candidate(T)
    c._on_regime_flip(-1, T + 30 * NS, 1.0, 1.0, 1.0)   # flip at 15:14:30, inside horizon
    assert dispositions(c) == [DISPOSITION_CENSORED]
    assert c.observations_log[0]["censor_reason"] == CENSOR_SESSION_END


def test_7_pending_candidates_at_strategy_stop_all_reach_a_disposition():
    """E.7 -- nothing may still be pending once the strategy has stopped.

    Disposition depends on whether the horizon completed within observed data. The 10:00
    and 12:00 candidates ran their full 300s inside the session, so their outcome is
    known and they are LABELED. Only 15:14:30, whose horizon reaches past the 15:15
    close, is genuinely unanswerable.
    """
    c = _Collector()
    for hhmmss in ("10:00:00", "12:00:00", "15:14:30"):
        c.add_candidate(ct_ns(DAY, hhmmss))
    c.last_ts_seen = ct_ns(DAY, "15:15:00")
    c.on_stop()
    assert len(c.observations_log) == 3
    assert c.pending_candidates == []

    by_ts = {o["observation_ts"]: o for o in c.observations_log}
    assert by_ts[ct_ns(DAY, "10:00:00")]["disposition"] == DISPOSITION_NEGATIVE
    assert by_ts[ct_ns(DAY, "12:00:00")]["disposition"] == DISPOSITION_NEGATIVE
    late = by_ts[ct_ns(DAY, "15:14:30")]
    assert late["disposition"] == DISPOSITION_CENSORED
    assert late["censor_reason"] == CENSOR_SESSION_END


# ---------------------------------------------------------------------------
# The reconciliation invariant
# ---------------------------------------------------------------------------

def test_candidates_reconcile_to_labeled_plus_censored():
    """Every candidate reaches exactly one terminal disposition -- no more, no fewer."""
    c = _Collector()
    times = ["09:00:00", "09:00:05", "10:30:00", "13:00:00", "15:13:00", "15:14:00"]
    for t in times:
        c.add_candidate(ct_ns(DAY, t))
    n_candidates = len(times)

    # A flip resolves the first two; the rest run their course; the run then ends.
    c._on_regime_flip(-1, ct_ns(DAY, "09:02:00"), 1.0, 1.0, 1.0)
    c._sweep_elapsed_horizons(ct_ns(DAY, "14:00:00"))
    c.last_ts_seen = ct_ns(DAY, "15:15:00")
    c.on_stop()

    obs = c.observations_log
    assert len(obs) == n_candidates, "candidate count must equal observation count"

    keys = {(o["observation_ts"], o["checkpoint_index"]) for o in obs}
    assert len(keys) == n_candidates, "a candidate was disposed more than once"

    labeled = [o for o in obs if o["disposition"] in (DISPOSITION_POSITIVE, DISPOSITION_NEGATIVE)]
    censored = [o for o in obs if o["disposition"] == DISPOSITION_CENSORED]
    assert len(labeled) + len(censored) == n_candidates

    for o in labeled:
        assert o["target_flip_within_horizon"] in (0, 1)
    for o in censored:
        assert o["target_flip_within_horizon"] is None
        assert o["censor_reason"] in (CENSOR_SESSION_END, CENSOR_DATA_END)


def test_disabling_censoring_labels_the_late_candidates_instead_of_dropping_them():
    """With the policy off, late candidates are still disposed -- as labels, not silence.

    The defect was never 'no censoring'; it was 'no disposition'.
    """
    c = _Collector(session_end_censoring=False)
    T = ct_ns(DAY, "15:14:00")
    c.add_candidate(T)
    c._sweep_elapsed_horizons(T + (HORIZON + 1) * NS)
    assert dispositions(c) == [DISPOSITION_NEGATIVE]


def test_session_close_is_the_canonical_1515_boundary():
    """Censoring is computed against the project-canonical RTH close, not 15:00."""
    close = session_close_ns(ct_ns(DAY, "10:00:00"), "RTH")
    assert pd.Timestamp(close, tz="UTC").tz_convert("America/Chicago").strftime("%H:%M:%S") == "15:15:00"
