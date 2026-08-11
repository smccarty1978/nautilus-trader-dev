"""The monotonicity gate must not be able to pass a maximally BAD model.

This test exists because the first implementation of `_spearman` reversed the
tightness axis, so a perfectly anti-monotone bucket table scored +1 with zero
inversions. No verdict depended on it, but a gate that rewards the wrong shape is
worse than no gate.
"""
import numpy as np

from studies.p80_p90_opportunity_continuation_ml.analysis.gates import _spearman

# Buckets always arrive LOOSEST -> TIGHTEST: top_50, top_25, top_20, top_10,
# top_5, top_2_5, top_1.


def test_perfect_concentration_scores_plus_one_with_no_inversions():
    good = np.array([31.0, 33.0, 35.0, 38.0, 42.0, 47.0, 55.0])
    sp, inv = _spearman(good)
    assert sp == 1.0
    assert inv == 0


def test_perfect_anti_concentration_scores_minus_one_and_fails():
    bad = np.array([55.0, 47.0, 42.0, 38.0, 35.0, 33.0, 31.0])
    sp, inv = _spearman(bad)
    assert sp == -1.0
    assert inv == 6
    assert not (sp >= 0.80 and inv <= 1)      # the A-1 / B-2 condition


def test_observed_p90_win_rate_shape_fails_the_gate():
    """The actual 2024 P90 WIN% tail: rises to top_20 then collapses."""
    observed = np.array([31.97, 33.18, 34.09, 32.95, 29.55, 22.73, 11.11])
    sp, inv = _spearman(observed)
    assert sp < 0
    assert inv == 4
    assert not (sp >= 0.80 and inv <= 1)


def test_scale_rises_even_though_sign_does_not():
    """MFE300 concentrates where WIN% does not -- the study's central finding.

    Over the seven tail buckets MFE300 rises monotonically through top_2_5 and
    only breaks at top_1, which holds 9 candidates. WIN% is negatively ranked over
    the same buckets. The claim is the CONTRAST, not that MFE is perfectly ordered.
    """
    mfe = np.array([1.094, 1.179, 1.198, 1.271, 1.364, 1.392, 1.160])
    win = np.array([31.97, 33.18, 34.09, 32.95, 29.55, 22.73, 11.11])
    sp_mfe, inv_mfe = _spearman(mfe)
    sp_win, _ = _spearman(win)
    assert sp_mfe > 0 > sp_win
    assert inv_mfe == 1                       # the single break is top_1, n=9
    assert np.all(np.diff(mfe[:-1]) > 0)      # strictly rising up to top_2_5
