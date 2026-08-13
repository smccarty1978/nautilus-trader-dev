"""Materialize the frozen model-threshold contract table.

Both frozen calibration populations are reconstructed exactly from their
originating training artifacts, rescored with the frozen model binaries, and
quantiled with the recorded method. Every threshold that was already frozen
upstream is reproduced and asserted bit-exact before any new percentile is
emitted; a mismatch aborts the build rather than writing a derived value.

No threshold is derived from study outcomes. The calibration populations are
calendar-2025 and therefore overlap the 2021-2025 evaluation window; every
emitted row carries `overlaps_evaluation_window` so the disclosure cannot be
lost downstream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[3]

# Frozen upstream values. Every one of these must be reproduced exactly.
FROZEN_REFERENCE = {
    "BULLISH_STRICT_top25_gbt_v2": {
        "top_10": 0.43167249785595935,
        "top_5": 0.5067081427626979,
        "top_2_5": 0.5697449423968936,
    },
    "LONG_STRICT_top25_gbt_v2": {
        "top_5": 0.5084619230529974,
        "top_2_5": 0.5641320087327389,
    },
}

# Ordered (label, upper-tail fraction). Frozen levels first is not required;
# ordering here only controls row order in the emitted table.
PERCENTILES = (
    ("top_20", 0.20),
    ("top_10", 0.10),
    ("top_5", 0.05),
    ("top_2_5", 0.025),
    ("top_1", 0.01),
    ("top_0_5", 0.005),
)

QUANTILE_METHOD = "linear"
TIE_POLICY = "inclusive_ge_membership_operator"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_float64(values: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(values.astype("<f8"))
    return hashlib.sha256(contiguous.tobytes()).hexdigest()


def _load_bullish_population() -> tuple[np.ndarray, dict]:
    """Bullish calibration population: all feature-complete in-domain
    established bullish RTH checkpoints of 2025 (Phase A collector output)."""
    adapter_features = json.loads(
        (
            REPO_ROOT
            / "studies/freeze_long_strict_models_v2/artifacts"
            / "LONG_STRICT_top25_gbt_v2/feature_list.json"
        ).read_text()
    )
    source = (
        "studies/full_trade_path_builder/_work/phase_a_monthly/"
        "year=2025/month=*/checkpoints.parquet"
    )
    frame = (
        pl.scan_parquet(REPO_ROOT / source)
        .filter(pl.col("feature_complete"))
        .select(["checkpoint_decision_ns", *adapter_features])
        .sort("checkpoint_decision_ns")
        .collect()
    )
    provenance = {
        "calibration_population_id": "BULLISH_2025_RTH_ESTABLISHED_INDOMAIN_COMPLETE",
        "population_description": (
            "all feature-complete in-domain established bullish RTH checkpoints"
        ),
        "source_glob": source,
        "row_filter": "feature_complete == true",
        "deterministic_sort": "checkpoint_decision_ns",
        "key_column": "checkpoint_decision_ns",
    }
    keys = frame["checkpoint_decision_ns"].to_numpy()
    provenance["population_key_sha256"] = hashlib.sha256(
        np.ascontiguousarray(keys.astype("<i8")).tobytes()
    ).hexdigest()
    return frame.select(adapter_features).to_numpy(), provenance


def _load_bearish_population() -> tuple[np.ndarray, dict]:
    """Bearish calibration population: the frozen 2025 development population
    of the LONG_STRICT symmetric retrain."""
    adapter_features = json.loads(
        (
            REPO_ROOT
            / "studies/freeze_long_strict_models_v2/artifacts"
            / "LONG_STRICT_top25_gbt_v2/feature_list.json"
        ).read_text()
    )
    source = "studies/long_rth_strict_symmetric_retrain/_work/monthly/2025/2025-*.parquet"
    frame = (
        pl.scan_parquet(REPO_ROOT / source)
        .select(["observation_time", *adapter_features])
        .sort("observation_time")
        .collect()
    )
    provenance = {
        "calibration_population_id": "BEARISH_2025_DEVELOPMENT_POPULATION",
        "population_description": (
            "frozen 2025 development population of the LONG_STRICT symmetric retrain"
        ),
        "source_glob": source,
        "row_filter": "none",
        "deterministic_sort": "observation_time",
        "key_column": "observation_time",
    }
    keys = frame["observation_time"].to_numpy().astype("datetime64[ns]").astype("<i8")
    provenance["population_key_sha256"] = hashlib.sha256(
        np.ascontiguousarray(keys).tobytes()
    ).hexdigest()
    return frame.select(adapter_features).to_numpy(), provenance


MODELS = {
    "BULLISH_STRICT_top25_gbt_v2": {
        "model_path": (
            "studies/full_trade_path_builder/artifacts/"
            "BULLISH_STRICT_top25_gbt_v2/model.joblib"
        ),
        "source_artifact": (
            "studies/full_trade_path_builder/artifacts/"
            "BULLISH_STRICT_top25_gbt_v2/thresholds.json"
        ),
        "domain_name": "established_bullish_rth_confirmed_regime",
        "entry_direction": -1,
        "loader": _load_bullish_population,
    },
    "LONG_STRICT_top25_gbt_v2": {
        "model_path": (
            "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/model.joblib"
        ),
        "source_artifact": (
            "studies/freeze_long_strict_models_v2/artifacts/"
            "LONG_STRICT_top25_gbt_v2/metrics_2025.json"
        ),
        "domain_name": "established_bearish_rth_confirmed_regime",
        "entry_direction": 1,
        "loader": _load_bearish_population,
    },
}


def build(out_dir: Path) -> tuple[pl.DataFrame, dict]:
    created_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    report: dict = {"created_at": created_at, "models": {}}

    for model_id, spec in MODELS.items():
        model_path = REPO_ROOT / spec["model_path"]
        model_hash = _sha256_file(model_path)
        model = joblib.load(model_path)

        features, provenance = spec["loader"]()
        with warnings.catch_warnings():
            # The bearish estimator was fitted with feature names; the frozen
            # thresholds were produced from a positional array. Preserving that
            # exact call is what makes the reproduction bit-exact.
            warnings.simplefilter("ignore", UserWarning)
            scores = model.predict_proba(features)[:, 1]

        score_hash = _sha256_float64(scores)
        frozen = FROZEN_REFERENCE[model_id]
        model_report = {
            "model_artifact_hash": model_hash,
            "sample_count": int(scores.shape[0]),
            "score_sha256_little_endian_float64": score_hash,
            "reproduced": {},
            "derived": {},
            **provenance,
        }

        for label, fraction in PERCENTILES:
            value = float(np.quantile(scores, 1.0 - fraction, method=QUANTILE_METHOD))
            reference = frozen.get(label)
            if reference is None:
                status = "RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION"
                model_report["derived"][label] = value
            else:
                if value != reference:
                    raise SystemExit(
                        f"ABORT: {model_id} {label} did not reproduce exactly: "
                        f"got {value!r}, frozen {reference!r}"
                    )
                status = "AVAILABLE_AND_FROZEN"
                model_report["reproduced"][label] = {
                    "value": value,
                    "frozen": reference,
                    "exact": True,
                }

            rows.append(
                {
                    "model_id": model_id,
                    "model_version": "v2",
                    "model_artifact_hash": model_hash,
                    "domain_name": spec["domain_name"],
                    "domain_contract_version": "phase_b_established_regime_gate_v1",
                    "entry_direction": spec["entry_direction"],
                    "threshold_contract_id": f"{model_id}::{label}::2025_calibration",
                    "calibration_population_id": provenance["calibration_population_id"],
                    "calibration_population_description": provenance[
                        "population_description"
                    ],
                    "calibration_start_date": "2025-01-01",
                    "calibration_end_date_exclusive": "2026-01-01",
                    "calibration_population_key_sha256": provenance[
                        "population_key_sha256"
                    ],
                    "calibration_score_sha256": score_hash,
                    "percentile_label": label,
                    "upper_tail_fraction": fraction,
                    "probability_threshold": value,
                    "sample_count": int(scores.shape[0]),
                    "quantile_method": QUANTILE_METHOD,
                    "tie_policy": TIE_POLICY,
                    "membership_operator": ">=",
                    "availability_status": status,
                    "frozen_reference_value": reference,
                    "reproduced_frozen_value_exactly": None
                    if reference is None
                    else True,
                    "overlaps_evaluation_window": True,
                    "overlap_disclosure": (
                        "Calibration population is calendar-2025 and overlaps the "
                        "2021-2025 evaluation window. Results using this threshold "
                        "are descriptive and must not be represented as "
                        "threshold-out-of-sample for 2025."
                    ),
                    "waiver_artifact": (
                        "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json"
                    ),
                    "created_at": created_at,
                    "source_artifact": spec["source_artifact"],
                    "source_artifact_hash": _sha256_file(
                        REPO_ROOT / spec["source_artifact"]
                    ),
                    "is_frozen": True,
                }
            )

        report["models"][model_id] = model_report

    table = pl.DataFrame(rows).sort(["model_id", "upper_tail_fraction"], descending=[False, True])
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "canonical_model_threshold_contracts.parquet"
    table.write_parquet(target, compression="zstd", statistics=True)
    report["output"] = str(target.relative_to(REPO_ROOT)).replace("\\", "/")
    report["output_sha256"] = _sha256_file(target)
    report["row_count"] = table.height
    return table, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "data/canonical/regime_complete_v1"),
        help="output directory for the threshold contract table",
    )
    parser.add_argument(
        "--report",
        default=str(
            REPO_ROOT
            / "studies/regime_complete_canonical_store/results/threshold_availability_report.json"
        ),
    )
    args = parser.parse_args()

    table, report = build(Path(args.out))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    with pl.Config(tbl_rows=20, tbl_cols=8, fmt_str_lengths=40):
        print(
            table.select(
                "model_id",
                "percentile_label",
                "probability_threshold",
                "sample_count",
                "availability_status",
            )
        )
    print(f"\nwrote {report['output']}  sha256={report['output_sha256'][:16]}...")
    print(f"wrote {report_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
