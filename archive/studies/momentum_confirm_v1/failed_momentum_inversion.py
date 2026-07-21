"""Failed momentum confirmation inversion — quick mechanical test.

Setup:
  - 1m regime flip detected
  - HH/LL confirmation bar (V_A: bar+1 1m; V_B: first 30s) makes
    new HH/LL in regime direction
  - BUT confirmation bar fails momentum:
      bull: confirm bar close <= open
      bear: confirm bar close >= open
  - Trade AGAINST the original regime:
      bull failed → SHORT
      bear failed → LONG

Exit: hold until the SECOND-next regime flip (= the flip back against
our inverted position). The FIRST opposing flip is the reversal we
are trying to capture; we hold THROUGH it and exit on the flip back.

Catastrophic SL: 1.0 ATR or 1.5 ATR. SL hit → immediate exit.

Causal timing: same as momentum-confirm study (decision at confirm
bar close, fill 30s later).
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "studies/hmm_5s_v1"))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from hmm_pipeline import SimpleRegimeTracker

NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
CT = pytz.timezone("America/Chicago")
SL_THRESHOLDS = [1.00, 1.50]
LABEL_MAX_S = 7200  # cap walk at 2h


def compute_atr_series(h, l, c, period=14):
    n = len(c)
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev_c = c[:-1]
    tr[1:] = np.maximum.reduce([
        h[1:] - l[1:], np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)])
    atr = np.full(n, np.nan, dtype=float)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def enumerate_flips(bars_h, bars_l, bars_o, bars_c, bars_ts,
                       bars_init, year_start_ns):
    tracker = SimpleRegimeTracker()
    flips = []
    for i in range(len(bars_c)):
        flipped = tracker.update(bars_h[i], bars_l[i], bars_c[i])
        if flipped and bars_ts[i] >= year_start_ns:
            flips.append({
                "flip_bar_idx": i,
                "flip_bar_ts_event": int(bars_ts[i]),
                "flip_bar_ts_init": int(bars_init[i]),
                "flip_bar_o": float(bars_o[i]),
                "flip_bar_h": float(bars_h[i]),
                "flip_bar_l": float(bars_l[i]),
                "flip_bar_c": float(bars_c[i]),
                "new_regime": int(tracker.regime),
            })
    df = pd.DataFrame(flips)
    if not len(df):
        return df
    df = df.sort_values("flip_bar_ts_event").reset_index(drop=True)
    # SECOND-next flip CLOSE — the flip BACK against our inverted position
    df["second_next_flip_ts_init"] = df["flip_bar_ts_init"].shift(
        -2).fillna(
        df["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")
    df["second_next_flip_close"] = df["flip_bar_c"].shift(-2).fillna(
        0.0)
    return df


def process_year(year: int):
    print(f"\n{'='*72}\nYEAR {year}\n{'='*72}")
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    print("Loading 1m bars...")
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m_nt])
    bars_1m_init = np.array([b.ts_init for b in bars_1m_nt])
    bars_1m_o = np.array([float(b.open) for b in bars_1m_nt])
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])

    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    flips = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_o, bars_1m_c,
        bars_1m_ts, bars_1m_init, year_start_ns)
    flip_dts = pd.to_datetime(flips["flip_bar_ts_event"], unit="ns",
                                  utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    flips = flips[rth_mask].copy()
    print(f"  RTH flips: {len(flips):,}")
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c)

    print("Loading 1s bars...")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC"),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    bars_c = np.array([float(b.close) for b in bars_1s_nt])

    rows_a = []  # 1m failed momentum inversion
    rows_b = []  # 30s failed momentum inversion

    for _, row in flips.iterrows():
        d_orig = int(row["new_regime"])  # original regime direction
        d_trade = -d_orig  # we trade INVERSE
        flip_idx = int(row["flip_bar_idx"])
        flip_init = int(row["flip_bar_ts_init"])
        flip_h = float(row["flip_bar_h"])
        flip_l = float(row["flip_bar_l"])
        # Exit at SECOND-next opposing flip = the flip BACK against
        # our inverted (i.e. against original) position.
        exit_ts = int(row["second_next_flip_ts_init"])
        exit_price = float(row["second_next_flip_close"])
        if exit_price == 0.0:
            continue  # no second-next flip available (end of year)

        if flip_idx + 1 >= len(bars_1m_c):
            continue
        atr = float(atr_series[flip_idx + 1])
        if not np.isfinite(atr) or atr <= 0:
            continue

        # ----- V_A: 1m bar+1 confirmation -----
        # Confirmation: bar+1 makes HH/LL in d_orig direction
        # AND fails momentum (close NOT in d_orig direction)
        signal_a = flip_init + 60 * int(1e9)
        if exit_ts > signal_a:
            b1_o = float(bars_1m_o[flip_idx + 1])
            b1_h = float(bars_1m_h[flip_idx + 1])
            b1_l = float(bars_1m_l[flip_idx + 1])
            b1_c = float(bars_1m_c[flip_idx + 1])
            if d_orig == 1:
                hhll = b1_h > flip_h
                fail_mom = b1_c <= b1_o
            else:
                hhll = b1_l < flip_l
                fail_mom = b1_c >= b1_o
            if hhll and fail_mom:
                fill_ts_target = signal_a + 30 * int(1e9)
                fi = np.searchsorted(
                    bars_ts, fill_ts_target, side="left")
                if (fi < len(bars_ts)
                        and bars_ts[fi] - fill_ts_target
                            <= 60 * int(1e9)):
                    actual_fill_ts = int(bars_ts[fi])
                    fill_price = float(bars_o[fi])
                    # Walk to exit_ts (or 2h cap)
                    walk_end = min(exit_ts,
                                     actual_fill_ts + LABEL_MAX_S * int(1e9))
                    walk_lo = fi
                    walk_hi = np.searchsorted(
                        bars_ts, walk_end, side="left")
                    walk_hi = min(walk_hi, len(bars_ts))
                    if walk_hi > walk_lo:
                        seg_h = bars_h[walk_lo:walk_hi]
                        seg_l = bars_l[walk_lo:walk_hi]
                        seg_ts = bars_ts[walk_lo:walk_hi]
                        # Compute MAE in d_trade direction
                        if d_trade == 1:
                            mae_seq = (fill_price - seg_l) / atr
                        else:
                            mae_seq = (seg_h - fill_price) / atr
                        peak_mae = np.maximum.accumulate(mae_seq)
                        for sl_thr in SL_THRESHOLDS:
                            sl_hit_mask = peak_mae >= sl_thr
                            if sl_hit_mask.any():
                                sl_idx = int(np.argmax(sl_hit_mask))
                                hold_s = (seg_ts[sl_idx]
                                            - actual_fill_ts) / 1e9
                                # SL exit price = fill - sl_thr * atr
                                # in trade direction
                                sl_exit_price = (
                                    fill_price
                                    - d_trade * sl_thr * atr)
                                gross = ((sl_exit_price - fill_price)
                                            * d_trade * NQ_MULT)
                                # SL exit: 2-tick adverse slip
                                pnl = (gross - COMMISSION
                                          - 2 * TICK_COST)
                                exit_kind = "sl"
                            else:
                                hold_s = (exit_ts
                                            - actual_fill_ts) / 1e9
                                gross = ((exit_price - fill_price)
                                            * d_trade * NQ_MULT)
                                # Regime flip-back exit:
                                # 1-tick adverse slip
                                pnl = (gross - COMMISSION
                                          - TICK_COST)
                                exit_kind = "regime"
                            rows_a.append({
                                "year": year,
                                "sl_thr": sl_thr,
                                "direction": d_trade,
                                "fill_price": fill_price,
                                "exit_kind": exit_kind,
                                "hold_s": hold_s,
                                "net_pnl": pnl,
                            })

        # ----- V_B: 30s confirmation -----
        signal_b = flip_init + 30 * int(1e9)
        if exit_ts > signal_b:
            cw_lo = np.searchsorted(bars_ts, flip_init, side="left")
            cw_hi = np.searchsorted(bars_ts, signal_b, side="left")
            if cw_hi > cw_lo:
                c30_o = float(bars_o[cw_lo])
                c30_c = float(bars_c[cw_hi - 1])
                c30_h = float(bars_h[cw_lo:cw_hi].max())
                c30_l = float(bars_l[cw_lo:cw_hi].min())
                if d_orig == 1:
                    hhll = c30_h > flip_h
                    fail_mom = c30_c <= c30_o
                else:
                    hhll = c30_l < flip_l
                    fail_mom = c30_c >= c30_o
                if hhll and fail_mom:
                    fill_ts_target = signal_b + 30 * int(1e9)
                    fi = np.searchsorted(
                        bars_ts, fill_ts_target, side="left")
                    if (fi < len(bars_ts)
                            and bars_ts[fi] - fill_ts_target
                                <= 60 * int(1e9)):
                        actual_fill_ts = int(bars_ts[fi])
                        fill_price = float(bars_o[fi])
                        walk_end = min(
                            exit_ts,
                            actual_fill_ts + LABEL_MAX_S * int(1e9))
                        walk_lo = fi
                        walk_hi = np.searchsorted(
                            bars_ts, walk_end, side="left")
                        walk_hi = min(walk_hi, len(bars_ts))
                        if walk_hi > walk_lo:
                            seg_h = bars_h[walk_lo:walk_hi]
                            seg_l = bars_l[walk_lo:walk_hi]
                            seg_ts = bars_ts[walk_lo:walk_hi]
                            if d_trade == 1:
                                mae_seq = (fill_price - seg_l) / atr
                            else:
                                mae_seq = (seg_h - fill_price) / atr
                            peak_mae = np.maximum.accumulate(mae_seq)
                            for sl_thr in SL_THRESHOLDS:
                                sl_hit = peak_mae >= sl_thr
                                if sl_hit.any():
                                    sl_idx = int(np.argmax(sl_hit))
                                    hold_s = (seg_ts[sl_idx]
                                                - actual_fill_ts) / 1e9
                                    sl_exit_price = (
                                        fill_price
                                        - d_trade * sl_thr * atr)
                                    gross = ((sl_exit_price
                                                  - fill_price)
                                                * d_trade * NQ_MULT)
                                    pnl = (gross - COMMISSION
                                              - 2 * TICK_COST)
                                    exit_kind = "sl"
                                else:
                                    hold_s = (exit_ts
                                                - actual_fill_ts) / 1e9
                                    gross = ((exit_price
                                                  - fill_price)
                                                * d_trade * NQ_MULT)
                                    pnl = (gross - COMMISSION
                                              - TICK_COST)
                                    exit_kind = "regime"
                                rows_b.append({
                                    "year": year,
                                    "sl_thr": sl_thr,
                                    "direction": d_trade,
                                    "fill_price": fill_price,
                                    "exit_kind": exit_kind,
                                    "hold_s": hold_s,
                                    "net_pnl": pnl,
                                })

    return pd.DataFrame(rows_a), pd.DataFrame(rows_b)


def stats(df, label):
    if len(df) == 0:
        return None
    pnl = df["net_pnl"]
    n = len(df)
    wr = (pnl > 0).mean() * 100
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = (wins.sum() / abs(losses.sum())
            if (pnl < 0).any() else float("inf"))
    cum = pnl.cumsum().values
    peak = np.maximum.accumulate(cum)
    mdd = float((cum - peak).min())
    sl_pct = (df["exit_kind"] == "sl").mean() * 100
    reg_pct = (df["exit_kind"] == "regime").mean() * 100
    n_long = int((df["direction"] == 1).sum())
    n_short = int((df["direction"] == -1).sum())
    med_hold = df["hold_s"].median() / 60
    return {
        "label": label, "n": n, "wr": wr,
        "mean": pnl.mean(), "median": pnl.median(),
        "total": pnl.sum(), "pf": pf, "max_dd": mdd,
        "sl_pct": sl_pct, "reg_pct": reg_pct,
        "long_pct": n_long / n * 100,
        "short_pct": n_short / n * 100,
        "med_hold_min": med_hold,
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses)
                      else float("nan"),
    }


def main():
    all_results = []
    for year in [2024, 2025, 2026]:
        df_a, df_b = process_year(year)
        for sl in SL_THRESHOLDS:
            for label, df in [("V_A 1m_failed", df_a),
                                ("V_B 30s_failed", df_b)]:
                sub = df[df["sl_thr"] == sl]
                s = stats(sub, label)
                if s is None:
                    continue
                s["year"] = year
                s["sl_thr"] = sl
                all_results.append(s)

    print("\n" + "=" * 130)
    print("FAILED MOMENTUM INVERSION — RESULTS BY YEAR × VERSION × SL")
    print("=" * 130)
    header = (
        f'{"Year":<6} {"Version":<16} {"SL":>4} {"n":>5} {"WR%":>6} '
        f'{"Mean$":>9} {"Med$":>8} {"Total$":>11} {"PF":>6} '
        f'{"MaxDD":>10} {"SL%":>6} {"Reg%":>6} '
        f'{"AvgWin":>8} {"AvgLoss":>8} {"L/S%":>9} {"Hold":>7}')
    print(header)
    print("-" * 130)
    for r in all_results:
        print(
            f'{r["year"]:<6} {r["label"]:<16} {r["sl_thr"]:>4.1f} '
            f'{r["n"]:>5,} {r["wr"]:>6.2f} {r["mean"]:>9.2f} '
            f'{r["median"]:>8,.0f} {r["total"]:>11,.0f} '
            f'{r["pf"]:>6.2f} {r["max_dd"]:>10,.0f} '
            f'{r["sl_pct"]:>6.1f} {r["reg_pct"]:>6.1f} '
            f'{r["avg_win"]:>8.0f} {r["avg_loss"]:>8.0f} '
            f'{r["long_pct"]:>3.0f}/{r["short_pct"]:>3.0f}% '
            f'{r["med_hold_min"]:>6.1f}m')

    # Aggregate
    print("\n" + "=" * 130)
    print("3-YEAR AGGREGATE")
    print("=" * 130)
    print(header)
    print("-" * 130)
    for sl in SL_THRESHOLDS:
        for label in ["V_A 1m_failed", "V_B 30s_failed"]:
            rs = [r for r in all_results
                    if r["sl_thr"] == sl and r["label"] == label]
            if not rs:
                continue
            n = sum(r["n"] for r in rs)
            total = sum(r["total"] for r in rs)
            mean = total / n if n else 0
            wr = sum(r["wr"] * r["n"] for r in rs) / n if n else 0
            sl_pct = sum(r["sl_pct"] * r["n"] for r in rs) / n
            reg_pct = sum(r["reg_pct"] * r["n"] for r in rs) / n
            print(
                f'{"ALL":<6} {label:<16} {sl:>4.1f} {n:>5,} '
                f'{wr:>6.2f} {mean:>9.2f} {"—":>8} '
                f'{total:>11,.0f} {"—":>6} {"—":>10} '
                f'{sl_pct:>6.1f} {reg_pct:>6.1f} '
                f'{"—":>8} {"—":>8} {"—":>9} {"—":>7}')


if __name__ == "__main__":
    main()
