"""
Phase 2 — complete causal multi-timeframe context.

Every field is evaluated at each checkpoint's `observation_time` using ONLY
1s bars whose ts <= observation_time (causal). Windowed reductions use O(1)
prefix-sum / prefix-cumulative evaluation over the global 1s series, so the
whole build is vectorized (no per-checkpoint Python loop).

Directional fields are canonicalized so POSITIVE == favorable to the trade
(long: price up; short: price down).

Families implemented (see full_mtf_feature_contract.json for the field list):
  A returns & slope        B directional path efficiency
  C extreme behaviour      D volatility decomposition
  E OHLCV effort/result    F completed-bar structural context (1m/3m/5m/15m)
  G pullback history        H focused cross-horizon relationships

Structural/pullback proxies are labelled as proxies in the contract; no field
uses aggressor-side volume (OHLCV price-response only).
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import common as C


# ── prefix helpers ──────────────────────────────────────────────────────────
def _pref(x: np.ndarray) -> np.ndarray:
    """Prefix sum with leading 0: out[k] = sum(x[:k]); window (a,b] = out[b+1]-out[a+1]."""
    out = np.empty(len(x) + 1, dtype=np.float64)
    out[0] = 0.0
    np.cumsum(x, out=out[1:])
    return out


def _wsum(pref: np.ndarray, idx: np.ndarray, H: int) -> np.ndarray:
    """Sum of x over bars [idx-H+1 .. idx] (H bars ending at idx)."""
    return pref[idx + 1] - pref[idx - H + 1]


def build_context(chk: pd.DataFrame, arr: np.ndarray) -> pd.DataFrame:
    """Return a DataFrame aligned to `chk` rows with all MTF context columns."""
    ts = arr[:, 0].astype(np.int64)
    P = arr[:, 4].copy()                 # close
    HI = arr[:, 3].copy()
    LO = arr[:, 2].copy()
    VOL = arr[:, 5] / 1e9                 # de-scale fixed point -> contracts
    N = len(P)

    # per-bar change
    dp = np.empty(N, dtype=np.float64)
    dp[0] = 0.0
    dp[1:] = np.diff(P)

    # prefix arrays -----------------------------------------------------------
    j = np.arange(N, dtype=np.float64)
    pref_P = _pref(P)
    pref_jP = _pref(j * P)
    pref_P2 = _pref(P * P)
    pref_dp2 = _pref(dp * dp)
    pref_absdp = _pref(np.abs(dp))
    up = np.where(dp > 0, dp, 0.0)
    dn = np.where(dp < 0, -dp, 0.0)       # positive magnitude of down moves
    pref_up = _pref(up)
    pref_dn = _pref(dn)
    pref_up2 = _pref(up * up)
    pref_dn2 = _pref(dn * dn)
    pref_upN = _pref((dp > 0).astype(np.float64))
    pref_dnN = _pref((dp < 0).astype(np.float64))
    pref_vol = _pref(VOL)
    pref_vol_up = _pref(np.where(dp > 0, VOL, 0.0))
    pref_vol_dn = _pref(np.where(dp < 0, VOL, 0.0))

    # rolling max(high)/min(low) per horizon (fast C, causal — ends at bar)
    hi_s = pd.Series(HI)
    lo_s = pd.Series(LO)
    roll_hi = {H: hi_s.rolling(H, min_periods=1).max().values for H in C.HORIZONS.values()}
    roll_lo = {H: lo_s.rolling(H, min_periods=1).min().values for H in C.HORIZONS.values()}

    # map checkpoints -> bar index (last bar with ts <= obs_ts) ---------------
    obs = chk["observation_time"].values.astype(np.int64)
    idx = np.searchsorted(ts, obs, side="right") - 1
    idx = np.clip(idx, 0, N - 1)
    direction = chk["direction"].values.astype(np.float64)
    atr = chk["atr_at_flip"].values.astype(np.float64)
    atr = np.where(atr <= 0, np.nan, atr)

    out = {}
    for label, H in C.HORIZONS.items():
        ok = (idx - H) >= 0
        idc = np.where(ok, idx, H)        # safe index; masked to NaN after

        # A. returns & slope --------------------------------------------------
        p_now = P[idc]
        p_then = P[idc - H]
        net = p_now - p_then                       # raw price net move
        aligned_return = direction * net / atr
        # linear slope via regression over H bars ending at idc
        sp = _wsum(pref_P, idc, H)
        sjp = _wsum(pref_jP, idc, H)
        # local t = j - (idc-H+1); mean_t = (H-1)/2 ; var_t*H = H*(H^2-1)/12
        base = (idc - H + 1).astype(np.float64)
        sum_tp = sjp - base * sp                    # sum(local_t * P)
        mean_t = (H - 1) / 2.0
        mean_p = sp / H
        cov_tp = sum_tp / H - mean_t * mean_p
        var_t = (H * H - 1) / 12.0
        slope_price = cov_tp / var_t                # price per bar (per second)
        aligned_slope = direction * slope_price / atr
        # r^2 of that fit
        sp2 = _wsum(pref_P2, idc, H)
        var_p = sp2 / H - mean_p * mean_p
        r2 = np.where(var_p > 1e-12, (cov_tp * cov_tp) / (var_t * var_p), 0.0)
        r2 = np.clip(r2, 0.0, 1.0)

        out[f"aligned_return_{label}"] = np.where(ok, aligned_return, np.nan)
        out[f"aligned_slope_{label}"] = np.where(ok, aligned_slope, np.nan)
        out[f"slope_r2_{label}"] = np.where(ok, r2, np.nan)

        # B. directional path efficiency -------------------------------------
        path = _wsum(pref_absdp, idc, H)
        up_path = _wsum(pref_up, idc, H)
        dn_path = _wsum(pref_dn, idc, H)
        eff = np.where(path > 1e-9, net / path, 0.0) * direction     # signed, favorable+
        fav_path = np.where(direction > 0, up_path, dn_path)
        adv_path = np.where(direction > 0, dn_path, up_path)
        fav_frac = np.where(path > 1e-9, fav_path / path, np.nan)
        out[f"directional_efficiency_{label}"] = np.where(ok, eff, np.nan)
        out[f"favorable_path_fraction_{label}"] = np.where(ok, fav_frac, np.nan)
        out[f"net_progress_atr_{label}"] = np.where(ok, direction * net / atr, np.nan)

        # C. extreme behaviour -----------------------------------------------
        wh = roll_hi[H][idc]
        wl = roll_lo[H][idc]
        rng = wh - wl
        pos_in_range = np.where(rng > 1e-9, (P[idc] - wl) / rng, 0.5)
        # canonical: position toward favorable extreme (long->near high, short->near low)
        pos_fav = np.where(direction > 0, pos_in_range, 1.0 - pos_in_range)
        fav_extreme = np.where(direction > 0, wh, wl)
        dist_from_fav = direction * (P[idc] - fav_extreme) / atr    # <=0 (below fav ext)
        out[f"position_in_horizon_range_{label}"] = np.where(ok, pos_fav, np.nan)
        out[f"dist_from_favorable_extreme_{label}"] = np.where(ok, dist_from_fav, np.nan)
        out[f"horizon_range_atr_{label}"] = np.where(ok, rng / atr, np.nan)
        # new-extreme frequency proxy: bars in window making a new running fav extreme
        # approximated by fraction of favorable path over range (effort concentration)
        out[f"new_favorable_extreme_rate_{label}"] = np.where(
            ok & (rng > 1e-9), fav_path / (rng + 1e-9), np.nan)

        # D. volatility decomposition ----------------------------------------
        rv = np.sqrt(np.maximum(_wsum(pref_dp2, idc, H) / H, 0.0)) / atr
        n_up = _wsum(pref_upN, idc, H)
        n_dn = _wsum(pref_dnN, idc, H)
        up2 = _wsum(pref_up2, idc, H)
        dn2 = _wsum(pref_dn2, idc, H)
        vol_up = np.sqrt(np.where(n_up > 0, up2 / np.maximum(n_up, 1), 0.0)) / atr
        vol_dn = np.sqrt(np.where(n_dn > 0, dn2 / np.maximum(n_dn, 1), 0.0)) / atr
        fav_vol = np.where(direction > 0, vol_up, vol_dn)
        adv_vol = np.where(direction > 0, vol_dn, vol_up)
        out[f"realized_vol_{label}"] = np.where(ok, rv, np.nan)
        out[f"favorable_vol_{label}"] = np.where(ok, fav_vol, np.nan)
        out[f"adverse_vol_{label}"] = np.where(ok, adv_vol, np.nan)
        out[f"fav_to_adv_vol_ratio_{label}"] = np.where(
            ok, fav_vol / (adv_vol + 1e-6), np.nan)

        # E. OHLCV effort vs result ------------------------------------------
        wv = _wsum(pref_vol, idc, H)
        wv_up = _wsum(pref_vol_up, idc, H)
        wv_dn = _wsum(pref_vol_dn, idc, H)
        fav_vol_share = np.where(direction > 0, wv_up, wv_dn)
        adv_vol_share = np.where(direction > 0, wv_dn, wv_up)
        prog_per_vol = np.where(wv > 1e-9, (direction * net / atr) / (wv / H), np.nan)
        retr_per_vol = np.where(wv > 1e-9, (adv_path / atr) / (wv / H), np.nan)
        out[f"volume_total_{label}"] = np.where(ok, wv, np.nan)
        out[f"progress_per_volume_{label}"] = np.where(ok, prog_per_vol, np.nan)
        out[f"retracement_per_volume_{label}"] = np.where(ok, retr_per_vol, np.nan)
        out[f"favorable_volume_share_{label}"] = np.where(
            ok & (wv > 1e-9), fav_vol_share / wv, np.nan)
        # high effort / low progress: adverse volume high but net small
        out[f"high_volume_low_progress_{label}"] = np.where(
            ok, (adv_vol_share / (wv + 1e-9)) * (1.0 - np.clip(np.abs(eff), 0, 1)), np.nan)

    # cross-horizon relationships (H) ----------------------------------------
    def g(name):  # helper to fetch built column
        return out[name]
    out["cross_30s_vs_180s_return"] = g("aligned_return_30s") - g("aligned_return_180s")
    out["cross_30s_vs_300s_return"] = g("aligned_return_30s") - g("aligned_return_300s")
    out["cross_60s_vs_300s_return"] = g("aligned_return_60s") - g("aligned_return_300s")
    out["cross_180s_vs_900s_slope"] = g("aligned_slope_180s") - g("aligned_slope_900s")
    out["local_adv_vs_5m_fav_vol"] = g("adverse_vol_30s") - g("favorable_vol_300s")
    out["cross_eff_30s_vs_300s"] = g("directional_efficiency_30s") - g("directional_efficiency_300s")
    # local weakness while higher-tf still strong (positive == divergence)
    out["local_weak_htf_strong"] = np.clip(-g("aligned_return_30s"), 0, None) * \
        np.clip(g("aligned_return_300s"), 0, None)

    ctx = pd.DataFrame(out, index=chk.index)
    return ctx


def build_structural(chk: pd.DataFrame, arr: np.ndarray) -> pd.DataFrame:
    """Family F — completed-bar structural context at 1m/3m/5m/15m."""
    obs = chk["observation_time"].values.astype(np.int64)
    direction = chk["direction"].values.astype(np.float64)
    atr = chk["atr_at_flip"].values.astype(np.float64)
    atr = np.where(atr <= 0, np.nan, atr)
    out = {}
    SW = 3  # swing lookback in HTF bars

    for label, secs in C.HTF.items():
        htf = C.build_htf(arr, secs)
        cts = htf["close_ts"].values.astype(np.int64)
        hh = htf["high"].values
        ll = htf["low"].values
        cl = htf["close"].values
        M = len(htf)
        # causal swing state per HTF bar: compare last swing high/low vs prior
        higher_high = np.zeros(M)
        higher_low = np.zeros(M)
        lower_high = np.zeros(M)
        lower_low = np.zeros(M)
        for k in range(SW, M):
            recent_h = hh[k - SW + 1:k + 1].max()
            prev_h = hh[k - 2 * SW + 1:k - SW + 1].max() if k - 2 * SW + 1 >= 0 else hh[:k - SW + 1].max()
            recent_l = ll[k - SW + 1:k + 1].min()
            prev_l = ll[k - 2 * SW + 1:k - SW + 1].min() if k - 2 * SW + 1 >= 0 else ll[:k - SW + 1].min()
            higher_high[k] = 1.0 if recent_h > prev_h else 0.0
            lower_high[k] = 1.0 if recent_h < prev_h else 0.0
            higher_low[k] = 1.0 if recent_l > prev_l else 0.0
            lower_low[k] = 1.0 if recent_l < prev_l else 0.0
        struct_dir = (higher_high + higher_low) - (lower_high + lower_low)  # +2..-2
        # EMA slope / spread on HTF closes
        ema_f = pd.Series(cl).ewm(span=3, adjust=False).mean().values
        ema_s = pd.Series(cl).ewm(span=9, adjust=False).mean().values
        ema_slope = np.zeros(M)
        ema_slope[1:] = ema_f[1:] - ema_f[:-1]
        ema_spread = ema_f - ema_s

        # map checkpoint -> last HTF bar with close_ts <= obs (causal)
        b = np.searchsorted(cts, obs, side="right") - 1
        ok = b >= SW
        b = np.clip(b, 0, M - 1)
        sd_signed = direction * struct_dir[b]          # canonical: +favorable
        out[f"structure_direction_{label}"] = np.where(ok, sd_signed, np.nan)
        out[f"structure_break_against_{label}"] = np.where(
            ok, (sd_signed < 0).astype(float), np.nan)
        out[f"structure_intact_{label}"] = np.where(
            ok, (sd_signed > 0).astype(float), np.nan)
        out[f"ema_slope_{label}"] = np.where(ok, direction * ema_slope[b] / atr, np.nan)
        out[f"ema_spread_{label}"] = np.where(ok, direction * ema_spread[b] / atr, np.nan)

    return pd.DataFrame(out, index=chk.index)


def build_pullback_history(chk: pd.DataFrame) -> pd.DataFrame:
    """Family G — causal within-trade pullback history from atlas progress path.

    A pullback is 'completed' once, after a local peak in current_progress_atr,
    price recovers back to within 0.1 ATR of that peak (recovery criterion).
    All fields at checkpoint t use only checkpoints <= t of the same episode.
    """
    cols = ["episode_id", "seconds_since_entry", "current_progress_atr",
            "max_progress_atr", "pullback_from_peak_atr"]
    df = chk[cols].copy()
    n = len(df)
    n_pb = np.zeros(n)
    last_depth = np.zeros(n)
    med_depth = np.full(n, np.nan)
    max_depth = np.zeros(n)
    cur_vs_med = np.full(n, np.nan)
    last_made_new = np.zeros(n)

    ep = df["episode_id"].values
    prog = df["current_progress_atr"].values
    peak = df["max_progress_atr"].values
    RECOVER = 0.10   # ATR
    DEPTH_MIN = 0.25  # ATR minimum to count as a pullback

    start = 0
    for i in range(1, n + 1):
        if i == n or ep[i] != ep[start]:
            sl = slice(start, i)
            pr = prog[sl]
            pk = peak[sl]
            m = i - start
            depths = []           # completed pullback depths in order
            in_pb = False
            pb_peak = pr[0]
            pb_trough = pr[0]
            made_new = 0
            for t in range(m):
                cur_peak = pk[t]
                if not in_pb:
                    # start of pullback: drop from running peak
                    if cur_peak - pr[t] >= DEPTH_MIN:
                        in_pb = True
                        pb_peak = cur_peak
                        pb_trough = pr[t]
                else:
                    pb_trough = min(pb_trough, pr[t])
                    # recovery back near the pre-pullback peak
                    if pr[t] >= pb_peak - RECOVER:
                        depth = pb_peak - pb_trough
                        depths.append(depth)
                        made_new = 1 if pr[t] > pb_peak else 0
                        in_pb = False
                # write causal aggregates as-of t
                k = start + t
                nd = len(depths)
                n_pb[k] = nd
                if nd > 0:
                    last_depth[k] = depths[-1]
                    md = float(np.median(depths))
                    med_depth[k] = md
                    max_depth[k] = max(depths)
                    cur_pb = cur_peak - pr[t]
                    cur_vs_med[k] = cur_pb / md if md > 1e-9 else np.nan
                    last_made_new[k] = made_new
            start = i

    return pd.DataFrame({
        "pb_count": n_pb,
        "pb_last_depth": last_depth,
        "pb_median_depth": med_depth,
        "pb_max_depth": max_depth,
        "pb_current_vs_median": cur_vs_med,
        "pb_last_made_new_extreme": last_made_new,
    }, index=chk.index)


def main(cache=True):
    print("=" * 70)
    print("Phase 2 — build full MTF context")
    print("=" * 70)
    chk, _ = C.load_atlas()
    chk = chk[chk["period"].isin(["train", "val", "test"])].reset_index(drop=True)
    print(f"  checkpoints (train+val+test): {len(chk):,}")

    arr = C.load_1s_full()
    print("  building families A-E (returns/slope/efficiency/extremes/vol/volume) ...")
    ctx = build_context(chk, arr)
    print(f"    {ctx.shape[1]} context columns")
    print("  building family F (structural) ...")
    struct = build_structural(chk, arr)
    print(f"    {struct.shape[1]} structural columns")
    print("  building family G (pullback history) ...")
    pb = build_pullback_history(chk)
    print(f"    {pb.shape[1]} pullback columns")

    key = chk[["episode_id", "observation_time", "seconds_since_entry",
               "direction", "period"]].reset_index(drop=True)
    full = pd.concat([key, ctx, struct, pb], axis=1)
    feat_cols = [c for c in full.columns if c not in key.columns]
    # downcast features to float32 to halve memory (values are ATR-normalized,
    # float32 precision is ample for tree models and policy thresholds).
    full[feat_cols] = full[feat_cols].astype(np.float32)

    # provenance audit: causality + NaN rates
    prov = {
        "n_checkpoints": int(len(full)),
        "n_features": len(feat_cols),
        "families": {
            "A_returns_slope": [c for c in feat_cols if "return" in c or "slope" in c],
            "B_efficiency": [c for c in feat_cols if "efficien" in c or "path_fraction" in c or "net_progress" in c],
            "C_extremes": [c for c in feat_cols if "extreme" in c or "position_in_horizon" in c or "horizon_range" in c],
            "D_volatility": [c for c in feat_cols if "vol_" in c or c.endswith("_vol") or "realized_vol" in c],
            "E_volume": [c for c in feat_cols if "volume" in c or "per_volume" in c],
            "F_structural": list(struct.columns),
            "G_pullback": list(pb.columns),
            "H_cross": [c for c in feat_cols if c.startswith("cross_") or c.startswith("local_")],
        },
        "nan_rate": {c: float(full[c].isna().mean()) for c in feat_cols},
    }
    C.savej(prov, C.RESULTS / "feature_provenance_audit.json")

    contract = {
        "description": "Complete causal multi-timeframe context feature contract (v2).",
        "canonicalization": "directional fields positive == favorable to trade direction",
        "horizons_seconds": C.HORIZONS,
        "htf_seconds": C.HTF,
        "causal_rule": "all fields use only 1s bars with ts <= observation_time; "
                       "HTF bars use close_ts <= observation_time (closed='left' resample).",
        "proxy_disclosures": [
            "new_favorable_extreme_rate_* is a favorable-path/range concentration proxy.",
            "volume_* are OHLCV price-response proxies; NOT aggressor-side volume.",
            "structure_* use SW=3 HTF-bar swing lookback.",
        ],
        "feature_order": feat_cols,
        "n_features": len(feat_cols),
    }
    C.savej(contract, C.RESULTS / "full_mtf_feature_contract.json")

    if cache:
        full.to_parquet(C.CACHE / "full_context_features.parquet", index=False)
        full.to_parquet(C.RESULTS / "full_context_features.parquet", index=False)
        print(f"  wrote full_context_features.parquet ({len(full):,} x {full.shape[1]})")
    return full


if __name__ == "__main__":
    main()
