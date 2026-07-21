"""V_A 2-bar delay test (corrected entry convention).

Entry convention (per user clarification):
  V_A's TRUE current entry = OPEN of next 1s bar at-or-after decision_ts
                             (= bar+1 close), NO 30s delay.

For each V_A HH/LL bar+1 confirmed entry:
  flip_close_ts  = decision_ts - 60s
  bar+1 close    = decision_ts
  V_A normal entry = OPEN of 1s bar at-or-after decision_ts
  2-bar delay entry = OPEN of 1s bar at-or-after (decision_ts + 120s)
                       (= bar 5 OPEN if bar 1 = flip bar)

Dip filter: in [flip_close_ts, new_entry_ts):
  long  V_A: skip if any 1s bar low  <= flip_bar_low
  short V_A: skip if any 1s bar high >= flip_bar_high

Exits:
  Regime exit = V_A's natural exit_ts (unchanged)
  V4 = candidate at +3m AND confirm at +4m elapsed FROM new entry

Baseline recomputed at corrected entry (NOT trades.parquet's fill_price)
to ensure apples-to-apples comparison.

Universe: option (a) — ALL V_A HH/LL confirmed entries (no excursion filter)
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
EPS = 1e-6
DELAY_S = 0     # 0-bar = enter at decision_ts (V_A's natural time)
                # Dip filter window = [flip_close_ts, decision_ts)
                # = bar+1's 60s of price action (observable at entry time)

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


def fill_open_at(t_ns, ts_idx, opens):
    i = np.searchsorted(ts_idx, t_ns, side="left")
    if i >= len(opens): return np.nan, None
    return float(opens[i]), int(ts_idx[i])


def find_dip(direction, flip_low, flip_high, start_ts, end_ts,
                ts_idx, highs, lows):
    i_lo = np.searchsorted(ts_idx, start_ts, side="left")
    i_hi = np.searchsorted(ts_idx, end_ts, side="left")
    if i_hi <= i_lo: return False
    if direction == 1:
        return bool((lows[i_lo:i_hi] <= flip_low + EPS).any())
    else:
        return bool((highs[i_lo:i_hi] >= flip_high - EPS).any())


def evaluate_v4(direction, atr, fill_px, entry_ts, exit_ts,
                  ts_idx, opens, highs, lows, closes):
    """V4: candidate at +3m (unr<-50 AND mfe<0.25); confirm at +4m
    (unr<0 AND mfe<0.35 AND xfast<0). Exit at OPEN of bar at +4m."""
    ts_3m = entry_ts + 180 * 1_000_000_000
    ts_4m = entry_ts + 240 * 1_000_000_000
    if ts_3m >= exit_ts or ts_4m >= exit_ts:
        return False, None
    j_entry = np.searchsorted(ts_idx, entry_ts, side="left")
    j_3m = np.searchsorted(ts_idx, ts_3m, side="left")
    if j_3m <= j_entry: return False, None
    seg_h = highs[j_entry:j_3m]
    seg_l = lows[j_entry:j_3m]
    seg_c = closes[j_3m - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        unr_pts = float(seg_c - fill_px)
    else:
        cur_mfe = float(fill_px - seg_l.min())
        unr_pts = float(fill_px - seg_c)
    if not (unr_pts * NQ_MULT < -50
              and cur_mfe / max(atr, 0.01) < 0.25):
        return False, None
    j_4m = np.searchsorted(ts_idx, ts_4m, side="left")
    if j_4m <= j_entry: return False, None
    seg_h4 = highs[j_entry:j_4m]
    seg_l4 = lows[j_entry:j_4m]
    seg_c4 = closes[j_4m - 1]
    if direction == 1:
        cur_mfe4 = float(seg_h4.max() - fill_px)
        unr_pts4 = float(seg_c4 - fill_px)
    else:
        cur_mfe4 = float(fill_px - seg_l4.min())
        unr_pts4 = float(fill_px - seg_c4)
    win_start = ts_4m - 150 * 1_000_000_000
    i_xf = np.searchsorted(ts_idx, win_start, side="left")
    if j_4m <= i_xf: return False, None
    anc = float(opens[i_xf])
    cn = float(closes[j_4m - 1])
    xfast_net = (cn - anc) if direction == 1 else (anc - cn)
    if not (unr_pts4 * NQ_MULT < 0
              and cur_mfe4 / max(atr, 0.01) < 0.35
              and xfast_net < 0):
        return False, None
    if j_4m >= len(opens): return False, None
    return True, float(opens[j_4m])


def compute_pnl(direction, fill_px, exit_px):
    if pd.isna(exit_px): return np.nan
    pts = (exit_px - fill_px) if direction == 1 else (fill_px - exit_px)
    return pts * NQ_MULT - 2 * COMMISSION


def add_drawdown(df, col):
    df = df.sort_values("entry_ts_baseline").copy()
    df["cum"] = df[col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, col):
    if not len(df) or col not in df.columns: return {}
    n = len(df)
    wins = (df[col] > 0).sum()
    net = df[col].sum()
    max_dd = add_drawdown(df, col)["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts_baseline"], unit="ns",
                                          utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[col].sum()
    return {"n": n, "wr_pct": wins/n*100, "net_pnl": net,
            "per_trade": net/n, "max_dd": max_dd,
            "pos_months": (monthly > 0).sum(),
            "total_months": len(monthly)}


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A 2-BAR DELAY (decision_ts+120s) + flip-low dip filter + V4")
    print("Baseline entry: OPEN at decision_ts (no 30s delay)")
    print("Universe: ALL V_A HH/LL confirmed entries (option a)")
    print("=" * 78)

    rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- year {yr} ---", flush=True)
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        trades = pd.read_parquet(base / "trades.parquet")
        snaps = pd.read_parquet(base / "snapshots.parquet")
        b1 = snaps[snaps["kind"] == "bar1_check"][[
            "event_id", "flip_bar_h", "flip_bar_l"]]
        trades = trades.merge(b1, left_on="decision_event_id",
                                  right_on="event_id", how="left")

        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        n_total = len(trades)
        n_skip_dip = 0
        n_skip_overrun = 0
        for _, tr in trades.iterrows():
            decision_ts = int(tr["decision_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            orig_exit_px = float(tr["exit_price"])
            flip_low = float(tr["flip_bar_l"])
            flip_high = float(tr["flip_bar_h"])
            flip_close_ts = decision_ts - 60 * 1_000_000_000

            # ---- BASELINE: V_A entry at OPEN of bar at decision_ts ----
            base_fill, base_entry_ts = fill_open_at(
                decision_ts, ts_idx, opens)
            if pd.isna(base_fill): continue
            baseline_pnl = compute_pnl(direction, base_fill, orig_exit_px)

            # V_A + V4 (baseline entry)
            v4_b_fired, v4_b_fill = evaluate_v4(
                direction, atr, base_fill, base_entry_ts, exit_ts,
                ts_idx, opens, highs, lows, closes)
            v4_b_pnl = (compute_pnl(direction, base_fill, v4_b_fill)
                          if v4_b_fired else baseline_pnl)

            row = {
                "year": yr, "decision_ts": decision_ts,
                "entry_ts_baseline": base_entry_ts,
                "exit_ts": exit_ts, "direction": direction,
                "atr": atr, "base_fill": base_fill,
                "exit_px": orig_exit_px,
                "baseline_pnl": baseline_pnl,
                "va_v4_pnl": v4_b_pnl,
                "va_v4_fired": v4_b_fired,
            }

            # ---- 2-BAR DELAY ----
            new_entry_target = decision_ts + DELAY_S * 1_000_000_000
            if new_entry_target >= exit_ts:
                n_skip_overrun += 1
                row.update({
                    "delayed_status": "overrun",
                    "delayed_pnl": baseline_pnl,    # placeholder = baseline
                    "delayed_v4_pnl": v4_b_pnl,
                    "delayed_taken": False,
                })
                rows.append(row); continue

            # Dip filter: [flip_close_ts, new_entry_target)
            dipped = find_dip(direction, flip_low, flip_high,
                                  flip_close_ts, new_entry_target,
                                  ts_idx, highs, lows)
            if dipped:
                n_skip_dip += 1
                row.update({
                    "delayed_status": "dipped",
                    "delayed_pnl": baseline_pnl,
                    "delayed_v4_pnl": v4_b_pnl,
                    "delayed_taken": False,
                })
                rows.append(row); continue

            # Take the trade — entry at OPEN of bar at new_entry_target
            new_fill, new_entry_ts = fill_open_at(
                new_entry_target, ts_idx, opens)
            if pd.isna(new_fill):
                row.update({
                    "delayed_status": "no_bar",
                    "delayed_pnl": baseline_pnl,
                    "delayed_v4_pnl": v4_b_pnl,
                    "delayed_taken": False,
                })
                rows.append(row); continue

            new_baseline = compute_pnl(direction, new_fill, orig_exit_px)
            v4_d_fired, v4_d_fill = evaluate_v4(
                direction, atr, new_fill, new_entry_ts, exit_ts,
                ts_idx, opens, highs, lows, closes)
            v4_d_pnl = (compute_pnl(direction, new_fill, v4_d_fill)
                          if v4_d_fired else new_baseline)

            row.update({
                "delayed_status": "taken",
                "delayed_taken": True,
                "delayed_entry_ts": new_entry_ts,
                "delayed_fill": new_fill,
                "delayed_pnl": new_baseline,
                "delayed_v4_pnl": v4_d_pnl,
                "delayed_v4_fired": v4_d_fired,
            })
            rows.append(row)

        n_taken = sum(1 for r in rows if r["year"] == yr
                       and r.get("delayed_taken"))
        print(f"  V_A entries: {n_total:,}")
        print(f"  delayed taken: {n_taken:,} "
              f"({100*n_taken/n_total:.1f}%)")
        print(f"  skipped: {n_skip_dip:,} dip "
              f"+ {n_skip_overrun:,} overrun")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "delayed_entry_2bar.parquet")

    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE")
    print(f"{'='*78}")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        if not len(sub): continue
        taken = sub[sub["delayed_taken"]]
        print(f"\n--- {yr} ---")
        # baseline (no V4)
        m = yearly_metrics(sub, "baseline_pnl")
        print(f"  {'V_A baseline':<18} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}")
        # V_A + V4
        m = yearly_metrics(sub, "va_v4_pnl")
        n_v4_orig = int(sub["va_v4_fired"].sum())
        print(f"  {'V_A + V4':<18} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}  "
              f"(V4 fired {n_v4_orig})")
        # Delayed + V4 (only taken)
        if len(taken):
            taken2 = taken.copy()
            taken2["entry_ts_baseline"] = (
                taken2.get("delayed_entry_ts",
                            taken2["entry_ts_baseline"]))
            m = yearly_metrics(taken2, "delayed_v4_pnl")
            n_v4_d = int(taken["delayed_v4_fired"].sum())
            same_va_v4 = sub[sub["delayed_taken"]]["va_v4_pnl"].sum()
            print(f"  {'Delayed + V4':<18} n={int(m['n']):>5,}  "
                  f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
                  f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}  "
                  f"(V4 fired {n_v4_d})")
            print(f"  {'  same-cohort V_A+V4':<18}    "
                  f"net ${same_va_v4:+,.0f}   "
                  f"Δ ${m['net_pnl']-same_va_v4:+,.0f}")

    # ALL YEARS
    print(f"\n--- ALL YEARS ---")
    n_total = len(df)
    n_taken_all = int(df["delayed_taken"].sum())
    n_skip_dip_all = int((df["delayed_status"] == "dipped").sum())
    n_skip_overrun_all = int((df["delayed_status"] == "overrun").sum())
    print(f"  V_A entries:    {n_total:,}")
    print(f"  delayed taken:  {n_taken_all:,} "
          f"({100*n_taken_all/n_total:.1f}%)")
    print(f"  skipped (dip):  {n_skip_dip_all:,} "
          f"({100*n_skip_dip_all/n_total:.1f}%)")
    print(f"  skipped (overrun): {n_skip_overrun_all:,} "
          f"({100*n_skip_overrun_all/n_total:.1f}%)")

    print()
    for label, col, sub_df in [
        ("V_A baseline",  "baseline_pnl",   df),
        ("V_A + V4",      "va_v4_pnl",      df),
        ("Delayed + V4",  "delayed_v4_pnl", df[df["delayed_taken"]].copy()),
    ]:
        if not len(sub_df): continue
        if label == "Delayed + V4":
            sub_df["entry_ts_baseline"] = sub_df["delayed_entry_ts"]
        m = yearly_metrics(sub_df, col)
        print(f"  {label:<18} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}")

    # Same-cohort comparison
    taken_all = df[df["delayed_taken"]]
    delayed_net = taken_all["delayed_v4_pnl"].sum()
    same_va_v4 = taken_all["va_v4_pnl"].sum()
    same_baseline = taken_all["baseline_pnl"].sum()
    print(f"\n  Same {len(taken_all):,}-trade cohort:")
    print(f"    V_A baseline: ${same_baseline:+,.0f} "
          f"(${same_baseline/len(taken_all):+.2f}/tr)")
    print(f"    V_A + V4:     ${same_va_v4:+,.0f} "
          f"(${same_va_v4/len(taken_all):+.2f}/tr)")
    print(f"    Delayed + V4: ${delayed_net:+,.0f} "
          f"(${delayed_net/len(taken_all):+.2f}/tr)")
    print(f"    Δ vs V_A+V4 (same cohort): "
          f"${delayed_net - same_va_v4:+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
