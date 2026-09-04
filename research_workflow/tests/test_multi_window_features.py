"""Multi-window parameterization of the window-parameterized feature families.

A study that declares the SAME canonical feature at several windows (the rolling
productivity family at 60s / 120s / 300s, say) must bind every one of them, and each
window's value must be exactly what a single-window study would have produced. Before
this, ``RollingProductivityAdapter`` raised on more than one window, and because
``ProviderHost.from_feature_contract`` groups instances by canonical provider and
constructs ONE adapter per group, that construction failure unbound every rolling alias
in the study -- including the 300s ones that were fine on their own. The compile surface
of that was ``MISSING_CAPABILITY: no runtime adapter renders 'rolling_300s_giveback_atr'``,
which names the wrong feature and hides the real cause.

The decisive test here is ``test_added_windows_do_not_perturb_an_existing_window``:
per-window value identity against a single-window host is what makes adding a window to
an existing study's surface a scientifically inert change.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import pytest

from research_workflow.provider_host import (
    EVENT_REGIME_TRANSITION_1M,
    ProviderHost,
    STREAM_COMPLETED_1S,
)

NS = 1_000_000_000
ATR = 10.0
PREVAILING = 1
DECISION_T = 780

ROLLING_PROVIDER = (
    "features.trackers.generic_rolling_productivity.GenericRollingProductivityProvider"
)
ROLLING_METRICS = (
    "retention_ratio", "current_progress_atr", "max_progress_atr", "giveback_atr",
)


def _price(t: int) -> float:
    """Bullish regime from t=120 with a mid-course giveback, so the 60s / 120s / 300s
    windows genuinely see different progress and giveback (a flat path would let a
    single-window bug pass)."""
    if t <= 120:
        return 20000.0 - 0.25 * t
    if t <= 700:
        return 19970.0 + 0.30 * (t - 120)      # steady climb -> ~20144
    if t <= 900:
        return 20144.0 - 0.22 * (t - 700)      # giveback -> ~20100
    return 20100.0 + 0.18 * (t - 900)          # partial recovery


def _bar(t0: int, t1: int) -> tuple[float, float, float, float]:
    pts = [_price(t) for t in range(t0, t1 + 1)]
    return pts[0], max(pts), min(pts), pts[-1]


def _tape() -> List[tuple[int, str, Dict[str, Any]]]:
    ev: List[tuple[int, str, Dict[str, Any]]] = [
        (0, EVENT_REGIME_TRANSITION_1M, dict(
            direction=-1, start_ns=0, start_price=_price(0), atr_start=ATR,
            prior_end_close=_price(0))),
        (120 * NS, EVENT_REGIME_TRANSITION_1M, dict(
            direction=1, start_ns=120 * NS, start_price=_price(120), atr_start=ATR,
            prior_end_close=_price(119))),
    ]
    for t in range(0, DECISION_T):
        o, h, l, c = _bar(t, t + 1)
        ev.append(((t + 1) * NS, STREAM_COMPLETED_1S, dict(
            ts_init=(t + 1) * NS, open=o, high=h, low=l, close=c,
            volume=100.0 + (t % 11), arm_atr=ATR)))
    ev.sort(key=lambda row: (row[0], 0 if row[1] == EVENT_REGIME_TRANSITION_1M else 1))
    return ev


def _rolling_contract(windows: Sequence[str]) -> Dict[str, Any]:
    """A minimal compiled-study feature contract: the four rolling productivity metrics
    at each declared window, spelled exactly as the compiler resolves them."""
    instances = [
        {
            "canonical_name": f"rolling_{metric}",
            "parameters": {"window": window, "update_every": "1s"},
            "physical_alias": f"rolling_{window}_{metric}",
            "provider": ROLLING_PROVIDER,
            "input_requirements": {"required_streams": [STREAM_COMPLETED_1S]},
        }
        for window in windows
        for metric in ROLLING_METRICS
    ]
    return {"contracts": {"feature_contract": {
        "runtime_data_requirements": {"resolved_instances": instances}}}}


def _snapshot(windows: Sequence[str]) -> Dict[str, Any]:
    host = ProviderHost.from_feature_contract(_rolling_contract(windows))
    assert not host._unbound, f"unbound aliases for windows={list(windows)}: {host._unbound}"
    for ts, event_type, payload in _tape():
        if ts > DECISION_T * NS:
            break
        host.dispatch(event_type, payload)
    return dict(host.snapshot(
        decision_ts=DECISION_T * NS, price=_price(DECISION_T), atr=ATR,
        episode_state=dict(
            prevailing_direction=PREVAILING,
            family_a_atr=ATR,
            regime_expansion_atr_per_min=0.35,
        ),
    ))


def test_three_rolling_windows_all_bind_and_emit():
    snap = _snapshot(("60s", "120s", "300s"))
    expected = {f"rolling_{w}_{m}" for w in ("60s", "120s", "300s") for m in ROLLING_METRICS}
    assert expected <= set(snap), f"missing aliases: {sorted(expected - set(snap))}"
    assert all(snap[a] is not None for a in expected), \
        f"null aliases: {sorted(a for a in expected if snap[a] is None)}"


def test_windows_are_independent_not_one_window_reused():
    """Distinct windows must produce distinct values on a path with a mid-course
    giveback -- otherwise a single provider silently answering for every window would
    pass every other assertion here."""
    snap = _snapshot(("60s", "120s", "300s"))
    for metric in ROLLING_METRICS:
        values = [snap[f"rolling_{w}_{metric}"] for w in ("60s", "120s", "300s")]
        assert len(set(values)) == 3, f"{metric} collapsed across windows: {values}"


@pytest.mark.parametrize("window", ["60s", "120s", "300s"])
def test_added_windows_do_not_perturb_an_existing_window(window):
    """Per-window value identity: declaring 60s+120s+300s must give each window exactly
    what it would have had alone. This is what makes widening a study's rolling surface
    inert for the windows already in it."""
    alone = _snapshot((window,))
    together = _snapshot(("60s", "120s", "300s"))
    for metric in ROLLING_METRICS:
        alias = f"rolling_{window}_{metric}"
        assert together[alias] == alone[alias], (
            f"{alias} changed when other windows were added: "
            f"alone={alone[alias]!r} together={together[alias]!r}")


def test_single_window_still_binds():
    """The pre-existing one-window path is unchanged."""
    snap = _snapshot(("300s",))
    assert {f"rolling_300s_{m}" for m in ROLLING_METRICS} <= set(snap)
