"""Builds results/data_readiness.csv and results/label_quality_by_year.csv
from the Phase 0 prepared surfaces, per year."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
TARGET = "bearish_regime_flip_within_300s"


def main() -> None:
    phase0 = json.loads((RESULTS / "phase0_manifest.json").read_text(encoding="utf-8"))
    readiness_rows = [phase0["year_reports"][str(y)] for y in YEARS]
    pd.DataFrame(readiness_rows).to_csv(RESULTS / "data_readiness.csv", index=False)

    label_rows = []
    for year in YEARS:
        df = pd.read_parquet(WORK / f"prepared_{year}.parquet", columns=[
            TARGET, "bearish_flip_within_600s", "time_to_bearish_flip_s",
            "bearish_flip_within_300s_and_followthrough_1A",
            "adverse_move_1p25A_before_bearish_flip"])
        flipped = df[df[TARGET]]
        label_rows.append({
            "year": year,
            "bearish_regime_flip_within_300s_rate": float(df[TARGET].mean()),
            "bearish_flip_within_600s_rate": float(df["bearish_flip_within_600s"].mean()),
            "median_time_to_bearish_flip_s": float(df["time_to_bearish_flip_s"].median()),
            "followthrough_1A_rate_given_300s_flip": (
                float(flipped["bearish_flip_within_300s_and_followthrough_1A"].mean())
                if len(flipped) else float("nan")),
            "adverse_move_1p25A_before_flip_rate": float(df["adverse_move_1p25A_before_bearish_flip"].mean()),
        })
    pd.DataFrame(label_rows).to_csv(RESULTS / "label_quality_by_year.csv", index=False)
    print(pd.DataFrame(label_rows).to_string(index=False))


if __name__ == "__main__":
    main()
