"""Phase 0 - freeze TOP50 / TOP25 as exact PREFIXES of the frozen top-100 list,
and verify the strict-causal long-side prepared data is present and reproducible.

Hard stops (per brief):
  * top-100 source SHA mismatch                -> STOP
  * TOP50/TOP25 not exact prefixes             -> STOP
  * prepared data missing / row counts wrong   -> STOP
  * target column missing / any feature absent -> STOP
  * bar-snap convention not strictly causal    -> STOP

No re-ranking. No long-side importance used. No 2025/2026 signal touches the list.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY.parents[1]
RESULTS = STUDY / "results"
PRIOR = ROOT / "studies" / "long_rth_mirrored_surface_top100_training"
PRIOR_WORK = PRIOR / "_work"
SOURCE_CSV = (ROOT / "studies" / "runtime_constrained_f3_feature_reduction"
              / "results" / "top_100_raw_feature_columns.csv")

EXPECTED_SOURCE_SHA = "6c6ceba7d3520e91b0feaed00cd6ab320230e8404e840894190b1cc7e70bc619"
EXPECTED_TOP100_SHA = "f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992"

TARGET = "bullish_regime_flip_within_300s"
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
EXPECTED_ROWS = {2021: 164940, 2022: 189071, 2023: 167721, 2024: 161220,
                 2025: 163397, 2026: 52488}
EXPECTED_SPLIT_ROWS = {"train_2021_2024": 682952, "dev_2025": 163397, "test_2026": 52488}


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def sha256_list(names: list[str]) -> str:
    """Hash of the ordered feature list.

    Recipe is fixed by the prior top-100 study and reproduced here EXACTLY:
    newline-joined with a trailing newline. Verified by reproducing
    EXPECTED_TOP100_SHA from the source CSV before any reduced list is hashed.
    """
    return hashlib.sha256(("\n".join(names) + "\n").encode("utf-8")).hexdigest()


def main() -> None:
    report: dict = {}

    # ---------- Phase 0a: reproduce the frozen top-100 source exactly ----------
    src_sha = sha256_file(SOURCE_CSV)
    if src_sha != EXPECTED_SOURCE_SHA:
        raise SystemExit(
            f"LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: top-100 source SHA "
            f"mismatch\n  expected {EXPECTED_SOURCE_SHA}\n  actual   {src_sha}")

    src = pd.read_csv(SOURCE_CSV)
    if not src["rank"].is_monotonic_increasing or src["rank"].iloc[0] != 1:
        raise SystemExit("LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: "
                         "source CSV is not in ascending rank order")
    top100 = src.sort_values("rank")["feature_name"].tolist()
    if len(top100) != 100:
        raise SystemExit(f"expected 100 ranked features, got {len(top100)}")

    top100_sha = sha256_list(top100)
    if top100_sha != EXPECTED_TOP100_SHA:
        raise SystemExit(
            f"LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: ordered top-100 list "
            f"SHA mismatch\n  expected {EXPECTED_TOP100_SHA}\n  actual {top100_sha}")

    # Cross-check against the prior study's frozen manifest (same list, same order).
    prior_manifest = json.load(open(PRIOR / "results" / "top100_feature_manifest.json"))
    if prior_manifest["feature_names_in_order"] != top100:
        raise SystemExit("LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: "
                         "prior study's frozen top-100 order differs from source CSV")

    # ---------- Phase 0b: construct TOP50 / TOP25 as exact prefixes ----------
    top50, top25 = top100[:50], top100[:25]
    for name, lst in (("TOP50", top50), ("TOP25", top25)):
        if lst != top100[:len(lst)]:
            raise SystemExit(f"LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: "
                             f"{name} is not an exact prefix of the frozen top-100")
    report["prefix_check"] = {
        "top50_is_exact_prefix": top50 == top100[:50],
        "top25_is_exact_prefix": top25 == top100[:25],
        "top25_is_prefix_of_top50": top25 == top50[:25],
    }

    meta = src.sort_values("rank").set_index("feature_name")
    for name, lst in (("top50", top50), ("top25", top25)):
        pd.DataFrame({
            "rank": range(1, len(lst) + 1),
            "feature_name": lst,
            "family": [meta.loc[f, "family"] for f in lst],
            "timing_status": [meta.loc[f, "timing_status"] for f in lst],
            "source_timeframe": [meta.loc[f, "source_timeframe"] for f in lst],
        }).to_csv(RESULTS / f"{name}_feature_list.csv", index=False)

    # ---------- Phase 0c: verify the strict-causal prepared data ----------
    readiness, all_ok = [], True
    for y in YEARS:
        p = PRIOR_WORK / f"prepared_long_{y}.parquet"
        a = PRIOR_WORK / f"attached_long_{y}.parquet"
        if not p.exists():
            raise SystemExit(f"LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: "
                             f"strict-causal prepared data missing: {p}")
        df = pd.read_parquet(p)
        att = pd.read_parquet(a, columns=["latest_source_ts_used", "observation_time"])
        gap = att["observation_time"] - att["latest_source_ts_used"]

        missing = [f for f in top100 if f not in df.columns]
        obj = [f for f in top100 if f in df.columns and df[f].dtype == object]
        row = {
            "year": y,
            "rows": len(df),
            "expected_rows": EXPECTED_ROWS[y],
            "rows_match": len(df) == EXPECTED_ROWS[y],
            "distinct_regimes": int(df["regime_start_ns"].nunique()),
            "target_present": TARGET in df.columns,
            "positive_rate": round(float(df[TARGET].mean()), 5),
            "n_missing_top100_features": len(missing),
            "n_object_dtype_features": len(obj),
            "prevailing_direction_all_minus1": bool((df["prevailing_direction"] == -1).all()),
            "entry_direction_all_plus1": bool((df["entry_direction"] == 1).all()),
            # strict causality: last source bar must be STRICTLY before observation_time
            "min_source_gap_ns": int(gap.min()),
            "n_snap_at_or_after_obs": int((gap <= 0).sum()),
            "strict_causal_ok": bool(gap.min() > 0),
            "prepared_sha256": sha256_file(p),
        }
        year_ok = (row["rows_match"] and row["target_present"] and not missing
                   and not obj and row["strict_causal_ok"]
                   and row["prevailing_direction_all_minus1"]
                   and row["entry_direction_all_plus1"])
        row["year_ok"] = year_ok
        all_ok = all_ok and year_ok
        readiness.append(row)

    rd = pd.DataFrame(readiness)
    rd.to_csv(RESULTS / "data_readiness.csv", index=False)

    split_rows = {
        "train_2021_2024": int(rd[rd.year.isin([2021, 2022, 2023, 2024])]["rows"].sum()),
        "dev_2025": int(rd[rd.year == 2025]["rows"].iloc[0]),
        "test_2026": int(rd[rd.year == 2026]["rows"].iloc[0]),
    }
    if split_rows != EXPECTED_SPLIT_ROWS:
        raise SystemExit(f"LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: split row "
                         f"counts differ\n  expected {EXPECTED_SPLIT_ROWS}\n  actual {split_rows}")
    if not all_ok:
        raise SystemExit("LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED: "
                         "prepared-data readiness FAILED - do not train")

    manifest = {
        "study": "long_rth_pure_flip_top50_top25_training",
        "feature_source_file": str(SOURCE_CSV.relative_to(ROOT)).replace("\\", "/"),
        "feature_source_sha256": src_sha,
        "feature_source_sha256_matches_expected": True,
        "ordered_top100_feature_list_sha256": top100_sha,
        "ordered_top100_sha256_matches_expected": True,
        "ranking_provenance": "frozen short-side runtime_constrained_f3_feature_reduction "
                              "ranking; NOT re-ranked, NOT re-scored on long-side data",
        "feature_sets": {
            "TOP100": {"n": 100, "ordered_list_sha256": top100_sha},
            "TOP50": {"n": 50, "ordered_list_sha256": sha256_list(top50),
                      "is_exact_prefix_of_top100": True,
                      "feature_names_in_order": top50},
            "TOP25": {"n": 25, "ordered_list_sha256": sha256_list(top25),
                      "is_exact_prefix_of_top100": True,
                      "feature_names_in_order": top25},
        },
        "prefix_check": report["prefix_check"],
        "family_counts": {
            "TOP100": src["family"].value_counts().to_dict(),
            "TOP50": meta.loc[top50, "family"].value_counts().to_dict(),
            "TOP25": meta.loc[top25, "family"].value_counts().to_dict(),
        },
        "timing_unverified": {
            "TOP100": src[src.timing_status != "verified"]["feature_name"].tolist(),
            "TOP50": [f for f in top50 if meta.loc[f, "timing_status"] != "verified"],
            "TOP25": [f for f in top25 if meta.loc[f, "timing_status"] != "verified"],
        },
        "prepared_data_source": str(PRIOR_WORK.relative_to(ROOT)).replace("\\", "/"),
        "prepared_data_convention": "latest_source_ts_used < observation_time (strict)",
        "split_rows": split_rows,
        "target": TARGET,
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "feature_sets_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(rd.to_string(index=False))
    print(f"\nTOP50 sha256 {manifest['feature_sets']['TOP50']['ordered_list_sha256']}")
    print(f"TOP25 sha256 {manifest['feature_sets']['TOP25']['ordered_list_sha256']}")
    print(f"split_rows {split_rows}")
    print("PHASE 0 GATE: PASS")


if __name__ == "__main__":
    main()
