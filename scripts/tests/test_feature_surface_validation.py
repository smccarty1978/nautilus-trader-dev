"""Regression tests for declared-feature-vs-produced-surface binding (Finding C1).

The historical failure: a run recorded ``COMPLETED`` / ``SUCCESS`` with 1748 candidates
whose declared feature ``latest_1m_wick_imbalance`` was NULL in every single row. The
feature checks in place at the time compared column *names*, counts and an ordered hash
-- all of which an all-null column satisfies perfectly.

The central rule these tests pin down is that ``null_policy='allow'`` permits *some*
nulls and never *all* of them. "Sometimes unavailable" and "never emitted" are different
facts, and only the first is what a permissive null policy is for.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.check_feature_surface import (
    FeatureSurfaceError,
    assert_feature_surface,
    validate_feature_surface,
)


class _FDef:
    """Minimal stand-in for a registry FeatureDefinition."""

    def __init__(self, name, null_policy="disallow", dtype="float64", status="verified"):
        self.name = name
        self.null_policy = null_policy
        self.dtype = dtype
        self.status = status


ALLOW = {"f": _FDef("f", null_policy="allow")}
DISALLOW = {"f": _FDef("f", null_policy="disallow")}


def _codes(report):
    return {f["code"] for f in report.findings}


# ---------------------------------------------------------------------------
# The historical failure fixture
# ---------------------------------------------------------------------------

def test_all_null_declared_feature_blocks_even_under_allow():
    """C1.1 -- reproduces the cf80295f-shaped failure and refuses it.

    Feature declared, tracker registered, runtime emits nothing: the column exists, the
    count is right, the ordered hash matches, and every value is null.
    """
    df = pd.DataFrame({"observation_ts": [1, 2, 3], "f": [None, None, None]})
    report = validate_feature_surface(df, ["f"], ALLOW)
    assert not report.passed
    assert "FEATURE_NEVER_EMITTED" in _codes(report)


def test_all_null_blocks_under_disallow_too():
    df = pd.DataFrame({"f": [None, None]})
    report = validate_feature_surface(df, ["f"], DISALLOW)
    assert not report.passed
    assert "FEATURE_NEVER_EMITTED" in _codes(report)


def test_assert_wrapper_raises_on_the_historical_failure():
    df = pd.DataFrame({"f": [None, None]})
    with pytest.raises(FeatureSurfaceError, match="FEATURE_NEVER_EMITTED"):
        assert_feature_surface(df, ["f"], ALLOW)


# ---------------------------------------------------------------------------
# Null policy is consumed, not overridden with "no nulls anywhere"
# ---------------------------------------------------------------------------

def test_partial_nulls_are_accepted_when_the_policy_allows_them():
    """C1.2 -- warmup nulls are legitimate and must NOT be banned outright."""
    df = pd.DataFrame({"f": [None, 0.5, -0.2]})
    report = validate_feature_surface(df, ["f"], ALLOW)
    assert report.passed, report.findings
    assert report.per_feature["f"]["null_count"] == 1
    assert report.per_feature["f"]["null_fraction"] == pytest.approx(1 / 3)


def test_partial_nulls_are_refused_when_the_policy_disallows_them():
    df = pd.DataFrame({"f": [None, 0.5, -0.2]})
    report = validate_feature_surface(df, ["f"], DISALLOW)
    assert not report.passed
    assert "FEATURE_NULL_POLICY_VIOLATION" in _codes(report)


def test_fully_populated_surface_passes():
    df = pd.DataFrame({"f": [0.1, 0.5, -0.2]})
    assert validate_feature_surface(df, ["f"], DISALLOW).passed


# ---------------------------------------------------------------------------
# Identity, substitution, binding, dtype
# ---------------------------------------------------------------------------

def test_missing_column_blocks():
    df = pd.DataFrame({"observation_ts": [1]})
    report = validate_feature_surface(df, ["f"], ALLOW)
    assert not report.passed
    assert "FEATURE_COLUMN_MISSING" in _codes(report)


def test_undeclared_substitution_blocks():
    """A different feature standing in for the declared one is not the declared one."""
    df = pd.DataFrame({"other": [0.1, 0.2]})
    report = validate_feature_surface(df, ["f"], ALLOW)
    assert not report.passed
    assert {"FEATURE_COLUMN_MISSING", "FEATURE_SURFACE_IDENTITY_MISMATCH"} & _codes(report)


def test_reordered_features_block():
    """Ordered feature identity is part of the contract, so order is checked."""
    reg = {"a": _FDef("a"), "b": _FDef("b")}
    df = pd.DataFrame({"b": [1.0], "a": [2.0]})
    report = validate_feature_surface(df, ["a", "b"], reg)
    assert not report.passed
    assert "FEATURE_SURFACE_IDENTITY_MISMATCH" in _codes(report)


def test_unregistered_feature_blocks():
    df = pd.DataFrame({"ghost": [1.0]})
    report = validate_feature_surface(df, ["ghost"], {})
    assert not report.passed
    assert "FEATURE_NOT_REGISTERED" in _codes(report)


def test_incompatible_dtype_blocks():
    reg = {"f": _FDef("f", null_policy="allow", dtype="float64")}
    df = pd.DataFrame({"f": ["a", "b"]})
    report = validate_feature_surface(df, ["f"], reg)
    assert not report.passed
    assert "FEATURE_DTYPE_INCOMPATIBLE" in _codes(report)


def test_no_declared_features_is_a_no_op():
    assert validate_feature_surface(pd.DataFrame({"x": [1]}), [], {}).passed


def test_constant_column_is_reported_but_not_failed():
    """A stuck tracker is worth seeing; it is not by itself a contract breach."""
    df = pd.DataFrame({"f": [0.0, 0.0, 0.0]})
    report = validate_feature_surface(df, ["f"], ALLOW)
    assert report.passed
    assert report.per_feature["f"]["distinct_non_null"] == 1


# ---------------------------------------------------------------------------
# The real registry entry behaves as these tests assume
# ---------------------------------------------------------------------------

def test_real_wick_feature_binds_through_the_real_registry():
    from features.registry import FEATURE_REGISTRY

    df = pd.DataFrame({"latest_1m_wick_imbalance": [None, 0.3, -0.5]})
    report = validate_feature_surface(df, ["latest_1m_wick_imbalance"], FEATURE_REGISTRY)
    assert report.passed, report.findings

    all_null = pd.DataFrame({"latest_1m_wick_imbalance": [None, None, None]})
    bad = validate_feature_surface(all_null, ["latest_1m_wick_imbalance"], FEATURE_REGISTRY)
    assert not bad.passed
    assert "FEATURE_NEVER_EMITTED" in _codes(bad)
