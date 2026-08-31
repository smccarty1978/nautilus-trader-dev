"""March 2024 regime-level score / first-fire diagnostic — post-hoc analysis of the
already-persisted March validation artifacts. No NT rerun, no model change.

INPUTS (all already persisted / committed):
  validation_march2024/artifacts/score_parity_detail.parquet
       -> per-checkpoint frozen model score (ref_score == nt_score, verified 0.0)
  validation_march2024/artifacts/outcome_parity.parquet
       -> per-checkpoint target_flip_within_horizon / flip_ts / time_to_flip_seconds /
          censored / disposition   (ref == nt)
  artifacts/oos_observations_merged.parquet  (March slice)  -> regime_direction, flip_ts
  artifacts/oos_candidates_merged.parquet    (March slice)  -> regime_age_seconds
  artifacts/train_experiment_freeze.json                    -> frozen TRAIN P90/P95/P97.5

Frozen thresholds (verbatim, NOT recomputed):
  LONG  P90 0.2852887899663343  P95 0.32770330252959395  P97.5 0.3639796684339806
  SHORT P90 0.28485631865861344 P95 0.33222113070660036  P97.5 0.37673375655439945
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
from research.analysis.metrics import classification_bundle

S = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
V = S / "validation_march2024" / "artifacts"
JOIN = ["observation_ts", "regime_start_ns", "checkpoint_index"]
AGG = json.loads((S / "artifacts" / "train_experiment_freeze.json").read_text())
THR = {d: {k: AGG["thresholds"][f"{d}_C"][k]["threshold"] for k in ("p90", "p95", "p97_5")} for d in ("LONG", "SHORT")}
SIGN = {"LONG": -1, "SHORT": 1}
MAR_LO = pd.Timestamp("2024-03-01", tz="UTC").value
MAR_HI = pd.Timestamp("2024-04-01", tz="UTC").value
NS = 1e9


def _bundle(y, s):
    b = classification_bundle(pd.Series(np.asarray(y, int)), np.asarray(s, float))
    return {k: (b[k]["value"] if b[k]["status"] == "ok" else None) for k in ("roc_auc", "pr_auc", "brier", "positive_rate", "sample_count")}


def _lift(d):
    return (d["pr_auc"] / d["positive_rate"]) if (d["pr_auc"] and d["positive_rate"]) else None


def _sdist(s):
    s = np.asarray(s, float)
    q = {f"p{int(p*100)}": float(np.quantile(s, p)) for p in (0.05, 0.25, 0.5, 0.75, 0.95)}
    return {"n": int(len(s)), "min": float(s.min()), "max": float(s.max()), "mean": float(s.mean()), **q}


# ---------------- assemble the checkpoint panel ----------------
sc = pd.read_parquet(V / "score_parity_detail.parquet")[JOIN + ["ref_score"]].rename(columns={"ref_score": "score"})
oc = pd.read_parquet(V / "outcome_parity.parquet")
oc = oc[JOIN + ["target_flip_within_horizon_ref", "flip_ts_ref", "time_to_flip_seconds_ref", "disposition_ref"]].rename(
    columns={c: c[:-4] for c in oc.columns if c.endswith("_ref")})
obs = pd.read_parquet(S / "artifacts" / "oos_observations_merged.parquet")
obs = obs[(obs.observation_ts >= MAR_LO) & (obs.observation_ts < MAR_HI)][JOIN + ["regime_direction"]]
cand = pd.read_parquet(S / "artifacts" / "oos_candidates_merged.parquet")
cand = cand[(cand.observation_ts >= MAR_LO) & (cand.observation_ts < MAR_HI)][JOIN + ["regime_age_seconds"]]

P = sc.merge(oc, on=JOIN).merge(obs, on=JOIN).merge(cand, on=JOIN)
P["dir"] = P.regime_direction.map({-1: "LONG", 1: "SHORT"})
P["y"] = pd.to_numeric(P.target_flip_within_horizon, errors="coerce")
P["labeled"] = P.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])
assert P.score.notna().all() and len(P) == 35872, (P.score.isna().sum(), len(P))

result = {
    "inputs_used": {
        "score": "validation_march2024/artifacts/score_parity_detail.parquet :: ref_score (== nt_score, verified 0.0)",
        "outcome": "validation_march2024/artifacts/outcome_parity.parquet :: *_ref columns",
        "regime_direction": "artifacts/oos_observations_merged.parquet (March slice, committed fa47c4e)",
        "regime_age_seconds": "artifacts/oos_candidates_merged.parquet (March slice)",
        "thresholds": "artifacts/train_experiment_freeze.json (frozen TRAIN, verbatim)",
    },
    "frozen_thresholds": THR,
    "march_panel": {"checkpoint_rows": int(len(P)),
                    "labeled_rows": int(P.labeled.sum()),
                    "censored_rows": int((~P.labeled).sum()),
                    "regimes": int(P.regime_start_ns.nunique())},
}

# ================= PART 1 — checkpoint-level reference =================
p1 = {}
for d in ("LONG", "SHORT"):
    g = P[(P.dir == d) & P.labeled]
    cpr = g.groupby("regime_start_ns").size()
    b = _bundle(g.y, g.score)
    p1[d] = {
        "candidate_rows": int(len(g)), "unique_regimes": int(g.regime_start_ns.nunique()),
        "checkpoints_per_regime": {"median": float(cpr.median()), "p10": float(cpr.quantile(0.1)),
                                   "p90": float(cpr.quantile(0.9)), "max": int(cpr.max())},
        "roc_auc": b["roc_auc"], "pr_auc": b["pr_auc"], "base_rate": b["positive_rate"],
        "pr_auc_over_base_rate": _lift(b),
        "every_eligible_5s_checkpoint_is_one_observation": True,
    }
result["PART_1_checkpoint_reference"] = p1

# ================= PART 2 — first eligible checkpoint per regime =================
p2 = {}
first_cp = P.sort_values(["regime_start_ns", "observation_ts"]).groupby("regime_start_ns", as_index=False).head(1)
for d in ("LONG", "SHORT"):
    g = first_cp[(first_cp.dir == d) & first_cp.labeled].copy()
    b = _bundle(g.y, g.score)
    q = pd.qcut(g.score.rank(method="first"), 10, labels=False)
    dec = g.assign(dec=q).groupby("dec").agg(n=("y", "size"), mean_score=("score", "mean"), flip_rate=("y", "mean")).reset_index()
    p2[d] = {
        "n_regimes": int(len(g)), "base_rate_180s": b["positive_rate"],
        "roc_auc": b["roc_auc"], "pr_auc": b["pr_auc"], "pr_auc_over_base_rate": _lift(b), "brier": b["brier"],
        "score_distribution": _sdist(g.score),
        "score_deciles": dec.to_dict("records"),
    }
result["PART_2_first_eligible_per_regime"] = p2

# ================= PART 3 — first P90 fire per regime =================
p3 = {}
for d in ("LONG", "SHORT"):
    g = P[P.dir == d].sort_values(["regime_start_ns", "observation_ts"])
    armed = g[g.score >= THR[d]["p90"]]
    ff = armed.groupby("regime_start_ns", as_index=False).head(1)
    ffl = ff[ff.labeled]
    elig = g.regime_start_ns.nunique()
    base_first_cp = first_cp[(first_cp.dir == d) & first_cp.labeled].y.mean()
    ttf_pos = pd.to_numeric(ffl.loc[ffl.y == 1, "time_to_flip_seconds"], errors="coerce")
    b = _bundle(ffl.y, ffl.score)
    # score quartiles within the first-fire tail
    if len(ffl) >= 20:
        qq = pd.qcut(ffl.score.rank(method="first"), 4, labels=False)
        buckets = []
        for k in range(4):
            sub = ffl[qq == k]
            tt = pd.to_numeric(sub.loc[sub.y == 1, "time_to_flip_seconds"], errors="coerce")
            buckets.append({"quartile": k + 1, "n": int(len(sub)),
                            "score_range": [float(sub.score.min()), float(sub.score.max())],
                            "mean_score": float(sub.score.mean()), "flip_within_180s_rate": float(sub.y.mean()),
                            "median_seconds_to_flip_positives": float(tt.median()) if tt.notna().any() else None})
    else:
        buckets = "n<20, quartiles not computed"
    p3[d] = {
        "first_fire_n": int(len(ff)), "eligible_regimes": int(elig),
        "pct_regimes_firing": float(len(ff) / elig) if elig else None,
        "flip_within_180s_rate": float(ffl.y.mean()) if len(ffl) else None,
        "precision_lift_vs_first_checkpoint_base": float(ffl.y.mean() / base_first_cp) if (len(ffl) and base_first_cp) else None,
        "median_seconds_to_flip_positives": float(ttf_pos.median()) if ttf_pos.notna().any() else None,
        "first_fire_score_distribution": _sdist(ff.score),
        "within_tail_roc_auc": b["roc_auc"], "within_tail_pr_auc": b["pr_auc"], "within_tail_brier": b["brier"],
        "within_tail_interpretability_caveat": "threshold-selected population, restricted score range -> ROC/PR limited",
        "score_quartile_buckets": buckets,
    }
result["PART_3_first_p90_fire"] = p3

# ================= PART 4 — within-regime score evolution before flip =================
p4 = {}
REL = [180, 150, 120, 90, 60, 30]
for d in ("LONG", "SHORT"):
    g = P[(P.dir == d) & P.flip_ts.notna()].copy()
    g["flip_ts"] = pd.to_numeric(g.flip_ts, errors="coerce")
    regimes = g.regime_start_ns.unique()
    per_bucket = {}
    traj = {r: {} for r in regimes}
    for dt in REL:
        rows = []
        for r, sub in g.groupby("regime_start_ns"):
            ft = sub.flip_ts.iloc[0]
            cut = ft - dt * NS
            elig = sub[sub.observation_ts <= cut]
            if len(elig):
                sv = float(elig.sort_values("observation_ts").iloc[-1].score)
                rows.append(sv); traj[r][dt] = sv
        arr = np.array(rows)
        per_bucket[f"T-{dt}s"] = {
            "n_regimes_observable": int(len(arr)),
            "median_score": float(np.median(arr)) if len(arr) else None,
            "mean_score": float(arr.mean()) if len(arr) else None,
            "p25": float(np.quantile(arr, 0.25)) if len(arr) else None,
            "p75": float(np.quantile(arr, 0.75)) if len(arr) else None,
            "pct_ge_P90": float((arr >= THR[d]["p90"]).mean()) if len(arr) else None,
            "pct_ge_P95": float((arr >= THR[d]["p95"]).mean()) if len(arr) else None,
            "pct_ge_P97_5": float((arr >= THR[d]["p97_5"]).mean()) if len(arr) else None,
        }
    ch_180_60 = [traj[r][180] - traj[r][60] for r in regimes if 180 in traj[r] and 60 in traj[r]]
    ch_120_30 = [traj[r][120] - traj[r][30] for r in regimes if 120 in traj[r] and 30 in traj[r]]
    # negative change = score rose toward flip (later minus earlier); report earlier->later as (later - earlier)
    rise_180_60 = [traj[r][60] - traj[r][180] for r in regimes if 180 in traj[r] and 60 in traj[r]]
    rise_120_30 = [traj[r][30] - traj[r][120] for r in regimes if 120 in traj[r] and 30 in traj[r]]
    maxpre = []
    p90_before = []
    for r, sub in g.groupby("regime_start_ns"):
        ft = sub.flip_ts.iloc[0]
        pre = sub[sub.observation_ts < ft]
        if len(pre):
            maxpre.append(float(pre.score.max()))
            armed = pre[pre.score >= THR[d]["p90"]].sort_values("observation_ts")
            if len(armed):
                p90_before.append(float((ft - armed.iloc[0].observation_ts) / NS))
    def dist(x):
        x = np.array([v for v in x if v is not None])
        return {"n": int(len(x)), "median": float(np.median(x)) if len(x) else None,
                "mean": float(x.mean()) if len(x) else None,
                "p25": float(np.quantile(x, .25)) if len(x) else None,
                "p75": float(np.quantile(x, .75)) if len(x) else None} if len(x) else {"n": 0}
    med = per_bucket
    ramp = (med["T-180s"]["median_score"] is not None and med["T-30s"]["median_score"] is not None
            and med["T-30s"]["median_score"] > med["T-180s"]["median_score"] + 0.01
            and med["T-60s"]["median_score"] >= med["T-120s"]["median_score"])
    p4[d] = {
        "flipping_regimes": int(len(regimes)),
        "by_relative_time": per_bucket,
        "score_rise_T180_to_T60_later_minus_earlier": dist(rise_180_60),
        "score_rise_T120_to_T30_later_minus_earlier": dist(rise_120_30),
        "maximum_preflip_score": dist(maxpre),
        "first_P90_seconds_before_flip": dist(p90_before),
        "systematic_ramp": "YES" if ramp else "MIXED",
    }
result["PART_4_preflip_score_ramp"] = p4

# ================= PART 5 — non-flipping / negative-checkpoint control =================
p5 = {}
AGE_BINS = [(0, 300), (300, 600), (600, 900), (900, 1800), (1800, 1e9)]
for d in ("LONG", "SHORT"):
    g = P[(P.dir == d) & P.labeled].copy()
    rows = []
    for lo, hi in AGE_BINS:
        b = g[(g.regime_age_seconds >= lo) & (g.regime_age_seconds < hi)]
        pos = b[b.y == 1]; neg = b[b.y == 0]
        rows.append({
            "regime_age_bin": f"{lo}-{int(hi) if hi < 1e8 else 'inf'}",
            "n_pos_checkpoints": int(len(pos)), "n_neg_checkpoints": int(len(neg)),
            "median_score_pos": float(pos.score.median()) if len(pos) else None,
            "median_score_neg": float(neg.score.median()) if len(neg) else None,
            "pct_ge_P90_pos": float((pos.score >= THR[d]["p90"]).mean()) if len(pos) else None,
            "pct_ge_P90_neg": float((neg.score >= THR[d]["p90"]).mean()) if len(neg) else None,
        })
    p5[d] = {"by_regime_age_bin": rows,
             "design": "within a regime-age bin, target=1 (flip <=180s) vs target=0 checkpoints; "
                       "a causal, age-controlled contrast that does not redefine the frozen target",
             "limitation": "not a per-regime matched control; exact regime matching would need a new research design"}
result["PART_5_nonflipping_control"] = p5

# ================= PART 6 — max score per regime (RETROSPECTIVE) =================
p6 = {"RETROSPECTIVE_DIAGNOSTIC_ONLY": True}
for d in ("LONG", "SHORT"):
    g = P[P.dir == d]
    per = g.groupby("regime_start_ns").agg(max_score=("score", "max"),
                                           ever_flip=("flip_ts", lambda s: int(s.notna().any())),
                                           ever_pos=("y", lambda s: int((s == 1).any()))).reset_index()
    b = _bundle(per.ever_flip, per.max_score)
    b2 = _bundle(per.ever_pos, per.max_score)
    q = pd.qcut(per.max_score.rank(method="first"), 4, labels=False)
    inc = per.assign(q=q).groupby("q").agg(n=("ever_flip", "size"), mean_max_score=("max_score", "mean"),
                                           eventual_flip_rate=("ever_flip", "mean"),
                                           ever_pos_rate=("ever_pos", "mean")).reset_index()
    p6[d] = {
        "n_regimes": int(len(per)),
        "max_score_distribution": _sdist(per.max_score),
        "descriptive_roc_auc_vs_ever_flip": b["roc_auc"], "descriptive_pr_auc_vs_ever_flip": b["pr_auc"],
        "descriptive_roc_auc_vs_ever_pos_checkpoint": b2["roc_auc"],
        "eventual_flip_by_max_score_quartile": inc.to_dict("records"),
    }
result["PART_6_max_score_per_regime"] = p6

# ---- persist ----
(V.parent / "REGIME_LEVEL_SCORE_DIAGNOSTIC.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
# detail parquet: first-checkpoint + first-fire + max per regime
det = first_cp[JOIN + ["dir", "score", "y", "regime_age_seconds"]].rename(columns={"score": "first_checkpoint_score", "y": "first_checkpoint_y"})
mx = P.groupby("regime_start_ns").agg(max_score=("score", "max"),
                                      ever_flip=("flip_ts", lambda s: int(s.notna().any()))).reset_index()
det = det.merge(mx, on="regime_start_ns", how="left")
det.to_parquet(V.parent / "regime_level_score_detail.parquet", index=False)
print("WROTE REGIME_LEVEL_SCORE_DIAGNOSTIC.json + regime_level_score_detail.parquet")
print(json.dumps({
    "P1": {d: {"roc": round(p1[d]["roc_auc"], 3), "regimes": p1[d]["unique_regimes"], "rows": p1[d]["candidate_rows"],
               "cp_per_regime_median": p1[d]["checkpoints_per_regime"]["median"]} for d in ("LONG", "SHORT")},
    "P2": {d: {"n": p2[d]["n_regimes"], "roc": round(p2[d]["roc_auc"], 3), "base": round(p2[d]["base_rate_180s"], 3),
               "lift": round(p2[d]["pr_auc_over_base_rate"], 2)} for d in ("LONG", "SHORT")},
    "P3": {d: {"n": p3[d]["first_fire_n"], "flip180": round(p3[d]["flip_within_180s_rate"], 3),
               "lift": round(p3[d]["precision_lift_vs_first_checkpoint_base"], 2)} for d in ("LONG", "SHORT")},
    "P4_median_score": {d: {b: round(p4[d]["by_relative_time"][b]["median_score"], 3) for b in ("T-180s", "T-120s", "T-60s", "T-30s")}
                        for d in ("LONG", "SHORT")},
    "P4_ramp": {d: p4[d]["systematic_ramp"] for d in ("LONG", "SHORT")},
    "P6_maxscore_roc": {d: round(p6[d]["descriptive_roc_auc_vs_ever_flip"], 3) for d in ("LONG", "SHORT")},
}, indent=2))
