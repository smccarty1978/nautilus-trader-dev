"""Pin the gate orientations. The predecessor shipped a backwards Spearman that
would have scored a maximally anti-monotone model as PASSING; it changed no verdict
there, but an un-pinned orientation is a defect waiting for a run where it does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from studies.model_b_low_tail_deterioration.analysis.gates import (MATERIAL_ATR,
                                                                   MIN_SPEARMAN, decide)
from studies.model_b_low_tail_deterioration.implementation.common import (band_mask,
                                                                          low_rank,
                                                                          nested_mask,
                                                                          spearman)


def test_spearman_positive_is_deterioration():
    """Band index 0 is the WORST score. A real deterioration curve therefore has its
    most negative economics at index 0 and RISES with index -> positive rho."""
    deteriorating = np.array([-1.0, -0.8, -0.6, -0.4, -0.2, 0.0, 0.1, 0.2, 0.3, 0.4])
    rho, inv = spearman(deteriorating)
    assert rho == pytest.approx(1.0)
    assert inv == 0
    assert rho >= MIN_SPEARMAN


def test_spearman_negative_is_improvement_and_must_not_pass():
    """The inverted curve -- best economics in the worst-scoring band -- is the exact
    failure the predecessor's backwards gate would have waved through."""
    improving = np.array([0.4, 0.3, 0.2, 0.1, 0.0, -0.2, -0.4, -0.6, -0.8, -1.0])
    rho, inv = spearman(improving)
    assert rho == pytest.approx(-1.0)
    assert rho < MIN_SPEARMAN
    assert inv == 9


def test_inversions_count_downward_steps():
    rho, inv = spearman(np.array([-1.0, -0.5, -0.9, 0.0, 0.5]))
    assert inv == 1


def test_low_rank_is_ascending():
    """Every cut in this study is a LOW-score cut. A descending sort here would
    silently analyse the top tail and reproduce the predecessor's question."""
    p = np.array([0.9, 0.1, 0.5, 0.3])
    assert list(low_rank(p)) == [1, 3, 2, 0]
    m = nested_mask(p, 0.50)
    assert list(p[m]) == [0.1, 0.3]


def test_bands_partition_exactly():
    rng = np.random.default_rng(0)
    p = rng.random(1410)
    masks = [band_mask(p, lo, lo + 10) for lo in range(0, 100, 10)]
    assert sum(m.sum() for m in masks) == 1410
    assert np.all(np.sum(masks, axis=0) == 1)


def test_material_threshold_is_a_worsening_not_an_improvement():
    """`tail_material` must require the tail to be WORSE than the population. A sign
    slip here turns the gate into a test for the opposite finding."""
    curve = pd.DataFrame([
        _c("ALL", 0.0), _c("bottom_20", -MATERIAL_ATR - 0.01),
        _c("bottom_10", -MATERIAL_ATR - 0.01),
    ])
    assert _tail_passed(curve) is True

    better = pd.DataFrame([
        _c("ALL", 0.0), _c("bottom_20", +0.50), _c("bottom_10", +0.50),
    ])
    assert _tail_passed(better) is False


def _c(cut: str, econ: float) -> dict:
    return {"scope": "POOLED", "cut": cut, "cut_basis": "WITHIN_SCOPE",
            "continue_minus_exit_mark_atr": econ, "n_unique_trades": 100,
            "ci95_lo_mark": econ - 0.1, "ci95_hi_mark": econ + 0.1,
            "underpowered": False}


def _tail_passed(curve: pd.DataFrame) -> bool:
    mono = {"DISJOINT_BAND__cme_mark": {"spearman": 1.0, "inversions": 0,
                                        "direction": "DETERIORATION"}}
    empty = pd.DataFrame(columns=["scope", "cut", "cut_basis",
                                  "continue_minus_exit_mark_atr", "underpowered"])
    placebo = pd.DataFrame(columns=["cut", "control", "difference_mark_atr"])
    out = decide(curve, mono, empty, empty, empty, empty,
                 pd.DataFrame(), placebo)
    return out["conditions"]["tail_material"]["passed"]
