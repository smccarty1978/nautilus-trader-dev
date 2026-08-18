"""Governed-harness descriptive analysis driver for ym_prev5_range_position.

One-off orchestration script: composes research/analysis/* library calls only.
No ad-hoc pandas statistics are computed outside what the harness itself provides
(descriptive_summary, slice_target_disposition, slice_fixed_edges, classification_bundle).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.analysis import reporting as R  # noqa: E402
from research.analysis import metrics as M  # noqa: E402
from research.analysis.slices import slice_direction, STUDY_FIXED_EDGES  # noqa: E402
from research.analysis.loader import (  # noqa: E402
    get_features_targets_metadata, load_collection, validate_collection, write_dataset_identity,
)
from research.analysis.spec import parse_analysis_spec  # noqa: E402

RUN_ID = "20260818_132043_ym_prev5_range_position_day"
STUDY_ID = "ym_prev5_range_position"
FEATURE = "latest_1m_close_position_prev5_range"
OUT_DIR = REPO_ROOT / "studies" / STUDY_ID / "results"


def main() -> None:
    spec = parse_analysis_spec({
        "analysis_id": "ym_prev5_range_position_train_pilot",
        "collection": {"run_id": RUN_ID, "study_id": STUDY_ID},
        "target": {"column": "target_flip_within_horizon", "horizon_seconds": 300},
        "partitions": ["train"],
        "features": {"feature_list_sha256": "0a4200c7db88216fa0a5a5b9761052b51d26e70fb169ea4ae19cd0d646cfb300"},
        "seed": 20260818,
        "slices": ["direction"],
        "notes": (
            "One-day descriptive TRAIN pilot (YM RTH 2024-09-03). Descriptive only: "
            "no model fitting, no threshold tuning, no post-hoc binning. Buckets are "
            "the harness's predeclared STUDY_FIXED_EDGES, unchanged."
        ),
    })

    col = load_collection(RUN_ID, runs_root=REPO_ROOT / "runs", studies_root=REPO_ROOT / "studies")
    report = validate_collection(col, spec)
    if not report.passed:
        print("VALIDATION FAILED:", json.dumps([c.to_dict() for c in report.failures], indent=2))
        sys.exit(1)

    X, y, meta = get_features_targets_metadata(col, spec, report)
    meta = meta.copy()
    meta[spec.target_column] = y.values

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tables_dir = OUT_DIR / "tables"

    ident = write_dataset_identity(col, report, OUT_DIR / "dataset_identity.json", spec)
    ds_sha = ident["collection_identity_sha256"]
    spec_sha = spec.analysis_spec_sha256

    values = X[FEATURE]

    tables: dict[str, R.StandardTable] = {}

    tables["descriptive_all"] = R.build_descriptive_table(
        values, column_name=FEATURE, dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )

    pos_mask = (y == 1)
    neg_mask = (y == 0)
    tables["descriptive_positive"] = R.build_descriptive_table(
        values[pos_mask.values], column_name=f"{FEATURE}__target_positive",
        dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )
    tables["descriptive_negative"] = R.build_descriptive_table(
        values[neg_mask.values], column_name=f"{FEATURE}__target_negative",
        dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )

    bull_mask = (meta["regime_direction"] == 1)
    bear_mask = (meta["regime_direction"] == -1)
    tables["descriptive_bullish"] = R.build_descriptive_table(
        values[bull_mask.values], column_name=f"{FEATURE}__bullish_candidates",
        dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )
    tables["descriptive_bearish"] = R.build_descriptive_table(
        values[bear_mask.values], column_name=f"{FEATURE}__bearish_candidates",
        dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )

    tables["by_target_disposition"] = R.build_target_disposition_table(
        y, meta, target_column=spec.target_column, scores=values,
        dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )

    tables["by_direction"] = R.build_slice_table(
        y, slice_direction(meta),
        scores=values, dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )

    tables["by_fixed_edges"] = R.build_fixed_edges_table(
        y, values, STUDY_FIXED_EDGES, column_name=FEATURE, scores=None,
        dataset_identity_sha256=ds_sha, analysis_spec_sha256=spec_sha,
    )

    # Simple, non-optimized distribution-separation statistic: the raw feature value
    # used directly as a "score" against the target. No threshold, no fit.
    bundle = M.classification_bundle(y, values)

    paths = {name: t.write(tables_dir) for name, t in tables.items()}

    ctx = R.build_analysis_context(
        analysis_id=spec.analysis_id,
        question=(
            "Does latest_1m_close_position_prev5_range show enough descriptive "
            "separation between YM observations that do and do not experience the "
            "prevailing 1m regime transition within 300s to justify expanding TRAIN?"
        ),
        dataset_identity=ident,
        analysis_spec_sha256=spec_sha,
        validation=report.to_dict(),
        tables=tables,
        table_paths=paths,
        headline_metrics={
            "feature_as_score_roc_auc": bundle["roc_auc"],
            "feature_as_score_pr_auc": bundle["pr_auc"],
            "positive_rate": bundle["positive_rate"],
        },
        caveats=[
            "One-day TRAIN pilot (2024-09-03 only). Not proof of predictive value.",
            "Feature is descriptive-only; it did not influence candidate selection, "
            "labels, timing, censoring, regime state, or direction eligibility.",
            "roc_auc/pr_auc here use the raw feature value as a 'score' with no fit "
            "and no threshold -- a distribution-separation statistic, not a model.",
        ],
    )
    problems = R.check_report_completeness(ctx, tables)
    ctx["report_completeness_problems"] = problems
    R.write_analysis_context(ctx, OUT_DIR / "analysis_context.json")

    print("VALIDATION:", "PASSED" if report.passed else "FAILED")
    print("completeness problems:", problems)
    print()
    for name, t in tables.items():
        d = t.to_dict()
        print(f"--- {name} ---")
        print(json.dumps(d["rows"], indent=2, default=str))
        if d["caveats"]:
            print("caveats:", d["caveats"])
        print()

    print("=== classification_bundle (feature-as-score vs target) ===")
    print(json.dumps(bundle, indent=2, default=str))

    print()
    print("=== disposition_counts (from collection_manifest.json, authoritative) ===")
    print(json.dumps(col.collection_manifest.get("candidate_disposition_reconciliation", {}), indent=2))

    print()
    print("first/last observation_ts (ns):", int(meta["observation_ts"].min()), int(meta["observation_ts"].max()))


if __name__ == "__main__":
    main()
