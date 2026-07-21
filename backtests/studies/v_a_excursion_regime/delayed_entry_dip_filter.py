"""V_A delayed-entry test: wait until close of bar 4 (flip + 240s),
plus a "no flip-bar dip" filter. Apply V4 overlay (shifted to new
entry time).

For each V_A HH/LL bar+1 confirmed entry:
  1. flip_close_ts = decision_ts - 60s   (flip bar's close = bar+1 open)
  2. bar4_close_ts = flip_close_ts + 240s (= decision_ts + 180s)
  3. Walk 1s bars in [flip_close_ts, bar4_close_ts):
     - If LONG V_A and any bar.low <= flip_bar_low → SKIP trade
     - If SHORT V_A and any bar.high >= flip_bar_high → SKIP trade
  4. Else: new entry at OPEN of 1s bar at bar4_close_ts
  5. Exit unchanged (next opposing regime flip — V_A's natural exit)
  6. V4 overlay shifted to +3m / +4m elapsed from NEW entry

Compare three variants per year:
  baseline       — V_A original entry, regime exit
  V_A + V4       — V_A original entry, V4 overlay
  delayed + V4   — new delayed entry, V4 overlay (subset of trades)

Universe: ALL V_A HH/LL confirmed entries (no excursion filter).

Causality: every check uses bars with ts_event < cp_ts (strict).
Entry uses OPEN of bar at cp_ts (bar at-or-after).
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
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75

# Set False (option a) for ALL V_A HH/LL entries; True (option b) for
# production-like total_excursion_slow=mid filter
USE_EXCURSION_FILTER = False

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
    """Return True if a dip below flip_low (long) / above flip_high (short)
    occurs in [start_ts, end_ts)."""
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
    df = df.sort_values("entry_ts").copy()
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
    return {"n": n, "wr_pct": wins/n*100, "net_pnl": net,
            "per_trade": net/n, "max_dd": max_dd}


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A DELAYED ENTRY (bar 4 close) + flip-low dip filter + V4")
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
        if USE_EXCURSION_FILTER:
            wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
            wex_filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                             & (wex["total_excursion_slow"] < SLOW_HI_CUT)
                             ].copy()
            keep_idx = set(wex_filt["decision_event_id"].tolist())
            n_pre = len(trades)
            trades = trades[trades["decision_event_id"].isin(keep_idx)
                              ].copy()
            print(f"  filter total_excursion_slow=mid: "
                  f"{n_pre:,} → {len(trades):,}")
        else:
            print(f"  no excursion filter (option a) — "
                  f"all V_A entries: {len(trades):,}")

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
            entry_ts_orig = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            decision_ts = int(tr["decision_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            orig_fill = float(tr["fill_price"])
            orig_exit_px = float(tr["exit_price"])
            net_pnl_orig = float(tr["net_pnl"])
            flip_low = float(tr["flip_bar_l"])
            flip_high = float(tr["flip_bar_h"])

            row = {
                "year": yr, "decision_ts": decision_ts,
                "entry_ts_orig": entry_ts_orig,
                "exit_ts": exit_ts, "direction": direction,
                "atr": atr, "orig_fill": orig_fill,
                "orig_exit_px": orig_exit_px,
                "baseline_pnl": net_pnl_orig,
            }

            # V_A + V4 (original entry)
            v4_orig_fired, v4_orig_fill = evaluate_v4(
                direction, atr, orig_fill, entry_ts_orig, exit_ts,
                ts_idx, opens, highs, lows, closes)
            if v4_orig_fired:
                row["va_v4_pnl"] = compute_pnl(
                    direction, orig_fill, v4_orig_fill)
                row["va_v4_fired"] = True
            else:
                row["va_v4_pnl"] = net_pnl_orig
                row["va_v4_fired"] = False

            # Delayed entry + dip filter
            flip_close_ts = decision_ts - 60 * 1_000_000_000
            bar4_close_ts = flip_close_ts + 240 * 1_000_000_000

            # Don't enter if bar4_close >= original exit (would never trade)
            if bar4_close_ts >= exit_ts:
                n_skip_overrun += 1
                row["delayed_status"] = "overrun"
                row["delayed_pnl"] = 0.0
                row["delayed_v4_pnl"] = 0.0
                row["delayed_taken"] = False
                rows.append(row); continue

            # Dip filter: in [flip_close_ts, bar4_close_ts)
            dipped = find_dip(direction, flip_low, flip_high,
                                  flip_close_ts, bar4_close_ts,
                                  ts_idx, highs, lows)
            if dipped:
                n_skip_dip += 1
                row["delayed_status"] = "dipped"
                row["delayed_pnl"] = 0.0
                row["delayed_v4_pnl"] = 0.0
                row["delayed_taken"] = False
                rows.append(row); continue

            # Take the trade — entry at OPEN of bar at bar4_close_ts
            new_fill, new_entry_ts = fill_open_at(bar4_close_ts,
                                                       ts_idx, opens)
            if pd.isna(new_fill):
                row["delayed_status"] = "no_bar"
                row["delayed_pnl"] = 0.0
                row["delayed_v4_pnl"] = 0.0
                row["delayed_taken"] = False
                rows.append(row); continue

            # Baseline PnL with shifted entry, regime exit unchanged
            baseline_delayed = compute_pnl(
                direction, new_fill, orig_exit_px)

            # V4 overlay from new entry time
            v4d_fired, v4d_fill = evaluate_v4(
                direction, atr, new_fill, new_entry_ts, exit_ts,
                ts_idx, opens, highs, lows, closes)
            if v4d_fired:
                v4d_pnl = compute_pnl(direction, new_fill, v4d_fill)
            else:
                v4d_pnl = baseline_delayed

            row["delayed_status"] = "taken"
            row["delayed_taken"] = True
            row["delayed_entry_ts"] = new_entry_ts
            row["delayed_fill"] = new_fill
            row["delayed_pnl"] = baseline_delayed
            row["delayed_v4_pnl"] = v4d_pnl
            row["delayed_v4_fired"] = v4d_fired
            rows.append(row)

        n_taken = sum(1 for r in rows if r["year"] == yr
                       and r.get("delayed_taken"))
        print(f"  V_A entries: {n_total:,}")
        print(f"  delayed taken: {n_taken:,} "
              f"({100*n_taken/n_total:.1f}%)")
        print(f"  skipped: {n_skip_dip:,} dip "
              f"+ {n_skip_overrun:,} overrun "
              f"= {n_skip_dip+n_skip_overrun:,} "
              f"({100*(n_skip_dip+n_skip_overrun)/n_total:.1f}%)")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "delayed_entry_dip_filter.parquet")

    # ===== Per-year reports =====
    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE")
    print(f"{'='*78}")
    # Need entry_ts column for drawdown
    df["entry_ts"] = df["entry_ts_orig"]
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        if not len(sub): continue
        # For delayed: use only taken trades
        taken = sub[sub["delayed_taken"]]
        print(f"\n--- {yr} ---")
        # baseline (all V_A trades, original entry, regime exit)
        m = yearly_metrics(sub, "baseline_pnl")
        print(f"  {'V_A baseline':<20} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}")
        # V_A + V4 (all trades)
        m = yearly_metrics(sub, "va_v4_pnl")
        n_v4_orig = int(sub["va_v4_fired"].sum())
        print(f"  {'V_A + V4':<20} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}  "
              f"(V4 fired {n_v4_orig})")
        # Delayed + V4 (only taken trades)
        if len(taken):
            taken_for_dd = taken.copy()
            taken_for_dd["entry_ts"] = taken_for_dd.get(
                "delayed_entry_ts", taken_for_dd["entry_ts_orig"])
            m = yearly_metrics(taken_for_dd, "delayed_v4_pnl")
            n_v4_d = int(taken["delayed_v4_fired"].sum())
            # Δ vs V_A + V4 on same trade SET (apples-to-apples on the
            # filter-passed cohort)
            same_set_va_v4 = sub[sub["delayed_taken"]]["va_v4_pnl"].sum()
            print(f"  {'Delayed + V4':<20} n={int(m['n']):>5,}  "
                  f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
                  f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}  "
                  f"(V4 fired {n_v4_d})")
            print(f"  {'  on same n=':<20}    V_A+V4 net ${same_set_va_v4:+,.0f}"
                  f"   Δ ${m['net_pnl'] - same_set_va_v4:+,.0f}")

    # ===== ALL YEARS =====
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
        ("Delayed + V4",  "delayed_v4_pnl", df[df["delayed_taken"]]),
    ]:
        if not len(sub_df): continue
        m = yearly_metrics(sub_df, col)
        print(f"  {label:<18} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr ${m['per_trade']:+.2f}  maxDD ${m['max_dd']:+,.0f}")

    # Δ on same-cohort comparison
    taken = df[df["delayed_taken"]]
    delayed_net = taken["delayed_v4_pnl"].sum()
    same_va_v4 = taken["va_v4_pnl"].sum()
    same_baseline = taken["baseline_pnl"].sum()
    print(f"\n  Same {len(taken):,}-trade cohort comparison:")
    print(f"    V_A baseline:  ${same_baseline:+,.0f}  "
          f"(${same_baseline/len(taken):+.2f}/tr)")
    print(f"    V_A + V4:      ${same_va_v4:+,.0f}  "
          f"(${same_va_v4/len(taken):+.2f}/tr)")
    print(f"    Delayed + V4:  ${delayed_net:+,.0f}  "
          f"(${delayed_net/len(taken):+.2f}/tr)")
    print(f"    Δ Delayed-V4 vs V_A+V4: "
          f"${delayed_net - same_va_v4:+,.0f}")
    print(f"    Δ Delayed-V4 vs V_A baseline: "
          f"${delayed_net - same_baseline:+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
