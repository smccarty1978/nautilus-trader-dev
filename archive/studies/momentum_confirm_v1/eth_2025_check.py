"""ETH-only check: same momentum-confirmation logic, 2025 only."""

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
YEAR = 2025


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
    df = pd.DataFrame(flips).sort_values(
        "flip_bar_ts_event").reset_index(drop=True)
    df["next_flip_ts_init"] = df["flip_bar_ts_init"].shift(-1).fillna(
        df["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")
    df["next_flip_close"] = df["flip_bar_c"].shift(-1).fillna(0.0)
    return df


def main():
    print("=" * 72)
    print(f"ETH-ONLY MOMENTUM-CONFIRM CHECK — YEAR {YEAR}")
    print("=" * 72)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    print("\nLoading 1m bars...")
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{YEAR}-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp(f"{YEAR}-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m_nt])
    bars_1m_init = np.array([b.ts_init for b in bars_1m_nt])
    bars_1m_o = np.array([float(b.open) for b in bars_1m_nt])
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])
    print(f"  {len(bars_1m_nt):,} 1m bars")

    year_start_ns = pd.Timestamp(f"{YEAR}-01-01", tz="UTC").value
    flips = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_o, bars_1m_c, bars_1m_ts,
        bars_1m_init, year_start_ns)
    print(f"  Raw flips: {len(flips):,}")

    flip_dts = pd.to_datetime(flips["flip_bar_ts_event"], unit="ns",
                                  utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    # ETH = NOT RTH (RTH = 510-900 = 8:30-15:00 CT)
    eth_mask = (flip_minutes < 510) | (flip_minutes >= 900)
    flips_eth = flips[eth_mask].copy()
    flips_rth = flips[~eth_mask].copy()
    print(f"  ETH flips: {len(flips_eth):,}")
    print(f"  RTH flips: {len(flips_rth):,} (for reference)")

    print(f"\nLoading 1s bars...")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{YEAR}-01-01", tz="UTC"),
        end=pd.Timestamp(f"{YEAR}-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    bars_c = np.array([float(b.close) for b in bars_1s_nt])
    print(f"  {len(bars_1s_nt):,} 1s bars")

    def process(flips_df, label):
        rows_a = []
        rows_b = []
        for _, row in flips_df.iterrows():
            d = int(row["new_regime"])
            flip_idx = int(row["flip_bar_idx"])
            flip_init = int(row["flip_bar_ts_init"])
            flip_h = float(row["flip_bar_h"])
            flip_l = float(row["flip_bar_l"])
            regime_end_ts = int(row["next_flip_ts_init"])
            regime_end_price = float(row["next_flip_close"])

            # V_A: 1m bar+1
            signal_time_a = flip_init + 60 * int(1e9)
            if regime_end_ts > signal_time_a:
                if flip_idx + 1 < len(bars_1m_c):
                    b1_o = float(bars_1m_o[flip_idx + 1])
                    b1_h = float(bars_1m_h[flip_idx + 1])
                    b1_l = float(bars_1m_l[flip_idx + 1])
                    b1_c = float(bars_1m_c[flip_idx + 1])
                    if d == 1:
                        hhll = b1_h > flip_h
                        mom = b1_c > b1_o
                    else:
                        hhll = b1_l < flip_l
                        mom = b1_c < b1_o
                    if hhll and mom:
                        fill_ts_target = signal_time_a + 30 * int(1e9)
                        fi = np.searchsorted(
                            bars_ts, fill_ts_target, side="left")
                        if (fi < len(bars_ts)
                                and bars_ts[fi] - fill_ts_target
                                    <= 60 * int(1e9)):
                            fill_price = float(bars_o[fi])
                            pnl = ((regime_end_price - fill_price)
                                     * d * NQ_MULT
                                     - COMMISSION - TICK_COST)
                            rows_a.append({
                                "direction": d,
                                "regime_dur_s": (regime_end_ts
                                                    - flip_init) / 1e9,
                                "net_pnl": pnl})

            # V_B: 30s
            signal_time_b = flip_init + 30 * int(1e9)
            if regime_end_ts > signal_time_b:
                cw_lo = np.searchsorted(bars_ts, flip_init,
                                           side="left")
                cw_hi = np.searchsorted(bars_ts, signal_time_b,
                                           side="left")
                if cw_hi > cw_lo:
                    c30_o = float(bars_o[cw_lo])
                    c30_c = float(bars_c[cw_hi - 1])
                    c30_h = float(bars_h[cw_lo:cw_hi].max())
                    c30_l = float(bars_l[cw_lo:cw_hi].min())
                    if d == 1:
                        hhll = c30_h > flip_h
                        mom = c30_c > c30_o
                    else:
                        hhll = c30_l < flip_l
                        mom = c30_c < c30_o
                    if hhll and mom:
                        fill_ts_target = signal_time_b + 30 * int(1e9)
                        fi = np.searchsorted(
                            bars_ts, fill_ts_target, side="left")
                        if (fi < len(bars_ts)
                                and bars_ts[fi] - fill_ts_target
                                    <= 60 * int(1e9)):
                            fill_price = float(bars_o[fi])
                            pnl = ((regime_end_price - fill_price)
                                     * d * NQ_MULT
                                     - COMMISSION - TICK_COST)
                            rows_b.append({
                                "direction": d,
                                "regime_dur_s": (regime_end_ts
                                                    - flip_init) / 1e9,
                                "net_pnl": pnl})
        return pd.DataFrame(rows_a), pd.DataFrame(rows_b)

    print(f"\nProcessing {len(flips_eth):,} ETH flips + "
           f"{len(flips_rth):,} RTH flips...")
    df_a_eth, df_b_eth = process(flips_eth, "ETH")
    df_a_rth, df_b_rth = process(flips_rth, "RTH")

    def stats(df, label):
        if len(df) == 0:
            return None
        pnl = df["net_pnl"]
        n = len(pnl)
        wr = (pnl > 0).mean() * 100
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        pf = (wins.sum() / abs(losses.sum())
                if (pnl < 0).any() else float("inf"))
        n_long = int((df["direction"] == 1).sum())
        n_short = int((df["direction"] == -1).sum())
        med_dur = df["regime_dur_s"].median() / 60
        return {
            "label": label, "n": n, "wr": wr,
            "mean": pnl.mean(), "median": pnl.median(),
            "total": pnl.sum(), "pf": pf,
            "long_pct": n_long / n * 100,
            "short_pct": n_short / n * 100,
            "med_dur_min": med_dur,
            "avg_win": float(wins.mean()) if len(wins) else float("nan"),
            "avg_loss": float(losses.mean()) if len(losses)
                          else float("nan"),
        }

    print("\n" + "=" * 110)
    print(f"RESULTS — momentum-confirm regime-exit, 2025")
    print("=" * 110)
    header = (
        f'{"Session":<8} {"Version":<8} {"n":>6} {"WR%":>6} '
        f'{"Mean$":>9} {"Med$":>8} {"Total$":>11} {"PF":>6} '
        f'{"AvgWin":>9} {"AvgLoss":>9} {"L/S%":>9} {"MedDur":>8}')
    print(header)
    print("-" * 110)
    for label, df in [("ETH V_A", df_a_eth), ("ETH V_B", df_b_eth),
                        ("RTH V_A", df_a_rth), ("RTH V_B", df_b_rth)]:
        s = stats(df, label)
        if s is None:
            continue
        sess, ver = label.split(" ")
        print(f'{sess:<8} {ver:<8} {s["n"]:>6,} {s["wr"]:>6.2f} '
               f'{s["mean"]:>9.2f} {s["median"]:>8,.0f} '
               f'{s["total"]:>11,.0f} {s["pf"]:>6.2f} '
               f'{s["avg_win"]:>9.0f} {s["avg_loss"]:>9.0f} '
               f'{s["long_pct"]:>3.0f}/{s["short_pct"]:>3.0f}% '
               f'{s["med_dur_min"]:>7.1f}m')


if __name__ == "__main__":
    main()
