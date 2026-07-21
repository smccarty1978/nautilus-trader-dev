"""Phase 1 -- select the busiest 2025 month across T1/T2/T3, by trigger
count only (never profitability), per SPEC.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENTRY_POLICY = ROOT / "studies" / "short_rth_pure_flip_score_entry_policy"
PHASE2 = HERE / "phase2"

VARIANTS = {"T1": "trig_B_top2.5", "T2": "trig_C30_top5", "T3": "trig_B_top5"}


def main() -> None:
    monthly_rows = []
    per_variant = {}
    for label, key in VARIANTS.items():
        sched = pd.read_parquet(ENTRY_POLICY / "_work" / f"schedule_{key}_2025.parquet",
                                columns=["regime_start_ns", "observation_time", "entry_ts"])
        sched["month"] = pd.to_datetime(sched["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
        per_variant[label] = sched

    all_months = sorted(set().union(*[set(df["month"]) for df in per_variant.values()]))
    for month in all_months:
        row = {"month": month}
        regimes_this_month = set()
        timestamps_this_month = set()
        for label, df in per_variant.items():
            sub = df[df["month"] == month]
            row[f"{label}_count"] = len(sub)
            regimes_this_month |= set(sub["regime_start_ns"])
            timestamps_this_month |= set(sub["observation_time"])
        row["sum_triggers"] = row["T1_count"] + row["T2_count"] + row["T3_count"]
        row["unique_regimes"] = len(regimes_this_month)
        row["unique_trigger_timestamps"] = len(timestamps_this_month)
        row["min_trigger_count"] = min(row["T1_count"], row["T2_count"], row["T3_count"])
        monthly_rows.append(row)

    monthly_df = pd.DataFrame(monthly_rows)
    monthly_df.to_csv(PHASE2 / "month_selection.csv", index=False)

    ranked = monthly_df.sort_values(
        ["sum_triggers", "unique_regimes", "min_trigger_count", "month"],
        ascending=[False, False, False, True])
    selected_month = ranked.iloc[0]["month"]

    manifest = {
        "selected_month": selected_month,
        "selection_rule": "highest sum_triggers; tie-break: unique_regimes desc, min_trigger_count desc, earliest month",
        "monthly_table": monthly_df.to_dict(orient="records"),
        "selected_month_detail": ranked.iloc[0].to_dict(),
    }
    (PHASE2 / "month_selection_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(monthly_df.sort_values("sum_triggers", ascending=False).to_string(index=False))
    print(f"\nSELECTED MONTH: {selected_month}")


if __name__ == "__main__":
    main()
