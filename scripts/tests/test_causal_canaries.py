"""Tests for causal canaries in utils/causal_canaries.py.
=====================================================
"""

import sys
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.causal_canaries import (
    run_prefix_invariance_test,
    run_future_mutation_canary,
    generate_boundary_fixture,
    PrefixInvarianceViolation,
    FutureMutationLeak,
)


def test_causal_indicator_passes_canaries():
    """A standard causal rolling indicator passes both canaries."""
    df = generate_boundary_fixture(periods=300)

    def causal_fn(data: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=data.index)
        out["sma_10"] = data["close"].rolling(10).mean()
        out["cum_vol"] = data["volume"].cumsum()
        return out

    t_cut = df.index[150]
    assert run_prefix_invariance_test(causal_fn, df, t_cut) is True
    assert run_future_mutation_canary(causal_fn, df, t_cut) is True


def test_noncausal_centered_rolling_fails_canaries():
    """Centered rolling looks forward and must fail both canaries."""
    df = generate_boundary_fixture(periods=300)

    def leaky_fn(data: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=data.index)
        out["centered_sma"] = data["close"].rolling(10, center=True).mean()
        return out

    t_cut = df.index[150]
    with pytest.raises(PrefixInvarianceViolation):
        run_prefix_invariance_test(leaky_fn, df, t_cut)

    with pytest.raises(FutureMutationLeak):
        run_future_mutation_canary(leaky_fn, df, t_cut)


def test_negative_shift_fails_future_mutation_canary():
    """Negative shift looks ahead into the next row and must fail."""
    df = generate_boundary_fixture(periods=300)

    def leaky_shift_fn(data: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=data.index)
        out["next_close"] = data["close"].shift(-1)
        return out

    t_cut = df.index[150]
    with pytest.raises(FutureMutationLeak):
        run_future_mutation_canary(leaky_shift_fn, df, t_cut)
