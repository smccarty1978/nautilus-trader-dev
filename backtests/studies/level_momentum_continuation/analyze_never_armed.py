"""How often do trades fail to reach the +2.5 MFE BE-trigger?

For each trade, walks bars from entry to exit and computes max
favorable excursion. Counts as 'never_armed' if MFE < 2.5 pt
during the trade's lifetime.

Reports by year, session, and pair.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
    detect_triggers,
)
from studies.level_momentum_continuation.run_be_only_2024_oos import (
    simulate_trade_with_be,
)
from studies.level_momentum_continuation.run_nq_2025 import (
    filter_roll_window,
)


BE_THRESHOLD = 2.5
YEARS = [2024, 2025]


def regenerate_trades_v0(year):
    """Re-simulate trades for a year using .v.0 1s data so
    entry_idx aligns with the same bars we use for MFE."""
    parquet = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
    bars_1s = load_v0_1s(parquet)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)
    bars_filt, _ = filter_roll_window(bars_1m, 3)
    bars_reset = bars_filt.reset_index(drop=False)
    triggers = detect_triggers(bars_reset)
    rows = []
    for tr in triggers:
        r = simulate_trade_with_be(tr, bars_reset, BE_THRESHOLD)
        if r is not None:
            rows.append(r)
    trades = pd.DataFrame(rows)
    L_offset = trades["breach_level"] - (
        (trades["breach_level"] // 100) * 100)
    Y_offset = trades["next_level"] - (
        (trades["next_level"] // 100) * 100)
    Y_offset = Y_offset.where(Y_offset != 100.0, 0.0)
    trades["level_pair"] = (
        L_offset.astype(int).astype(str).str.zfill(2)
        + "->"
        + Y_offset.astype(int).astype(str).str.zfill(2)
        + "_"
        + trades["direction"].map({1: "long", -1: "short"})
    )
    return trades, bars_reset


def compute_max_mfe(trades, bars):
    """Walk bars per trade, compute max favorable excursion."""
    bars = bars.reset_index(drop=False)
    highs = bars["high"].values
    lows = bars["low"].values
    n = len(bars)
    out = trades.copy().reset_index(drop=True)
    eidx = out["entry_idx"].astype(int).values
    xidx = out["exit_idx"].astype(int).values
    d = out["direction"].astype(int).values
    ep = out["entry_price"].astype(float).values
    mfe = np.zeros(len(out))
    for i in range(len(out)):
        ei = eidx[i]
        xi = min(xidx[i], n - 1)
        if xi < ei: continue
        max_fav = 0.0
        di = d[i]
        epi = ep[i]
        for k in range(ei, xi + 1):
            h = highs[k]; l = lows[k]
            fav = (h - epi) if di == 1 else (epi - l)
            if fav > max_fav:
                max_fav = fav
        mfe[i] = max_fav
    out["full_mfe_pts"] = mfe
    out["never_armed"] = (mfe < BE_THRESHOLD).astype(int)
    return out


def main():
    for year in YEARS:
        print(f"\n[{year}] regenerating trades from .v.0 1s...")
        trades, bars_filt = regenerate_trades_v0(year)
        print(f"[{year}] computing MFE for {len(trades):,} trades...")
        out = compute_max_mfe(trades, bars_filt)

        # Overall
        n = len(out)
        n_never = int(out["never_armed"].sum())
        print(f"\n[{year}] OVERALL: n={n:,}, "
              f"never_armed={n_never:,} "
              f"({100*n_never/n:.1f}%)")

        # By session
        print(f"[{year}] By session:")
        for sess, g in out.groupby("entry_session"):
            n_g = len(g)
            n_n = int(g["never_armed"].sum())
            print(f"  {sess}: n={n_g:,}, "
                  f"never_armed={n_n:,} ({100*n_n/n_g:.1f}%)")

        # By pair
        print(f"[{year}] By pair (sorted by never_armed%):")
        rows = []
        for pair, g in out.groupby("level_pair"):
            n_g = len(g)
            n_n = int(g["never_armed"].sum())
            mfe_p50 = float(np.percentile(g["full_mfe_pts"], 50))
            mfe_p25 = float(np.percentile(g["full_mfe_pts"], 25))
            rows.append({"pair": pair, "n": n_g,
                              "never_armed_n": n_n,
                              "never_armed_pct": n_n/n_g,
                              "mfe_p25": mfe_p25,
                              "mfe_p50": mfe_p50})
        df = pd.DataFrame(rows).sort_values(
            "never_armed_pct", ascending=False)
        print(df.to_string(index=False,
                                 float_format=lambda v: f"{v:.3f}"))

        # By pair × session
        print(f"\n[{year}] By pair × session:")
        rows = []
        for keys, g in out.groupby(
                ["level_pair", "entry_session"]):
            n_g = len(g)
            n_n = int(g["never_armed"].sum())
            rows.append({"pair": keys[0], "session": keys[1],
                              "n": n_g,
                              "never_armed_pct": n_n/n_g})
        ps = pd.DataFrame(rows).sort_values(
            ["pair", "session"])
        print(ps.to_string(index=False,
                                  float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
