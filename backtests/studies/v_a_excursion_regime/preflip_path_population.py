"""Pre-flip T-1 path-population study (base rates, no model).

Universe: every on-stream T-1 candidate (live feature log, 2020-2026).
Each candidate is a 1m bar at whose CLOSE the live strategy would
decide to enter in intended direction d.  close_ts_ns = that close
= the flip bar's open.

Classify each candidate by what the 1m regime actually did:
  A  raw 1m regime flip TO d at the flip bar  AND bar1 V_A confirm
  B  raw 1m regime flip TO d at the flip bar  AND bar1 confirm fails
  C  no raw 1m regime flip TO d               (contamination cohort)

Then measure the forward 1s price path from the T-1 entry fill (open
of the 1s bar at close_ts_ns): first-touch race of +X ATR (favorable)
vs -Y ATR (adverse) within N 1m bars.

Target pairs : +0.5/-0.5  +1.0/-1.0  +1.0/-1.5  +1.5/-1.0  (ATR units)
Windows      : 3 / 5 / 10  1m bars
Ambiguity    : both targets inside one 1s OHLC -> adverse (conservative)
ATR          : Wilder RMA(14) on 1m bars, value at the T-1 bar.

No commission, no spread, no model.  Raw price-path base rates only —
the gate for whether a continuation model is worth training.
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

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from rolling_train import build_1m_bars, compute_1m_regime

NS = 1_000_000_000
FEAT_LOG = Path("studies/v_a_excursion_regime/results_v0/live_feature_log")
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OUT = Path("studies/v_a_excursion_regime/results_v0")

ATR_PERIOD = 14
PAIRS = [(0.5, 0.5), (1.0, 1.0), (1.0, 1.5), (1.5, 1.0)]
WINDOWS = [3, 5, 10]            # 1m bars
MAX_WIN = max(WINDOWS)
ENTRY_SNAP_NS = 5 * NS          # accept entry 1s bar up to 5s after cts
INF = np.iinfo(np.int64).max


def wilder_atr(one_m, period=ATR_PERIOD):
    h = one_m["high"].to_numpy()
    l = one_m["low"].to_numpy()
    c = one_m["close"].to_numpy()
    pc = np.empty_like(c); pc[0] = c[0]; pc[1:] = c[:-1]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()


def classify_candidates(df):
    """Add pop (A/B/C), flip, confirm, atr_1m to the candidate frame."""
    bars1m = {}
    for y in range(2020, 2027):
        try:
            bars1m[y] = build_1m_bars(y)
        except FileNotFoundError:
            pass
    one_m = pd.concat(bars1m.values()).sort_index()
    one_m = one_m[~one_m.index.duplicated(keep="first")]
    om_ts = one_m.index.values.astype(np.int64)
    om_h, om_l = one_m["high"].values, one_m["low"].values
    om_o, om_c = one_m["open"].values, one_m["close"].values
    om_reg = compute_1m_regime(one_m)
    om_atr = wilder_atr(one_m)
    idx = {int(t): i for i, t in enumerate(om_ts)}

    flip = np.zeros(len(df), dtype=bool)
    confirm = np.zeros(len(df), dtype=bool)
    atr = np.full(len(df), np.nan)
    for k in range(len(df)):
        cts = int(df["close_ts_ns"].iat[k])
        d = int(df["direction"].iat[k])
        fb = idx.get(cts, -1)             # flip bar opens at cts
        tm1 = idx.get(cts - 60 * NS, -1)  # T-1 bar (decision bar)
        if tm1 >= ATR_PERIOD:
            atr[k] = om_atr[tm1]
        if fb < 1:
            continue
        flip_to_d = (om_reg[fb] == d and om_reg[fb] != 0
                     and om_reg[fb - 1] != 0
                     and om_reg[fb] != om_reg[fb - 1])
        if not flip_to_d:
            continue
        flip[k] = True
        b1 = idx.get(cts + 60 * NS, -1)
        if b1 < 0:
            continue
        if d == 1:
            confirm[k] = om_h[b1] > om_h[fb] and om_c[b1] > om_o[b1]
        else:
            confirm[k] = om_l[b1] < om_l[fb] and om_c[b1] < om_o[b1]

    df["flip"] = flip
    df["confirm"] = confirm
    df["atr_1m"] = atr
    df["pop"] = np.where(~flip, "C",
                         np.where(confirm, "A", "B"))
    return df


def measure_paths(df):
    """First-touch favorable/adverse offsets (ns from cts) per pair."""
    n = len(df)
    ft = {p: np.full(n, INF, dtype=np.int64) for p in PAIRS}
    at = {p: np.full(n, INF, dtype=np.int64) for p in PAIRS}
    entry_ok = np.zeros(n, dtype=bool)
    entry_px = np.full(n, np.nan)

    for year in sorted(df["year"].unique()):
        ypath = ONE_S.get(int(year))
        if ypath is None or not Path(ypath).exists():
            continue
        s = pd.read_parquet(ypath, columns=["open", "high", "low"])
        sts = pd.to_datetime(s.index, utc=True).view("int64")
        order = np.argsort(sts, kind="stable")
        sts = sts[order]
        so = s["open"].to_numpy()[order]
        sh = s["high"].to_numpy()[order]
        sl = s["low"].to_numpy()[order]

        ymask = np.where(df["year"].to_numpy() == year)[0]
        for k in ymask:
            cts = int(df["close_ts_ns"].iat[k])
            d = int(df["direction"].iat[k])
            a = df["atr_1m"].iat[k]
            if not np.isfinite(a) or a <= 0:
                continue
            e = np.searchsorted(sts, cts)
            if e >= len(sts) or sts[e] - cts > ENTRY_SNAP_NS:
                continue
            E = so[e]
            entry_ok[k] = True
            entry_px[k] = E
            w = np.searchsorted(sts, cts + MAX_WIN * 60 * NS)
            seg_h = sh[e:w]; seg_l = sl[e:w]; seg_ts = sts[e:w]
            if len(seg_ts) == 0:
                continue
            for (X, Y) in PAIRS:
                if d == 1:
                    fav = seg_h >= E + X * a
                    adv = seg_l <= E - Y * a
                else:
                    fav = seg_l <= E - X * a
                    adv = seg_h >= E + Y * a
                if fav.any():
                    ft[(X, Y)][k] = seg_ts[fav.argmax()] - cts
                if adv.any():
                    at[(X, Y)][k] = seg_ts[adv.argmax()] - cts

    df["entry_ok"] = entry_ok
    df["entry_px"] = entry_px
    for p in PAIRS:
        tag = f"{p[0]}_{p[1]}"
        df[f"ft_{tag}"] = ft[p]
        df[f"at_{tag}"] = at[p]
    return df


def outcome(df, pair, win_bars):
    """Return Series of 'win'/'loss'/'neither'/'na' per candidate."""
    tag = f"{pair[0]}_{pair[1]}"
    ft = df[f"ft_{tag}"].to_numpy()
    at = df[f"at_{tag}"].to_numpy()
    limit = win_bars * 60 * NS
    res = np.full(len(df), "na", dtype=object)
    ok = df["entry_ok"].to_numpy()
    earlier = np.minimum(ft, at)
    res[ok & (earlier > limit)] = "neither"
    # adverse ties (at <= ft) within window -> loss (conservative)
    in_win = ok & (earlier <= limit)
    res[in_win & (at <= ft)] = "loss"
    res[in_win & (ft < at)] = "win"
    return pd.Series(res, index=df.index)


def wr_table(df, pair, win_bars, group_cols):
    rows = []
    oc = outcome(df, pair, win_bars)
    for keys, sub in df.groupby(group_cols):
        o = oc.loc[sub.index]
        valid = o[o != "na"]
        n = len(valid)
        if n == 0:
            continue
        w = (valid == "win").mean()
        l = (valid == "loss").mean()
        nn = (valid == "neither").mean()
        if not isinstance(keys, tuple):
            keys = (keys,)
        rows.append((*keys, n, w, l, nn))
    return rows


def main():
    t0 = time.time()
    logs = sorted(FEAT_LOG.glob("feat_*.parquet"))
    parts = []
    for p in logs:
        d = pd.read_parquet(p, columns=["close_ts_ns", "direction"])
        d["year"] = int(p.stem.split("_")[1])
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    print(f"T-1 candidates (live feature log): {len(df):,}  "
          f"{df['year'].min()}-{df['year'].max()}")

    print("Classifying flip / confirm / ATR ...")
    df = classify_candidates(df)
    print("Measuring 1s forward paths ...")
    df = measure_paths(df)

    miss_atr = (~np.isfinite(df["atr_1m"])).sum()
    miss_entry = (~df["entry_ok"]).sum()
    print(f"  no ATR: {miss_atr:,}   no entry 1s bar: {miss_entry:,}")

    POPN = {"A": "A flip+confirm", "B": "B flip,no-conf",
            "C": "C no-flip"}
    DIRN = {1: "long", -1: "short"}
    df["dir"] = df["direction"].map(DIRN)

    # --- population sizes ---
    print(f"\n{'='*68}\nPOPULATION SIZES\n{'='*68}")
    piv = df.pivot_table(index="dir", columns="pop", values="close_ts_ns",
                         aggfunc="count", fill_value=0)
    piv["total"] = piv.sum(axis=1)
    print(piv.to_string())
    flip_rate = df["flip"].mean()
    conf_of_flip = df.loc[df["flip"], "confirm"].mean()
    print(f"\noverall: raw-flip rate {flip_rate:.1%}   "
          f"bar1-confirm rate among flips {conf_of_flip:.1%}")
    print(f"\nby year  (raw-flip% / confirm%-among-flips):")
    for y, g in df.groupby("year"):
        fr = g["flip"].mean()
        cr = g.loc[g["flip"], "confirm"].mean() if g["flip"].any() else 0
        print(f"  {y}: n={len(g):>7,}  flip={fr:5.1%}  confirm={cr:5.1%}")

    # --- first-touch win rates, window = 5 bars, by pop x dir ---
    for win in WINDOWS:
        print(f"\n{'='*68}")
        print(f"FIRST-TOUCH RACE  —  window = {win} 1m bars")
        print(f"{'='*68}")
        for pair in PAIRS:
            print(f"\n  target +{pair[0]} / -{pair[1]} ATR")
            print(f"  {'pop':<16}{'dir':<7}{'n':>8}{'win%':>9}"
                  f"{'loss%':>9}{'neither%':>10}")
            rows = wr_table(df, pair, win, ["pop", "dir"])
            for pop, dr, n, w, l, nn in sorted(rows):
                print(f"  {POPN[pop]:<16}{dr:<7}{n:>8,}{w:>8.1%}"
                      f"{l:>9.1%}{nn:>9.1%}")
            # all-flip (A+B) and all-candidate aggregate
            for label, mask in [("all flips (A+B)", df["flip"]),
                                ("ALL candidates",
                                 pd.Series(True, index=df.index))]:
                sub = df[mask]
                oc = outcome(sub, pair, win)
                for dr in ("long", "short"):
                    o = oc[sub["dir"] == dr]
                    o = o[o != "na"]
                    if len(o) == 0:
                        continue
                    print(f"  {label:<16}{dr:<7}{len(o):>8,}"
                          f"{(o=='win').mean():>8.1%}"
                          f"{(o=='loss').mean():>9.1%}"
                          f"{(o=='neither').mean():>9.1%}")

    # --- headline +1/-1, window 5, by year x pop x dir ---
    print(f"\n{'='*68}")
    print(f"HEADLINE  +1.0/-1.0 ATR, window 5 bars  —  by year")
    print(f"{'='*68}")
    for pop in ("A", "B", "C"):
        print(f"\n  {POPN[pop]}")
        print(f"  {'year':<7}{'long n':>9}{'long win%':>11}"
              f"{'short n':>10}{'short win%':>12}")
        sub = df[df["pop"] == pop]
        oc = outcome(sub, (1.0, 1.0), 5)
        for y, g in sub.groupby("year"):
            o = oc.loc[g.index]
            cells = []
            for dr in ("long", "short"):
                od = o[(g["dir"] == dr).values]
                od = od[od != "na"]
                cells.append((len(od),
                              (od == "win").mean() if len(od) else
                              float("nan")))
            print(f"  {y:<7}{cells[0][0]:>9,}{cells[0][1]:>10.1%}"
                  f"{cells[1][0]:>10,}{cells[1][1]:>11.1%}")

    keep = (["close_ts_ns", "direction", "dir", "year", "pop", "flip",
             "confirm", "atr_1m", "entry_ok", "entry_px"]
            + [c for c in df.columns
               if c.startswith("ft_") or c.startswith("at_")])
    outp = OUT / "preflip_path_population.parquet"
    df[keep].to_parquet(outp, index=False)
    print(f"\n[done] {time.time()-t0:.0f}s  ->  {outp}")


if __name__ == "__main__":
    main()
