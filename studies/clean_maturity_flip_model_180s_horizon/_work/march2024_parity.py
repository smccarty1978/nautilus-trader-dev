"""March 2024 bounded-window / restart / runtime-determinism parity validation.

Gates:
  1  candidate population parity  (bounded March run vs March slice of frozen full-year panel)
  2  all-13 feature parity
  3  frozen-model score parity     (native boosters + combined bundle; downstream of gate 2)
  4  first-P90 fire parity         (frozen TRAIN thresholds; first_crossing semantics; downstream)
  5  180s outcome parity           (label / flip_ts / seconds_to_flip / censoring)

Reference = March 1-31 slice of the committed full-year 2024 NT panel
            (oos_candidates_merged.parquet / oos_observations_merged.parquet).
Both paths are the governed generic NT collector -> this is restart/bounded-window
determinism, NOT a cross-implementation test.
"""
from __future__ import annotations
import json, sys
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
HIGHLIGHT = ["ema_slope", "arrival_velocity", "rolling_300s_retention_ratio",
             "rolling_300s_giveback_atr", "rolling_300s_current_progress_atr"]
SCORE_TOL = 1e-9          # predeclared strict LightGBM float tolerance
FEATURE_TOL = 1e-9
AGG = json.loads((S / "artifacts" / "train_experiment_freeze.json").read_text())
P90 = {"LONG": AGG["thresholds"]["LONG_C"]["p90"]["threshold"],
       "SHORT": AGG["thresholds"]["SHORT_C"]["p90"]["threshold"]}
MAR_LO = pd.Timestamp("2024-03-01", tz="UTC").value
MAR_HI = pd.Timestamp("2024-04-01", tz="UTC").value


def _march(df):
    return df[(df.observation_ts >= MAR_LO) & (df.observation_ts < MAR_HI)].copy()


def _load_ref():
    c = pd.read_parquet(S / "artifacts" / "oos_candidates_merged.parquet")
    o = pd.read_parquet(S / "artifacts" / "oos_observations_merged.parquet")
    return _march(c).reset_index(drop=True), _march(o).reset_index(drop=True)


def _load_nt():
    res = json.loads((S / "_work" / "march2024_bounded_collect_result.json").read_text())
    oa = res["run"]["output_artifacts"]
    c = pd.read_parquet(oa["candidates_parquet"])
    o = pd.read_parquet(oa["observations_parquet"])
    return _march(c).reset_index(drop=True), _march(o).reset_index(drop=True), res


def _key(df):
    return set(map(tuple, df[JOIN].to_numpy().tolist()))


def gate1_candidates(rc, nc):
    rk, nk = _key(rc), _key(nc)
    dup_n = int(nc.duplicated(JOIN).sum())
    dup_r = int(rc.duplicated(JOIN).sum())
    inter = rk & nk
    # direction / identity checks on the intersection
    rj = rc.set_index(JOIN)
    nj = nc.set_index(JOIN)
    dir_mismatch = 0
    if "regime_direction" in rc.columns and "regime_direction" in nc.columns:
        common = list(inter)
        rr = rj.loc[common, "regime_direction"] if common else pd.Series(dtype=float)
        nn = nj.loc[common, "regime_direction"] if common else pd.Series(dtype=float)
        dir_mismatch = int((rr.values != nn.values).sum())
    # timestamp retiming: same (regime_start_ns, checkpoint_index) but different observation_ts
    rc2 = rc[["regime_start_ns", "checkpoint_index", "observation_ts"]].rename(columns={"observation_ts": "ref_ts"})
    nc2 = nc[["regime_start_ns", "checkpoint_index", "observation_ts"]].rename(columns={"observation_ts": "nt_ts"})
    m = rc2.merge(nc2, on=["regime_start_ns", "checkpoint_index"], how="inner")
    retime = int((m.ref_ts != m.nt_ts).sum())
    return {
        "reference_candidates": len(rc), "nt_candidates": len(nc),
        "exact_matches": len(inter),
        "missing_in_nt": len(rk - nk), "extra_in_nt": len(nk - rk),
        "duplicate_nt_candidates": dup_n, "duplicate_reference_candidates": dup_r,
        "timestamp_mismatches_same_regime_checkpoint": retime,
        "direction_mismatches": dir_mismatch,
        "identity_mismatches": len(rk - nk) + len(nk - rk),
        "PASS": (rk == nk) and dup_n == 0 and dup_r == 0 and retime == 0 and dir_mismatch == 0,
        "examples_missing_in_nt": [list(x) for x in list(rk - nk)[:10]],
        "examples_extra_in_nt": [list(x) for x in list(nk - rk)[:10]],
    }


def gate2_features(rc, nc):
    m = rc.merge(nc, on=JOIN, how="inner", suffixes=("_ref", "_nt"), validate="one_to_one")
    detail = []
    per = {}
    worst = []
    for f in FEATS:
        a = pd.to_numeric(m[f + "_ref"], errors="coerce")
        b = pd.to_numeric(m[f + "_nt"], errors="coerce")
        both_null = int((a.isna() & b.isna()).sum())
        ref_null_nt_val = int((a.isna() & b.notna()).sum())
        ref_val_nt_null = int((a.notna() & b.isna()).sum())
        mask = a.notna() & b.notna()
        err = (a[mask] - b[mask]).abs()
        exact = int((err == 0).sum())
        n_cmp = int(mask.sum())
        rec = {
            "feature": f, "n_compared": n_cmp, "exact_matches": exact,
            "max_abs_error": float(err.max()) if n_cmp else 0.0,
            "median_abs_error": float(err.median()) if n_cmp else 0.0,
            "p99_abs_error": float(err.quantile(0.99)) if n_cmp else 0.0,
            "both_null": both_null, "ref_null_nt_value": ref_null_nt_val, "ref_value_nt_null": ref_val_nt_null,
            "within_tol": (float(err.max()) if n_cmp else 0.0) <= FEATURE_TOL and ref_null_nt_val == 0 and ref_val_nt_null == 0,
        }
        per[f] = rec
        detail.append(rec)
        if n_cmp and err.max() > FEATURE_TOL:
            ex = m.loc[mask].assign(abs_err=err).nlargest(3, "abs_err")
            worst.append({"feature": f, "examples": ex[JOIN + [f + "_ref", f + "_nt", "abs_err"]].to_dict("records")})
    mism = [f for f in FEATS if not per[f]["within_tol"]]
    pd.DataFrame(detail).to_parquet(VAL / "feature_parity_detail.parquet", index=False)
    return {
        "rows_compared": int(len(m)), "features_compared": len(FEATS), "13_of_13_compared": len(FEATS) == 13,
        "features_with_mismatches": mism,
        "highlight": {f: per[f] for f in HIGHLIGHT},
        "all_features": per,
        "worst_examples": worst,
        "PASS": len(mism) == 0,
    }, m


def _score(feat_df, direction):
    mid = {r["model_role"]: r["model_id"] for r in AGG["model_artifacts"]}[f"{direction}_C"]
    bst = lgb.Booster(model_file=str(S / "artifacts" / "models" / f"{mid}.booster.txt"))
    bundle = joblib.load(VAL / "frozen_180s_combined_bundle.joblib")[f"{direction}_C"]["estimator"]
    X = feat_df[FEATS].to_numpy(float)
    s_bst = bst.predict(X)
    s_bundle = bundle.predict_proba(X)[:, 1]
    return s_bst, s_bundle


def gate3_score(m):
    """m = merged matched candidates with *_ref / *_nt feature columns."""
    out = {}
    frames = {}
    for direction, sign in (("LONG", -1), ("SHORT", 1)):
        md = m[m["regime_direction_ref"] == sign].reset_index(drop=True)
        ref_feat = md[[c + "_ref" for c in FEATS]].rename(columns={c + "_ref": c for c in FEATS})
        nt_feat = md[[c + "_nt" for c in FEATS]].rename(columns={c + "_nt": c for c in FEATS})
        rs_b, rs_u = _score(ref_feat, direction)
        ns_b, ns_u = _score(nt_feat, direction)
        d_path = np.abs(rs_b - ns_b)                 # ref-features vs nt-features, same booster
        d_impl = np.abs(rs_b - rs_u)                 # booster vs combined-bundle, same features
        out[direction] = {
            "rows_compared": int(len(md)),
            "ref_vs_nt_features_same_booster": {
                "max_abs_score_delta": float(d_path.max()) if len(md) else 0.0,
                "median_abs_score_delta": float(np.median(d_path)) if len(md) else 0.0,
                "p99_abs_score_delta": float(np.quantile(d_path, 0.99)) if len(md) else 0.0,
                "mismatches_over_tolerance": int((d_path > SCORE_TOL).sum()),
            },
            "native_booster_vs_combined_bundle_same_features": {
                "max_abs_score_delta": float(d_impl.max()) if len(md) else 0.0,
                "mismatches_over_tolerance": int((d_impl > SCORE_TOL).sum()),
            },
        }
        frames[direction] = md.assign(ref_score=rs_b, nt_score=ns_b, abs_delta=d_path)[JOIN + ["ref_score", "nt_score", "abs_delta"]]
    pd.concat(frames.values(), ignore_index=True).to_parquet(VAL / "score_parity_detail.parquet", index=False)
    allpass = all(
        v["ref_vs_nt_features_same_booster"]["mismatches_over_tolerance"] == 0
        and v["native_booster_vs_combined_bundle_same_features"]["mismatches_over_tolerance"] == 0
        for v in out.values()
    )
    out["tolerance"] = SCORE_TOL
    out["PASS"] = allpass
    return out, frames


def _first_p90(df_dir, scores, direction):
    d = df_dir.assign(score=scores).sort_values(["regime_start_ns", "observation_ts"], kind="mergesort")
    armed = d[d.score >= P90[direction]]
    first = armed.groupby("regime_start_ns", sort=True, as_index=False).head(1)
    return first.set_index("regime_start_ns")


def gate4_first_p90(m):
    rows = []
    agg = {}
    for direction, sign in (("LONG", -1), ("SHORT", 1)):
        md = m[m["regime_direction_ref"] == sign].reset_index(drop=True)
        ref_feat = md[[c + "_ref" for c in FEATS]].rename(columns={c + "_ref": c for c in FEATS})
        nt_feat = md[[c + "_nt" for c in FEATS]].rename(columns={c + "_nt": c for c in FEATS})
        rs, _ = _score(ref_feat, direction)
        ns, _ = _score(nt_feat, direction)
        R = _first_p90(md[JOIN], rs, direction)
        N = _first_p90(md[JOIN], ns, direction)
        regimes = sorted(set(R.index) | set(N.index))
        eligible = md["regime_start_ns"].nunique()
        cnt = {"EXACT": 0, "NT_EARLY": 0, "NT_LATE": 0, "REFERENCE_ONLY": 0, "NT_ONLY": 0}
        for rg in regimes:
            r_ts = int(R.loc[rg, "observation_ts"]) if rg in R.index else None
            n_ts = int(N.loc[rg, "observation_ts"]) if rg in N.index else None
            if r_ts is not None and n_ts is not None:
                st = "EXACT" if r_ts == n_ts else ("NT_EARLY" if n_ts < r_ts else "NT_LATE")
            elif r_ts is not None:
                st = "REFERENCE_ONLY"
            else:
                st = "NT_ONLY"
            cnt[st] += 1
            rows.append({"direction": direction, "regime_id": int(rg),
                         "research_first_P90_ts": r_ts, "nt_first_P90_ts": n_ts,
                         "time_delta_seconds": ((n_ts - r_ts) / 1e9) if (r_ts and n_ts) else None,
                         "match_status": st})
        agg[direction] = {
            "eligible_regimes": int(eligible),
            "reference_regimes_with_fire": int(len(R)), "nt_regimes_with_fire": int(len(N)),
            "exact_first_fire_matches": cnt["EXACT"], "early_nt_fires": cnt["NT_EARLY"],
            "late_nt_fires": cnt["NT_LATE"], "reference_only_fires": cnt["REFERENCE_ONLY"],
            "nt_only_fires": cnt["NT_ONLY"],
            "PASS": cnt["NT_EARLY"] == cnt["NT_LATE"] == cnt["REFERENCE_ONLY"] == cnt["NT_ONLY"] == 0,
        }
    pd.DataFrame(rows).to_parquet(VAL / "first_p90_parity.parquet", index=False)
    agg["PASS"] = all(agg[d]["PASS"] for d in ("LONG", "SHORT"))
    return agg


def gate5_outcome(ro, no):
    cols = ["target_flip_within_horizon", "flip_ts", "time_to_flip_seconds", "censored", "censor_reason", "disposition"]
    cols = [c for c in cols if c in ro.columns and c in no.columns]
    m = ro[JOIN + cols].merge(no[JOIN + cols], on=JOIN, how="inner", suffixes=("_ref", "_nt"))
    def mm(c):
        a, b = m[c + "_ref"], m[c + "_nt"]
        if pd.api.types.is_numeric_dtype(a):
            a2 = pd.to_numeric(a, errors="coerce"); b2 = pd.to_numeric(b, errors="coerce")
            return int(((a2 != b2) & ~(a2.isna() & b2.isna())).sum())
        return int((a.astype(str) != b.astype(str)).sum())
    label_mm = mm("target_flip_within_horizon") if "target_flip_within_horizon" in cols else None
    flip_mm = mm("flip_ts") if "flip_ts" in cols else None
    ttf_mm = mm("time_to_flip_seconds") if "time_to_flip_seconds" in cols else None
    cens_mm = mm("censored") if "censored" in cols else None
    disp_mm = mm("disposition") if "disposition" in cols else None
    m.to_parquet(VAL / "outcome_parity.parquet", index=False)
    return {
        "matched_signals": int(len(m)),
        "target_label_mismatches": label_mm, "flip_timestamp_mismatches": flip_mm,
        "seconds_to_flip_mismatches": ttf_mm, "censoring_mismatches": cens_mm,
        "disposition_mismatches": disp_mm,
        "PASS": all(x in (0, None) for x in (label_mm, flip_mm, ttf_mm, cens_mm, disp_mm)),
    }


def main():
    rc, ro = _load_ref()
    nc, no, res = _load_nt()
    g1 = gate1_candidates(rc, nc)
    g2, m = gate2_features(rc, nc)
    # attach reference regime_direction (an observation column) for score/first-fire routing
    m = m.merge(ro[JOIN + ["regime_direction"]].rename(columns={"regime_direction": "regime_direction_ref"}),
                on=JOIN, how="left", validate="one_to_one")
    g3, _ = gate3_score(m)
    g4 = gate4_first_p90(m)
    g5 = gate5_outcome(ro, no)
    summary = {
        "validation_month": "2024-03-01 through 2024-03-31",
        "reference_panel": "March slice of oos_{candidates,observations}_merged.parquet (committed fa47c4e)",
        "nt_run_id": res["run"]["run_id"],
        "partition_provenance_sha256": res["provenance_sha256"],
        "warmup": {"requested_validation_interval": "2024-03-01..2024-03-31",
                   "warmup_interval_streamed": "2024-02-24..2024-03-01 (governed fixed 5 calendar days)",
                   "streamed_window": "2024-02-24..2024-04-01",
                   "first_nt_march_candidate_ts": int(nc.observation_ts.min()),
                   "first_ref_march_candidate_ts": int(rc.observation_ts.min())},
        "GATE_1_candidate_population": g1,
        "GATE_2_feature_parity": {k: v for k, v in g2.items() if k != "all_features"},
        "GATE_3_score_parity": g3,
        "GATE_4_first_p90_parity": g4,
        "GATE_5_outcome_parity": g5,
        "PARITY_HIERARCHY_PASS": all([g1["PASS"], g2["PASS"], g3["PASS"], g4["PASS"], g5["PASS"]]),
    }
    (VAL / "validation_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (VAL / "feature_parity_summary.json").write_text(json.dumps(g2, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: (v.get("PASS") if isinstance(v, dict) else v) for k, v in summary.items()
                      if k.startswith("GATE") or k == "PARITY_HIERARCHY_PASS"}, indent=2))
    for g, nm in ((g1, "G1"), (g2, "G2"), (g3, "G3"), (g4, "G4"), (g5, "G5")):
        print(nm, {kk: g[kk] for kk in list(g)[:8] if kk not in ("all_features", "highlight", "worst_examples", "examples_missing_in_nt", "examples_extra_in_nt")})


if __name__ == "__main__":
    main()
