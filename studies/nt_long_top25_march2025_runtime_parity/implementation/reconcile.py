"""Phases 1-3 reconciliation: candidate population, features, logistic score.

Phase 1 : live vs offline candidate population on the canonical key
          (regime_id + observation_ts), with per-regime detail and timestamp
          displacement buckets for symmetric-difference rows.
Phase 2 : all 25 frozen features on exactly-matched rows.
Phase 3 : logit / probability / per-feature contribution attribution, comparing
          the frozen offline reference, the live joblib path, and the live
          explicit-formula path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

NS = 1_000_000_000
BUCKETS = [(0, 0, "0s"), (1, 1, "+/-1s"), (2, 5, "+/-2-5s"),
           (6, 30, "+/-6-30s"), (31, 10**9, ">30s")]


def bucket(delta_s: float) -> str:
    a = abs(delta_s)
    for lo, hi, name in BUCKETS:
        if lo <= a <= hi:
            return name
    return ">30s"


def main(tag: str = "layerA") -> None:
    live = pd.read_parquet(C.WORK / f"candidate_ledger_live_{tag}.parquet")
    off = pd.read_parquet(C.WORK / "offline_reference_march_2025.parquet")
    feats = pd.read_csv(C.FEATURE_ORDER_PATH)["feature_name"].tolist()

    elig = live[live["final_candidate_eligible"]].copy()

    # ---------------- Phase 1: population ----------------
    ok = set(zip(off["regime_start_ns"], off["observation_time"]))
    lk = set(zip(elig["regime_id"], elig["observation_ts"]))
    matched, off_only, live_only = ok & lk, ok - lk, lk - ok

    off_reg, live_reg = set(off["regime_start_ns"]), set(elig["regime_id"])
    off_cnt = off.groupby("regime_start_ns").size()
    live_cnt = elig.groupby("regime_id").size()
    shared = sorted(off_reg & live_reg)
    exact_rowcount = sum(1 for r in shared if off_cnt.get(r, 0) == live_cnt.get(r, 0))

    # checkpoint-index-set parity per regime
    off_ci = off.groupby("regime_start_ns")["checkpoint_index"].apply(set)
    live_ci = elig.groupby("regime_id")["checkpoint_index"].apply(set)
    exact_ci = sum(1 for r in shared if off_ci.get(r, set()) == live_ci.get(r, set()))

    per_regime = pd.DataFrame([{
        "regime_id": r,
        "offline_rows": int(off_cnt.get(r, 0)), "live_rows": int(live_cnt.get(r, 0)),
        "row_diff": int(live_cnt.get(r, 0) - off_cnt.get(r, 0)),
        "checkpoint_index_set_equal": off_ci.get(r, set()) == live_ci.get(r, set()),
    } for r in sorted(off_reg | live_reg)])
    per_regime.to_csv(C.RESULTS / "candidate_reconciliation_per_regime.csv", index=False)

    # displacement analysis for symmetric-difference rows
    disp = []
    live_by_reg = {r: np.sort(g["observation_ts"].to_numpy())
                   for r, g in elig.groupby("regime_id")}
    off_by_reg = {r: np.sort(g["observation_time"].to_numpy())
                  for r, g in off.groupby("regime_start_ns")}
    for side, rows, counterpart in (("offline_only", off_only, live_by_reg),
                                    ("live_only", live_only, off_by_reg)):
        for rid, ts in rows:
            arr = counterpart.get(rid)
            if arr is None or not len(arr):
                disp.append({"side": side, "regime_id": rid, "observation_ts": ts,
                             "nearest_counterpart_ts": None, "delta_s": None,
                             "bucket": "no counterpart", "checkpoint_displacement": None})
                continue
            j = int(np.argmin(np.abs(arr - ts)))
            d = (int(arr[j]) - int(ts)) / NS
            disp.append({"side": side, "regime_id": rid, "observation_ts": ts,
                         "nearest_counterpart_ts": int(arr[j]), "delta_s": d,
                         "bucket": bucket(d),
                         "checkpoint_displacement": int(round(d / 5.0))})
    disp_df = pd.DataFrame(disp)
    if len(disp_df):
        disp_df.to_csv(C.RESULTS / "candidate_symmetric_difference.csv", index=False)

    phase1 = {
        "offline_eligible": int(len(off)), "live_eligible": int(len(elig)),
        "abs_difference": int(len(elig) - len(off)),
        "pct_difference": round(100.0 * (len(elig) - len(off)) / max(1, len(off)), 4),
        "exact_key_matches": int(len(matched)),
        "pct_of_offline_matched": round(100.0 * len(matched) / max(1, len(ok)), 4),
        "offline_only_rows": int(len(off_only)), "live_only_rows": int(len(live_only)),
        "offline_regimes": int(len(off_reg)), "live_regimes": int(len(live_reg)),
        "offline_only_regimes": sorted(off_reg - live_reg),
        "live_only_regimes": sorted(live_reg - off_reg),
        "shared_regimes": int(len(shared)),
        "regimes_with_exact_row_counts": exact_ci and int(exact_rowcount),
        "regimes_with_exact_checkpoint_index_sets": int(exact_ci),
        "displacement_buckets": (disp_df["bucket"].value_counts().to_dict()
                                 if len(disp_df) else {}),
    }

    # ---------------- Phase 2: features ----------------
    okey = off.set_index(["regime_start_ns", "observation_time"])
    lkey = elig.set_index(["regime_id", "observation_ts"])
    common_idx = okey.index.intersection(lkey.index)
    o2, l2 = okey.loc[common_idx], lkey.loc[common_idx]

    frows = []
    for f in feats:
        a = pd.to_numeric(o2[f], errors="coerce").to_numpy(float)
        b = pd.to_numeric(l2[f"feat__{f}"], errors="coerce").to_numpy(float)
        an, bn = np.isnan(a), np.isnan(b)
        both = ~an & ~bn
        d = np.abs(a[both] - b[both])
        frows.append({
            "feature": f, "matched_rows": int(len(a)),
            "exact_matches": int((d <= C.TOL_FEATURE).sum()),
            "mismatches": int((d > C.TOL_FEATURE).sum() + (an != bn).sum()),
            "offline_missing": int(an.sum()), "live_missing": int(bn.sum()),
            "missing_mask_agrees": int((an == bn).sum()),
            "max_abs_diff": float(d.max()) if d.size else 0.0,
            "mean_abs_diff": float(d.mean()) if d.size else 0.0,
            "p99_abs_diff": float(np.percentile(d, 99)) if d.size else 0.0,
            "status": "PASS" if (d.size and d.max() <= C.TOL_FEATURE
                                 and (an == bn).all()) else "FAIL",
        })
    fsum = pd.DataFrame(frows)
    fsum.to_csv(C.RESULTS / "feature_parity_summary.csv", index=False)

    # long-form per-feature rows, capped so the artifact stays reviewable
    long_rows = []
    for f in feats:
        a = pd.to_numeric(o2[f], errors="coerce").to_numpy(float)
        b = pd.to_numeric(l2[f"feat__{f}"], errors="coerce").to_numpy(float)
        d = np.abs(a - b)
        bad = np.where(~(d <= C.TOL_FEATURE) & ~(np.isnan(a) & np.isnan(b)))[0][:200]
        for i in bad:
            long_rows.append({
                "feature": f, "regime_id": common_idx[i][0],
                "observation_ts": common_idx[i][1],
                "offline_raw_value": a[i], "live_raw_value": b[i],
                "absolute_difference": float(d[i]),
                "offline_missing": bool(np.isnan(a[i])), "live_missing": bool(np.isnan(b[i])),
                "latest_source_ts_used": int(l2["latest_source_ts_used"].to_numpy()[i]),
            })
    pd.DataFrame(long_rows).to_csv(C.RESULTS / "feature_parity.csv", index=False)

    # ---------------- Phase 3: score ----------------
    sc_off = o2["score"].to_numpy(float)
    sc_live = l2["score"].to_numpy(float)
    sc_expl = l2["score_explicit"].to_numpy(float)
    logit_live = l2["logit"].to_numpy(float)
    logit_from_off = np.log(sc_off / (1.0 - sc_off))

    def stats(a, b, tol):
        d = np.abs(a - b)
        return {"n": int(len(d)), "max_abs_diff": float(d.max()) if d.size else 0.0,
                "mean_abs_diff": float(d.mean()) if d.size else 0.0,
                "p99_abs_diff": float(np.percentile(d, 99)) if d.size else 0.0,
                "n_above_tolerance": int((d > tol).sum()), "tolerance": tol,
                "status": "PASS" if d.size and d.max() <= tol else "FAIL"}

    phase3 = {
        "probability_live_joblib_vs_offline": stats(sc_live, sc_off, C.TOL_PROBA),
        "probability_live_explicit_vs_offline": stats(sc_expl, sc_off, C.TOL_PROBA),
        "probability_explicit_vs_joblib": stats(sc_expl, sc_live, C.TOL_PROBA),
        "logit_live_vs_offline_implied": stats(logit_live, logit_from_off, C.TOL_LOGIT),
    }
    pd.DataFrame({
        "regime_id": [i[0] for i in common_idx],
        "observation_ts": [i[1] for i in common_idx],
        "offline_probability": sc_off, "live_probability_joblib": sc_live,
        "live_probability_explicit": sc_expl, "live_logit": logit_live,
        "offline_implied_logit": logit_from_off,
        "abs_diff_joblib": np.abs(sc_live - sc_off),
        "abs_diff_explicit": np.abs(sc_expl - sc_off),
    }).to_csv(C.RESULTS / "score_parity.csv", index=False)

    contrib_cols = [f"contrib__{f}" for f in feats]
    contrib = l2[contrib_cols].copy()
    contrib.columns = feats
    contrib = contrib.reset_index()
    contrib["intercept"] = json.loads(C.INTERCEPT_PATH.read_text())["intercept"]
    contrib["sum_contributions"] = l2[contrib_cols].sum(axis=1).to_numpy()
    contrib["logit"] = logit_live
    contrib["probability"] = sc_live
    contrib.to_csv(C.RESULTS / "score_contributions.csv", index=False)

    out = {"tag": tag, "phase1_population": phase1,
           "phase2_features": {
               "n_matched_rows": int(len(common_idx)),
               "features_passing": int((fsum["status"] == "PASS").sum()),
               "features_failing": int((fsum["status"] == "FAIL").sum()),
               "worst_feature": (fsum.sort_values("max_abs_diff", ascending=False)
                                 .iloc[0][["feature", "max_abs_diff"]].to_dict()
                                 if len(fsum) else None),
               "tolerance": C.TOL_FEATURE},
           "phase3_score": phase3}
    (C.RESULTS / f"reconciliation_{tag}.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "layerA")
