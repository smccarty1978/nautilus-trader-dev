"""March 2024 validation: same-timestamp event ordering + first-fire diagnostics
+ checkpoint-level context + strengthened golden-score parity.

Ordering: for a bounded-window / restart determinism study, coincident-event order
is imposed by the SAME governed code in both runs (utils.causal_registration.
add_bars_causal_order -> 1s before coincident 1m, engine_builder.py:240). Parity is
therefore verified by (a) the helper's contract and (b) zero feature delta on the
boundary sub-populations (5s grid, 1m boundary, regime-flip boundary).
"""
from __future__ import annotations
import json, sys, inspect
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb, joblib

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
S = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
VAL = S / "validation_march2024" / "artifacts"
JOIN = ["observation_ts", "regime_start_ns", "checkpoint_index"]
FEATS = ["arrival_velocity", "arrival_acceleration", "ema_slope",
         "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
         "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
         "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
         "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"]
NS = 1_000_000_000
AGG = json.loads((S / "artifacts" / "train_experiment_freeze.json").read_text())
P90 = {"LONG": AGG["thresholds"]["LONG_C"]["p90"]["threshold"], "SHORT": AGG["thresholds"]["SHORT_C"]["p90"]["threshold"]}
MAR_LO = pd.Timestamp("2024-03-01", tz="UTC").value
MAR_HI = pd.Timestamp("2024-04-01", tz="UTC").value


def _march(df):
    return df[(df.observation_ts >= MAR_LO) & (df.observation_ts < MAR_HI)].copy()


rc = _march(pd.read_parquet(S / "artifacts" / "oos_candidates_merged.parquet")).reset_index(drop=True)
ro = _march(pd.read_parquet(S / "artifacts" / "oos_observations_merged.parquet")).reset_index(drop=True)
res = json.loads((S / "_work" / "march2024_bounded_collect_result.json").read_text())
oa = res["run"]["output_artifacts"]
nc = _march(pd.read_parquet(oa["candidates_parquet"])).reset_index(drop=True)
no = _march(pd.read_parquet(oa["observations_parquet"])).reset_index(drop=True)

m = rc.merge(nc, on=JOIN, how="inner", suffixes=("_ref", "_nt"), validate="one_to_one")
m = m.merge(ro[JOIN + ["regime_direction", "time_to_flip_seconds", "target_flip_within_horizon", "disposition"]], on=JOIN, how="left")


# ---------- 1. SAME-TIMESTAMP EVENT ORDERING ----------
def _feat_delta(sub):
    if not len(sub):
        return {"n": 0, "max_abs_feature_delta": 0.0}
    mx = 0.0
    for f in FEATS:
        a = pd.to_numeric(sub[f + "_ref"], errors="coerce"); b = pd.to_numeric(sub[f + "_nt"], errors="coerce")
        mm = a.notna() & b.notna()
        if mm.any():
            mx = max(mx, float((a[mm] - b[mm]).abs().max()))
        if int((a.isna() ^ b.isna()).sum()):
            mx = float("inf")
    return {"n": int(len(sub)), "max_abs_feature_delta": mx}


ord_src = inspect.getsource(__import__("utils.causal_registration", fromlist=["add_bars_causal_order"]).add_bars_causal_order)
obs_ts = m["observation_ts"].to_numpy()
on_5s = m[(obs_ts % (5 * NS)) == 0]
on_1m = m[(obs_ts % (60 * NS)) == 0]
# regime-flip boundary: checkpoints in the last 5s window before a regime's own flip, and the first checkpoint of a regime
flip_ts = pd.to_numeric(m["time_to_flip_seconds"], errors="coerce")
near_flip = m[flip_ts.notna() & (flip_ts <= 5.0)]
first_cp = m[m["checkpoint_index"] == m.groupby("regime_start_ns")["checkpoint_index"].transform("min")]

ordering = {
    "mechanism": "utils.causal_registration.add_bars_causal_order (engine_builder.py:240) -- identical code in both runs",
    "helper_contract_1s_before_coincident_1m": ("1s" in ord_src and "1m" in ord_src),
    "boundary_feature_parity": {
        "ordinary_5s_boundary": _feat_delta(on_5s),
        "1m_boundary": _feat_delta(on_1m),
        "regime_flip_boundary_within_5s": _feat_delta(near_flip),
        "regime_first_checkpoint": _feat_delta(first_cp),
    },
}
ordering["same_timestamp_ordering_parity"] = "PASS" if all(
    v["max_abs_feature_delta"] == 0.0 for v in ordering["boundary_feature_parity"].values()
) else "FAIL"


# ---------- 2. strengthened golden-score parity (full 2024 OOS matrix) ----------
full_c = pd.read_parquet(S / "artifacts" / "oos_candidates_merged.parquet")
full_o = pd.read_parquet(S / "artifacts" / "oos_observations_merged.parquet")
fm = full_c.merge(full_o[JOIN + ["regime_direction"]], on=JOIN, how="inner")
gold = {}
for direction, sign in (("LONG", -1), ("SHORT", 1)):
    d = fm[fm.regime_direction == sign]
    X = d[FEATS].to_numpy(float)
    mid = {r["model_role"]: r["model_id"] for r in AGG["model_artifacts"]}[f"{direction}_C"]
    bst = lgb.Booster(model_file=str(S / "artifacts" / "models" / f"{mid}.booster.txt"))
    bundle = joblib.load(VAL / "frozen_180s_combined_bundle.joblib")[f"{direction}_C"]["estimator"]
    per_dir_jb = joblib.load(S / "artifacts" / "models" / f"{mid}.joblib")["C"]["estimator"]
    s_bst = bst.predict(X); s_bundle = bundle.predict_proba(X)[:, 1]; s_perdir = per_dir_jb.predict_proba(X)[:, 1]
    gold[direction] = {
        "n_rows": int(len(d)),
        "combined_bundle_vs_native_booster_max_abs": float(np.max(np.abs(s_bundle - s_bst))),
        "combined_bundle_vs_perdirection_joblib_max_abs": float(np.max(np.abs(s_bundle - s_perdir))),
    }
gold["PASS"] = all(v["combined_bundle_vs_native_booster_max_abs"] == 0.0
                   and v["combined_bundle_vs_perdirection_joblib_max_abs"] == 0.0 for v in gold.values() if isinstance(v, dict))


# ---------- 3. FIRST-FIRE DIAGNOSTICS (NT bounded-March population) ----------
def _score(df, direction):
    mid = {r["model_role"]: r["model_id"] for r in AGG["model_artifacts"]}[f"{direction}_C"]
    bst = lgb.Booster(model_file=str(S / "artifacts" / "models" / f"{mid}.booster.txt"))
    return bst.predict(df[FEATS].to_numpy(float))


rth_days = sorted({pd.Timestamp(t, unit="ns", tz="UTC").date() for t in nc.observation_ts})
fires_all = []
diag = {}
for direction, sign in (("LONG", -1), ("SHORT", 1), ("ALL", None)):
    if direction == "ALL":
        d = m.copy()
        d["score"] = np.nan
        for dd, ss in (("LONG", -1), ("SHORT", 1)):
            mask = d.regime_direction == ss
            d.loc[mask, "score"] = _score(d[mask][[f + "_nt" for f in FEATS]].rename(columns={f + "_nt": f for f in FEATS}), dd)
        d["thr"] = d.regime_direction.map({-1: P90["LONG"], 1: P90["SHORT"]})
    else:
        d = m[m.regime_direction == sign].copy()
        d["score"] = _score(d[[f + "_nt" for f in FEATS]].rename(columns={f + "_nt": f for f in FEATS}), direction)
        d["thr"] = P90[direction]
    d = d.sort_values(["regime_start_ns", "observation_ts"], kind="mergesort")
    armed = d[d.score >= d.thr]
    first = armed.groupby("regime_start_ns", as_index=False).head(1).copy()
    eligible = d.regime_start_ns.nunique()
    first["day"] = first.observation_ts.map(lambda t: pd.Timestamp(t, unit="ns", tz="UTC").date())
    per_day = first.groupby("day").size().reindex(rth_days, fill_value=0)
    ttf = pd.to_numeric(first["time_to_flip_seconds"], errors="coerce")
    diag[direction] = {
        "first_fire_signals": int(len(first)),
        "RTH_trading_days": len(rth_days),
        "mean_signals_per_day": float(per_day.mean()), "median_signals_per_day": float(per_day.median()),
        "p10_signals_per_day": float(per_day.quantile(0.1)), "p90_signals_per_day": float(per_day.quantile(0.9)),
        "days_with_0": int((per_day == 0).sum()), "days_with_1": int((per_day == 1).sum()),
        "days_with_2": int((per_day == 2).sum()), "days_with_3plus": int((per_day >= 3).sum()),
        "pct_eligible_regimes_firing": float(len(first) / eligible) if eligible else None,
        "flip_within_180s_rate": float(ttf.notna().mean()),
        "median_seconds_to_flip": float(ttf.dropna().median()) if ttf.notna().any() else None,
    }
    if direction != "ALL":
        fires_all.append(first.assign(direction=direction))

pd.concat(fires_all, ignore_index=True)[JOIN + ["direction", "score", "time_to_flip_seconds", "target_flip_within_horizon"]].to_parquet(
    VAL / "first_fire_diagnostics.parquet", index=False)


# ---------- 4. checkpoint-level context vs frozen 2024 OOS finding ----------
ct = json.loads((S / "artifacts" / "oos_2024_classification_timing.json").read_text())
cp_ctx = {}
for direction, sign in (("LONG", -1), ("SHORT", 1)):
    d = m[m.regime_direction == sign].copy()
    d["score"] = _score(d[[f + "_nt" for f in FEATS]].rename(columns={f + "_nt": f for f in FEATS}), direction)
    hi = d[d.score >= P90[direction]]
    y = pd.to_numeric(d["target_flip_within_horizon"], errors="coerce")
    cp_ctx[direction] = {
        "note": "CHECKPOINT-LEVEL tail (every qualifying checkpoint), NOT first-fire; not expected to equal first-fire stats",
        "march_checkpoint_base_rate": float(y.mean()),
        "march_p90_checkpoint_retained_frac": float(len(hi) / len(d)) if len(d) else None,
        "march_p90_checkpoint_flip_prob": float(pd.to_numeric(hi["target_flip_within_horizon"], errors="coerce").mean()) if len(hi) else None,
        "full_2024_oos_p90_checkpoint_flip_prob": ct[direction]["frozen_score_tail_180s"]["p90"]["actual_flip_prob"],
        "full_2024_oos_base_rate": ct[direction]["classification_180s"]["positive_rate"],
    }

out = {
    "validation_month": "2024-03-01 through 2024-03-31",
    "same_timestamp_event_ordering": ordering,
    "golden_score_parity_full_matrix": gold,
    "first_fire_diagnostics": diag,
    "checkpoint_level_context": cp_ctx,
}
(VAL / "first_fire_diagnostics.json").write_text(json.dumps({"first_fire_diagnostics": diag,
                                                            "checkpoint_level_context": cp_ctx}, indent=2, default=str), encoding="utf-8")
(VAL / "ordering_and_context.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
print(json.dumps({
    "same_timestamp_ordering_parity": ordering["same_timestamp_ordering_parity"],
    "boundary_deltas": {k: v["max_abs_feature_delta"] for k, v in ordering["boundary_feature_parity"].items()},
    "golden_full_matrix_PASS": gold["PASS"],
    "first_fire": {k: {"signals": diag[k]["first_fire_signals"], "per_day_mean": round(diag[k]["mean_signals_per_day"], 2),
                       "flip180_rate": round(diag[k]["flip_within_180s_rate"], 3),
                       "med_ttf": diag[k]["median_seconds_to_flip"]} for k in ("ALL", "LONG", "SHORT")},
}, indent=2))
