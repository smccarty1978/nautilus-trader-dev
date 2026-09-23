"""T0 development (favourable-reach) follow-up study -- 2023 ONLY, same T0, different future label.

Stages, each refusing to run without the previous stage's hashed freeze:

  audit     lineage/reuse proof, +2A/+3A entry-ATR target audit (4 independent paths incl. raw 1s bars),
            FUTURE_5M_ALIGNMENT label audit (2 implementations), target-blind stationarity screens,
            bucket list, frozen contract. Fits nothing. Reads no final-20% label except inside the
            population/target audits, which count labels over the whole audited population and are
            never split by block.
  develop   canary + 60%->20% development over the frozen ladder; frozen gate; selection.
  final     only if the gate passed: the FROZEN development model (no refit) scores the final 20% once.

    python studies/nq_t0_development_reach_2023/development_model.py audit|develop|final
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

OUT = HERE / "artifacts"
ROOT = REPO.parent
BASE = REPO.name.split("-")[0]
PRIOR = ROOT / f"{BASE}-nq_mtf_structural_predictive_ranking" / "studies" / "nq_mtf_structural_predictive_ranking"
MERGED = PRIOR / "_work" / "controller" / "merged"
CONSTRAINED = ROOT / f"{BASE}-nq_target_a_constrained_stationary_2023" / "studies" / "nq_target_a_constrained_stationary_2023" / "artifacts"
ATLAS = ROOT / f"{BASE}-nq_mtf_regime_structural_geometry_atlas" / "studies" / "nq_mtf_regime_structural_geometry_atlas" / "artifacts"
CATALOG = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader/data/catalog/NQ_1S_V2_GLOBEX")
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
YEAR = 2023
NS = 1_000_000_000

EXPECT_SHA = {
    "merged/candidates.parquet": "475209b46caf48b674d66833f56005c8fc6c6436f34c8aa50626da7d07300842",
    "merged/observations.parquet": "98e03dc4a2cf01b44d05c45d84b81af5768848142216945cfd133e13d66303b6",
}
PRIOR_POP_DIGEST = None  # read from the constrained study's PHASE0_REUSE_PROOF.json

SHUFFLE_SEED = 20260923
MODEL_SEED = 42
BOOT_SEED = 20260924
BOOT_REPS = 2000
CANARY_MAX = 0.70
SELECTION_TOL = 0.01
CONTROL_M = 20.0
SCREEN_A_MAX_PCT_OUTSIDE = 25.0     # % of validation rows outside the development-train [min, max]
SCREEN_B_MAX_ABS_RHO_TIME = 0.50    # |Spearman(feature, observation_ts)| inside development train
GATE = {"delta_auc_min": 0.02, "q5_minus_pooled_fav2_min_pp": 5.0, "mono_spearman_min": 0.9,
        "q5_min_n": 150, "q5_min_share": 0.10}
HOLDOUT = {"mono_spearman_min": 0.8}

REACH = {  # atlas definition (atlas_2023_columns.json), bound = terminal flip, strict
    "fav2": ("fp_fav_2p00", "POSITIVE"), "fav3": ("fp_fav_3p00", "POSITIVE"),
    "adv0p5": ("fp_adv_0p50", "NEGATIVE"), "adv1": ("fp_adv_1p00", "NEGATIVE"),
}
BOUND_EXPR = ("where(terminal_flip_disposition == 'LABELED_POSITIVE', terminal_flip_ts, "
              "where(terminal_flip_censor_reason == 'SESSION_END', session_close_ts, null))")


def reach_expr(prefix: str, disp: str) -> str:
    return (f"where({prefix}_disposition == '{disp}' and (bound_ts - executable_entry_ts) / 1000000000 > "
            f"{prefix}_resolution_seconds, 1, 0)")


# ----------------------------------------------------------------------------- utilities
def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha_list(x) -> str:
    return hashlib.sha256(json.dumps(x).encode()).hexdigest()


def _jsonable(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    raise TypeError(type(v))


def write_json(name: str, payload: dict) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=_jsonable) + "\n", encoding="utf-8")
    return sha_file(OUT / name)


def write_table(name: str, df: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False)
    df.to_parquet(OUT / f"{name}.parquet", index=False)


def read_frozen(name: str, sha: str | None = None) -> dict:
    p = OUT / name
    if not p.is_file():
        raise SystemExit(f"CONTRACT_MISSING: {name}")
    if sha and sha_file(p) != sha:
        raise SystemExit(f"CONTRACT_CHANGED: {name}")
    return json.loads(p.read_text(encoding="utf-8"))


def auc(y, s) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(np.asarray(y, dtype=int), np.asarray(s, dtype=float)))


def spearman(x, y):
    s = pd.Series(np.asarray(y, dtype=float))
    if s.nunique() < 2:
        return None
    return float(pd.Series(np.asarray(x, dtype=float)).rank().corr(s.rank()))


# ----------------------------------------------------------------------------- frame
def load_merged() -> pd.DataFrame:
    c = pd.read_parquet(MERGED / "candidates.parquet")
    o = pd.read_parquet(MERGED / "observations.parquet")
    dup = [col for col in o.columns if col in c.columns and col not in KEY]
    f = c.merge(o.drop(columns=dup), on=KEY, how="inner")
    f["_year"] = pd.to_datetime(f["observation_ts"], unit="ns", utc=True).dt.year
    return f[f["_year"] == YEAR].copy()   # 2024 dropped here and never referenced again


def add_labels(t: pd.DataFrame) -> pd.DataFrame:
    """Raw-pandas construction of every label (path 2 of the target audit)."""
    t = t.copy()
    bound = np.where(t["terminal_flip_disposition"] == "LABELED_POSITIVE", t["terminal_flip_ts"],
                     np.where(t["terminal_flip_censor_reason"] == "SESSION_END", t["session_close_ts"], np.nan))
    t["bound_ts"] = bound
    window_s = (t["bound_ts"] - t["executable_entry_ts"]) / NS
    for name, (prefix, disp) in REACH.items():
        t[name] = ((t[f"{prefix}_disposition"] == disp) & (window_s > t[f"{prefix}_resolution_seconds"])).astype(int)
    g = t["terminal_gross_pnl_atr"]
    t["target_A"] = np.where(g.isna(), np.nan, (g > 0).astype(float))
    return t


def population(t0: pd.DataFrame) -> pd.DataFrame:
    pop = t0[t0["target_A"].isin([0.0, 1.0])].copy()
    pop["target_A"] = pop["target_A"].astype(int)
    pop["session"] = globex_trading_day(pop["observation_ts"])
    return pop


# ----------------------------------------------------------------------------- 1s path recompute
def path_recompute(pop: pd.DataFrame) -> pd.DataFrame:
    """Path 4: re-derive +2A/+3A reach from the raw 1s catalog with atr_entry_1m as the denominator.

    Kernel convention (research_workflow/host/outcomes.py): entry = OPEN of the first 1s bar with
    ts_init > T, entry instant = that bar's ts_event; the entry bar and every later bar are
    touch-eligible; touch when favourable excursion >= k * ATR; a bar gap > max_gap (300 s) before the
    touch censors. Reach-before-terminal = touch bar close strictly before bound_ts.
    """
    from utils.runner.data import CausalDataLoader
    loader = CausalDataLoader(CATALOG)
    out = []
    for sess, part in pop.groupby("session"):
        start = pd.Timestamp(int(part["decision_epoch_ts_ns"].min()), tz="UTC") - pd.Timedelta(seconds=5)
        end = pd.Timestamp(int(np.nanmax(part["bound_ts"])), tz="UTC") + pd.Timedelta(seconds=5)
        bars = loader.load_bars(BAR_TYPE, start, end)
        ti = np.fromiter((b.ts_init for b in bars), dtype=np.int64, count=len(bars))
        te = np.fromiter((b.ts_event for b in bars), dtype=np.int64, count=len(bars))
        op = np.fromiter((b.open.as_double() for b in bars), dtype=float, count=len(bars))
        hi = np.fromiter((b.high.as_double() for b in bars), dtype=float, count=len(bars))
        lo = np.fromiter((b.low.as_double() for b in bars), dtype=float, count=len(bars))
        for r in part.itertuples():
            T, bound, d, atr = int(r.decision_epoch_ts_ns), int(r.bound_ts), int(r.dir_1m), float(r.atr_entry_1m)
            i0 = int(np.searchsorted(ti, T, side="right"))
            i1 = int(np.searchsorted(ti, bound, side="left"))       # bars with ts_init < bound
            ep, ets = op[i0], te[i0]
            rec = {"regime_start_ns": r.regime_start_ns, "p_entry_price": ep, "p_entry_ts": ets}
            seg_ti = ti[i0:i1]
            gaps = np.diff(np.concatenate([[ets], seg_ti]))
            gap_at = np.flatnonzero(gaps > 300 * NS)
            first_gap = int(gap_at[0]) if len(gap_at) else None
            h, lw = hi[i0:i1], lo[i0:i1]
            fav = (h - ep) if d > 0 else (ep - lw)
            for name, k in (("fav2", 2.0), ("fav3", 3.0), ("adv0p5", 0.5), ("adv1", 1.0)):
                if name.startswith("fav"):          # kernel: good = ep + d*k*atr; hi >= good (long) / lo <= good (short)
                    good = ep + d * k * atr
                    touch = (h >= good) if d > 0 else (lw <= good)
                else:                                # kernel: bad = ep - d*k*atr; lo <= bad (long) / hi >= bad (short)
                    bad = ep - d * k * atr
                    touch = (lw <= bad) if d > 0 else (h >= bad)
                hit = np.flatnonzero(touch)
                j = int(hit[0]) if len(hit) else None
                ok = j is not None and (first_gap is None or j < first_gap)
                rec[f"p_{name}"] = int(ok)
                rec[f"p_{name}_res_s"] = (seg_ti[j] - ets) / NS if ok else np.nan
            rec["p_max_fav_atr"] = float(fav.max() / atr) if len(fav) else np.nan
            out.append(rec)
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- 5m future label
def future_5m_alignment(frame: pd.DataFrame, pop: pd.DataFrame) -> pd.DataFrame:
    """Implementation 1: exact chain walk-back over 5m regime links observed anywhere in the 2023 frame.

    A 5m regime is identified by start_ns_5m (its flip-detection bar close; prior_frozen_at == start);
    every observation carries (current start, dir) and (prior start, dir). Label = 1 iff a 5m regime with
    dir == trade dir STARTED strictly inside (T0 observation, terminal flip). The regime current at the
    terminal flip is read from the first observation at or after it in the same session, and the chain is
    walked back to the T0 regime; any missing link makes the label NULL (never guessed).
    """
    f = frame[["observation_ts", "start_ns_5m", "dir_5m", "prior_start_ns_5m", "prior_dir_5m"]].copy()
    f["session"] = globex_trading_day(f["observation_ts"])
    dir_of, link = {}, {}
    conflicts = 0
    for s, dcur, ps, pdir in f[["start_ns_5m", "dir_5m", "prior_start_ns_5m", "prior_dir_5m"]].itertuples(index=False):
        for k, v in ((s, dcur), (ps, pdir)):
            if pd.isna(k):
                continue
            k = int(k)
            if k in dir_of and dir_of[k] != v:
                conflicts += 1
            dir_of[k] = v
        if not pd.isna(ps):
            if int(s) in link and link[int(s)] != int(ps):
                conflicts += 1
            link[int(s)] = int(ps)
    f = f.sort_values("observation_ts")
    obs_by_sess = {k: (g["observation_ts"].to_numpy(), g["start_ns_5m"].to_numpy()) for k, g in f.groupby("session")}
    rows = []
    for r in pop.itertuples():
        t0, T, s0, d = int(r.observation_ts), int(r.bound_ts), int(r.start_ns_5m), int(r.dir_1m)
        ts, st = obs_by_sess[r.session]
        j = int(np.searchsorted(ts, T, side="left"))
        rec = {"regime_start_ns": r.regime_start_ns, "f5_label": np.nan, "f5_status": None, "f5_flips_in_window": np.nan,
               "f5_obs_lag_s": np.nan, "f5_aligned_at_T0": int(dir_of.get(s0) == d)}
        if j >= len(ts):
            rec["f5_status"] = "NO_OBSERVATION_AFTER_TERMINAL_IN_SESSION"
            rows.append(rec)
            continue
        rec["f5_obs_lag_s"] = (ts[j] - T) / NS
        cur, chain = int(st[j]), []
        while cur > s0:
            chain.append(cur)
            if cur not in link:
                cur = None
                break
            cur = link[cur]
        if cur is None:
            rec["f5_status"] = "CHAIN_BROKEN"
        elif cur != s0:
            rec["f5_status"] = "CHAIN_INCONSISTENT"
        else:
            inside = [c for c in chain if t0 < c < T]
            rec["f5_status"] = "EXACT"
            rec["f5_flips_in_window"] = len(inside)
            rec["f5_label"] = int(any(dir_of[c] == d for c in inside))
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.attrs["conflicts"] = conflicts
    # implementation 2: interval query over the union of every known regime start (no chain walk)
    starts = np.array(sorted(dir_of))
    dirs = np.array([dir_of[s] for s in starts])
    lab2 = []
    for r in pop.itertuples():
        lo_i, hi_i = np.searchsorted(starts, int(r.observation_ts), "right"), np.searchsorted(starts, int(r.bound_ts), "left")
        lab2.append(int((dirs[lo_i:hi_i] == int(r.dir_1m)).any()))
    out["f5_label_impl2"] = lab2
    return out


# ----------------------------------------------------------------------------- audit stage
def stage_audit() -> None:
    from research.analysis.expressions import Evaluator, parse
    shas = {n: sha_file(MERGED / n.split("/")[1]) for n in EXPECT_SHA}
    if shas != EXPECT_SHA:
        raise SystemExit("INVALID_EXPERIMENT: source frame hash differs from the audited frame")
    frame = load_merged()
    t0 = add_labels(frame[frame["checkpoint_index"] == 0])
    pop = population(t0)
    prior = json.loads((CONSTRAINED / "PHASE0_REUSE_PROOF.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(pop.sort_values("regime_start_ns")[["regime_start_ns", "target_A"]].to_numpy().tobytes()).hexdigest()
    reuse = {"N": len(pop), "positives_A": int(pop["target_A"].sum()), "nulls_A": int(t0["target_A"].isna().sum()),
             "unique_trade_keys": int(pop["regime_start_ns"].nunique()), "duplicate_keys": int(pop.duplicated(KEY).sum()),
             "sessions": int(pop["session"].nunique()), "population_row_digest": digest,
             "prior_population_row_digest": prior["population_row_digest"],
             "digest_match": digest == prior["population_row_digest"], "source_sha256": shas,
             "t0_feature_parity": "frozen FULL model score digest 8fa2031cd01d9a7a reproduced on this exact frame in the constrained study (PHASE0_REUSE_PROOF.json)",
             "prior_reuse_proof_sha256": sha_file(CONSTRAINED / "PHASE0_REUSE_PROOF.json")}
    if not reuse["digest_match"] or reuse["N"] != 7475 or reuse["duplicate_keys"]:
        raise SystemExit("INVALID_EXPERIMENT: population differs from the audited population")

    # ---- target audit: 4 paths
    t0e = t0.copy()
    ev = Evaluator(t0e)
    t0e["bound_ts_expr"] = ev.materialize(ev.eval(parse(BOUND_EXPR)))
    bound_mismatch = int((t0e["bound_ts_expr"].astype("float64").fillna(-1) != t0e["bound_ts"].astype("float64").fillna(-1)).sum())
    t0e = t0e.rename(columns={"bound_ts": "bound_ts_pandas"}).rename(columns={"bound_ts_expr": "bound_ts"})
    ev = Evaluator(t0e)
    expr_mm = {}
    for name, (prefix, disp) in REACH.items():
        v = pd.Series(ev.materialize(ev.eval(parse(reach_expr(prefix, disp)))), index=t0e.index).astype("float64")
        expr_mm[name] = int((v != t0[name].astype("float64")).sum())
    atlas = pd.read_parquet(ATLAS / "atlas_2023_frame.parquet")
    atlas_sha = sha_file(ATLAS / "atlas_2023_frame.parquet")
    atlas_cols = json.loads((ATLAS / "atlas_2023_columns.json").read_text(encoding="utf-8"))
    atlas_expr = {c["name"]: c["expr"] for c in atlas_cols["columns"]}
    j = t0.merge(atlas[["regime_start_ns", "observation_ts", "reach_fav_2p00", "reach_fav_3p00", "reach_adv_0p50", "reach_adv_1p00",
                        "atr_entry_1m", "dir_1m", "executable_entry_price"]], on="regime_start_ns", how="outer", suffixes=("", "_atlas"), indicator=True)
    atlas_mm = {"join_both": int((j["_merge"] == "both").sum()), "join_left_only": int((j["_merge"] == "left_only").sum()),
                "join_right_only": int((j["_merge"] == "right_only").sum())}
    jb = j[j["_merge"] == "both"]
    for ours, theirs in (("fav2", "reach_fav_2p00"), ("fav3", "reach_fav_3p00"), ("adv0p5", "reach_adv_0p50"), ("adv1", "reach_adv_1p00")):
        atlas_mm[ours] = int((jb[ours].astype(float) != jb[theirs].astype(float)).sum())
    for col in ("atr_entry_1m", "dir_1m", "executable_entry_price", "observation_ts"):
        atlas_mm[f"column_{col}"] = int((jb[col].astype(float) != jb[f"{col}_atlas"].astype(float)).sum())
    atlas_mm["expr_text_identical"] = {n: atlas_expr.get(f"reach_{REACH[n][0][3:]}") == reach_expr(*REACH[n]) for n in REACH}
    atlas_mm["bound_expr_identical"] = atlas_expr.get("bound_ts") == BOUND_EXPR

    path = path_recompute(pop)
    pj = pop.merge(path, on="regime_start_ns", how="left")
    path_mm = {"entry_price": int((pj["p_entry_price"] != pj["executable_entry_price"]).sum()),
               "entry_ts": int((pj["p_entry_ts"] != pj["executable_entry_ts"]).sum())}
    for name in ("fav2", "fav3", "adv0p5", "adv1"):
        path_mm[name] = int((pj[f"p_{name}"] != pj[name]).sum())
        pos = pj[pj[name] == 1]
        path_mm[f"{name}_resolution_seconds"] = int((pos[f"p_{name}_res_s"] != pos[f"{REACH[name][0]}_resolution_seconds"]).sum())
    # denominator identity: the same path with a DIFFERENT atr would disagree; record the wrong definition too
    wrong = {"raw_fp_fav_2p00_label_rate_all_T0": float((t0["fp_fav_2p00_label"] == 1).mean()),
             "why_wrong": "fp_fav_2p00_label ignores the terminal flip: it reports any +2A touch within 24h / the session, after the trade has already exited"}
    pos_fav2, pos_fav3 = int(pop["fav2"].sum()), int(pop["fav3"].sum())
    total_mm = sum(v for k, v in expr_mm.items()) + bound_mismatch + sum(atlas_mm[k] for k in ("fav2", "fav3", "adv0p5", "adv1")) + \
        sum(v for k, v in path_mm.items())
    target_audit = {
        "kind": "target_definition_audit", "year": YEAR,
        "primary": {"id": "reach_fav_2p00_before_terminal", "expression": reach_expr(*REACH["fav2"]), "bound_ts": BOUND_EXPR,
                    "numerator": pos_fav2, "denominator": len(pop), "prevalence": pos_fav2 / len(pop),
                    "prevalence_all_7489_T0": float(t0["fav2"].mean()), "nulls": 0,
                    "censored_barrier_rows_counted_zero": int((pop["fp_fav_2p00_disposition"] == "CENSORED").sum()),
                    "source_columns": ["fp_fav_2p00_disposition", "fp_fav_2p00_resolution_seconds", "executable_entry_ts",
                                       "terminal_flip_disposition", "terminal_flip_ts", "terminal_flip_censor_reason", "session_close_ts"],
                    "atr_denominator": "atr_entry_1m (= excursion_1m.frozen_atr at T0, the outcome ATR) -- proven by the raw 1s path recompute"},
        "secondary_diagnostic": {"id": "reach_fav_3p00_before_terminal", "expression": reach_expr(*REACH["fav3"]),
                                 "numerator": pos_fav3, "denominator": len(pop), "prevalence": pos_fav3 / len(pop)},
        "diagnostics": {n: {"expression": reach_expr(*REACH[n]), "prevalence": float(pop[n].mean())} for n in ("adv0p5", "adv1")},
        "historical_baseline_check": {"atlas_2023_all_T0_fav2": 0.369, "this_frame_all_T0_fav2": float(t0["fav2"].mean())},
        "independent_recomputations": {
            "path1_platform_expression_grammar_vs_path2_pandas": {"bound_ts_mismatch": bound_mismatch, **expr_mm, "rows": len(t0)},
            "path3_atlas_study_frame_parity": {**atlas_mm, "atlas_frame_sha256": atlas_sha},
            "path4_raw_1s_catalog_recompute_with_atr_entry_1m": {**path_mm, "rows": len(pop), "catalog": str(CATALOG), "bar_type": BAR_TYPE},
        },
        "wrong_definition_recorded": wrong,
        "mismatch_count_total": total_mm,
        "PASS": total_mm == 0 and atlas_mm["join_left_only"] == 0 and atlas_mm["join_right_only"] == 0,
        "reuse": reuse,
    }
    write_json("TARGET_DEFINITION_AUDIT.json", target_audit)
    if not target_audit["PASS"]:
        raise SystemExit(f"INVALID_EXPERIMENT: target cannot be reconstructed exactly (mismatches {total_mm})")

    # ---- FUTURE_5M_ALIGNMENT
    f5 = future_5m_alignment(frame, pop)
    exact = f5[f5["f5_status"] == "EXACT"]
    f5_audit = {"kind": "future_5m_alignment_label_audit", "definition": "1 iff a 5m regime whose dir == the trade's 1m direction STARTED strictly after the T0 observation and strictly before the terminal opposite 1m flip",
                "role": "FUTURE LABEL -- never a feature; no model is trained on it in this study",
                "status_counts": f5["f5_status"].value_counts().to_dict(), "regime_map_conflicts": f5.attrs["conflicts"],
                "exact_n": len(exact), "prevalence_exact": float(exact["f5_label"].mean()),
                "impl1_vs_impl2_mismatch_on_exact": int((exact["f5_label"] != exact["f5_label_impl2"]).sum()),
                "obs_lag_s_after_terminal": exact["f5_obs_lag_s"].describe().to_dict(),
                "flips_in_window": exact["f5_flips_in_window"].value_counts().sort_index().to_dict()}
    write_json("FUTURE_5M_LABEL_AUDIT.json", f5_audit)
    if f5_audit["impl1_vs_impl2_mismatch_on_exact"] or f5_audit["regime_map_conflicts"]:
        raise SystemExit("INVALID_EXPERIMENT: future 5m label not reproducible")
    labels = pop[["regime_start_ns", "session", "target_A", "terminal_gross_pnl_atr", "fav2", "fav3", "adv0p5", "adv1"]].merge(
        f5[["regime_start_ns", "f5_label", "f5_status", "f5_aligned_at_T0"]], on="regime_start_ns")
    labels.to_parquet(OUT / "labels.parquet", index=False)

    # ---- stationarity screens (development rows only, features only, target-blind)
    split = json.loads((CONSTRAINED / "TEMPORAL_SPLIT_2023.json").read_text(encoding="utf-8"))
    surface = json.loads((CONSTRAINED / "STATIONARY_FEATURE_SURFACE.json").read_text(encoding="utf-8"))
    blk = {k: set(v["session_list"]) for k, v in split["blocks"].items()}
    tr = pop[pop["session"].isin(blk["development_train"])]
    va = pop[pop["session"].isin(blk["development_validation"])]
    start = surface["arms"]["stationary_full"]["ordered_features"]
    rows = []
    for c in start:
        lo, hi = tr[c].min(), tr[c].max()
        v = va[c].dropna()
        pct = float(100 * ((v < lo) | (v > hi)).mean()) if len(v) else 0.0
        rho = spearman(tr["observation_ts"], tr[c]) if tr[c].nunique() > 1 else None
        const = tr[c].nunique(dropna=True) <= 1
        flags = [n for n, hit in (("A_extrapolation", pct >= SCREEN_A_MAX_PCT_OUTSIDE),
                                  ("B_time_proxy", rho is not None and abs(rho) >= SCREEN_B_MAX_ABS_RHO_TIME),
                                  ("C_constant_in_train", const),
                                  ("D_named_counter", c.startswith("prior_rotation_seq_"))) if hit]
        rows.append({"feature": c, "val_pct_outside_train_range": pct, "spearman_vs_time_train": rho,
                     "train_unique": int(tr[c].nunique()), "flags": ";".join(flags), "excluded": bool(flags)})
    screen = pd.DataFrame(rows)
    write_table("STATIONARITY_AUDIT", screen)
    kept = [r["feature"] for r in rows if not r["excluded"]]
    geom_prior = set(surface["arms"]["stationary_geometry_no_direction"]["ordered_features"])
    arms = {"stationary_full": kept, "stationary_geometry_no_direction": [c for c in kept if c in geom_prior],
            "direction_only": ["dir_1m"], "mtf_state_only": ["dir_1m", "dir_5m", "dir_15m", "dir_1h"]}
    for a, feats in arms.items():
        leak = [c for c in feats if c.startswith(("fp_", "terminal_", "f5_", "fav", "adv", "target", "executable_", "flip_", "time_to_flip"))]
        if leak:
            raise SystemExit(f"INVALID_EXPERIMENT: future column in {a}: {leak}")

    # ---- strongest previously identified positive-lift buckets (atlas 2023 nomination tests)
    nom = pd.read_parquet(ATLAS / "t2023_E_nomination_tests.parquet")
    nom_sha = sha_file(ATLAS / "t2023_E_nomination_tests.parquet")
    pos = nom[(nom["tested"]) & (nom["estimate"] > 0) & (nom["metric"].isin(["is_win", "reach_fav_2p00"]))
              & (nom["n_child"] >= 150) & (nom["n_rest"] >= 150)]   # rest-of-parent gate: the atlas lacked it and produced degenerate p ~ 0 contrasts
    pick = pd.concat([g.sort_values(["p_value", "estimate"], ascending=[True, False]).head(10) for _, g in pos.groupby("metric")])
    buckets = pick[["parent.mtf_state", "dimension", "child_value", "metric", "n_child", "child_mean", "rest_mean", "estimate", "p_value", "q_value"]]
    buckets = buckets.drop_duplicates(["parent.mtf_state", "dimension", "child_value"]).reset_index(drop=True)
    buckets.insert(0, "bucket_id", [f"B{i:02d}" for i in range(len(buckets))])

    ladder_prior = json.loads((CONSTRAINED / "CAPACITY_LADDER.json").read_text(encoding="utf-8"))
    contract = {
        "kind": "development_contract", "frozen_before_any_fit": True,
        "question": "same T0, same causal observation, different future label: does T0 rank +2A-before-terminal development?",
        "primary_target": target_audit["primary"]["expression"], "primary_target_id": "fav2",
        "secondary_diagnostic": {"id": "fav3", "rule": "reported only; can never rescue a failed +2A gate; no other thresholds tested"},
        "future_5m_alignment": "label only; never a feature; no model",
        "population": "the audited 7,475 T0 trades (Target-A-eligible), unchanged",
        "split": {"source": "nq_target_a_constrained_stationary_2023/artifacts/TEMPORAL_SPLIT_2023.json",
                  "sha256": sha_file(CONSTRAINED / "TEMPORAL_SPLIT_2023.json"),
                  "blocks": {k: [v["first_session"], v["last_session"], v["sessions"], v["N"]] for k, v in split["blocks"].items()}},
        "feature_surface": {"start": "constrained stationary_full (56), sha " + surface["arms"]["stationary_full"]["sha256"],
                            "screens": {"A": f"exclude if >= {SCREEN_A_MAX_PCT_OUTSIDE}% of validation rows fall outside the development-train range",
                                        "B": f"exclude if |Spearman(feature, observation_ts)| >= {SCREEN_B_MAX_ABS_RHO_TIME} inside development train",
                                        "C": "exclude if constant inside development train", "D": "exclude prior_rotation_seq_* (named within-year counters)"},
                            "target_blind": True,
                            "arms": {a: {"ordered_features": f, "n": len(f), "sha256": sha_list(f)} for a, f in arms.items()}},
        "capacity_ladder": {"source_sha256": sha_file(CONSTRAINED / "CAPACITY_LADDER.json"), "configurations": ladder_prior["configurations"],
                            "canary": {"seed": SHUFFLE_SEED, "max_random_label_train_auc": CANARY_MAX, "rows": "development train only"}},
        "controls": "exact-cell empirical +2A rate (smoothed m=20 toward the training prevalence), fitted on development train",
        "bins": "quintile/decile boundaries = quantiles of each model's development-TRAIN scores; frozen with the model",
        "development_gate": {
            "G1_canary": f"random-label train AUC <= {CANARY_MAX}",
            "G2_validation_auc": "session-blocked 95% CI lower bound > 0.50",
            "G3_controls": f"paired delta AUC vs mtf_state_only AND vs direction_only each >= {GATE['delta_auc_min']} with CI lower > 0",
            "G4_monotonic": f"Spearman(validation quintile, +2A rate) >= {GATE['mono_spearman_min']} AND Q5 +2A rate - validation pooled >= {GATE['q5_minus_pooled_fav2_min_pp']} pp",
            "G5_support": f"validation Q5 N >= {GATE['q5_min_n']} and >= {int(100 * GATE['q5_min_share'])}% of validation rows",
            "G6_not_variance": "(Q5 - Q1) rise in -1A reach < (Q5 - Q1) rise in +2A reach (always reported)",
            "selection": f"lowest capacity among configs passing G1-G6 whose validation AUC >= best passing - {SELECTION_TOL}",
            "none_pass": "NO_T0_DEVELOPMENT_SIGNAL; stop; final 20% stays dark"},
        "holdout_confirmation": {"rule": "the FROZEN development-train model (no refit), frozen bins, frozen controls",
                                 "H1": "AUC CI lower > 0.50", "H2": "paired delta vs both controls CI lower > 0",
                                 "H3": f"Spearman(quintile, +2A) >= {HOLDOUT['mono_spearman_min']}", "H4": "G6 rule holds",
                                 "all_pass": "DEVELOPMENT_SIGNAL_CONFIRMED", "otherwise": "DEVELOPMENT_SIGNAL_NOT_CONFIRMED"},
        "bucket_reconciliation": {"source": "nq_mtf_regime_structural_geometry_atlas t2023_E_nomination_tests.parquet", "sha256": nom_sha,
                                  "rule": "tested AND estimate > 0 AND n_child >= 150 AND n_rest >= 150, metric in {is_win, reach_fav_2p00}; top 10 per metric by p_value; deduplicated. The n_rest gate was added before any fit after the first draft picked 7 degenerate rest_mean=0 contrasts (atlas report: no rest-of-parent N gate)",
                                  "buckets": buckets.to_dict("records"),
                                  "disclosure": "the atlas selected these on full-year 2023, including the final 20% block"},
        "bound_to": {"TARGET_DEFINITION_AUDIT.json": sha_file(OUT / "TARGET_DEFINITION_AUDIT.json"),
                     "FUTURE_5M_LABEL_AUDIT.json": sha_file(OUT / "FUTURE_5M_LABEL_AUDIT.json"),
                     "STATIONARITY_AUDIT.csv": sha_file(OUT / "STATIONARITY_AUDIT.csv"),
                     "labels.parquet": sha_file(OUT / "labels.parquet"), "script": sha_file(Path(__file__))},
    }
    csha = write_json("DEVELOPMENT_CONTRACT.json", contract)
    write_json("CONTRACT_FREEZE.json", {"DEVELOPMENT_CONTRACT.json": csha})
    print(json.dumps({"reuse": {k: reuse[k] for k in ("N", "digest_match", "sessions")},
                      "target": {k: target_audit["primary"][k] for k in ("numerator", "denominator", "prevalence", "prevalence_all_7489_T0")},
                      "mismatch_total": total_mm, "path4": path_mm, "atlas": atlas_mm, "f5": {k: f5_audit[k] for k in ("status_counts", "exact_n", "prevalence_exact", "impl1_vs_impl2_mismatch_on_exact")},
                      "excluded": screen[screen.excluded][["feature", "flags"]].to_dict("records"),
                      "arms": {a: len(f) for a, f in arms.items()}, "buckets": len(buckets)}, indent=1, default=_jsonable))


# ----------------------------------------------------------------------------- modelling
def load_contract() -> dict:
    freeze = json.loads((OUT / "CONTRACT_FREEZE.json").read_text(encoding="utf-8"))
    return read_frozen("DEVELOPMENT_CONTRACT.json", freeze["DEVELOPMENT_CONTRACT.json"])


def lgbm(cfg: dict, **override):
    from lightgbm import LGBMClassifier
    p = {k: v for k, v in cfg.items() if k not in ("id", "capacity_rank", "max_total_leaves")}
    p.update(override)
    return LGBMClassifier(**p)


class CellRate:
    def __init__(self, cols, m=CONTROL_M):
        self.cols, self.m = cols, m

    def fit(self, X, y):
        d = X[self.cols].copy()
        d["_y"] = np.asarray(y)
        self.p0 = float(d["_y"].mean())
        g = d.groupby(self.cols)["_y"].agg(["sum", "count"])
        self.table = ((g["sum"] + self.m * self.p0) / (g["count"] + self.m)).rename("rate")
        return self

    def predict(self, X):
        return X[self.cols].merge(self.table.reset_index(), on=self.cols, how="left")["rate"].fillna(self.p0).to_numpy()


def boot_indices(sessions: pd.Series, reps: int, seed: int):
    rng = np.random.default_rng(seed)
    codes, uniq = pd.factorize(sessions)
    groups = [np.flatnonzero(codes == i) for i in range(len(uniq))]
    for _ in range(reps):
        yield np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])


def auc_ci(y, scores: dict, sessions, pairs=()):
    y = np.asarray(y)
    point = {k: auc(y, s) for k, s in scores.items()}
    draws = {k: [] for k in scores}
    for idx in boot_indices(pd.Series(sessions).reset_index(drop=True), BOOT_REPS, BOOT_SEED):
        if y[idx].min() == y[idx].max():
            continue
        for k, s in scores.items():
            draws[k].append(auc(y[idx], np.asarray(s)[idx]))
    out = {k: {"auc": point[k], "ci95": [float(np.percentile(draws[k], 2.5)), float(np.percentile(draws[k], 97.5))]} for k in scores}
    for a, b in pairs:
        d = np.asarray(draws[a]) - np.asarray(draws[b])
        out[f"delta_{a}_vs_{b}"] = {"delta": point[a] - point[b], "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]}
    return out


METRICS = [("fav2", "fav2_pct"), ("fav3", "fav3_pct"), ("target_A", "win_pct"), ("adv0p5", "adv0p5_pct"), ("adv1", "adv1_pct")]


def summarise(part: pd.DataFrame, label: str, n_sessions: int, n_total: int) -> dict:
    n = len(part)
    row = {"surface": label, "N": n, "pct_of_population": 100 * n / n_total if n_total else None, "trades_per_session": n / n_sessions}
    for col, name in METRICS:
        row[name] = 100 * part[col].mean() if n else None
    row["mean_terminal_gross_atr"] = part["terminal_gross_pnl_atr"].mean() if n else None
    ex = part[part["f5_status"] == "EXACT"]
    row["future_5m_align_pct"] = 100 * ex["f5_label"].mean() if len(ex) else None
    row["future_5m_exact_n"] = len(ex)
    return row


def bins_table(df: pd.DataFrame, s: np.ndarray, edges, prefix: str, n_sessions: int) -> pd.DataFrame:
    b = np.searchsorted(np.asarray(edges), s, side="right")
    return pd.DataFrame([summarise(df[b == i], f"{prefix}{i + 1}", n_sessions, len(df)) for i in range(len(edges) + 1)])


def score_tables(df: pd.DataFrame, s: np.ndarray, s_train: np.ndarray, n_sessions: int, arm: str, block: str) -> pd.DataFrame:
    q5 = list(np.quantile(s_train, [0.2, 0.4, 0.6, 0.8]))
    q10 = list(np.quantile(s_train, np.arange(1, 10) / 10))
    parts = [pd.DataFrame([summarise(df, "pooled", n_sessions, len(df))]), bins_table(df, s, q5, "Q", n_sessions),
             bins_table(df, s, q10, "D", n_sessions)]
    tops = []
    for k in (50, 30, 20, 10):
        thr = float(np.quantile(s_train, 1 - k / 100))
        tops.append({**summarise(df[s >= thr], f"top{k}", n_sessions, len(df)), "train_threshold": thr})
    out = pd.concat(parts + [pd.DataFrame(tops)], ignore_index=True)
    out.insert(0, "block", block)
    out.insert(0, "arm", arm)
    return out


def gate_metrics(tab: pd.DataFrame) -> dict:
    q = tab[tab["surface"].str.match(r"^Q\d$")].reset_index(drop=True)
    pooled = tab[tab["surface"] == "pooled"].iloc[0]
    x = np.arange(1, len(q) + 1)
    return {"spearman_fav2": spearman(x, q["fav2_pct"]), "spearman_fav3": spearman(x, q["fav3_pct"]),
            "spearman_win": spearman(x, q["win_pct"]), "spearman_adv1": spearman(x, q["adv1_pct"]),
            "spearman_adv0p5": spearman(x, q["adv0p5_pct"]), "spearman_mean_g": spearman(x, q["mean_terminal_gross_atr"]),
            "spearman_f5": spearman(x, q["future_5m_align_pct"]),
            "q5_fav2_minus_pooled_pp": float(q.iloc[-1]["fav2_pct"] - pooled["fav2_pct"]),
            "q5_n": int(q.iloc[-1]["N"]), "q5_share": float(q.iloc[-1]["N"] / pooled["N"]),
            "q5_minus_q1_fav2_pp": float(q.iloc[-1]["fav2_pct"] - q.iloc[0]["fav2_pct"]),
            "q5_minus_q1_adv1_pp": float(q.iloc[-1]["adv1_pct"] - q.iloc[0]["adv1_pct"])}


def frames(contract: dict, include_final: bool):
    frame = load_merged()
    t0 = add_labels(frame[frame["checkpoint_index"] == 0])
    pop = population(t0)
    labels = pd.read_parquet(OUT / "labels.parquet")[["regime_start_ns", "f5_label", "f5_status", "f5_aligned_at_T0"]]
    pop = pop.merge(labels, on="regime_start_ns", how="left")
    split = json.loads((CONSTRAINED / "TEMPORAL_SPLIT_2023.json").read_text(encoding="utf-8"))
    if sha_file(CONSTRAINED / "TEMPORAL_SPLIT_2023.json") != contract["split"]["sha256"]:
        raise SystemExit("CONTRACT_CHANGED: split")
    blk = {k: set(v["session_list"]) for k, v in split["blocks"].items()}
    if not include_final:
        pop = pop[~pop["session"].isin(blk["final_holdout"])]
    get = lambda name: pop[pop["session"].isin(blk[name])].reset_index(drop=True)  # noqa: E731
    return get("development_train"), get("development_validation"), (get("final_holdout") if include_final else None), blk


def stage_develop() -> None:
    contract = load_contract()
    tr, va, _, blk = frames(contract, include_final=False)
    arms = {a: v["ordered_features"] for a, v in contract["feature_surface"]["arms"].items()}
    feats = arms["stationary_full"]
    ytr, yva = tr["fav2"].to_numpy(), va["fav2"].to_numpy()
    shuffled = np.random.default_rng(SHUFFLE_SEED).permutation(ytr)
    n_va_sess = len(blk["development_validation"])

    ctrl_va, ctrl_tr = {}, {}
    for name in ("direction_only", "mtf_state_only"):
        cr = CellRate(arms[name]).fit(tr, ytr)
        ctrl_va[name], ctrl_tr[name] = cr.predict(va), cr.predict(tr)

    rows, tables, gates = [], [], {}
    for cfg in contract["capacity_ladder"]["configurations"]:
        m = lgbm(cfg).fit(tr[feats], ytr)
        s_tr, s_va = m.predict_proba(tr[feats])[:, 1], m.predict_proba(va[feats])[:, 1]
        s_nobag = lgbm(cfg, subsample_freq=0).fit(tr[feats], ytr).predict_proba(va[feats])[:, 1]
        if float(np.max(np.abs(s_va - s_nobag))) == 0.0:
            raise SystemExit(f"INVALID_EXPERIMENT: bagging inert for {cfg['id']}")
        mr = lgbm(cfg).fit(tr[feats], shuffled)
        r_auc = auc(shuffled, mr.predict_proba(tr[feats])[:, 1])
        res = auc_ci(yva, {"model": s_va, **ctrl_va}, va["session"], [("model", "direction_only"), ("model", "mtf_state_only")])
        tab = score_tables(va, s_va, s_tr, n_va_sess, f"stationary_full:{cfg['id']}", "validation")
        tables.append(tab)
        gm = gate_metrics(tab)
        dd, dm = res["delta_model_vs_direction_only"], res["delta_model_vs_mtf_state_only"]
        g = {"G1_canary": r_auc <= CANARY_MAX, "G2_validation_auc": res["model"]["ci95"][0] > 0.5,
             "G3_controls": all(x["delta"] >= GATE["delta_auc_min"] and x["ci95"][0] > 0 for x in (dd, dm)),
             "G4_monotonic": (gm["spearman_fav2"] or -1) >= GATE["mono_spearman_min"] and gm["q5_fav2_minus_pooled_pp"] >= GATE["q5_minus_pooled_fav2_min_pp"],
             "G5_support": gm["q5_n"] >= GATE["q5_min_n"] and gm["q5_share"] >= GATE["q5_min_share"],
             "G6_not_variance": gm["q5_minus_q1_adv1_pp"] < gm["q5_minus_q1_fav2_pp"]}
        gates[cfg["id"]] = g
        rows.append({"config": cfg["id"], "capacity_rank": cfg["capacity_rank"], "train_n": len(tr), "validation_n": len(va),
                     "real_label_train_auc": auc(ytr, s_tr), "shuffled_label_train_auc": r_auc,
                     "real_minus_shuffled_train_auc": auc(ytr, s_tr) - r_auc,
                     "validation_auc": res["model"]["auc"], "validation_auc_ci_lo": res["model"]["ci95"][0], "validation_auc_ci_hi": res["model"]["ci95"][1],
                     "delta_vs_direction_only": dd["delta"], "delta_vs_direction_only_ci_lo": dd["ci95"][0], "delta_vs_direction_only_ci_hi": dd["ci95"][1],
                     "delta_vs_mtf_state_only": dm["delta"], "delta_vs_mtf_state_only_ci_lo": dm["ci95"][0], "delta_vs_mtf_state_only_ci_hi": dm["ci95"][1],
                     "total_leaves": int(sum(t["num_leaves"] for t in m.booster_.dump_model()["tree_info"])),
                     "bagging_max_abs_pred_diff": float(np.max(np.abs(s_va - s_nobag))),
                     **{f"val_{k}": v for k, v in gm.items()}, **g, "all_gates": all(g.values())})
        if cfg["id"] == contract["capacity_ladder"]["configurations"][0]["id"]:
            ctrl_res = res
    for name in ("direction_only", "mtf_state_only"):
        rows.append({"config": f"control:{name}", "real_label_train_auc": auc(ytr, ctrl_tr[name]),
                     "validation_auc": ctrl_res[name]["auc"], "validation_auc_ci_lo": ctrl_res[name]["ci95"][0],
                     "validation_auc_ci_hi": ctrl_res[name]["ci95"][1]})
        tables.append(score_tables(va, ctrl_va[name], ctrl_tr[name], n_va_sess, f"control:{name}", "validation"))
    dev = pd.DataFrame(rows)
    write_table("DEVELOPMENT_MODEL_RESULTS", dev)
    write_table("SCORE_BINS_VALIDATION", pd.concat(tables, ignore_index=True))

    cand = dev[dev["capacity_rank"].notna() & dev["all_gates"].eq(True)]
    selected = None
    if len(cand):
        best = cand["validation_auc"].max()
        selected = cand[cand["validation_auc"] >= best - SELECTION_TOL].sort_values("capacity_rank").iloc[0]["config"]
    gate = {"kind": "development_gate", "gates": gates, "selected": selected, "gate_passed": selected is not None,
            "verdict_if_stop": None if selected else "NO_T0_DEVELOPMENT_SIGNAL", "final_holdout_opened": False,
            "contract_sha256": sha_file(OUT / "DEVELOPMENT_CONTRACT.json")}
    write_json("DEVELOPMENT_GATE.json", gate)

    # bucket reconciliation on VALIDATION rows (scores out of sample), using every config's validation score
    atlas = pd.read_parquet(ATLAS / "atlas_2023_frame.parquet")
    rec_rows = []
    for cfg in contract["capacity_ladder"]["configurations"]:
        m = lgbm(cfg).fit(tr[feats], ytr)
        va_s = va.assign(score=m.predict_proba(va[feats])[:, 1])
        dims = sorted({"mtf_state"} | {b["dimension"] for b in contract["bucket_reconciliation"]["buckets"]})
        va_s = va_s.merge(atlas[["regime_start_ns"] + dims], on="regime_start_ns", how="left", validate="1:1")
        for b in contract["bucket_reconciliation"]["buckets"]:
            parent = va_s if b["parent.mtf_state"] is None else va_s[va_s["mtf_state"] == b["parent.mtf_state"]]
            part = parent[parent[b["dimension"]].astype(str) == str(b["child_value"])]
            ex = part[part["f5_status"] == "EXACT"]
            rec_rows.append({"config": cfg["id"], "bucket_id": b["bucket_id"], "parent": b["parent.mtf_state"], "dimension": b["dimension"],
                             "child_value": b["child_value"], "atlas_metric": b["metric"], "atlas_2023_estimate": b["estimate"],
                             "atlas_2023_p": b["p_value"], "val_n": len(part), "val_mean_score": part["score"].mean() if len(part) else None,
                             "val_parent_mean_score": parent["score"].mean(), "val_pop_mean_score": va_s["score"].mean(),
                             "val_fav2_pct": 100 * part["fav2"].mean() if len(part) else None,
                             "val_fav3_pct": 100 * part["fav3"].mean() if len(part) else None,
                             "val_win_pct": 100 * part["target_A"].mean() if len(part) else None,
                             "val_parent_fav2_pct": 100 * parent["fav2"].mean(), "val_parent_win_pct": 100 * parent["target_A"].mean(),
                             "val_f5_pct": 100 * ex["f5_label"].mean() if len(ex) else None})
    write_table("BUCKET_RECONCILIATION", pd.DataFrame(rec_rows))
    print(dev[["config", "real_label_train_auc", "shuffled_label_train_auc", "validation_auc", "validation_auc_ci_lo",
               "validation_auc_ci_hi", "delta_vs_direction_only", "delta_vs_mtf_state_only", "all_gates"]].to_string())
    print(json.dumps({"gates": gates, "selected": selected}, indent=1, default=_jsonable))


def stage_final() -> None:
    contract = load_contract()
    gate = read_frozen("DEVELOPMENT_GATE.json")
    if not gate.get("gate_passed"):
        raise SystemExit("FINAL_HOLDOUT_LOCKED: development gate did not pass (NO_T0_DEVELOPMENT_SIGNAL)")
    raise SystemExit("final stage intentionally not implemented until the gate passes; implement against the frozen contract")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["audit", "develop", "final"])
    {"audit": stage_audit, "develop": stage_develop, "final": stage_final}[ap.parse_args().stage]()
