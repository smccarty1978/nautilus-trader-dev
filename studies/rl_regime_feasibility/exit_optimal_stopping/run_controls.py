"""
Phase 11: Controls (fully vectorised — no per-episode loops).

  C1: Label shuffle — shuffle hold_advantage targets across EPISODES (by episode)
  C2: Within-trade feature-sequence shuffle — shuffle timestamps within each episode
  C3: Score lag — use score from T-1 step (5s lag)
  C4: Future-score positive control — train on T+1 features (leak confirmation)
  C6: Pullback-state shuffle — shuffle pullback features only
  C7: Feature-family removals
"""

import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import json
import numpy as np
import pandas as pd
import joblib
from lightgbm import LGBMRegressor

BASE_DIR  = Path("studies/rl_regime_feasibility")
OUT_DIR   = BASE_DIR / "exit_optimal_stopping/results"
MODEL_DIR = OUT_DIR / "models"

COMMISSION = 5.0


# ── Vectorised policy simulation ──────────────────────────────────────────────

def build_ep_base(df: pd.DataFrame) -> pd.DataFrame:
    """Per-episode metadata: period + regime fallback PnL."""
    first = df.sort_values("seconds_since_entry").groupby("episode_id").first()
    last  = df.sort_values("seconds_since_entry").groupby("episode_id").last()
    regime_pnl = first["total_pnl_hold_regime"].fillna(last["exit_now_pnl"])
    return pd.DataFrame({"period": first["period"], "regime_pnl": regime_pnl})


def simulate_v(df: pd.DataFrame, ep_base: pd.DataFrame,
               sig_col: str, cost_adj: float = 0.0) -> pd.Series:
    """
    Vectorised: first-signal per episode → sig_pnl, fallback → regime_pnl.
    Returns Series indexed by episode_id with pnl.
    """
    triggered = df[df[sig_col] == True]
    if len(triggered):
        fired = (triggered
                 .sort_values("seconds_since_entry")
                 .groupby("episode_id")[["exit_now_pnl"]]
                 .first()
                 .rename(columns={"exit_now_pnl": "sig_pnl"}))
    else:
        fired = pd.DataFrame(columns=["sig_pnl"])

    result = ep_base["regime_pnl"].copy() - cost_adj
    if len(fired):
        result.loc[fired.index] = fired["sig_pnl"] - cost_adj
    return result


def ev_by_period(pnl_series: pd.Series, period_series: pd.Series) -> dict:
    out = {}
    for p in ["val", "test"]:
        mask = period_series == p
        out[p] = float(pnl_series[mask].mean()) if mask.any() else float("nan")
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Phase 11: Controls (vectorised)")
    print("=" * 70)

    print("\nLoading data ...")
    df = pd.read_parquet(OUT_DIR / "exit_targets.parquet")
    df = df.sort_values(["episode_id", "seconds_since_entry"]).reset_index(drop=True)

    with open(OUT_DIR / "exit_feature_contract.json") as f:
        feats = [x for x in json.load(f)["features"] if x in df.columns]
    with open(OUT_DIR / "policy_thresholds.json") as f:
        thr = json.load(f)

    m4 = joblib.load(MODEL_DIR / "m4_fitted_q.pkl")["model"]
    print(f"  Checkpoints: {df.shape}, features: {len(feats)}")

    ep_base   = build_ep_base(df)
    period_ep = ep_base["period"]

    # Baseline E5 (fitted-Q, unmodified)
    X = df[feats].fillna(0).values
    df["_score_base"] = m4.predict(X)
    thr_m4 = thr["m4_fitted_q"]
    elig = df["seconds_since_entry"] >= 30
    df["sig_base"] = elig & (df["_score_base"] < thr_m4)
    pnl_base = simulate_v(df, ep_base, "sig_base")
    base_ev  = ev_by_period(pnl_base, period_ep)
    print(f"\nBaseline E5 EV: val={base_ev['val']:.2f}  test={base_ev['test']:.2f}")

    results = []

    # ── C1: Label (episode-level) shuffle ────────────────────────────────────
    print("\nC1: Label shuffle (episode-level) ...")
    rng = np.random.default_rng(42)
    train_mask = df["period"] == "train"

    # Map episode_id → shuffled episode_id for label assignment
    train_eps = df.loc[train_mask, "episode_id"].unique()
    shuffled_eps = train_eps.copy(); rng.shuffle(shuffled_eps)
    ep_label_map = dict(zip(train_eps, shuffled_eps))

    train_df = df[train_mask].copy()
    orig_id   = train_df["episode_id"].values
    shuffled_ep_ids = np.array([ep_label_map.get(e, e) for e in orig_id])
    # Join shuffled episode → shuffled hold_advantage
    ep_to_ha = df[train_mask].groupby("episode_id")["hold_advantage"].mean()
    shuffled_ha = pd.Series(shuffled_ep_ids, index=train_df.index).map(ep_to_ha)

    X_tr = train_df[feats].fillna(0).values
    y_shuf = shuffled_ha.fillna(0).values

    c1_mdl = LGBMRegressor(n_estimators=200, learning_rate=0.05, max_depth=4,
                            min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                            random_state=42, n_jobs=4, verbose=-1)
    c1_mdl.fit(X_tr, y_shuf)

    X_all = df[feats].fillna(0).values
    df["sig_c1"] = elig & (c1_mdl.predict(X_all) < thr_m4)
    pnl_c1 = simulate_v(df, ep_base, "sig_c1")
    ev_c1  = ev_by_period(pnl_c1, period_ep)
    results.append({"control": "C1_label_shuffle", **ev_c1,
                    "vs_base_val": ev_c1["val"] - base_ev["val"],
                    "vs_base_test": ev_c1["test"] - base_ev["test"]})
    print(f"  C1 EV: val={ev_c1['val']:.2f}  test={ev_c1['test']:.2f}  "
          f"(vs base: {ev_c1['val']-base_ev['val']:+.2f} / {ev_c1['test']-base_ev['test']:+.2f})")

    # ── C2: Within-trade feature-sequence shuffle (vectorised) ────────────────
    print("C2: Within-trade feature-sequence shuffle ...")
    rng2 = np.random.default_rng(456)
    shuf_df = df.copy()
    # Shuffle features within each episode: assign random rank per episode, sort
    ep_cumcount = df.groupby("episode_id").cumcount().astype(np.int32)
    ep_ngroup   = df.groupby("episode_id").ngroup().astype(np.int32)
    ep_len_arr  = df.groupby("episode_id")["episode_id"].transform("count").astype(np.int32).values
    rand_key    = rng2.uniform(size=len(df)).astype(np.float32)
    # Sort within episode by random key
    sort_primary   = ep_ngroup.values * 100_000 + ep_cumcount.values
    shuffle_within = np.argsort(
        ep_ngroup.values.astype(np.int64) * 1_000_000 + (rand_key * ep_len_arr).astype(np.int64)
    )
    # For each position in sorted order, take feature from shuffled row
    shuf_df.iloc[:, [df.columns.get_loc(f) for f in feats]] = (
        df[feats].values[shuffle_within]
    )
    X_shuf = shuf_df[feats].fillna(0).values
    df["sig_c2"] = elig & (m4.predict(X_shuf) < thr_m4)
    pnl_c2 = simulate_v(df, ep_base, "sig_c2")
    ev_c2  = ev_by_period(pnl_c2, period_ep)
    results.append({"control": "C2_seq_shuffle", **ev_c2,
                    "vs_base_val": ev_c2["val"] - base_ev["val"],
                    "vs_base_test": ev_c2["test"] - base_ev["test"]})
    print(f"  C2 EV: val={ev_c2['val']:.2f}  test={ev_c2['test']:.2f}  "
          f"(vs base: {ev_c2['val']-base_ev['val']:+.2f} / {ev_c2['test']-base_ev['test']:+.2f})")

    # ── C3: Score lag (5s) ────────────────────────────────────────────────────
    print("C3: Score lag (5s) ...")
    df["_score_lag"] = df.groupby("episode_id")["_score_base"].shift(1, fill_value=0)
    df["sig_c3"] = elig & (df["_score_lag"] < thr_m4)
    pnl_c3 = simulate_v(df, ep_base, "sig_c3")
    ev_c3  = ev_by_period(pnl_c3, period_ep)
    results.append({"control": "C3_lag_5s", **ev_c3,
                    "vs_base_val": ev_c3["val"] - base_ev["val"],
                    "vs_base_test": ev_c3["test"] - base_ev["test"]})
    print(f"  C3 EV: val={ev_c3['val']:.2f}  test={ev_c3['test']:.2f}  "
          f"(vs base: {ev_c3['val']-base_ev['val']:+.2f} / {ev_c3['test']-base_ev['test']:+.2f})")

    # ── C4: Future-score positive control ─────────────────────────────────────
    print("C4: Future-score positive control (EXPECTED: better than base) ...")
    df["_score_lead"] = df.groupby("episode_id")["_score_base"].shift(-1, fill_value=0)
    df["sig_c4"] = elig & (df["_score_lead"] < thr_m4)
    pnl_c4 = simulate_v(df, ep_base, "sig_c4")
    ev_c4  = ev_by_period(pnl_c4, period_ep)
    results.append({"control": "C4_future_lead", **ev_c4,
                    "vs_base_val": ev_c4["val"] - base_ev["val"],
                    "vs_base_test": ev_c4["test"] - base_ev["test"]})
    print(f"  C4 EV: val={ev_c4['val']:.2f}  test={ev_c4['test']:.2f}  "
          f"(vs base: {ev_c4['val']-base_ev['val']:+.2f} / {ev_c4['test']-base_ev['test']:+.2f})")

    # ── C6: Pullback features shuffle (vectorised) ────────────────────────────
    print("C6: Pullback feature shuffle ...")
    pb_feats = [f for f in feats if any(x in f for x in
                ["pullback", "pb_", "giveback", "secs_since_trade_peak"])]
    print(f"  Pullback features ({len(pb_feats)}): {pb_feats[:5]}...")
    shuf_pb = df.copy()
    # Shuffle pullback features across all checkpoints (global shuffle)
    for pf in pb_feats:
        shuf_pb[pf] = rng.permutation(shuf_pb[pf].values)
    X_pb = shuf_pb[feats].fillna(0).values
    df["sig_c6"] = elig & (m4.predict(X_pb) < thr_m4)
    pnl_c6 = simulate_v(df, ep_base, "sig_c6")
    ev_c6  = ev_by_period(pnl_c6, period_ep)
    results.append({"control": "C6_pullback_shuffle", **ev_c6,
                    "vs_base_val": ev_c6["val"] - base_ev["val"],
                    "vs_base_test": ev_c6["test"] - base_ev["test"]})
    print(f"  C6 EV: val={ev_c6['val']:.2f}  test={ev_c6['test']:.2f}  "
          f"(vs base: {ev_c6['val']-base_ev['val']:+.2f} / {ev_c6['test']-base_ev['test']:+.2f})")

    # ── C7: Feature-family removals ───────────────────────────────────────────
    print("C7: Feature-family removals ...")
    families = {
        "no_pullback": [f for f in feats if not any(x in f for x in
                        ["pullback", "pb_", "giveback", "secs_since_trade_peak"])],
        "no_slope":    [f for f in feats if not any(x in f for x in
                        ["slope", "decay", "kalman"])],
        "no_progress": [f for f in feats if not any(x in f for x in
                        ["progress", "efficiency", "path"])],
        "no_regime":   [f for f in feats if not any(x in f for x in
                        ["regime", "adx", "ema", "bollinger"])],
    }
    for fam_name, fam_feats in families.items():
        X_fam = df[fam_feats].fillna(0).values
        zeros_col = thr_m4 + 1  # score that won't trigger (above threshold)
        # Retrain on reduced feature set
        X_tr_fam = df.loc[train_mask, fam_feats].fillna(0).values
        y_tr_fam = df.loc[train_mask, "hold_advantage"].fillna(0).values
        fam_mdl = LGBMRegressor(n_estimators=200, learning_rate=0.05, max_depth=4,
                                min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                                random_state=42, n_jobs=4, verbose=-1)
        fam_mdl.fit(X_tr_fam, y_tr_fam)
        scores_fam = fam_mdl.predict(X_fam)
        sig_col_fam = f"sig_c7_{fam_name}"
        df[sig_col_fam] = elig & (scores_fam < thr_m4)
        pnl_fam = simulate_v(df, ep_base, sig_col_fam)
        ev_fam  = ev_by_period(pnl_fam, period_ep)
        results.append({"control": f"C7_{fam_name}", **ev_fam,
                        "vs_base_val": ev_fam["val"] - base_ev["val"],
                        "vs_base_test": ev_fam["test"] - base_ev["test"]})
        print(f"  C7 {fam_name}: val={ev_fam['val']:.2f}  test={ev_fam['test']:.2f}  "
              f"(vs base: {ev_fam['val']-base_ev['val']:+.2f} / {ev_fam['test']-base_ev['test']:+.2f})")

    # Save and print summary
    ctrl_df = pd.DataFrame(results)
    ctrl_df.to_parquet(OUT_DIR / "control_results.parquet", index=False)

    print("\n" + "=" * 70)
    print("CONTROL SUMMARY")
    print("=" * 70)
    print(f"  Baseline E5:     val={base_ev['val']:>8.2f}  test={base_ev['test']:>8.2f}")
    print(f"  {'Control':<30} {'val':>8}  {'test':>8}  {'Δval':>8}  {'Δtest':>8}  {'Verdict':>12}")
    print(f"  {'-'*30} {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*12}")
    for _, row in ctrl_df.iterrows():
        v  = row.get("val", float("nan"))
        t  = row.get("test", float("nan"))
        dv = row.get("vs_base_val", float("nan"))
        dt = row.get("vs_base_test", float("nan"))
        # Verdict logic
        if "C1" in row["control"]:
            verdict = "PASS(causal)" if abs(dv) > 10 else "FAIL(leak)"
        elif "C4" in row["control"]:
            verdict = "PASS(oracle)" if t > base_ev["test"] else "WARN"
        else:
            verdict = "OK" if abs(dv) > 5 else "FLAT"
        print(f"  {row['control']:<30} {v:>8.2f}  {t:>8.2f}  {dv:>+8.2f}  {dt:>+8.2f}  {verdict:>12}")

    print("\nPhase 11 complete.")


if __name__ == "__main__":
    main()
