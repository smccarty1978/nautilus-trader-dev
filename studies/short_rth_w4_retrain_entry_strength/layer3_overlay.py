"""Layer 3 — fixed-807 overlay.

For continuity with the confirmed pocket (Baseline B: 807 trades, +$27,013
offline), applies each model/retention-band's Layer 2 one-entry-per-regime
schedule to the KNOWN fixed-807 regime set (the globally one-position-
executed confirmed pocket) and reports keep/drop/moved-entry counts, plus
economics on the kept subset using the MODEL's own selected checkpoint (not
the original W4-threshold entry) -- this measures what the model would have
done on the same opportunity set, not a re-labeling of the original trades.

This overlay is semantically clean here because the fixed-807 regime set is
a subset of regimes already present in the score-independent surface (every
fixed-807 entry is, by construction, an established/RTH/valid-fill
checkpoint) -- unlike a candidate population defined by a *different*
established-regime gate, which would not be comparable.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK, RESULTS = HERE / "_work", HERE / "results"
SCHED_DIR = ROOT / "studies" / "fable5_nt_short_rth_policy_a" / "_work"

BANDS = [1.00, 0.85, 0.70, 0.50, 0.35, 0.20]


def pf(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def load_fixed807(year: int) -> pd.DataFrame:
    return pd.read_parquet(SCHED_DIR / f"short_rth_schedule_{year}.parquet")


def overlay_one(schedule: pd.DataFrame, fixed807: pd.DataFrame) -> dict:
    fixed_regimes = set(fixed807["regime_start_ns"].astype(np.int64))
    sched_regimes = set(schedule["regime_start_ns"].astype(np.int64)) if len(schedule) else set()
    kept = fixed_regimes & sched_regimes
    dropped = fixed_regimes - sched_regimes
    added = sched_regimes - fixed_regimes  # regimes the model trades that fixed-807 didn't

    kept_rows = schedule[schedule["regime_start_ns"].isin(kept)] if len(schedule) else schedule.iloc[0:0]
    fixed_kept = fixed807[fixed807["regime_start_ns"].isin(kept)]
    moved = 0
    if len(kept) and len(kept_rows):
        merged = kept_rows[["regime_start_ns", "entry_ts"]].merge(
            fixed_kept[["regime_start_ns", "target_fill_ts"]],
            on="regime_start_ns", how="inner")
        moved = int((merged["entry_ts"] != merged["target_fill_ts"]).sum())

    pnl = kept_rows["net_pnl"].astype(float) if len(kept_rows) else pd.Series(dtype=float)
    w, l = pnl[pnl > 0], pnl[pnl < 0]
    return {
        "fixed807_regimes": len(fixed_regimes), "kept": len(kept), "dropped": len(dropped),
        "added_beyond_fixed807": len(added), "moved_entry_within_kept": moved,
        "kept_trades": len(kept_rows), "kept_net_pnl": float(pnl.sum()) if len(pnl) else np.nan,
        "kept_per_trade": float(pnl.mean()) if len(pnl) else np.nan,
        "kept_profit_factor": pf(pnl) if len(pnl) else np.nan,
        "kept_win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
    }


def main() -> None:
    rows = []
    fixed807 = {y: load_fixed807(y) for y in (2025, 2026)}
    for model_name in ("logreg", "gbt", "w4_comparator"):
        for split_name, year in (("2025", 2025), ("2026", 2026)):
            for band in BANDS:
                path = WORK / f"schedule_{model_name}_{split_name}_{band}.parquet"
                if not path.exists():
                    continue
                schedule = pd.read_parquet(path)
                res = overlay_one(schedule, fixed807[year])
                rows.append({"model": model_name, "split": split_name, "retention_band": band, **res})
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "layer3_fixed807_overlay.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
