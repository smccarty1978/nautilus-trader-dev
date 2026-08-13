"""Build the exact machine-readable annex required by BUILD_REPORT."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .run_phase_a_collect import ROOT, atomic_json, sha256_file


BASE = ROOT / "studies/full_trade_path_builder"


def main() -> None:
    score_months = []
    score_frames = []
    for path in sorted((BASE / "_work/phase_b_monthly").glob("year=*/month=*/canonical_model_scores.parquet")):
        frame = pq.read_table(
            path,
            columns=[
                "session",
                "confirmed_regime_direction",
                "bullish_score_available",
                "bearish_score_available",
                "bullish_in_domain",
                "bearish_in_domain",
            ],
        ).to_pandas()
        score_frames.append(frame)
        score_months.append(
            {
                "year": int(path.parent.parent.name.split("=")[1]),
                "month": int(path.parent.name.split("=")[1]),
                "rows": len(frame),
                "rth_rows": int((frame.session == "RTH").sum()),
                "bullish_regime_rows": int((frame.confirmed_regime_direction == 1).sum()),
                "bearish_regime_rows": int((frame.confirmed_regime_direction == -1).sum()),
                "both_models_available_rows": int(
                    (frame.bullish_score_available & frame.bearish_score_available).sum()
                ),
                "bullish_in_domain_rows": int(frame.bullish_in_domain.sum()),
                "bearish_in_domain_rows": int(frame.bearish_in_domain.sum()),
            }
        )
    scores = pd.concat(score_frames, ignore_index=True)
    availability = []
    for direction in (-1, 1):
        frame = scores[scores.confirmed_regime_direction == direction]
        availability.append(
            {
                "regime_direction": direction,
                "rows": len(frame),
                "both_models_available_rows": int(
                    (frame.bullish_score_available & frame.bearish_score_available).sum()
                ),
                "bullish_available_rows": int(frame.bullish_score_available.sum()),
                "bearish_available_rows": int(frame.bearish_score_available.sum()),
                "bullish_in_domain_rows": int(frame.bullish_in_domain.sum()),
                "bearish_in_domain_rows": int(frame.bearish_in_domain.sum()),
                "bullish_exploratory_available_rows": int(
                    (frame.bullish_score_available & ~frame.bullish_in_domain).sum()
                ),
                "bearish_exploratory_available_rows": int(
                    (frame.bearish_score_available & ~frame.bearish_in_domain).sum()
                ),
            }
        )
    path_inventory = []
    for manifest_path in sorted(
        (BASE / "canonical_trade_paths").glob(
            "entry_year=*/entry_month=*/trade_direction=*/trade_id_prefix=*/manifest.json"
        )
    ):
        manifest = json.loads(manifest_path.read_text())
        data_path = manifest_path.with_name("part-00000.parquet")
        path_inventory.append(
            {
                "partition": str(manifest_path.parent.relative_to(BASE)),
                "row_count": manifest["row_count"],
                "trade_count": manifest["trade_count"],
                "compressed_bytes": data_path.stat().st_size,
                "output_sha256": manifest["output_sha256"],
            }
        )
    summaries = pd.concat(
        [
            pq.read_table(path).to_pandas()
            for path in (BASE / "_work/phase_d_monthly").glob(
                "entry_year=*/entry_month=*/trade_population.parquet"
            )
        ],
        ignore_index=True,
    )
    false_warnings = []
    for label, field in (
        ("top_10", "opposite_first_top_10_ns"),
        ("top_5", "opposite_first_top_5_ns"),
        ("top_2_5", "opposite_first_top_2_5_ns"),
    ):
        warned = summaries[summaries[field].notna()].copy()
        fallback_seconds = (warned.fallback_exit_flip_ns - warned[field]) / 1e9
        censor_seconds = (warned.censor_ns - warned[field]) / 1e9
        true_warning = warned.path_is_complete & (fallback_seconds <= 600)
        eligible = warned.path_is_complete | (
            ~warned.path_is_complete & (censor_seconds >= 600)
        )
        false_warning = eligible & ~true_warning
        false_warnings.append(
            {
                "threshold": label,
                "warned": len(warned),
                "eligible_with_600s_outcome": int(eligible.sum()),
                "fallback_within_600s": int((true_warning & eligible).sum()),
                "false_warnings": int(false_warning.sum()),
                "false_warning_rate": float(false_warning.sum() / eligible.sum()),
                "definition": (
                    "A warning is false when no accepted fallback flip is observed "
                    "within 600 seconds after warning. Censored observations with "
                    "less than 600 seconds of follow-up are excluded."
                ),
            }
        )
    payload = {
        "model_and_adapter_hashes": {
            "bullish_model": sha256_file(
                BASE / "artifacts/BULLISH_STRICT_top25_gbt_v2/model.joblib"
            ),
            "bullish_adapter": sha256_file(
                BASE / "artifacts/BULLISH_STRICT_top25_gbt_v2/adapter.py"
            ),
            "bearish_model": sha256_file(
                ROOT
                / "studies/freeze_long_strict_models_v2/artifacts/"
                "LONG_STRICT_top25_gbt_v2/model.joblib"
            ),
            "dual_runtime_adapter": sha256_file(
                BASE / "implementation/phase_b_adapter.py"
            ),
        },
        "score_rows_by_month_session_regime": score_months,
        "model_availability_and_domain_by_regime": availability,
        "canonical_path_partition_inventory": path_inventory,
        "false_warning_analysis": false_warnings,
    }
    atomic_json(payload, BASE / "results/build_report_inventory.json")


if __name__ == "__main__":
    main()
