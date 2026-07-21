"""Applies path_logic.py (pre-execution-tested and audited) to the selected
trigger's actual trades. Diagnostic only -- no stop/exit optimization.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PURE_FLIP = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
CODEX = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
WORK, RESULTS = HERE / "_work", HERE / "results"
for p in (CODEX,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from CODEX_5_X_common import RAW_1S  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402
sys.path.insert(0, str(HERE))
from path_logic import align_open_price, post_flip_giveback_atr, scan_trade_path  # noqa: E402

EXTRA_COLS = ["regime_start_ns", "observation_time", "entry_px", "exit_px", "alignment_ts", "aligned",
              "entry_direction", "post_align_mfe_atr", "post_align_mae_atr",
              "pre_align_mae_atr", "pre_align_mfe_atr"]
KEY = ["regime_start_ns", "observation_time"]
ATR_THRESHOLDS = (0.25, 0.50, 0.75, 1.00)


def enrich(selected: pd.DataFrame, source_path: Path) -> pd.DataFrame:
    extra = pd.read_parquet(source_path, columns=EXTRA_COLS)
    merged = selected.merge(extra, on=KEY, how="left", validate="one_to_one")
    if merged[["entry_px", "exit_px"]].isna().any().any():
        raise RuntimeError("enrich join left NaN entry_px/exit_px -- key mismatch")
    return merged


def run_year(year: int, trades: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)

    rows = []
    for t in trades.itertuples(index=False):
        direction = int(t.entry_direction)
        if direction != -1:
            raise RuntimeError(f"unexpected non-short entry_direction={direction}")
        path = scan_trade_path(ts, opens, highs, lows, entry_ts=int(t.entry_ts), entry_px=float(t.entry_px),
                               exit_ts=int(t.exit_ts), direction=direction, atr=float(t.atr_at_entry),
                               flip_ts=int(t.confirm_flip_ns))
        row = {
            "regime_start_ns": int(t.regime_start_ns), "observation_time": int(t.observation_time),
            "net_pnl": float(t.net_pnl), "hit_opposing_flip": bool(t.hit_opposing_flip),
            "aligned": bool(t.aligned),
            "pre_align_mfe_atr": float(t.pre_align_mfe_atr), "pre_align_mae_atr": float(t.pre_align_mae_atr),
            "post_align_mfe_atr": float(t.post_align_mfe_atr) if t.aligned else np.nan,
            "post_align_mae_atr": float(t.post_align_mae_atr) if t.aligned else np.nan,
            "max_favorable_excursion_atr": path["max_favorable_excursion_atr"],
            "max_adverse_excursion_atr_to_exit": path["max_adverse_excursion_atr_to_exit"],
            "max_adverse_excursion_atr_before_flip": path["max_adverse_excursion_atr_before_flip"],
            "time_from_entry_to_bearish_flip_s": (int(t.confirm_flip_ns) - int(t.entry_ts)) / 1e9,
        }
        for th in ATR_THRESHOLDS:
            row[f"ever_up_{th}atr"] = path["ever_up_atr"][th]
            row[f"ever_up_{th}atr_then_loser"] = path["ever_up_atr"][th] and t.net_pnl < 0

        if t.aligned:
            align_open = align_open_price(ts, opens, int(t.alignment_ts))
            row["post_flip_giveback_atr"] = post_flip_giveback_atr(
                direction, align_open, float(t.exit_px), float(t.atr_at_entry), float(t.post_align_mfe_atr))
        else:
            row["post_flip_giveback_atr"] = np.nan

        row["max_unrealized_pnl_usd"] = 20.0 * path["max_favorable_excursion_atr"] * float(t.atr_at_entry)
        row["min_unrealized_pnl_usd"] = -20.0 * path["max_adverse_excursion_atr_to_exit"] * float(t.atr_at_entry)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    t0 = time.time()
    all_rows = []
    for split_name, year, sel_path, src_path in (
        ("2025", 2025, RESULTS / "selected_trades_2025.parquet", PURE_FLIP / "_work" / "scored_dev_2025.parquet"),
        ("2026", 2026, RESULTS / "selected_trades_2026.parquet", PURE_FLIP / "_work" / "scored_test_2026.parquet"),
    ):
        selected = pd.read_parquet(sel_path, columns=KEY + ["entry_ts", "exit_ts", "atr_at_entry",
                                                             "confirm_flip_ns", "net_pnl", "hit_opposing_flip"])
        enriched = enrich(selected, src_path)
        year_result = run_year(year, enriched)
        year_result["split"] = split_name
        all_rows.append(year_result)

    path_df = pd.concat(all_rows, ignore_index=True)
    path_df.to_csv(RESULTS / "path_diagnostics.csv", index=False)

    giveback_rows = []
    for split_name, g in path_df.groupby("split"):
        row = {"split": split_name, "n_trades": len(g)}
        for th in ATR_THRESHOLDS:
            row[f"ever_up_{th}atr_count"] = int(g[f"ever_up_{th}atr"].sum())
            row[f"ever_up_{th}atr_then_loser_count"] = int(g[f"ever_up_{th}atr_then_loser"].sum())
        opp = g[g["hit_opposing_flip"]]
        for th in ATR_THRESHOLDS:
            row[f"opposing_flip_ever_up_{th}atr_count"] = int(opp[f"ever_up_{th}atr"].sum())
            row[f"opposing_flip_ever_up_{th}atr_then_loser_count"] = int(opp[f"ever_up_{th}atr_then_loser"].sum())
        giveback_rows.append(row)
    pd.DataFrame(giveback_rows).to_csv(RESULTS / "winner_giveback_counts.csv", index=False)

    print(pd.DataFrame(giveback_rows).to_string(index=False))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
