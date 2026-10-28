"""
Pillar 2 (VP Fade Companion) Dynamic ATR Stop Loss & Take Profit Ablation Study.
Evaluated across the full 2020-2026 NQ dataset (1,613 trading days, 505,077 1m RTH bars).
Location: research/noise_vp_study/study_p2_atr_sl_tp_ablation.py
"""

from pathlib import Path
import numpy as np
import pandas as pd


class Pillar2ATRSLTPAblation:

    def __init__(
        self, parquet_path: str = "research/noise_vp_study/rth_resampled_cache.parquet"
    ):
        self.parquet_path = Path(parquet_path)
        # Parameter Grid to Test
        self.sl_multipliers = [0.5, 0.75, 1.0, 1.25, 1.5]
        self.tp_multipliers = [0.25, 0.5, 0.75, 1.0, 1.25]
        self.time_stop_mins = 15

        # Institutional Frictions
        self.slippage = 0.25  # 1 tick per side ($5.00 on NQ, $0.50 on MNQ)
        self.commission = (
            1.30 / 20.0
        )  # $1.30 MNQ round-turn expressed in NQ points (~0.065 pt)

    def load_data(self) -> pd.DataFrame:
        if not self.parquet_path.exists():
            raise FileNotFoundError(
                f"Resampled RTH cache not found at {self.parquet_path}"
            )
        df = pd.read_parquet(self.parquet_path)
        if "date" not in df.columns:
            df["date"] = df.index.date
        return df

    def run_grid_search(self):
        print("Loading NQ RTH resampled cache (2020-2026)...")
        df = self.load_data()
        print(
            f"Loaded {len(df):,} bars across {df['date'].nunique():,} trading"
            " sessions."
        )

        results = []
        total_runs = len(self.sl_multipliers) * len(self.tp_multipliers)
        run_idx = 0

        grouped = df.groupby("date")
        # Pre-extract days as list of tuples for lightning-fast iteration
        days_data = [(d, list(day.itertuples())) for d, day in grouped]

        for sl_m in self.sl_multipliers:
            for tp_m in self.tp_multipliers:
                run_idx += 1
                config_name = f"SL_{sl_m}xATR_TP_{tp_m}xATR"
                print(
                    f"[{run_idx:02d}/{total_runs}] Evaluating Pillar 2 Config: {config_name} ..."
                )

                fade_trades = []

                for d, day_bars in days_data:
                    fade_pos = 0  # 0: Flat, 1: Long Fade, -1: Short Fade
                    fade_entry_p = 0.0
                    fade_sl_level = 0.0
                    fade_tp_level = 0.0
                    fade_bars_held = 0

                    for i, bar in enumerate(day_bars):
                        ts = bar.Index
                        hour = ts.hour
                        minute = ts.minute
                        c = bar.close
                        ub = bar.upper_band
                        lb = bar.lower_band
                        vwap = bar.vwap
                        atr = bar.atr_15m if not np.isnan(bar.atr_15m) else 45.0
                        poc = bar.prev_poc
                        vah = bar.prev_vah
                        val = bar.prev_val

                        # Pillar 2 State Machine
                        if fade_pos == 0:
                            is_up_breach = c > ub and c > vwap
                            is_down_breach = c < lb and c < vwap

                            if is_up_breach or is_down_breach:
                                # VP Clearance Gate (Must be rejected by VP node)
                                pass_vp = (
                                    (c > vah)
                                    if is_up_breach
                                    else (c < val) or (c > vah and (c - poc >= 1.5 * atr))
                                )
                                if is_up_breach and (c < val and (poc - c >= 1.5 * atr)):
                                    pass_vp = True

                                if not pass_vp:  # VP Rejected -> Fade Entry
                                    fade_pos = -1 if is_up_breach else 1
                                    fade_entry_p = c
                                    fade_bars_held = 0
                                    # Dynamic ATR-scaled Stop Loss and Take Profit
                                    fade_sl_level = sl_m * atr
                                    fade_tp_level = tp_m * atr

                        elif fade_pos != 0:
                            fade_bars_held += 1

                            if fade_pos == 1:  # Long Fade (Entered below lower band)
                                # Check Stop Loss
                                if c <= fade_entry_p - fade_sl_level:
                                    pnl = (
                                        (c - fade_entry_p)
                                        - (2 * self.slippage)
                                        - self.commission
                                    )
                                    fade_trades.append({"date": d, "net_pts": pnl, "reason": "SL"})
                                    fade_pos = 0
                                # Check Take Profit Target (ATR-scaled distance upward)
                                elif c >= fade_entry_p + fade_tp_level:
                                    pnl = (
                                        (c - fade_entry_p)
                                        - (2 * self.slippage)
                                        - self.commission
                                    )
                                    fade_trades.append({"date": d, "net_pts": pnl, "reason": "TP"})
                                    fade_pos = 0
                                # Check Time Stop
                                elif fade_bars_held >= self.time_stop_mins:
                                    pnl = (
                                        (c - fade_entry_p)
                                        - (2 * self.slippage)
                                        - self.commission
                                    )
                                    fade_trades.append(
                                        {"date": d, "net_pts": pnl, "reason": "TimeStop"}
                                    )
                                    fade_pos = 0

                            elif fade_pos == -1:  # Short Fade (Entered above upper band)
                                # Check Stop Loss
                                if c >= fade_entry_p + fade_sl_level:
                                    pnl = (
                                        (fade_entry_p - c)
                                        - (2 * self.slippage)
                                        - self.commission
                                    )
                                    fade_trades.append({"date": d, "net_pts": pnl, "reason": "SL"})
                                    fade_pos = 0
                                # Check Take Profit Target (ATR-scaled distance downward)
                                elif c <= fade_entry_p - fade_tp_level:
                                    pnl = (
                                        (fade_entry_p - c)
                                        - (2 * self.slippage)
                                        - self.commission
                                    )
                                    fade_trades.append({"date": d, "net_pts": pnl, "reason": "TP"})
                                    fade_pos = 0
                                # Check Time Stop
                                elif fade_bars_held >= self.time_stop_mins:
                                    pnl = (
                                        (fade_entry_p - c)
                                        - (2 * self.slippage)
                                        - self.commission
                                    )
                                    fade_trades.append(
                                        {"date": d, "net_pts": pnl, "reason": "TimeStop"}
                                    )
                                    fade_pos = 0

                        # EOD Flatten at 15:59 ET
                        if hour == 15 and minute >= 59 and fade_pos != 0:
                            pnl = (
                                (
                                    (c - fade_entry_p)
                                    if fade_pos == 1
                                    else (fade_entry_p - c)
                                )
                                - (2 * self.slippage)
                                - self.commission
                            )
                            fade_trades.append({"date": d, "net_pts": pnl, "reason": "EOD"})
                            fade_pos = 0

                # Compute Performance Metrics for this Config
                df_f = pd.DataFrame(fade_trades)
                if len(df_f) > 0:
                    total_trades = len(df_f)
                    win_rate = (df_f["net_pts"] > 0).mean() * 100
                    net_pts = df_f["net_pts"].sum()
                    avg_pts = df_f["net_pts"].mean()

                    gross_win = df_f.loc[df_f["net_pts"] > 0, "net_pts"].sum()
                    gross_loss = abs(df_f.loc[df_f["net_pts"] < 0, "net_pts"].sum())
                    profit_factor = gross_win / gross_loss if gross_loss > 0 else np.nan

                    df_f["cum_pts"] = df_f["net_pts"].cumsum()
                    peak = df_f["cum_pts"].cummax()
                    dd = df_f["cum_pts"] - peak
                    max_dd = abs(dd.min())
                    romad = net_pts / max_dd if max_dd > 0 else 0

                    results.append({
                        "SL Mult": sl_m,
                        "TP Mult": tp_m,
                        "Trades": total_trades,
                        "Win Rate %": win_rate,
                        "Net Pts": net_pts,
                        "Avg Pts/Trd": avg_pts,
                        "Profit Factor": profit_factor,
                        "Max DD (pts)": max_dd,
                        "RoMaD": romad,
                    })

        df_results = pd.DataFrame(results)
        df_results.sort_values(by="Net Pts", ascending=False, inplace=True)

        print("\n=========================================================================")
        print("PILLAR 2 (VP FADE) DYNAMIC ATR SL & TP ABLATION RESULTS (2020-2026)")
        print("=========================================================================")
        print(df_results.to_string(index=False))
        print("=========================================================================")

        # Save report
        output_path = Path("research/noise_vp_study/p2_atr_sl_tp_ablation_report.md")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_content = f"""# Pillar 2 (VP Fade) ATR SL & TP Ablation Report (2020–2026)

## Executive Summary
This report summarizes the grid search optimization testing dynamic ATR-scaled Stop Loss (`0.5x` to `1.5x` $\\text{{ATR}}_{{15m}}$) and Take Profit targets (`0.25x` to `1.25x` $\\text{{ATR}}_{{15m}}$) for Pillar 2 across all 1,613 trading days (2020–2026) under 100% market-order execution (0.50 pt slippage + commission).

## Ablation Matrix (Ranked by Net PnL)
| SL Mult | TP Mult | Trades | Win Rate % | Net Pts | Avg Pts/Trd | Profit Factor | Max DD (pts) | RoMaD |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|
"""
        for _, row in df_results.iterrows():
            report_content += (
                f"| {row['SL Mult']}x | {row['TP Mult']}x | {row['Trades']:,}"
                f" | {row['Win Rate %']:.2f}% | {row['Net Pts']:+.2f} |"
                f" {row['Avg Pts/Trd']:+.2f} | {row['Profit Factor']:.2f}"
                f" | {row['Max DD (pts)']:.2f} | {row['RoMaD']:.2f} |\n"
            )

        output_path.write_text(report_content, encoding="utf-8")
        print(f"\nSaved full ablation report to {output_path}")


if __name__ == "__main__":
    study = Pillar2ATRSLTPAblation()
    study.run_grid_search()
