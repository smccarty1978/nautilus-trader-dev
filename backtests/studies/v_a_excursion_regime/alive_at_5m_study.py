"""V_A "alive at +5m" cohort — anatomy of trades still open at +5m.

Goal: among trades surviving past 5 minutes, can we capture eventual
winners' remaining MFE while limiting losers' remaining MAE?

For each V_A trade alive at +5m:
  - State at +5m (from entry): current_mfe_atr, current_mae_atr, unrealized
  - Remaining MFE from +5m forward (anchored at price_at_5m)
  - Remaining MAE from +5m forward (anchored at price_at_5m)
  - Final outcome (winner / loser by net_pnl)

Reports:
  1. Cohort sizes (V_A total, alive at +5m, dead before +5m)
  2. Outcome distribution among alive-at-+5m
  3. Winner/loser stats from +5m forward
  4. Hypothetical: double-up at +5m (add 1 contract at +5m price,
     exits at regime flip with 2nd contract — does the math work?)

Causality: every read uses bars with ts_event < cp_ts. Future MFE
window = [+5m, exit_ts).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMMISSION = 5.0
SURVIVE_S = 300   # +5 minutes

OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_year_bars(year):
    parts = []
    files_for_year = {
        2024: ["data/raw/NQ_v0_1s_2023.parquet",
                "data/raw/NQ_v0_1s_2024.parquet"],
        2025: ["data/raw/NQ_v0_1s_2024.parquet",
                "data/raw/NQ_v0_1s_2025.parquet"],
        2026: ["data/raw/NQ_v0_1s_2025.parquet",
                "data/raw/NQ_v0_1s_2026_ytd.parquet"],
    }
    for f in files_for_year[year]:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def state_at_checkpoint(direction, fill_px, entry_ts, cp_ts, atr,
                            ts_idx, opens, highs, lows, closes):
    """State of trade at cp_ts, computed from price action in
    [entry_ts, cp_ts). Returns dict + price at cp_ts."""
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
    if j_hi <= j_lo: return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
        unr_pts = float(seg_c - fill_px)
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
        unr_pts = float(fill_px - seg_c)
    # price at cp_ts = OPEN of bar at-or-after cp_ts
    price_at_cp = float(opens[j_hi]) if j_hi < len(opens) else np.nan
    return {
        "current_mfe_atr": cur_mfe / max(atr, 0.01),
        "current_mae_atr": cur_mae / max(atr, 0.01),
        "unrealized_pnl": unr_pts * NQ_MULT,
        "price_at_cp": price_at_cp,
    }


def future_excursion(direction, anchor_px, start_ts, exit_ts, atr,
                       ts_idx, highs, lows, closes):
    """Compute MFE/MAE from anchor_px over [start_ts, exit_ts)."""
    i_lo = np.searchsorted(ts_idx, start_ts, side="left")
    i_hi = np.searchsorted(ts_idx, exit_ts, side="left")
    if i_hi <= i_lo: return None
    seg_h = highs[i_lo:i_hi]
    seg_l = lows[i_lo:i_hi]
    if direction == 1:
        future_mfe = float(seg_h.max() - anchor_px)
        future_mae = float(anchor_px - seg_l.min())
    else:
        future_mfe = float(anchor_px - seg_l.min())
        future_mae = float(seg_h.max() - anchor_px)
    return {
        "future_mfe_atr": future_mfe / max(atr, 0.01),
        "future_mae_atr": future_mae / max(atr, 0.01),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A 'ALIVE AT +5m' COHORT ANATOMY")
    print("=" * 78)

    rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n  loading {yr}...", flush=True)
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        trades = pd.read_parquet(base / "trades.parquet")
        trades["year"] = yr
        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        for _, tr in trades.iterrows():
            entry_ts = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])
            net_pnl = float(tr["net_pnl"])
            hold_s = float(tr["hold_s"])

            cp_ts = entry_ts + SURVIVE_S * 1_000_000_000
            alive = cp_ts < exit_ts

            row = {
                "year": yr, "entry_ts": entry_ts, "exit_ts": exit_ts,
                "direction": direction, "atr": atr,
                "fill_px": fill_px, "net_pnl": net_pnl,
                "hold_s": hold_s,
                "is_winner": net_pnl > 0,
                "alive_at_5m": alive,
            }
            if not alive:
                rows.append(row); continue

            s = state_at_checkpoint(
                direction, fill_px, entry_ts, cp_ts, atr,
                ts_idx, opens, highs, lows, closes)
            if s is None:
                row["alive_at_5m"] = False
                rows.append(row); continue

            row.update({
                "mfe_atr_at_5m": s["current_mfe_atr"],
                "mae_atr_at_5m": s["current_mae_atr"],
                "unrealized_at_5m": s["unrealized_pnl"],
                "price_at_5m": s["price_at_cp"],
            })

            # Future excursion from +5m onward
            f = future_excursion(
                direction, s["price_at_cp"], cp_ts, exit_ts, atr,
                ts_idx, highs, lows, closes)
            if f:
                row.update({
                    "future_mfe_atr": f["future_mfe_atr"],
                    "future_mae_atr": f["future_mae_atr"],
                })

            # Hypothetical: add 1 contract at price_at_5m, exit at regime
            # PnL on the added C2 contract:
            #   long: (exit_px - price_at_5m) * 20 - $10 commission
            if direction == 1:
                c2_pts = float(tr["exit_price"]) - s["price_at_cp"]
            else:
                c2_pts = s["price_at_cp"] - float(tr["exit_price"])
            row["c2_added_at_5m_pnl"] = c2_pts * NQ_MULT - 2 * COMMISSION

            rows.append(row)

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "alive_at_5m.parquet")
    print(f"\n  total trades: {len(df):,}")

    # ============ Cohort sizes ============
    print(f"\n{'='*78}")
    print("COHORT BREAKDOWN")
    print(f"{'='*78}")
    print(f"  {'year':<5}  {'total':>6}  {'<5m':>5}  {'≥5m':>5}  "
          f"{'survive%':>9}")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        n = len(sub)
        alive = sub["alive_at_5m"].sum()
        print(f"  {yr:<5}  {n:>6,}  {n-alive:>5,}  {alive:>5,}  "
              f"{100*alive/n:>8.1f}%")
    n = len(df); alive = df["alive_at_5m"].sum()
    print(f"  {'all':<5}  {n:>6,}  {n-alive:>5,}  {alive:>5,}  "
          f"{100*alive/n:>8.1f}%")

    # ============ PnL by cohort ============
    print(f"\n{'='*78}")
    print("PnL CONTRIBUTION BY COHORT")
    print(f"{'='*78}")
    print(f"  {'cohort':<22}  {'n':>5}  {'WR%':>5}  {'sum$':>10}  "
          f"{'$/tr':>7}")
    for label, mask in [
        ("dead < 5min",  ~df["alive_at_5m"]),
        ("alive ≥ 5min", df["alive_at_5m"]),
        ("ALL",          df["alive_at_5m"].notna()),
    ]:
        sub = df[mask]
        if not len(sub): continue
        wr = sub["is_winner"].mean() * 100
        print(f"  {label:<22}  {len(sub):>5,}  {wr:>4.1f}%  "
              f"{sub['net_pnl'].sum():>+9,.0f}  "
              f"{sub['net_pnl'].mean():>+6.1f}")

    # ============ Alive-at-5m WINNER vs LOSER anatomy ============
    print(f"\n{'='*78}")
    print("ALIVE @ +5m — WINNER vs LOSER ANATOMY")
    print(f"{'='*78}")
    alive_df = df[df["alive_at_5m"]].copy()
    print(f"\n  Total alive @ +5m: {len(alive_df):,}")
    print(f"  Winners: {alive_df['is_winner'].sum():,} "
          f"({100*alive_df['is_winner'].mean():.1f}% WR)")

    print(f"\n  --- STATE AT +5m (from entry) ---")
    for col, label in [
        ("mfe_atr_at_5m", "MFE_atr at +5m"),
        ("mae_atr_at_5m", "MAE_atr at +5m"),
        ("unrealized_at_5m", "Unrealized $ at +5m"),
    ]:
        win = alive_df[alive_df["is_winner"]][col].dropna()
        lose = alive_df[~alive_df["is_winner"]][col].dropna()
        print(f"\n  {label}:")
        for name, s in [("winners", win), ("losers", lose)]:
            if len(s):
                print(f"    {name}: med={s.median():.2f}  "
                      f"p25={s.quantile(0.25):.2f}  "
                      f"p75={s.quantile(0.75):.2f}  "
                      f"p90={s.quantile(0.9):.2f}")

    print(f"\n  --- FUTURE EXCURSION (from +5m anchor) ---")
    for col, label in [
        ("future_mfe_atr", "Future MFE_atr (from price@5m)"),
        ("future_mae_atr", "Future MAE_atr (from price@5m)"),
    ]:
        win = alive_df[alive_df["is_winner"]][col].dropna()
        lose = alive_df[~alive_df["is_winner"]][col].dropna()
        print(f"\n  {label}:")
        for name, s in [("winners", win), ("losers", lose)]:
            if len(s):
                print(f"    {name}: med={s.median():.2f}  "
                      f"p25={s.quantile(0.25):.2f}  "
                      f"p75={s.quantile(0.75):.2f}  "
                      f"p90={s.quantile(0.9):.2f}  mean={s.mean():.2f}")

    # ============ Future MFE thresholds ============
    print(f"\n{'='*78}")
    print("% OF ALIVE-AT-5m TRADES REACHING FUTURE MFE THRESHOLDS")
    print(f"{'='*78}")
    print(f"  {'threshold':>10}  {'all alive':>10}  {'winners':>9}  "
          f"{'losers':>8}")
    for t in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        all_pct = (alive_df["future_mfe_atr"] >= t).mean() * 100
        win_pct = (alive_df[alive_df["is_winner"]
                            ]["future_mfe_atr"] >= t).mean() * 100
        lose_pct = (alive_df[~alive_df["is_winner"]
                              ]["future_mfe_atr"] >= t).mean() * 100
        print(f"  ≥{t:>5.2f} ATR  {all_pct:>+9.1f}%  "
              f"{win_pct:>+8.1f}%  {lose_pct:>+7.1f}%")

    # ============ Hypothetical: double-up at +5m ============
    print(f"\n{'='*78}")
    print("HYPOTHETICAL: ADD 1 CONTRACT AT +5m (alive cohort only)")
    print(f"{'='*78}")
    print(f"  C2 enters at price_at_+5m, exits at regime flip.")
    print(f"  C2 PnL = (exit_px - price_at_5m) * direction * 20 - $10")
    print()
    print(f"  {'cohort':<22}  {'n':>5}  {'C1 pnl':>10}  {'C2 pnl':>10}  "
          f"{'total':>10}  {'$/tr':>7}")
    for label, mask in [
        ("All alive @ +5m",     alive_df["alive_at_5m"]),
        ("Eventual winners",    alive_df["is_winner"]),
        ("Eventual losers",     ~alive_df["is_winner"]),
    ]:
        sub = alive_df[mask]
        if not len(sub): continue
        c1 = sub["net_pnl"].sum()
        c2 = sub["c2_added_at_5m_pnl"].sum()
        total = c1 + c2
        print(f"  {label:<22}  {len(sub):>5,}  {c1:>+9,.0f}  "
              f"{c2:>+9,.0f}  {total:>+9,.0f}  "
              f"{total/len(sub):>+6.1f}")

    # Per-year double-up
    print(f"\n  Per year (all alive @ +5m):")
    print(f"  {'year':<5}  {'n':>5}  {'C1':>9}  {'C2':>9}  {'total':>10}  "
          f"{'$/tr':>7}")
    for yr in (2024, 2025, 2026):
        sub = alive_df[alive_df["year"] == yr]
        if not len(sub): continue
        c1 = sub["net_pnl"].sum()
        c2 = sub["c2_added_at_5m_pnl"].sum()
        total = c1 + c2
        print(f"  {yr:<5}  {len(sub):>5,}  {c1:>+8,.0f}  {c2:>+8,.0f}  "
              f"{total:>+9,.0f}  {total/len(sub):>+6.1f}")

    # Compare to "always 2c naive" on the same cohort
    print(f"\n  Compare to 2c naive (both at original entry) on same cohort:")
    naive_2c = 2 * alive_df["net_pnl"].sum()
    plus_at_5m = alive_df["net_pnl"].sum() + alive_df["c2_added_at_5m_pnl"].sum()
    print(f"    2c naive (both at entry):    ${naive_2c:>+,.0f} "
          f"(${naive_2c/len(alive_df):+.2f}/tr)")
    print(f"    1c entry + 1c added @ +5m:   ${plus_at_5m:>+,.0f} "
          f"(${plus_at_5m/len(alive_df):+.2f}/tr)")
    print(f"    Δ (delayed C2 vs naive 2c):  ${plus_at_5m - naive_2c:>+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
