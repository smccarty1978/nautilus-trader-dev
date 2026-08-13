"""The vectorised trade-clustered bootstrap equals the concatenation form exactly.

`common.trade_clustered_ci` replaced a literal "concatenate each drawn trade's
observations and take the mean" loop with a sufficient-statistic form. That is a
performance change to a number the study's confidence intervals depend on, so
the equality is asserted rather than asserted-in-a-comment.
"""
from __future__ import annotations

import numpy as np
import pytest

from studies.post_confirm_retracement_recovery.implementation.common import (
    N_BOOT, SEED, UNDERPOWERED_TRADES, trade_clustered_ci,
)


def _reference(values, trades, seed=SEED, n_boot=N_BOOT):
    """The original concatenation implementation, kept only as an oracle."""
    uniq, inv = np.unique(np.asarray(trades), return_inverse=True)
    if uniq.size < UNDERPOWERED_TRADES:
        return None, None
    rng = np.random.default_rng(seed)
    parts = [np.asarray(values, float)[inv == i] for i in range(uniq.size)]
    draws = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, uniq.size, uniq.size)
        draws[b] = np.concatenate([parts[i] for i in pick]).mean()
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


@pytest.mark.parametrize("n_trades,max_obs", [(25, 1), (40, 6), (120, 3)])
def test_matches_concatenation_form(n_trades, max_obs):
    """Unequal cluster sizes are the case where the two forms could diverge."""
    rng = np.random.default_rng(7)
    trades, values = [], []
    for t in range(n_trades):
        for _ in range(rng.integers(1, max_obs + 1)):
            trades.append(f"RGM_{t:04d}")
            values.append(float(rng.normal(0.1, 1.0)))
    trades = np.array(trades)
    values = np.array(values)

    got = trade_clustered_ci(values, trades)
    want = _reference(values, trades)
    assert got[0] == pytest.approx(want[0], abs=1e-12)
    assert got[1] == pytest.approx(want[1], abs=1e-12)


def test_underpowered_cells_emit_null():
    """Fewer than UNDERPOWERED_TRADES clusters yields no interval, not a narrow one."""
    trades = np.array([f"RGM_{i}" for i in range(UNDERPOWERED_TRADES - 1)])
    values = np.arange(trades.size, dtype=float)
    assert trade_clustered_ci(values, trades) == (None, None)


def test_empty_input_is_null_not_an_error():
    assert trade_clustered_ci(np.array([]), np.array([])) == (None, None)
