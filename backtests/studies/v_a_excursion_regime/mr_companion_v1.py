"""Mean-reversion companion v1 — fade failed V_A continuations.

Universe: ALL V_A HH/LL bar+1 confirmed entries (no excursion filter)
across 2024 + 2025 + 2026.

REPLACE semantics: when MR fires at +60s, V_A is closed, MR opens
opposite direction.

MR fire conditions, evaluated at exactly +60s post V_A entry, using
ONLY data with ts < (entry + 60s):
  1) trend_MFE_atr < 0.25
  2) trend_MAE_atr > 0.5
  3) xfast_net_move OPPOSITE to V_A direction (i.e., negative when
     computed in V_A's direction)
  4) close_loc_in_range < 0.4
     (where close_loc = 1.0 means price at favorable extreme of
      [low, high] window from V_A perspective)

If all 4 met → MR enters opposite direction at OPEN of next 1s bar
at-or-after MR_fire_ts (= entry_ts + 60s).

MR exits (whichever fires first):
  - PT: ±0.75 ATR from MR fill (long MR: bar high >= MR_fill+0.75*ATR;
        short MR: bar low <= MR_fill-0.75*ATR). Fill exact at PT level.
  - SL: ∓0.75 ATR from MR fill. Fill exact at SL level.
  - Time stop: 4 minutes after MR fill. Fill at OPEN of bar at +4m.
  - Same-bar PT+SL conflict: SL wins (conservative, per CLAUDE.md).

ATR = atr_at_signal (V_A's stored ATR per trade).

Reports per year:
  - Fire rate (% of V_A entries that produce MR)
  - Exit mix (PT% / SL% / time stop% / regime-overrun%)
  - Avg net PnL / trade, total net, $/tr
  - Max DD, positive months, median monthly PnL
  - MR_MFE achieved distribution (p10/p25/p50/p75/p90)
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
PT_ATR = 0.75
SL_ATR = 0.75
TIME_STOP_S = 240
MR_FIRE_OFFSET_S = 60
EPS = 1e-6

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


def features_at_60s(direction, atr, fill_px, entry_ts, exit_ts,
                       ts_idx, opens, highs, lows, closes):
    """Compute V_A trade-state at +60s. All bars strictly before +60s.
    Returns dict with the 4 fire-condition values + fill_at_next_bar.
    Returns None if checkpoint past V_A exit OR insufficient bars.
    """
    cp_ts = entry_ts + MR_FIRE_OFFSET_S * 1_000_000_000
    if cp_ts >= exit_ts:
        return None
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
    if j_hi <= j_lo:
        return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
    # close_loc_in_range: 1 = at favorable extreme, 0 = at adverse extreme
    rng = float(seg_h.max() - seg_l.min())
    if rng < EPS:
        close_loc = 0.5
    else:
        if direction == 1:
            close_loc = (float(seg_c) - float(seg_l.min())) / rng
        else:
            close_loc = (float(seg_h.max()) - float(seg_c)) / rng

    # xfast_net_move: 2.5min window ending at cp_ts, V_A direction
    win_start = cp_ts - 150 * 1_000_000_000
    i_xf_lo = np.searchsorted(ts_idx, win_start, side="left")
    if j_hi - i_xf_lo < 30:
        xfast_net = np.nan
    else:
        anc = float(opens[i_xf_lo])
        cn = float(closes[j_hi - 1])
        xfast_net = (cn - anc) if direction == 1 else (anc - cn)

    # MR fill price: OPEN of bar at-or-after cp_ts
    fill_at_next_bar = (
        float(opens[j_hi]) if j_hi < len(opens) else np.nan)

    return {
        "trend_mfe_atr": cur_mfe / max(atr, 0.01),
        "trend_mae_atr": cur_mae / max(atr, 0.01),
        "close_loc_in_range": close_loc,
        "xfast_net_move": xfast_net,
        "fill_at_next_bar": fill_at_next_bar,
        "cp_ts": cp_ts,
    }


def fires_mr(features):
    """Return True if all 4 conditions met."""
    if features is None: return False
    if pd.isna(features.get("xfast_net_move", np.nan)): return False
    return (
        features["trend_mfe_atr"] < 0.25
        and features["trend_mae_atr"] > 0.5
        and features["xfast_net_move"] < 0          # opposite to V_A dir
        and features["close_loc_in_range"] < 0.4
    )


def walk_mr_exit(mr_dir, mr_fill_px, mr_fill_ts, atr,
                    ts_idx, opens, highs, lows, year_end_ts):
    """From MR fill, walk 1s bars looking for PT, SL, or time stop.
    Returns (exit_type, exit_ts, exit_px, mfe_achieved_atr, mae_achieved_atr).
    """
    pt_distance = PT_ATR * atr
    sl_distance = SL_ATR * atr
    if mr_dir == 1:
        pt_level = mr_fill_px + pt_distance
        sl_level = mr_fill_px - sl_distance
    else:
        pt_level = mr_fill_px - pt_distance
        sl_level = mr_fill_px + sl_distance

    time_stop_ts = mr_fill_ts + TIME_STOP_S * 1_000_000_000
    j_start = np.searchsorted(ts_idx, mr_fill_ts, side="left")
    j_time = np.searchsorted(ts_idx, time_stop_ts, side="left")
    j_end = min(j_time, len(ts_idx))
    if j_end <= j_start:
        return ("nodata", None, np.nan, np.nan, np.nan)

    # Track MFE/MAE achieved (for distribution reporting)
    seg_h = highs[j_start:j_end]
    seg_l = lows[j_start:j_end]
    if mr_dir == 1:
        running_mfe = float(seg_h.max() - mr_fill_px)
        running_mae = float(mr_fill_px - seg_l.min())
    else:
        running_mfe = float(mr_fill_px - seg_l.min())
        running_mae = float(seg_h.max() - mr_fill_px)

    # Find first bar with PT or SL hit; same-bar SL wins
    for k in range(j_start, j_end):
        bar_h = highs[k]; bar_l = lows[k]
        if mr_dir == 1:
            sl_hit = bar_l <= sl_level + EPS
            pt_hit = bar_h >= pt_level - EPS
        else:
            sl_hit = bar_h >= sl_level - EPS
            pt_hit = bar_l <= pt_level + EPS
        if sl_hit and pt_hit:
            # Same-bar conflict: SL wins (conservative)
            return ("SL", int(ts_idx[k]), float(sl_level),
                     running_mfe / max(atr, 0.01),
                     running_mae / max(atr, 0.01))
        if sl_hit:
            return ("SL", int(ts_idx[k]), float(sl_level),
                     running_mfe / max(atr, 0.01),
                     running_mae / max(atr, 0.01))
        if pt_hit:
            return ("PT", int(ts_idx[k]), float(pt_level),
                     running_mfe / max(atr, 0.01),
                     running_mae / max(atr, 0.01))

    # No PT or SL — time stop. Fill at OPEN of bar at +4m.
    if j_time >= len(opens):
        return ("nodata", None, np.nan, np.nan, np.nan)
    return ("TIME", int(ts_idx[j_time]), float(opens[j_time]),
             running_mfe / max(atr, 0.01),
             running_mae / max(atr, 0.01))


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
    if not len(df): return {}
    n = len(df)
    wins = (df[col] > 0).sum()
    net = df[col].sum()
    max_dd = add_drawdown(df, col)["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[col].sum()
    return {"n": n, "wr_pct": wins / n * 100, "net_pnl": net,
            "per_trade": net / n, "max_dd": max_dd,
            "pos_months": (monthly > 0).sum(),
            "total_months": len(monthly),
            "median_monthly_pnl": monthly.median()}


def main():
    t0 = time.time()
    print("=" * 78)
    print("MEAN-REVERSION COMPANION v1 — fade failed V_A continuations")
    print(f"  fire conditions: MFE<0.25 AND MAE>0.5 AND xfast<0 AND "
          f"close_loc<0.4")
    print(f"  exits: PT={PT_ATR} ATR / SL={SL_ATR} ATR / "
          f"time={TIME_STOP_S//60}m  (replace V_A)")
    print("=" * 78)

    all_va = []
    all_mr = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- year {yr} ---", flush=True)
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        trades = pd.read_parquet(base / "trades.parquet")
        print(f"  V_A entries: {len(trades):,}")

        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)
        year_end_ts = int(ts_idx[-1])

        n_fires = 0
        for _, tr in trades.iterrows():
            entry_ts = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])
            va_pnl = float(tr["net_pnl"])

            # Eval at +60s
            f60 = features_at_60s(
                direction, atr, fill_px, entry_ts, exit_ts,
                ts_idx, opens, highs, lows, closes)

            row_va = {
                "year": yr,
                "va_entry_ts": entry_ts, "va_exit_ts": exit_ts,
                "va_direction": direction, "atr": atr,
                "va_fill_price": fill_px, "va_net_pnl": va_pnl,
            }
            if f60 is not None:
                row_va.update({
                    "trend_mfe_atr_60s": f60["trend_mfe_atr"],
                    "trend_mae_atr_60s": f60["trend_mae_atr"],
                    "close_loc_60s": f60["close_loc_in_range"],
                    "xfast_net_60s": f60["xfast_net_move"],
                })
            mr_fired = fires_mr(f60)
            row_va["mr_fired"] = mr_fired

            if mr_fired and not pd.isna(f60["fill_at_next_bar"]):
                mr_dir = -direction
                mr_fill_px = float(f60["fill_at_next_bar"])
                mr_fill_ts = (
                    int(np.searchsorted(ts_idx, f60["cp_ts"], side="left"))
                )
                mr_fill_ts = int(ts_idx[mr_fill_ts]) if mr_fill_ts < len(
                    ts_idx) else None
                if mr_fill_ts is None:
                    row_va["mr_fired"] = False
                else:
                    exit_type, exit_ts_mr, exit_px_mr, mfe_atr, mae_atr = (
                        walk_mr_exit(
                            mr_dir, mr_fill_px, mr_fill_ts, atr,
                            ts_idx, opens, highs, lows, year_end_ts))
                    if exit_type == "nodata":
                        row_va["mr_fired"] = False
                    else:
                        mr_pnl = compute_pnl(mr_dir, mr_fill_px, exit_px_mr)
                        row_va.update({
                            "mr_dir": mr_dir,
                            "mr_fill_px": mr_fill_px,
                            "mr_fill_ts": mr_fill_ts,
                            "mr_exit_type": exit_type,
                            "mr_exit_ts": exit_ts_mr,
                            "mr_exit_px": exit_px_mr,
                            "mr_pnl": mr_pnl,
                            "mr_mfe_achieved_atr": mfe_atr,
                            "mr_mae_achieved_atr": mae_atr,
                            "va_pnl_at_mr_fire": (
                                # what V_A had earned at MR fire time
                                # (counted as realized loss/gain on close)
                                ((mr_fill_px - fill_px)
                                  if direction == 1
                                  else (fill_px - mr_fill_px))
                                * NQ_MULT - 2 * COMMISSION),
                        })
                        n_fires += 1
                        all_mr.append({**row_va,
                                        "entry_ts": mr_fill_ts})

            all_va.append(row_va)
        n_va = len(trades)
        print(f"  MR fires: {n_fires:,}  ({100*n_fires/n_va:.1f}% of V_A "
              f"entries)")

    va = pd.DataFrame(all_va)
    mr = pd.DataFrame(all_mr)
    va.to_parquet(OUT / "mr_v1_va_eval.parquet")
    mr.to_parquet(OUT / "mr_v1_trades.parquet")
    print(f"\n  wrote V_A eval ({len(va):,}) + MR trades "
          f"({len(mr):,}) parquets")

    # ============================================================
    # Per-year reports
    # ============================================================
    print(f"\n{'='*78}")
    print("PER-YEAR MR PERFORMANCE")
    print(f"{'='*78}")
    for yr in (2024, 2025, 2026):
        sub_mr = mr[mr["year"] == yr] if "year" in mr.columns else \
            pd.DataFrame()
        sub_va = va[va["year"] == yr]
        n_va_yr = len(sub_va)
        n_mr_yr = len(sub_mr)
        fire_rate = 100 * n_mr_yr / max(n_va_yr, 1)
        print(f"\n--- {yr}  V_A entries={n_va_yr:,}  "
              f"MR fires={n_mr_yr:,}  ({fire_rate:.1f}%) ---")
        if n_mr_yr == 0:
            print(f"  (no MR fires)"); continue

        # Exit type mix
        exit_mix = sub_mr["mr_exit_type"].value_counts().to_dict()
        print(f"  exit mix: " + "  ".join(
            f"{k}={v:,} ({100*v/n_mr_yr:.0f}%)"
            for k, v in exit_mix.items()))

        # PnL stats
        m = yearly_metrics(sub_mr, "mr_pnl")
        print(f"  WR: {m['wr_pct']:.1f}%   net ${m['net_pnl']:+,.0f}   "
              f"$/tr ${m['per_trade']:+.2f}   maxDD ${m['max_dd']:+,.0f}   "
              f"posM {int(m['pos_months'])}/{int(m['total_months'])}   "
              f"medMonthly ${m['median_monthly_pnl']:+,.0f}")

        # MFE distribution
        mfe = sub_mr["mr_mfe_achieved_atr"].dropna()
        if len(mfe):
            print(f"  MR_MFE achieved (ATR units): "
                  f"p10={mfe.quantile(0.1):.2f} "
                  f"p25={mfe.quantile(0.25):.2f} "
                  f"p50={mfe.quantile(0.5):.2f} "
                  f"p75={mfe.quantile(0.75):.2f} "
                  f"p90={mfe.quantile(0.9):.2f}")

        # MR vs V_A would-have-been on the same trades
        va_baseline_on_mr_set = sub_mr["va_net_pnl"].sum()
        net_replace = m["net_pnl"]
        # Net change vs holding V_A: replace V_A with MR
        delta_replace = net_replace - va_baseline_on_mr_set
        print(f"  V_A net on these {n_mr_yr} trades: "
              f"${va_baseline_on_mr_set:+,.0f}  "
              f"(MR replaces V_A: ${net_replace:+,.0f}, "
              f"Δ ${delta_replace:+,.0f})")

    # ============================================================
    # All-years roll-up
    # ============================================================
    print(f"\n{'='*78}")
    print("ALL YEARS")
    print(f"{'='*78}")
    n_va_all = len(va)
    n_mr_all = len(mr)
    fire_rate_all = 100 * n_mr_all / max(n_va_all, 1)
    print(f"  V_A entries: {n_va_all:,}   MR fires: {n_mr_all:,}   "
          f"({fire_rate_all:.1f}%)")
    if n_mr_all > 0:
        m = yearly_metrics(mr, "mr_pnl")
        exit_mix = mr["mr_exit_type"].value_counts().to_dict()
        print(f"  exit mix: " + "  ".join(
            f"{k}={v:,} ({100*v/n_mr_all:.0f}%)"
            for k, v in exit_mix.items()))
        print(f"  WR: {m['wr_pct']:.1f}%   net ${m['net_pnl']:+,.0f}   "
              f"$/tr ${m['per_trade']:+.2f}")
        print(f"  maxDD ${m['max_dd']:+,.0f}   "
              f"posMonths {int(m['pos_months'])}/{int(m['total_months'])}")

        mfe = mr["mr_mfe_achieved_atr"].dropna()
        print(f"  MR_MFE achieved (ATR units): "
              f"p10={mfe.quantile(0.1):.2f}  "
              f"p25={mfe.quantile(0.25):.2f}  "
              f"p50={mfe.quantile(0.5):.2f}  "
              f"p75={mfe.quantile(0.75):.2f}  "
              f"p90={mfe.quantile(0.9):.2f}")

        va_on_mr = mr["va_net_pnl"].sum()
        print(f"\n  V_A would-be net on these {n_mr_all} trades: "
              f"${va_on_mr:+,.0f}  ({va_on_mr/n_mr_all:+.2f}/tr)")
        print(f"  MR net replacing V_A:                    "
              f"${m['net_pnl']:+,.0f}  ({m['per_trade']:+.2f}/tr)")
        print(f"  Replacement Δ (MR − V_A on same trades): "
              f"${m['net_pnl'] - va_on_mr:+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
