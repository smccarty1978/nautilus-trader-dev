"""V_A baseline fundamentals — descriptive stats on the unfiltered
V_A HH/LL bar+1 confirmed trade population.

Reports:
  1. Trades per day (per year, RTH)
  2. Win rate (net_pnl > 0)
  3. MFE distribution: % reaching 0.5 / 1.0 / 1.5 / 2.0 / 3.0 ATR
  4. MAE distribution: % exceeding 0.5 / 1.0 / 1.5 / 2.0 ATR adverse
  5. MFE/MAE ratio distribution
  6. Hold-time distribution
  7. Winners vs losers — anatomy contrast
  8. By direction (long vs short)
  9. By year cross-stability

This is a fundamentals reset — what does V_A actually look like
on its own, without overlays?
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/v_a_excursion_regime/results_v0")

MFE_THRESHOLDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]
MAE_THRESHOLDS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def load_year_trades(yr):
    base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
    df = pd.read_parquet(base / "trades.parquet")
    df["mfe_atr"] = df["running_mfe"] / df["atr_at_signal"].clip(lower=0.01)
    df["mae_atr"] = df["running_mae"] / df["atr_at_signal"].clip(lower=0.01)
    df["mfe_to_mae"] = df["mfe_atr"] / df["mae_atr"].clip(lower=0.01)
    df["is_winner"] = df["net_pnl"] > 0
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["entry_date"] = df["entry_dt"].dt.tz_convert(
        "America/Chicago").dt.date
    df["hold_min"] = df["hold_s"] / 60
    df["year"] = yr
    return df


def describe_distribution(s, name, units=""):
    if not len(s) or s.isna().all():
        return f"  {name}: n=0"
    s = s.dropna()
    return (f"  {name}: n={len(s):,}  mean={s.mean():.2f}  "
            f"med={s.median():.2f}  p25={s.quantile(0.25):.2f}  "
            f"p75={s.quantile(0.75):.2f}  p90={s.quantile(0.9):.2f}  "
            f"p95={s.quantile(0.95):.2f}  max={s.max():.2f}{units}")


def print_threshold_table(df, col, thresholds, label):
    print(f"\n  --- {label} cumulative threshold % ---")
    print(f"  {'threshold':>10}  {'2024':>7}  {'2025':>7}  "
          f"{'2026':>7}  {'all':>7}")
    for t in thresholds:
        line = f"  >={t:>7.2f} ATR  "
        for yr in (2024, 2025, 2026, "all"):
            sub = df if yr == "all" else df[df["year"] == yr]
            if not len(sub):
                line += f"{'-':>7}  "; continue
            pct = (sub[col] >= t).mean() * 100
            line += f"{pct:>6.1f}%  "
        print(line)


def print_yearly_basics(df):
    print(f"\n{'='*78}")
    print("BASIC COUNTS")
    print(f"{'='*78}")
    print(f"  {'year':<5}  {'trades':>7}  {'days':>5}  {'tr/day':>7}  "
          f"{'WR%':>5}  {'long%':>6}  {'medMFE':>7}  {'medMAE':>7}  "
          f"{'medHold':>7}  {'sumPnL':>10}")
    for yr in (2024, 2025, 2026, "all"):
        sub = df if yr == "all" else df[df["year"] == yr]
        if not len(sub): continue
        n = len(sub)
        days = sub["entry_date"].nunique()
        tr_per = n / max(days, 1)
        wr = sub["is_winner"].mean() * 100
        long_pct = (sub["direction"] == 1).mean() * 100
        med_mfe = sub["mfe_atr"].median()
        med_mae = sub["mae_atr"].median()
        med_hold = sub["hold_min"].median()
        total = sub["net_pnl"].sum()
        print(f"  {str(yr):<5}  {n:>7,}  {days:>5}  {tr_per:>6.1f}  "
              f"{wr:>4.1f}%  {long_pct:>5.1f}%  "
              f"{med_mfe:>+7.2f}  {med_mae:>+7.2f}  "
              f"{med_hold:>6.1f}m  {total:>+9,.0f}")


def main():
    print("=" * 78)
    print("V_A BASELINE DIAGNOSTIC — fundamentals across 2024+2025+2026")
    print("=" * 78)

    parts = [load_year_trades(yr) for yr in (2024, 2025, 2026)]
    df = pd.concat(parts, ignore_index=True)

    # -------- 1. Basic counts --------
    print_yearly_basics(df)

    # -------- 2. MFE thresholds --------
    print(f"\n{'='*78}")
    print(f"% TRADES REACHING MFE THRESHOLD (favorable, ATR units)")
    print(f"{'='*78}")
    print_threshold_table(df, "mfe_atr", MFE_THRESHOLDS,
                            "MFE_atr")

    # -------- 3. MAE thresholds --------
    print(f"\n{'='*78}")
    print(f"% TRADES EXCEEDING MAE THRESHOLD (adverse, ATR units)")
    print(f"{'='*78}")
    print_threshold_table(df, "mae_atr", MAE_THRESHOLDS, "MAE_atr")

    # -------- 4. Distribution summary --------
    print(f"\n{'='*78}")
    print("DISTRIBUTION SUMMARIES (across all 7,794 trades)")
    print(f"{'='*78}")
    print(describe_distribution(df["mfe_atr"], "MFE_atr"))
    print(describe_distribution(df["mae_atr"], "MAE_atr"))
    print(describe_distribution(df["mfe_to_mae"], "MFE/MAE ratio"))
    print(describe_distribution(df["hold_min"], "hold (min)"))
    print(describe_distribution(df["net_pnl"], "net_pnl ($)"))
    print(describe_distribution(df["atr_at_signal"], "ATR at signal "
                                  "(NQ pts)"))

    # -------- 5. Winners vs losers anatomy --------
    print(f"\n{'='*78}")
    print("WINNERS vs LOSERS ANATOMY")
    print(f"{'='*78}")
    win = df[df["is_winner"]]
    lose = df[~df["is_winner"]]
    print(f"\n  Winners (n={len(win):,}, {100*len(win)/len(df):.1f}%):")
    print(describe_distribution(win["mfe_atr"], "  MFE_atr"))
    print(describe_distribution(win["mae_atr"], "  MAE_atr"))
    print(describe_distribution(win["mfe_to_mae"], "  MFE/MAE"))
    print(describe_distribution(win["hold_min"], "  hold (min)"))
    print(describe_distribution(win["net_pnl"], "  net_pnl ($)"))
    print(f"\n  Losers (n={len(lose):,}, {100*len(lose)/len(df):.1f}%):")
    print(describe_distribution(lose["mfe_atr"], "  MFE_atr"))
    print(describe_distribution(lose["mae_atr"], "  MAE_atr"))
    print(describe_distribution(lose["mfe_to_mae"], "  MFE/MAE"))
    print(describe_distribution(lose["hold_min"], "  hold (min)"))
    print(describe_distribution(lose["net_pnl"], "  net_pnl ($)"))

    # -------- 6. By direction --------
    print(f"\n{'='*78}")
    print("BY DIRECTION (long vs short)")
    print(f"{'='*78}")
    print(f"  {'side':<6}  {'n':>5}  {'WR%':>5}  {'medMFE':>7}  "
          f"{'medMAE':>7}  {'sumPnL':>10}")
    for label, mask in [("long", df["direction"] == 1),
                          ("short", df["direction"] == -1)]:
        sub = df[mask]
        n = len(sub)
        wr = sub["is_winner"].mean() * 100
        print(f"  {label:<6}  {n:>5,}  {wr:>4.1f}%  "
              f"{sub['mfe_atr'].median():>+7.2f}  "
              f"{sub['mae_atr'].median():>+7.2f}  "
              f"{sub['net_pnl'].sum():>+9,.0f}")

    # Per-year per-direction
    print(f"\n  Per-year:")
    print(f"  {'year':<5}  {'side':<6}  {'n':>5}  {'WR%':>5}  "
          f"{'pct≥1ATR':>9}  {'medMFE':>7}  {'sumPnL':>10}")
    for yr in (2024, 2025, 2026):
        for label, mask in [("long", df["direction"] == 1),
                              ("short", df["direction"] == -1)]:
            sub = df[(df["year"] == yr) & mask]
            if not len(sub): continue
            wr = sub["is_winner"].mean() * 100
            pct1atr = (sub["mfe_atr"] >= 1.0).mean() * 100
            print(f"  {yr:<5}  {label:<6}  {len(sub):>5,}  {wr:>4.1f}%  "
                  f"{pct1atr:>+8.1f}%  "
                  f"{sub['mfe_atr'].median():>+7.2f}  "
                  f"{sub['net_pnl'].sum():>+9,.0f}")

    # -------- 7. Winner sub-categories (where the money lives) --------
    print(f"\n{'='*78}")
    print("WINNER SUB-CATEGORIES — where the PnL lives")
    print(f"{'='*78}")
    print(f"  {'category':<25}  {'n':>5}  {'%pop':>5}  {'sumPnL':>10}  "
          f"{'$/tr':>7}  {'medMFE':>7}")
    cats = [
        ("All trades",            df["mfe_atr"] >= -np.inf),
        ("Win + MFE >= 1.0",      df["is_winner"] & (df["mfe_atr"] >= 1.0)),
        ("Win + MFE >= 1.5",      df["is_winner"] & (df["mfe_atr"] >= 1.5)),
        ("Win + MFE >= 2.0",      df["is_winner"] & (df["mfe_atr"] >= 2.0)),
        ("Win + MFE >= 3.0",      df["is_winner"] & (df["mfe_atr"] >= 3.0)),
        ("Win + MFE >= 4.0",      df["is_winner"] & (df["mfe_atr"] >= 4.0)),
        ("Loser only",            ~df["is_winner"]),
        ("Loser, MFE < 0.25 (DOA)", ~df["is_winner"] & (df["mfe_atr"] < 0.25)),
        ("Loser, MFE 0.25-1.0",   ~df["is_winner"]
                                      & (df["mfe_atr"] >= 0.25)
                                      & (df["mfe_atr"] < 1.0)),
        ("Loser, MFE >= 1.0 giveback", ~df["is_winner"]
                                            & (df["mfe_atr"] >= 1.0)),
    ]
    for name, mask in cats:
        sub = df[mask]
        if not len(sub): continue
        print(f"  {name:<25}  {len(sub):>5,}  "
              f"{100*len(sub)/len(df):>4.1f}%  "
              f"{sub['net_pnl'].sum():>+9,.0f}  "
              f"{sub['net_pnl'].mean():>+6.1f}  "
              f"{sub['mfe_atr'].median():>+7.2f}")

    # -------- 8. Loser tail breakdown --------
    print(f"\n{'='*78}")
    print("LOSER TAIL — distribution of net_pnl among losers")
    print(f"{'='*78}")
    losers = df[~df["is_winner"]]
    quantiles = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
    print(f"  Loser net_pnl ($) percentiles:")
    for q in quantiles:
        print(f"    p{int(q*100):>3}: ${losers['net_pnl'].quantile(q):>+8.0f}")
    print(f"  Loser MAE_atr percentiles:")
    for q in quantiles:
        print(f"    p{int(q*100):>3}: {losers['mae_atr'].quantile(q):>+5.2f}")

    # -------- 9. Winner sub-stratification --------
    print(f"\n{'='*78}")
    print("WINNER STRATIFICATION (% of total winners' PnL by MFE band)")
    print(f"{'='*78}")
    win_total_pnl = win["net_pnl"].sum()
    bands = [
        ("MFE 0.0 - 1.0",  win[win["mfe_atr"] < 1.0]),
        ("MFE 1.0 - 1.5",  win[(win["mfe_atr"] >= 1.0)
                                & (win["mfe_atr"] < 1.5)]),
        ("MFE 1.5 - 2.0",  win[(win["mfe_atr"] >= 1.5)
                                & (win["mfe_atr"] < 2.0)]),
        ("MFE 2.0 - 3.0",  win[(win["mfe_atr"] >= 2.0)
                                & (win["mfe_atr"] < 3.0)]),
        ("MFE 3.0 - 4.0",  win[(win["mfe_atr"] >= 3.0)
                                & (win["mfe_atr"] < 4.0)]),
        ("MFE >= 4.0",     win[win["mfe_atr"] >= 4.0]),
    ]
    print(f"  {'band':<18}  {'n':>5}  {'%winners':>9}  "
          f"{'sumPnL':>10}  {'%totalPnL':>10}  {'$/tr':>7}")
    for label, sub in bands:
        if not len(sub):
            print(f"  {label:<18}  {0:>5,}"); continue
        pct = 100 * len(sub) / len(win)
        sp = sub["net_pnl"].sum()
        pct_pnl = 100 * sp / max(win_total_pnl, 1)
        print(f"  {label:<18}  {len(sub):>5,}  {pct:>8.1f}%  "
              f"{sp:>+9,.0f}  {pct_pnl:>+9.1f}%  "
              f"{sub['net_pnl'].mean():>+6.1f}")

    # -------- 10. Hold time stratification --------
    print(f"\n{'='*78}")
    print("HOLD-TIME BANDS — count + WR + PnL")
    print(f"{'='*78}")
    bands = [
        ("≤ 2 min",   df["hold_min"] <= 2),
        ("2-5 min",   (df["hold_min"] > 2) & (df["hold_min"] <= 5)),
        ("5-10 min",  (df["hold_min"] > 5) & (df["hold_min"] <= 10)),
        ("10-20 min", (df["hold_min"] > 10) & (df["hold_min"] <= 20)),
        ("20-40 min", (df["hold_min"] > 20) & (df["hold_min"] <= 40)),
        ("> 40 min",  df["hold_min"] > 40),
    ]
    print(f"  {'band':<12}  {'n':>5}  {'%pop':>6}  {'WR%':>5}  "
          f"{'medMFE':>7}  {'sumPnL':>10}  {'$/tr':>7}")
    for label, mask in bands:
        sub = df[mask]
        if not len(sub): continue
        wr = sub["is_winner"].mean() * 100
        print(f"  {label:<12}  {len(sub):>5,}  "
              f"{100*len(sub)/len(df):>5.1f}%  {wr:>4.1f}%  "
              f"{sub['mfe_atr'].median():>+7.2f}  "
              f"{sub['net_pnl'].sum():>+9,.0f}  "
              f"{sub['net_pnl'].mean():>+6.1f}")


if __name__ == "__main__":
    main()
