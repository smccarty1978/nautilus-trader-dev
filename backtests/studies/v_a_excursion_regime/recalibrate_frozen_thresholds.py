"""Recalibrate entry/rescore thresholds to the FROZEN model's own
score distribution.

The original thresholds.json took the 90th/50th percentile of the
WALK-FORWARD model's OOS p_score. The frozen model (trained in-sample
on 2024-2025) produces systematically higher scores, so those cutoffs
no longer represent top-10% / top-50%.

Fix: score the 2024-2025 candidate pool (the freeze-era data) with the
frozen model, take the real 90th / 50th percentiles. Overwrite
thresholds.json. 2024-2025 only — no peek at OOS years.
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb


FROZEN = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
CANDIDATES = ("studies/v_a_excursion_regime/results_v0/"
                 "pre_flip_candidates_augmented.parquet")

model = lgb.Booster(model_file=str(FROZEN / "model.txt"))
feats = json.loads((FROZEN / "feature_list.json").read_text())

df = pd.read_parquet(CANDIDATES)
df_train_era = df[df["year"].isin([2024, 2025])].copy()
print(f"Candidate pool (2024-2025, freeze era): {len(df_train_era):,}")

scores = model.predict(df_train_era[feats])
print(f"\nFrozen-model score distribution on 2024-2025 candidates:")
for q in [0.50, 0.70, 0.80, 0.90, 0.95, 0.99]:
    print(f"  p{int(q*100)}: {np.quantile(scores, q):.5f}")
print(f"  min={scores.min():.5f}  max={scores.max():.5f}  "
      f"distinct values={len(np.unique(np.round(scores, 6)))}")

entry_thr = float(np.quantile(scores, 0.90))   # top 10%
rescore_thr = float(np.quantile(scores, 0.50))  # top 50%

# Coarse-distribution check: how many candidates actually clear each
# cutoff (1-tree model => few distinct scores => coarse percentiles).
pct_above_entry = float((scores >= entry_thr).mean())
pct_above_rescore = float((scores >= rescore_thr).mean())
print(f"\nDerived thresholds (frozen model, 2024-2025 pool):")
print(f"  entry (target top 10%): p >= {entry_thr:.5f}  "
      f"-> actually {pct_above_entry:.1%} of pool clears it")
print(f"  rescore (target top 50%): p >= {rescore_thr:.5f}  "
      f"-> actually {pct_above_rescore:.1%} clears it")

old = json.loads((FROZEN / "thresholds.json").read_text())
new = {
    "entry_top10": entry_thr,
    "rescore_top50": rescore_thr,
    "frozen_on": old.get("frozen_on", "2024-2025 candidates only"),
    "n_train_candidates": old.get("n_train_candidates"),
    "calibration": "frozen-model 90th/50th pctile on 2024-2025 pool",
    "entry_actual_pct": pct_above_entry,
    "rescore_actual_pct": pct_above_rescore,
    "prior_entry_top10": old.get("entry_top10"),
    "prior_rescore_top50": old.get("rescore_top50"),
}
(FROZEN / "thresholds.json").write_text(json.dumps(new, indent=2))
print(f"\nUpdated thresholds.json")
print(f"  entry:   {old.get('entry_top10'):.5f} -> {entry_thr:.5f}")
print(f"  rescore: {old.get('rescore_top50'):.5f} -> {rescore_thr:.5f}")
