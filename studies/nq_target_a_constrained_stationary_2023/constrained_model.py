"""Target A constrained / stationary model methodology study -- 2023 ONLY.

Three stages, each refusing to run unless the previous stage's hashed freeze is present and unchanged:

  contract  Phase 0-3   reuse proof, stationary feature surface, 60/20/20 session split, capacity ladder
                        + evaluation contract. Fits nothing. Reads no label outside the population proof.
  develop   Phase 4-6   random-label canary + real-label 60%->20% development; selection by the frozen rule.
                        The FINAL 20% rows are dropped before any fit or metric.
  final     Phase 7-10  only if the development gate passed: retrain on the first 80%, score the final 20%
                        once, controls, concentration, monotonicity, control gate, verdict.

The frame is REUSED read-only from the prior study's merged controller output (never replayed). 2024 rows are
dropped at load; 2025/2026 are not in the frame.

    python studies/nq_target_a_constrained_stationary_2023/constrained_model.py contract
    python studies/nq_target_a_constrained_stationary_2023/constrained_model.py develop
    python studies/nq_target_a_constrained_stationary_2023/constrained_model.py final
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from research.analysis.diagnostic_ops import globex_trading_day  # noqa: E402
from research.analysis.metrics import roc_auc as platform_roc_auc  # noqa: E402

OUT = HERE / "artifacts"
PRIOR_ID = "nq_mtf_structural_predictive_ranking"
PRIOR = REPO.parent / f"{REPO.name.split('-')[0]}-{PRIOR_ID}" / "studies" / PRIOR_ID
MERGED = PRIOR / "_work" / "controller" / "merged"
FORENSICS = PRIOR / "forensics"
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
YEAR = 2023

# Phase-0 reference values, read from the forensic audit (TARGET_A_POPULATION_PARITY.csv, _VERDICT.json)
EXPECT_SHA = {"candidates.parquet": "475209b46caf48b674d66833f56005c8fc6c6436f34c8aa50626da7d07300842",
              "observations.parquet": "98e03dc4a2cf01b44d05c45d84b81af5768848142216945cfd133e13d66303b6"}
FULL_MODEL_ID = "3cf8c5493fef66a7c1b5c04468b0e717eef8247626bfa7dc3ff65109f28ed973"
FULL_SCORE_DIGEST_2023 = "8fa2031cd01d9a7a"
FULL_FEATURE_SHA = "36777a8755e32abc7b120f1715948b6f5f5beef2e8dc8cfc739c97e2fd653ef0"
GEOM_NO_DIR_FEATURE_COUNT = 71

SHUFFLE_SEED = 20260923          # the forensic audit's seed; one shuffle, never varied
MODEL_SEED = 42                  # the prior frozen model seed
BOOT_SEED = 20260924
BOOT_REPS = 2000

LADDER_SHARED = {"objective": "binary", "n_estimators": 100, "learning_rate": 0.05, "min_child_samples": 200,
                 "reg_alpha": 0.0, "reg_lambda": 10.0, "colsample_bytree": 0.7, "subsample": 0.7,
                 "subsample_freq": 1, "random_state": MODEL_SEED, "deterministic": True, "force_row_wise": True,
                 "n_jobs": 4, "verbosity": -1}
LADDER = [  # capacity rank 1 < 2 < 3; ONLY tree complexity varies
    {"id": "L1_stumps", "capacity_rank": 1, "num_leaves": 2, "max_depth": 1},
    {"id": "L2_depth2", "capacity_rank": 2, "num_leaves": 4, "max_depth": 2},
    {"id": "L3_depth3", "capacity_rank": 3, "num_leaves": 8, "max_depth": 3},
]
CANARY_MAX_RANDOM_TRAIN_AUC = 0.70
SELECTION_TOLERANCE = 0.01
CONTROL_SMOOTHING_M = 20.0
CONTROL_MARGIN = 0.02
MONO_QUALITY_MIN = 0.9
VARIANCE_MIN = 0.9


# ----------------------------------------------------------------------------- utilities
def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha_json(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(name: str, payload: dict) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_jsonable) + "\n", encoding="utf-8")
    return sha_file(p)


def _jsonable(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    raise TypeError(type(v))


def write_table(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / f"{name}.csv", index=False)
    df.to_parquet(OUT / f"{name}.parquet", index=False)


def read_frozen(name: str, expect_sha: str | None = None) -> dict:
    p = OUT / name
    if not p.is_file():
        raise SystemExit(f"CONTRACT_MISSING: {p}")
    if expect_sha and sha_file(p) != expect_sha:
        raise SystemExit(f"CONTRACT_CHANGED: {name} sha {sha_file(p)} != frozen {expect_sha}")
    return json.loads(p.read_text(encoding="utf-8"))


def auc(y, s) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(np.asarray(y, dtype=int), np.asarray(s, dtype=float)))


def spearman(x, y) -> float | None:
    s = pd.Series(np.asarray(y, dtype=float))
    if s.nunique() < 2:
        return None
    return float(pd.Series(np.asarray(x, dtype=float)).rank().corr(s.rank()))


# ----------------------------------------------------------------------------- frame
def load_population() -> tuple[pd.DataFrame, dict]:
    """The exact forensic population: 2023, checkpoint_index 0, derived Target A in {0,1}."""
    shas = {n: sha_file(MERGED / n) for n in EXPECT_SHA}
    c = pd.read_parquet(MERGED / "candidates.parquet")
    o = pd.read_parquet(MERGED / "observations.parquet")
    dup = [col for col in o.columns if col in c.columns and col not in KEY]   # lifecycle_v2._train_frame_all_labels
    frame = c.merge(o.drop(columns=dup), on=KEY, how="inner")
    frame["_year"] = pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year
    frame = frame[frame["_year"] == YEAR]                                      # 2024 dropped here, never read further
    t0 = frame[frame["checkpoint_index"] == 0].copy()
    g = t0["terminal_gross_pnl_atr"]
    t0["target_A"] = np.where(g.isna(), np.nan, (g > 0).astype(float))
    nulls = int(t0["target_A"].isna().sum())
    pop = t0[t0["target_A"].isin([0.0, 1.0])].copy()
    pop["target_A"] = pop["target_A"].astype(int)
    pop["session"] = globex_trading_day(pop["observation_ts"])
    # diagnostics (never optimised): barrier reached at or before the terminal flip
    ttf = pop["terminal_time_to_flip_seconds"]
    pop["fav2_before_terminal"] = ((pop["fp_fav_2p00_label"] == 1) & (pop["fp_fav_2p00_resolution_seconds"] <= ttf)).astype(int)
    pop["adv1_before_terminal"] = ((pop["fp_adv_1p00_label"] == 0) & (pop["fp_adv_1p00_resolution_seconds"] <= ttf)).astype(int)
    info = {"source_sha256": shas, "t0_rows_in_year": int(len(t0)), "target_nulls": nulls}
    return pop, info


def score_digest(s) -> str:
    return hashlib.sha256(np.round(np.asarray(s, dtype=float), 10).tobytes()).hexdigest()


# ----------------------------------------------------------------------------- contract
def stage_contract() -> None:
    pop, info = load_population()
    # ---- Phase 0: exact reuse proof
    exp = pd.read_csv(FORENSICS / "TARGET_A_POPULATION_PARITY.csv")
    exp = exp[exp["year"] == YEAR].iloc[0]
    verdict = json.loads((FORENSICS / "TARGET_A_FORENSIC_VERDICT.json").read_text(encoding="utf-8"))
    models = json.loads((PRIOR / "artifacts" / "experiment_models.json").read_text(encoding="utf-8"))
    full = next(m for m in models["models"] if m["arm"] == "full")
    original = list(full["features"])
    from research_workflow.model_store import score as store_score
    s_full = store_score(FULL_MODEL_ID, pop[original])
    checks = {
        "source_parquet_sha256_match": info["source_sha256"] == EXPECT_SHA,
        "N": (int(len(pop)), int(exp["eligible_n"])),
        "positives": (int(pop["target_A"].sum()), int(exp["positive_n"])),
        "negatives": (int((pop["target_A"] == 0).sum()), int(exp["negative_n"])),
        "target_nulls": (info["target_nulls"], int(exp["null_n"])),
        "t0_rows_in_year": (info["t0_rows_in_year"], int(exp["t0_rows"])),
        "unique_regime_start_ns": (int(pop["regime_start_ns"].nunique()), int(exp["unique_regime_start_ns"])),
        "unique_key_tuples": (int(pop[KEY].drop_duplicates().shape[0]), int(exp["unique_key_tuples"])),
        "duplicate_key_rows": (int(pop.duplicated(KEY).sum()), int(exp["duplicate_key_rows"])),
        "session_days": (int(pop["session"].nunique()), int(exp["session_days"])),
        "fit_receipt_final_fit_rows": (int(len(pop)), int(full["final_fit_rows"])),
        "original_feature_order_sha256": (hashlib.sha256(json.dumps(original).encode()).hexdigest(), FULL_FEATURE_SHA),
        "frozen_full_model_2023_score_digest16": (score_digest(s_full)[:16], FULL_SCORE_DIGEST_2023),
        "frozen_full_model_2023_auc": (auc(pop["target_A"], s_full), verdict["recomputed_auc_2023"]),
    }
    ok = checks["source_parquet_sha256_match"] and all(
        (abs(a - b) < 1e-12 if isinstance(a, float) else a == b) for k, v in checks.items() if isinstance(v, tuple) for a, b in [v])
    reuse = {"kind": "phase0_reuse_proof", "year": YEAR, "PASS": bool(ok),
             "checks": {k: (v if not isinstance(v, tuple) else {"observed": v[0], "forensic": v[1],
                                                                 "match": (abs(v[0] - v[1]) < 1e-12 if isinstance(v[0], float) else v[0] == v[1])})
                        for k, v in checks.items()},
             "lineage": {"prior_study": PRIOR_ID, "prior_study_commit": "577c5fc5 (forensic audit)",
                         "source_dir": str(MERGED), "source_sha256": info["source_sha256"],
                         "merge_rule": "lifecycle_v2._train_frame_all_labels: inner join on (observation_ts, regime_start_ns, checkpoint_index) after dropping duplicated observation columns",
                         "population_rule": "_year == 2023 AND checkpoint_index == 0 AND (terminal_gross_pnl_atr > 0) in {0,1}",
                         "replayed": False},
             "population_row_digest": hashlib.sha256(pop.sort_values("regime_start_ns")[["regime_start_ns", "target_A"]].to_numpy().tobytes()).hexdigest()}
    write_json("PHASE0_REUSE_PROOF.json", reuse)
    if not ok:
        raise SystemExit("PIPELINE_OR_CONTRACT_FAILURE: exact reuse of the forensic 2023 population not established")

    # ---- Phase 1: stationary surface from the forensic feature-parity artifact (no manual naming)
    par = pd.read_csv(FORENSICS / "TARGET_A_FEATURE_PARITY.csv").set_index("feature")
    if list(par.sort_values("model_index").index) != original:
        raise SystemExit("PIPELINE_OR_CONTRACT_FAILURE: forensic parity artifact order != frozen FULL order")
    outside = par["pct_2024_outside_2023_range"]
    gap_lo, gap_hi = float(outside[outside < 50].max()), float(outside[outside >= 50].min())
    excluded = [f for f in original if outside[f] >= 50.0]
    rule = ("excluded iff forensic pct_2024_outside_2023_range >= 50 (the distribution is bimodal: kept max "
            f"{gap_lo:.2f}%, excluded min {gap_hi:.2f}%)")
    forensic_named_families = ("start_price_", "highest_high_", "lowest_low_", "prior_start_price_", "prior_end_price_",
                               "prior_mfe_price_", "prior_mae_price_")
    cross_check = sorted(f for f in original if f.startswith(forensic_named_families))
    if sorted(excluded) != cross_check or len(excluded) != 22:
        raise SystemExit(f"PIPELINE_OR_CONTRACT_FAILURE: mechanical exclusion {len(excluded)} != forensic named 22")
    stationary_full = [f for f in original if f not in excluded]
    geom_prior = next(m for m in models["models"] if m["arm"] == "geometry_no_direction")["features"]
    if len(geom_prior) != GEOM_NO_DIR_FEATURE_COUNT:
        raise SystemExit("PIPELINE_OR_CONTRACT_FAILURE: prior geometry_no_direction arm not as audited")
    stationary_geometry_no_direction = [f for f in stationary_full if f in set(geom_prior)]
    arms = {"stationary_full": stationary_full,
            "stationary_geometry_no_direction": stationary_geometry_no_direction,
            "direction_only": ["dir_1m"],
            "mtf_state_only": ["dir_1m", "dir_5m", "dir_15m", "dir_1h"]}
    surface = {
        "kind": "stationary_feature_surface",
        "original_78": original, "original_78_sha256": FULL_FEATURE_SHA,
        "exclusion_rule": rule,
        "excluded": [{"feature": f, "model_index": int(par.loc[f, "model_index"]),
                      "reason": "absolute price-level coordinate (non-stationary)",
                      "forensic_evidence": {"artifact": "forensics/TARGET_A_FEATURE_PARITY.csv",
                                            "pct_2024_outside_2023_range": float(outside[f]),
                                            "min_2023": float(par.loc[f, "min_2023"]), "max_2023": float(par.loc[f, "max_2023"]),
                                            "audit_text": "TARGET_A_FORENSIC_AUDIT.md Phase 4: the 22 absolute price levels"}}
                     for f in excluded],
        "excluded_n": len(excluded),
        "kept_max_pct_2024_outside_2023_range": gap_lo,
        "note_2024_evidence": "the exclusion reads an already-produced forensic artifact; no 2024 row is loaded by this study",
        "arms": {k: {"ordered_features": v, "n": len(v), "sha256": hashlib.sha256(json.dumps(v).encode()).hexdigest()} for k, v in arms.items()},
        "stationary_geometry_no_direction_rule": "stationary_full INTERSECT the audited geometry_no_direction arm (= full minus the 7 dir_* / prior_dir_* columns); no subjective selection",
        "retained_not_replaced": "no new features engineered; the two 2023-constant columns (checkpoint_seconds_since_flip, bars_1m) are retained unchanged -- a tree cannot split on a constant",
        "caveat_point_scale_atr": "atr_* / frozen_atr_* are in index points (scale with price and volatility); they are NOT absolute coordinates and the forensic shows <=3.6% 2024 out-of-range, so they are kept per the declared rule",
    }
    surface_sha = write_json("STATIONARY_FEATURE_SURFACE.json", surface)

    # ---- Phase 2: 60/20/20 by ordered unique sessions
    sessions = sorted(pop["session"].unique())
    S = len(sessions)
    n_tr, n_trv = int(np.floor(0.6 * S)), int(np.floor(0.8 * S))
    blocks = {"development_train": sessions[:n_tr], "development_validation": sessions[n_tr:n_trv], "final_holdout": sessions[n_trv:]}
    split = {"kind": "temporal_split_2023", "unit": "complete RTH trading session (Globex trading day of observation_ts)",
             "rule": "sessions sorted ascending; train = first floor(0.6*S), validation = next floor(0.8*S)-floor(0.6*S), final = rest",
             "S": S, "searched": False, "blocks": {}}
    for name, ss in blocks.items():
        rows = pop[pop["session"].isin(ss)]
        entry = {"first_session": ss[0], "last_session": ss[-1], "sessions": len(ss), "N": int(len(rows))}
        if name != "final_holdout":   # the final block's label balance stays dark until the gate opens it
            entry.update({"positives": int(rows["target_A"].sum()), "negatives": int((rows["target_A"] == 0).sum()),
                          "positive_rate": float(rows["target_A"].mean())})
        split["blocks"][name] = entry
        split["blocks"][name]["session_list"] = ss
    split["disclosure"] = ("the forensic 70/30 diagnostic already opened 2023-09-11 onward; this final 20% lies inside that "
                           "window. It is unseen by THIS study's choices, but it is not virgin data.")
    split_sha = write_json("TEMPORAL_SPLIT_2023.json", split)

    # ---- Phase 3: old configuration + ladder + evaluation contract
    ladder = {
        "kind": "capacity_ladder_and_evaluation_contract",
        "frozen_before_any_fit": True,
        "old_configuration": {"family": "lightgbm.LGBMClassifier 4.6.0", "params": full["hyperparameters"],
                              "forensic_capacity": verdict["capacity"],
                              "defects": ["subsample 0.8 inert (subsample_freq unset)", "no early stopping",
                                          "12,400 leaves for 7,475 rows", "22 absolute price inputs"]},
        "shared_params": LADDER_SHARED,
        "configurations": [{**LADDER_SHARED, **c, "max_total_leaves": c["num_leaves"] * LADDER_SHARED["n_estimators"]} for c in LADDER],
        "bagging_active_proof": "every configuration is also refit with subsample_freq=0; predictions must differ, else CONTRACT FAILURE",
        "early_stopping": "none -- fixed n_estimators, the validation block is never passed to fit",
        "random_label_canary": {"seed": SHUFFLE_SEED, "shuffles": 1, "rows": "development_train only", "arm": "stationary_full",
                                "pass_if_random_label_train_auc_le": CANARY_MAX_RANDOM_TRAIN_AUC, "scored_elsewhere": False},
        "controls": {"estimator": "exact-cell empirical Target-A rate fitted on the training block, smoothed toward the training prevalence with m=%g; an unseen cell scores the prevalence" % CONTROL_SMOOTHING_M,
                     "why": "the strongest use of 'knowing direction / the exact 1m/5m/15m/1h state' -- no capacity limit handicaps it",
                     "direction_only": ["dir_1m"], "mtf_state_only": ["dir_1m", "dir_5m", "dir_15m", "dir_1h"]},
        "development_gate": {"per_config_eligible_if": ["random-label train AUC <= %.2f" % CANARY_MAX_RANDOM_TRAIN_AUC,
                                                        "validation AUC day-blocked 95% CI lower bound > 0.50"],
                             "none_eligible": "NO_DEVELOPMENT_SIGNAL -- stop, final 20% stays dark",
                             "selection": f"among eligible configs take the LOWEST capacity_rank whose validation AUC >= best eligible validation AUC - {SELECTION_TOLERANCE}"},
        "final": {"refit_rows": "development_train + development_validation (first 80% of sessions)",
                  "score": "final_holdout once", "arms": list(surface["arms"]),
                  "uncertainty": f"session-blocked bootstrap, {BOOT_REPS} reps, seed {BOOT_SEED}; paired deltas use the same resamples",
                  "bin_boundaries": "quantiles of the frozen final model's scores on the first-80% rows (development data), never the holdout",
                  "surfaces": ["quintiles Q1..Q5", "deciles D1..D10 (monotonicity only)", "top50", "top30", "top20", "top10"]},
        "gates": {"holdout_skill": "stationary_full holdout AUC 95% CI lower > 0.50",
                  "beats_control": f"paired delta AUC 95% CI lower > 0 AND point delta >= {CONTROL_MARGIN}",
                  "monotonic_quality": f"Spearman(quintile, Target-A rate) >= {MONO_QUALITY_MIN}",
                  "variance_signature": f"Spearman(quintile, +2A reach) >= {VARIANCE_MIN} AND Spearman(quintile, -1A reach) >= {VARIANCE_MIN}, in validation AND final holdout"},
        "verdict_order": [
            "PIPELINE_OR_CONTRACT_FAILURE if any contract check fails",
            "NO_DEVELOPMENT_SIGNAL if no configuration passes the development gate",
            "CAPACITY_FIXED_SIGNAL_FOUND if holdout_skill AND beats mtf_state_only AND beats direction_only AND monotonic_quality AND NOT variance_signature",
            "VARIANCE_NOT_QUALITY if variance_signature (reproduced in validation and holdout)",
            "CAPACITY_FIXED_NO_INCREMENTAL_SIGNAL otherwise"],
        "target": {"id": "A_win", "expr": "terminal_gross_pnl_atr > 0"},
        "diagnostics_not_targets": {"fav2_before_terminal": "fp_fav_2p00_label == 1 AND fp_fav_2p00_resolution_seconds <= terminal_time_to_flip_seconds",
                                    "adv1_before_terminal": "fp_adv_1p00_label == 0 (adverse barrier hit) AND fp_adv_1p00_resolution_seconds <= terminal_time_to_flip_seconds"},
        "bound_to": {"STATIONARY_FEATURE_SURFACE.json": surface_sha, "TEMPORAL_SPLIT_2023.json": split_sha,
                     "PHASE0_REUSE_PROOF.json": sha_file(OUT / "PHASE0_REUSE_PROOF.json")},
    }
    ladder_sha = write_json("CAPACITY_LADDER.json", ladder)
    write_json("CONTRACT_FREEZE.json", {"STATIONARY_FEATURE_SURFACE.json": surface_sha, "TEMPORAL_SPLIT_2023.json": split_sha,
                                        "CAPACITY_LADDER.json": ladder_sha, "script_sha256": sha_file(Path(__file__))})
    print(json.dumps({"stage": "contract", "reuse_PASS": ok, "excluded": len(excluded), "stationary_full": len(stationary_full),
                      "geometry_no_direction": len(stationary_geometry_no_direction),
                      "blocks": {k: {kk: v[kk] for kk in ("first_session", "last_session", "sessions", "N")} for k, v in split["blocks"].items()}}, indent=1))


# ----------------------------------------------------------------------------- modelling helpers
def load_contract() -> tuple[dict, dict, dict]:
    freeze = json.loads((OUT / "CONTRACT_FREEZE.json").read_text(encoding="utf-8"))
    surface = read_frozen("STATIONARY_FEATURE_SURFACE.json", freeze["STATIONARY_FEATURE_SURFACE.json"])
    split = read_frozen("TEMPORAL_SPLIT_2023.json", freeze["TEMPORAL_SPLIT_2023.json"])
    ladder = read_frozen("CAPACITY_LADDER.json", freeze["CAPACITY_LADDER.json"])
    return surface, split, ladder


def lgbm(cfg: dict, **override):
    from lightgbm import LGBMClassifier
    p = {k: v for k, v in cfg.items() if k not in ("id", "capacity_rank", "max_total_leaves")}
    p.update(override)
    return LGBMClassifier(**p)


def fit_score(cfg: dict, Xtr: pd.DataFrame, ytr, Xsc: list[pd.DataFrame], **override):
    m = lgbm(cfg, **override).fit(Xtr, ytr)
    return m, [m.predict_proba(X)[:, 1] for X in Xsc]


def total_leaves(m) -> int:
    return int(sum(t["num_leaves"] for t in m.booster_.dump_model()["tree_info"]))


class CellRate:
    """Exact-cell empirical rate, smoothed toward the training prevalence."""

    def __init__(self, cols: list[str], m: float = CONTROL_SMOOTHING_M):
        self.cols, self.m = cols, m

    def fit(self, X: pd.DataFrame, y):
        d = X[self.cols].copy()
        d["_y"] = np.asarray(y)
        self.p0 = float(d["_y"].mean())
        g = d.groupby(self.cols)["_y"].agg(["sum", "count"])
        self.table = ((g["sum"] + self.m * self.p0) / (g["count"] + self.m)).rename("rate")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        r = X[self.cols].merge(self.table.reset_index(), on=self.cols, how="left")["rate"]
        return r.fillna(self.p0).to_numpy()


def boot_indices(sessions: pd.Series, reps: int, seed: int):
    """Session-blocked bootstrap: yields row-index arrays built from resampled sessions."""
    rng = np.random.default_rng(seed)
    codes, uniq = pd.factorize(sessions)
    groups = [np.flatnonzero(codes == i) for i in range(len(uniq))]
    for _ in range(reps):
        pick = rng.integers(0, len(groups), len(groups))
        yield np.concatenate([groups[i] for i in pick])


def auc_ci(y, scores: dict, sessions: pd.Series, pairs=()) -> dict:
    y = np.asarray(y)
    point = {k: auc(y, s) for k, s in scores.items()}
    draws = {k: [] for k in scores}
    for idx in boot_indices(sessions, BOOT_REPS, BOOT_SEED):
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        for k, s in scores.items():
            draws[k].append(auc(yy, np.asarray(s)[idx]))
    out = {k: {"auc": point[k], "ci95": [float(np.percentile(draws[k], 2.5)), float(np.percentile(draws[k], 97.5))]} for k in scores}
    for a, b in pairs:
        d = np.asarray(draws[a]) - np.asarray(draws[b])
        out[f"delta_{a}_vs_{b}"] = {"delta": point[a] - point[b], "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]}
    return out


def bin_table(df: pd.DataFrame, score: np.ndarray, edges: list[float], labels: list[str], n_sessions: int) -> pd.DataFrame:
    b = np.searchsorted(np.asarray(edges), score, side="right")
    rows = []
    for i, lab in enumerate(labels):
        part = df[b == i]
        rows.append(summarise(part, lab, n_sessions, len(df), df["target_A"].mean()))
    return pd.DataFrame(rows)


def summarise(part: pd.DataFrame, lab: str, n_sessions: int, n_total: int, pooled: float) -> dict:
    n = len(part)
    return {"surface": lab, "N": n, "coverage": n / n_total if n_total else None,
            "trades_per_session": n / n_sessions, "target_A_win_pct": 100 * part["target_A"].mean() if n else None,
            "lift_vs_pooled": part["target_A"].mean() / pooled if n else None,
            "mean_terminal_gross_atr": part["terminal_gross_pnl_atr"].mean() if n else None,
            "fav2_before_terminal_pct": 100 * part["fav2_before_terminal"].mean() if n else None,
            "adv1_before_terminal_pct": 100 * part["adv1_before_terminal"].mean() if n else None}


def session_ci(part: pd.DataFrame, col: str, reps: int = 1000) -> list:
    if len(part) == 0:
        return [None, None]
    v = part[col].to_numpy(dtype=float)
    vals = [v[idx].mean() for idx in boot_indices(part["session"].reset_index(drop=True), reps, BOOT_SEED)]
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def monotonic(tab: pd.DataFrame) -> dict:
    x = np.arange(1, len(tab) + 1)
    return {"target_A": spearman(x, tab["target_A_win_pct"]), "mean_terminal_gross_atr": spearman(x, tab["mean_terminal_gross_atr"]),
            "fav2_before_terminal": spearman(x, tab["fav2_before_terminal_pct"]), "adv1_before_terminal": spearman(x, tab["adv1_before_terminal_pct"])}


def pct_outside(train: pd.DataFrame, other: pd.DataFrame, cols: list[str]) -> dict:
    out = {}
    for c in cols:
        lo, hi = train[c].min(), train[c].max()
        v = other[c].dropna()
        out[c] = float(100 * ((v < lo) | (v > hi)).mean()) if len(v) else 0.0
    return out


# ----------------------------------------------------------------------------- develop
def stage_develop() -> None:
    surface, split, ladder = load_contract()
    pop, _ = load_population()
    blk = {k: set(v["session_list"]) for k, v in split["blocks"].items()}
    pop = pop[~pop["session"].isin(blk["final_holdout"])]           # FINAL 20% dropped before anything else
    tr = pop[pop["session"].isin(blk["development_train"])].reset_index(drop=True)
    va = pop[pop["session"].isin(blk["development_validation"])].reset_index(drop=True)
    feats = surface["arms"]["stationary_full"]["ordered_features"]
    ytr, yva = tr["target_A"].to_numpy(), va["target_A"].to_numpy()
    shuffled = np.random.default_rng(SHUFFLE_SEED).permutation(ytr)

    canary_rows, dev_rows, valbins = [], [], {}
    for cfg in ladder["configurations"]:
        m_real, (s_tr, s_va) = fit_score(cfg, tr[feats], ytr, [tr[feats], va[feats]])
        _, (s_va_nobag,) = fit_score(cfg, tr[feats], ytr, [va[feats]], subsample_freq=0)
        bag_diff = float(np.max(np.abs(s_va - s_va_nobag)))
        if bag_diff == 0.0:
            raise SystemExit(f"PIPELINE_OR_CONTRACT_FAILURE: bagging inert for {cfg['id']}")
        m_rand, (s_rand_tr,) = fit_score(cfg, tr[feats], shuffled, [tr[feats]])
        r_auc = auc(shuffled, s_rand_tr)
        canary_rows.append({"config": cfg["id"], "capacity_rank": cfg["capacity_rank"], "rows": len(tr), "shuffle_seed": SHUFFLE_SEED,
                            "shuffled_positive_rate": float(shuffled.mean()), "random_label_train_auc": r_auc,
                            "total_leaves": total_leaves(m_rand), "canary_pass": r_auc <= CANARY_MAX_RANDOM_TRAIN_AUC,
                            "old_model_random_label_train_auc": 0.9711100606060606})
        ci = auc_ci(yva, {"v": s_va}, va["session"])["v"]
        t_auc = auc(ytr, s_tr)
        assert abs(platform_roc_auc(yva, s_va).to_dict()["value"] - ci["auc"]) < 1e-12
        # validation bins: quantiles of this model's own TRAIN scores (development data)
        q5 = list(np.quantile(s_tr, [0.2, 0.4, 0.6, 0.8]))
        tab = bin_table(va, s_va, q5, [f"Q{i}" for i in range(1, 6)], len(blk["development_validation"]))
        tab.insert(0, "config", cfg["id"])
        valbins[cfg["id"]] = tab
        mono = monotonic(tab)
        dev_rows.append({"config": cfg["id"], "capacity_rank": cfg["capacity_rank"], "train_n": len(tr), "validation_n": len(va),
                         "train_auc": t_auc, "validation_auc": ci["auc"], "validation_auc_ci_lo": ci["ci95"][0],
                         "validation_auc_ci_hi": ci["ci95"][1], "train_validation_gap": t_auc - ci["auc"],
                         "random_label_train_auc": r_auc, "real_minus_random_train_auc": t_auc - r_auc,
                         "total_leaves": total_leaves(m_real), "bagging_active_max_abs_pred_diff": bag_diff,
                         "canary_pass": r_auc <= CANARY_MAX_RANDOM_TRAIN_AUC,
                         "validation_ci_lo_gt_0p5": ci["ci95"][0] > 0.5,
                         **{f"val_spearman_{k}": v for k, v in mono.items()}})
    # controls (context only; never select anything)
    ctrl = {}
    for name in ("direction_only", "mtf_state_only"):
        cols = surface["arms"][name]["ordered_features"]
        cr = CellRate(cols).fit(tr, ytr)
        c = auc_ci(yva, {"v": cr.predict(va)}, va["session"])["v"]
        ctrl[name] = {"train_auc": auc(ytr, cr.predict(tr)), "validation_auc": c["auc"], "validation_auc_ci": c["ci95"]}
        dev_rows.append({"config": f"control:{name}", "capacity_rank": None, "train_n": len(tr), "validation_n": len(va),
                         "train_auc": ctrl[name]["train_auc"], "validation_auc": c["auc"], "validation_auc_ci_lo": c["ci95"][0],
                         "validation_auc_ci_hi": c["ci95"][1], "train_validation_gap": ctrl[name]["train_auc"] - c["auc"]})
    write_table("RANDOM_LABEL_CAPACITY", pd.DataFrame(canary_rows))
    dev = pd.DataFrame(dev_rows)
    write_table("DEVELOPMENT_RESULTS", dev)
    write_table("DEVELOPMENT_VALIDATION_BINS", pd.concat(valbins.values(), ignore_index=True))

    # nonstationarity inside development (validation vs development-train range; labels not used)
    excl = [e["feature"] for e in surface["excluded"]]
    po = pct_outside(tr, va, excl + feats)
    nonstat = {"validation_vs_devtrain_pct_outside_range": {
        "excluded_22_mean": float(np.mean([po[c] for c in excl])), "excluded_22_max": float(np.max([po[c] for c in excl])),
        "stationary_mean": float(np.mean([po[c] for c in feats])), "stationary_max": float(np.max([po[c] for c in feats])),
        "stationary_top5": sorted(((po[c], c) for c in feats), reverse=True)[:5]}}

    cand = dev[dev["capacity_rank"].notna()]
    elig = cand[cand["canary_pass"] & cand["validation_ci_lo_gt_0p5"]]
    selected = None
    if len(elig):
        best = elig["validation_auc"].max()
        selected = elig[elig["validation_auc"] >= best - SELECTION_TOLERANCE].sort_values("capacity_rank").iloc[0]["config"]
    gate = {"kind": "development_gate", "eligible": elig["config"].tolist(), "selected_config": selected,
            "gate_passed": selected is not None, "rule": ladder["development_gate"], "controls_validation": ctrl,
            "nonstationarity_inside_development": nonstat,
            "final_holdout_opened": False, "contract_freeze_sha256": sha_file(OUT / "CONTRACT_FREEZE.json")}
    if selected is not None:
        cfg = next(c for c in ladder["configurations"] if c["id"] == selected)
        gate["frozen_for_final"] = {"estimator": cfg, "arms": surface["arms"], "target": ladder["target"], "model_seed": MODEL_SEED,
                                    "session_boundaries": {k: [v["first_session"], v["last_session"]] for k, v in split["blocks"].items()},
                                    "metrics": ladder["final"], "gates": ladder["gates"]}
    else:
        gate["verdict"] = "NO_DEVELOPMENT_SIGNAL"
    write_json("DEVELOPMENT_GATE.json", gate)
    print(dev.drop(columns=[c for c in dev.columns if c.startswith("val_spearman")]).to_string())
    print(json.dumps({"eligible": gate["eligible"], "selected": selected, "nonstationarity": nonstat}, indent=1, default=str))


# ----------------------------------------------------------------------------- final
def stage_final() -> None:
    surface, split, ladder = load_contract()
    gate = read_frozen("DEVELOPMENT_GATE.json")
    if not gate.get("gate_passed"):
        raise SystemExit("FINAL_HOLDOUT_LOCKED: development gate did not pass (NO_DEVELOPMENT_SIGNAL)")
    if gate["contract_freeze_sha256"] != sha_file(OUT / "CONTRACT_FREEZE.json"):
        raise SystemExit("CONTRACT_CHANGED after development")
    if (OUT / "FINAL_HOLDOUT_RESULTS.json").exists():
        raise SystemExit("FINAL_HOLDOUT_ALREADY_SCORED: the final 20% is scored exactly once")
    cfg = gate["frozen_for_final"]["estimator"]
    pop, _ = load_population()
    blk = {k: set(v["session_list"]) for k, v in split["blocks"].items()}
    dev = pop[~pop["session"].isin(blk["final_holdout"])].reset_index(drop=True)
    ho = pop[pop["session"].isin(blk["final_holdout"])].reset_index(drop=True)
    n_ho_sessions = len(blk["final_holdout"])
    ydev, yho = dev["target_A"].to_numpy(), ho["target_A"].to_numpy()

    scores_ho, scores_dev = {}, {}
    for arm in ("stationary_full", "stationary_geometry_no_direction"):
        f = surface["arms"][arm]["ordered_features"]
        _, (sd, sh) = fit_score(cfg, dev[f], ydev, [dev[f], ho[f]])
        scores_dev[arm], scores_ho[arm] = sd, sh
    for arm in ("direction_only", "mtf_state_only"):
        cr = CellRate(surface["arms"][arm]["ordered_features"]).fit(dev, ydev)
        scores_dev[arm], scores_ho[arm] = cr.predict(dev), cr.predict(ho)
    pairs = [("stationary_full", "mtf_state_only"), ("stationary_full", "direction_only"),
             ("stationary_geometry_no_direction", "mtf_state_only")]
    res = auc_ci(yho, scores_ho, ho["session"], pairs)
    for arm in scores_dev:
        res[arm]["refit_in_sample_auc"] = auc(ydev, scores_dev[arm])

    pooled = ho["target_A"].mean()
    conc, mono = [], {}
    for arm in scores_ho:
        sd, sh = scores_dev[arm], scores_ho[arm]
        q5 = list(np.quantile(sd, [0.2, 0.4, 0.6, 0.8]))
        q10 = list(np.quantile(sd, np.arange(1, 10) / 10))
        t5 = bin_table(ho, sh, q5, [f"Q{i}" for i in range(1, 6)], n_ho_sessions)
        t10 = bin_table(ho, sh, q10, [f"D{i}" for i in range(1, 11)], n_ho_sessions)
        mono[arm] = {"quintiles": monotonic(t5), "deciles": monotonic(t10)}
        tops = []
        for k in (50, 30, 20, 10):
            thr = float(np.quantile(sd, 1 - k / 100))
            part = ho[sh >= thr]
            row = summarise(part, f"top{k}", n_ho_sessions, len(ho), pooled)
            row["dev_threshold"] = thr
            row["target_A_win_pct_ci95"] = [100 * x if x is not None else None for x in session_ci(part, "target_A")]
            row["mean_terminal_gross_atr_ci95"] = session_ci(part, "terminal_gross_pnl_atr")
            tops.append(row)
        allrow = summarise(ho, "pooled", n_ho_sessions, len(ho), pooled)
        for t in (t5, t10):
            t["target_A_win_pct_ci95"] = [[100 * x if x is not None else None for x in session_ci(ho[np.searchsorted(np.asarray(q), sh, side="right") == i], "target_A")]
                                          for q in [q5 if t is t5 else q10] for i in range(len(t))]
        frame = pd.concat([pd.DataFrame([allrow]), t5, t10, pd.DataFrame(tops)], ignore_index=True)
        frame.insert(0, "arm", arm)
        conc.append(frame)
    conc_df = pd.concat(conc, ignore_index=True)
    conc_df["target_A_win_pct_ci95"] = conc_df["target_A_win_pct_ci95"].astype(str)
    conc_df["mean_terminal_gross_atr_ci95"] = conc_df.get("mean_terminal_gross_atr_ci95", pd.Series(dtype=object)).astype(str)
    write_table("SCORE_CONCENTRATION", conc_df)

    ho_rows = [{"arm": a, "n": len(ho), "sessions": n_ho_sessions, "positives": int(yho.sum()), "auc": res[a]["auc"],
                "auc_ci_lo": res[a]["ci95"][0], "auc_ci_hi": res[a]["ci95"][1], "refit_in_sample_auc": res[a]["refit_in_sample_auc"]}
               for a in scores_ho]
    for a, b in pairs:
        d = res[f"delta_{a}_vs_{b}"]
        ho_rows.append({"arm": f"delta:{a}-{b}", "auc": d["delta"], "auc_ci_lo": d["ci95"][0], "auc_ci_hi": d["ci95"][1]})
    write_table("FINAL_HOLDOUT_RESULTS", pd.DataFrame(ho_rows))

    # gates
    dm, dd = res["delta_stationary_full_vs_mtf_state_only"], res["delta_stationary_full_vs_direction_only"]
    valbins = pd.read_parquet(OUT / "DEVELOPMENT_VALIDATION_BINS.parquet")
    vb = valbins[valbins["config"] == cfg["id"]]
    vmono = monotonic(vb.reset_index(drop=True))
    fm = mono["stationary_full"]["quintiles"]
    g = {"holdout_skill": res["stationary_full"]["ci95"][0] > 0.5,
         "beats_mtf_state_only": dm["ci95"][0] > 0 and dm["delta"] >= CONTROL_MARGIN,
         "beats_direction_only": dd["ci95"][0] > 0 and dd["delta"] >= CONTROL_MARGIN,
         "monotonic_quality": (fm["target_A"] or -1) >= MONO_QUALITY_MIN,
         "variance_signature": all((x or -1) >= VARIANCE_MIN for x in (fm["fav2_before_terminal"], fm["adv1_before_terminal"],
                                                                      vmono["fav2_before_terminal"], vmono["adv1_before_terminal"]))}
    if g["holdout_skill"] and g["beats_mtf_state_only"] and g["beats_direction_only"] and g["monotonic_quality"] and not g["variance_signature"]:
        verdict = "CAPACITY_FIXED_SIGNAL_FOUND"
    elif g["variance_signature"]:
        verdict = "VARIANCE_NOT_QUALITY"
    else:
        verdict = "CAPACITY_FIXED_NO_INCREMENTAL_SIGNAL"
    excl = [e["feature"] for e in surface["excluded"]]
    feats = surface["arms"]["stationary_full"]["ordered_features"]
    po = pct_outside(dev, ho, excl + feats)
    out = {"kind": "final_holdout_results", "config": cfg["id"], "holdout": {"n": len(ho), "sessions": n_ho_sessions,
           "positives": int(yho.sum()), "negatives": int((yho == 0).sum()), "positive_rate": float(yho.mean())},
           "auc": res, "monotonicity": mono, "validation_monotonicity_selected": vmono, "gates": g, "verdict": verdict,
           "nonstationarity_holdout_vs_first80": {"excluded_22_mean": float(np.mean([po[c] for c in excl])),
                                                  "stationary_mean": float(np.mean([po[c] for c in feats])),
                                                  "stationary_max": float(np.max([po[c] for c in feats]))},
           "development_gate_sha256": sha_file(OUT / "DEVELOPMENT_GATE.json")}
    write_json("FINAL_HOLDOUT_RESULTS.json", out)
    print(pd.DataFrame(ho_rows).to_string())
    print(json.dumps({"gates": g, "verdict": verdict, "mono": mono}, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["contract", "develop", "final"])
    {"contract": stage_contract, "develop": stage_develop, "final": stage_final}[ap.parse_args().stage]()
