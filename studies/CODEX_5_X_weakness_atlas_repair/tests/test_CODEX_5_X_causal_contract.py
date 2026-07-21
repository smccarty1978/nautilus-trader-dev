from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(UPSTREAM))

import CODEX_5_X_common as common  # noqa: E402
import CODEX_5_X_train_repaired_w4 as w4  # noqa: E402
from CODEX_5_X_train_repaired_w4 import (  # noqa: E402
    apply_calibration,
    purged_2025_windows,
    score_distribution_and_crossings,
)
from CODEX_5_X_build_repaired_atlas import (  # noqa: E402
    add_legacy_regime_key, attach_last_available_feature_rows,
    classify_noncausal_legacy_only, compute_activity_features_batched,
    compute_sequence_features_batched,
)
from train_weakness_model import SEQUENCE_FEATS  # noqa: E402
from build_regime_sequence import compute_sequence_features  # noqa: E402
from build_weakness_atlas import build_weakness_checkpoints_for_regime  # noqa: E402
from CODEX_5_X_build_regime_history import build_completed_regimes  # noqa: E402


def bars(start: int, count: int = 12) -> pd.DataFrame:
    ts = start + np.arange(count, dtype=np.int64) * common.NS
    px = 100.0 + np.arange(count) * 0.1
    return pd.DataFrame({
        "open": px, "high": px + 0.2, "low": px - 0.2, "close": px,
    }, index=pd.to_datetime(ts, unit="ns", utc=True))


def test_checkpoint_uses_half_open_causal_path_and_excludes_endpoint() -> None:
    start = 1_700_000_000_000_000_000
    d = bars(start)
    d.loc[d.index[5], "high"] = 500.0  # unavailable at checkpoint start+5s
    rows = build_weakness_checkpoints_for_regime(
        1, start, 100.0, start + 10 * common.NS, 2.0, d,
        pd.DataFrame(), step_s=5,
    )
    assert [r["observation_time"] for r in rows] == [start + 5 * common.NS]
    assert rows[0]["current_mfe"] < 1.0
    assert rows[0]["entry_ts_event"] == start
    assert rows[0]["observation_time"] < rows[0]["regime_end_ns"]


def test_completed_regime_uses_start_inclusive_end_exclusive_bars() -> None:
    start = 1_700_000_000_000_000_000
    df_1m = pd.DataFrame({
        "regime": [1, -1, 1],
        "close_ts": [start - 60 * common.NS, start, start + 3 * common.NS],
    })
    d = bars(start, 4)
    d["volume"] = 1.0
    d.loc[d.index[-1], "high"] = 999.0  # bar stamped at end belongs to next regime
    regimes = build_completed_regimes(df_1m, d)
    assert len(regimes) == 1
    assert float(regimes.iloc[0]["start_price"]) == pytest.approx(100.0)
    assert float(regimes.iloc[0]["MFE"]) < 10.0


def test_anchor_must_equal_first_raw_open_at_or_after_flip() -> None:
    start = 1_700_000_000_000_000_000
    with pytest.raises(ValueError, match="anchor mismatch"):
        build_weakness_checkpoints_for_regime(
            1, start, 99.0, start + 10 * common.NS, 2.0, bars(start),
            pd.DataFrame(), step_s=5,
        )


def test_w4_context_uses_last_feature_bar_strictly_before_checkpoint() -> None:
    checkpoints = pd.DataFrame({"observation_time": [10, 20]})
    feature_rows = pd.DataFrame({
        "feature_bar_ts_event": [9, 10, 19, 20],
        "marker": [9, 10, 19, 20],
    })
    out = attach_last_available_feature_rows(checkpoints, feature_rows)
    assert out["marker"].tolist() == [9, 19]


@pytest.mark.parametrize("direction", [1, -1])
def test_batched_sequence_features_equal_rowwise_reference(direction: int) -> None:
    rows = []
    for i in range(15):
        dr = 1 if i % 2 == 0 else -1
        start = i * 100
        rows.append({
            "direction": dr, "start_time": start, "end_time": start + 90,
            "duration": 90.0, "start_price": 100.0 + i,
            "end_price": 100.5 + i, "net_aligned_move": dr * 0.5,
            "MFE": 2.0 + i * 0.1, "MAE": 1.0 + i * 0.05,
            "range": 3.0, "directional_efficiency": 0.5,
            "volume": 1000.0 + i, "regime_center": 100.25 + i,
            "fav_extremes": 2, "adv_extremes": 1,
        })
    regimes = pd.DataFrame(rows)
    cp = pd.DataFrame({
        "regime_start_ns": [2000, 2000, 2000],
        "observation_time": [1600, 1610, 1620],
        "close": [114.0, 114.5, 113.75],
        "atr": [2.0, 2.5, 1.75],
        "direction": [direction] * 3,
    })
    batch = compute_sequence_features_batched(cp, regimes)
    reference = []
    for row in cp.itertuples(index=False):
        record = compute_sequence_features(
            row.observation_time, row.close, row.direction, row.atr, regimes
        )
        reference.append({col: record.get(col, np.nan) for col in SEQUENCE_FEATS})
    reference = pd.DataFrame(reference)
    assert np.allclose(batch.to_numpy(), reference.to_numpy(),
                       rtol=1e-12, atol=1e-12, equal_nan=True)


def test_batched_activity_features_equal_scalar_reference() -> None:
    regimes = pd.DataFrame({
        "end_time": np.arange(1, 21, dtype=np.int64) * 100 * common.NS,
        "duration": np.arange(1, 21, dtype=float) * 7.0,
    })
    cp = pd.DataFrame({
        "observation_time": (
            np.array([550, 950, 1550, 2050], dtype=np.int64) * common.NS
        ),
        "center_spread_5m_30m": [1.0, 2.0, 3.0, 4.0],
        "slope_30m_15m_aligned_atr": [0.1, 0.2, 0.3, 0.4],
    })
    batch = compute_activity_features_batched(cp, regimes)
    scalar = []
    ends = regimes["end_time"].to_numpy(dtype=np.int64)
    durations = regimes["duration"].to_numpy(dtype=float)
    for row in cp.itertuples(index=False):
        right = int(np.searchsorted(ends, row.observation_time, side="right"))
        record = {}
        for window in (5, 15, 30, 60, 120):
            left = int(np.searchsorted(
                ends, row.observation_time - window * 60 * common.NS, side="right"
            ))
            count = right - left
            record[f"activity_regime_count_{window}m"] = count
            if window == 30:
                record["activity_flip_count_30m"] = count
                record["activity_duration_median_30m"] = (
                    float(np.median(durations[left:right])) if count else np.nan
                )
        for count in (3, 5, 10):
            record[f"duration_median_last_{count}"] = (
                float(np.median(durations[right - count:right]))
                if right >= count else np.nan
            )
        record["duration_ratio_3_vs_10"] = (
            record["duration_median_last_3"]
            / (record["duration_median_last_10"] + 1e-8)
        )
        record["duration_ratio_5_vs_10"] = (
            record["duration_median_last_5"]
            / (record["duration_median_last_10"] + 1e-8)
        )
        divisor = max(record["activity_regime_count_30m"], 1)
        record["cross_family_spread_vs_reg_count"] = row.center_spread_5m_30m / divisor
        record["cross_family_slope_vs_reg_count"] = row.slope_30m_15m_aligned_atr / divisor
        scalar.append(record)
    scalar = pd.DataFrame(scalar)[batch.columns]
    assert np.allclose(batch.to_numpy(), scalar.to_numpy(),
                       rtol=1e-12, atol=1e-12, equal_nan=True)


def test_h1_h2_windows_purge_boundary_regime_and_are_disjoint() -> None:
    b = common.SELECTION_END_NS
    h1, crossing, h2 = b - 30, b - 10, b + 1
    val = pd.DataFrame({
        "regime_start_ns": [h1, h1, crossing, crossing, h2, h2],
        "regime_end_ns": [b - 5, b - 5, b + 15, b + 15, b + 30, b + 30],
        "observation_time": [b - 20, b - 10, b - 10, b + 10, b + 10, b + 20],
    })
    selection, calibration, purge = purged_2025_windows(val)
    assert set(selection["regime_start_ns"]) == {h1}
    assert set(calibration["regime_start_ns"]) == {h2}
    assert purge["purged_regime_start_ns"] == [crossing]
    assert set(selection["regime_start_ns"]).isdisjoint(calibration["regime_start_ns"])


def test_invalid_direction_fails_before_calibration() -> None:
    with pytest.raises(RuntimeError, match="direction domain"):
        apply_calibration(np.array([0.2, 0.3]), np.array([1, 0]), {})


def test_checkpoint_identity_includes_reconstructed_regime_start() -> None:
    obs = 1_700_000_100_000_000_000
    legacy = pd.DataFrame({
        "observation_time": [obs, obs], "direction": [1, 1],
        "regime_age": [10.0, 20.0],
    })
    keyed = add_legacy_regime_key(legacy, 2025)
    assert keyed["regime_start_ns"].nunique() == 2


def test_legacy_only_classifier_accepts_only_two_noncausal_classes() -> None:
    d = pd.DataFrame({
        "observation_time": [20, 10],
        "regime_end_ns": [20, 20],
        "entry_ts_event": [10, 10],
    })
    endpoint, no_path = classify_noncausal_legacy_only(d)
    assert endpoint.tolist() == [True, False]
    assert no_path.tolist() == [False, True]


@pytest.mark.parametrize("row", [
    {"observation_time": 15, "regime_end_ns": 20, "entry_ts_event": 10},
    {"observation_time": 20, "regime_end_ns": np.nan, "entry_ts_event": 10},
    {"observation_time": 20, "regime_end_ns": 20, "entry_ts_event": 20},
])
def test_legacy_only_classifier_rejects_unexplained_null_or_overlap(row: dict) -> None:
    with pytest.raises(RuntimeError):
        classify_noncausal_legacy_only(pd.DataFrame([row]))


def test_crossing_state_resets_at_each_regime() -> None:
    d = pd.DataFrame({
        "observation_time": [1, 2, 3, 4],
        "regime_start_ns": [10, 10, 20, 20],
        "direction": [1, 1, 1, 1],
    })
    out = score_distribution_and_crossings(
        d, np.array([0.4, 0.6, 0.7, 0.8]), {1: 0.5, -1: 0.5}, "test"
    )
    assert int(out.iloc[0]["strict_cross_count"]) == 1


def test_failed_manifest_cannot_authorize_2026(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = tmp_path / "manifest.json"
    bundle = tmp_path / "bundle.pkl"
    auth = tmp_path / "auth.json"
    bundle.write_bytes(b"bundle")
    manifest.write_text(json.dumps({
        "status": "FAILED_PRE_2026_GATE", "gate": {"pass": False},
        "bundle_sha256": common.sha256_file(bundle),
    }), encoding="utf-8")
    auth.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(common, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(common, "BUNDLE_PATH", bundle)
    monkeypatch.setattr(common, "PRE_2026_AUTH_PATH", auth)
    with pytest.raises(RuntimeError, match="manifest status"):
        common.require_frozen_pre_2026_contract("unit test")


def test_stale_first_open_ledger_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="ledger contract mismatch"):
        common.validate_existing_first_open(
            {"manifest_sha256": "old"}, {"manifest_sha256": "new"}
        )


def test_first_open_ledger_blocks_refreeze(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "first_open.json"
    ledger.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(w4, "FIRST_2026_OPEN_PATH", ledger)
    with pytest.raises(RuntimeError, match="cannot refreeze"):
        w4.ensure_freeze_allowed()
