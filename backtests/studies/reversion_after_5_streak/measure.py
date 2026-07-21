"""Reversion after a 6-bar same-direction streak on 1m bars (NQ.v.0, 2024-2025).

Question (user-defined):
  After a streak of 6 consecutive 1m bars where close > open (bullish) or
  close < open (bearish), what % of the time does at least one of the next
  2 bars CLOSE beyond the 6th-bar close by {0.25, 0.5, 1.0} * ATR(14)?
  And, for the events that hit each threshold, what is the mean MAE over
  the 2-bar window? (MAE = max adverse excursion AGAINST the fade direction:
  bullish streak fade is short, MAE = max(high+1, high+2) - close6;
  bearish streak fade is long, MAE = close6 - min(low+1, low+2).)

Definitions:
  - Streak side: 6 consecutive bars with sign(close - open) all the same
    (no doji; bars with close == open break the streak).
  - Consecutive: ts_event diff == 60s between every pair (drops streaks
    spanning the 16:00-17:00 CT pause or weekend close).
  - ATR: Wilder's ATR(14) on 1m bars, snapshot at the 6th bar.
  - Hit: bullish streak hits if min(close+1, close+2) < close6 - X * atr6;
    bearish: max(close+1, close+2) > close6 + X * atr6.
  - MAE (intra-bar): bullish: max(high+1, high+2) - close6 (points up against
    the short fade). Bearish: close6 - min(low+1, low+2) (points down against
    the long fade). Reported in ATR units.
  - Session of the streak end: classified by 6th-bar ts_init (close time) in
    America/Chicago. RTH = 08:30 CT (incl.) to 15:00 CT (excl.). Both forward
    bars must fall in the same session bucket as the streak end.

Output:
  studies/reversion_after_5_streak/results/{summary.csv, events.parquet}
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog


CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
START = "2024-01-01"
END = "2025-12-31 23:59:59"
ATR_PERIOD = 14
STREAK_LEN = 6
FORWARD_BARS = 2
ATR_MULTS = [0.25, 0.5, 1.0]
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_df() -> pd.DataFrame:
    print(f"Loading {BAR_TYPE} {START} -> {END}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp(START, tz="UTC"),
        end=pd.Timestamp(END, tz="UTC"),
    )
    print(f"  {len(bars):,} bars in {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame({
        "ts_event": [b.ts_event for b in bars],
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    })
    df["ts_event_dt"] = pd.to_datetime(df["ts_event"], unit="ns", utc=True)
    df["ts_init_dt"]  = pd.to_datetime(df["ts_init"],  unit="ns", utc=True)
    return df.sort_values("ts_event").reset_index(drop=True)


def compute_atr_wilder(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's ATR. tr at row 0 = high-low. atr starts after `period` rows."""
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    if n > 1:
        prev_close = close[:-1]
        tr[1:] = np.maximum.reduce([
            high[1:] - low[1:],
            np.abs(high[1:] - prev_close),
            np.abs(low[1:] - prev_close),
        ])
    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = tr[:period].mean()
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(atr, index=df.index, name="atr")


def session_of_close_ct(ts_init_utc_ns: np.ndarray) -> np.ndarray:
    """Classify each bar's CLOSE time as RTH or ETH (America/Chicago)."""
    dt_utc = pd.to_datetime(ts_init_utc_ns, unit="ns", utc=True)
    dt_ct = dt_utc.tz_convert("America/Chicago")
    minutes = dt_ct.hour * 60 + dt_ct.minute
    rth_mask = (minutes >= 8 * 60 + 30) & (minutes < 15 * 60)
    return np.where(rth_mask, "RTH", "ETH")


def find_streak_ends(df: pd.DataFrame, side: str) -> np.ndarray:
    """Indices of bars that end a 5-bar streak of given side.
    side='bull': all 5 bars have close > open. side='bear': close < open.
    Each pair of consecutive bars in the streak must have ts_event diff == 60s.
    """
    if side == "bull":
        bar_match = (df["close"] > df["open"]).to_numpy()
    elif side == "bear":
        bar_match = (df["close"] < df["open"]).to_numpy()
    else:
        raise ValueError(side)

    ts = df["ts_event"].to_numpy()
    consec = np.zeros(len(df), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000

    n = len(df)
    ends = []
    if n < STREAK_LEN:
        return np.array(ends, dtype=int)
    for i in range(STREAK_LEN - 1, n):
        ok = bar_match[i - STREAK_LEN + 1:i + 1].all()
        if not ok:
            continue
        gap_ok = consec[i - STREAK_LEN + 2:i + 1].all()
        if gap_ok:
            ends.append(i)
    return np.array(ends, dtype=int)


def evaluate(df: pd.DataFrame, ends: np.ndarray, side: str) -> pd.DataFrame:
    """For each streak end, check forward 1 and 2 bars closes vs ATR threshold."""
    sign = +1 if side == "bull" else -1
    rows = []
    n = len(df)
    ts = df["ts_event"].to_numpy()
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    atr = df["atr"].to_numpy()
    sess_close = session_of_close_ct(df["ts_init"].to_numpy())

    for i in ends:
        if i + FORWARD_BARS >= n:
            continue
        if i < STREAK_LEN:
            continue   # need close of bar before streak for magnitude calc
        a = atr[i]
        if not np.isfinite(a):
            continue
        # Forward bars must be 60s-consecutive with the streak end.
        gap_ok = True
        for k in range(1, FORWARD_BARS + 1):
            if ts[i + k] - ts[i + k - 1] != 60_000_000_000:
                gap_ok = False
                break
        if not gap_ok:
            continue
        # Both forward bars must be in the same session as the streak-end close.
        sess = sess_close[i]
        if not (sess_close[i + 1] == sess and sess_close[i + 2] == sess):
            continue

        c5 = close[i]
        c1, c2 = close[i + 1], close[i + 2]
        h1, h2 = high[i + 1], high[i + 2]
        l1, l2 = low[i + 1], low[i + 2]
        # Streak magnitude: close[end] - close[bar before streak start]
        # (signed in fade direction: positive means a "stronger" streak)
        c_pre = close[i - STREAK_LEN]
        if sign > 0:
            streak_pts = c5 - c_pre
        else:
            streak_pts = c_pre - c5
        streak_atr = streak_pts / a if a > 0 else np.nan
        # Reversion direction is opposite to the streak direction (fade trade).
        # MAE is intra-bar excursion AGAINST the fade.
        if sign > 0:
            # Bullish streak -> short fade. Favorable = closes below c5.
            reverted_close = min(c1, c2)
            move = c5 - reverted_close          # positive when reverted
            mae_full_pts = max(h1, h2) - c5      # adverse for short = high above entry
            mae_bar1_pts = h1 - c5
        else:
            # Bearish streak -> long fade. Favorable = closes above c5.
            reverted_close = max(c1, c2)
            move = reverted_close - c5
            mae_full_pts = c5 - min(l1, l2)      # adverse for long = low below entry
            mae_bar1_pts = c5 - l1
        mae_full_pts = max(mae_full_pts, 0.0)
        mae_bar1_pts = max(mae_bar1_pts, 0.0)
        row = {
            "side": side,
            "session": sess,
            "ts_init_5": df["ts_init"].iloc[i],
            "close_5": c5,
            "atr_5": a,
            "close_plus1": c1,
            "close_plus2": c2,
            "reversion_pts": move,
            "reversion_atr": move / a if a > 0 else np.nan,
            "mae_pts": mae_full_pts,
            "mae_atr": mae_full_pts / a if a > 0 else np.nan,
            "streak_pts": streak_pts,
            "streak_atr": streak_atr,
        }
        # Per-threshold: hit, first-hit bar (0 = no hit, 1 or 2), and MAE
        # measured only up to (and including) the first-hit bar.
        for m in ATR_MULTS:
            thr = m * a
            if sign > 0:
                hit1 = (c5 - c1) >= thr
                hit2 = (c5 - c2) >= thr
            else:
                hit1 = (c1 - c5) >= thr
                hit2 = (c2 - c5) >= thr
            if hit1:
                first_hit = 1
                mae_first_pts = mae_bar1_pts
            elif hit2:
                first_hit = 2
                mae_first_pts = mae_full_pts  # both bars in window before exit
            else:
                first_hit = 0
                mae_first_pts = np.nan
            row[f"hit_{m}"] = bool(hit1 or hit2)
            row[f"first_hit_bar_{m}"] = first_hit
            row[f"mae_first_pts_{m}"] = mae_first_pts
            row[f"mae_first_atr_{m}"] = (mae_first_pts / a
                                         if (a > 0 and not np.isnan(mae_first_pts))
                                         else np.nan)
        rows.append(row)

    return pd.DataFrame(rows)


def _qstats(s: pd.Series) -> dict:
    if len(s) == 0 or s.isna().all():
        return {k: np.nan for k in ("n", "mean", "p50", "p75", "p90")}
    s = s.dropna()
    return {
        "n":    int(len(s)),
        "mean": s.mean(),
        "p50":  s.median(),
        "p75":  s.quantile(0.75),
        "p90":  s.quantile(0.90),
    }


def summarise(events: pd.DataFrame) -> pd.DataFrame:
    """Per (side, session, threshold) row: hit rate, winner MAE-to-first-hit (ATR),
    loser MAE over full 2-bar window (ATR), and full-population MAE (ATR)."""
    rows = []
    sides = sorted(events["side"].unique())
    sessions = list(sorted(events["session"].unique())) + ["ALL"]
    for side in sides:
        for sess in sessions:
            grp = events[events["side"] == side]
            if sess != "ALL":
                grp = grp[grp["session"] == sess]
            n_total = len(grp)
            for m in ATR_MULTS:
                hit = grp[f"hit_{m}"]
                winners = grp.loc[hit]
                losers  = grp.loc[~hit]
                w = _qstats(winners[f"mae_first_atr_{m}"])
                l = _qstats(losers["mae_atr"])
                a = _qstats(grp["mae_atr"])
                row = {
                    "side": side, "session": sess,
                    "PT_atr": m, "n_total": n_total,
                    "hit_pct": (hit.mean() * 100) if n_total else np.nan,
                    "n_hit": int(hit.sum()),
                    # Winner MAE: only up to first-hit bar (in ATR)
                    "win_mae_mean": w["mean"], "win_mae_p50": w["p50"],
                    "win_mae_p75":  w["p75"],  "win_mae_p90": w["p90"],
                    # Loser MAE: full 2-bar window MAE among non-hit events (ATR)
                    "lose_mae_mean": l["mean"], "lose_mae_p50": l["p50"],
                    "lose_mae_p75":  l["p75"],  "lose_mae_p90": l["p90"],
                    # All-population MAE: full 2-bar window across every event (ATR)
                    "all_mae_mean": a["mean"], "all_mae_p50": a["p50"],
                    "all_mae_p75":  a["p75"],  "all_mae_p90": a["p90"],
                }
                rows.append(row)
    return pd.DataFrame(rows)


MAG_FIXED_BINS = [-np.inf, 0.5, 1.0, 1.5, 2.0, 3.0, np.inf]
MAG_FIXED_LABELS = ["<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", "2.0-3.0", "3.0+"]


def summarise_by_magnitude(events: pd.DataFrame, n_quintiles: int = 5) -> pd.DataFrame:
    """Per (side, magnitude_bucket, PT) row: hit %, winner & loser MAE in ATR.
    Two bucket schemes: fixed ATR cutoffs and per-side quintiles."""
    rows = []
    for scheme in ("fixed", "quintile"):
        for side in sorted(events["side"].unique()):
            grp_side = events[events["side"] == side].copy()
            if scheme == "fixed":
                grp_side["bucket"] = pd.cut(
                    grp_side["streak_atr"],
                    bins=MAG_FIXED_BINS, labels=MAG_FIXED_LABELS,
                    right=False, include_lowest=True,
                )
            else:
                try:
                    grp_side["bucket"] = pd.qcut(
                        grp_side["streak_atr"], q=n_quintiles,
                        labels=[f"Q{i+1}" for i in range(n_quintiles)],
                        duplicates="drop",
                    )
                except ValueError:
                    continue
            for bkt, sub in grp_side.groupby("bucket", observed=True):
                if len(sub) == 0:
                    continue
                mag_p50 = sub["streak_atr"].median()
                mag_min = sub["streak_atr"].min()
                mag_max = sub["streak_atr"].max()
                for m in ATR_MULTS:
                    hit = sub[f"hit_{m}"]
                    win = sub.loc[hit, f"mae_first_atr_{m}"]
                    los = sub.loc[~hit, "mae_atr"]
                    rows.append({
                        "scheme": scheme,
                        "side": side,
                        "bucket": str(bkt),
                        "n": len(sub),
                        "mag_min": mag_min, "mag_p50": mag_p50, "mag_max": mag_max,
                        "PT_atr": m,
                        "hit_pct": hit.mean() * 100,
                        "win_mae_p50": win.median() if len(win) else np.nan,
                        "win_mae_p90": win.quantile(0.90) if len(win) else np.nan,
                        "lose_mae_p50": los.median() if len(los) else np.nan,
                        "lose_mae_p90": los.quantile(0.90) if len(los) else np.nan,
                    })
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_1m_df()
    df["atr"] = compute_atr_wilder(df, ATR_PERIOD)

    print(f"\nDetecting {STREAK_LEN}-bar streaks...", flush=True)
    bull_ends = find_streak_ends(df, "bull")
    bear_ends = find_streak_ends(df, "bear")
    print(f"  bullish streak ends: {len(bull_ends):,}")
    print(f"  bearish streak ends: {len(bear_ends):,}")

    bull_evt = evaluate(df, bull_ends, "bull")
    bear_evt = evaluate(df, bear_ends, "bear")
    events = pd.concat([bull_evt, bear_evt], ignore_index=True)
    events.to_parquet(OUT / "events.parquet")
    print(f"\nQualified events (streak + 2 forward bars all same session, "
          f"60s-consec, ATR finite): {len(events):,}")

    summary = summarise(events)
    summary.to_csv(OUT / "summary.csv", index=False)

    mag_summary = summarise_by_magnitude(events)
    mag_summary.to_csv(OUT / "summary_by_magnitude.csv", index=False)

    print("\n=== STREAK MAGNITUDE DISTRIBUTION (ATR units, close-to-close) ===")
    for side in sorted(events["side"].unique()):
        s = events.loc[events["side"] == side, "streak_atr"]
        print(f"  {side}: n={len(s):,}  p10={s.quantile(0.1):.2f}  "
              f"p25={s.quantile(0.25):.2f}  p50={s.median():.2f}  "
              f"p75={s.quantile(0.75):.2f}  p90={s.quantile(0.9):.2f}  "
              f"max={s.max():.2f}")

    print("\n=== HIT % BY STREAK MAGNITUDE (fixed ATR bins) ===")
    fixed = mag_summary[mag_summary["scheme"] == "fixed"]
    with pd.option_context("display.max_columns", None,
                           "display.width", 200,
                           "display.float_format", "{:.2f}".format):
        cols = ["side", "bucket", "n", "mag_p50", "PT_atr",
                "hit_pct", "win_mae_p50", "win_mae_p90",
                "lose_mae_p50", "lose_mae_p90"]
        print(fixed[cols].to_string(index=False))

    print("\n=== HIT % BY STREAK MAGNITUDE (per-side quintiles) ===")
    qs = mag_summary[mag_summary["scheme"] == "quintile"]
    with pd.option_context("display.max_columns", None,
                           "display.width", 200,
                           "display.float_format", "{:.2f}".format):
        cols = ["side", "bucket", "n", "mag_p50", "PT_atr",
                "hit_pct", "win_mae_p50", "win_mae_p90",
                "lose_mae_p50", "lose_mae_p90"]
        print(qs[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'summary.csv'}, {OUT/'summary_by_magnitude.csv'}, "
          f"{OUT/'events.parquet'}")


if __name__ == "__main__":
    main()
