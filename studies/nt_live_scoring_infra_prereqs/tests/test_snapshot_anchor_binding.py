"""Phase 2 (post-audit addition) -- tests for `bind_snapshot_anchor`/
`effective_snapshot_anchor`, the codified mechanism closing the
completion-gate audit's Warning ("SPEC-mandated snapshot_anchor binding
mechanism was not delivered")."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from features.registry import (  # noqa: E402
    FEATURE_REGISTRY, bind_snapshot_anchor, effective_snapshot_anchor,
)


def test_default_snapshot_anchor_is_the_registry_class_default_before_any_binding():
    assert effective_snapshot_anchor("bar_volume", "some_study_that_never_bound_it") == \
        FEATURE_REGISTRY["bar_volume"].snapshot_anchor


def test_bind_and_read_back_a_study_specific_anchor():
    bind_snapshot_anchor("bar_volume", "test_study_A", "at_signal_decision_ts")
    assert effective_snapshot_anchor("bar_volume", "test_study_A") == "at_signal_decision_ts"
    # unrelated study's binding is unaffected
    assert effective_snapshot_anchor("bar_volume", "test_study_B") == \
        FEATURE_REGISTRY["bar_volume"].snapshot_anchor


def test_bindings_are_per_study_not_global():
    bind_snapshot_anchor("bar_volume", "test_study_C", "at_touch_time")
    bind_snapshot_anchor("bar_volume", "test_study_D", "at_fill_time")
    assert effective_snapshot_anchor("bar_volume", "test_study_C") == "at_touch_time"
    assert effective_snapshot_anchor("bar_volume", "test_study_D") == "at_fill_time"


def test_binding_an_unregistered_feature_raises():
    with pytest.raises(KeyError):
        bind_snapshot_anchor("this_feature_does_not_exist", "test_study", "at_touch_time")


def test_querying_an_unregistered_feature_raises():
    with pytest.raises(KeyError):
        effective_snapshot_anchor("this_feature_does_not_exist", "test_study")
