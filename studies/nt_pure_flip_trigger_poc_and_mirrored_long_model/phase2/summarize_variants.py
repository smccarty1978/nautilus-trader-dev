"""Builds variant_summary.csv, exit_reason_summary.csv,
equity_curve_by_variant.csv, winner_giveback_counts.csv, and the pooled
raw_trade_paths.parquet from each variant's independent NT run outputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

ATR_THRESHOLDS = (0.25, 0.50, 0.75, 1.00, 1.50, 2.00)


def pf(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def max_closed_trade_dd(pnl_by_exit_order: pd.Series) -> float:
    eq = np.concatenate(([0.0], pnl_by_exit_order.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(eq) - eq))


def max_mtm_dd(trades: pd.DataFrame) -> float:
    """Max mark-to-market drawdown using each trade's own min_unrealized_pnl
    as an intra-trade low-water mark stitched onto the closed-trade equity
    curve (a reasonable, documented approximation given independent runs
    don't share a continuous tick-level equity series across trades)."""
    if len(trades) == 0:
        return np.nan
    ordered = trades.sort_values("entry_fill_time")
    running_closed_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    for _, t in ordered.iterrows():
        intratrade_low = running_closed_pnl + (t["min_unrealized_pnl"] if pd.notna(t["min_unrealized_pnl"]) else 0.0)
        peak = max(peak, running_closed_pnl)
        max_dd = max(max_dd, peak - intratrade_low)
        running_closed_pnl += t["net_pnl"] if pd.notna(t["net_pnl"]) else 0.0
        peak = max(peak, running_closed_pnl)
    return float(max_dd)


def variant_metrics(label: str, trades: pd.DataFrame, skips: pd.DataFrame, n_scheduled: int) -> dict:
    n = len(trades)
    if n == 0:
        return {"variant": label, "raw_trigger_count": n_scheduled, "entries_submitted": n_scheduled,
                "entries_filled": 0, "trades": 0}
    valid = trades[trades["exit_reason"] != "end_of_data_exit"]
    pnl = valid["net_pnl"].astype(float)
    w, l = pnl[pnl > 0], pnl[pnl < 0]
    ordered = valid.sort_values("exit_fill_time")["net_pnl"].astype(float)
    reached_bearish_flip = valid["bearish_flip_time"].notna()
    return {
        "variant": label, "raw_trigger_count": n_scheduled, "eligible_trigger_count": n_scheduled,
        "entries_submitted": n_scheduled, "entries_filled": n, "trades": len(valid),
        "gross_pnl": float(valid["gross_pnl"].sum()), "net_pnl": float(pnl.sum()),
        "per_trade": float(pnl.mean()) if len(pnl) else np.nan, "profit_factor": pf(pnl),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "avg_winner": float(w.mean()) if len(w) else np.nan, "avg_loser": float(l.mean()) if len(l) else np.nan,
        "largest_winner": float(w.max()) if len(w) else np.nan, "largest_loser": float(l.min()) if len(l) else np.nan,
        "max_closed_trade_dd": max_closed_trade_dd(ordered), "max_mtm_dd": max_mtm_dd(valid),
        "median_hold_s": float(valid["hold_seconds"].median()), "mean_hold_s": float(valid["hold_seconds"].mean()),
        "median_time_to_bearish_flip_s": float(valid["seconds_entry_to_bearish_flip"].median()),
        "mean_time_to_bearish_flip_s": float(valid["seconds_entry_to_bearish_flip"].mean()),
        "pct_reached_bearish_flip_before_stop": float(reached_bearish_flip.mean()),
        "n_skips": len(skips),
    }


def exit_reason_summary(label: str, trades: pd.DataFrame) -> pd.DataFrame:
    valid = trades[trades["exit_reason"] != "end_of_data_exit"]
    if len(valid) == 0:
        return pd.DataFrame(columns=["variant", "exit_reason", "count", "gross_pnl", "net_pnl"])
    g = valid.groupby("exit_reason").agg(count=("net_pnl", "size"), gross_pnl=("gross_pnl", "sum"),
                                         net_pnl=("net_pnl", "sum")).reset_index()
    g["variant"] = label
    return g


def giveback_counts(label: str, trades: pd.DataFrame) -> dict:
    valid = trades[trades["exit_reason"] != "end_of_data_exit"]
    row = {"variant": label, "n_trades": len(valid)}
    for th in ATR_THRESHOLDS:
        ever_up = valid["whole_trade_mfe_atr"] >= th
        loser = valid["net_pnl"] < 0
        row[f"ever_up_{th}atr_count"] = int(ever_up.sum())
        row[f"ever_up_{th}atr_then_loser_count"] = int((ever_up & loser).sum())
    for subset_name, mask in (
        ("stop_before_flip", valid["exit_reason"] == "fixed_stop_before_bearish_flip"),
        ("stop_after_flip", valid["exit_reason"] == "fixed_stop_after_bearish_flip"),
        ("opposing_flip", valid["exit_reason"] == "opposing_flip_exit"),
    ):
        sub = valid[mask]
        for th in (0.5, 1.0):
            ever_up = sub["whole_trade_mfe_atr"] >= th
            loser = sub["net_pnl"] < 0
            row[f"{subset_name}_ever_up_{th}atr_then_loser_count"] = int((ever_up & loser).sum())
            row[f"{subset_name}_n"] = len(sub)
    return row


def main() -> None:
    variant_rows, exit_frames, giveback_rows, equity_rows, all_trades = [], [], [], [], []
    for label in C.VARIANTS:
        out_dir = C.WORK / "nt_runs" / label
        trades = pd.read_parquet(out_dir / "trades.parquet") if (out_dir / "trades.parquet").exists() else pd.DataFrame()
        skips = pd.read_parquet(out_dir / "skips.parquet") if (out_dir / "skips.parquet").exists() else pd.DataFrame()
        sched = pd.read_parquet(C.schedule_path(label))
        variant_rows.append(variant_metrics(label, trades, skips, len(sched)))
        if len(trades):
            exit_frames.append(exit_reason_summary(label, trades))
            giveback_rows.append(giveback_counts(label, trades))
            valid = trades[trades["exit_reason"] != "end_of_data_exit"].sort_values("entry_fill_time")
            cum = valid["net_pnl"].cumsum()
            for i, (_, t) in enumerate(valid.iterrows()):
                equity_rows.append({"variant": label, "trade_num": i + 1,
                                    "entry_fill_time": t["entry_fill_time"], "net_pnl": t["net_pnl"],
                                    "cum_pnl": cum.iloc[i]})
            all_trades.append(trades)

    pd.DataFrame(variant_rows).to_csv(C.PHASE2 / "variant_summary.csv", index=False)
    if exit_frames:
        pd.concat(exit_frames, ignore_index=True).to_csv(C.PHASE2 / "exit_reason_summary.csv", index=False)
    pd.DataFrame(giveback_rows).to_csv(C.PHASE2 / "winner_giveback_counts.csv", index=False)
    pd.DataFrame(equity_rows).to_csv(C.PHASE2 / "equity_curve_by_variant.csv", index=False)

    # per-variant trade parquets, named per SPEC's exact filenames:
    variant_filenames = {
        "T1": "trades_trig_B_top2p5.parquet",
        "T2": "trades_trig_C30_top5.parquet",
        "T3": "trades_trig_B_top5.parquet",
    }
    for label, fname in variant_filenames.items():
        out_dir = C.WORK / "nt_runs" / label
        trades_p = out_dir / "trades.parquet"
        if trades_p.exists():
            pd.read_parquet(trades_p).to_parquet(C.PHASE2 / fname, index=False)

    raw_paths_frames = []
    for label in C.VARIANTS:
        out_dir = C.WORK / "nt_runs" / label
        p = out_dir / "raw_paths.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["variant"] = label
            raw_paths_frames.append(df)
    if raw_paths_frames:
        pd.concat(raw_paths_frames, ignore_index=True).to_parquet(C.PHASE2 / "raw_trade_paths.parquet", index=False)

    print(pd.DataFrame(variant_rows).to_string(index=False))


if __name__ == "__main__":
    main()
