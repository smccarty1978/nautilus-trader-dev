"""Archetype study — classify 1m regime flips by market-state archetype
and measure +1/-1 ATR first-touch outcomes per cell, year-by-year, IS/OOS.

Reframe of the failed threshold optimization: instead of asking
"which compression cap value is best?" (which gave razor-edge +$11.43/tr
at cap=22.0, negative on both neighbors), ask "which market state is
this flip occurring inside?" The cap=22.0 effect is most likely a
hidden archetype accidentally isolated by the threshold.

Universe: every v2 1m regime flip 2020-2026 (~117K events).
Outcome:  +1.0 ATR / -1.0 ATR first-touch on 1s bars, anchored at the
          flip-bar close (= v2 signal_time - 60s; empirical match).
          Unbounded forward race, ambiguous bar = adverse (conservative).

Archetypes (5 base, non-exclusive boolean filters):
  A. Balanced compression       near VWAP + low recent flips + low excursion
  B. Exhaustion                 outside VWAP 2σ + flip away from VWAP
  C. Acceptance Breakout        breaking PDH/PDL, 4 sub-cells:
       C1. Strict tag (within 0.25 ATR) × near VWAP
       C2. Strict tag × stretched VWAP (|z| ≥ 2)
       C3. Vicinity (within 1 ATR) × near VWAP
       C4. Vicinity × stretched VWAP
  D. Chop                       many recent flips + near VWAP
  E. Opening Drive              first flip + 09:30-10:30 ET + volume expanding

Orthogonal cleanliness axis (binary):
  Clean = ALL of:
    regime_flips_last_30min ≤ 2
    prior_regime_duration_bars ≥ 5
    flip_close_location ≥ 0.75 (long) or ≤ 0.25 (short)
    flip_range_atr ≥ 1.0 OR pre_signal_breakout_from_compression_flag = 1

Discipline:
  - Tertile cuts (excursion, ATR percentile) computed on IS 2020-2022 only.
  - IS = 2020-2022, OOS = 2023-2026.
  - Screen: +1/-1 ATR first-touch win rate by cell, IS vs OOS.
  - Runner EV (2-lot bracket) computed ONLY for cells that survive
    the screen (defined: OOS win% ≥ 54%, n ≥ 30/year on avg, sign
    stable year-by-year).
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

# Paths
SNAP = "studies/1m_regime_collector_v2/results/v2_feature_snapshots_{}.parquet"
COMPRESSION_VWAP = ("studies/v_a_excursion_regime/results_v0/"
                    "compression_vwap_study.parquet")
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OUT = Path("studies/v_a_excursion_regime/results_v0")

# Time windows (seconds from midnight ET)
RTH_START_ET = (9 * 3600) + (30 * 60)
RTH_END_ET   = 16 * 3600
OPEN_END_ET  = (10 * 3600) + (30 * 60)

# Archetype thresholds
NEAR_VWAP_Z = 1.0
STRETCHED_VWAP_Z = 2.0
STRICT_LEVEL_ATR = 0.25
VICINITY_LEVEL_ATR = 1.0
CHOP_MIN_FLIPS_30M = 4
VOL_EXPAND_RATIO = 1.2

# Cleanliness thresholds
CLEAN_MAX_FLIPS_30M     = 2     # ≤ 2 flips in last 30m (incl current)
CLEAN_MIN_CONSEC_TREND  = 2     # consecutive_trend_bars_pre_flip ≥ 2
CLEAN_MIN_CLOSE_LOC     = 0.75  # for long; mirror for short
CLEAN_MIN_RANGE_ATR     = 1.0   # OR breakout-flag = 1
# Note: prior_regime_duration_bars is always 0 in v2 snapshots (broken
# column), so we use consecutive_trend_bars_pre_flip as the "decisive
# setup" proxy instead.

# IS / OOS
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)


# ── data loaders ────────────────────────────────────────────────────────────

def load_flips() -> pd.DataFrame:
    """One row per (signal_time, signal_direction) flip, 2020-2026."""
    feats = [
        "signal_time", "signal_direction", "atr_at_signal",
        "regime_flips_last_30min", "regime_flips_last_60min",
        "consecutive_trend_bars_pre_flip", "avg_regime_duration_last_5",
        "flip_close_location", "flip_range_atr",
        "pre_signal_breakout_from_compression_flag",
        "flip_vol_vs_20avg",
        "dist_to_recent_high_10_atr", "dist_to_recent_low_10_atr",
        "minutes_since_rth_open", "is_rth",
        "checkpoint_s",
    ]
    parts = []
    for y in range(2020, 2027):
        p = Path(SNAP.format(y))
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=feats)
        df = df.sort_values(["signal_time", "signal_direction",
                             "checkpoint_s"])
        df = df.drop_duplicates(subset=["signal_time",
                                        "signal_direction"], keep="first")
        df["year"] = y
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df = df.drop(columns=["checkpoint_s"])
    df["signal_time"] = df["signal_time"].astype(np.int64)
    df["signal_direction"] = df["signal_direction"].astype(np.int64)
    return df


def attach_vwap_and_excursion(flips: pd.DataFrame) -> pd.DataFrame:
    """Join VWAP, vwap_sigma, tot_slow from compression_vwap_study."""
    cv = pd.read_parquet(COMPRESSION_VWAP,
                         columns=["signal_time", "signal_direction",
                                  "vwap", "vwap_sigma", "close_at_T",
                                  "tot_slow"])
    cv["signal_time"] = cv["signal_time"].astype(np.int64)
    cv["signal_direction"] = cv["signal_direction"].astype(np.int64)
    merged = flips.merge(cv, on=["signal_time", "signal_direction"],
                          how="left")
    # vwap z-score (signed, +ve = above VWAP)
    merged["vwap_z"] = ((merged["close_at_T"] - merged["vwap"])
                        / merged["vwap_sigma"].replace(0, np.nan))
    merged["vwap_z_dir"] = merged["vwap_z"] * merged["signal_direction"]
    return merged


# ── prior-day H/L and overnight H/L ─────────────────────────────────────────

def compute_session_HL_table() -> pd.DataFrame:
    """Per ET trading-date, compute RTH high/low and overnight high/low.

    ETH attribution: bars on day D before 09:30 ET attribute to D's
    overnight; bars on day D after 16:00 ET attribute to D+1's overnight.
    Returns DataFrame indexed by date with columns rth_high, rth_low,
    eth_high, eth_low.
    """
    parts = []
    for y in range(2019, 2027):
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


def attach_levels(flips: pd.DataFrame,
                  hl_table: pd.DataFrame) -> pd.DataFrame:
    """For each flip, attach prior-day RTH HL and current overnight HL
    distances (in ATR units, signed: positive = above level).
    """
    flips = flips.copy()
    flips["et_date"] = pd.to_datetime(
        pd.to_datetime(flips["signal_time"], unit="ns", utc=True)
          .dt.tz_convert(ET).dt.date)
    # Build a sorted list of all dates with RTH data
    rth_dates = pd.to_datetime(
        hl_table.dropna(subset=["rth_high"]).index)

    # For each flip, prior trading date = greatest rth_date < et_date
    flip_dates = flips["et_date"].to_numpy()
    rth_dates_arr = rth_dates.to_numpy()
    rth_dates_arr.sort()
    # searchsorted: first index where rth_date >= flip_date → minus 1 → prior date
    idx = np.searchsorted(rth_dates_arr, flip_dates, side="left") - 1
    prior_dates = pd.Series(
        np.where(idx >= 0, rth_dates_arr[np.clip(idx, 0, None)],
                 pd.NaT), index=flips.index)
    flips["prior_date"] = pd.to_datetime(prior_dates)

    # Map prior date → PDH/PDL
    pdh = hl_table["rth_high"].reindex(flips["prior_date"].values).values
    pdl = hl_table["rth_low"].reindex(flips["prior_date"].values).values
    flips["pdh"] = pdh
    flips["pdl"] = pdl

    # Map current et_date → overnight HL (the overnight leading INTO this
    # session = ETH attributed to et_date)
    onh = hl_table["eth_high"].reindex(flips["et_date"].values).values
    onl = hl_table["eth_low"].reindex(flips["et_date"].values).values
    flips["onh"] = onh
    flips["onl"] = onl

    # Distances in ATR (signed, +ve = price above level)
    atr = flips["atr_at_signal"].replace(0, np.nan)
    c = flips["close_at_T"]
    flips["dist_pdh_atr"] = (c - flips["pdh"]) / atr
    flips["dist_pdl_atr"] = (c - flips["pdl"]) / atr
    flips["dist_onh_atr"] = (c - flips["onh"]) / atr
    flips["dist_onl_atr"] = (c - flips["onl"]) / atr
    return flips


# ── ATR percentile ──────────────────────────────────────────────────────────

def attach_atr_percentile(flips: pd.DataFrame,
                          window: int = 250) -> pd.DataFrame:
    """Rolling rank of atr_at_signal over the last `window` flips
    (chronological)."""
    flips = flips.sort_values("signal_time").reset_index(drop=True)
    atr = flips["atr_at_signal"].to_numpy()
    pct = np.full(len(flips), np.nan)
    for i in range(len(flips)):
        lo = max(0, i - window + 1)
        win = atr[lo:i + 1]
        if len(win) < 30:
            continue
        pct[i] = (win <= atr[i]).mean()
    flips["atr_pct"] = pct
    return flips


# ── re-anchored outcome at flip-bar close ────────────────────────────────────

@njit
def race_unbounded(anchor_ts, anchor_px, direction, atr,
                    ts, hi, lo):
    if not (anchor_px == anchor_px) or atr <= 0:
        return -1, -1  # hit, bars_to_hit
    j = np.searchsorted(ts, anchor_ts, side="left")
    if direction == 1:
        tgt, stp = anchor_px + atr, anchor_px - atr
    else:
        tgt, stp = anchor_px - atr, anchor_px + atr
    j0 = j
    while j < len(ts):
        h, l = hi[j], lo[j]
        if direction == 1:
            ht, hs = h >= tgt, l <= stp
        else:
            ht, hs = l <= tgt, h >= stp
        if ht and hs:
            return 0, j - j0
        if ht:
            return 1, j - j0
        if hs:
            return 0, j - j0
        j += 1
    return -1, -1


def compute_outcomes(flips: pd.DataFrame) -> pd.DataFrame:
    """For each flip, race +1/-1 ATR from anchor = close of 1s bar at
    (signal_time - 60s) (= flip-bar close, the canonical strategy
    entry moment)."""
    flips = flips.copy()
    hit = np.full(len(flips), -1, dtype=np.int64)
    bars_to_hit = np.full(len(flips), -1, dtype=np.int64)
    for year in sorted(flips["year"].unique()):
        # Load 1s bars for year-1, year, year+1 (forward-race spillover)
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
        ts = bars.index.values.astype(np.int64)
        o = bars["open"].to_numpy(np.float64)
        h = bars["high"].to_numpy(np.float64)
        l = bars["low"].to_numpy(np.float64)
        mask = (flips["year"] == year).to_numpy()
        for k in np.where(mask)[0]:
            cts = int(flips["signal_time"].iat[k]) - 60 * NS  # flip-bar close
            d = int(flips["signal_direction"].iat[k])
            a = float(flips["atr_at_signal"].iat[k])
            # anchor = open of 1s bar AT cts = price at cts = flip-bar close.
            # Forward race starts at this same bar.
            i = np.searchsorted(ts, cts, side="left")
            if i >= len(ts) or ts[i] - cts > 5 * NS:
                continue
            anchor_px = o[i]
            hh, bb = race_unbounded(cts, anchor_px, d, a, ts, h, l)
            hit[k] = hh
            bars_to_hit[k] = bb
    flips["hit_flip_close"] = hit
    flips["bars_to_hit_flip_close"] = bars_to_hit
    return flips


# ── archetype + cleanliness classification ──────────────────────────────────

def classify(flips: pd.DataFrame) -> pd.DataFrame:
    flips = flips.copy()
    d = flips["signal_direction"]
    # Convenience flags
    near_vwap     = flips["vwap_z"].abs() < NEAR_VWAP_Z
    stretched     = flips["vwap_z"].abs() >= STRETCHED_VWAP_Z
    away_vwap     = flips["vwap_z_dir"] > 0   # flip extends from VWAP
    flips["near_vwap"] = near_vwap
    flips["stretched"] = stretched
    flips["away_vwap"] = away_vwap

    # IS-tuned low-excursion threshold: bottom tertile of tot_slow on IS years
    is_ts = flips[flips["year"].isin(IS_YEARS)]["tot_slow"].dropna()
    if len(is_ts):
        exc_lo_cut = float(is_ts.quantile(1 / 3))
    else:
        exc_lo_cut = 19.2
    flips["exc_low"] = flips["tot_slow"] < exc_lo_cut

    # "First flip after quiet" = ONLY the current flip in the last 30 min
    # (regime_flips_last_30min counts the current flip, so == 1 means
    # no prior flip in the last 30 min).
    flips["first_flip_recent"] = flips["regime_flips_last_30min"] == 1

    # ET seconds-of-day
    et_dt = pd.to_datetime(flips["signal_time"], unit="ns", utc=True
                            ).dt.tz_convert(ET)
    et_sod = et_dt.dt.hour * 3600 + et_dt.dt.minute * 60 + et_dt.dt.second
    flips["et_sod"] = et_sod
    flips["in_rth"] = (et_sod >= RTH_START_ET) & (et_sod < RTH_END_ET)
    flips["in_opening"] = ((et_sod >= RTH_START_ET) &
                            (et_sod < OPEN_END_ET))

    # Directional PDH/PDL: for long flips, look at proximity to PDH;
    # for short flips, proximity to PDL.
    dist_to_dir_pd = np.where(d == 1,
                               np.abs(flips["dist_pdh_atr"]),
                               np.abs(flips["dist_pdl_atr"]))
    flips["dist_dir_pd_atr"] = dist_to_dir_pd

    # ──── ARCHETYPES (non-exclusive booleans) ────
    flips["arc_balanced"]   = (near_vwap & flips["exc_low"] &
                                (flips["regime_flips_last_30min"] <=
                                 CLEAN_MAX_FLIPS_30M))
    flips["arc_exhaustion"] = stretched & away_vwap
    flips["arc_chop"]       = (near_vwap &
                                (flips["regime_flips_last_30min"] >=
                                 CHOP_MIN_FLIPS_30M))
    flips["arc_opendrive"]  = (flips["in_opening"] & flips["in_rth"] &
                                flips["first_flip_recent"] &
                                (flips["flip_vol_vs_20avg"] >=
                                 VOL_EXPAND_RATIO))

    # Acceptance Breakout sub-cells
    strict = dist_to_dir_pd < STRICT_LEVEL_ATR
    vicin  = dist_to_dir_pd < VICINITY_LEVEL_ATR
    flips["arc_ab_strict_near"]  = strict & near_vwap
    flips["arc_ab_strict_stretched"] = strict & stretched
    flips["arc_ab_vicinity_near"]    = vicin  & near_vwap
    flips["arc_ab_vicinity_stretched"] = vicin & stretched

    # ──── CLEANLINESS ────
    cl_flips_quiet   = flips["regime_flips_last_30min"] <= CLEAN_MAX_FLIPS_30M
    cl_decisive      = (flips["consecutive_trend_bars_pre_flip"] >=
                        CLEAN_MIN_CONSEC_TREND)
    cl_close_loc     = pd.Series(np.where(
                            d == 1,
                            flips["flip_close_location"] >= CLEAN_MIN_CLOSE_LOC,
                            flips["flip_close_location"] <= (1 - CLEAN_MIN_CLOSE_LOC)),
                        index=flips.index)
    cl_range_exp     = ((flips["flip_range_atr"] >= CLEAN_MIN_RANGE_ATR) |
                        (flips["pre_signal_breakout_from_compression_flag"] == 1))
    flips["cl_quiet"]    = cl_flips_quiet
    flips["cl_decisive"] = cl_decisive
    flips["cl_close"]    = cl_close_loc
    flips["cl_range"]    = cl_range_exp
    flips["clean"] = cl_flips_quiet & cl_decisive & cl_close_loc & cl_range_exp
    print(f"  cleanliness marginal pass rates:")
    print(f"    quiet (flips_30m<=2):   {cl_flips_quiet.mean():.1%}")
    print(f"    decisive (consec>=2):   {cl_decisive.mean():.1%}")
    print(f"    close near extreme:     {cl_close_loc.mean():.1%}")
    print(f"    range expansion:        {cl_range_exp.mean():.1%}")
    print(f"    ALL 4 (clean):          {flips['clean'].mean():.1%}")
    return flips, exc_lo_cut


# ── reporter ────────────────────────────────────────────────────────────────

CELLS = [
    ("arc_balanced",          "Balanced"),
    ("arc_exhaustion",        "Exhaustion"),
    ("arc_chop",              "Chop"),
    ("arc_opendrive",         "OpeningDrive"),
    ("arc_ab_strict_near",    "AB strict×near"),
    ("arc_ab_strict_stretched","AB strict×stretched"),
    ("arc_ab_vicinity_near",  "AB vicin×near"),
    ("arc_ab_vicinity_stretched","AB vicin×stretched"),
]


def _wr(sub):
    """Resolved win rate excluding unresolved (hit=-1)."""
    s = sub[sub["hit_flip_close"] >= 0]
    n = len(s)
    w = (s["hit_flip_close"] == 1).mean() if n else np.nan
    return n, w


def report(flips: pd.DataFrame, exc_lo_cut: float):
    print(f"\n{'='*78}\nUNIVERSE\n{'='*78}")
    print(f"  Total flips 2020-2026: {len(flips):,}")
    print(f"  With VWAP / outcome:   {flips['hit_flip_close'].ge(0).sum():,}")
    print(f"  IS-tuned exc_low cut:  {exc_lo_cut:.1f} pts (tot_slow < cut)")
    base_n, base_wr = _wr(flips)
    print(f"  Base resolved win rate: {base_wr:.1%}  (n={base_n:,})")

    print(f"\n{'='*78}\nCELL OVERVIEW — clean vs noisy × archetype")
    print(f"{'='*78}")
    print(f"  {'cell':<24}{'IS clean':>15}{'IS noisy':>15}"
          f"{'OOS clean':>16}{'OOS noisy':>16}")
    for col, name in CELLS:
        row = f"  {name:<24}"
        for years, clean in [(IS_YEARS, True), (IS_YEARS, False),
                              (OOS_YEARS, True), (OOS_YEARS, False)]:
            sub = flips[flips[col] & (flips["clean"] == clean) &
                         flips["year"].isin(years)]
            n, w = _wr(sub)
            if n < 10:
                row += f"{'-':>15}"
            else:
                row += f"{n:>6} / {w:>6.1%}".rjust(15)
        print(row)

    # Year-by-year for survivors (OOS clean win% ≥ 54%)
    print(f"\n{'='*78}")
    print(f"YEAR-BY-YEAR for cells where OOS clean n≥30 AND win% ≥ 54%")
    print(f"{'='*78}")
    survivors = []
    for col, name in CELLS:
        sub = flips[flips[col] & flips["clean"] &
                     flips["year"].isin(OOS_YEARS)]
        n, w = _wr(sub)
        if n >= 30 and w >= 0.54:
            survivors.append((col, name, n, w))
    if not survivors:
        print("  (none — no cell passes OOS screen)")
    else:
        for col, name, n, w in survivors:
            print(f"\n  CLEAN {name} — OOS pooled n={n} win {w:.1%}")
            print(f"    {'year':<6}{'n':>6}{'win%':>9}{'-1 atr%':>10}"
                  f"{'unresolved':>12}")
            for y in range(2020, 2027):
                ss = flips[flips[col] & flips["clean"] &
                            (flips["year"] == y)]
                if len(ss) < 5:
                    continue
                n1, w1 = _wr(ss)
                un = (ss["hit_flip_close"] == -1).mean()
                tag = "(IS)" if y in IS_YEARS else ""
                print(f"    {y:<6}{n1:>6}{w1:>8.1%}"
                      f"{1-w1 if not np.isnan(w1) else float('nan'):>9.1%}"
                      f"{un:>11.1%}  {tag}")

    # Overlap diagnostic among clean+OOS-positive cells
    print(f"\n{'='*78}")
    print(f"OVERLAP DIAGNOSTIC (OOS clean, % of cell-A flips also in cell-B)")
    print(f"{'='*78}")
    pop = flips[flips["clean"] & flips["year"].isin(OOS_YEARS)]
    print(f"  {'cell':<24}" + "".join(f"{n[:8]:>10}" for _, n in CELLS))
    for col_a, name_a in CELLS:
        a = pop[pop[col_a]]
        if len(a) == 0:
            continue
        row = f"  {name_a:<24}"
        for col_b, _ in CELLS:
            if col_a == col_b:
                row += f"{'-':>10}"
            else:
                overlap = (a[col_b]).sum() / len(a) if len(a) else 0
                row += f"{overlap:>9.1%}"
        print(row)


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    print("Loading v2 flip snapshots ...")
    flips = load_flips()
    print(f"  {len(flips):,} flips 2020-2026")
    print("Attaching VWAP + excursion ...")
    flips = attach_vwap_and_excursion(flips)
    print("Computing prior-day / overnight H/L table ...")
    hl_table = compute_session_HL_table()
    print(f"  {len(hl_table)} session dates")
    flips = attach_levels(flips, hl_table)
    print("Computing rolling ATR percentile ...")
    flips = attach_atr_percentile(flips)
    print("Computing re-anchored +1/-1 ATR outcomes (flip-bar close) ...")
    flips = compute_outcomes(flips)
    print("Classifying archetypes + cleanliness ...")
    flips, exc_lo_cut = classify(flips)

    out_p = OUT / "archetype_flips.parquet"
    flips.to_parquet(out_p, index=False)
    print(f"  saved {out_p}")

    report(flips, exc_lo_cut)
    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
