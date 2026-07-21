"""Sample 100 random + 20 edge-case events from 2025 for parity testing.

Edge cases:
  - 5 near threshold (|pred - threshold| smallest)
  - 5 highest scores (most likely "5m flip imminent")
  - 5 lowest scores (least likely)
  - 5 near session boundaries (first/last 30 min of RTH)

Output:
  parity_event_ids_2025.json   — list of event_ids
  parity_event_meta_2025.parquet — event_id + category + reason
"""

import sys
import os
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

PREDS_PATH = ("studies/ml_5m_flip_prediction/results/"
               "preds_2025_walk_forward.parquet")
DS_PATH = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
THR_PATH = "models/ml_5m_flip/threshold_2026.json"

OUT_DIR = Path("studies/ml_5m_flip_prediction/parity")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_IDS = OUT_DIR / "parity_event_ids_2025.json"
OUT_META = OUT_DIR / "parity_event_meta_2025.parquet"

RNG_SEED = 42
N_RANDOM = 100
N_EDGE_PER_CAT = 5


def main():
    print("Loading 2025 predictions...")
    preds = pd.read_parquet(PREDS_PATH)
    print(f"  {len(preds):,} rows")

    with open(THR_PATH) as f:
        thr = json.load(f)["bottom_50"]
    print(f"  threshold (bottom_50 from training): {thr:.6f}")

    # Need decision time / minute_of_hour for session-boundary edge cases.
    # Pull from the dataset.
    ds = pd.read_parquet(DS_PATH, columns=[
        "event_id", "year", "decision_checkpoint_s", "is_rth",
        "minute_of_hour", "hour_of_day", "minutes_since_rth_open",
    ])
    ds_2025_t0 = ds[
        (ds["year"] == 2025)
        & (ds["decision_checkpoint_s"] == 0)
        & (ds["is_rth"] == 1)
    ]
    preds_meta = preds.merge(
        ds_2025_t0[["event_id", "minutes_since_rth_open",
                     "hour_of_day", "minute_of_hour"]],
        on="event_id", how="inner")
    print(f"  Joined: {len(preds_meta):,} rows")

    rng = np.random.default_rng(RNG_SEED)
    selected = []

    # 1. Random 100 (excluding extreme tails to make diverse)
    rand_pool = preds_meta.sample(n=N_RANDOM, random_state=RNG_SEED)
    for _, row in rand_pool.iterrows():
        selected.append({
            "event_id": int(row["event_id"]),
            "category": "random",
            "reason": f"random sample, pred={row['pred']:.4f}",
            "pred": float(row["pred"]),
            "minutes_since_rth_open": int(row["minutes_since_rth_open"]),
        })

    # 2. 5 near threshold
    near_thr = preds_meta.copy()
    near_thr["abs_diff"] = (near_thr["pred"] - thr).abs()
    near_thr_sorted = near_thr.sort_values("abs_diff").head(N_EDGE_PER_CAT)
    for _, row in near_thr_sorted.iterrows():
        selected.append({
            "event_id": int(row["event_id"]),
            "category": "near_threshold",
            "reason": f"|pred-thr|={row['abs_diff']:.6f}, "
                       f"pred={row['pred']:.4f}",
            "pred": float(row["pred"]),
            "minutes_since_rth_open": int(row["minutes_since_rth_open"]),
        })

    # 3. 5 highest predictions
    high_pred = preds_meta.sort_values("pred", ascending=False).head(
        N_EDGE_PER_CAT)
    for _, row in high_pred.iterrows():
        selected.append({
            "event_id": int(row["event_id"]),
            "category": "high_pred",
            "reason": f"high pred={row['pred']:.4f}",
            "pred": float(row["pred"]),
            "minutes_since_rth_open": int(row["minutes_since_rth_open"]),
        })

    # 4. 5 lowest predictions
    low_pred = preds_meta.sort_values("pred", ascending=True).head(
        N_EDGE_PER_CAT)
    for _, row in low_pred.iterrows():
        selected.append({
            "event_id": int(row["event_id"]),
            "category": "low_pred",
            "reason": f"low pred={row['pred']:.4f}",
            "pred": float(row["pred"]),
            "minutes_since_rth_open": int(row["minutes_since_rth_open"]),
        })

    # 5. 5 near RTH session boundaries (first 30min: 0..30 min after open;
    #    last 30 min: 360..390 min after open)
    boundary_pool = preds_meta[
        (preds_meta["minutes_since_rth_open"].between(0, 30))
        | (preds_meta["minutes_since_rth_open"].between(360, 390))
    ]
    bnd = boundary_pool.sample(
        n=min(N_EDGE_PER_CAT, len(boundary_pool)), random_state=RNG_SEED + 1)
    for _, row in bnd.iterrows():
        selected.append({
            "event_id": int(row["event_id"]),
            "category": "session_boundary",
            "reason": f"min_since_rth={int(row['minutes_since_rth_open'])}, "
                       f"pred={row['pred']:.4f}",
            "pred": float(row["pred"]),
            "minutes_since_rth_open": int(row["minutes_since_rth_open"]),
        })

    # Dedupe (some random samples may overlap with edge cases)
    seen = set()
    dedup = []
    for s in selected:
        if s["event_id"] in seen:
            continue
        seen.add(s["event_id"])
        dedup.append(s)
    print(f"\n  Total selected (after dedup): {len(dedup):,}")

    by_cat = {}
    for s in dedup:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"    {cat}: {n}")

    # Save event_ids list (for NT parity capture)
    event_ids = [s["event_id"] for s in dedup]
    with open(OUT_IDS, "w") as f:
        json.dump({
            "year": 2025,
            "n_total": len(event_ids),
            "by_category": by_cat,
            "event_ids": event_ids,
            "rng_seed": RNG_SEED,
        }, f, indent=2)
    print(f"\n  Saved event ids: {OUT_IDS}")

    # Save meta as parquet
    meta_df = pd.DataFrame(dedup)
    meta_df.to_parquet(OUT_META, index=False)
    print(f"  Saved meta:      {OUT_META}")


if __name__ == "__main__":
    main()
