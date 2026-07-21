"""5-second microstructure features for NT 1m regime flips.

Hypothesis: discretionary "the move is building underneath the 1m candle"
intuition might be capturable via 5s-timeframe regime structure in the
2m / 5m / 10m before a 1m flip. Tests whether organized 5s microstructure
(low churn, longer 5s runs, last 5s flip already aligned) precedes
1m flips that PAY (hit +1 ATR before -1 ATR) more often than 1m flips
that DON'T pay.

NOT a 5s strategy. An additive diagnostic on the deployable 1m flip
universe (NT-detected, 166K flips 2020-2026 — not v2's filtered set).

Discipline:
  - Same regime rule (EMA3/9 sticky on highs/lows) applied to 5s bars
  - Features per flip computed over 2m / 5m / 10m lookback (causal)
  - Cohorts: A = NT flip wins +1ATR, B = loses
  - Univariate AUC per feature, IS (2020-2022) and OOS (2023-2026)
  - If any feature has stable IS+OOS AUC > 0.55, decision-tree split
    on the top 2-3 features to find a simple filter rule.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from numba import njit
from sklearn.metrics import roc_auc_score

NS = 1_000_000_000
PERIOD_5S_NS = 5 * NS
ATR_PERIOD_1M = 14
ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2

PRODUCT_DATA = {
    "NQ": {"one_s": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
                         for y in range(2019, 2026)},
                     2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
            "trades": "backtests/baseline_flip_parity/results/nq_live_{}/trades.parquet",
            "out_suffix": "nq"},
    "ES": {"one_s": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                         for y in range(2019, 2026)},
                     2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
            "trades": "backtests/baseline_flip_parity/results/es_live_{}/trades.parquet",
            "out_suffix": "es"},
}
PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PD = PRODUCT_DATA[PRODUCT]
ONE_S = PD["one_s"]
NT_TRADES = PD["trades"]
OUT = Path("studies/v_a_excursion_regime/results_v0")

IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)


def aggregate_5s(bars_1s):
    """Epoch-floor 1s bars to 5s buckets. Returns DataFrame indexed by
    5s bucket start (ns), columns: open, high, low, close."""
    ts = bars_1s.index.values.astype(np.int64)
    bucket = (ts // PERIOD_5S_NS) * PERIOD_5S_NS
    g = pd.DataFrame({
        "b": bucket,
        "o": bars_1s["open"].values,
        "h": bars_1s["high"].values,
        "l": bars_1s["low"].values,
        "c": bars_1s["close"].values})
    return g.groupby("b").agg(
        o=("o", "first"), h=("h", "max"),
        l=("l", "min"), c=("c", "last"))


@njit
def compute_5s_regime(h5, l5, c5):
    """Sticky EMA3/9 regime on 5s bars. Returns regime array."""
    n = len(c5)
    reg = np.zeros(n, dtype=np.int64)
    e3h = e9h = e3l = e9l = 0.0
    cur = 0
    for i in range(n):
        if i == 0:
            e3h = h5[i]; e9h = h5[i]; e3l = l5[i]; e9l = l5[i]
        else:
            e3h = ALPHA_EMA3 * h5[i] + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * h5[i] + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * l5[i] + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * l5[i] + (1.0 - ALPHA_EMA9) * e9l
        new_reg = cur
        if c5[i] > e3h and c5[i] > e9h:
            new_reg = 1
        elif c5[i] < e3l and c5[i] < e9l:
            new_reg = -1
        reg[i] = new_reg
        cur = new_reg
    return reg


@njit
def compute_features_for_window(entry_ts, signal_dir, ts5, reg5,
                                  o5, h5, l5, win_ns):
    """Compute 5s microstructure features for one (entry_ts, window).

    Returns:
      n_flips      — regime transitions (non-zero to different non-zero) in window
      max_run      — longest consecutive bars in a single regime
      pct_in_dir   — fraction of 5s bars in flip direction (signed)
      last_dir     — regime of the LAST 5s bar before entry_ts
      ts_since_last_flip — seconds from last regime transition to entry_ts
      churn        — n_flips per minute of window
      persistence  — max_run / window_bars
      excursion    — (max_high - min_low) over window in PRICE points
      range_atr    — (max_high - min_low) over window — caller normalizes
      aligned_at_entry — 1 if last_dir == signal_dir, 0 otherwise
    """
    i_lo = np.searchsorted(ts5, entry_ts - win_ns, side="left")
    i_hi = np.searchsorted(ts5, entry_ts, side="left")  # exclusive
    if i_hi <= i_lo + 5:
        return (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan,
                np.nan, np.nan, np.nan, np.nan)
    seg = reg5[i_lo:i_hi]
    seg_ts = ts5[i_lo:i_hi]
    seg_h = h5[i_lo:i_hi]
    seg_l = l5[i_lo:i_hi]

    # n_flips and max_run
    n_flips = 0
    last_transition_idx = -1
    cur_run = 1
    max_run = 1
    for q in range(1, len(seg)):
        if seg[q] != seg[q - 1]:
            if seg[q] != 0 and seg[q - 1] != 0:
                n_flips += 1
                last_transition_idx = q
            cur_run = 1
        else:
            cur_run += 1
        if cur_run > max_run:
            max_run = cur_run

    # pct_in_dir
    in_dir_count = 0
    for q in range(len(seg)):
        if seg[q] == signal_dir:
            in_dir_count += 1
    pct_in_dir = in_dir_count / len(seg)

    # last_dir = regime of last bar in window
    last_dir = seg[-1]

    # ts_since_last_flip
    if last_transition_idx >= 0:
        ts_since_last_flip = (entry_ts - seg_ts[last_transition_idx]) / NS
    else:
        ts_since_last_flip = (entry_ts - seg_ts[0]) / NS  # no flip in window

    minutes = win_ns / (60 * NS)
    churn = n_flips / minutes if minutes > 0 else 0.0
    persistence = max_run / len(seg)

    excursion = np.max(seg_h) - np.min(seg_l)
    aligned = 1.0 if last_dir == signal_dir else 0.0
    return (float(n_flips), float(max_run), float(pct_in_dir),
            float(last_dir), float(ts_since_last_flip),
            float(churn), float(persistence),
            float(excursion), float(excursion),  # raw + atr-normalized later
            float(aligned))


def compute_year(year, nt_flips_year):
    """Compute 5s microstructure features for one year of NT flips."""
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")

    five_s = aggregate_5s(bars)
    ts5 = five_s.index.values.astype(np.int64)
    o5 = five_s["o"].to_numpy(np.float64)
    h5 = five_s["h"].to_numpy(np.float64)
    l5 = five_s["l"].to_numpy(np.float64)
    c5 = five_s["c"].to_numpy(np.float64)
    reg5 = compute_5s_regime(h5, l5, c5)

    ets = nt_flips_year["entry_ts"].to_numpy(np.int64)
    dr  = nt_flips_year["signal_direction"].to_numpy(np.int64)
    at  = nt_flips_year["entry_atr"].to_numpy(np.float64)
    n = len(nt_flips_year)
    windows = [("2m", 2 * 60 * NS), ("5m", 5 * 60 * NS), ("10m", 10 * 60 * NS)]
    feat_names = ["nflips", "maxrun", "pctdir", "lastdir", "tslast",
                  "churn", "persist", "excur", "excur2", "aligned"]
    cols = {}
    for wn, _ in windows:
        for fn in feat_names:
            cols[f"{fn}_{wn}"] = np.full(n, np.nan)

    for k in range(n):
        T = int(ets[k]); d = int(dr[k]); atr = float(at[k])
        for wn, wns in windows:
            r = compute_features_for_window(T, d, ts5, reg5, o5, h5, l5,
                                              wns)
            (nflips, maxrun, pctdir, lastdir, tslast,
             churn, persist, excur, excur2, aligned) = r
            cols[f"nflips_{wn}"][k]  = nflips
            cols[f"maxrun_{wn}"][k]  = maxrun
            cols[f"pctdir_{wn}"][k]  = pctdir
            cols[f"lastdir_{wn}"][k] = lastdir
            cols[f"tslast_{wn}"][k]  = tslast
            cols[f"churn_{wn}"][k]   = churn
            cols[f"persist_{wn}"][k] = persist
            cols[f"excur_{wn}"][k]   = excur
            # ATR-normalized excursion
            cols[f"excur2_{wn}"][k]  = excur / atr if atr > 0 else np.nan
            cols[f"aligned_{wn}"][k] = aligned

    out = pd.DataFrame(cols, index=nt_flips_year.index)
    return out


def report_univariate(df):
    """For each 5s feature, compute IS and OOS AUC vs win/loss outcome."""
    res = df[df["exit_reason"].isin(["T", "SL"])].copy()
    res["win"] = (res["exit_reason"] == "T").astype(int)
    is_set  = res[res["year"].isin(IS_YEARS)]
    oos_set = res[res["year"].isin(OOS_YEARS)]
    feat_cols = [c for c in df.columns if any(c.endswith(f"_{w}")
                  for w in ("2m", "5m", "10m"))]
    print(f"\n{'='*78}")
    print(f"UNIVARIATE 5s MICROSTRUCTURE AUC (target = win/loss)")
    print(f"{'='*78}")
    print(f"  {'feature':<24}{'IS n':>8}{'IS AUC':>10}{'IS win%':>10}"
          f"{'OOS n':>8}{'OOS AUC':>10}{'OOS win%':>10}{'flag':>6}")
    rows = []
    for c in feat_cols:
        is_s = is_set.dropna(subset=[c])
        oos_s = oos_set.dropna(subset=[c])
        if len(is_s) < 100 or is_s["win"].nunique() < 2 \
                or len(oos_s) < 100 or oos_s["win"].nunique() < 2:
            continue
        is_auc = roc_auc_score(is_s["win"], is_s[c])
        oos_auc = roc_auc_score(oos_s["win"], oos_s[c])
        flag = ""
        if abs(is_auc - 0.5) > 0.03 and abs(oos_auc - 0.5) > 0.03:
            if (is_auc - 0.5) * (oos_auc - 0.5) > 0:  # same sign
                flag = "**"
        rows.append((c, len(is_s), is_auc, is_s["win"].mean(),
                     len(oos_s), oos_auc, oos_s["win"].mean(), flag))
    # sort by max |OOS AUC - 0.5|
    rows.sort(key=lambda r: -abs(r[5] - 0.5))
    for r in rows:
        print(f"  {r[0]:<24}{r[1]:>8,}{r[2]:>9.4f}{r[3]:>10.1%}"
              f"{r[4]:>8,}{r[5]:>9.4f}{r[6]:>10.1%}{r[7]:>6}")
    return rows


def report_cohort_means(df):
    """Mean of each 5s feature for win vs loss cohorts (OOS only)."""
    res = df[df["exit_reason"].isin(["T", "SL"]) &
              df["year"].isin(OOS_YEARS)].copy()
    res["win"] = (res["exit_reason"] == "T").astype(int)
    feat_cols = [c for c in df.columns if any(c.endswith(f"_{w}")
                  for w in ("2m", "5m", "10m"))]
    print(f"\n{'='*78}")
    print(f"COHORT MEANS — OOS (2023-2026) WIN vs LOSS")
    print(f"{'='*78}")
    print(f"  {'feature':<24}{'win mean':>12}{'loss mean':>12}"
          f"{'delta':>10}{'n_win':>8}{'n_loss':>8}")
    win_set = res[res["win"] == 1]
    los_set = res[res["win"] == 0]
    for c in feat_cols:
        wm = win_set[c].mean(); lm = los_set[c].mean()
        print(f"  {c:<24}{wm:>12.3f}{lm:>12.3f}{wm-lm:>+10.3f}"
              f"{win_set[c].notna().sum():>8,}{los_set[c].notna().sum():>8,}")


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    print("Loading NT flips ...")
    parts = []
    for y in range(2020, 2027):
        p = Path(NT_TRADES.format(y))
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d["year"] = y
        parts.append(d)
    nt = pd.concat(parts, ignore_index=True).sort_values("entry_ts"
                                                          ).reset_index(drop=True)
    nt["entry_ts"] = nt["entry_ts"].astype(np.int64)
    nt["signal_direction"] = nt["signal_direction"].astype(np.int64)
    print(f"  {len(nt):,} flips")

    print("Computing 5s microstructure features per year ...")
    feat_parts = []
    for y in sorted(nt["year"].unique()):
        sub = nt[nt["year"] == y]
        t1 = time.time()
        feats = compute_year(int(y), sub)
        feat_parts.append(feats)
        print(f"  {y}: {len(sub):,} flips  ({time.time()-t1:.0f}s)")
    feats = pd.concat(feat_parts)
    df = pd.concat([nt, feats], axis=1)

    out_p = OUT / f"nt_5s_microstructure_{PD['out_suffix']}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"  saved {out_p}  (PRODUCT={PRODUCT})")

    report_univariate(df)
    report_cohort_means(df)

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
