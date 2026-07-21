"""Quick test: 30s bar HH/LL confirmation vs 1m bar+1.

Two variants:
  A. 30s HH/LL only — first 30s bar after flip close makes new HH (bull)
     or new LL (bear) vs flip bar's H/L.
  B. 30s HH/LL + momentum — A AND that 30s bar closes in regime
     direction (close > open for bull, close < open for bear).

Hold-to-regime-exit, causal: exit at next opposing flip's 1m close.
RTH only.
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


def enumerate_flips(bars_h, bars_l, bars_c, bars_ts, bars_init,
                       year_start_ns):
    tracker = SimpleRegimeTracker()
    flips = []
    for i in range(len(bars_c)):
        flipped = tracker.update(bars_h[i], bars_l[i], bars_c[i])
        if flipped and bars_ts[i] >= year_start_ns:
            flips.append({
                "flip_bar_idx": i,
                "flip_bar_ts_event": int(bars_ts[i]),
                "flip_bar_ts_init": int(bars_init[i]),
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


def run_year(year: int):
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
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])

    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    flips = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_ts, bars_1m_init,
        year_start_ns)
    print(f"  Raw flips: {len(flips):,}")

    # RTH filter on flip
    flip_dts = pd.to_datetime(flips["flip_bar_ts_event"], unit="ns",
                                  utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    flips = flips[rth_mask].copy()
    print(f"  RTH flips: {len(flips):,}")

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
    print(f"  {len(bars_1s_nt):,} 1s bars")

    rows = []
    for _, row in flips.iterrows():
        d = int(row["new_regime"])
        flip_init = int(row["flip_bar_ts_init"])
        flip_h = float(row["flip_bar_h"])
        flip_l = float(row["flip_bar_l"])
        regime_end_ts = int(row["next_flip_ts_init"])
        regime_end_price = float(row["next_flip_close"])
        if regime_end_ts <= flip_init + 30 * int(1e9):
            continue  # regime dies before 30s confirm

        # 30s confirmation bar = 1s bars from flip_init to flip_init+30s
        cw_lo = np.searchsorted(bars_ts, flip_init, side="left")
        cw_hi = np.searchsorted(bars_ts, flip_init + 30 * int(1e9),
                                  side="left")
        if cw_hi <= cw_lo:
            continue
        c30_o = float(bars_o[cw_lo])
        c30_c = float(bars_c[cw_hi - 1])
        c30_h = float(bars_h[cw_lo:cw_hi].max())
        c30_l = float(bars_l[cw_lo:cw_hi].min())

        # HH/LL confirmation
        if d == 1:
            hhll = bool(c30_h > flip_h)
            mom = bool(c30_c > c30_o)
        else:
            hhll = bool(c30_l < flip_l)
            mom = bool(c30_c < c30_o)

        # Fill at flip_init + 60s = next 1s bar OPEN
        fill_ts_target = flip_init + 60 * int(1e9)
        fi = np.searchsorted(bars_ts, fill_ts_target, side="left")
        if fi >= len(bars_ts):
            continue
        actual_fill_ts = int(bars_ts[fi])
        if actual_fill_ts - fill_ts_target > 60 * int(1e9):
            continue
        # Causal: regime intact at decision time = flip_init+30s
        decision_ts = flip_init + 30 * int(1e9)
        if regime_end_ts <= decision_ts:
            continue
        fill_price = float(bars_o[fi])
        # Hold-to-regime-exit pnl
        pnl = ((regime_end_price - fill_price) * d * NQ_MULT
                 - COMMISSION - TICK_COST)
        rows.append({
            "year": year,
            "direction": d,
            "atr_at_signal": float("nan"),
            "fill_price": fill_price,
            "regime_end_price": regime_end_price,
            "regime_dur_s": (regime_end_ts - flip_init) / 1e9,
            "hhll_30s": hhll,
            "momentum_30s": mom,
            "pnl": pnl,
        })

    df = pd.DataFrame(rows)
    return df


def stats(df, label):
    n = len(df)
    if n == 0:
        return None
    pnl = df["pnl"]
    wr = (pnl > 0).mean() * 100
    pf = (pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum())
            if (pnl < 0).any() else float("inf"))
    return {
        "label": label, "n": n,
        "wr": wr, "mean": pnl.mean(),
        "median": pnl.median(), "total": pnl.sum(), "pf": pf,
    }


def main():
    all_dfs = {}
    for year in [2024, 2025, 2026]:
        all_dfs[year] = run_year(year)

    print("\n" + "=" * 100)
    print("RESULTS — hold to regime-exit (causal), RTH only")
    print("=" * 100)
    header = (f'{"Year":<6} {"Slice":<32} {"n":>6} {"WR%":>7} '
                f'{"Mean$":>10} {"Med$":>9} {"Total$":>12} {"PF":>6}')
    print(header)
    print("-" * 100)

    cross_year = []
    for year, df in all_dfs.items():
        slices = [
            ("All RTH flips (no confirm)", df),
            ("30s HH/LL only", df[df["hhll_30s"]]),
            ("30s HH/LL + momentum", df[df["hhll_30s"]
                                            & df["momentum_30s"]]),
            ("30s HH/LL, no momentum", df[df["hhll_30s"]
                                              & ~df["momentum_30s"]]),
        ]
        for label, sub in slices:
            s = stats(sub, label)
            if s is None:
                continue
            print(f'{year:<6} {s["label"]:<32} {s["n"]:>6,} '
                   f'{s["wr"]:>7.2f} {s["mean"]:>10.2f} '
                   f'{s["median"]:>9,.0f} {s["total"]:>12,.0f} '
                   f'{s["pf"]:>6.2f}')
            cross_year.append({"year": year, **s})

    print("\n" + "=" * 100)
    print("CROSS-YEAR AGGREGATE")
    print("=" * 100)
    print(header)
    print("-" * 100)
    for label in ["All RTH flips (no confirm)", "30s HH/LL only",
                    "30s HH/LL + momentum", "30s HH/LL, no momentum"]:
        rs = [r for r in cross_year if r["label"] == label]
        if not rs:
            continue
        n = sum(r["n"] for r in rs)
        total = sum(r["total"] for r in rs)
        mean = total / n if n else 0
        wr = sum(r["wr"] * r["n"] for r in rs) / n if n else 0
        print(f'{"ALL":<6} {label:<32} {n:>6,} {wr:>7.2f} '
               f'{mean:>10.2f} {"—":>9} {total:>12,.0f} {"—":>6}')


if __name__ == "__main__":
    main()
