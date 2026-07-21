"""Offline causal collector — momentum-confirmation regime-exit.

For each RTH 1m regime flip, emit trade rows for two versions:

  Version A (1m_momentum):
    bar+1 makes new HH/LL vs flip bar's H/L AND
    bar+1 closes in regime direction (close > open for bull, etc).
    signal_time = bar+1 close = flip_init + 60s
    fill_ts = signal_time + 30s = flip_init + 90s

  Version B (30s_momentum):
    First 30s after flip close makes new HH/LL vs flip bar's H/L AND
    that 30s window closes in regime direction.
    signal_time = flip_init + 30s
    fill_ts = signal_time + 30s = flip_init + 60s

Causal rules:
  - regime_end_ts = next opposing flip's flip_bar_ts_init (1m close)
  - regime_exit_price = next opposing flip bar's close
  - drop trade only if regime is already known flipped at decision time
"""

from __future__ import annotations
import os, sys, argparse
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

OUT = Path("studies/momentum_confirm_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
CT = pytz.timezone("America/Chicago")


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
    df["next_flip_ts_init"] = df["flip_bar_ts_init"].shift(-1).fillna(
        df["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")
    df["next_flip_close"] = df["flip_bar_c"].shift(-1).fillna(0.0)
    return df


def main(year: int):
    print("=" * 72)
    print(f"MOMENTUM-CONFIRM COLLECTOR — YEAR {year}")
    print("=" * 72)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    print(f"\nLoading 1m bars...")
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
    print(f"  {len(bars_1m_nt):,} 1m bars")

    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    flips = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_o, bars_1m_c, bars_1m_ts,
        bars_1m_init, year_start_ns)
    print(f"  Raw flips: {len(flips):,}")

    flip_dts = pd.to_datetime(flips["flip_bar_ts_event"], unit="ns",
                                  utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    flips = flips[rth_mask].copy()
    print(f"  RTH flips: {len(flips):,}")

    print(f"\nLoading 1s bars...")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC"),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    bars_c = np.array([float(b.close) for b in bars_1s_nt])
    print(f"  {len(bars_1s_nt):,} 1s bars")

    rows_a = []
    rows_b = []

    for _, row in flips.iterrows():
        d = int(row["new_regime"])
        flip_idx = int(row["flip_bar_idx"])
        flip_init = int(row["flip_bar_ts_init"])
        flip_h = float(row["flip_bar_h"])
        flip_l = float(row["flip_bar_l"])
        regime_end_ts = int(row["next_flip_ts_init"])
        regime_end_price = float(row["next_flip_close"])

        # ----- Version A: 1m bar+1 confirmation -----
        # signal_time = flip_init + 60s, decision_ts = signal_time
        signal_time_a = flip_init + 60 * int(1e9)
        if regime_end_ts > signal_time_a:
            # bar+1 = next 1m bar
            if flip_idx + 1 < len(bars_1m_c):
                b1_o = float(bars_1m_o[flip_idx + 1])
                b1_h = float(bars_1m_h[flip_idx + 1])
                b1_l = float(bars_1m_l[flip_idx + 1])
                b1_c = float(bars_1m_c[flip_idx + 1])
                if d == 1:
                    hhll_ok = b1_h > flip_h
                    mom_ok = b1_c > b1_o
                else:
                    hhll_ok = b1_l < flip_l
                    mom_ok = b1_c < b1_o
                if hhll_ok and mom_ok:
                    # Fill at signal_time + 30s
                    fill_ts_target = signal_time_a + 30 * int(1e9)
                    fi = np.searchsorted(bars_ts, fill_ts_target,
                                            side="left")
                    if (fi < len(bars_ts)
                            and bars_ts[fi] - fill_ts_target
                                <= 60 * int(1e9)):
                        actual_fill_ts = int(bars_ts[fi])
                        fill_price = float(bars_o[fi])
                        pnl = ((regime_end_price - fill_price)
                                 * d * NQ_MULT
                                 - COMMISSION - TICK_COST)
                        rows_a.append({
                            "year": year,
                            "flip_bar_ts_event": int(
                                row["flip_bar_ts_event"]),
                            "flip_bar_ts_init": flip_init,
                            "direction": d,
                            "decision_ts": signal_time_a,
                            "fill_ts": actual_fill_ts,
                            "fill_price": fill_price,
                            "regime_end_ts": regime_end_ts,
                            "regime_end_price": regime_end_price,
                            "regime_dur_s": (regime_end_ts
                                                - flip_init) / 1e9,
                            "net_pnl": pnl,
                        })

        # ----- Version B: 30s confirmation -----
        signal_time_b = flip_init + 30 * int(1e9)
        if regime_end_ts > signal_time_b:
            cw_lo = np.searchsorted(bars_ts, flip_init, side="left")
            cw_hi = np.searchsorted(bars_ts, signal_time_b,
                                       side="left")
            if cw_hi > cw_lo:
                c30_o = float(bars_o[cw_lo])
                c30_c = float(bars_c[cw_hi - 1])
                c30_h = float(bars_h[cw_lo:cw_hi].max())
                c30_l = float(bars_l[cw_lo:cw_hi].min())
                if d == 1:
                    hhll_ok = c30_h > flip_h
                    mom_ok = c30_c > c30_o
                else:
                    hhll_ok = c30_l < flip_l
                    mom_ok = c30_c < c30_o
                if hhll_ok and mom_ok:
                    fill_ts_target = signal_time_b + 30 * int(1e9)
                    fi = np.searchsorted(bars_ts, fill_ts_target,
                                            side="left")
                    if (fi < len(bars_ts)
                            and bars_ts[fi] - fill_ts_target
                                <= 60 * int(1e9)):
                        actual_fill_ts = int(bars_ts[fi])
                        fill_price = float(bars_o[fi])
                        pnl = ((regime_end_price - fill_price)
                                 * d * NQ_MULT
                                 - COMMISSION - TICK_COST)
                        rows_b.append({
                            "year": year,
                            "flip_bar_ts_event": int(
                                row["flip_bar_ts_event"]),
                            "flip_bar_ts_init": flip_init,
                            "direction": d,
                            "decision_ts": signal_time_b,
                            "fill_ts": actual_fill_ts,
                            "fill_price": fill_price,
                            "regime_end_ts": regime_end_ts,
                            "regime_end_price": regime_end_price,
                            "regime_dur_s": (regime_end_ts
                                                - flip_init) / 1e9,
                            "net_pnl": pnl,
                        })

    df_a = pd.DataFrame(rows_a)
    df_b = pd.DataFrame(rows_b)
    df_a.to_parquet(OUT / f"offline_v_a_{year}.parquet", index=False)
    df_b.to_parquet(OUT / f"offline_v_b_{year}.parquet", index=False)
    print(f"\nSaved:")
    print(f"  V_A (1m HH/LL + momentum): {len(df_a):,} trades")
    print(f"  V_B (30s HH/LL + momentum): {len(df_b):,} trades")
    if len(df_a):
        print(f"  V_A: WR {(df_a['net_pnl']>0).mean()*100:.1f}%, "
               f"mean ${df_a['net_pnl'].mean():.2f}")
    if len(df_b):
        print(f"  V_B: WR {(df_b['net_pnl']>0).mean()*100:.1f}%, "
               f"mean ${df_b['net_pnl'].mean():.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    main(args.year)
