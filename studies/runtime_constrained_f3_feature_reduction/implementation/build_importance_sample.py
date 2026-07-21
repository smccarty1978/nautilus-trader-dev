"""Phase 3 -- freeze a deterministic, regime-stratified 2025 sample for
permutation importance, per SPEC.md Phase 3 step 2: preserve monthly
representation, cap per-regime row contribution so long regimes with many
checkpoints cannot dominate solely through row count, document + hash the
construction. All SELECTED candidates are still validated on the COMPLETE
2025 population in Phase 6 -- this sample is for ranking only.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import SRC_STUDY, RESULTS, CONFIG, TARGET, sha256_obj

CAP_PER_REGIME = 25
TARGET_PER_MONTH = 2500
SEED = 42


def main() -> None:
    dev_df = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet",
                              columns=["regime_start_ns", "observation_time", TARGET])
    dev_df["month"] = pd.to_datetime(dev_df["observation_time"], unit="ns", utc=True).dt.month
    rng = np.random.default_rng(SEED)

    selected_idx = []
    per_month_report = {}
    for month, month_df in dev_df.groupby("month"):
        capped_idx = []
        for regime_id, reg_df in month_df.groupby("regime_start_ns"):
            n = min(CAP_PER_REGIME, len(reg_df))
            chosen = rng.choice(reg_df.index.to_numpy(), size=n, replace=False)
            capped_idx.extend(chosen.tolist())
        capped_idx = np.array(capped_idx)
        if len(capped_idx) > TARGET_PER_MONTH:
            capped_idx = rng.choice(capped_idx, size=TARGET_PER_MONTH, replace=False)
        selected_idx.extend(capped_idx.tolist())
        per_month_report[int(month)] = {
            "n_regimes": int(month_df["regime_start_ns"].nunique()),
            "n_rows_available": int(len(month_df)),
            "n_rows_sampled": int(len(capped_idx)),
        }

    selected_idx = sorted(set(int(i) for i in selected_idx))
    sample_df = dev_df.loc[selected_idx]

    config = {
        "method": "regime-stratified, monthly-preserved, per-regime-capped uniform sampling",
        "cap_per_regime": CAP_PER_REGIME, "target_per_month": TARGET_PER_MONTH, "seed": SEED,
        "n_total_dev_rows": len(dev_df), "n_sampled_rows": len(selected_idx),
        "n_unique_regimes_in_sample": int(sample_df["regime_start_ns"].nunique()),
        "per_month_report": per_month_report,
        "positive_rate_full": float(dev_df[TARGET].mean()),
        "positive_rate_sample": float(sample_df[TARGET].mean()),
        "row_index_sha256": sha256_obj(selected_idx),
    }
    (CONFIG / "importance_sample.json").write_text(json.dumps(config, indent=2))
    np.save(CONFIG / "importance_sample_row_index.npy", np.array(selected_idx, dtype=np.int64))
    print(json.dumps({k: v for k, v in config.items() if k != "per_month_report"}, indent=2))
    print("per_month_report:", json.dumps(per_month_report, indent=2))


if __name__ == "__main__":
    main()
