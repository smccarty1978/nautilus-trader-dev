"""Level Momentum Continuation — bullish-bar (open-outside, close-inside)
trigger filter, single-position skip-while-open, 1m bracket simulation.

Differences from level_study v1:
- Trigger requires the bar's OPEN to be outside the Goldilocks zone and
  the CLOSE to be inside it. For long L->Y: open <= L AND L < close <
  midpoint. For short L->Y: open >= L AND midpoint < close < L. This
  enforces "true breakout" shape (bar travels INTO the zone from
  outside the level), excluding reclaim and gap+hold bars.
- Skip-while-open chain logic at trigger level (one trade at a time).
- MFE/MAE tracked per trade for SL/PT tuning analysis.
- Groups results by level-pair gap size:
    A (25 pt) : 25-50, 50-75
    B (14-15) : 11-25, 75-90
    C (10-11) : 90-00, 00-11

Data: NQ.v.0 (continuous volume contract) — no quarterly-roll issue.
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
    absolute_levels_in_range, next_level_above, next_level_below,
    prior_level_in_sequence_long, prior_level_in_sequence_short,
    HANDLE, TARGET_BUFFER_PTS,
)

NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25
MAX_BARS = 120  # 1m bracket time limit

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)


# ---------------- Trigger detection (with bar-shape filter) ----------------

def detect_triggers_breakout(bars: pd.DataFrame) -> list[dict]:
    """One pass over bars detecting Goldilocks triggers that ALSO
    satisfy the bar-shape requirement: open OUTSIDE the zone, close
    INSIDE the zone.

    Long L->Y: open <= L AND L < close < midpoint
    Short L->Y: open >= L AND midpoint < close < L

    Multi-level breach in one bar: take the LATEST qualifying level
    (highest for long, lowest for short).
    """
    bars = bars.reset_index(drop=False)
    opens = bars["open"].values
    closes = bars["close"].values
    sessions = bars["session"].values
    ts_closes = bars["ts_close"].values
    n = len(bars)
    out: list[dict] = []
    for i in range(1, n):
        prev_c = closes[i - 1]
        cur_o = opens[i]
        cur_c = closes[i]
        if cur_c == prev_c:
            continue
        if cur_c > prev_c:
            d = 1
            lo, hi = prev_c, cur_c
        else:
            d = -1
            lo, hi = cur_c, prev_c
        levels = absolute_levels_in_range(lo, hi)
        if d == 1:
            breached = sorted(
                [L for L in levels if prev_c < L and cur_c > L],
                reverse=True)
        else:
            breached = sorted(
                [L for L in levels if prev_c > L and cur_c < L])
        if not breached:
            continue

        for L in breached:
            if d == 1:
                Y = next_level_above(L + 1e-9)
                target = Y - TARGET_BUFFER_PTS
                midpoint = (L + target) / 2.0
                # Goldilocks: close in (L, midpoint)
                if not (L < cur_c < midpoint):
                    continue
                # Bar shape: open at/below the level
                if not (cur_o <= L):
                    continue
                stop = prior_level_in_sequence_long(L)
            else:
                Y = next_level_below(L - 1e-9)
                target = Y + TARGET_BUFFER_PTS
                midpoint = (L + target) / 2.0
                if not (midpoint < cur_c < L):
                    continue
                if not (cur_o >= L):
                    continue
                stop = prior_level_in_sequence_short(L)

            L_off = L - (int(L // HANDLE) * HANDLE)
            Y_off = Y - (int(Y // HANDLE) * HANDLE)
            if Y_off == 100.0:
                Y_off = 0.0
            pair = (f"{int(L_off):02d}->{int(Y_off):02d}_"
                    f"{'long' if d == 1 else 'short'}")

            out.append({
                "bar_idx": i,
                "direction": d,
                "breach_level": L,
                "next_level": Y,
                "target": target,
                "stop": stop,
                "midpoint": midpoint,
                "open_at_breach": float(cur_o),
                "close_at_breach": float(cur_c),
                "bar_ts_close": ts_closes[i],
                "bar_session": sessions[i],
                "level_pair": pair,
            })
            break  # only the latest qualifying level per bar
    return out


# ---------------- 1m bracket simulation w/ MFE+MAE ----------------

def simulate_trade_1m(
    trig: dict,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    ts_closes: np.ndarray,
    sessions: np.ndarray,
    n: int,
) -> dict | None:
    """Enter at open of bar (trig.bar_idx + 1). Walk forward up to
    MAX_BARS bars. Stop-then-target priority within bar (conservative).
    Track MFE/MAE per bar. Return None if entry off the end."""
    entry_idx = trig["bar_idx"] + 1
    if entry_idx >= n:
        return None
    d = trig["direction"]
    target = trig["target"]
    stop = trig["stop"]
    entry_price = float(opens[entry_idx])
    entry_ts = ts_closes[entry_idx]
    entry_session = sessions[entry_idx]
    last_bar = min(entry_idx + MAX_BARS - 1, n - 1)
    mae = 0.0
    mfe = 0.0
    for i in range(entry_idx, last_bar + 1):
        h = float(highs[i]); l = float(lows[i]); c = float(closes[i])
        if d == 1:
            adverse = entry_price - l
            favorable = h - entry_price
        else:
            adverse = h - entry_price
            favorable = entry_price - l
        if adverse > mae:
            mae = adverse
        if favorable > mfe:
            mfe = favorable
        # Stop-then-target priority
        if d == 1:
            stop_hit = l <= stop
            tgt_hit = h >= target
        else:
            stop_hit = h >= stop
            tgt_hit = l <= target
        if stop_hit:
            exit_price = float(stop)
            return _result(trig, entry_idx, entry_price, entry_ts,
                           entry_session, i, exit_price,
                           ts_closes[i], "loss", mae, mfe)
        if tgt_hit:
            exit_price = float(target)
            return _result(trig, entry_idx, entry_price, entry_ts,
                           entry_session, i, exit_price,
                           ts_closes[i], "win", mae, mfe)
    # Time-out
    exit_price = float(closes[last_bar])
    return _result(trig, entry_idx, entry_price, entry_ts,
                   entry_session, last_bar, exit_price,
                   ts_closes[last_bar], "timed_out", mae, mfe)


def _result(trig, entry_idx, entry_px, entry_ts, entry_session,
            exit_idx, exit_px, exit_ts, outcome, mae, mfe):
    d = trig["direction"]
    pnl_pts = (exit_px - entry_px) * d
    return {
        "trigger_ts_close": pd.Timestamp(trig["bar_ts_close"]),
        "trigger_session": trig["bar_session"],
        "level_pair": trig["level_pair"],
        "direction": d,
        "breach_level": trig["breach_level"],
        "target": trig["target"],
        "stop": trig["stop"],
        "open_at_breach": trig["open_at_breach"],
        "close_at_breach": trig["close_at_breach"],
        "entry_idx": entry_idx,
        "entry_price": entry_px,
        "entry_ts_close": pd.Timestamp(entry_ts),
        "entry_session": entry_session,
        "exit_idx": exit_idx,
        "exit_price": exit_px,
        "exit_ts_close": pd.Timestamp(exit_ts),
        "bars_held": exit_idx - entry_idx + 1,
        "outcome": outcome,
        "mae_pts": float(mae),
        "mfe_pts": float(mfe),
        "pnl_pts": float(pnl_pts),
        "pnl_net_pts": float(pnl_pts - COMMISSION_PTS),
        "pnl_dollars": float((pnl_pts - COMMISSION_PTS)
                              * NQ_DOLLAR_PER_PT),
    }


# ---------------- Chain w/ skip-while-open ----------------

def run_chain(triggers: list[dict], bars_1m: pd.DataFrame) -> pd.DataFrame:
    bars = bars_1m.reset_index(drop=False)
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    ts_closes = bars["ts_close"].values
    sessions = bars["session"].values
    n = len(bars)

    out = []
    last_exit_idx = -1
    for trig in triggers:
        # Skip-while-open: trigger bar (bar_idx) must be > last exit bar
        if trig["bar_idx"] <= last_exit_idx:
            continue
        r = simulate_trade_1m(trig, opens, highs, lows, closes,
                              ts_closes, sessions, n)
        if r is None:
            continue
        out.append(r)
        last_exit_idx = r["exit_idx"]
    return pd.DataFrame(out)


# ---------------- Gap groups ----------------

LEVEL_PAIR_TO_GROUP = {
    # Group A — 25 pt
    "25->50_long": "A_25pt", "50->25_short": "A_25pt",
    "50->75_long": "A_25pt", "75->50_short": "A_25pt",
    # Group B — 14-15 pt
    "11->25_long": "B_14_15pt", "25->11_short": "B_14_15pt",
    "75->90_long": "B_14_15pt", "90->75_short": "B_14_15pt",
    # Group C — 10-11 pt
    "90->00_long": "C_10_11pt", "00->90_short": "C_10_11pt",
    "00->11_long": "C_10_11pt", "11->00_short": "C_10_11pt",
}


def assign_group(level_pair: str) -> str:
    return LEVEL_PAIR_TO_GROUP.get(level_pair, "OTHER")


# ---------------- Reporting ----------------

def _qrow(s: pd.Series, qs: tuple) -> dict:
    return {f"p{int(100*q):02d}": float(np.percentile(s, 100*q))
            for q in qs}


def aggregate(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0}
    n_win = int((df["outcome"] == "win").sum())
    n_loss = int((df["outcome"] == "loss").sum())
    n_to = int((df["outcome"] == "timed_out").sum())
    win_pnl = df.loc[df["outcome"] == "win", "pnl_pts"].sum()
    loss_pnl = df.loc[df["outcome"] == "loss", "pnl_pts"].sum()
    to_pnl = df.loc[df["outcome"] == "timed_out", "pnl_pts"].sum()
    gross = win_pnl + loss_pnl + to_pnl
    pf = ((win_pnl + max(0, to_pnl)) /
          abs(min(0, to_pnl) + loss_pnl)
          if (loss_pnl + min(0, to_pnl)) < 0 else float("inf"))
    return {
        "n": n,
        "wr": n_win / n,
        "loss_rate": n_loss / n,
        "to_rate": n_to / n,
        "pf": pf,
        "mean_pnl_pts": float(df["pnl_pts"].mean()),
        "mean_net_pts": float(df["pnl_net_pts"].mean()),
        "mean_pnl_dollars": float(df["pnl_dollars"].mean()),
        "total_pnl_dollars": float(df["pnl_dollars"].sum()),
        "mean_mae_pts": float(df["mae_pts"].mean()),
        "mean_mfe_pts": float(df["mfe_pts"].mean()),
    }


def per_outcome_excursion(df: pd.DataFrame, group_label: str,
                          year: int, session: str) -> list[dict]:
    """For each outcome bucket, compute MFE+MAE percentiles."""
    rows = []
    for oc in ("win", "loss", "timed_out"):
        sub = df[df["outcome"] == oc]
        if len(sub) == 0:
            continue
        rows.append({
            "year": year, "session": session, "group": group_label,
            "outcome": oc, "n": len(sub),
            "mfe_p25": float(np.percentile(sub["mfe_pts"], 25)),
            "mfe_p50": float(np.percentile(sub["mfe_pts"], 50)),
            "mfe_p75": float(np.percentile(sub["mfe_pts"], 75)),
            "mfe_p90": float(np.percentile(sub["mfe_pts"], 90)),
            "mae_p25": float(np.percentile(sub["mae_pts"], 25)),
            "mae_p50": float(np.percentile(sub["mae_pts"], 50)),
            "mae_p75": float(np.percentile(sub["mae_pts"], 75)),
            "mae_p90": float(np.percentile(sub["mae_pts"], 90)),
        })
    return rows


def print_summary(df: pd.DataFrame, label: str):
    s = aggregate(df)
    if s["n"] == 0:
        print(f"  {label:<48} | n=0")
        return
    print(f"  {label:<48} | n={s['n']:>5,} "
          f"| WR={100*s['wr']:>4.1f}% "
          f"| PF={s['pf']:>5.2f} "
          f"| net={s['mean_net_pts']:>+5.2f} pts "
          f"| ${s['mean_pnl_dollars']:>+7.2f}/tr "
          f"| total ${s['total_pnl_dollars']:>+10,.0f}")


def main():
    all_trades = []
    all_excursions = []

    for year in (2024, 2025):
        path = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
        print(f"\n{'='*78}\n[{year}] loading {path.name} ...")
        bars_1s = load_v0_1s(path)
        bars_1m = resample_1s_to_1m(bars_1s)
        bars_1m = annotate_sessions_ct(bars_1m)
        print(f"  bars_1m: {len(bars_1m):,}")

        triggers = detect_triggers_breakout(bars_1m)
        print(f"  triggers (bullish/bearish bar, open outside zone, "
              f"close inside): {len(triggers):,}")

        trades = run_chain(triggers, bars_1m)
        print(f"  trades (skip-while-open): {len(trades):,}")
        if len(trades) == 0:
            continue
        trades["year"] = year
        trades["group"] = trades["level_pair"].map(assign_group)
        all_trades.append(trades)

        # ----- per-session × per-group summary -----
        for sess in ("RTH", "ETH"):
            sub_sess = trades[trades["entry_session"] == sess]
            if len(sub_sess) == 0:
                continue
            print(f"\n[{year} | {sess}] (n={len(sub_sess):,})")
            print_summary(sub_sess, "ALL")

            for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
                gsub = sub_sess[sub_sess["group"] == grp]
                if len(gsub) == 0:
                    continue
                print_summary(gsub, f"  group {grp}")
                for di, dn in ((1, "long"), (-1, "short")):
                    dsub = gsub[gsub["direction"] == di]
                    print_summary(dsub, f"    {grp} {dn}")
                # Per-outcome excursion bucket
                all_excursions.extend(
                    per_outcome_excursion(gsub, grp, year, sess))

            # Other (any pair not in groups A/B/C — should be empty
            # given our level grid, but check)
            other = sub_sess[sub_sess["group"] == "OTHER"]
            if len(other) > 0:
                print_summary(other, "  group OTHER")

    if not all_trades:
        print("No trades.")
        return

    full = pd.concat(all_trades, ignore_index=True)
    full.to_parquet(OUT / "trades_breakout.parquet")
    print(f"\nSaved trades: {OUT / 'trades_breakout.parquet'} "
          f"(n={len(full):,})")

    # Excursion table
    exc = pd.DataFrame(all_excursions)
    exc.to_csv(OUT / "excursion_by_group_outcome.csv", index=False)
    print(f"Saved excursion table: "
          f"{OUT / 'excursion_by_group_outcome.csv'} (rows={len(exc)})")

    # ---------------- Excursion analysis printout ----------------
    print(f"\n{'='*78}\nMFE / MAE distribution by group × outcome "
          f"(for SL/PT tuning)")
    print("All values in points. Splits across both years × sessions.")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        gdf = full[full["group"] == grp]
        if len(gdf) == 0:
            continue
        print(f"\n[{grp}] n_total={len(gdf):,}")
        for oc in ("win", "loss", "timed_out"):
            sub = gdf[gdf["outcome"] == oc]
            if len(sub) == 0:
                continue
            mfe_p = np.percentile(sub["mfe_pts"], [25, 50, 75, 90, 95])
            mae_p = np.percentile(sub["mae_pts"], [25, 50, 75, 90, 95])
            print(f"  {oc:>10}: n={len(sub):>5,} "
                  f"| MFE p25/50/75/90/95: "
                  f"{mfe_p[0]:>5.2f}/{mfe_p[1]:>5.2f}/"
                  f"{mfe_p[2]:>5.2f}/{mfe_p[3]:>5.2f}/{mfe_p[4]:>5.2f} "
                  f"| MAE p25/50/75/90/95: "
                  f"{mae_p[0]:>5.2f}/{mae_p[1]:>5.2f}/"
                  f"{mae_p[2]:>5.2f}/{mae_p[3]:>5.2f}/{mae_p[4]:>5.2f}")


if __name__ == "__main__":
    main()
