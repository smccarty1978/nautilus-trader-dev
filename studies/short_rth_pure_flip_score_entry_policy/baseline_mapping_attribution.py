"""Compares the selected trigger's schedule to Baseline A (W4-threshold
crossing candidates, regenerated via the same already-audited
`run_ladder.generate_entries` used throughout this project -- not
recomputed logic) and Baseline B (the fixed-807 pocket, existing schedule
file) on a regime_start_ns basis.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = HERE / "results"
SCHED_DIR = ROOT / "studies" / "fable5_nt_short_rth_policy_a" / "_work"

for p in (ROOT / "studies" / "fable5_short_rth_threshold_ladder",
          ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import run_ladder as LADDER  # noqa: E402
from CODEX_5_X_common import RAW_1S  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402


def pf(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def baseline_a_regimes(year: int) -> set[int]:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    policy = LADDER.json.loads(LADDER.POLICY_PATH.read_text(encoding="utf-8"))
    stream = LADDER.load_checkpoint_stream(year, policy)
    crossing = LADDER.generate_entries(year, raw, stream, LADDER.CONTROL, policy["filter"])
    if len(crossing) != LADDER.YEAR_CAND_COUNT[year]:
        raise RuntimeError(f"{year}: Baseline A regenerated {len(crossing)} != expected {LADDER.YEAR_CAND_COUNT[year]}")
    return set(crossing["regime_start_ns"].astype(np.int64))


def baseline_b_regimes(year: int) -> set[int]:
    sched = pd.read_parquet(SCHED_DIR / f"short_rth_schedule_{year}.parquet")
    return set(sched["regime_start_ns"].astype(np.int64))


def overlay(selected: pd.DataFrame, baseline_regimes: set[int], baseline_name: str) -> dict:
    sel_regimes = set(selected["regime_start_ns"].astype(np.int64))
    kept = baseline_regimes & sel_regimes
    dropped = baseline_regimes - sel_regimes
    added = sel_regimes - baseline_regimes

    kept_rows = selected[selected["regime_start_ns"].isin(kept)]
    pnl = kept_rows["net_pnl"].astype(float) if len(kept_rows) else pd.Series(dtype=float)
    added_rows = selected[selected["regime_start_ns"].isin(added)]
    added_pnl = added_rows["net_pnl"].astype(float) if len(added_rows) else pd.Series(dtype=float)

    return {
        "baseline": baseline_name, "baseline_trades": len(baseline_regimes),
        "baseline_trades_kept": len(kept), "baseline_trades_missed": len(dropped),
        "new_trades_added": len(added),
        "kept_trades": len(kept_rows), "kept_net_pnl": float(pnl.sum()) if len(pnl) else np.nan,
        "kept_per_trade": float(pnl.mean()) if len(pnl) else np.nan,
        "kept_win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "added_net_pnl": float(added_pnl.sum()) if len(added_pnl) else np.nan,
        "added_trades": len(added_rows),
    }


def main() -> None:
    rows = []
    for split_name, year in (("2025", 2025), ("2026", 2026)):
        selected = pd.read_parquet(RESULTS / f"selected_trades_{split_name}.parquet")
        a_regimes = baseline_a_regimes(year)
        b_regimes = baseline_b_regimes(year)
        rows.append({"split": split_name, **overlay(selected, a_regimes, "A_w4_threshold")})
        rows.append({"split": split_name, **overlay(selected, b_regimes, "B_fixed_807")})

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "baseline_mapping_attribution.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
