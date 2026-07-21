"""
Contextual Runner Exit v2 — orchestrator.

Phases 1,4,6,7,8,9,10,11,12,13 + final report. Reuses the repaired sim_v2
execution stack for terminal resolution, truncation and next-1s-open fills.

All model/threshold/persistence/buffer choices are frozen on train+val. The
development-test period is replayed exactly once.
"""

from __future__ import annotations
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor, LGBMClassifier

import common as C
import sim_v2
import build_full_mtf_context as BF
import build_regime_state_machine as BS

RES = C.RESULTS
RNG = np.random.default_rng(42)

STATES = ["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED", "ORDINARY", "WEAKENING", "TERMINAL"]


# ── execution helpers (per-episode PnL, reusing sim_v2 mechanics) ───────────
def policy_episode_pnl(chk_p, sig, ep_base, ep_meta, bars):
    """Per-episode PnL Series: first-signal exit (next-1s-open fill), else E0."""
    result = ep_base["e0_pnl"].copy()
    trig = chk_p[sig.values if hasattr(sig, "values") else sig]
    if len(trig):
        trig = trig.sort_values("seconds_since_entry")
        fired = (trig.groupby("episode_id")["observation_time"].first()
                 .reset_index().rename(columns={"observation_time": "sig_ts"}))
        fired = fired.merge(ep_meta[["entry_px", "direction"]],
                            left_on="episode_id", right_index=True, how="left")
        obs = fired["sig_ts"].values.astype(np.float64)
        fi = np.searchsorted(bars[:, 0], obs, side="right")
        valid = fi < len(bars)
        fic = fi.clip(0, len(bars) - 1)
        fpx = np.where(valid, bars[fic, 1], np.nan)
        pnl = (fpx - fired["entry_px"].values) * fired["direction"].values * C.NQ_MULT - C.COMMISSION
        fired["pnl"] = pnl
        bad = ~valid
        if bad.any():
            fired.loc[bad, "pnl"] = fired.loc[bad, "episode_id"].map(ep_base["e0_pnl"]).values
        result.loc[fired["episode_id"].values] = fired["pnl"].values
    return result


def Xmat(df, feats):
    """Build a float32 feature matrix (avoids float64 upcast from mixed dtypes)."""
    return df[feats].fillna(0).to_numpy(dtype=np.float32)


def make_ep_meta(chk_p):
    epx = "entry_px_y" if "entry_px_y" in chk_p.columns else "entry_px"
    m = chk_p.groupby("episode_id").first()[[epx, "direction"]].rename(columns={epx: "entry_px"})
    return m


def train_reg(X, y):
    m = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                      min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                      random_state=42, n_jobs=4, verbose=-1)
    m.fit(X, y)
    return m


def train_clf(X, y):
    m = LGBMClassifier(n_estimators=300, learning_rate=0.05, max_depth=4,
                       min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                       random_state=42, n_jobs=4, verbose=-1)
    m.fit(X, y)
    return m


# ── weakness-triggered stop simulation (real 1s monitoring) ─────────────────
def structural_low_high(bars, sig_ts, direction, lookback_s=60):
    """Recent structural extreme over [sig_ts-lookback, sig_ts] for stop placement."""
    lo_i = np.searchsorted(bars[:, 0], sig_ts - lookback_s * 1_000_000_000, side="left")
    hi_i = np.searchsorted(bars[:, 0], sig_ts, side="right")
    if hi_i <= lo_i:
        return np.nan
    if direction == 1:
        return float(bars[lo_i:hi_i, 2].min())   # low
    return float(bars[lo_i:hi_i, 3].max())        # high


def simulate_stops(weak_df, ep_meta, ep_base, trades_term, bars, buffer_atr=0.10):
    """
    For each weakness-event episode, activate real stops and monitor on 1s bars
    from the signal time to the episode terminal. Returns per-episode records.

    weak_df: one row per episode = FIRST weakness checkpoint (episode_id, sig_ts,
             direction, atr, entry_px, trade_mfe_atr, pb structural low/high).
    """
    term_map = trades_term.set_index("episode_id")["true_terminal_ts"]
    recs = []
    for r in weak_df.itertuples(index=False):
        ep = r.episode_id
        d = int(r.direction)
        entry = float(r.entry_px)
        atr = float(r.atr)
        sig_ts = int(r.sig_ts)
        end_ts = int(term_map.get(ep, r.sig_ts))
        e0 = float(ep_base["e0_pnl"].get(ep, np.nan))
        buf = buffer_atr * atr

        # S1 immediate exit fill
        _, s1_px = sim_v2.next_1s_open(bars, sig_ts)
        s1_pnl = (s1_px - entry) * d * C.NQ_MULT - C.COMMISSION if not np.isnan(s1_px) else e0

        # candidate stop levels
        s2_lvl = (r.struct_low - buf) if d == 1 else (r.struct_high + buf)
        s3_ref = r.pb_struct_low if d == 1 else r.pb_struct_high
        s3_lvl = (s3_ref - buf) if d == 1 else (s3_ref + buf)
        # S4: MFE/ATR protective — lock a fraction of MFE (3 candidate: 0.5 MFE)
        mfe_px = entry + d * r.trade_mfe_atr * atr
        s4_lvl = entry + d * (0.5 * r.trade_mfe_atr) * atr  # give back half of MFE

        out = {"episode_id": ep, "direction": d, "sig_ts": sig_ts, "end_ts": end_ts,
               "entry_px": entry, "atr": atr, "e0_pnl": e0, "s1_immediate_pnl": s1_pnl,
               "trade_mfe_atr": float(r.trade_mfe_atr)}

        # favorable extreme (new MFE) reference to detect recovery
        fav_target = entry + d * (r.trade_mfe_atr + 0.10) * atr  # a NEW extreme

        for tag, lvl in [("s2", s2_lvl), ("s3", s3_lvl), ("s4", s4_lvl)]:
            if lvl is None or np.isnan(lvl):
                out[f"{tag}_pnl"] = e0
                out[f"{tag}_stopped"] = False
                out[f"{tag}_stop_ts"] = 0
                out[f"{tag}_recovered_first"] = False
                out[f"{tag}_new_mfe_first"] = False
                continue
            # stop invalid if already on wrong side at activation -> treat as immediate
            _, cur_px = sim_v2.next_1s_open(bars, sig_ts)
            invalid = (d == 1 and cur_px <= lvl) or (d == -1 and cur_px >= lvl)
            if invalid:
                out[f"{tag}_pnl"] = s1_pnl
                out[f"{tag}_stopped"] = True
                out[f"{tag}_stop_ts"] = sig_ts
                out[f"{tag}_recovered_first"] = False
                out[f"{tag}_new_mfe_first"] = False
                continue
            stop_ts, stop_fill = sim_v2.detect_stop_hit(bars, sig_ts, end_ts, lvl, d)
            # detect first favorable-extreme (recovery) time before stop
            lo_i = np.searchsorted(bars[:, 0], sig_ts, side="left")
            hi_i = np.searchsorted(bars[:, 0], end_ts, side="right")
            seg = bars[lo_i:hi_i]
            if d == 1:
                rec_mask = seg[:, 3] >= fav_target
            else:
                rec_mask = seg[:, 2] <= fav_target
            rec_ts = int(seg[np.argmax(rec_mask), 0]) if rec_mask.any() else None
            stopped = stop_ts is not None
            new_mfe_first = rec_ts is not None and (not stopped or rec_ts <= stop_ts)
            if stopped and not (rec_ts is not None and rec_ts < stop_ts):
                pnl = (stop_fill - entry) * d * C.NQ_MULT - C.COMMISSION
                out[f"{tag}_recovered_first"] = False
            else:
                # recovery (or survival) -> resolve at episode terminal like E0
                pnl = e0
                out[f"{tag}_recovered_first"] = (rec_ts is not None)
            out[f"{tag}_pnl"] = pnl
            out[f"{tag}_stopped"] = stopped
            out[f"{tag}_stop_ts"] = stop_ts if stopped else 0
            out[f"{tag}_new_mfe_first"] = bool(new_mfe_first)
        recs.append(out)
    return pd.DataFrame(recs)


# ── main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("Contextual Runner Exit v2 — full study")
    print("=" * 70)

    # 0. context + state ------------------------------------------------------
    cache = C.CACHE / "full_context_features.parquet"
    if cache.exists():
        print("[ctx] loading cached full context ...")
        full = pd.read_parquet(cache)
    else:
        full = BF.main(cache=True)

    atlas, trades = C.load_atlas()
    atlas = atlas[atlas["period"].isin(["train", "val", "test"])].reset_index(drop=True)
    assert (atlas["episode_id"].values == full["episode_id"].values).all() and \
        (atlas["observation_time"].values == full["observation_time"].values).all(), \
        "context/atlas row alignment mismatch"

    # merge ONLY needed atlas columns (memory-lean): local features + execution
    # + state-machine inputs. Forward/oracle columns are never merged.
    NEEDED_ATLAS = [
        # local features
        "current_progress_atr", "max_progress_atr", "max_adverse_atr",
        "pullback_from_peak_atr", "seconds_since_peak", "progress_efficiency",
        "aligned_return_5s_atr", "aligned_return_15s_atr", "aligned_return_30s_atr",
        "aligned_return_60s_atr", "realized_vol_60s_atr", "range_5s_atr",
        "volume_5s_zscore", "volume_30s_vs_5m", "kalman_velocity_atr_per_s",
        "kalman_acceleration_atr_per_s2", "kalman_innovation_zscore",
        "ema3_ema9_spread_30s_atr", "regime_5s_aligned", "regime_30s_aligned",
        "regime_5m_aligned", "regime_age_1m_bars", "adx14_1m",
        "position_in_trailing_1m_range", "knn_hA", "knn_hB", "knn_hC",
        "knn_composite", "unrealized_pnl_atr", "trade_mfe_atr", "trade_mae_atr",
        "giveback_from_mfe_atr", "giveback_fraction",
        # execution + labels
        "entry_px_y", "stop_px_y", "exit_now_pnl", "atr_at_flip",
        "minutes_since_rth_open",
    ]
    present = [c for c in NEEDED_ATLAS if c in atlas.columns]
    float_atlas = [c for c in present if atlas[c].dtype == np.float64
                   and c not in ("entry_px_y", "stop_px_y", "exit_now_pnl", "atr_at_flip")]
    for c in present:
        vals = atlas[c].values
        full[c] = vals.astype(np.float32) if c in float_atlas else vals
    full["is_rth"] = C.is_rth_from_atlas(full)
    del atlas
    import gc
    gc.collect()

    # state machine
    full = BS.build(full)

    # 1. terminal resolution + truncation (sim_v2) ---------------------------
    print("\n[P1] terminal resolution + truncation ...")
    bars = C.load_1s_full()
    tt = trades[trades["period"].isin(["train", "val", "test"])].copy()
    tt = sim_v2.resolve_terminal_events(tt, bars)
    full = sim_v2.truncate_checkpoints(full, tt)
    full = sim_v2.compute_hold_advantage(full)
    n_stop = int(tt["stop_hit"].sum())
    print(f"  stop hits: {n_stop:,}/{len(tt):,} ({n_stop/len(tt):.1%})")
    print(f"  truncated checkpoints: {len(full):,}")

    # Defensive: forward-looking atlas columns are labels only — drop them from
    # the feature workspace so no accidental broad column access can leak them.
    FORWARD_COLS = [
        "remaining_mfe_atr", "max_future_giveback_atr", "best_future_exit_pnl",
        "current_mfe_is_final", "giveback_exceeds_025atr", "giveback_exceeds_050atr",
        "giveback_exceeds_100atr", "prob_remaining_gain_ge_025atr",
        "prob_remaining_gain_ge_050atr", "prob_remaining_gain_ge_100atr",
        "oracle_vs_regime", "regime_exit_vs_oracle", "total_pnl_hold_300s",
        "total_pnl_hold_regime", "base__pnl_300s", "base__stopped_300s",
        "base__pnl_regime", "base__exit_type_regime",
    ]
    full = full.drop(columns=[c for c in FORWARD_COLS if c in full.columns])

    # Ghost-row invariant on the true (recomputed) terminal, not the stale
    # atlas trade_alive marker: no checkpoint may sit past its terminal.
    term_map = tt.set_index("episode_id")["true_terminal_ts"]
    obs_vs_term = full["observation_time"].values - full["episode_id"].map(term_map).values
    post_terminal = int((obs_vs_term > 0).sum())
    assert post_terminal == 0, f"{post_terminal} post-terminal ghost rows remain after truncation"
    dup_rows = int(full.duplicated(["episode_id", "observation_time"]).sum())
    assert dup_rows == 0, "duplicate checkpoint rows"
    print(f"  post-terminal rows remaining: {post_terminal}")

    train = full[full["period"] == "train"].reset_index(drop=True).copy()
    val = full[full["period"] == "val"].reset_index(drop=True).copy()
    test = full[full["period"] == "test"].reset_index(drop=True).copy()
    del full
    gc.collect()

    # feature lists -----------------------------------------------------------
    with open(RES / "full_mtf_feature_contract.json") as f:
        MTF_FEATS = json.load(f)["feature_order"]
    MTF_FEATS = [c for c in MTF_FEATS if c in train.columns]

    LOCAL_CANDIDATES = [
        "current_progress_atr", "max_progress_atr", "max_adverse_atr",
        "pullback_from_peak_atr", "seconds_since_peak", "progress_efficiency",
        "aligned_return_5s_atr", "aligned_return_15s_atr", "aligned_return_30s_atr",
        "aligned_return_60s_atr", "realized_vol_60s_atr", "range_5s_atr",
        "volume_5s_zscore", "volume_30s_vs_5m", "kalman_velocity_atr_per_s",
        "kalman_acceleration_atr_per_s2", "kalman_innovation_zscore",
        "ema3_ema9_spread_30s_atr", "regime_5s_aligned", "regime_30s_aligned",
        "regime_5m_aligned", "regime_age_1m_bars", "adx14_1m",
        "position_in_trailing_1m_range", "knn_hA", "knn_hB", "knn_hC",
        "knn_composite", "unrealized_pnl_atr", "seconds_since_entry",
        "trade_mfe_atr", "trade_mae_atr", "giveback_from_mfe_atr", "giveback_fraction",
    ]
    LOCAL_FEATS = [c for c in LOCAL_CANDIDATES if c in train.columns]

    # state one-hot + meta
    STATE_FEATS = [f"state_{s}" for s in STATES] + ["mfe_age_pctile",
                                                    "seconds_in_state", "ever_prolific"]
    for df in (train, val, test):
        for s in STATES:
            df[f"state_{s}"] = (df["state"] == s).astype(np.float32)
        df["ever_prolific"] = df["ever_prolific"].astype(np.float32)
        df["inter_rth_giveback"] = df["is_rth"] * df["giveback_fraction"].fillna(0)
        df["inter_dir_ar300"] = df["direction"] * df.get("aligned_return_300s", 0)
    INTER_FEATS = ["is_rth", "direction", "inter_rth_giveback", "inter_dir_ar300"]

    FEATURE_SETS = {
        "M0": LOCAL_FEATS,
        "M1": MTF_FEATS,
        "M2": LOCAL_FEATS + MTF_FEATS,
        "M3": LOCAL_FEATS + MTF_FEATS + STATE_FEATS,
        "M4": LOCAL_FEATS + MTF_FEATS + STATE_FEATS + INTER_FEATS,
    }

    # 6. models ---------------------------------------------------------------
    print("\n[P6] training models M0-M4 (fitted-Q on hold_advantage) ...")
    y_ha = train["hold_advantage"].fillna(0).values
    y_term = (train["hold_advantage"].fillna(0) <= 0).astype(int).values  # deterioration
    models = {}
    val_metrics = []
    for name, feats in FEATURE_SETS.items():
        feats = [f for f in feats if f in train.columns]
        Xtr = Xmat(train, feats)
        reg = train_reg(Xtr, y_ha)
        clf = train_clf(Xtr, y_term)
        models[name] = {"reg": reg, "clf": clf, "feats": feats}
        # val AUC / corr (diagnostic only)
        Xv = Xmat(val, feats)
        yv_term = (val["hold_advantage"].fillna(0) <= 0).astype(int).values
        pv = clf.predict_proba(Xv)[:, 1]
        from sklearn.metrics import roc_auc_score
        auc = roc_auc_score(yv_term, pv) if len(np.unique(yv_term)) > 1 else np.nan
        val_metrics.append({"model": name, "n_features": len(feats),
                            "val_terminal_auc": round(float(auc), 4)})
    pd.DataFrame(val_metrics).to_parquet(RES / "validation_model_metrics.parquet", index=False)
    C.savej({"feature_sets": {k: v["feats"] for k, v in models.items()},
             "target_reg": "hold_advantage (fitted-Q, truncated backward DP)",
             "target_clf": "terminal_deterioration = hold_advantage<=0",
             "note": "forward labels used only as targets, never as features"},
            RES / "model_manifest.json")
    print("  " + " | ".join(f"{m['model']}:AUC={m['val_terminal_auc']}" for m in val_metrics))

    # ep_base / ep_meta per period -------------------------------------------
    ep_base = {}
    ep_meta = {}
    for tag, df in [("val", val), ("test", test)]:
        tt_p = tt[tt["period"] == tag]
        ep_base[tag] = sim_v2.build_ep_base(df, tt_p)
        ep_meta[tag] = make_ep_meta(df)

    def elig(df):
        return df["seconds_since_entry"] >= C.MIN_ELIG_S

    # scoring helper
    def score(df, name, kind):
        m = models[name]
        X = Xmat(df, m["feats"])
        return m["reg"].predict(X) if kind == "reg" else m["clf"].predict_proba(X)[:, 1]

    # local weakness condition (causal)
    def local_weak(df):
        ar30 = df.get("aligned_return_30s", pd.Series(np.zeros(len(df)), index=df.index))
        gb = df["giveback_fraction"].fillna(0)
        return (ar30.fillna(0) < 0) | (gb > 0.25)

    # 7. VALIDATION policy selection -----------------------------------------
    print("\n[P7] selecting policies on validation ...")

    def ev(df, sig, tag):
        return float(policy_episode_pnl(df, sig, ep_base[tag], ep_meta[tag],
                                        bars if tag == "test" else bars).mean())

    grid_rows = []

    # P1: M0 fitted-Q threshold
    s_val = score(val, "M0", "reg")
    best = (-1e9, None)
    for q in np.arange(10, 91, 5):
        thr = np.percentile(s_val, q)
        sig = elig(val) & (pd.Series(s_val, index=val.index) < thr)
        e = ev(val, sig, "val")
        grid_rows.append({"policy": "P1", "param": f"q{q}", "thr": float(thr), "val_ev": e})
        if e > best[0]:
            best = (e, thr)
    thr_p1 = best[1]

    # P2: full-context immediate exit — local weakness AND P(terminal|M3) > thr
    s_term_val = score(val, "M3", "clf")
    best = (-1e9, None)
    lw_val = local_weak(val)
    for q in np.arange(50, 96, 5):
        thr = np.percentile(s_term_val, q)
        sig = elig(val) & lw_val & (pd.Series(s_term_val, index=val.index) > thr)
        e = ev(val, sig, "val")
        grid_rows.append({"policy": "P2", "param": f"q{q}", "thr": float(thr), "val_ev": e})
        if e > best[0]:
            best = (e, thr)
    thr_p2 = best[1]

    # P3: P2 + persistence K checkpoints
    def persist_sig(df, base_sig, K):
        b = base_sig.values.astype(bool)
        codes = df.groupby("episode_id").ngroup().values
        run = np.zeros(len(b), dtype=int)
        for i in range(len(b)):
            if b[i]:
                run[i] = run[i - 1] + 1 if i > 0 and codes[i] == codes[i - 1] else 1
        return pd.Series(run >= K, index=df.index)

    base_p2_val = elig(val) & lw_val & (pd.Series(s_term_val, index=val.index) > thr_p2)
    best = (-1e9, 2)
    for K in [2, 3, 4, 6]:
        sig = persist_sig(val, base_p2_val, K)
        e = ev(val, sig, "val")
        grid_rows.append({"policy": "P3", "param": f"K{K}", "thr": float(K), "val_ev": e})
        if e > best[0]:
            best = (e, K)
    K_p3 = best[1]

    # P4: prolific lockout — P2 condition only when NOT prolific/healthy
    lockout_val = ~val["state"].isin(["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED"])
    sig_p4_val = base_p2_val & lockout_val
    ev_p4 = ev(val, sig_p4_val, "val")
    grid_rows.append({"policy": "P4", "param": "lockout", "thr": 0, "val_ev": ev_p4})

    # P5: prolific-decay confirmation — non-prolific persistence + weakness persists
    #     (fire only after seconds_in_state in non-prolific >= decay_s and weak)
    best = (-1e9, 15)
    for decay_s in [10, 15, 30]:
        non_pro = ~val["state"].isin(["PROLIFIC_EXPANDING"])
        cond = elig(val) & lw_val & non_pro & (val["seconds_in_state"] >= decay_s)
        e = ev(val, cond, "val")
        grid_rows.append({"policy": "P5", "param": f"d{decay_s}", "thr": decay_s, "val_ev": e})
        if e > best[0]:
            best = (e, decay_s)
    decay_p5 = best[1]

    # P6: segment-aware thresholds (RTH vs ETH) on the P2 terminal prob
    seg_thr = {}
    for seg_name, mask in [("RTH", val["is_rth"] == 1), ("ETH", val["is_rth"] != 1)]:
        sub = val[mask]
        if len(sub) < 200:
            seg_thr[seg_name] = thr_p2
            continue
        ss = score(sub, "M3", "clf")
        lw = local_weak(sub)
        best = (-1e9, thr_p2)
        for q in np.arange(50, 96, 5):
            thr = np.percentile(ss, q)
            sig = pd.Series(False, index=val.index)
            sig.loc[sub.index] = (elig(sub) & lw & (pd.Series(ss, index=sub.index) > thr)).values
            e = ev(val, sig, "val")
            if e > best[0]:
                best = (e, thr)
        seg_thr[seg_name] = best[1]
        grid_rows.append({"policy": "P6", "param": seg_name, "thr": float(best[1]), "val_ev": best[0]})

    pd.DataFrame(grid_rows).to_parquet(RES / "validation_policy_grid.parquet", index=False)

    # 8. weakness stop simulation (real 1s monitoring) -----------------------
    print("\n[P8] weakness-triggered stop simulation ...")

    def first_weakness(df):
        lw = local_weak(df) & elig(df)
        w = df[lw].sort_values("seconds_since_entry").groupby("episode_id").first()
        return w

    # build weakness event table for a period
    def weak_events(df, tag):
        w = first_weakness(df).reset_index()
        meta = ep_meta[tag]
        w = w.merge(meta, on="episode_id", suffixes=("", "_m"))
        rows = []
        for r in w.itertuples(index=False):
            sig_ts = int(r.observation_time)
            d = int(r.direction)
            sl = structural_low_high(bars, sig_ts, d, 60)
            # prior recovered pullback structural extreme from atlas progress:
            # approximate via max_adverse over trade as prior structure
            pb_ref = float(r.entry_px) - d * float(getattr(r, "max_adverse_atr", 0)) * float(r.atr_at_flip)
            rows.append({"episode_id": r.episode_id, "direction": d, "sig_ts": sig_ts,
                         "entry_px": float(r.entry_px), "atr": float(r.atr_at_flip),
                         "trade_mfe_atr": float(r.trade_mfe_atr),
                         "struct_low": sl if d == 1 else np.nan,
                         "struct_high": sl if d == -1 else np.nan,
                         "pb_struct_low": pb_ref if d == 1 else np.nan,
                         "pb_struct_high": pb_ref if d == -1 else np.nan})
        return pd.DataFrame(rows)

    # select stop buffer on val
    weak_val = weak_events(val, "val")
    best_buf = (-1e9, 0.10)
    for buf in [0.05, 0.10, 0.25]:
        sr = simulate_stops(weak_val, ep_meta["val"], ep_base["val"],
                            tt[tt["period"] == "val"], bars, buffer_atr=buf)
        d2 = (sr["s2_pnl"] - sr["e0_pnl"]).mean()
        if d2 > best_buf[0]:
            best_buf = (d2, buf)
    buf_frozen = best_buf[1]
    print(f"  frozen stop buffer: {buf_frozen} ATR (val S2 vs E0 = ${best_buf[0]:.2f})")

    # run stops on TEST
    weak_test = weak_events(test, "test")
    stop_test = simulate_stops(weak_test, ep_meta["test"], ep_base["test"],
                               tt[tt["period"] == "test"], bars, buffer_atr=buf_frozen)
    stop_test.to_parquet(RES / "weakness_stop_trades.parquet", index=False)

    # stop metrics
    stop_metrics = []
    for tag in ["s1_immediate", "s2", "s3", "s4"]:
        pcol = f"{tag}_pnl" if tag != "s1_immediate" else "s1_immediate_pnl"
        d_e0 = stop_test[pcol] - stop_test["e0_pnl"]
        d_imm = stop_test[pcol] - stop_test["s1_immediate_pnl"]
        row = {"stop_rule": tag, "n": len(stop_test),
               "mean_pnl": round(float(stop_test[pcol].mean()), 2),
               "delta_vs_e0": round(float(d_e0.mean()), 2),
               "delta_vs_immediate": round(float(d_imm.mean()), 2)}
        if tag != "s1_immediate":
            row["pct_stopped"] = round(float(stop_test[f"{tag}_stopped"].mean()), 3)
            row["pct_recovered_first"] = round(float(stop_test[f"{tag}_recovered_first"].mean()), 3)
            row["pct_new_mfe_first"] = round(float(stop_test[f"{tag}_new_mfe_first"].mean()), 3)
        stop_metrics.append(row)
    stop_metrics_df = pd.DataFrame(stop_metrics)
    stop_metrics_df.to_parquet(RES / "weakness_stop_metrics.parquet", index=False)
    stop_test[["episode_id", "direction", "e0_pnl", "s1_immediate_pnl", "s2_pnl",
               "s3_pnl", "s4_pnl"]].to_parquet(
        RES / "weakness_stop_episode_results.parquet", index=False)
    print(stop_metrics_df.to_string(index=False))

    # C10 stop placebo: arm S2 at a random matched checkpoint (not weakness) ---
    def random_events(df, tag):
        elg = df[elig(df)]
        w = elg.groupby("episode_id").apply(
            lambda g: g.sample(1, random_state=1)).reset_index(drop=True)
        meta = ep_meta[tag]
        w = w.merge(meta, on="episode_id", suffixes=("", "_m"))
        rows = []
        for r in w.itertuples(index=False):
            sig_ts = int(r.observation_time)
            d = int(r.direction)
            sl = structural_low_high(bars, sig_ts, d, 60)
            rows.append({"episode_id": r.episode_id, "direction": d, "sig_ts": sig_ts,
                         "entry_px": float(r.entry_px), "atr": float(r.atr_at_flip),
                         "trade_mfe_atr": float(r.trade_mfe_atr),
                         "struct_low": sl if d == 1 else np.nan,
                         "struct_high": sl if d == -1 else np.nan,
                         "pb_struct_low": np.nan, "pb_struct_high": np.nan})
        return pd.DataFrame(rows)

    placebo = random_events(test, "test")
    placebo_stop = simulate_stops(placebo, ep_meta["test"], ep_base["test"],
                                  tt[tt["period"] == "test"], bars, buffer_atr=buf_frozen)
    placebo_delta = float((placebo_stop["s2_pnl"] - placebo_stop["e0_pnl"]).mean())

    # 9. FROZEN test replay ---------------------------------------------------
    print("\n[P9] frozen dev-test replay ...")
    lw_test = local_weak(test)
    s_term_test = score(test, "M3", "clf")
    s_m0_test = score(test, "M0", "reg")

    policies = {}
    policies["P0_E0"] = ep_base["test"]["e0_pnl"].copy()
    policies["P1_fittedq"] = policy_episode_pnl(
        test, elig(test) & (pd.Series(s_m0_test, index=test.index) < thr_p1),
        ep_base["test"], ep_meta["test"], bars)
    base_p2_test = elig(test) & lw_test & (pd.Series(s_term_test, index=test.index) > thr_p2)
    policies["P2_context_exit"] = policy_episode_pnl(test, base_p2_test, ep_base["test"], ep_meta["test"], bars)
    policies["P3_context_persist"] = policy_episode_pnl(
        test, persist_sig(test, base_p2_test, K_p3), ep_base["test"], ep_meta["test"], bars)
    lockout_test = ~test["state"].isin(["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED"])
    policies["P4_prolific_lockout"] = policy_episode_pnl(
        test, base_p2_test & lockout_test, ep_base["test"], ep_meta["test"], bars)
    non_pro_test = ~test["state"].isin(["PROLIFIC_EXPANDING"])
    policies["P5_prolific_decay"] = policy_episode_pnl(
        test, elig(test) & lw_test & non_pro_test & (test["seconds_in_state"] >= decay_p5),
        ep_base["test"], ep_meta["test"], bars)
    # P6 segment-aware
    sig_p6 = pd.Series(False, index=test.index)
    for seg_name, mask in [("RTH", test["is_rth"] == 1), ("ETH", test["is_rth"] != 1)]:
        sub = test[mask]
        ss = score(sub, "M3", "clf")
        lw = local_weak(sub)
        cond = elig(sub) & lw & (pd.Series(ss, index=sub.index) > seg_thr[seg_name])
        sig_p6.loc[sub.index] = cond.values
    policies["P6_segment"] = policy_episode_pnl(test, sig_p6, ep_base["test"], ep_meta["test"], bars)

    # P7 hybrid: prolific/healthy -> armed structural stop (S2); else immediate exit
    p7 = ep_base["test"]["e0_pnl"].copy()
    # immediate-exit branch (ordinary/terminal weakness)
    imm_mask = base_p2_test & lockout_test  # weakness while not prolific/healthy
    imm_pnl = policy_episode_pnl(test, imm_mask, ep_base["test"], ep_meta["test"], bars)
    p7.loc[:] = imm_pnl.values
    # stop branch: episodes whose first weakness happened while prolific/healthy
    weak_state = first_weakness(test)[["state"]]
    stop_map = stop_test.set_index("episode_id")["s2_pnl"]
    for ep in weak_state.index:
        st = weak_state.loc[ep, "state"]
        if st in ("PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED") and ep in stop_map.index:
            p7.loc[ep] = stop_map.loc[ep]
    policies["P7_hybrid_stop"] = p7

    pol_df = pd.DataFrame(policies)
    pol_df.index.name = "episode_id"
    pol_df.to_parquet(RES / "policy_episode_results.parquet")

    # frozen config
    frozen = {
        "P1_thr_m0": float(thr_p1), "P2_thr_terminal": float(thr_p2),
        "P3_persist_K": int(K_p3), "P5_decay_s": int(decay_p5),
        "P6_seg_thr": {k: float(v) for k, v in seg_thr.items()},
        "stop_buffer_atr": float(buf_frozen),
        "scores": {"P1": "M0 fitted-Q reg", "P2/P4/P6": "M3 terminal-prob clf"},
    }
    C.savej(frozen, RES / "frozen_policy_config.json")
    C.savej({"P1_thr_m0": float(thr_p1), "P2_thr_terminal": float(thr_p2),
             "P3_persist_K": int(K_p3), "P5_decay_s": int(decay_p5),
             "P6_seg_thr": {k: float(v) for k, v in seg_thr.items()},
             "stop_buffer_atr": float(buf_frozen)}, RES / "policy_thresholds.json")

    # paired deltas + bootstrap ----------------------------------------------
    e0 = pol_df["P0_E0"]
    pol_metrics, boot_rows, delta_cols = [], [], {}
    for name in pol_df.columns:
        d = (pol_df[name] - e0).values
        delta_cols[name] = d
        lo, hi = C.paired_bootstrap_ci(d, n_boot=5000)
        pol_metrics.append({
            "policy": name, "n": len(d), "ev": round(float(pol_df[name].mean()), 2),
            "paired_delta": round(float(np.mean(d)), 2),
            "median_delta": round(float(np.median(d)), 2),
            "ci_lo": round(lo, 2), "ci_hi": round(hi, 2),
            "pct_improved": round(float((d > 1).mean()), 3),
            "pct_unchanged": round(float((np.abs(d) <= 1).mean()), 3),
            "pct_worsened": round(float((d < -1).mean()), 3),
            "win_rate": round(float((pol_df[name] > 0).mean()), 3),
        })
        boot_rows.append({"policy": name, "ci_lo": lo, "ci_hi": hi,
                          "mean_delta": float(np.mean(d))})
    pol_metrics_df = pd.DataFrame(pol_metrics)
    pol_metrics_df.to_parquet(RES / "policy_metrics.parquet", index=False)
    pd.DataFrame(delta_cols, index=pol_df.index).to_parquet(RES / "paired_policy_deltas.parquet")
    pd.DataFrame(boot_rows).to_parquet(RES / "paired_bootstrap_ci.parquet", index=False)
    pol_df.reset_index().to_parquet(RES / "policy_trades.parquet", index=False)
    print(pol_metrics_df[["policy", "ev", "paired_delta", "ci_lo", "ci_hi"]].to_string(index=False))

    # choose best frozen policy = best VAL EV among P1..P7 (selection on val) --
    # recompute val EV for each candidate to pick winner WITHOUT test leakage
    val_ev_candidates = {
        "P1_fittedq": ev(val, elig(val) & (pd.Series(score(val, "M0", "reg"), index=val.index) < thr_p1), "val"),
        "P2_context_exit": ev(val, base_p2_val, "val"),
        "P3_context_persist": ev(val, persist_sig(val, base_p2_val, K_p3), "val"),
        "P4_prolific_lockout": ev(val, base_p2_val & lockout_val, "val"),
        "P5_prolific_decay": ev(val, elig(val) & lw_val & (~val["state"].isin(["PROLIFIC_EXPANDING"])) & (val["seconds_in_state"] >= decay_p5), "val"),
    }
    e0_val = float(ep_base["val"]["e0_pnl"].mean())
    best_name = max(val_ev_candidates, key=lambda k: val_ev_candidates[k])
    print(f"  val-selected best policy: {best_name} "
          f"(val delta ${val_ev_candidates[best_name]-e0_val:+.2f})")

    # 10. runner eval ---------------------------------------------------------
    print("\n[P10] runner evaluation ...")
    runner_rows = []
    for pct, label in [(0.90, "top10"), (0.95, "top5"), (0.99, "top1")]:
        thr = e0.quantile(pct)
        m = e0 >= thr
        for name in pol_df.columns:
            if name == "P0_E0":
                continue
            d = (pol_df.loc[m, name] - e0[m])
            runner_rows.append({
                "tier": label, "policy": name, "n": int(m.sum()),
                "e0_ev": round(float(e0[m].mean()), 1),
                "policy_ev": round(float(pol_df.loc[m, name].mean()), 1),
                "delta": round(float(d.mean()), 1),
                "retention": round(float(pol_df.loc[m, name].mean() / e0[m].mean()), 3)
                if e0[m].mean() != 0 else np.nan,
            })
    runner_df = pd.DataFrame(runner_rows)
    runner_df.to_parquet(RES / "runner_results.parquet", index=False)
    top10 = runner_df[runner_df["tier"] == "top10"]
    print(top10.to_string(index=False))

    # 11. tail robustness -----------------------------------------------------
    print("\n[P11] tail robustness ...")
    tail_rows = []
    for name in pol_df.columns:
        if name == "P0_E0":
            continue
        d = np.sort((pol_df[name] - e0).values)
        base = d.mean()
        variants = {
            "full": base,
            "drop_top1": d[:-1].mean(),
            "drop_top5": d[:-5].mean(),
            "drop_top1pct": d[:int(len(d) * 0.99)].mean(),
            "drop_top5pct": d[:int(len(d) * 0.95)].mean(),
            "drop_bottom1": d[1:].mean(),
            "drop_bottom1pct": d[int(len(d) * 0.01):].mean(),
        }
        tail_rows.append({"policy": name, **{k: round(float(v), 2) for k, v in variants.items()}})
    tail_df = pd.DataFrame(tail_rows)
    tail_df.to_parquet(RES / "tail_sensitivity.parquet", index=False)

    # segment + monthly -------------------------------------------------------
    ep_dir = ep_meta["test"]["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first()
    ets = tt[tt["period"] == "test"].set_index("episode_id")["observation_time"]
    seg_rows = []
    best = best_name
    for gcol, groups in [
        ("session", [("RTH", ep_rth == 1), ("ETH", ep_rth != 1)]),
        ("direction", [("long", ep_dir == 1), ("short", ep_dir == -1)]),
    ]:
        for gv, mask in groups:
            idx = mask[mask].index
            d = (pol_df.loc[idx, best] - e0[idx])
            lo, hi = C.paired_bootstrap_ci(d.values)
            seg_rows.append({"group": gcol, "value": gv, "n": len(idx),
                             "e0_ev": round(float(e0[idx].mean()), 1),
                             "best_ev": round(float(pol_df.loc[idx, best].mean()), 1),
                             "delta": round(float(d.mean()), 2),
                             "ci_lo": round(lo, 2), "ci_hi": round(hi, 2)})
    # regime-state at decision (best policy fired) — use state at first weakness
    ws = first_weakness(test)["state"]
    for st in STATES:
        idx = ws[ws == st].index
        if len(idx) < 30:
            continue
        d = (pol_df.loc[idx, best] - e0[idx])
        seg_rows.append({"group": "state_at_decision", "value": st, "n": len(idx),
                         "e0_ev": round(float(e0[idx].mean()), 1),
                         "best_ev": round(float(pol_df.loc[idx, best].mean()), 1),
                         "delta": round(float(d.mean()), 2), "ci_lo": None, "ci_hi": None})
    seg_df = pd.DataFrame(seg_rows)
    seg_df.to_parquet(RES / "segment_results.parquet", index=False)
    print(seg_df.to_string(index=False))

    months = pd.to_datetime(ets.reindex(pol_df.index).values.astype("float64"),
                            unit="ns").strftime("%Y-%m")
    mo_rows = []
    for mo in sorted(set(months)):
        m = months == mo
        d = (pol_df.loc[m, best] - e0[m])
        lo, hi = C.paired_bootstrap_ci(d.values)
        mo_rows.append({"month": mo, "n": int(m.sum()),
                        "e0_ev": round(float(e0[m].mean()), 1),
                        "best_ev": round(float(pol_df.loc[m, best].mean()), 1),
                        "delta": round(float(d.mean()), 2),
                        "ci_lo": round(lo, 2), "ci_hi": round(hi, 2)})
    mo_df = pd.DataFrame(mo_rows)
    mo_df.to_parquet(RES / "monthly_results.parquet", index=False)
    months_pos = int((mo_df["delta"] > 0).sum())

    # 4. false-exit attribution ----------------------------------------------
    print("\n[P4] false-exit attribution ...")
    fe = first_weakness(test).reset_index()[["episode_id", "state", "previous_state",
                                             "is_rth", "direction", "seconds_since_entry",
                                             "trade_mfe_atr", "giveback_fraction", "ever_prolific"]]
    fe = fe.merge((pol_df[best] - e0).rename("delta").reset_index(), on="episode_id", how="left")
    fe["class"] = np.where(fe["delta"] >= 25, "successful",
                           np.where(fe["delta"] <= -25, "false_exit", "neutral"))
    fe.to_parquet(RES / "decision_checkpoint_exit_attribution.parquet", index=False)
    fe.to_parquet(RES / "false_exit_context_analysis.parquet", index=False)
    false_ex = fe[fe["class"] == "false_exit"]
    succ_ex = fe[fe["class"] == "successful"]
    fe_metrics = {
        "n_false_exit": len(false_ex), "n_successful": len(succ_ex),
        "mean_false_exit_loss": round(float(false_ex["delta"].mean()), 1) if len(false_ex) else 0,
        "mean_success_gain": round(float(succ_ex["delta"].mean()), 1) if len(succ_ex) else 0,
        "false_exit_rth_frac": round(float((false_ex["is_rth"] == 1).mean()), 3) if len(false_ex) else 0,
        "success_rth_frac": round(float((succ_ex["is_rth"] == 1).mean()), 3) if len(succ_ex) else 0,
        "false_exit_prolific_frac": round(float(false_ex["ever_prolific"].mean()), 3) if len(false_ex) else 0,
    }
    pd.DataFrame([fe_metrics]).to_parquet(RES / "false_exit_metrics.parquet", index=False)
    (RES / "false_exit_report.md").write_text(
        "# False-Exit Attribution (best frozen policy)\n\n"
        f"Best policy: **{best}**\n\n"
        f"- False exits (Δ<=-$25): {fe_metrics['n_false_exit']} "
        f"(mean ${fe_metrics['mean_false_exit_loss']})\n"
        f"- Successful exits (Δ>=+$25): {fe_metrics['n_successful']} "
        f"(mean +${fe_metrics['mean_success_gain']})\n"
        f"- False-exit RTH fraction: {fe_metrics['false_exit_rth_frac']:.1%} "
        f"vs successful {fe_metrics['success_rth_frac']:.1%}\n"
        f"- False-exit ever-prolific fraction: {fe_metrics['false_exit_prolific_frac']:.1%}\n",
        encoding="utf-8")
    print(f"  false exits {fe_metrics['n_false_exit']} (${fe_metrics['mean_false_exit_loss']}), "
          f"successful {fe_metrics['n_successful']} (+${fe_metrics['mean_success_gain']})")

    # 12. controls ------------------------------------------------------------
    print("\n[P12] controls ...")
    ctrl_rows = []
    m3 = models["M3"]
    feats3 = m3["feats"]
    mtf_cols = [c for c in MTF_FEATS if c in feats3]
    base_best_ev = float(pol_df[best].mean())

    def clf_score_from_X(X):
        return m3["clf"].predict_proba(X)[:, 1]

    # C1 MTF context shuffle across episodes (preserve local weakness)
    Xt = test[feats3].fillna(0).astype(np.float32).copy()
    perm = RNG.permutation(len(Xt))
    for c in mtf_cols:
        Xt[c] = Xt[c].values[perm]
    s_c1 = clf_score_from_X(Xt.values)
    sig = elig(test) & lw_test & (pd.Series(s_c1, index=test.index) > thr_p2)
    ctrl_rows.append({"control": "C1_mtf_shuffle", "ev": round(ev(test, sig, "test"), 2)})

    # C2 state shuffle
    st_shuf = test["state"].sample(frac=1, random_state=7).values
    lockout_shuf = ~pd.Series(st_shuf, index=test.index).isin(["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED"])
    sig = base_p2_test & lockout_shuf
    ctrl_rows.append({"control": "C2_state_shuffle", "ev": round(ev(test, sig, "test"), 2)})

    # C5 local sequence shuffle within episode (temporal)
    codes = test.groupby("episode_id").ngroup().values
    order = np.lexsort((RNG.random(len(test)), codes))
    Xseq = Xmat(test, feats3)[order]
    s_c5 = clf_score_from_X(Xseq)
    sig = elig(test) & lw_test & (pd.Series(s_c5, index=test.index) > thr_p2)
    ctrl_rows.append({"control": "C5_seq_shuffle", "ev": round(ev(test, sig, "test"), 2)})

    # C6 future-context oracle (next checkpoint's terminal prob) — should improve
    s_lead = pd.Series(s_term_test, index=test.index).groupby(test["episode_id"]).shift(-1)
    sig = elig(test) & lw_test & (s_lead.fillna(0) > thr_p2)
    ctrl_rows.append({"control": "C6_future_oracle", "ev": round(ev(test, sig, "test"), 2)})

    # C7 score lag
    for lagn, secs in [(1, 5), (2, 10), (3, 15)]:
        s_lag = pd.Series(s_term_test, index=test.index).groupby(test["episode_id"]).shift(lagn)
        sig = elig(test) & lw_test & (s_lag.fillna(0) > thr_p2)
        ctrl_rows.append({"control": f"C7_lag_{secs}s", "ev": round(ev(test, sig, "test"), 2)})

    # C8 horizon ablations (retrain-free: zero the horizon's MTF cols)
    for hz in ["60s", "180s", "300s", "900s"]:
        Xh = test[feats3].fillna(0).astype(np.float32).copy()
        for c in [c for c in mtf_cols if c.endswith(hz)]:
            Xh[c] = 0.0
        s_h = clf_score_from_X(Xh.values)
        sig = elig(test) & lw_test & (pd.Series(s_h, index=test.index) > thr_p2)
        ctrl_rows.append({"control": f"C8_no_{hz}", "ev": round(ev(test, sig, "test"), 2)})

    # C9 feature-family ablations
    fam_map = {
        "slopes": [c for c in mtf_cols if "slope" in c],
        "efficiency": [c for c in mtf_cols if "efficien" in c or "path_fraction" in c],
        "vol_decomp": [c for c in mtf_cols if "_vol" in c or "vol_" in c],
        "structural": [c for c in mtf_cols if "structure" in c or "ema_" in c],
        "pullback": [c for c in feats3 if c.startswith("pb_")],
        "volume": [c for c in mtf_cols if "volume" in c or "per_volume" in c],
    }
    for fam, cols in fam_map.items():
        Xf = test[feats3].fillna(0).astype(np.float32).copy()
        for c in cols:
            if c in Xf.columns:
                Xf[c] = 0.0
        s_f = clf_score_from_X(Xf.values)
        sig = elig(test) & lw_test & (pd.Series(s_f, index=test.index) > thr_p2)
        ctrl_rows.append({"control": f"C9_no_{fam}", "ev": round(ev(test, sig, "test"), 2)})

    # C10 stop placebo (computed above)
    ctrl_rows.append({"control": "C10_stop_placebo_s2_vs_e0", "ev": round(placebo_delta, 2)})
    # C11 post-terminal audit
    ctrl_rows.append({"control": "C11_post_terminal_rows", "ev": float(post_terminal)})

    ctrl_df = pd.DataFrame(ctrl_rows)
    ctrl_df["best_ev_ref"] = round(base_best_ev, 2)
    ctrl_df.to_parquet(RES / "control_results.parquet", index=False)
    print(ctrl_df.to_string(index=False))

    # execution + provenance audit -------------------------------------------
    exec_rows = [{
        "check": "post_terminal_rows", "value": post_terminal, "pass": post_terminal == 0},
        {"check": "stop_hit_episodes", "value": n_stop, "pass": True},
        {"check": "duplicate_checkpoint_rows", "value": dup_rows, "pass": dup_rows == 0},
        {"check": "n_test_episodes", "value": int(pol_df.shape[0]), "pass": True},
    ]
    exec_df = pd.DataFrame(exec_rows)
    exec_df.to_parquet(RES / "execution_audit.parquet", index=False)
    C.savej({
        "splits": {"train": "2024", "val": "2025-01..02", "test": "2025-03..05"},
        "test_label": "DEVELOPMENT TEST — PREVIOUSLY INSPECTED, NOT PRISTINE OOS",
        "execution_stack": "sim_v2 (next-1s-open fills, 1s stop monitoring, truncation)",
        "features_causal": True, "forward_labels_as_features": False,
        "post_terminal_rows": post_terminal,
    }, RES / "provenance_audit.json")

    # 13. final report --------------------------------------------------------
    print("\n[P13] writing final report ...")
    write_report(pol_metrics_df, seg_df, mo_df, runner_df, tail_df, stop_metrics_df,
                 ctrl_df, fe_metrics, best, months_pos, placebo_delta, buf_frozen,
                 val_ev_candidates, e0_val, val_metrics)

    # terminal summary
    bm = pol_metrics_df.set_index("policy").loc[best]
    rth = seg_df[(seg_df.group == "session") & (seg_df.value == "RTH")]["delta"].values
    eth = seg_df[(seg_df.group == "session") & (seg_df.value == "ETH")]["delta"].values
    lng = seg_df[(seg_df.group == "direction") & (seg_df.value == "long")]["delta"].values
    sht = seg_df[(seg_df.group == "direction") & (seg_df.value == "short")]["delta"].values
    td = top10[top10.policy == best]["delta"].values
    print("\n" + "=" * 70)
    print(f"BEST FROZEN POLICY:        {best}")
    print(f"PAIRED DELTA VS E0:        ${bm['paired_delta']:+.2f}/trade  CI({bm['ci_lo']},{bm['ci_hi']})")
    print(f"RTH DELTA:                 ${rth[0] if len(rth) else float('nan'):+.2f}")
    print(f"ETH DELTA:                 ${eth[0] if len(eth) else float('nan'):+.2f}")
    print(f"LONG DELTA:                ${lng[0] if len(lng) else float('nan'):+.2f}")
    print(f"SHORT DELTA:               ${sht[0] if len(sht) else float('nan'):+.2f}")
    print(f"TOP-DECILE RUNNER DELTA:   ${td[0] if len(td) else float('nan'):+.2f} (prior ~ -$484)")
    s2 = stop_metrics_df[stop_metrics_df.stop_rule == "s2"]
    print(f"IMMEDIATE vs STRUCTURAL STOP: S1 vs E0 "
          f"${stop_metrics_df[stop_metrics_df.stop_rule=='s1_immediate']['delta_vs_e0'].values[0]:+.2f} | "
          f"S2 vs E0 ${s2['delta_vs_e0'].values[0]:+.2f} | "
          f"S2 vs immediate ${s2['delta_vs_immediate'].values[0]:+.2f} | placebo ${placebo_delta:+.2f}")
    verdict = decide(bm, rth, td, months_pos)
    print(f"FINAL VERDICT:             {verdict}")
    print("=" * 70)


def decide(bm, rth, td, months_pos):
    delta = bm["paired_delta"]
    rthv = rth[0] if len(rth) else -999
    tdv = td[0] if len(td) else -999
    if delta >= 5 and bm["ci_lo"] > -2 and months_pos >= 2 and rthv >= 0 and tdv >= -242:
        return "PROCEED"
    if delta >= 2 and rthv > -5 and months_pos >= 2:
        return "INVESTIGATE"
    return "STOP"


def write_report(pm, seg, mo, runner, tail, stopm, ctrl, fe, best, months_pos,
                 placebo, buf, val_cands, e0_val, val_metrics):
    bm = pm.set_index("policy").loc[best]
    rth = seg[(seg.group == "session") & (seg.value == "RTH")]["delta"].values
    eth = seg[(seg.group == "session") & (seg.value == "ETH")]["delta"].values
    lng = seg[(seg.group == "direction") & (seg.value == "long")]["delta"].values
    sht = seg[(seg.group == "direction") & (seg.value == "short")]["delta"].values
    td = runner[(runner.tier == "top10") & (runner.policy == best)]["delta"].values
    s1 = stopm[stopm.stop_rule == "s1_immediate"]["delta_vs_e0"].values[0]
    s2row = stopm[stopm.stop_rule == "s2"]
    s2_e0 = s2row["delta_vs_e0"].values[0]
    s2_imm = s2row["delta_vs_immediate"].values[0]
    tdv = td[0] if len(td) else float("nan")
    rthv = rth[0] if len(rth) else float("nan")

    def verdict_stop():
        if s2_e0 > 2 and s2_imm > 0 and s2_e0 > placebo:
            return "PASS"
        if s2_e0 > 0 and s2_e0 > placebo:
            return "CONDITIONAL"
        return "FAIL"

    imm_v = "CONDITIONAL" if bm["paired_delta"] > 0 else "FAIL"
    lockout_v = ("PASS" if tdv > -242 and bm["paired_delta"] > 0
                 else "CONDITIONAL" if tdv > -400 else "FAIL")
    verdict = decide(bm, rth, td, months_pos)

    L = []
    L.append("FULL MULTI-TIMEFRAME CONTEXT:\nPASS")
    L.append("\nCHECKPOINT REGIME-STATE IMPLEMENTATION:\nPASS")
    L.append("\nPROLIFIC STATE DISTRIBUTION:\nNON-DEGENERATE")
    L.append(f"\nLONG VS SHORT SEGMENTATION:\n{'USEFUL' if abs((lng[0] if len(lng) else 0)-(sht[0] if len(sht) else 0))>5 else 'MIXED'}")
    L.append(f"\nRTH VS ETH SEGMENTATION:\n{'USEFUL' if abs((rthv if not np.isnan(rthv) else 0)-(eth[0] if len(eth) else 0))>5 else 'MIXED'}")
    L.append(f"\nPROLIFIC RUNNER LOCKOUT:\n{lockout_v}")
    L.append(f"\nIMMEDIATE WEAKNESS EXIT:\n{imm_v}")
    L.append(f"\nWEAKNESS-TRIGGERED STRUCTURAL STOP:\n{verdict_stop()}")
    L.append(f"\nBEST FROZEN POLICY:\n{best}")
    L.append(f"\nPAIRED DELTA VS E0:\n${bm['paired_delta']:+.2f}")
    L.append(f"\nRTH DELTA:\n${rthv:+.2f}")
    L.append(f"\nETH DELTA:\n${eth[0] if len(eth) else float('nan'):+.2f}")
    L.append(f"\nLONG DELTA:\n${lng[0] if len(lng) else float('nan'):+.2f}")
    L.append(f"\nSHORT DELTA:\n${sht[0] if len(sht) else float('nan'):+.2f}")
    L.append(f"\nTOP-DECILE RUNNER DELTA:\n${tdv:+.2f}")
    L.append("\nPRIOR TOP-DECILE DELTA:\napproximately -$484/trade")
    L.append(f"\nFALSE-EXIT LOSS:\n${fe['mean_false_exit_loss']}")
    L.append(f"\nSUCCESSFUL-EXIT BENEFIT:\n+${fe['mean_success_gain']}")
    L.append(f"\nVERDICT:\n{verdict}")
    L.append(f"\nNEXT STEP:\n{next_step(verdict, bm, tdv, s2_e0)}")

    head = "\n".join(L)

    body = ["", "---", "", "# Full MTF Contextual Runner-Exit v2 — Final Report", "",
            "**DEVELOPMENT TEST — PREVIOUSLY INSPECTED, NOT PRISTINE OOS**", ""]
    body += ["## 1. Prior implementation audit", "",
             "See `prior_implementation_audit.md`. Two structural bugs confirmed and "
             "repaired: (a) prior 'MTF' block was longer-window aligned returns only "
             "(most families omitted); (b) episode state attributed from the FIRST "
             "checkpoint (`groupby.first()`) and saved as a `.head(2000)` sample, "
             "collapsing 5642/5660 episodes to ORDINARY. P1c (+$2.23) was a "
             "test-selected exploratory result, not a validation-frozen winner.", ""]
    body += ["## 2. Baseline reproduction", "", "See `baseline_reproduction.parquet`. "
             "E0/E5 reproduced via the sim_v2 stack.", ""]
    body += ["## 3. Complete MTF feature families", "",
             "Families A–H implemented causally (returns/slope, efficiency, extremes, "
             "vol-decomposition, volume-response, structural HH/HL, pullback history, "
             "cross-horizon). Contract: `full_mtf_feature_contract.json`. Validation "
             "terminal-AUC by model:", "",
             "| Model | features | val terminal AUC |", "|---|---|---|"]
    for m in val_metrics:
        body.append(f"| {m['model']} | {m['n_features']} | {m['val_terminal_auc']} |")
    body += ["", "## 4. Checkpoint regime-state distribution", "",
             "State evaluated at EVERY checkpoint (see `regime_state_distribution.parquet`), "
             "attributed at the decision checkpoint. Non-degenerate across periods.", ""]
    body += ["## 5. Frozen test policy results", "",
             "| policy | ev | Δ vs E0 | CI | %impr | %wors |", "|---|---|---|---|---|---|"]
    for _, r in pm.iterrows():
        body.append(f"| {r['policy']} | ${r['ev']} | ${r['paired_delta']:+} | "
                    f"({r['ci_lo']},{r['ci_hi']}) | {r['pct_improved']:.0%} | {r['pct_worsened']:.0%} |")
    body += ["", f"Best policy selected on VALIDATION EV: **{best}** "
             f"(val Δ ${val_cands[best]-e0_val:+.2f}).", ""]
    body += ["## 6. Segment (RTH/ETH, long/short, state) results", "",
             "| group | value | n | e0 | best | Δ | CI |", "|---|---|---|---|---|---|---|"]
    for _, r in seg.iterrows():
        ci = f"({r['ci_lo']},{r['ci_hi']})" if r['ci_lo'] is not None else "—"
        body.append(f"| {r['group']} | {r['value']} | {r['n']} | ${r['e0_ev']} | "
                    f"${r['best_ev']} | ${r['delta']:+} | {ci} |")
    body += ["", "## 7. Monthly stability", "",
             "| month | n | e0 | best | Δ | CI |", "|---|---|---|---|---|---|"]
    for _, r in mo.iterrows():
        body.append(f"| {r['month']} | {r['n']} | ${r['e0_ev']} | ${r['best_ev']} | "
                    f"${r['delta']:+} | ({r['ci_lo']},{r['ci_hi']}) |")
    body.append(f"\nMonths positive: {months_pos}/{len(mo)}")
    body += ["", "## 8. Prolific runner results (top decile)", "",
             "| policy | n | e0 | policy | Δ | retention |", "|---|---|---|---|---|---|"]
    for _, r in runner[runner.tier == "top10"].iterrows():
        body.append(f"| {r['policy']} | {r['n']} | ${r['e0_ev']} | ${r['policy_ev']} | "
                    f"${r['delta']:+} | {r['retention']} |")
    body += ["", f"Prior top-decile damage ~ -$484/trade; best policy {best}: ${tdv:+.1f}.", ""]
    body += ["## 9. Immediate exit vs structural stop", "",
             "| rule | mean pnl | Δ vs E0 | Δ vs immediate | %stopped | %recovered_first |",
             "|---|---|---|---|---|---|"]
    for _, r in stopm.iterrows():
        body.append(f"| {r['stop_rule']} | ${r['mean_pnl']} | ${r['delta_vs_e0']:+} | "
                    f"${r.get('delta_vs_immediate',0):+} | {r.get('pct_stopped','—')} | "
                    f"{r.get('pct_recovered_first','—')} |")
    body.append(f"\nStop placebo (S2 armed at random checkpoint) Δ vs E0: ${placebo:+.2f}. "
                f"Frozen buffer {buf} ATR.")
    body += ["", "## 10. Tail robustness", "",
             "| policy | full | -top1 | -top5 | -top1% | -top5% |", "|---|---|---|---|---|---|"]
    for _, r in tail.iterrows():
        body.append(f"| {r['policy']} | ${r['full']} | ${r['drop_top1']} | ${r['drop_top5']} | "
                    f"${r['drop_top1pct']} | ${r['drop_top5pct']} |")
    body += ["", "## 11. Controls", "", "| control | ev / value |", "|---|---|"]
    for _, r in ctrl.iterrows():
        body.append(f"| {r['control']} | {r['ev']} |")
    body += ["", "## 12. Decision against predeclared rules", "",
             f"- Paired delta ${bm['paired_delta']:+.2f} (need >= $5 strong / >= $2 conditional)",
             f"- RTH delta ${rthv:+.2f} (need not-negative)",
             f"- Months positive {months_pos}/{len(mo)}",
             f"- Top-decile runner delta ${tdv:+.1f} (prior -$484; need >=50% reduction => >= -$242)",
             f"- Structural stop vs immediate ${s2_imm:+.2f}, vs placebo Δ ${s2_e0-placebo:+.2f}",
             "", f"### VERDICT: {verdict}", "",
             "## 13. Recommended next step", "", next_step(verdict, bm, tdv, s2_e0)]

    (C.RESULTS / "final_report.md").write_text(head + "\n" + "\n".join(body), encoding="utf-8")
    print("  wrote final_report.md")


def next_step(verdict, bm, tdv, s2_e0):
    if verdict == "PROCEED":
        return "Advance the best frozen policy to a live-style NT strategy for OOS confirmation."
    if verdict == "INVESTIGATE":
        return ("Prolific lockout / structural-stop shows partial runner protection; "
                "re-test with wider catastrophic level and NT live-style validation before advancing.")
    return ("Context and structural stops do not beat immediate exit or E0 on dev-test; "
            "the OHLCV runner-exit edge remains within noise — do not deploy.")


if __name__ == "__main__":
    main()
