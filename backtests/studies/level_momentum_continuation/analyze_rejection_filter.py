"""Identify characteristics of 'level rejection' trades — trades
that needed a wide cat-30 stop to save them or were the deep-MAE
winners that 'got lucky'.

Hypothesis: trades with a high MAE relative to their target gap
are not real continuations. They're brief level pokes followed by
rejection. If we can find features that distinguish them from
clean continuations, we can filter them out and improve R/R.

User's deep-MAE thresholds (by gap size):
  - Wide gaps (>=25 pt): MAE > 15 pt = "deep"
  - Narrow gaps (<=15 pt): MAE > 12 pt = "deep"

Categorization:
  - clean_win   : winner, MAE <= deep threshold
  - deep_win    : winner, MAE > deep threshold
  - cat_loss    : original loser (cat-30 territory) — never armed
                  BE, hit deep adverse zone
  - other_loss  : losers that DID arm BE-2.5 then stopped at BE
                  or that hit shallow MAE  (these are 'saveable'
                  with the BE rule)
  - timed_out

Features computed per trade:
  - close_dist_from_level  : how far past the level the close was
  - close_pos_in_zone      : (close - level) / (target - level)
                              0 = barely past, ~1 = touching target
  - trigger_bar_range_pts  : trigger bar's high - low
  - trigger_bar_close_pos  : where in the trigger bar the close
                              landed (0 = at low, 1 = at high; for
                              short = inverse so 1 = strong)
  - first_bar_range_pts
  - first_bar_close_move   : already have
  - hour_ct                : 0-23, time of trigger bar
  - is_round_level         : breach level == 0 or 50 in handle
  - is_breach_after_round  : breach level == 11 or 50 (right after
                              round)
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
)


V0_PARQUET = Path("data/raw/NQ_v0_1s_2025.parquet")
SOURCE = Path(
    "studies/level_momentum_continuation/results_nq_2025/"
    "trades_with_first_bar.csv")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")

# Deep MAE thresholds by gap size
DEEP_MAE_WIDE = 15.0      # for gap >= 25 pt
DEEP_MAE_NARROW = 12.0    # for gap < 25 pt
WIDE_GAP_THRESHOLD = 25.0


def gap_size(row) -> float:
    """Distance from breach level to next level (target+buffer)."""
    return float(row["next_level"]) - float(row["breach_level"])


def deep_mae_threshold(gap: float) -> float:
    return DEEP_MAE_WIDE if gap >= WIDE_GAP_THRESHOLD else DEEP_MAE_NARROW


def categorize(row, gap, threshold) -> str:
    if row["outcome"] == "win":
        return "deep_win" if row["mae_pts"] > threshold else "clean_win"
    if row["outcome"] == "timed_out":
        return "timed_out"
    # losers
    if row["mae_pts"] > threshold:
        return "cat_loss"
    return "other_loss"


def add_trigger_bar_features(trades, bars_1m):
    bars = bars_1m.reset_index(drop=False)
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    n = len(bars)

    out = trades.copy().reset_index(drop=True)
    eidx = out["entry_idx"].astype(int).values
    # Trigger bar = bar BEFORE entry
    tidx = eidx - 1
    valid = (tidx >= 0) & (tidx < n)
    if not valid.all():
        print(f"  WARN: {(~valid).sum()} trades with invalid "
              "trigger_idx (start-of-data)")

    trig_o = np.where(valid, opens[np.where(valid, tidx, 0)],
                            np.nan)
    trig_h = np.where(valid, highs[np.where(valid, tidx, 0)],
                            np.nan)
    trig_l = np.where(valid, lows[np.where(valid, tidx, 0)],
                            np.nan)
    trig_c = np.where(valid, closes[np.where(valid, tidx, 0)],
                            np.nan)

    out["trigger_open"] = trig_o
    out["trigger_high"] = trig_h
    out["trigger_low"] = trig_l
    out["trigger_close"] = trig_c
    out["trigger_range_pts"] = trig_h - trig_l

    # Close position within trigger bar (signed by trade direction)
    # 1 = closed at favorable extreme, 0 = unfavorable extreme
    d = out["direction"].astype(int).values
    rng = out["trigger_range_pts"].values
    rng_safe = np.where(rng > 0, rng, 1.0)
    out["trigger_close_pos"] = np.where(
        d == 1,
        (trig_c - trig_l) / rng_safe,    # long: 1=at high
        (trig_h - trig_c) / rng_safe,    # short: 1=at low
    )
    out["trigger_close_pos"] = np.where(
        rng > 0, out["trigger_close_pos"], 0.5)

    # Distance from level (signed favorable)
    # For long: close - level (+ = above level)
    # For short: level - close (+ = below level)
    out["close_dist_from_level"] = np.where(
        d == 1,
        out["close_at_breach"] - out["breach_level"],
        out["breach_level"] - out["close_at_breach"],
    )

    # Position in zone (toward target)
    target_dist = (out["target"] - out["breach_level"]).astype(float)
    target_dist = np.where(d == 1, target_dist, -target_dist)
    target_dist_safe = np.where(target_dist > 0, target_dist, 1.0)
    out["close_pos_in_zone"] = (
        out["close_dist_from_level"] / target_dist_safe)

    # First bar range
    out["first_bar_range_pts"] = (
        out["first_bar_high"] - out["first_bar_low"])

    # First bar close position (favorable extreme = 1)
    fb_rng = out["first_bar_range_pts"].values
    fb_rng_safe = np.where(fb_rng > 0, fb_rng, 1.0)
    out["first_bar_close_pos"] = np.where(
        d == 1,
        (out["first_bar_close"] - out["first_bar_low"])
            / fb_rng_safe,
        (out["first_bar_high"] - out["first_bar_close"])
            / fb_rng_safe,
    )

    # Hour of CT
    out["hour_ct"] = pd.to_datetime(
        out["trigger_ts_close"], utc=True
    ).dt.tz_convert("America/Chicago").dt.hour

    # Level features
    out["level_offset_in_handle"] = (
        out["breach_level"] % 100).astype(float)
    out["is_round_level"] = (
        out["level_offset_in_handle"].isin([0.0, 50.0]).astype(int))

    # Gap size and deep-MAE threshold
    out["gap_pts"] = (
        out["next_level"] - out["breach_level"])
    out["deep_mae_threshold"] = np.where(
        out["gap_pts"] >= WIDE_GAP_THRESHOLD,
        DEEP_MAE_WIDE, DEEP_MAE_NARROW)

    # Categorize each trade
    cats = []
    for i in range(len(out)):
        cats.append(categorize(out.iloc[i], out["gap_pts"].iloc[i],
                                      out["deep_mae_threshold"].iloc[i]))
    out["category"] = cats
    return out


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:.{dp}f}"


def feature_summary(trades, group_col, features):
    rows = []
    for keys, g in trades.groupby(group_col, observed=True):
        if not isinstance(keys, tuple): keys = (keys,)
        n = len(g)
        row = dict(zip([group_col] if isinstance(
            group_col, str) else group_col, keys))
        row["n"] = n
        for f in features:
            v = g[f].dropna()
            if len(v) == 0:
                row[f"{f}_mean"] = float("nan")
                row[f"{f}_p50"] = float("nan")
                row[f"{f}_p25"] = float("nan")
                row[f"{f}_p75"] = float("nan")
            else:
                row[f"{f}_mean"] = float(v.mean())
                row[f"{f}_p50"] = float(np.percentile(v, 50))
                row[f"{f}_p25"] = float(np.percentile(v, 25))
                row[f"{f}_p75"] = float(np.percentile(v, 75))
        rows.append(row)
    return pd.DataFrame(rows)


def write_report(trades, summary_overall, summary_by_pair_session,
                       feature_corr_with_loss):
    L = []
    L.append("# Rejection-Filter Analysis "
              "— Level Momentum Study\n")
    L.append("## Definitions\n")
    L.append(
        "Categorize each trade by gap size and MAE:\n"
        f"- Wide gaps (>= {WIDE_GAP_THRESHOLD} pt): "
        f"deep MAE = > {DEEP_MAE_WIDE} pt\n"
        f"- Narrow gaps (< {WIDE_GAP_THRESHOLD} pt): "
        f"deep MAE = > {DEEP_MAE_NARROW} pt\n\n"
        "Categories:\n"
        "- **clean_win**: winner with MAE <= deep threshold "
        "(low-stress wins)\n"
        "- **deep_win**: winner with MAE > deep threshold "
        "('lucky' wins that drew down deep)\n"
        "- **cat_loss**: loser with MAE > deep threshold "
        "(would have hit cat-30 territory)\n"
        "- **other_loss**: loser with MAE <= deep threshold "
        "(would have BE-stopped or hit a tight stop)\n"
        "- **timed_out**: time limit reached\n\n"
        "Question: do `deep_win` and `cat_loss` share features "
        "that distinguish them from `clean_win`? If yes, "
        "we can filter them out at trigger time.\n")

    L.append("## Category sizes (overall)\n")
    counts = trades["category"].value_counts()
    L.append("| Category | n | % |")
    L.append("|---|--:|--:|")
    for cat, n in counts.items():
        L.append(f"| {cat} | {n:,} | "
                  f"{fmt_p(n / len(trades))} |")
    L.append("")

    L.append("## Feature distributions by category (overall)\n")
    L.append("Means with [p25, p75] for context.\n")
    features = ["close_dist_from_level", "close_pos_in_zone",
                  "trigger_range_pts", "trigger_close_pos",
                  "first_bar_range_pts", "first_bar_close_pos",
                  "first_bar_close_move_pts",
                  "atr_at_signal" if "atr_at_signal" in trades.columns
                    else "trigger_range_pts"]
    features = list(dict.fromkeys(
        f for f in features if f in trades.columns))
    L.append("| Category | n | " + " | ".join(features) + " |")
    L.append("|---" * (len(features) + 2) + "|")
    for cat, g in trades.groupby("category", observed=True):
        cells = [cat, f"{len(g):,}"]
        for f in features:
            v = g[f].dropna()
            if len(v) == 0:
                cells.append("—")
            else:
                m = v.mean()
                p25 = np.percentile(v, 25)
                p75 = np.percentile(v, 75)
                cells.append(
                    f"{m:.2f} [{p25:.2f},{p75:.2f}]")
        L.append("| " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Comparison: clean_win vs deep_win vs cat_loss\n")
    L.append("Side-by-side means for the three key categories.\n")
    L.append("| Feature | clean_win | deep_win | cat_loss | "
             "Δ (cat - clean) | Δ (deep - clean) |")
    L.append("|---|--:|--:|--:|--:|--:|")
    means = {}
    for cat in ["clean_win", "deep_win", "cat_loss"]:
        g = trades[trades["category"] == cat]
        means[cat] = {f: float(g[f].dropna().mean())
                          for f in features}
    for f in features:
        cw = means["clean_win"][f]
        dw = means["deep_win"][f]
        cl = means["cat_loss"][f]
        L.append(
            f"| {f} | {cw:.3f} | {dw:.3f} | {cl:.3f} | "
            f"{cl - cw:+.3f} | {dw - cw:+.3f} |")
    L.append("")

    L.append("## By gap-size class\n")
    for gap_class, label in [
            ("wide", f">= {WIDE_GAP_THRESHOLD}pt gaps"),
            ("narrow", f"< {WIDE_GAP_THRESHOLD}pt gaps")]:
        if gap_class == "wide":
            sub = trades[trades["gap_pts"] >= WIDE_GAP_THRESHOLD]
        else:
            sub = trades[trades["gap_pts"] < WIDE_GAP_THRESHOLD]
        L.append(f"### {label}\n")
        counts = sub["category"].value_counts()
        L.append("| Category | n | % |")
        L.append("|---|--:|--:|")
        for cat in ["clean_win", "deep_win", "other_loss",
                       "cat_loss", "timed_out"]:
            n = counts.get(cat, 0)
            L.append(f"| {cat} | {n:,} | "
                      f"{fmt_p(n / max(len(sub), 1))} |")
        L.append("")
        # Means by category for this gap class
        L.append("| Category | "
                  + " | ".join(features) + " |")
        L.append("|---" * (len(features) + 1) + "|")
        for cat in ["clean_win", "deep_win", "cat_loss"]:
            g = sub[sub["category"] == cat]
            cells = [cat]
            for f in features:
                v = g[f].dropna()
                if len(v) == 0:
                    cells.append("—")
                else:
                    cells.append(f"{v.mean():.3f}")
            L.append("| " + " | ".join(cells) + " |")
        L.append("")

    L.append("## Hour-of-CT distribution by category\n")
    L.append("(% of category falling in each hour bucket; helps "
              "identify time-of-day filters)\n")
    L.append("| Category | "
              + " | ".join(f"h{h:02d}" for h in range(24))
              + " |")
    L.append("|---" * 25 + "|")
    for cat in ["clean_win", "deep_win", "cat_loss"]:
        g = trades[trades["category"] == cat]
        n = len(g)
        if n == 0: continue
        cells = [cat]
        for h in range(24):
            pct = float((g["hour_ct"] == h).mean())
            cells.append(f"{100*pct:.1f}%")
        L.append("| " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Round-level breakdown\n")
    L.append("Round = breach at .00 or .50 within handle.\n")
    L.append("| Category | round n | round % | non-round n | "
             "non-round % |")
    L.append("|---|--:|--:|--:|--:|")
    for cat in ["clean_win", "deep_win", "cat_loss",
                  "other_loss", "timed_out"]:
        g = trades[trades["category"] == cat]
        if len(g) == 0: continue
        rn = int(g["is_round_level"].sum())
        nrn = len(g) - rn
        L.append(
            f"| {cat} | {rn:,} | "
            f"{fmt_p(rn/len(g))} | "
            f"{nrn:,} | {fmt_p(nrn/len(g))} |")
    L.append("")

    p = OUT / "report_rejection_filter.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")
    print("Reloading bars...")
    bars_1s = load_v0_1s(V0_PARQUET)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)

    print("Computing trigger-bar + categorical features...")
    trades_aug = add_trigger_bar_features(trades, bars_1m)
    trades_aug.to_csv(OUT / "trades_with_features.csv",
                              index=False)

    counts = trades_aug["category"].value_counts()
    print("\nCategory sizes:")
    for cat, n in counts.items():
        print(f"  {cat}: {n:,} ({100*n/len(trades_aug):.1f}%)")

    print("\nWriting report...")
    rp = write_report(trades_aug, None, None, None)
    print(f"Report: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
