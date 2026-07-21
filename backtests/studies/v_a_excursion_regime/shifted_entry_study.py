"""Shifted-entry study — two tests:

T0 baseline (current): HH/LL-confirmed, fill at flip+90s (bar+1 close + 30s delay)
T1: HH/LL-confirmed, fill at flip+60s (OPEN of 1s bar at bar+1 close — no delay)
T2: Every regime flip (no HH/LL), filter at flip bar, fill at flip+0
    (OPEN of 1s bar at flip bar close — no delay)

For all three, apply V4 exit overlay at wall-clock-equivalent times:
  T0/T1 V4: candidate at +3m elapsed, confirm at +4m
  T2 V4:    candidate at +4m elapsed, confirm at +5m  (= same wall-clock)

Filter (`total_excursion_slow = mid`):
  T0: evaluated at decision_ts (= bar+1 close, current behavior)
  T1: evaluated at flip bar close (= decision_ts - 60s)
  T2: evaluated at flip bar close

For T2 we use snapshots (kind=='regime_flip') as the candidate pool — this
is a LARGER population than HH/LL-confirmed (e.g. 2025: 7,353 flips vs
3,313 HH/LL-confirmed). Exit = next opposing flip's bar close.
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import pytz
CT = pytz.timezone("America/Chicago")

NQ_MULT = 20.0
COMMISSION = 5.0
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75
RTH_START_MIN = 8 * 60 + 30   # 8:30 CT
RTH_END_MIN = 15 * 60          # 15:00 CT

OUT = Path("studies/v_a_excursion_regime/results_v0")
OUT.mkdir(parents=True, exist_ok=True)


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


def is_rth(ts_ns):
    ts = pd.Timestamp(ts_ns, unit="ns", tz="UTC").astimezone(CT)
    if ts.weekday() >= 5: return False
    m = ts.hour * 60 + ts.minute
    return RTH_START_MIN <= m < RTH_END_MIN


def compute_excursion_slow(decision_ts_ns, direction, ts_index_ns,
                              opens, highs, lows, closes):
    """Compute total_excursion_slow over [decision_ts - 30min, decision_ts).
    Returns excursion in points (sum of mfe + mae direction-aware)."""
    win_start = decision_ts_ns - 30 * 60 * 1_000_000_000
    i_lo = np.searchsorted(ts_index_ns, win_start, side="left")
    i_hi = np.searchsorted(ts_index_ns, decision_ts_ns, side="left")
    if i_hi - i_lo < 60:
        return np.nan
    anchor_open = float(opens[i_lo])
    hi = float(highs[i_lo:i_hi].max())
    lo = float(lows[i_lo:i_hi].min())
    if direction == 1:
        mfe = hi - anchor_open
        mae = anchor_open - lo
    else:
        mfe = anchor_open - lo
        mae = hi - anchor_open
    return mfe + mae


def trade_state_at(t_ns, direction, atr, ts_index_ns,
                      opens, highs, lows, closes, entry_ts, fill_px):
    """Trade-state + xfast_net_move at t_ns, causal."""
    j_lo = np.searchsorted(ts_index_ns, entry_ts, side="left")
    j_hi = np.searchsorted(ts_index_ns, t_ns, side="left")
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
    out = {
        "current_mfe_atr": cur_mfe / max(atr, 0.01),
        "current_mae_atr": cur_mae / max(atr, 0.01),
        "unrealized_pnl": unr_pts * NQ_MULT,
        "fill_at_next_bar": float(opens[j_hi]) if j_hi < len(opens) else np.nan,
    }
    # xfast_net_move (2.5min, direction-aware, strictly before t_ns)
    win_start = t_ns - 5 * 30 * 1_000_000_000
    i_lo = np.searchsorted(ts_index_ns, win_start, side="left")
    if j_hi - i_lo < 30:
        out["xfast_net_move"] = np.nan
    else:
        anchor_open = float(opens[i_lo])
        close_now = float(closes[j_hi - 1])
        if direction == 1:
            out["xfast_net_move"] = close_now - anchor_open
        else:
            out["xfast_net_move"] = anchor_open - close_now
    return out


def fill_open_at(ts_ns, ts_index_ns, opens):
    """OPEN of the 1s bar at-or-after ts_ns. Returns nan if past end."""
    i = np.searchsorted(ts_index_ns, ts_ns, side="left")
    if i >= len(opens): return np.nan
    return float(opens[i])


def get_atr_estimate(decision_ts, direction, ts_index_ns, highs, lows, closes,
                      n=14):
    """ATR(14) estimate over the prior n minutes — uses 1s bars to derive a
    crude proxy. We need atr_at_signal for V4 overlay's mfe_atr calc.
    For T2 (no-HH/LL flips), the snapshots may not have atr_at_signal in
    the right form. Fallback: compute simple high-low range over prior 1m
    as proxy."""
    # Use last 14 1m windows ending at decision_ts
    out = []
    for k in range(1, n + 1):
        end_ns = decision_ts - (k - 1) * 60 * 1_000_000_000
        start_ns = end_ns - 60 * 1_000_000_000
        i_lo = np.searchsorted(ts_index_ns, start_ns, side="left")
        i_hi = np.searchsorted(ts_index_ns, end_ns, side="left")
        if i_hi - i_lo < 30: continue
        h = float(highs[i_lo:i_hi].max())
        l = float(lows[i_lo:i_hi].min())
        out.append(h - l)
    if not out: return 5.0
    return float(np.mean(out))


def apply_v4_overlay(direction, entry_ts, exit_ts, fill_px, atr, baseline_pnl,
                       ts_index_ns, opens, highs, lows, closes,
                       cand_elapsed_s, conf_elapsed_s):
    """V4 logic:
      Candidate at cand_elapsed (e.g. +3m or +4m): unr<-50 AND mfe<0.25
      Confirm at conf_elapsed: still unr<0 AND mfe<0.35 AND xfast<0
      → exit at OPEN of 1s bar at conf checkpoint
    """
    cand_ts = entry_ts + cand_elapsed_s * 1_000_000_000
    conf_ts = entry_ts + conf_elapsed_s * 1_000_000_000
    if cand_ts >= exit_ts or conf_ts >= exit_ts:
        return baseline_pnl, False
    s_cand = trade_state_at(cand_ts, direction, atr, ts_index_ns,
                                opens, highs, lows, closes, entry_ts, fill_px)
    if s_cand is None: return baseline_pnl, False
    if not (s_cand["unrealized_pnl"] < -50
              and s_cand["current_mfe_atr"] < 0.25):
        return baseline_pnl, False
    s_conf = trade_state_at(conf_ts, direction, atr, ts_index_ns,
                                opens, highs, lows, closes, entry_ts, fill_px)
    if s_conf is None: return baseline_pnl, False
    if not (s_conf["unrealized_pnl"] < 0
              and s_conf["current_mfe_atr"] < 0.35
              and not pd.isna(s_conf.get("xfast_net_move", np.nan))
              and s_conf["xfast_net_move"] < 0):
        return baseline_pnl, False
    alt_px = s_conf["fill_at_next_bar"]
    if pd.isna(alt_px): return baseline_pnl, False
    if direction == 1:
        pts = alt_px - fill_px
    else:
        pts = fill_px - alt_px
    return pts * NQ_MULT - 2 * COMMISSION, True


def run_test_T1(year, lo_cut, hi_cut):
    """HH/LL-confirmed cohort, fill at flip+60s (no 30s delay), filter at
    flip bar close."""
    print(f"\n=== T1 (HH/LL no-delay) year {year} ===", flush=True)
    base = Path(f"collectors/collector_v2/results/v_a_v0_{year}")
    trades = pd.read_parquet(base / "trades.parquet")
    bars = load_year_bars(year)
    ts_idx = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)
    print(f"  loaded {len(trades):,} trades + {len(bars):,} 1s bars",
          flush=True)

    rows = []
    for _, tr in trades.iterrows():
        decision_ts = int(tr["decision_ts"])         # bar+1 close
        flip_close_ts = decision_ts - 60 * 1_000_000_000  # flip bar close
        direction = int(tr["direction"])
        atr = float(tr["atr_at_signal"])
        old_exit_ts = int(tr["exit_ts"])
        old_exit_px = float(tr["exit_price"])

        # Filter: total_excursion_slow at FLIP bar close
        exc = compute_excursion_slow(flip_close_ts, direction,
                                          ts_idx, opens, highs, lows, closes)
        if pd.isna(exc) or not (SLOW_LO_CUT <= exc < SLOW_HI_CUT):
            continue

        # NEW entry: open of 1s bar at decision_ts (= bar+1 close)
        new_entry_ts = decision_ts
        new_fill = fill_open_at(new_entry_ts, ts_idx, opens)
        if pd.isna(new_fill): continue

        # Exit unchanged
        if direction == 1:
            new_pnl_pts = old_exit_px - new_fill
        else:
            new_pnl_pts = new_fill - old_exit_px
        new_baseline = new_pnl_pts * NQ_MULT - 2 * COMMISSION

        # V4 overlay at +3m / +4m elapsed
        v4_pnl, v4_fired = apply_v4_overlay(
            direction, new_entry_ts, old_exit_ts, new_fill, atr,
            new_baseline, ts_idx, opens, highs, lows, closes, 180, 240)

        rows.append({"year": year, "direction": direction,
                     "entry_ts": new_entry_ts, "fill_price": new_fill,
                     "exit_ts": old_exit_ts, "exit_price": old_exit_px,
                     "baseline_pnl": new_baseline,
                     "v4_pnl": v4_pnl, "v4_fired": v4_fired})
    print(f"  T1 cohort: {len(rows):,} trades", flush=True)
    return pd.DataFrame(rows)


def run_test_T2(year, lo_cut, hi_cut):
    """Every regime flip (no HH/LL), filter at flip bar close, fill at
    flip bar close (open of next 1s bar). Exit at next opposing flip."""
    print(f"\n=== T2 (every flip, no HH/LL) year {year} ===", flush=True)
    base = Path(f"collectors/collector_v2/results/v_a_v0_{year}")
    snaps = pd.read_parquet(base / "snapshots.parquet")
    flips = snaps[snaps["kind"] == "regime_flip"].sort_values(
        "decision_ts").reset_index(drop=True)
    print(f"  total regime flips: {len(flips):,}", flush=True)

    bars = load_year_bars(year)
    ts_idx = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)

    flip_ts = flips["decision_ts"].values.astype(np.int64)
    flip_dir = flips["direction"].values.astype(np.int64)

    rows = []
    rth_skipped = 0
    filter_skipped = 0
    for i in range(len(flips)):
        f_ts = int(flip_ts[i])
        f_dir = int(flip_dir[i])

        # RTH only
        if not is_rth(f_ts):
            rth_skipped += 1
            continue

        # Filter at flip bar close
        exc = compute_excursion_slow(f_ts, f_dir, ts_idx, opens,
                                          highs, lows, closes)
        if pd.isna(exc) or not (SLOW_LO_CUT <= exc < SLOW_HI_CUT):
            filter_skipped += 1
            continue

        # Find next opposing flip
        nxt_idx = i + 1
        while nxt_idx < len(flips) and flip_dir[nxt_idx] == f_dir:
            nxt_idx += 1
        if nxt_idx >= len(flips):
            continue
        exit_ts = int(flip_ts[nxt_idx])

        # Fill at OPEN of 1s bar at flip bar close
        fill = fill_open_at(f_ts, ts_idx, opens)
        if pd.isna(fill): continue
        # Exit at OPEN of 1s bar at opposing flip's bar close
        exit_px = fill_open_at(exit_ts, ts_idx, opens)
        if pd.isna(exit_px): continue

        # Crude ATR estimate for V4 overlay
        atr = get_atr_estimate(f_ts, f_dir, ts_idx, highs, lows, closes)

        if f_dir == 1:
            pnl_pts = exit_px - fill
        else:
            pnl_pts = fill - exit_px
        baseline = pnl_pts * NQ_MULT - 2 * COMMISSION

        # V4 overlay at +4m / +5m elapsed (wall-clock equivalent)
        v4_pnl, v4_fired = apply_v4_overlay(
            f_dir, f_ts, exit_ts, fill, atr, baseline,
            ts_idx, opens, highs, lows, closes, 240, 300)

        rows.append({"year": year, "direction": f_dir,
                     "entry_ts": f_ts, "fill_price": fill,
                     "exit_ts": exit_ts, "exit_price": exit_px,
                     "atr_est": atr, "baseline_pnl": baseline,
                     "v4_pnl": v4_pnl, "v4_fired": v4_fired,
                     "excursion_slow": exc})
    print(f"  T2: skipped {rth_skipped:,} non-RTH, "
          f"{filter_skipped:,} filter-rejected → {len(rows):,} trades",
          flush=True)
    return pd.DataFrame(rows)


def add_drawdown(df, col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, col):
    if not len(df): return {}
    n = len(df)
    wins = (df[col] > 0).sum()
    net = df[col].sum()
    df_dd = add_drawdown(df, col)
    max_dd = df_dd["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[col].sum()
    return {"n": n, "wr_pct": wins / n * 100, "net_pnl": net,
            "per_trade": net / n, "max_dd": max_dd,
            "pos_months": (monthly > 0).sum(),
            "total_months": len(monthly)}


def main():
    t0 = time.time()
    print("=" * 78)
    print("SHIFTED-ENTRY STUDY: HH/LL no-delay (T1) vs every-flip (T2)")
    print("=" * 78)

    # Load existing T0 baseline (HH/LL with 30s delay) from prior results
    print("\n--- Loading T0 baseline (HH/LL + 30s delay, current default) ---")
    t0_dfs = {}
    for yr in (2024, 2025, 2026):
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        d = pd.read_parquet(base / "trades.parquet")
        # Excursion-mid filter at decision_ts (= bar+1 close)
        # Reuse from with_excursion file
        wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
        # Match on decision_event_id
        m = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                  & (wex["total_excursion_slow"] < SLOW_HI_CUT)]
        t0_dfs[yr] = m[["entry_ts", "net_pnl"]].rename(
            columns={"net_pnl": "baseline_pnl"})
        print(f"  {yr}: {len(t0_dfs[yr]):,} T0 trades", flush=True)

    # Run T1 and T2
    t1_dfs = {}
    t2_dfs = {}
    for yr in (2024, 2025, 2026):
        t1_dfs[yr] = run_test_T1(yr, SLOW_LO_CUT, SLOW_HI_CUT)
        t1_dfs[yr].to_parquet(OUT / f"shifted_T1_{yr}.parquet")
        t2_dfs[yr] = run_test_T2(yr, SLOW_LO_CUT, SLOW_HI_CUT)
        t2_dfs[yr].to_parquet(OUT / f"shifted_T2_{yr}.parquet")

    # Per-year reporting
    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE COMPARISON")
    print(f"{'='*78}")
    for yr in (2024, 2025, 2026):
        print(f"\n--- {yr} ---")
        print(f"  {'variant':<26} {'n':>5} {'WR%':>5} {'net':>9} "
              f"{'$/tr':>7} {'maxDD':>9} {'posM':>5}")

        # T0 baseline
        m = yearly_metrics(t0_dfs[yr], "baseline_pnl")
        print(f"  {'T0 HH/LL +30s baseline':<26} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")

        # T1 baseline (no V4)
        m = yearly_metrics(t1_dfs[yr], "baseline_pnl")
        print(f"  {'T1 HH/LL no-delay':<26} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")
        # T1 + V4
        m = yearly_metrics(t1_dfs[yr], "v4_pnl")
        n_fired = t1_dfs[yr]["v4_fired"].sum()
        print(f"  {'T1 + V4 (+3m/+4m)':<26} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}  "
              f"(V4 fired {n_fired:,})")

        # T2 baseline (no V4)
        m = yearly_metrics(t2_dfs[yr], "baseline_pnl")
        print(f"  {'T2 every-flip baseline':<26} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")
        # T2 + V4
        m = yearly_metrics(t2_dfs[yr], "v4_pnl")
        n_fired = t2_dfs[yr]["v4_fired"].sum()
        print(f"  {'T2 + V4 (+4m/+5m)':<26} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}  "
              f"(V4 fired {n_fired:,})")

    # ALL years
    print(f"\n--- ALL YEARS ---")
    for label, dfs, col in [
        ("T0 HH/LL +30s baseline", t0_dfs, "baseline_pnl"),
        ("T1 HH/LL no-delay base", t1_dfs, "baseline_pnl"),
        ("T1 + V4",                t1_dfs, "v4_pnl"),
        ("T2 every-flip base",     t2_dfs, "baseline_pnl"),
        ("T2 + V4",                t2_dfs, "v4_pnl"),
    ]:
        full = pd.concat(dfs.values(), ignore_index=True)
        m = yearly_metrics(full, col)
        print(f"  {label:<26} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr {m['per_trade']:+.1f}  maxDD ${m['max_dd']:+,.0f}  "
              f"posM {int(m['pos_months'])}/{int(m['total_months'])}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
