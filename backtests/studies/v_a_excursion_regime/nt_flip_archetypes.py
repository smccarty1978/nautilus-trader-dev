"""Archetype rebuild on the FULL NT flip universe.

Replaces the prior `archetype_study.py` which was built on v2's filtered
universe (proven to be ~10pp biased via NT parity test). Here we:

1. Load NT-detected flips from `backtests/baseline_flip_parity/results/
   live_<year>/trades.parquet` for all 7 years (2020-2026). The strategy
   enters on EVERY 1m regime flip (long and short), so this is the
   deployable universe.
2. Compute archetype features causally at each NT entry_ts:
     - VWAP / sigma (session-anchored, 17:00 CT reset)
     - vwap_z, vwap_z_dir
     - flip-bar OHLC pattern: flip_close_location, flip_range_atr
     - rolling 30m compression: tot_slow
     - recent flip count (last 30/60 min)
     - consecutive trend bars pre-flip
     - prior-day RTH H/L, overnight ETH H/L (distances in ATR)
     - time bucket: in_rth, in_opening (09:30-10:30 ET)
3. Apply the same archetype + cleanliness booleans as `archetype_study.py`.
4. Report win rates per cell against the NT 50% base, year-by-year,
   IS (2020-2022) vs OOS (2023-2026).

Outcome is already in NT trades.parquet (exit_reason ∈ {T, SL, max_hold}).
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
import pytz
from numba import njit

NS = 1_000_000_000
ET = pytz.timezone("America/New_York")
ATR_PERIOD = 14
ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2
RTH_START_ET = (9 * 3600) + (30 * 60)
RTH_END_ET   = 16 * 3600
OPEN_END_ET  = (10 * 3600) + (30 * 60)

# Archetype thresholds (same as before)
NEAR_VWAP_Z = 1.0
STRETCHED_VWAP_Z = 2.0
STRICT_LEVEL_ATR = 0.25
VICINITY_LEVEL_ATR = 1.0
CHOP_MIN_FLIPS_30M = 4
VOL_EXPAND_RATIO = 1.2

# Cleanliness thresholds
CLEAN_MAX_FLIPS_30M    = 2
CLEAN_MIN_CONSEC_TREND = 2
CLEAN_MIN_CLOSE_LOC    = 0.75
CLEAN_MIN_RANGE_ATR    = 1.0

IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)

PRODUCT_DATA = {
    "NQ": {
        "one_s": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
                      for y in range(2019, 2026)},
                  2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
        "trades": "backtests/baseline_flip_parity/results/nq_live_{}/trades.parquet",
        "out_suffix": "nq",
    },
    "ES": {
        "one_s": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                      for y in range(2019, 2026)},
                  2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
        "trades": "backtests/baseline_flip_parity/results/es_live_{}/trades.parquet",
        "out_suffix": "es",
    },
}
PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PD = PRODUCT_DATA[PRODUCT]
ONE_S = PD["one_s"]
NT_TRADES = PD["trades"]
OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_nt_flips():
    parts = []
    for y in range(2020, 2027):
        p = Path(NT_TRADES.format(y))
        if not p.exists():
            print(f"  WARN: no trades.parquet for {y}")
            continue
        df = pd.read_parquet(p)
        df["year"] = y
        parts.append(df)
    out = pd.concat(parts, ignore_index=True)
    out["entry_ts"] = out["entry_ts"].astype(np.int64)
    out["signal_direction"] = out["signal_direction"].astype(np.int64)
    return out


@njit
def compute_1m_state(om_h, om_l, om_c):
    """Per-1m-bar regime + Wilder ATR-14 + EMA3/9 of highs/lows.
    Returns (atr, regime, prior_consec_trend_bars).
    """
    n = len(om_c)
    atr = np.full(n, np.nan)
    regime = np.zeros(n, dtype=np.int64)
    consec = np.zeros(n, dtype=np.int64)
    e3h = e9h = e3l = e9l = 0.0
    cur_reg = 0
    cur_consec = 0
    prev_c = 0.0
    tr_seed_sum = 0.0
    tr_seed_n = 0
    cur_atr = np.nan
    for i in range(n):
        h, l, c = om_h[i], om_l[i], om_c[i]
        if i == 0:
            e3h = h; e9h = h; e3l = l; e9l = l
            tr_seed_sum += (h - l)
            tr_seed_n += 1
        else:
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            if np.isnan(cur_atr):
                tr_seed_sum += tr
                tr_seed_n += 1
                if tr_seed_n == ATR_PERIOD:
                    cur_atr = tr_seed_sum / ATR_PERIOD
            else:
                cur_atr = (cur_atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
            e3h = ALPHA_EMA3 * h + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * h + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * l + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * l + (1.0 - ALPHA_EMA9) * e9l
        prev_c = c
        new_reg = cur_reg
        if c > e3h and c > e9h:
            new_reg = 1
        elif c < e3l and c < e9l:
            new_reg = -1
        if new_reg != cur_reg and new_reg != 0:
            # this is a flip bar — consec resets
            cur_consec = 1
        else:
            cur_consec = cur_consec + 1 if (new_reg == cur_reg and new_reg != 0) else cur_consec
        # Actually consec = bars in CURRENT regime; for "pre-flip consec" we want
        # the count of bars in the PRIOR regime up to (but not including) this bar
        regime[i] = new_reg
        atr[i] = cur_atr
        consec[i] = cur_consec
        cur_reg = new_reg
    return atr, regime, consec


def compute_session_HL_table(start_y=2019, end_y=2026):
    """Per ET trading-date, compute RTH high/low and overnight high/low.
    Same logic as archetype_study.py."""
    parts = []
    for y in range(start_y, end_y + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            df = pd.read_parquet(p, columns=["high", "low"])
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    et = bars.index.tz_convert(ET)
    et_sod = et.hour * 3600 + et.minute * 60 + et.second
    is_rth = (et_sod >= RTH_START_ET) & (et_sod < RTH_END_ET)
    is_post_close = et_sod >= RTH_END_ET
    et_date_dt = pd.to_datetime(et.date)
    eth_dates_dt = et_date_dt.copy()
    eth_dates_dt = eth_dates_dt.where(~is_post_close,
                                       eth_dates_dt + pd.Timedelta(days=1))
    rth_df = pd.DataFrame({
        "date": et_date_dt[is_rth],
        "high": bars["high"].values[is_rth],
        "low":  bars["low"].values[is_rth],
    })
    rth = rth_df.groupby("date").agg(rth_high=("high", "max"),
                                      rth_low=("low",  "min"))
    eth_df = pd.DataFrame({
        "date": eth_dates_dt[~is_rth],
        "high": bars["high"].values[~is_rth],
        "low":  bars["low"].values[~is_rth],
    })
    eth = eth_df.groupby("date").agg(eth_high=("high", "max"),
                                      eth_low=("low",  "min"))
    out = rth.join(eth, how="outer").sort_index()
    return out


def compute_features_for_year(year, nt_flips_year):
    """Compute archetype features for all NT flips in `year`.
    Returns DataFrame indexed by row index of nt_flips_year.
    """
    # Load 1s bars for [year-1, year, year+1] for overflow on session/30m lookback
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close", "volume"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")

    ts_s = bars.index.values.astype(np.int64)
    o_s  = bars["open"].to_numpy(np.float64)
    h_s  = bars["high"].to_numpy(np.float64)
    l_s  = bars["low"].to_numpy(np.float64)
    c_s  = bars["close"].to_numpy(np.float64)
    v_s  = bars["volume"].to_numpy(np.float64)

    # 1m bars (epoch-floored)
    bucket = (ts_s // (60 * NS)) * (60 * NS)
    g = pd.DataFrame({
        "b": bucket, "o": o_s, "h": h_s, "l": l_s, "c": c_s})
    one_m = g.groupby("b").agg(o=("o", "first"), h=("h", "max"),
                                l=("l", "min"), c=("c", "last"))
    m_ts = one_m.index.values.astype(np.int64)
    m_h, m_l, m_o, m_c = (one_m["h"].to_numpy(np.float64),
                          one_m["l"].to_numpy(np.float64),
                          one_m["o"].to_numpy(np.float64),
                          one_m["c"].to_numpy(np.float64))
    atr_arr, regime_arr, consec_arr = compute_1m_state(m_h, m_l, m_c)

    # Session VWAP cumulative (per CT 17:00 session)
    et_idx = bars.index.tz_convert(ET)
    et_hour = et_idx.hour.values
    et_min  = et_idx.minute.values
    et_sec  = et_idx.second.values
    et_sod  = et_hour * 3600 + et_min * 60 + et_sec
    # Globex session boundary: 17:00 CT = 18:00 ET in standard time
    # (or 18:00 ET in DST). Use CT-based date+1d-if-hour>=17 for the session id.
    ct_idx = bars.index.tz_convert(pytz.timezone("America/Chicago"))
    ct_hour = ct_idx.hour.values
    ct_date = pd.to_datetime(ct_idx.date)
    sess_id_dt = ct_date.copy()
    sess_id_dt = sess_id_dt.where(ct_hour < 17,
                                    sess_id_dt + pd.Timedelta(days=1))
    sess_id = sess_id_dt.view("int64")  # ns since epoch as session key
    p = (h_s + l_s + c_s) / 3.0
    pv = p * v_s
    p2v = p * p * v_s
    f = pd.DataFrame({"sid": sess_id, "pv": pv, "p2v": p2v, "v": v_s})
    cum_pv  = f.groupby("sid")["pv"].cumsum().to_numpy()
    cum_p2v = f.groupby("sid")["p2v"].cumsum().to_numpy()
    cum_v   = f.groupby("sid")["v"].cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap_s  = np.where(cum_v > 0, cum_pv / cum_v, np.nan)
        var_s   = np.where(cum_v > 0, cum_p2v / cum_v - vwap_s * vwap_s, 0.0)
        sigma_s = np.sqrt(np.maximum(var_s, 0.0))

    # NT flips year subset
    ets = nt_flips_year["entry_ts"].to_numpy(np.int64)
    dr  = nt_flips_year["signal_direction"].to_numpy(np.int64)
    n = len(nt_flips_year)
    out = pd.DataFrame(index=nt_flips_year.index)
    cols = ["close_at_T", "vwap", "vwap_sigma",
            "flip_close_location", "flip_range_atr",
            "tot_slow_30m",
            "regime_flips_last_30min", "regime_flips_last_60min",
            "consec_trend_pre_flip",
            "et_sod"]
    for c in cols:
        out[c] = np.nan

    for k in range(n):
        T = int(ets[k])
        # 1s bar AT T (= flip-bar close moment)
        i_s = np.searchsorted(ts_s, T, side="left")
        if i_s < len(ts_s):
            out.iat[k, 0] = o_s[i_s]                  # close_at_T (= open of next bar = price at T)
            out.iat[k, 1] = vwap_s[i_s] if i_s > 0 else np.nan
            out.iat[k, 2] = sigma_s[i_s] if i_s > 0 else np.nan
        # 1m flip bar (open ts = T - 60s, close at T)
        fb_open_ts = T - 60 * NS
        i_m = np.searchsorted(m_ts, fb_open_ts, side="left")
        if i_m < len(m_ts) and m_ts[i_m] == fb_open_ts:
            rng = m_h[i_m] - m_l[i_m]
            if rng > 0:
                out.iat[k, 3] = (m_c[i_m] - m_l[i_m]) / rng
            atr_v = atr_arr[i_m]
            if not np.isnan(atr_v) and atr_v > 0:
                out.iat[k, 4] = rng / atr_v
            # consec trend pre-flip = consec_arr at i_m-1 (the prior bar's
            # "bars in regime" count, since flip bar itself starts a new regime)
            if i_m >= 1:
                out.iat[k, 8] = consec_arr[i_m - 1]
        # 30m compression: tot_slow = mfe+mae over [T-30m, T) 1s bars
        win_start = T - 30 * 60 * NS
        i_lo = np.searchsorted(ts_s, win_start, side="left")
        i_hi = i_s  # exclusive at T
        if i_hi - i_lo >= 10 and i_lo > 0:
            seg_h = h_s[i_lo:i_hi]; seg_l = l_s[i_lo:i_hi]
            anchor = o_s[i_lo]
            mfe = seg_h.max() - anchor
            mae = anchor - seg_l.min()
            out.iat[k, 5] = mfe + mae
        # regime flip counts: count regime transitions in 1m bars closing
        # within (T-30m, T] and (T-60m, T]
        # 1m bar at index j closes at m_ts[j] + 60s. We want closes in (T-Δ, T].
        # Equivalently, m_ts[j] in (T-Δ-60s, T-60s].
        if i_m >= 0:
            for win_idx, win_ns in [(6, 30 * 60 * NS), (7, 60 * 60 * NS)]:
                jstart = np.searchsorted(m_ts, T - win_ns - 60 * NS, side="right")
                jend   = i_m  # inclusive of flip bar
                if jstart < jend:
                    seg = regime_arr[jstart:jend + 1]
                    # Count transitions where adjacent bars differ and both non-zero
                    n_flips = 0
                    for q in range(1, len(seg)):
                        if seg[q] != seg[q - 1] and seg[q] != 0:
                            n_flips += 1
                    out.iat[k, win_idx] = n_flips
        out.iat[k, 9] = et_sod[i_s] if i_s < len(et_sod) else np.nan

    return out


def classify_and_report(df):
    """Apply archetype + cleanliness booleans and report cells."""
    # Compute derived columns
    df = df.copy()
    df["vwap_z"] = (df["close_at_T"] - df["vwap"]) / df["vwap_sigma"]
    df["vwap_z_dir"] = df["vwap_z"] * df["signal_direction"]
    df["near_vwap"] = df["vwap_z"].abs() < NEAR_VWAP_Z
    df["stretched"] = df["vwap_z"].abs() >= STRETCHED_VWAP_Z
    df["away_vwap"] = df["vwap_z_dir"] > 0
    df["in_rth"] = (df["et_sod"] >= RTH_START_ET) & (df["et_sod"] < RTH_END_ET)
    df["in_opening"] = (df["et_sod"] >= RTH_START_ET) & (df["et_sod"] < OPEN_END_ET)
    df["first_flip_recent"] = df["regime_flips_last_30min"] == 1

    # IS-tuned low-excursion cut
    is_ts = df[df["year"].isin(IS_YEARS)]["tot_slow_30m"].dropna()
    exc_lo_cut = float(is_ts.quantile(1 / 3)) if len(is_ts) else 19.2
    df["exc_low"] = df["tot_slow_30m"] < exc_lo_cut

    # NT outcome → win/loss
    df["win"] = (df["exit_reason"] == "T").astype(int)
    df["resolved"] = df["exit_reason"].isin(["T", "SL"])

    # Archetypes
    d = df["signal_direction"]
    df["arc_balanced"]   = (df["near_vwap"] & df["exc_low"] &
                             (df["regime_flips_last_30min"] <= CLEAN_MAX_FLIPS_30M))
    df["arc_exhaustion"] = df["stretched"] & df["away_vwap"]
    df["arc_chop"]       = (df["near_vwap"] &
                             (df["regime_flips_last_30min"] >= CHOP_MIN_FLIPS_30M))
    df["arc_opendrive"]  = (df["in_opening"] & df["first_flip_recent"])
    # Cleanliness
    cl_quiet = df["regime_flips_last_30min"] <= CLEAN_MAX_FLIPS_30M
    cl_decisive = df["consec_trend_pre_flip"] >= CLEAN_MIN_CONSEC_TREND
    cl_close = pd.Series(np.where(
        d == 1,
        df["flip_close_location"] >= CLEAN_MIN_CLOSE_LOC,
        df["flip_close_location"] <= (1 - CLEAN_MIN_CLOSE_LOC)),
        index=df.index)
    cl_range = df["flip_range_atr"] >= CLEAN_MIN_RANGE_ATR
    df["clean"] = cl_quiet & cl_decisive & cl_close & cl_range
    print(f"  cleanliness pass rates: quiet={cl_quiet.mean():.1%} "
          f"decisive={cl_decisive.mean():.1%} "
          f"close={cl_close.mean():.1%} range={cl_range.mean():.1%}  "
          f"ALL4={df['clean'].mean():.1%}")
    print(f"  IS-tuned exc_low cut: {exc_lo_cut:.1f} pts")

    # ── REPORT ──
    res = df[df["resolved"]]
    base = res["win"].mean()
    print(f"\n{'='*78}\nNT FULL FLIP UNIVERSE\n{'='*78}")
    print(f"  Total NT flips: {len(df):,}")
    print(f"  Resolved (T or SL): {len(res):,}")
    print(f"  NT base win rate (resolved): {base:.1%}")
    by_yr = res.groupby("year")["win"].agg(["count", "mean"])
    by_yr.columns = ["n", "win%"]
    print(f"\n  Base by year:")
    print(by_yr.to_string(formatters={"win%": "{:.1%}".format}))

    print(f"\n{'='*78}\nARCHETYPE CELLS (vs NT base "
          f"{base:.1%})\n{'='*78}")
    cells = [
        ("arc_balanced", "Balanced"),
        ("arc_exhaustion", "Exhaustion (stretched+away)"),
        ("arc_chop", "Chop"),
        ("arc_opendrive", "OpeningDrive"),
    ]
    print(f"  {'cell':<28}{'IS-clean':>14}{'IS-noisy':>14}"
          f"{'OOS-clean':>15}{'OOS-noisy':>15}")
    for col, name in cells:
        row = f"  {name:<28}"
        for years, clean in [(IS_YEARS, True), (IS_YEARS, False),
                              (OOS_YEARS, True), (OOS_YEARS, False)]:
            sub = res[res[col] & (res["clean"] == clean) &
                       res["year"].isin(years)]
            n = len(sub); w = sub["win"].mean() if n else float("nan")
            if n < 30:
                row += f"{'-':>14}" if not (years == IS_YEARS) else f"{'-':>14}"
            else:
                lift = (w - base) * 100
                row += f"{n:>5} {w:>5.1%} {lift:>+5.1f}".rjust(14)
        print(row)

    # Year-by-year for survivors (OOS clean win% > base + 3pp, n>=30)
    print(f"\n{'='*78}\nYEAR-BY-YEAR SURVIVORS (OOS-clean lift > +3pp vs base, "
          f"n>=30)\n{'='*78}")
    survivors = []
    for col, name in cells:
        sub = res[res[col] & res["clean"] & res["year"].isin(OOS_YEARS)]
        n = len(sub); w = sub["win"].mean() if n else float("nan")
        if n >= 30 and (w - base) > 0.03:
            survivors.append((col, name, n, w))
    if not survivors:
        print("  (none — no cell beats base by 3+pp with n>=30 on OOS clean)")
    for col, name, n, w in survivors:
        print(f"\n  {name} — OOS clean n={n} win={w:.1%}  "
              f"lift={(w-base)*100:+.1f}pp")
        print(f"    {'year':<6}{'n':>6}{'win%':>8}{'lift':>8}{'(IS)':>6}")
        for y in range(2020, 2027):
            ss = res[res[col] & res["clean"] & (res["year"] == y)]
            if len(ss) < 10:
                continue
            yw = ss["win"].mean()
            tag = "IS" if y in IS_YEARS else ""
            print(f"    {y:<6}{len(ss):>6}{yw:>7.1%}{(yw-base)*100:>+7.1f}"
                  f"{tag:>6}")


def main():
    t0 = time.time()
    print("Loading NT-detected flips ...")
    nt = load_nt_flips()
    print(f"  {len(nt):,} flips 2020-2026")
    nt = nt.sort_values("entry_ts").reset_index(drop=True)

    print("Computing features per year ...")
    feat_parts = []
    for y in sorted(nt["year"].unique()):
        sub = nt[nt["year"] == y]
        t1 = time.time()
        feats = compute_features_for_year(int(y), sub)
        feat_parts.append(feats)
        print(f"  {y}: {len(sub):,} flips features done ({time.time()-t1:.0f}s)")
    feats = pd.concat(feat_parts)
    df = pd.concat([nt, feats], axis=1)
    out_p = OUT / f"nt_flip_archetypes_{PD['out_suffix']}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"  saved {out_p}")

    print(f"Classifying + reporting (PRODUCT={PRODUCT}) ...")
    classify_and_report(df)

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
