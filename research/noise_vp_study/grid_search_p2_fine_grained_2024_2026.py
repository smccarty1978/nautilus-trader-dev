from pathlib import Path
import numpy as np
import pandas as pd


class FineGrainedP2GridSearch:

    def __init__(
        self, parquet_path: str = "research/noise_vp_study/rth_resampled_cache.parquet"
    ):
        self.parquet_path = Path(parquet_path)
        # Fine-grained parameter grid
        self.sl_grid = [0.35, 0.45, 0.50, 0.60, 0.75]
        self.tp_grid = [0.15, 0.20, 0.25, 0.35, 0.50]
        self.time_stop_mins = 15

        # Refined Institutional Frictions:
        # 1 tick total round-turn slippage = 0.125 pt per side
        self.slip = 0.125
        # $5.00 NQ RT commission ($2.50 per side) expressed in NQ points ($20/pt) = 0.125 pt per side
        self.comm_side = 2.50 / 20.0

    def run_search(self):
        print(
            "Loading RTH cache and filtering for out-of-sample era (2024–2026)..."
        )
        if not self.parquet_path.exists():
            raise FileNotFoundError(f"Cache not found at {self.parquet_path}")

        df = pd.read_parquet(self.parquet_path)
        if "date" not in df.columns:
            df["date"] = df.index.date

        # Filter for 2024-01-01 through latest 2026 date
        df = df[pd.to_datetime(df["date"]).dt.year >= 2024]
        print(
            f"Loaded {len(df):,} bars across {df['date'].nunique():,} trading"
            " sessions (2024–2026)."
        )

        grouped = df.groupby("date")
        days_data = [(d, list(day.itertuples(name="Bar"))) for d, day in grouped]

        results = []
        total_configs = len(self.sl_grid) * len(self.tp_grid)
        idx = 0

        for sl_m in self.sl_grid:
            for tp_m in self.tp_grid:
                idx += 1
                config_id = f"SL_{sl_m}x_TP_{tp_m}x"
                print(f"[{idx}/{total_configs}] Evaluating {config_id} ...")

                fade_trades = []

                for d, day_bars in days_data:
                    f_pos = 0
                    f_entry_p = 0.0
                    f_sl_pts = 0.0
                    f_tp_pts = 0.0
                    f_held = 0
                    needs_reset_long = False
                    needs_reset_short = False

                    for bar in day_bars:
                        ts = bar.Index
                        hour = ts.hour
                        minute = ts.minute
                        time_val = hour * 60 + minute

                        c = float(bar.close)
                        ub = float(bar.upper_band)
                        lb = float(bar.lower_band)
                        vwap = float(bar.vwap)
                        poc = float(bar.prev_poc) if not np.isnan(bar.prev_poc) else vwap
                        vah = float(bar.prev_vah) if not np.isnan(bar.prev_vah) else ub
                        val = float(bar.prev_val) if not np.isnan(bar.prev_val) else lb
                        atr = (
                            float(bar.atr_15m)
                            if not np.isnan(bar.atr_15m) and bar.atr_15m > 0
                            else 15.0
                        )

                        if lb <= c <= ub:
                            needs_reset_long = False
                            needs_reset_short = False

                        # Pillar 2 State Machine
                        if f_pos != 0:
                            f_held += 1
                            f_exit = False
                            f_exit_p = 0.0

                            if f_pos == 1:
                                if c <= f_entry_p - f_sl_pts:
                                    f_exit = True
                                    f_exit_p = c - self.slip
                                elif c >= f_entry_p + f_tp_pts:
                                    f_exit = True
                                    f_exit_p = c - self.slip
                                elif f_held >= self.time_stop_mins:
                                    f_exit = True
                                    f_exit_p = c - self.slip
                            elif f_pos == -1:
                                if c >= f_entry_p + f_sl_pts:
                                    f_exit = True
                                    f_exit_p = c + self.slip
                                elif c <= f_entry_p - f_tp_pts:
                                    f_exit = True
                                    f_exit_p = c + self.slip
                                elif f_held >= self.time_stop_mins:
                                    f_exit = True
                                    f_exit_p = c + self.slip

                            if f_exit:
                                gross = (f_exit_p - f_entry_p) * f_pos
                                net = gross - (self.slip + 2 * self.comm_side)
                                fade_trades.append({"date": d, "net_pts": net})
                                if f_pos == -1 and c > ub:
                                    needs_reset_long = True
                                elif f_pos == 1 and c < lb:
                                    needs_reset_short = True
                                f_pos = 0
                                f_held = 0

                        # Pillar 2 Entry Evaluation (09:31 to 15:29 ET)
                        if f_pos == 0 and (9 * 60 + 31 <= time_val <= 15 * 60 + 29):
                            is_up = (c > ub) and (c > vwap)
                            is_dn = (c < lb) and (c < vwap)
                            if is_up or is_dn:
                                skip = (is_up and needs_reset_long) or (
                                    is_dn and needs_reset_short
                                )
                                if not skip:
                                    pass_vp = False
                                    if is_up:
                                        pass_vp = (c > vah) or (
                                            c < val and (poc - c >= 1.5 * atr)
                                        )
                                    else:
                                        pass_vp = (c < val) or (
                                            c > vah and (c - poc >= 1.5 * atr)
                                        )
                                    if not pass_vp:
                                        f_pos = -1 if is_up else 1
                                        f_entry_p = c - self.slip if f_pos == -1 else c + self.slip
                                        f_sl_pts = sl_m * atr
                                        f_tp_pts = tp_m * atr
                                        f_held = 0

                        # EOD Flatten at 15:59 ET
                        if hour == 15 and minute >= 59 and f_pos != 0:
                            exit_p = c - self.slip if f_pos == 1 else c + self.slip
                            net = (exit_p - f_entry_p) * f_pos - (
                                self.slip + 2 * self.comm_side
                            )
                            fade_trades.append({"date": d, "net_pts": net})
                            f_pos = 0
                            f_held = 0

                # Compute Metrics
                df_f = pd.DataFrame(fade_trades)
                if len(df_f) > 0:
                    total_trades = len(df_f)
                    win_rate = (df_f["net_pts"] > 0).mean() * 100
                    net_pts = df_f["net_pts"].sum()
                    gross_win = df_f.loc[df_f["net_pts"] > 0, "net_pts"].sum()
                    gross_loss = abs(df_f.loc[df_f["net_pts"] < 0, "net_pts"].sum())
                    pf = gross_win / gross_loss if gross_loss > 0 else np.nan

                    df_f["cum"] = df_f["net_pts"].cumsum()
                    dd = df_f["cum"] - df_f["cum"].cummax()
                    max_dd = abs(dd.min())
                    romad = net_pts / max_dd if max_dd > 0 else 0

                    results.append({
                        "SL Mult": sl_m,
                        "TP Mult": tp_m,
                        "Trades": total_trades,
                        "Win Rate %": win_rate,
                        "Net Pts": net_pts,
                        "Profit Factor": pf,
                        "Max DD (pts)": max_dd,
                        "RoMaD": romad,
                    })

        df_res = pd.DataFrame(results)
        df_res.sort_values(by="Net Pts", ascending=False, inplace=True)

        print(
            "\n================================================================================="
        )
        print("PILLAR 2 FINE-GRAINED GRID SEARCH RESULTS (2024–2026)")
        print(
            "================================================================================="
        )
        print(df_res.to_string(index=False))
        print(
            "================================================================================="
        )

        out_path = Path("research/noise_vp_study/p2_fine_grained_grid_report.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "# Pillar 2 Fine-Grained Grid Search Report (2024–2026)\n\n"
            + df_res.to_markdown(index=False),
            encoding="utf-8",
        )
        print(f"Saved report to {out_path}")


if __name__ == "__main__":
    search = FineGrainedP2GridSearch()
    search.run_search()
