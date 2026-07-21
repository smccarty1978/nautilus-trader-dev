"""
Phase 0b -- reproduce the reference baselines this study must beat.

Two things happen here, kept explicitly separate:
  1. E0, P1a (frozen-original threshold), P1b (freshly reselected threshold)
     are RECOMPUTED from scratch on the v3 prepared base data (independent of
     v2's saved artifacts) -- these only depend on LOCAL_CANDIDATES + sim_v2,
     so an honest independent reproduction is cheap and worthwhile.
  2. "P3 prior persistence" (v2's M3-terminal-classifier + persistence-K exit)
     is NOT re-derived from scratch here: v3 redefines P2/P3 semantics (P2 =
     global score-persistence, P3 = state-gated persistence) as separate,
     distinct policies built in build_policy_candidates.py. The v2 P3 number
     is therefore loaded as a REFERENCE (what v3 must beat / contextualize),
     not recomputed bit-for-bit. This is a documented conservative assumption.

Writes:
  results/baseline_reproduction.parquet
  results/baseline_parity_audit.json
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C
import sim_v2

PRIOR = {
    "E0_test": 6.36,
    "P1_fittedq_test": 5.19,
    "P1_fittedq_test_delta": -1.17,
    "P1_fittedq_rth_delta": -11.61,
    "P1_fittedq_eth_delta": 2.97,
    "P3_persist_test": 5.22,
    "P3_persist_test_delta": -1.14,
    "P3_persist_long_delta": 4.73,
    "P3_persist_short_delta": -7.06,
}

V2_THR_P1 = 125.23300123309254  # frozen_policy_config.json, v2


def train_m0(train_df):
    feats = [f for f in C.LOCAL_CANDIDATES if f in train_df.columns]
    X = C.Xmat(train_df, feats)
    y = train_df["hold_advantage"].fillna(0).values
    m = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                       min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                       random_state=42, n_jobs=4, verbose=-1)
    m.fit(X, y)
    return m, feats


def policy_pnl(df, sig, ep_base, ep_meta, bars):
    result = ep_base["e0_pnl"].copy()
    trig = df[sig.values if hasattr(sig, "values") else sig]
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


def main():
    print("=" * 70)
    print("Phase 0b -- reproduce baselines (E0, P1a frozen, P1b reselected)")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()

    ep_base = {}
    ep_meta = {}
    for tag, df in [("val", val), ("test", test)]:
        tt_p = tt[tt["period"] == tag]
        ep_base[tag] = sim_v2.build_ep_base(df, tt_p)
        ep_meta[tag] = C.make_ep_meta(df)

    def elig(df):
        return df["seconds_since_entry"] >= C.MIN_ELIG_S

    e0_test = float(ep_base["test"]["e0_pnl"].mean())
    e0_val = float(ep_base["val"]["e0_pnl"].mean())
    print(f"  E0 val=${e0_val:.2f}  test=${e0_test:.2f}  (prior test ${PRIOR['E0_test']})")

    m0, feats0 = train_m0(train)
    s_val = m0.predict(C.Xmat(val, feats0))
    s_test = m0.predict(C.Xmat(test, feats0))

    # P1a: frozen ORIGINAL threshold (from v2's frozen_policy_config.json),
    # applied to a freshly (identically) trained model -- no pickle survives
    # from v2, so "frozen" means "the threshold value is not re-selected here".
    sig_p1a_test = elig(test) & (pd.Series(s_test, index=test.index) < V2_THR_P1)
    pnl_p1a = policy_pnl(test, sig_p1a_test, ep_base["test"], ep_meta["test"], bars)
    ev_p1a = float(pnl_p1a.mean())

    # P1b: RESELECTED threshold -- independent grid search on validation only.
    best_ev, best_thr = -1e9, None
    for q in np.arange(10, 91, 5):
        thr = np.percentile(s_val, q)
        sig = elig(val) & (pd.Series(s_val, index=val.index) < thr)
        pnl = policy_pnl(val, sig, ep_base["val"], ep_meta["val"], bars)
        e = float(pnl.mean())
        if e > best_ev:
            best_ev, best_thr = e, thr
    thr_p1b = float(best_thr)
    sig_p1b_test = elig(test) & (pd.Series(s_test, index=test.index) < thr_p1b)
    pnl_p1b = policy_pnl(test, sig_p1b_test, ep_base["test"], ep_meta["test"], bars)
    ev_p1b = float(pnl_p1b.mean())

    print(f"  P1a (frozen thr={V2_THR_P1:.3f}): test EV=${ev_p1a:.2f}  delta=${ev_p1a - e0_test:+.2f}")
    print(f"  P1b (reselected thr={thr_p1b:.3f}): test EV=${ev_p1b:.2f}  delta=${ev_p1b - e0_test:+.2f}")

    # segment splits for P1a (RTH/ETH, long/short) -- confirms the reference
    ep_dir = ep_meta["test"]["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first()
    e0 = ep_base["test"]["e0_pnl"]

    def seg_delta(pnl_series, mask_ep_ids):
        idx = pnl_series.index.intersection(mask_ep_ids)
        return float((pnl_series.loc[idx] - e0.loc[idx]).mean())

    rth_eps = ep_rth[ep_rth == 1].index
    eth_eps = ep_rth[ep_rth != 1].index
    long_eps = ep_dir[ep_dir == 1].index
    short_eps = ep_dir[ep_dir == -1].index

    p1a_rth = seg_delta(pnl_p1a, rth_eps)
    p1a_eth = seg_delta(pnl_p1a, eth_eps)
    print(f"  P1a RTH delta=${p1a_rth:+.2f} (prior {PRIOR['P1_fittedq_rth_delta']})  "
          f"ETH delta=${p1a_eth:+.2f} (prior {PRIOR['P1_fittedq_eth_delta']})")

    # v2 P3_context_persist reference (loaded, NOT recomputed -- see docstring)
    v2_pm = pd.read_parquet(C.V2_RESULTS / "policy_metrics.parquet")
    v2_pt = pd.read_parquet(C.V2_RESULTS / "policy_trades.parquet").set_index("episode_id")
    p3_row = v2_pm[v2_pm["policy"] == "P3_context_persist"].iloc[0]
    p3_ev, p3_delta = float(p3_row["ev"]), float(p3_row["paired_delta"])

    v2_e0 = v2_pt["P0_E0"]
    v2_p3 = v2_pt["P3_context_persist"]
    common_idx = v2_p3.index.intersection(ep_dir.index)
    p3_long_delta = float((v2_p3.loc[long_eps.intersection(common_idx)] -
                           v2_e0.loc[long_eps.intersection(common_idx)]).mean())
    p3_short_delta = float((v2_p3.loc[short_eps.intersection(common_idx)] -
                            v2_e0.loc[short_eps.intersection(common_idx)]).mean())
    print(f"  v2 P3 (loaded, reference only): ev=${p3_ev:.2f} delta=${p3_delta:+.2f}  "
          f"long=${p3_long_delta:+.2f} (prior {PRIOR['P3_persist_long_delta']})  "
          f"short=${p3_short_delta:+.2f} (prior {PRIOR['P3_persist_short_delta']})")

    rep_rows = [
        {"period": "test", "policy": "E0_regime", "ev": round(e0_test, 2),
         "source": "recomputed_v3"},
        {"period": "val", "policy": "E0_regime", "ev": round(e0_val, 2),
         "source": "recomputed_v3"},
        {"period": "test", "policy": "P1a_frozen_original", "ev": round(ev_p1a, 2),
         "delta_vs_e0": round(ev_p1a - e0_test, 2), "threshold": V2_THR_P1,
         "source": "recomputed_v3 (frozen v2 threshold, freshly-trained identical model)"},
        {"period": "test", "policy": "P1b_reselected_baseline", "ev": round(ev_p1b, 2),
         "delta_vs_e0": round(ev_p1b - e0_test, 2), "threshold": thr_p1b,
         "source": "recomputed_v3 (independent validation reselection)"},
        {"period": "test", "policy": "P3_context_persist_v2reference", "ev": round(p3_ev, 2),
         "delta_vs_e0": round(p3_delta, 2),
         "source": "loaded_from_v2 (NOT recomputed -- v3 redefines P2/P3 semantics; "
                    "see build_policy_candidates.py)"},
    ]
    rep_df = pd.DataFrame(rep_rows)
    rep_df.to_parquet(C.RESULTS / "baseline_reproduction.parquet", index=False)

    def parity(repro, prior, tol=1.5):
        d = abs(repro - prior)
        return {"reproduced": round(repro, 2), "prior": prior, "abs_diff": round(d, 2),
                "parity": "OK" if d <= tol else "CHECK"}

    audit = {
        "E0_test": parity(e0_test, PRIOR["E0_test"]),
        "P1a_test": parity(ev_p1a, PRIOR["P1_fittedq_test"]),
        "P1a_test_delta": parity(ev_p1a - e0_test, PRIOR["P1_fittedq_test_delta"]),
        "P1a_rth_delta": parity(p1a_rth, PRIOR["P1_fittedq_rth_delta"], tol=3.0),
        "P1a_eth_delta": parity(p1a_eth, PRIOR["P1_fittedq_eth_delta"], tol=3.0),
        "P1b_test": parity(ev_p1b, PRIOR["P1_fittedq_test"]),
        "P3_v2reference_note": "loaded from v2 policy_metrics.parquet, not independently "
                                "recomputed -- v3's P2/P3 are redefined (see build_policy_candidates.py)",
        "P3_v2reference_ev": parity(p3_ev, PRIOR["P3_persist_test"]),
        "P3_v2reference_delta": parity(p3_delta, PRIOR["P3_persist_test_delta"]),
        "P3_v2reference_long_delta": parity(p3_long_delta, PRIOR["P3_persist_long_delta"], tol=1.5),
        "P3_v2reference_short_delta": parity(p3_short_delta, PRIOR["P3_persist_short_delta"], tol=1.5),
        "P1a_vs_P1b_identical": bool(abs(V2_THR_P1 - thr_p1b) < 1e-6),
        "note_on_P1a_P1b": (
            "P1a and P1b use independent code paths (frozen literal threshold vs "
            "fresh validation grid search) but are expected to coincide numerically "
            "because the training data, features, hyperparameters and random_state "
            "are unchanged from v2 -- this is reported explicitly rather than "
            "silently reusing one number for both, per the spec's requirement to "
            "keep them distinct."
        ),
    }
    C.savej(audit, C.RESULTS / "baseline_parity_audit.json")
    print(rep_df.to_string(index=False))
    print("done.")


if __name__ == "__main__":
    main()
