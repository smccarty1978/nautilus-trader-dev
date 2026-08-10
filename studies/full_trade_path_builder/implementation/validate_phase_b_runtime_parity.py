"""Fresh Phase B builder-vector and probability parity against frozen offline rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .phase_b_adapter import FrozenBearishScorer, vector_sha256
from .phase_a_runtime import FrozenBullishScorer
from .run_phase_a_collect import atomic_json

ROOT = Path(__file__).resolve().parents[3]


def validate(phase_b_scores: Path, output: Path) -> dict:
    actual = pq.read_table(phase_b_scores).to_pandas()
    missing_path = phase_b_scores.parent / "missing_dispatch.parquet"
    missing_dispatch = set(
        pq.read_table(missing_path, columns=["checkpoint_decision_ns"])
        .column("checkpoint_decision_ns").to_pylist()
    )
    if actual["checkpoint_decision_ns"].duplicated().any():
        raise RuntimeError("duplicate Phase B checkpoint keys")
    bull_dir = ROOT / "studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2"
    bear_dir = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2"
    bull_scorer, bear_scorer = FrozenBullishScorer(bull_dir), FrozenBearishScorer(bear_dir)

    bull_ref = pq.read_table(
        ROOT / "studies/full_trade_path_builder/_work/phase_a_monthly/"
        "year=2025/month=03/checkpoints.parquet"
    ).to_pandas()
    bull_ref = bull_ref.drop_duplicates("checkpoint_decision_ns")
    bull = actual.merge(
        bull_ref[["checkpoint_decision_ns", *bull_scorer.features]],
        on="checkpoint_decision_ns", how="inner", suffixes=("", "__ref"),
    )
    if len(bull) != len(bull_ref):
        missing = set(bull_ref.checkpoint_decision_ns) - set(actual.checkpoint_decision_ns)
        raise RuntimeError(f"Bullish reference-key coverage failure: {len(missing)} missing")
    bull_actual = bull[[f"bullish__{f}" for f in bull_scorer.features]].to_numpy(float)
    bull_expected = bull[bull_scorer.features].to_numpy(float)
    bull_null_parity = np.array_equal(np.isnan(bull_actual), np.isnan(bull_expected))
    bull_complete = np.isfinite(bull_expected).all(axis=1)
    bull_actual, bull_expected = bull_actual[bull_complete], bull_expected[bull_complete]
    bull_vector_mismatch = int(np.count_nonzero(~np.isclose(
        bull_actual, bull_expected, rtol=0, atol=0, equal_nan=True
    )))
    bull_expected_p = bull_scorer.model.predict_proba(bull_expected)[:, 1]
    bull_actual_p = bull.loc[bull_complete, "bullish_probability"].to_numpy(float)
    bull_hash_parity = (
        bull.loc[bull_complete, "bullish_feature_vector_hash"].tolist()
        == [vector_sha256(row.tolist()) for row in bull_expected]
    )

    bear_ref = pq.read_table(
        ROOT / "studies/long_rth_strict_symmetric_retrain/_work/monthly/"
        "2025/2025-03.parquet",
        columns=["observation_time", *bear_scorer.features],
    ).to_pandas()
    bear_local = pd.to_datetime(bear_ref["observation_time"], unit="ns", utc=True).dt.tz_convert(
        "America/Chicago"
    )
    bear_ref = bear_ref[
        ((bear_local.dt.hour * 60 + bear_local.dt.minute) >= 510)
        & ((bear_local.dt.hour * 60 + bear_local.dt.minute) < 900)
    ].drop_duplicates("observation_time")
    bear = actual.merge(
        bear_ref, left_on="checkpoint_decision_ns", right_on="observation_time",
        how="inner", suffixes=("", "__ref"),
    )
    missing = set(bear_ref.observation_time) - set(actual.checkpoint_decision_ns)
    unexplained_missing = missing - missing_dispatch
    if unexplained_missing:
        raise RuntimeError(
            f"Bearish reference-key coverage failure: "
            f"{len(unexplained_missing)} missing without exact-dispatch diagnosis"
        )
    bear_ref = bear_ref[~bear_ref.observation_time.isin(missing)]
    bear = actual.merge(
        bear_ref, left_on="checkpoint_decision_ns", right_on="observation_time",
        how="inner", suffixes=("", "__ref"),
    )
    if len(bear) != len(bear_ref):
        raise RuntimeError("Bearish matched-key count differs after dispatch reconciliation")
    bear_actual = bear[[f"bearish__{f}" for f in bear_scorer.features]].to_numpy(float)
    bear_expected = bear[bear_scorer.features].to_numpy(float)
    bear_null_parity = np.array_equal(np.isnan(bear_actual), np.isnan(bear_expected))
    bear_complete = np.isfinite(bear_expected).all(axis=1)
    bear_actual, bear_expected = bear_actual[bear_complete], bear_expected[bear_complete]
    bear_vector_mismatch = int(np.count_nonzero(~np.isclose(
        bear_actual, bear_expected, rtol=0, atol=1e-12, equal_nan=True
    )))
    bear_expected_p = bear_scorer.model.predict_proba(bear_expected)[:, 1]
    bear_actual_p = bear.loc[bear_complete, "bearish_probability"].to_numpy(float)
    bear_hash_parity = (
        bear.loc[bear_complete, "bearish_feature_vector_hash"].tolist()
        == [vector_sha256(row.tolist()) for row in bear_expected]
    )
    result = {
        "status": "pass" if (
            len(bull_actual) and len(bear_actual)
            and bull_null_parity and bear_null_parity
            and bull_hash_parity and bear_hash_parity
            and bull_vector_mismatch == 0 and bear_vector_mismatch == 0
            and np.array_equal(bull_actual_p, bull_expected_p)
            and np.allclose(bear_actual_p, bear_expected_p, rtol=0, atol=1e-15)
            and np.array_equal(
                bull.loc[bull_complete, "bullish_raw_score"].to_numpy(float),
                bull_actual_p,
            )
            and np.array_equal(
                bear.loc[bear_complete, "bearish_raw_score"].to_numpy(float),
                bear_actual_p,
            )
            and actual[[
                "bullish_percentile", "bullish_decile", "bullish_is_top_10",
                "bullish_is_top_5", "bullish_is_top_2_5", "bearish_percentile",
                "bearish_decile", "bearish_is_top_10", "bearish_is_top_5",
                "bearish_is_top_2_5",
            ]].isna().all().all()
        ) else "fail",
        "actual_unique_checkpoint_rows": len(actual),
        "bullish_expected_keys": len(bull_ref),
        "bullish_matched_keys": len(bull),
        "bullish_rows": len(bull_actual),
        "bullish_null_mask_parity": bool(bull_null_parity),
        "bullish_feature_hash_parity": bool(bull_hash_parity),
        "bullish_vector_value_mismatches": bull_vector_mismatch,
        "bullish_probability_max_abs_diff": float(np.max(np.abs(bull_actual_p-bull_expected_p))),
        "bearish_expected_keys": len(bear_ref),
        "bearish_matched_keys": len(bear),
        "bearish_reference_keys_omitted_for_missing_exact_dispatch": len(missing),
        "bearish_rows": len(bear_actual),
        "bearish_null_mask_parity": bool(bear_null_parity),
        "bearish_feature_hash_parity": bool(bear_hash_parity),
        "bearish_vector_value_mismatches": bear_vector_mismatch,
        "bearish_probability_max_abs_diff": float(np.max(np.abs(bear_actual_p-bear_expected_p))),
    }
    atomic_json(result, output)
    if result["status"] != "pass":
        raise RuntimeError(json.dumps(result))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scores", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    print(json.dumps(validate(Path(a.scores), Path(a.output)), indent=2))


if __name__ == "__main__":
    main()
