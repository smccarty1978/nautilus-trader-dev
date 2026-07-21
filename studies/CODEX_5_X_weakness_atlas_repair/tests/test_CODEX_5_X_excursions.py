from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
sys.path.insert(0, str(UPSTREAM))

from build_weakness_atlas import (  # noqa: E402
    build_weakness_checkpoints_for_regime,
    compute_running_excursions,
)


def test_bullish_favorable_movement_produces_positive_mfe() -> None:
    mfe, _ = compute_running_excursions(1, 100.0, 104.0, 100.0, 2.0)
    assert mfe == pytest.approx(2.0)


def test_bearish_favorable_movement_produces_positive_mfe() -> None:
    mfe, _ = compute_running_excursions(-1, 100.0, 100.0, 94.0, 2.0)
    assert mfe == pytest.approx(3.0)


def test_bullish_adverse_movement_produces_positive_mae() -> None:
    _, mae = compute_running_excursions(1, 100.0, 100.0, 96.0, 2.0)
    assert mae == pytest.approx(2.0)


def test_bearish_adverse_movement_produces_positive_mae() -> None:
    _, mae = compute_running_excursions(-1, 100.0, 106.0, 100.0, 2.0)
    assert mae == pytest.approx(3.0)


@pytest.mark.parametrize("direction", [1, -1])
def test_running_excursions_nonnegative_and_monotonic(direction: int) -> None:
    start = 1_700_000_000_000_000_000
    seconds = np.arange(0, 31, dtype=np.int64)
    idx = pd.to_datetime(start + seconds * 1_000_000_000, unit="ns", utc=True)
    if direction == 1:
        closes = 100.0 + seconds * 0.10
    else:
        closes = 100.0 - seconds * 0.10
    bars = pd.DataFrame({
        "open": closes,
        "high": closes + 0.25,
        "low": closes - 0.25,
        "close": closes,
    }, index=idx)
    records = build_weakness_checkpoints_for_regime(
        direction=direction,
        flip_ts=start,
        flip_close=100.0,
        opp_flip_ts=start + 30_000_000_000,
        atr_val=2.0,
        df_1s_regime=bars,
        df_regimes=pd.DataFrame(),
        step_s=5,
    )
    d = pd.DataFrame(records)
    assert len(d) == 5
    for col in ("current_mfe", "current_mae", "running_mfe", "running_mae"):
        assert (d[col] >= 0).all()
        assert (np.diff(d[col].to_numpy()) >= -1e-12).all()
    assert np.allclose(d["current_mfe"], d["running_mfe"])
    assert np.allclose(d["current_mae"], d["running_mae"])
    assert (d["atr_at_entry"] == 2.0).all()


def test_excursion_input_contract_fails_closed() -> None:
    with pytest.raises(ValueError):
        compute_running_excursions(0, 100.0, 101.0, 99.0, 1.0)
    with pytest.raises(ValueError):
        compute_running_excursions(1, 100.0, 101.0, 99.0, 0.0)
