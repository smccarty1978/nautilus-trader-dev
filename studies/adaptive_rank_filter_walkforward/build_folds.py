"""Build fold_definitions.parquet: for every deployment month (Jan 2025 ..
Apr 2026) x window size (3m/6m/12m), the train/validate/deploy date ranges
per the rolling protocol:

    train:    trailing N months, ending the month BEFORE validation
    validate: immediately prior 1 calendar month
    deploy:   the deployment month itself

Example (12m): deploy=2025-06 -> validate=2025-05 -> train=2024-05..2025-04.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd
import awf_common as c


def build() -> pd.DataFrame:
    rows = []
    for window_name, n_months in c.WINDOW_SIZES.items():
        for deploy_month in c.DEPLOY_MONTHS:
            val_month = deploy_month - 1
            train_end_month = val_month - 1
            train_start_month = train_end_month - (n_months - 1)

            train_start, train_end = c.month_bounds(train_start_month)
            _, train_end = c.month_bounds(train_end_month)
            val_start, val_end = c.month_bounds(val_month)
            deploy_start, deploy_end = c.month_bounds(deploy_month)

            role = "final_reserved" if str(deploy_month) in ("2026-03", "2026-04") else "development"

            rows.append({
                "window_name": window_name,
                "n_months": n_months,
                "deploy_month": str(deploy_month),
                "val_month": str(val_month),
                "train_start_month": str(train_start_month),
                "train_end_month": str(train_end_month),
                "train_start_ts": train_start.value,
                "train_end_ts": train_end.value,
                "val_start_ts": val_start.value,
                "val_end_ts": val_end.value,
                "deploy_start_ts": deploy_start.value,
                "deploy_end_ts": deploy_end.value,
                "role": role,
            })
    return pd.DataFrame(rows)


def main():
    df = build()
    out_path = c.OUT / "fold_definitions.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df)} fold definitions to {out_path}")
    print(df.groupby("window_name")["deploy_month"].agg(["min", "max", "count"]))
    # Sanity: earliest train_start must be within/after protocol period start
    print("Earliest train_start_month:", df["train_start_month"].min())
    print("Latest deploy_month:", df["deploy_month"].max())


if __name__ == "__main__":
    main()
