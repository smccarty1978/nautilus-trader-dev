"""Volume + VWAP feature extension for V_A snapshots.

Adds causal volume (bull/bear/total/delta/imbalance over 1m/5m/15m
rolling windows) and session-anchored VWAP (with +/-1/2/3 sigma bands)
features to every row in `snapshots.parquet` (regime_flip, bar1_check,
path_checkpoint kinds). Reads existing snapshots; does NOT re-run the
V_A collector.

Causality:
  - Each event's as-of timestamp T = `decision_ts` (the snapshot's own
    decision_ts, which is the 1s bar close immediately after the
    relevant 1m bar close).
  - All features use ONLY 1s bars with `ts_event < T`. Implemented via
    `searchsorted(side='left')` against the 1s `ts_event_ns` array.
  - Audited path: cumulative-sum sliding-window arrays + per-session
    cumulative VWAP state, both queried with the strict ts < T cutoff.

Bull/bear classification (no MBP-1 available; sub canceled):
  - 1s bar bullish if close > open
  - 1s bar bearish if close < open
  - 1s bar neutral if close == open (excluded from bull/bear sums)

VWAP:
  - CME globex session anchor: 17:00 CT each day (= prior trading day's
    17:00 CT for the current futures session). Cumulative state resets
    at every 17:00 CT boundary.
  - Typical price per 1s bar = (h + l + c) / 3.
  - VWAP(t) = sum(typical * vol) / sum(vol) over session up to t.
  - sigma(t) = sqrt(max(E[p^2] - VWAP^2, 0)), volume-weighted.
  - Bands at VWAP +/- k*sigma for k in {1, 2, 3}.

Volume windows: always-on rolling (cross RTH/ETH freely, per user spec).

`close` used for distance features:
  - regime_flip      -> `flip_bar_c`
  - bar1_check       -> `bar1_c`
  - path_checkpoint  -> `cur_close_price`

Output:
  collectors/collector_v2/results/v_a_v0_{year}/snapshots_with_vol_vwap.parquet
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
import pyarrow.parquet as pq


YEARS = [2024, 2025, 2026]
ONE_S_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots.parquet"
    for yr in YEARS
}
OUT_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in YEARS
}

WINDOWS_S = [60, 300, 900]
WIN_LABELS = ["1m", "5m", "15m"]


def load_1s_bars(path: str) -> pd.DataFrame:
    df = pq.read_table(
        path,
        columns=["ts_event", "open", "high", "low", "close", "volume"],
    ).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    # Normalize to tz-aware UTC for session_id computation in CT.
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    else:
        df["ts_event"] = df["ts_event"].dt.tz_convert("UTC")
    # For int64 nanosecond arithmetic, strip tz on a parallel column.
    ts_naive = df["ts_event"].dt.tz_convert("UTC").dt.tz_localize(None)
    df["ts_event_ns"] = ts_naive.astype("datetime64[ns]").astype("int64")
    # Sanity: epoch nanoseconds for any year >= 2017 must exceed 1.5e18.
    assert df["ts_event_ns"].iloc[0] > 1_500_000_000_000_000_000, (
        f"ts_event_ns appears not to be nanosecond epoch: "
        f"first value = {df['ts_event_ns'].iloc[0]}"
    )
    return df


def assign_session_id(ts_event: pd.Series) -> pd.Series:
    """Label each 1s bar with its CME globex session date.

    Session anchor is 17:00 CT. Session for trading day D runs from
    (D-1) 17:00 CT through D 16:00 CT. Implementation: shift the CT
    timestamp back 17 hours, then take the resulting date. Bars at or
    after 17:00 CT roll into the next session.
    """
    ct = ts_event.dt.tz_convert("America/Chicago")
    shifted = ct - pd.Timedelta(hours=17)
    return shifted.dt.date.astype(str)


def precompute_bar_features(bars: pd.DataFrame) -> dict:
    """Attach per-bar columns and return cumulative-sum arrays for
    always-on rolling windows."""
    open_ = bars["open"].to_numpy()
    close = bars["close"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    vol = bars["volume"].to_numpy().astype(np.float64)

    bar_dir = np.zeros(len(bars), dtype=np.int8)
    bar_dir[close > open_] = 1
    bar_dir[close < open_] = -1

    bull_vol = np.where(bar_dir == 1, vol, 0.0)
    bear_vol = np.where(bar_dir == -1, vol, 0.0)
    signed_vol = bull_vol - bear_vol

    typical = (high + low + close) / 3.0
    p_vol = typical * vol
    p2_vol = typical * typical * vol

    bars["bull_vol"] = bull_vol
    bars["bear_vol"] = bear_vol
    bars["total_vol"] = vol
    bars["p_vol"] = p_vol
    bars["p2_vol"] = p2_vol
    bars["signed_vol"] = signed_vol
    bars["session_id"] = assign_session_id(bars["ts_event"])

    cum = {
        "cum_bull":  np.concatenate([[0.0], bull_vol.cumsum()]),
        "cum_bear":  np.concatenate([[0.0], bear_vol.cumsum()]),
        "cum_total": np.concatenate([[0.0], vol.cumsum()]),
    }

    grp = bars.groupby("session_id", sort=False, observed=True)
    bars["cum_p_vol_sess"]  = grp["p_vol"].cumsum()
    bars["cum_p2_vol_sess"] = grp["p2_vol"].cumsum()
    bars["cum_vol_sess"]    = grp["total_vol"].cumsum()
    bars["cum_signed_sess"] = grp["signed_vol"].cumsum()

    return cum


def compute_features_for_events(
    events_ts: np.ndarray, bars: pd.DataFrame, cum: dict,
) -> pd.DataFrame:
    bars_ts = bars["ts_event_ns"].to_numpy()
    n = len(events_ts)

    out: dict = {}
    for lab in WIN_LABELS:
        out[f"vol_bull_{lab}"]      = np.zeros(n)
        out[f"vol_bear_{lab}"]      = np.zeros(n)
        out[f"vol_total_{lab}"]     = np.zeros(n)
        out[f"vol_delta_{lab}"]     = np.zeros(n)
        out[f"vol_imbalance_{lab}"] = np.full(n, np.nan)

    out["vwap_value"]       = np.full(n, np.nan)
    out["vwap_sigma"]       = np.full(n, np.nan)
    out["obv_session"]      = np.zeros(n)
    out["cum_vol_session"]  = np.zeros(n)

    cum_p_vol  = bars["cum_p_vol_sess"].to_numpy()
    cum_p2_vol = bars["cum_p2_vol_sess"].to_numpy()
    cum_vol    = bars["cum_vol_sess"].to_numpy()
    cum_signed = bars["cum_signed_sess"].to_numpy()

    for k in range(n):
        T = int(events_ts[k])
        i_end = int(np.searchsorted(bars_ts, T, side="left"))
        if i_end == 0:
            continue

        for W, lab in zip(WINDOWS_S, WIN_LABELS):
            T_start = T - W * 1_000_000_000
            i_start = int(np.searchsorted(bars_ts, T_start, side="left"))
            bull = cum["cum_bull"][i_end]  - cum["cum_bull"][i_start]
            bear = cum["cum_bear"][i_end]  - cum["cum_bear"][i_start]
            tot  = cum["cum_total"][i_end] - cum["cum_total"][i_start]
            out[f"vol_bull_{lab}"][k]  = bull
            out[f"vol_bear_{lab}"][k]  = bear
            out[f"vol_total_{lab}"][k] = tot
            out[f"vol_delta_{lab}"][k] = bull - bear
            if tot > 0:
                out[f"vol_imbalance_{lab}"][k] = (bull - bear) / tot

        last_i = i_end - 1
        vol_sess = cum_vol[last_i]
        if vol_sess > 0:
            vwap = cum_p_vol[last_i] / vol_sess
            e_p2 = cum_p2_vol[last_i] / vol_sess
            sigma = float(np.sqrt(max(e_p2 - vwap * vwap, 0.0)))
            out["vwap_value"][k]      = vwap
            out["vwap_sigma"][k]      = sigma
            out["cum_vol_session"][k] = vol_sess
            out["obv_session"][k]     = cum_signed[last_i]

    return pd.DataFrame(out)


def attach_distance_features(snap: pd.DataFrame) -> pd.DataFrame:
    """Compute close-to-VWAP-level distances for each row.

    `close` source depends on kind (regime_flip uses flip_bar_c,
    bar1_check uses bar1_c, path_checkpoint uses cur_close_price).
    ATR normalization uses atr_1m (snapshot's freshest 1m ATR).
    """
    n = len(snap)
    close_col = np.full(n, np.nan)
    is_rf = (snap["kind"] == "regime_flip").to_numpy()
    is_b1 = (snap["kind"] == "bar1_check").to_numpy()
    is_pc = (snap["kind"] == "path_checkpoint").to_numpy()
    close_col[is_rf] = snap.loc[is_rf, "flip_bar_c"].to_numpy()
    close_col[is_b1] = snap.loc[is_b1, "bar1_c"].to_numpy()
    close_col[is_pc] = snap.loc[is_pc, "cur_close_price"].to_numpy()
    snap["event_close_px"] = close_col

    vwap = snap["vwap_value"].to_numpy()
    sigma = snap["vwap_sigma"].to_numpy()
    atr = snap["atr_1m"].to_numpy()
    atr_ok = np.isfinite(atr) & (atr > 0)

    raw_d = close_col - vwap
    snap["dist_close_to_vwap"]     = raw_d
    snap["dist_close_to_vwap_atr"] = np.where(atr_ok, raw_d / atr, np.nan)

    for k in (1, 2, 3):
        upper = vwap + k * sigma
        lower = vwap - k * sigma
        snap[f"dist_close_to_vwap_upper_{k}sd"]     = close_col - upper
        snap[f"dist_close_to_vwap_lower_{k}sd"]     = close_col - lower
        snap[f"dist_close_to_vwap_upper_{k}sd_atr"] = np.where(
            atr_ok, (close_col - upper) / atr, np.nan)
        snap[f"dist_close_to_vwap_lower_{k}sd_atr"] = np.where(
            atr_ok, (close_col - lower) / atr, np.nan)

    return snap


def audit_random_sample(snap: pd.DataFrame, bars: pd.DataFrame, n_check=50):
    """Re-compute features the slow brute-force way for n_check random
    rows and assert equivalence with the fast cumulative-sum result."""
    rng = np.random.default_rng(seed=42)
    valid = snap[snap["vwap_value"].notna()]
    if len(valid) < n_check:
        n_check = len(valid)
    idxs = rng.choice(len(valid), size=n_check, replace=False)

    bars_ts = bars["ts_event_ns"].to_numpy()
    bull = bars["bull_vol"].to_numpy()
    bear = bars["bear_vol"].to_numpy()
    tot = bars["total_vol"].to_numpy()
    p_v = bars["p_vol"].to_numpy()
    p2_v = bars["p2_vol"].to_numpy()
    sess = bars["session_id"].to_numpy()

    errs = 0
    for j in idxs:
        row = valid.iloc[j]
        T = int(row["decision_ts"])
        i_end = int(np.searchsorted(bars_ts, T, side="left"))
        if i_end == 0:
            continue
        for W, lab in zip(WINDOWS_S, WIN_LABELS):
            T_start = T - W * 1_000_000_000
            mask = (bars_ts >= T_start) & (bars_ts < T)
            ref_bull = bull[mask].sum()
            ref_tot  = tot[mask].sum()
            assert abs(row[f"vol_bull_{lab}"] - ref_bull) < 1e-6, \
                f"vol_bull_{lab} mismatch at row {j}"
            assert abs(row[f"vol_total_{lab}"] - ref_tot) < 1e-6, \
                f"vol_total_{lab} mismatch at row {j}"
        # VWAP: re-sum within session, ts < T
        last_i = i_end - 1
        session = sess[last_i]
        sess_mask = (sess == session) & (bars_ts < T)
        ref_vol = tot[sess_mask].sum()
        if ref_vol > 0:
            ref_pv = p_v[sess_mask].sum()
            ref_p2v = p2_v[sess_mask].sum()
            ref_vwap = ref_pv / ref_vol
            ref_var = max(ref_p2v / ref_vol - ref_vwap ** 2, 0.0)
            ref_sigma = np.sqrt(ref_var)
            assert abs(row["vwap_value"] - ref_vwap) < 1e-4, \
                f"vwap_value mismatch at row {j}: " \
                f"{row['vwap_value']} vs {ref_vwap}"
            assert abs(row["vwap_sigma"] - ref_sigma) < 1e-4, \
                f"vwap_sigma mismatch at row {j}"
    print(f"  audit: {n_check} random rows brute-force matched OK",
          flush=True)


def process_year(year: int):
    print(f"\n=== YEAR {year} ===", flush=True)
    t0 = time.time()
    snap = pd.read_parquet(SNAP_PATHS[year])
    print(f"  loaded {len(snap):,} snapshots", flush=True)

    one_s_path = ONE_S_PATHS[year]
    if not Path(one_s_path).exists():
        print(f"  MISSING 1s file: {one_s_path}"); return
    bars = load_1s_bars(one_s_path)
    print(f"  loaded {len(bars):,} 1s bars ({time.time()-t0:.0f}s)",
          flush=True)

    cum = precompute_bar_features(bars)
    print(f"  precomputed bar features ({time.time()-t0:.0f}s)",
          flush=True)

    # Verify decision_ts is the BAR CLOSE timestamp (ts_init = ts_event + 1s),
    # not the bar open timestamp. For path_checkpoint events the snapshot
    # also carries bar_ts_event = the 1s bar OPEN whose close was observed,
    # so decision_ts - bar_ts_event must equal exactly 1 second.
    pc_mask = snap["kind"] == "path_checkpoint"
    if pc_mask.any():
        diffs = (snap.loc[pc_mask, "decision_ts"]
                  - snap.loc[pc_mask, "bar_ts_event"]).to_numpy()
        assert np.all(diffs == 1_000_000_000), (
            "decision_ts semantics violated: path_checkpoint rows must "
            "have decision_ts = bar_ts_event + 1s (i.e., ts_init of the "
            "1s bar). Found unique diffs (ns): "
            f"{np.unique(diffs[:20])}"
        )

    events_ts = snap["decision_ts"].to_numpy(dtype=np.int64)
    feats = compute_features_for_events(events_ts, bars, cum)
    snap = pd.concat([snap.reset_index(drop=True), feats], axis=1)
    snap = attach_distance_features(snap)
    print(f"  computed features ({time.time()-t0:.0f}s)", flush=True)

    audit_random_sample(snap, bars, n_check=50)

    out_path = OUT_PATHS[year]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(out_path, index=False)
    print(f"  wrote {out_path} ({time.time()-t0:.0f}s total)", flush=True)

    print()
    rf = snap[snap["kind"] == "regime_flip"]
    print(f"  regime_flip summary ({len(rf):,} rows):")
    for col in ["vol_total_1m", "vol_total_5m", "vol_total_15m",
                "vol_imbalance_1m", "vol_imbalance_5m", "vol_imbalance_15m",
                "vwap_value", "vwap_sigma", "obv_session",
                "dist_close_to_vwap_atr",
                "dist_close_to_vwap_upper_1sd_atr",
                "dist_close_to_vwap_lower_1sd_atr"]:
        v = rf[col].dropna()
        if len(v):
            print(f"    {col:<42}  n={len(v):>6,}  "
                  f"mean={v.mean():>+10.3f}  "
                  f"std={v.std():>10.3f}  "
                  f"med={v.median():>+10.3f}")


def main():
    print("=" * 78)
    print("VOLUME + VWAP FEATURE EXTENSION FOR V_A SNAPSHOTS")
    print("=" * 78)
    for year in YEARS:
        process_year(year)
    print("\n[done]")


if __name__ == "__main__":
    main()
