"""Path Diagnostics analyzer — Sections 1-7 + final recommendation."""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/momentum_confirm_path_v1/results")
YEARS = [2024, 2025, 2026]
MODES = ["1m_momentum", "30s_momentum"]
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
SL_THRESHOLDS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
TIME_CHECKPOINTS = [60, 120, 180, 300, 600]
TRAIL_ACTIVATIONS = [0.75, 1.00, 1.50, 2.00]
TRAIL_GIVEBACKS = [0.50, 0.75, 1.00, 1.50]
SECTION6_CHECKPOINTS = [30, 60, 120, 180, 300, 600, 900, 1200]


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_dd(s):
    if len(s) == 0:
        return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats_pnl(pnl_arr):
    s = pd.Series(pnl_arr).dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    return {
        "n": n, "wr": float((s > 0).mean()),
        "mean": float(s.mean()), "median": float(s.median()),
        "sum": float(s.sum()), "pf": float(pf),
        "max_dd": max_dd(s),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses)
                      else float("nan"),
    }


def load_trades(mode, year):
    p = OUT / f"trades_{mode}_{year}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def load_paths(mode, year):
    p = OUT / f"paths_{mode}_{year}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def section1_baseline(lines):
    lines.append("## Section 1 — Baseline path profile")
    lines.append("")
    lines.append("| Year | Mode | n | WR | Mean $ | Med $ | PF | "
                 "Avg Win | Avg Loss | Med Dur | Med MFE | Mean MFE | "
                 "Med MAE | Mean MAE | Med Cap | Mean Cap |")
    lines.append(
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            if not len(df):
                continue
            s = stats_pnl(df["final_net_pnl"])
            med_dur_min = df["duration_s"].median() / 60
            med_mfe = df["max_mfe_atr"].median()
            mean_mfe = df["max_mfe_atr"].mean()
            med_mae = df["max_mae_atr"].median()
            mean_mae = df["max_mae_atr"].mean()
            cap = df["mfe_capture_ratio"].dropna()
            med_cap = cap.median() if len(cap) else float("nan")
            mean_cap = cap.mean() if len(cap) else float("nan")
            lines.append(
                f"| {year} | {mode} | {s['n']:,} | "
                f"{fmt_p(s['wr'])} | {fmt_d(s['mean'])} | "
                f"{fmt_d(s['median'])} | {s['pf']:.2f} | "
                f"{fmt_d(s['avg_win'])} | {fmt_d(s['avg_loss'])} | "
                f"{med_dur_min:.1f}m | "
                f"{med_mfe:.2f} | {mean_mfe:.2f} | "
                f"{med_mae:.2f} | {mean_mae:.2f} | "
                f"{med_cap:.2f} | {mean_cap:.2f} |")
    lines.append("")

    lines.append("MFE/MAE threshold reach rates (% of trades):")
    lines.append("")
    lines.append("| Year | Mode | MFE>=0.5 | MFE>=1.0 | MFE>=1.5 | "
                 "MFE>=2.0 | MAE>=0.5 | MAE>=0.75 | MAE>=1.0 |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            if not len(df):
                continue
            n = len(df)
            cells = [str(year), mode]
            for col, thr in [("max_mfe_atr", 0.5),
                              ("max_mfe_atr", 1.0),
                              ("max_mfe_atr", 1.5),
                              ("max_mfe_atr", 2.0),
                              ("max_mae_atr", 0.5),
                              ("max_mae_atr", 0.75),
                              ("max_mae_atr", 1.0)]:
                cells.append(fmt_p((df[col] >= thr).mean()))
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")


def simulate_sl(df, sl_thr):
    """Apply catastrophic SL = sl_thr ATR. Trade exits at SL hit if
    MAE crosses sl_thr first (using t_mae_<thr>_s); otherwise final
    PnL = baseline regime exit."""
    out_pnl = []
    stopped = []
    sl_key = f"t_mae_{int(sl_thr*100):03d}_s"
    if sl_key not in df.columns:
        # Compute by interpolation: assume SL hit if max_mae_atr >= sl_thr
        for _, row in df.iterrows():
            if row["max_mae_atr"] >= sl_thr:
                pnl = (-sl_thr * row["atr_at_signal"] * NQ_MULT
                         - COMMISSION - 2 * TICK_COST)
                out_pnl.append(pnl)
                stopped.append(True)
            else:
                out_pnl.append(row["final_net_pnl"])
                stopped.append(False)
    else:
        sl_times = df[sl_key].values
        atrs = df["atr_at_signal"].values
        finals = df["final_net_pnl"].values
        for i in range(len(df)):
            if not pd.isna(sl_times[i]):
                pnl = (-sl_thr * atrs[i] * NQ_MULT
                         - COMMISSION - 2 * TICK_COST)
                out_pnl.append(pnl)
                stopped.append(True)
            else:
                out_pnl.append(finals[i])
                stopped.append(False)
    return np.array(out_pnl), np.array(stopped)


def section2_catastrophic_sl(lines):
    lines.append("## Section 2 — Catastrophic SL study")
    lines.append("")
    lines.append("Apply SL overlay; otherwise hold to regime exit. "
                 "SL exit cost = $5 commission + 2-tick adverse slip.")
    lines.append("")

    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            if not len(df):
                continue
            base_pnl = df["final_net_pnl"].values
            base_s = stats_pnl(base_pnl)
            lines.append(f"### {year} — {mode}")
            lines.append("")
            lines.append(
                f"Baseline (no SL): n={base_s['n']:,}, "
                f"WR={fmt_p(base_s['wr'])}, "
                f"mean={fmt_d(base_s['mean'])}, "
                f"PF={base_s['pf']:.2f}, total={fmt_d(base_s['sum'])}, "
                f"max DD={fmt_d(base_s['max_dd'])}")
            lines.append("")
            lines.append("| SL ATR | n | WR | Mean $ | Med $ | PF | "
                         "Total $ | Max DD | %Stopped | %Win Stopped | "
                         "%Loss Stopped | Δ Mean $ | Δ Total $ |")
            lines.append(
                "|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
            base_winners = df["final_net_pnl"] > 0
            base_losers = ~base_winners
            for sl in SL_THRESHOLDS:
                pnls, stopped = simulate_sl(df, sl)
                s = stats_pnl(pnls)
                pct_stopped = stopped.mean()
                # Of original winners, how many were stopped?
                pct_win_stopped = (
                    stopped[base_winners].mean()
                    if base_winners.any() else 0.0)
                pct_loss_stopped = (
                    stopped[base_losers].mean()
                    if base_losers.any() else 0.0)
                lines.append(
                    f"| {sl} | {s['n']:,} | {fmt_p(s['wr'])} | "
                    f"{fmt_d(s['mean'])} | {fmt_d(s['median'])} | "
                    f"{s['pf']:.2f} | {fmt_d(s['sum'])} | "
                    f"{fmt_d(s['max_dd'])} | "
                    f"{fmt_p(pct_stopped)} | "
                    f"{fmt_p(pct_win_stopped)} | "
                    f"{fmt_p(pct_loss_stopped)} | "
                    f"{fmt_d(s['mean'] - base_s['mean'])} | "
                    f"{fmt_d(s['sum'] - base_s['sum'])} |")
            lines.append("")

    # Critical winner-tail table
    lines.append("### Winner-tail diagnostic")
    lines.append("")
    lines.append("Among ORIGINAL winners (those that ended positive "
                 "without any SL), what fraction had their MAE reach "
                 "each SL threshold during the trade?")
    lines.append("")
    lines.append("| Year | Mode | Med MAE (winners) | P90 MAE | "
                 "Mean MAE | %WinMAE>=0.5 | >=0.75 | >=1.0 | >=1.5 | "
                 ">=2.0 |")
    lines.append(
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            if not len(df):
                continue
            wins = df[df["final_net_pnl"] > 0]
            if not len(wins):
                continue
            mae = wins["max_mae_atr"]
            cells = [
                str(year), mode,
                f"{mae.median():.2f}",
                f"{mae.quantile(0.90):.2f}",
                f"{mae.mean():.2f}",
            ]
            for thr in [0.5, 0.75, 1.0, 1.5, 2.0]:
                cells.append(fmt_p((mae >= thr).mean()))
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")


def simulate_time_stop(df, paths, checkpoint_s, rule_fn):
    """Simulate exit at checkpoint if rule_fn(peak_mfe, peak_mae,
    pnl_atr) is True; otherwise hold to regime exit (final_net_pnl).
    """
    # For each trade, find the path row at <= checkpoint_s
    # Path is at PATH_STEP_S = 5s intervals
    nearest_cp = (checkpoint_s // 5) * 5
    cp_paths = paths[paths["elapsed_s"] == nearest_cp][
        ["trade_id", "peak_mfe_atr", "peak_mae_atr",
         "pnl_atr", "close_price"]]
    df = df.merge(cp_paths, on="trade_id", how="left",
                    suffixes=("", "_cp"))
    # For trades whose duration < checkpoint_s, no cp row — keep final
    out_pnl = []
    exited_early = []
    cut_winners = 0
    cut_losers = 0
    saved_on_losers = []
    sacrificed_on_winners = []
    for _, row in df.iterrows():
        cp_pnl_atr = row.get("pnl_atr")
        cp_mfe = row.get("peak_mfe_atr")
        cp_mae = row.get("peak_mae_atr")
        cp_close = row.get("close_price")
        if pd.isna(cp_pnl_atr) or pd.isna(cp_close):
            # Trade ended before checkpoint — no early exit possible
            out_pnl.append(row["final_net_pnl"])
            exited_early.append(False)
            continue
        if rule_fn(cp_mfe, cp_mae, cp_pnl_atr):
            # Early exit at cp_close
            atr = row["atr_at_signal"]
            d = row["direction"]
            fill = row["fill_price"]
            gross = (cp_close - fill) * d * NQ_MULT
            # 1-tick exit slip
            pnl = gross - COMMISSION - TICK_COST
            out_pnl.append(pnl)
            exited_early.append(True)
            base = row["final_net_pnl"]
            if base > 0:
                cut_winners += 1
                sacrificed_on_winners.append(base - pnl)
            else:
                cut_losers += 1
                saved_on_losers.append(pnl - base)
        else:
            out_pnl.append(row["final_net_pnl"])
            exited_early.append(False)
    return (np.array(out_pnl), np.array(exited_early),
              cut_winners, cut_losers,
              np.array(saved_on_losers),
              np.array(sacrificed_on_winners))


def section3_time_stops(lines):
    lines.append("## Section 3 — Early failure / time-stop diagnostics")
    lines.append("")
    rules = [
        ("MFE<0.25 ATR", lambda mfe, mae, p: mfe < 0.25),
        ("MFE<0.50 ATR", lambda mfe, mae, p: mfe < 0.50),
        ("PnL<0", lambda mfe, mae, p: p < 0),
        ("PnL<-0.25 ATR", lambda mfe, mae, p: p < -0.25),
        ("PnL<-0.50 ATR", lambda mfe, mae, p: p < -0.50),
        ("MFE<0.50 AND PnL<0",
         lambda mfe, mae, p: mfe < 0.50 and p < 0),
    ]
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            paths = load_paths(mode, year)
            if not len(df):
                continue
            base_s = stats_pnl(df["final_net_pnl"])
            lines.append(f"### {year} — {mode}")
            lines.append("")
            lines.append(
                f"Baseline: mean={fmt_d(base_s['mean'])}, "
                f"PF={base_s['pf']:.2f}, total={fmt_d(base_s['sum'])}")
            lines.append("")
            lines.append("| CP | Rule | Mean $ | PF | Total $ | "
                         "Max DD | %Exit | %Win Cut | %Loss Cut | "
                         "Avg Saved | Avg Sacrificed | Δ Mean |")
            lines.append(
                "|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
            for cp in TIME_CHECKPOINTS:
                for rname, rfn in rules:
                    pnls, exited, cw, cl, saved, sac = (
                        simulate_time_stop(df, paths, cp, rfn))
                    s = stats_pnl(pnls)
                    n_total = len(df)
                    n_winners = int((df["final_net_pnl"] > 0).sum())
                    n_losers = n_total - n_winners
                    lines.append(
                        f"| {cp}s | {rname} | "
                        f"{fmt_d(s['mean'])} | {s['pf']:.2f} | "
                        f"{fmt_d(s['sum'])} | "
                        f"{fmt_d(s['max_dd'])} | "
                        f"{fmt_p(exited.mean())} | "
                        f"{fmt_p(cw / max(1, n_winners))} | "
                        f"{fmt_p(cl / max(1, n_losers))} | "
                        f"{fmt_d(saved.mean()) if len(saved) else '—'} | "
                        f"{fmt_d(sac.mean()) if len(sac) else '—'} | "
                        f"{fmt_d(s['mean'] - base_s['mean'])} |")
            lines.append("")


def simulate_trail(df, paths, activation, giveback):
    """For each trade, find first time peak_mfe >= activation. After
    that, exit when (peak_mfe - pnl_atr) >= giveback. If never
    exited, take final PnL."""
    grouped = paths.groupby("trade_id")
    out_pnl = []
    trailed = []
    for _, row in df.iterrows():
        tid = row["trade_id"]
        if tid not in grouped.groups:
            out_pnl.append(row["final_net_pnl"])
            trailed.append(False)
            continue
        path = grouped.get_group(tid).sort_values("elapsed_s")
        peak_mfe = path["peak_mfe_atr"].values
        pnl_atr = path["pnl_atr"].values
        close = path["close_price"].values
        active = False
        exit_idx = None
        for i in range(len(peak_mfe)):
            if not active:
                if peak_mfe[i] >= activation:
                    active = True
            if active:
                give = peak_mfe[i] - pnl_atr[i]
                if give >= giveback:
                    exit_idx = i
                    break
        if exit_idx is not None:
            atr = row["atr_at_signal"]
            d = row["direction"]
            fill = row["fill_price"]
            gross = (close[exit_idx] - fill) * d * NQ_MULT
            pnl = gross - COMMISSION - TICK_COST
            out_pnl.append(pnl)
            trailed.append(True)
        else:
            out_pnl.append(row["final_net_pnl"])
            trailed.append(False)
    return np.array(out_pnl), np.array(trailed)


def section4_trailing(lines):
    lines.append("## Section 4 — MFE capture / trailing exit "
                 "diagnostics")
    lines.append("")
    lines.append("Trailing rule: once MFE >= activation, exit when "
                 "PnL gives back >= giveback ATR from peak. Else hold "
                 "to regime exit.")
    lines.append("")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            paths = load_paths(mode, year)
            if not len(df) or not len(paths):
                continue
            base_s = stats_pnl(df["final_net_pnl"])
            base_winners = (df["final_net_pnl"] > 0).values
            base_losers = ~base_winners
            lines.append(f"### {year} — {mode}")
            lines.append("")
            lines.append(
                f"Baseline: mean={fmt_d(base_s['mean'])}, "
                f"PF={base_s['pf']:.2f}, total={fmt_d(base_s['sum'])}")
            lines.append("")
            lines.append("| Activate | Giveback | Mean $ | PF | "
                         "Total $ | Max DD | Avg Win | Avg Loss | "
                         "%Trailed | %Win Trailed | %Loss Trailed | "
                         "Δ Mean |")
            lines.append(
                "|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
            for act in TRAIL_ACTIVATIONS:
                for give in TRAIL_GIVEBACKS:
                    if give >= act:
                        continue  # giveback should be < activation
                    pnls, trailed = simulate_trail(df, paths,
                                                       act, give)
                    s = stats_pnl(pnls)
                    pct_trailed = trailed.mean()
                    pct_win_trailed = (
                        trailed[base_winners].mean()
                        if base_winners.any() else 0)
                    pct_loss_trailed = (
                        trailed[base_losers].mean()
                        if base_losers.any() else 0)
                    lines.append(
                        f"| {act} | {give} | "
                        f"{fmt_d(s['mean'])} | {s['pf']:.2f} | "
                        f"{fmt_d(s['sum'])} | "
                        f"{fmt_d(s['max_dd'])} | "
                        f"{fmt_d(s['avg_win'])} | "
                        f"{fmt_d(s['avg_loss'])} | "
                        f"{fmt_p(pct_trailed)} | "
                        f"{fmt_p(pct_win_trailed)} | "
                        f"{fmt_p(pct_loss_trailed)} | "
                        f"{fmt_d(s['mean'] - base_s['mean'])} |")
            lines.append("")


def simulate_partial(df, paths, model):
    """Models:
      A: 1/2 off at +1.0 ATR, hold 1/2 to regime exit
      B: 1/2 off at +1.0 ATR, trail remainder by 0.75 ATR after
         +1.5 MFE
      C: 1/2 off at +0.75 ATR, hold 1/2 to regime exit
    """
    grouped = paths.groupby("trade_id")
    out_pnl = []
    for _, row in df.iterrows():
        tid = row["trade_id"]
        atr = row["atr_at_signal"]
        d = row["direction"]
        fill = row["fill_price"]
        final_full = row["final_net_pnl"]
        # Find first time MFE reaches partial threshold
        if model == "A":
            partial_thr = 1.0
            partial_lot = 0.5
        elif model == "B":
            partial_thr = 1.0
            partial_lot = 0.5
        elif model == "C":
            partial_thr = 0.75
            partial_lot = 0.5
        # Lookup t_mfe_<thr>
        t_col = f"t_mfe_{int(partial_thr*100):03d}_s"
        partial_t = row.get(t_col)
        if pd.isna(partial_t):
            # Never reached partial — full lot to regime exit
            out_pnl.append(final_full)
            continue
        # Partial PnL: take partial_lot at +partial_thr ATR
        partial_pnl = (partial_lot * partial_thr * atr * NQ_MULT
                         - partial_lot * COMMISSION
                         - partial_lot * TICK_COST)
        # Remainder
        if model in ("A", "C"):
            # Hold remainder to regime exit
            # remainder = (1 - partial_lot) of final_full
            # final_full was computed for full lot; remainder is
            # (1 - partial_lot) * (final_full + cost) - cost_remainder
            # Simpler: scale gross by (1-partial_lot) and subtract
            # remainder cost separately
            remainder_gross = ((row["regime_end_price"] - fill)
                                  * d * NQ_MULT * (1 - partial_lot))
            remainder_pnl = (remainder_gross
                                - (1 - partial_lot) * COMMISSION
                                - (1 - partial_lot) * TICK_COST)
            out_pnl.append(partial_pnl + remainder_pnl)
        elif model == "B":
            # Trail remainder by 0.75 ATR after +1.5 MFE
            if tid not in grouped.groups:
                # No path data — fall back to regime exit
                remainder_gross = ((row["regime_end_price"] - fill)
                                      * d * NQ_MULT
                                      * (1 - partial_lot))
                remainder_pnl = (remainder_gross
                                    - (1 - partial_lot) * COMMISSION
                                    - (1 - partial_lot) * TICK_COST)
                out_pnl.append(partial_pnl + remainder_pnl)
                continue
            path = grouped.get_group(tid).sort_values("elapsed_s")
            peak_mfe = path["peak_mfe_atr"].values
            pnl_atr = path["pnl_atr"].values
            close = path["close_price"].values
            active = False
            exit_idx = None
            for i in range(len(peak_mfe)):
                if not active and peak_mfe[i] >= 1.5:
                    active = True
                if active:
                    if peak_mfe[i] - pnl_atr[i] >= 0.75:
                        exit_idx = i
                        break
            if exit_idx is not None:
                rem_gross = ((close[exit_idx] - fill) * d * NQ_MULT
                                * (1 - partial_lot))
            else:
                rem_gross = ((row["regime_end_price"] - fill)
                                * d * NQ_MULT
                                * (1 - partial_lot))
            rem_pnl = (rem_gross
                          - (1 - partial_lot) * COMMISSION
                          - (1 - partial_lot) * TICK_COST)
            out_pnl.append(partial_pnl + rem_pnl)
    return np.array(out_pnl)


def section5_partials(lines):
    lines.append("## Section 5 — Partial profit diagnostics")
    lines.append("")
    lines.append("First, raw probabilities:")
    lines.append("")
    lines.append("| Year | Mode | %trade reaches +0.5 | +0.75 | +1.0 | "
                 "+1.5 | %reach -0.5 | -0.75 |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            if not len(df):
                continue
            cells = [str(year), mode]
            for thr in [0.5, 0.75, 1.0, 1.5]:
                col = f"t_mfe_{int(thr*100):03d}_s"
                cells.append(fmt_p(df[col].notna().mean()))
            for thr in [0.5, 0.75]:
                col = f"t_mae_{int(thr*100):03d}_s"
                cells.append(fmt_p(df[col].notna().mean()))
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("Partial models (1/2 lot at threshold + remainder "
                 "to regime exit or trailed):")
    lines.append("")
    lines.append("| Year | Mode | Model | Mean $ | PF | Total $ | "
                 "Max DD | Avg Win | Avg Loss | Δ Mean | Δ Total |")
    lines.append(
        "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            paths = load_paths(mode, year)
            if not len(df):
                continue
            base_s = stats_pnl(df["final_net_pnl"])
            for model in ["A", "B", "C"]:
                pnls = simulate_partial(df, paths, model)
                s = stats_pnl(pnls)
                desc = {
                    "A": "1/2 @ +1.0, hold rest",
                    "B": "1/2 @ +1.0, trail rest (act 1.5, give 0.75)",
                    "C": "1/2 @ +0.75, hold rest",
                }[model]
                lines.append(
                    f"| {year} | {mode} | {desc} | "
                    f"{fmt_d(s['mean'])} | {s['pf']:.2f} | "
                    f"{fmt_d(s['sum'])} | {fmt_d(s['max_dd'])} | "
                    f"{fmt_d(s['avg_win'])} | "
                    f"{fmt_d(s['avg_loss'])} | "
                    f"{fmt_d(s['mean'] - base_s['mean'])} | "
                    f"{fmt_d(s['sum'] - base_s['sum'])} |")
    lines.append("")


def section6_winner_vs_loser_paths(lines):
    lines.append("## Section 6 — Winner vs loser path comparison")
    lines.append("")
    lines.append("Per-checkpoint median MFE/MAE for winners vs losers, "
                 "plus probability trade is positive at each "
                 "checkpoint.")
    lines.append("")
    for year in YEARS:
        for mode in MODES:
            df = load_trades(mode, year)
            paths = load_paths(mode, year)
            if not len(df) or not len(paths):
                continue
            df["is_win"] = df["final_net_pnl"] > 0
            paths_with_label = paths.merge(
                df[["trade_id", "is_win"]], on="trade_id")
            lines.append(f"### {year} — {mode}")
            lines.append("")
            lines.append(
                "| Checkpoint | n W/L | Med MFE W/L | "
                "Med MAE W/L | %positive W/L | "
                "%MFE>=0.5 W/L | %MAE>=0.5 W/L |")
            lines.append(
                "|--:|---|---|---|---|---|---|")
            for cp in SECTION6_CHECKPOINTS:
                cp_path = paths_with_label[
                    paths_with_label["elapsed_s"] == cp]
                if not len(cp_path):
                    continue
                wins_p = cp_path[cp_path["is_win"]]
                losses_p = cp_path[~cp_path["is_win"]]
                if not len(wins_p) or not len(losses_p):
                    continue
                lines.append(
                    f"| {cp}s | "
                    f"{len(wins_p):,} / {len(losses_p):,} | "
                    f"{wins_p['peak_mfe_atr'].median():.2f} / "
                    f"{losses_p['peak_mfe_atr'].median():.2f} | "
                    f"{wins_p['peak_mae_atr'].median():.2f} / "
                    f"{losses_p['peak_mae_atr'].median():.2f} | "
                    f"{fmt_p((wins_p['pnl_atr'] > 0).mean())} / "
                    f"{fmt_p((losses_p['pnl_atr'] > 0).mean())} | "
                    f"{fmt_p((wins_p['peak_mfe_atr'] >= 0.5).mean())} / "
                    f"{fmt_p((losses_p['peak_mfe_atr'] >= 0.5).mean())} | "
                    f"{fmt_p((wins_p['peak_mae_atr'] >= 0.5).mean())} / "
                    f"{fmt_p((losses_p['peak_mae_atr'] >= 0.5).mean())} |")
            lines.append("")


def main():
    lines = []
    lines.append("# Momentum Confirm Path Diagnostics v1")
    lines.append("")
    lines.append("Path-reconstruction analysis of NT-validated "
                 "momentum-confirmation regime-exit strategies "
                 "(V_A = 1m HH/LL+momentum, V_B = 30s HH/LL+momentum) "
                 "across 2024 / 2025 / 2026.")
    lines.append("")
    lines.append(
        "**Causal exit**: regime-end at next opposing 1m flip's "
        "CLOSE. **Cost model**: $5 commission + 1-tick exit slip "
        "(2-tick on SL).")
    lines.append("")

    print("Section 1...")
    section1_baseline(lines)
    print("Section 2...")
    section2_catastrophic_sl(lines)
    print("Section 3...")
    section3_time_stops(lines)
    print("Section 4...")
    section4_trailing(lines)
    print("Section 5...")
    section5_partials(lines)
    print("Section 6...")
    section6_winner_vs_loser_paths(lines)

    # Section 7 + verdict in a follow-up
    out_path = OUT / "PATH_DIAGNOSTICS_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
