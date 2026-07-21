"""Sealed two-stage retrain on precomputed causal Policy-A outcome surfaces.

This script deliberately does not run NautilusTrader.  Its inputs are immutable,
NT-derived research surfaces; any result is research evidence, not NT validation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
WORK = HERE / "_work"
RESULTS = HERE / "results"
INPUT = ROOT / "studies/ohlcv_volume_delta_price_level_features/_work"
FOUNDATION_AUDIT = ROOT / "studies/ohlcv_volume_delta_price_level_features/audit/audit.md"
LOCAL_AUDIT = HERE / "audit/audit.md"
BASELINE_2025_FILE = HERE / "baseline_2025.json"
BASELINE_2025_SHA256 = "8ec12511477d81300d036fcc93c315d0878cb334076a64e182f1ee5435110e09"
# This commits the stage-2 dependency's identity without opening or importing it in stage 1.
SEALED_2026_SHA256 = "ac9521c385086ba1c282a8859f40de3080d6731882ac1b663a4b50753f19b354"
RECOVERY_CACHE_SHA256 = {
    "candidates": "d2df489e335fe2b7c3da59af262a5156b3c5541a270e416b90fd5b3e8d88c02b",
    "selected_schedule": "cbc11bd2e15dd14cf35c24248a14b49dbe1f5ab5e3940cdd3c0f02776417ccc2",
    "feature_manifest": "abf27c4651ae059a6e3edbeaaf71c04e1098a159ac3ac6076d6b636eb3265619",
    "readiness": "96a703f53e5057bc48522af6d1b9938512a6a6144c1e44609fa30210243df330",
}
FOUNDATION_MANIFEST = ROOT / "studies/ohlcv_volume_delta_price_level_features/results/full_manifest.json"
FOUNDATION_MANIFEST_SHA256 = "5ae3184cedc55332675824b39e4ea102491558c5fa9150d3f155b01830b9a553"
F0_SOURCE = ROOT / "studies/regime_sequence_chop_context/train_weakness_model.py"
REGISTRY_SOURCE = ROOT / "features/registry.py"
TRUSTED_INPUT_SHA256 = {2021: "0914a6d0bb50426732fbf3544e2277936f412e08635b47be8723cc795562c189", 2022: "c9ceaf80cc668f79224ab0d594ff2489c8538c8f4d39c3cebe3b45b66653c219", 2023: "fe2ae7dfd1c60cfa61de495e870dbb36d34c0f9a2a3651ba580015c3cb5114d8", 2024: "23a6a6fe34dd50c252fedf08b9e757101578a4f906953700a419da6e89fb7992", 2025: "72b457638d8d94c4a07f84c7e5ed470da60778a3cd312124af2c1b9a559a92a8", 2026: "877d907b29a4576993be43a47da16ff2dc5382bf91a80bbf9fa693de1001768a"}
COUNTS = {2021: 212241, 2022: 192378, 2023: 204742, 2024: 204611, 2025: 198255, 2026: 63021}
# `loser` is exhaustive for an unprofitable original opposing-flip exit.  It
# deliberately has a zero coefficient in the frozen score, rather than being
# silently folded into pre-alignment stops.
CLASSES = ("winner", "loser", "pre_alignment_stop", "confirmation_timeout", "post_alignment_stop")
BANDS = (1.0, .85, .7, .5, .35, .2)
PROVENANCE = {"observation_ts", "latest_source_ts_used", "latest_1s_bar_close_ts_used", "latest_1m_bar_close_ts_used"}
IDENTITY = {"nearest_level_above_name", "nearest_level_below_name"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
        json.dump(json_safe(value), f, indent=2, sort_keys=True, allow_nan=False, default=str)
        name = f.name
    os.replace(name, path)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        if np.isnan(value): return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.bool_): return bool(value)
    return value


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def load_baseline_2025() -> dict[str, float]:
    if sha256(BASELINE_2025_FILE) != BASELINE_2025_SHA256:
        raise RuntimeError("trusted 2025-only baseline hash mismatch")
    value=json.loads(BASELINE_2025_FILE.read_text(encoding="utf-8"))
    required={"per_trade","pf","dd","prestop","oppflip_pnl","prestop_pnl","provenance"}
    if required-set(value) or value["provenance"]!="user-provided frozen Baseline A": raise RuntimeError("sealed 2025 baseline invalid")
    return {k:float(value[k]) for k in required-{"provenance"}}


def exact_attribution(selected: pd.DataFrame, baseline: pd.DataFrame) -> tuple[dict[str, Any], pd.Series, pd.Series]:
    key = "regime_start_ns"
    left = baseline[[key, "net_pnl", "exit_reason", "entry_fill_ts", "exit_ts"]].rename(columns=lambda c: f"base_{c}" if c != key else c)
    right = selected[[key, "net_pnl", "exit_reason", "entry_ts", "exit_ts"]].rename(columns=lambda c: f"selected_{c}" if c != key else c)
    m = left.merge(right, on=key, how="outer", indicator=True)
    m["classification"] = m["_merge"].map({"both": "keep", "left_only": "drop", "right_only": "add"})
    m["moved_entry"] = (m["_merge"] == "both") & (m["base_entry_fill_ts"] != m["selected_entry_ts"])
    pre = m.base_exit_reason.eq("preflip_policy_stop")
    win = (m.base_exit_reason.eq("original_opposing_flip_exit")) & (m.base_net_pnl > 0)
    stop_savings = float(((m.selected_net_pnl.fillna(0) - m.base_net_pnl.fillna(0)).where(pre, 0)).sum())
    clipping = float(((m.base_net_pnl.fillna(0) - m.selected_net_pnl.fillna(0)).where(win, 0)).sum())
    return {"classification_counts": m.classification.value_counts().to_dict(), "moved_entry_count": int(m.moved_entry.sum()), "stop_savings_exact": stop_savings, "clipped_winners_exact": clipping, "clipped_winners_floor": max(0., clipping)}, m, pd.Series([stop_savings, clipping])


def require_audits() -> None:
    # The foundation warning is known to be dormant and limited to unwindowed artifacts.
    foundation = FOUNDATION_AUDIT.read_text(encoding="utf-8")
    final = foundation.rsplit("## Summary", 1)[-1].split("##", 1)[0]
    if "Critical: **0**" not in final: raise RuntimeError("foundation audit final summary is not zero-CRITICAL")
    local = LOCAL_AUDIT.read_text(encoding="utf-8")
    final_local = local.rsplit("## Summary", 1)[-1].split("##", 1)[0]
    if "Critical: **0**" not in final_local or "Warning: **0**" not in final_local or "Overall: PASS" not in final_local: raise RuntimeError("local audit final summary must be PASS/0/0")
    if sha256(FOUNDATION_MANIFEST) != FOUNDATION_MANIFEST_SHA256: raise RuntimeError("foundation manifest hash mismatch")
    foundation_manifest = json.loads(FOUNDATION_MANIFEST.read_text(encoding="utf-8"))
    for year, row in foundation_manifest.items():
        if not (row["row_count_unchanged"] and str(row["labels_unchanged"]) == "True" and row["duplicate_rows"] == 0 and row["provenance_violations"] == 0): raise RuntimeError("foundation per-year validation failed")


def f0_features() -> list[str]:
    path = F0_SOURCE
    spec = importlib.util.spec_from_file_location("_f0_source", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot dynamically import F0 source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    feats = list(module.CENTER_FEATS) + list(module.SEQUENCE_FEATS)
    if len(feats) != 149 or len(set(feats)) != 149:
        raise RuntimeError("F0 must be the exact ordered 149 CENTER_FEATS+SEQUENCE_FEATS")
    return feats


def registry_features() -> tuple[list[str], list[str], dict[str, Any]]:
    from features.registry import FEATURE_REGISTRY
    f1 = [n for n, d in FEATURE_REGISTRY.items() if d.family == "ohlcv_est_delta"]
    all_f2 = [n for n, d in FEATURE_REGISTRY.items() if d.family == "price_level_context"]
    raw_f2 = [n for n in all_f2 if n not in IDENTITY]
    bad = [n for n in f1 + raw_f2 if FEATURE_REGISTRY[n].status != "verified"]
    positions = [n for n in raw_f2 if n.endswith("_position")]
    numeric_f2 = [n for n in raw_f2 if n not in positions]
    if len(f1) != 214 or len(all_f2) != 247 or len(raw_f2) != 245 or len(positions) != 29 or len(numeric_f2) != 216:
        raise RuntimeError("registered family counts/status do not meet the frozen contract")
    if bad:
        raise RuntimeError(f"non-verified registered features: {bad}")
    metadata = {n: {"family": FEATURE_REGISTRY[n].family, "status": FEATURE_REGISTRY[n].status,
                    "version": FEATURE_REGISTRY[n].version} for n in f1 + raw_f2}
    return f1, numeric_f2, {"positions": positions, "metadata": metadata}


def manifests() -> dict[str, Any]:
    f0 = f0_features(); f1, f2, extra = registry_features()
    position_encoded = [f"{p}__{v}" for p in extra["positions"] for v in ("ABOVE", "BELOW", "TOUCH", "UNAVAILABLE")]
    sets = {"F0": f0, "F1": f0 + f1, "F2": f0 + f2 + position_encoded, "F3": f0 + f1 + f2 + position_encoded}
    expected = {"F0": 149, "F1": 363, "F2": 481, "F3": 695}
    if {k: len(v) for k, v in sets.items()} != expected:
        raise RuntimeError("feature manifest dimensions mismatch")
    return {"feature_sets": sets, "position_columns": extra["positions"], "registry": extra["metadata"]}


def label_frame(df: pd.DataFrame) -> pd.Series:
    if not df["label_available"].eq(True).all() or not df["entry_direction"].eq(-1).all():
        raise RuntimeError("labels unavailable or population is not exclusively short")
    reason = df["exit_reason"]
    if reason.isna().any(): raise RuntimeError("null exit reason")
    y = pd.Series(index=df.index, dtype="object")
    y[(reason == "original_opposing_flip_exit") & (df["net_pnl"] > 0)] = "winner"
    y[(reason == "original_opposing_flip_exit") & ~(df["net_pnl"] > 0)] = "loser"
    y[reason == "preflip_policy_stop"] = "pre_alignment_stop"
    y[reason == "confirmation_timeout_exit"] = "confirmation_timeout"
    y[reason == "original_stop_after_aligned_flip"] = "post_alignment_stop"
    if y.isna().any() or set(y.unique()) - set(CLASSES):
        raise RuntimeError("unknown or non-exhaustive exit-reason class map")
    return y


def validate_temporal_population(df: pd.DataFrame, year: int) -> None:
    ts_columns = ["regime_start_ns", "observation_time", "observation_ts", "entry_ts", "exit_ts", *PROVENANCE]
    for col in ts_columns:
        if not pd.api.types.is_integer_dtype(df[col]) or df[col].isna().any() or not np.isfinite(df[col]).all():
            raise RuntimeError("timestamp must be finite integer")
    if not (df["observation_ts"].eq(df["observation_time"]).all() and (df["observation_time"] <= df["entry_ts"]).all()):
        raise RuntimeError("observation/entry timestamp contract failed")
    causal = ((df["latest_source_ts_used"] <= df["observation_ts"]).all()
              and (df["latest_1s_bar_close_ts_used"] <= df["observation_ts"]).all()
              and (df["latest_1m_bar_close_ts_used"] <= df["observation_ts"]).all()
              and (df["entry_ts"] <= df["exit_ts"]).all())
    if not causal:
        raise RuntimeError("causal provenance/exit ordering violation")
    obs = pd.to_datetime(df["observation_ts"], unit="ns", utc=True)
    entry_ct = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.tz_convert("America/Chicago")
    in_rth = ((entry_ct.dt.hour > 8) | ((entry_ct.dt.hour == 8) & (entry_ct.dt.minute >= 30))) & (entry_ct.dt.hour < 15)
    if not obs.dt.year.eq(year).all() or not in_rth.all():
        raise RuntimeError("UTC year or short-RTH fill-time contract failed")


def load_year(year: int, manifest: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = INPUT / f"full_{year}.parquet"
    if not path.exists(): raise RuntimeError(f"missing input {path}")
    if sha256(path) != TRUSTED_INPUT_SHA256[year]: raise RuntimeError("trusted accepted-surface SHA256 mismatch")
    df = pd.read_parquet(path)
    required = {"regime_start_ns", "observation_time", "observation_ts", "entry_ts", "label_available", "entry_direction", "exit_reason", "net_pnl", "exit_ts", *PROVENANCE}
    needed = set(sum(manifest["feature_sets"].values(), [])) - {x for x in sum(manifest["feature_sets"].values(), []) if "__" in x}
    needed |= set(manifest["position_columns"])
    missing = (required | needed) - set(df.columns)
    if missing: raise RuntimeError(f"absent required features/schema fields: {sorted(missing)}")
    if len(df) != COUNTS[year] or df.duplicated(["regime_start_ns", "observation_time"]).any():
        raise RuntimeError("fixed count or unique-key contract failed")
    validate_temporal_population(df, year)
    if not np.isfinite(pd.to_numeric(df["net_pnl"], errors="coerce")).all(): raise RuntimeError("net_pnl must be finite")
    label_frame(df)
    return df, {"path": str(path), "sha256": sha256(path), "schema": {c: str(t) for c, t in df.dtypes.items()}, "count": len(df)}


def matrix(df: pd.DataFrame, features: list[str], positions: list[str]) -> np.ndarray:
    pieces: list[pd.DataFrame] = [df[[x for x in features if "__" not in x]].apply(pd.to_numeric, errors="coerce")]
    for col in positions:
        values = df[col].fillna("UNAVAILABLE").astype(str).str.upper()
        bad = ~values.isin(("ABOVE", "BELOW", "TOUCH", "UNAVAILABLE"))
        if bad.any(): raise RuntimeError(f"unknown non-null position token: {col}")
        pieces.append(pd.DataFrame({f"{col}__{v}": (values == v).astype("float32") for v in ("ABOVE", "BELOW", "TOUCH", "UNAVAILABLE")}, index=df.index))
    out = pd.concat(pieces, axis=1).reindex(columns=features)
    if list(out.columns) != features: raise RuntimeError("fixed feature order lost")
    return out.to_numpy(dtype=np.float32, copy=False)


def models() -> dict[str, Any]:
    return {
        "logistic": Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
            ("model", LogisticRegression(C=1, penalty="l2", max_iter=500, solver="lbfgs", random_state=42))]),
        "hist": Pipeline([("impute", SimpleImputer(strategy="median")), ("model", HistGradientBoostingClassifier(
            max_depth=3, max_iter=100, learning_rate=.05, l2_regularization=1, early_stopping=False, random_state=42))]),
    }


def score(model: Any, X: np.ndarray) -> np.ndarray:
    if set(model.classes_) != set(CLASSES): raise RuntimeError("model missing one or more required classes")
    p = model.predict_proba(X); by = {c: p[:, list(model.classes_).index(c)] for c in CLASSES}
    return by["winner"] - by["pre_alignment_stop"] - .25 * by["confirmation_timeout"] - .5 * by["post_alignment_stop"]


def economic(rows: pd.DataFrame) -> dict[str, float]:
    if rows.empty: return {"trades":0,"net":0.,"per_trade":0.,"gross_profit":0.,"gross_loss":0.,"pf":0.,"win_rate":0.,"avg_winner":0.,"avg_loser":0.,"dd":0.,"max_closed_trade_sequence_dd":0.,"prestop_rate":0.,"timeout_rate":0.,"poststop_rate":0.,"winner_rate":0.,"opposing_rate":0.,"oppflip_pnl":0.}
    ordered = rows.sort_values(["exit_ts", "regime_start_ns", "observation_time"], kind="stable"); pnl = ordered["net_pnl"].astype(float); gross_loss = float(pnl[pnl < 0].sum()); gains = float(pnl[pnl > 0].sum())
    curve = pd.concat([pd.Series([0.0]), pnl.reset_index(drop=True)]).cumsum(); dd = float((curve.cummax() - curve).max()); n = len(rows)
    out = {"trades": n, "net": float(pnl.sum()), "per_trade": float(pnl.mean()), "gross_profit": gains, "gross_loss": gross_loss, "pf": gains / -gross_loss if gross_loss else float("inf"), "win_rate": float((pnl > 0).mean()), "avg_winner": float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0., "avg_loser": float(pnl[pnl < 0].mean()) if (pnl < 0).any() else 0., "dd": dd, "max_closed_trade_sequence_dd": dd}
    for label, key in (("pre_alignment_stop", "prestop"), ("confirmation_timeout", "timeout"), ("post_alignment_stop", "poststop"), ("winner", "winner")):
        out[f"{key}_rate"] = float((ordered["_label"] == label).mean())
    out["opposing_rate"] = float((ordered["exit_reason"] == "original_opposing_flip_exit").mean()); out["oppflip_pnl"] = float(pnl[ordered["exit_reason"] == "original_opposing_flip_exit"].sum())
    return out


def derive_cutoff(scores: np.ndarray, band: float) -> float:
    return float("-inf") if band == 1 else float(np.quantile(scores, 1 - band, method="higher"))

def apply_cutoff(df: pd.DataFrame, scores: np.ndarray, cutoff: float) -> tuple[pd.DataFrame, int]:
    out = df.assign(_score=scores, _ordinal=np.arange(len(df))).loc[lambda x: x._score >= cutoff]; qualifying = len(out)
    out = out.sort_values(["regime_start_ns", "observation_time", "_ordinal"], kind="stable").drop_duplicates("regime_start_ns", keep="first")
    return out, qualifying


def checks(metrics: dict[str, float], base: dict[str, float]) -> int:
    return sum((metrics["per_trade"] > base["per_trade"], metrics["pf"] > base["pf"], metrics["dd"] < base["dd"],
                metrics["prestop_rate"] < base["prestop"], metrics["oppflip_pnl"] >= .9 * base["oppflip_pnl"]))


def final_decision(parity_ok: bool, chosen: dict[str, Any] | None, peer_checks: int | None, survival: dict[str, bool]) -> str:
    if not parity_ok: return "ENRICHED_RETRAIN_PARITY_FAIL"
    if chosen is None: return "ENRICHED_RETRAIN_REJECT"
    if chosen["feature_set"] == "F0" or peer_checks is None or chosen["checks"] < 2 or chosen["checks"] <= peer_checks: return "ENRICHED_RETRAIN_BASELINE_STILL_BEST"
    if not survival.get("winner_clipping_exact", False): return "ENRICHED_RETRAIN_CLIPS_WINNERS"
    if not all(survival.values()): return "ENRICHED_RETRAIN_OVERFITS_2025"
    if chosen["feature_set"] in {"F1", "F2", "F3"}: return "ENRICHED_RETRAIN_PROMISING"
    return "ENRICHED_RETRAIN_REJECT"


def diagnostics(model: Any, X: np.ndarray, y: pd.Series, scores: np.ndarray) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    p = model.predict_proba(X); classes = list(model.classes_); q = np.quantile(scores, [.05, .25, .5, .75, .95]); out: dict[str, Any] = {"logloss": float(log_loss(y, p, labels=classes)), "score_mean": float(np.mean(scores)), "score_std": float(np.std(scores)), "score_min": float(np.min(scores)), "score_max": float(np.max(scores)), "score_q05": float(q[0]), "score_q25": float(q[1]), "score_q50": float(q[2]), "score_q75": float(q[3]), "score_q95": float(q[4])}; calibration=[]
    for cls in ("pre_alignment_stop", "winner"):
        target = (y == cls).astype(int); prob = p[:, classes.index(cls)]
        out[f"auc_{cls}"] = float(roc_auc_score(target, prob)) if target.nunique() == 2 else None
    for cls in CLASSES:
        prob = p[:, classes.index(cls)]
        q = pd.qcut(pd.Series(prob), q=10, duplicates="drop")
        grouped = pd.DataFrame({"decile": q.astype(str), "p": prob, "y": (y == cls).astype(float)}).groupby("decile", observed=True)
        for decile, g in grouped: calibration.append({"class": cls, "decile": str(decile), "n": len(g), "mean_probability": float(g.p.mean()), "observed_rate": float(g.y.mean())})
    return out, calibration


def overlay_status(selected: pd.DataFrame, year: int) -> dict[str, Any]:
    return {"status":"NOT_APPLICABLE","reason":"fixed-807 schedule lacks baseline outcomes/PnL; keep/drop/move/add attribution would be incomplete and is non-promotional","favorable_claims_prohibited":True}


def code_hash() -> str: return sha256(Path(__file__))


def write_stage1_tables(inputs: dict[str, Any], frames: dict[int, pd.DataFrame], candidates: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    readiness = []
    for year, df in frames.items():
        readiness.append({"year": year, "rows": len(df), "classes": json.dumps(df["_label"].value_counts().to_dict(), sort_keys=True), "missing_cells": int(df.isna().sum().sum()), "input_sha256": inputs[str(year)]["sha256"]})
    pd.DataFrame(readiness).to_csv(WORK / "stage1_readiness.csv", index=False)
    pd.DataFrame(candidates).to_csv(WORK / "stage1_candidates.csv", index=False)


def schedule_breakdowns(rows: pd.DataFrame, meta: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if rows.empty:
        return ([{**meta,"month_ct":"NO_TRADES","trades":0,"net_pnl":0.}], [{**meta,"exit_reason":reason,"count":0,"pct":0.,"net_pnl":0.} for reason in ("original_opposing_flip_exit","preflip_policy_stop","confirmation_timeout_exit","original_stop_after_aligned_flip")])
    ct = pd.to_datetime(rows.exit_ts, unit="ns", utc=True).dt.tz_convert("America/Chicago").dt.to_period("M").astype(str)
    monthly = rows.assign(month_ct=ct).groupby("month_ct", observed=True).net_pnl.agg(["count", "sum"]).reset_index()
    exits = rows.groupby("exit_reason", observed=True).net_pnl.agg(["count", "sum"]).reset_index()
    return ([{**meta, "month_ct": r.month_ct, "trades": int(r.count), "net_pnl": float(r.sum)} for r in monthly.itertuples(index=False)],
            [{**meta, "exit_reason": r.exit_reason, "count": int(r.count), "pct": float(r.count / len(rows)), "net_pnl": float(r.sum)} for r in exits.itertuples(index=False)])


def readiness_rows(frames: dict[int, pd.DataFrame], manifest: dict[str, Any], inputs: dict[str, Any]) -> list[dict[str, Any]]:
    out=[]
    for year, df in frames.items():
        availability={c: float(df[c].notna().mean()) for c in manifest["position_columns"] if c in df}
        classes={c: {"count": int((df._label == c).sum()), "rate": float((df._label == c).mean())} for c in CLASSES}
        for family, feats in manifest["feature_sets"].items():
            raw=[x for x in feats if "__" not in x]; nan=float(df[raw].isna().mean().mean())
            info=inputs[str(year)]
            out.append({"year":year,"feature_set":family,"path":info["path"],"sha256":info["sha256"],"rows":len(df),"raw_feature_count":len(raw),"model_feature_count":len(feats),"nan_rate":nan,"class_distribution":json.dumps(classes,sort_keys=True),"availability":json.dumps(availability,sort_keys=True),"labels_preserved":True,"rows_preserved":True,"provenance_valid":True})
    return out


def write_stage1_rejection_report(diagnostic_leader: dict[str, Any]) -> None:
    decision = final_decision(True, None, None, {})
    report_path = HERE / "STUDY_REPORT.md"
    report_path.write_text(f"""# Enriched short-RTH retrain

## Executive summary

Decision: `{decision}`. No 2025 candidate passed the frozen gate, so the sealed 2026 holdout was not opened.

## Required questions

1. **Did enriched features improve over F0?** No deployable 2025 candidate cleared the gate.
2. **Did volume/delta add signal?** Not enough to clear the 2025 gate.
3. **Did price-level context add signal?** Not enough to clear the 2025 gate.
4. **Did the combined model improve 2025?** Not enough for selection.
5. **Did improvement survive sealed 2026?** Not evaluated; opening 2026 after rejection is prohibited.
6. **Were stops avoided without excessive winner clipping?** Not evaluated on the holdout.
7. **Promote to NT schedule validation?** No.
8. **Otherwise keep current W4 Policy A?** Yes.

Diagnostic-only 2025 leader: `{diagnostic_leader['schedule_id']}`. Research-only; not NT validation.
""", encoding="utf-8")
    artifacts = [{"path": f"results/{p.name}", "bytes": p.stat().st_size, "sha256": sha256(p)} for p in RESULTS.iterdir() if p.is_file() and p.name != "manifest.json"]
    for p in (report_path, HERE / "SPEC.md", HERE / "REPRODUCE.md", HERE / "baseline_2025.json", LOCAL_AUDIT):
        artifacts.append({"path": str(p.relative_to(HERE)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha256(p)})
    artifacts.append({"path": "results/manifest.json", "bytes": None, "sha256": None, "self_reference": "written last"})
    atomic_json(RESULTS / "manifest.json", {"decision": decision, "sealed_2026_opened": False, "artifacts": artifacts})


def stage1(args: argparse.Namespace) -> None:
    require_audits(); baseline_2025=load_baseline_2025(); manifest = manifests()
    WORK.mkdir(parents=True, exist_ok=True); RESULTS.mkdir(parents=True, exist_ok=True)
    # Deliberately enumerate only 2021--2025: this stage must never open 2026.
    frames: dict[int, pd.DataFrame] = {}; inputs: dict[str, Any] = {}
    for year in range(2021, 2026):
        frames[year], inputs[str(year)] = load_year(year, manifest); frames[year]["_label"] = label_frame(frames[year])
    train = pd.concat([frames[y] for y in range(2021, 2025)], ignore_index=True); val = frames[2025]
    manifest_path = RESULTS / "feature_manifest.json"; atomic_json(manifest_path, manifest)
    candidates = []
    for family, feats in manifest["feature_sets"].items():
        Xtr = matrix(train, feats, manifest["position_columns"]); Xv = matrix(val, feats, manifest["position_columns"])
        for model_name, model in models().items():
            model.fit(Xtr, train["_label"]); s = score(model, Xv)
            for band in BANDS:
                cutoff = derive_cutoff(s, band); selected, qualifying = apply_cutoff(val, s, cutoff); m = economic(selected); n = checks(m, baseline_2025); sid = f"{family}__{model_name}__rband{band:g}"
                candidates.append({"schedule_id": sid, "feature_set": family, "model": model_name, "band": band, "cutoff": cutoff,
                    "qualifying_rows": qualifying, "qualifying_fraction": qualifying / len(val), "schedule_fraction": len(selected) / val.regime_start_ns.nunique(), "ties_at_cutoff": int((s == cutoff).sum()), "checks": n, **m})
    ranked = sorted([x for x in candidates if x["checks"] >= 2], key=lambda x: (-x["checks"], -x["net"], -x["per_trade"], -x["pf"], x["dd"], x["schedule_id"]))
    chosen = ranked[0] if ranked else None
    diagnostic_leader = sorted(candidates, key=lambda x: (-x["checks"], -x["net"], -x["per_trade"], -x["pf"], x["dd"], x["schedule_id"]))[0]
    decision = "SELECTION_FROZEN" if chosen else final_decision(True, None, None, {})
    overlay_2025: dict[str, Any] = {"status": "NOT_APPLICABLE", "reason": "no selected schedule"}
    if chosen:
        feats = manifest["feature_sets"][chosen["feature_set"]]
        selected_model = models()[chosen["model"]]
        selected_model.fit(matrix(train, feats, manifest["position_columns"]), train["_label"])
        selected_rows, _ = apply_cutoff(val, score(selected_model, matrix(val, feats, manifest["position_columns"])), chosen["cutoff"])
        overlay_2025 = overlay_status(selected_rows, 2025)
        selected_rows.to_parquet(RESULTS / "selected_model_trade_schedule.parquet", index=False)
    pd.DataFrame(candidates).to_csv(RESULTS / "stage1_candidates.csv", index=False)
    write_stage1_tables(inputs, frames, candidates, manifest)
    result = {"decision": decision, "selection": chosen, "diagnostic_leader": diagnostic_leader, "baseline": baseline_2025, "candidates": len(candidates), "candidate_rows": candidates, "overlay_2025": overlay_2025}
    result_hash = canonical_hash(result)
    seal = {"stage": "select_2025", "result": result, "stage1_result_sha256": result_hash, "inputs": inputs,
            "code_sha256": code_hash(), "baseline_2025_sha256": BASELINE_2025_SHA256, "baseline_2025": baseline_2025, "sealed_2026_sha256": SEALED_2026_SHA256, "feature_manifest_sha256": canonical_hash(manifest), "registry_sha256": sha256(REGISTRY_SOURCE), "f0_sha256": sha256(F0_SOURCE), "configs": {"bands": BANDS, "classes": CLASSES}}
    atomic_json(WORK / "selection_seal.json", seal); atomic_json(RESULTS / "stage1_report.json", result)
    if chosen is None:
        write_stage1_rejection_report(diagnostic_leader)


def validate_recovery_candidates(candidates_df: pd.DataFrame, baseline_2025: dict[str, float]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
    required = {"schedule_id", "feature_set", "model", "band", "cutoff", "checks", "trades", "net", "per_trade", "pf", "dd", "prestop_rate", "oppflip_pnl"}
    if required - set(candidates_df): raise RuntimeError("stage1 recovery candidate schema failed")
    expected_ids = {f"F{f}__{m}__rband{b:g}" for f in range(4) for m in ("logistic", "hist") for b in BANDS}
    if len(candidates_df) != 48 or set(candidates_df["schedule_id"]) != expected_ids or candidates_df["schedule_id"].duplicated().any():
        raise RuntimeError("stage1 recovery candidate parity failed")
    candidates = candidates_df.to_dict("records")
    for row in candidates:
        expected_id = f"{row['feature_set']}__{row['model']}__rband{float(row['band']):g}"
        if row["schedule_id"] != expected_id or row["feature_set"] not in {"F0", "F1", "F2", "F3"} or row["model"] not in {"logistic", "hist"} or float(row["band"]) not in BANDS:
            raise RuntimeError("stage1 recovery row identity mismatch")
        numeric = [row[k] for k in required - {"schedule_id", "feature_set", "model", "cutoff"}]
        if any(not np.isfinite(float(v)) for v in numeric): raise RuntimeError("stage1 recovery non-finite metric")
        cutoff = float(row["cutoff"])
        if (float(row["band"]) == 1.0) != np.isneginf(cutoff): raise RuntimeError("stage1 recovery cutoff contract mismatch")
        if int(row["checks"]) != checks(row, baseline_2025): raise RuntimeError("stage1 recovery metric/check parity failed")
    ranked = sorted([x for x in candidates if int(x["checks"]) >= 2], key=lambda x: (-x["checks"], -x["net"], -x["per_trade"], -x["pf"], x["dd"], x["schedule_id"]))
    chosen = ranked[0] if ranked else None
    diagnostic_leader = sorted(candidates, key=lambda x: (-x["checks"], -x["net"], -x["per_trade"], -x["pf"], x["dd"], x["schedule_id"]))[0]
    return candidates, chosen, diagnostic_leader


def validate_recovery_schedule(selected: pd.DataFrame, chosen: dict[str, Any]) -> None:
    required = {"regime_start_ns", "observation_time", "exit_ts", "net_pnl", "exit_reason", "_label", "_score"}
    if required - set(selected) or selected["regime_start_ns"].duplicated().any(): raise RuntimeError("stage1 recovery selected-schedule schema/key failed")
    if not (selected["_score"] >= float(chosen["cutoff"])).all(): raise RuntimeError("stage1 recovery selected cutoff membership failed")
    actual = economic(selected)
    for key in ("trades", "net", "per_trade", "gross_profit", "gross_loss", "pf", "win_rate", "avg_winner", "avg_loser", "dd", "prestop_rate", "timeout_rate", "poststop_rate", "winner_rate", "opposing_rate", "oppflip_pnl"):
        if not np.isclose(float(actual[key]), float(chosen[key]), rtol=0, atol=1e-6): raise RuntimeError(f"stage1 recovery selected metric mismatch: {key}")


def finalize_2025(args: argparse.Namespace) -> None:
    """Seal a completed stage-1 cache after a write-only failure; never refit or open 2026."""
    require_audits(); baseline_2025 = load_baseline_2025(); manifest = manifests()
    candidates_path = RESULTS / "stage1_candidates.csv"
    schedule_path = RESULTS / "selected_model_trade_schedule.parquet"
    readiness_path = WORK / "stage1_readiness.csv"
    feature_path = RESULTS / "feature_manifest.json"
    if not candidates_path.exists() or not schedule_path.exists() or not readiness_path.exists() or not feature_path.exists():
        raise RuntimeError("stage1 recovery cache is incomplete")
    cache_paths = {"candidates": candidates_path, "selected_schedule": schedule_path, "feature_manifest": feature_path, "readiness": readiness_path}
    if any(sha256(path) != RECOVERY_CACHE_SHA256[name] for name, path in cache_paths.items()): raise RuntimeError("stage1 recovery trusted cache hash mismatch")
    candidates_df = pd.read_csv(candidates_path)
    candidates, chosen, diagnostic_leader = validate_recovery_candidates(candidates_df, baseline_2025)
    if chosen is not None:
        selected = pd.read_parquet(schedule_path)
        validate_recovery_schedule(selected, chosen)
    feature_copy = json.loads(feature_path.read_text(encoding="utf-8"))
    if canonical_hash(feature_copy) != canonical_hash(manifest): raise RuntimeError("stage1 recovery feature-manifest mismatch")
    readiness = pd.read_csv(readiness_path)
    if set(readiness["year"].astype(int)) != set(range(2021, 2026)): raise RuntimeError("stage1 recovery readiness years mismatch")
    inputs = {}
    for year in range(2021, 2026):
        path = INPUT / f"full_{year}.parquet"; digest = sha256(path)
        if digest != TRUSTED_INPUT_SHA256[year]: raise RuntimeError("stage1 recovery input hash mismatch")
        cached = readiness.loc[readiness["year"] == year].iloc[0]
        if int(cached["rows"]) != COUNTS[year] or str(cached["input_sha256"]) != digest: raise RuntimeError("stage1 recovery readiness mismatch")
        inputs[str(year)] = {"path": str(path), "sha256": digest, "count": COUNTS[year], "recovered_after_write_only_failure": True}
    decision = "SELECTION_FROZEN" if chosen else final_decision(True, None, None, {})
    result = {"decision": decision, "selection": chosen, "diagnostic_leader": diagnostic_leader, "baseline": baseline_2025, "candidates": 48, "candidate_rows": candidates, "overlay_2025": overlay_status(pd.read_parquet(schedule_path), 2025) if chosen else {"status": "NOT_APPLICABLE", "reason": "no selected schedule"}, "recovery": "validated stage1 cache after non-causal serialization failure"}
    seal = {"stage": "select_2025", "result": result, "stage1_result_sha256": canonical_hash(result), "inputs": inputs,
            "code_sha256": code_hash(), "baseline_2025_sha256": BASELINE_2025_SHA256, "baseline_2025": baseline_2025, "sealed_2026_sha256": SEALED_2026_SHA256, "recovery_cache_sha256": RECOVERY_CACHE_SHA256, "feature_manifest_sha256": canonical_hash(manifest), "registry_sha256": sha256(REGISTRY_SOURCE), "f0_sha256": sha256(F0_SOURCE), "configs": {"bands": BANDS, "classes": CLASSES}}
    atomic_json(WORK / "selection_seal.json", seal); atomic_json(RESULTS / "stage1_report.json", result)
    if chosen is None: write_stage1_rejection_report(diagnostic_leader)


def stage2(args: argparse.Namespace) -> None:
    require_audits(); seal_path = WORK / "selection_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    allowed_stage1_decisions = {"SELECTION_FROZEN", "ENRICHED_RETRAIN_REJECT"}
    if seal.get("stage") != "select_2025" or seal.get("result", {}).get("decision") not in allowed_stage1_decisions or seal["code_sha256"] != code_hash() or seal["baseline_2025_sha256"] != BASELINE_2025_SHA256 or sha256(BASELINE_2025_FILE) != BASELINE_2025_SHA256 or seal.get("sealed_2026_sha256") != SEALED_2026_SHA256 or seal["registry_sha256"] != sha256(REGISTRY_SOURCE) or seal["f0_sha256"] != sha256(F0_SOURCE):
        raise RuntimeError("selection seal code/baseline hash mismatch")
    if seal["stage1_result_sha256"] != canonical_hash(seal["result"]): raise RuntimeError("selection seal result hash mismatch")
    if seal["result"]["decision"] == "ENRICHED_RETRAIN_REJECT":
        if seal["result"].get("selection") is not None: raise RuntimeError("rejected seal cannot contain a selection")
        return
    if seal["result"]["selection"] not in seal["result"]["candidate_rows"]: raise RuntimeError("sealed selection is not a candidate")
    for year in range(2021, 2026):
        path = INPUT / f"full_{year}.parquet"
        if seal["inputs"][str(year)]["sha256"] != sha256(path):
            raise RuntimeError("selection seal input hash mismatch")
    manifest = manifests()
    if seal["feature_manifest_sha256"] != canonical_hash(manifest):
        raise RuntimeError("selection seal feature manifest mismatch")
    sealed_path = HERE / "sealed_2026.py"
    if sha256(sealed_path) != SEALED_2026_SHA256:
        decision = final_decision(False, seal["result"].get("selection"), None, {})
        atomic_json(RESULTS / "stage2_report.json", {"decision": decision, "parity_error": "sealed stage-2 dependency hash mismatch"})
        raise RuntimeError("sealed stage-2 dependency hash mismatch")
    spec=importlib.util.spec_from_file_location("_sealed_2026", sealed_path); sealed=importlib.util.module_from_spec(spec); spec.loader.exec_module(sealed)
    try:
        baseline_2026=sealed.load_baseline()
    except sealed.ParityError as exc:
        decision = final_decision(False, seal["result"].get("selection"), None, {})
        atomic_json(RESULTS / "stage2_report.json", {"decision": decision, "parity_error": str(exc)})
        raise
    # This is the first point at which evaluate_2026 is allowed to open the 2026 surface.
    df, info = load_year(2026, manifest); df["_label"] = label_frame(df)
    chosen = seal["result"]["selection"]
    if not chosen: raise RuntimeError("stage1 had no selected schedule; stage2 cannot decide")
    # Train only the selected model for final economics; all eight score 2026 diagnostically.
    frames = [load_year(y, manifest)[0] for y in range(2021, 2025)]
    for f in frames: f["_label"] = label_frame(f)
    train = pd.concat(frames, ignore_index=True); diagnostic: dict[str, Any] = {}
    selected_model = None; econ_rows=[]; retention_rows=[]; monthly_rows=[]; exit_rows=[]; calibration_rows=[]; top_features=[]
    val, _ = load_year(2025, manifest); val["_label"] = label_frame(val)
    for family, feats in manifest["feature_sets"].items():
        Xtr = matrix(train, feats, manifest["position_columns"]); X = matrix(df, feats, manifest["position_columns"])
        Xv = matrix(val, feats, manifest["position_columns"])
        for name, model in models().items():
            model.fit(Xtr, train["_label"]); s = score(model, X); sv = score(model, Xv); st = score(model, Xtr)
            tr_diag, tr_cal = diagnostics(model, Xtr, train["_label"], st); v_diag, v_cal = diagnostics(model, Xv, val["_label"], sv); o_diag, o_cal = diagnostics(model, X, df["_label"], s)
            diagnostic[f"{family}__{name}"] = {"train": tr_diag, "2025": v_diag, "2026": o_diag, "score_drift_2026_minus_2025": float(np.mean(s) - np.mean(sv))}
            for split, rows in (("train", tr_cal), ("2025", v_cal), ("2026", o_cal)):
                calibration_rows.extend({"feature_set": family, "model": name, "split": split, **row} for row in rows)
            if name == "logistic":
                coef=np.abs(model.named_steps["model"].coef_).mean(axis=0); order=np.argsort(coef)[::-1][:50]
                top_features.extend({"feature_set":family,"model":name,"rank":int(i+1),"feature":feats[j],"mean_abs_coefficient":float(coef[j])} for i,j in enumerate(order))
            else: top_features.append({"feature_set":family,"model":name,"rank":None,"feature":"UNAVAILABLE","mean_abs_coefficient":None,"reason":"HistGradientBoosting has no frozen built-in feature importance"})
            for candidate in seal["result"]["candidate_rows"]:
                if candidate["feature_set"] == family and candidate["model"] == name:
                    for split, source, scores in (("2025", val, sv), ("2026", df, s)):
                        candidate_rows, qualifying = apply_cutoff(source, scores, float(candidate["cutoff"])); selected_flag=candidate["schedule_id"] == chosen["schedule_id"]
                        meta={"schedule_id":candidate["schedule_id"],"feature_set":family,"model":name,"band":candidate["band"],"cutoff":candidate["cutoff"],"split":split,"selected":selected_flag,"layer":"layer2_frozen_cutoff"}
                        econ_rows.append({**meta,**economic(candidate_rows)})
                        retention_rows.append({**meta,"qualifying_rows":qualifying,"qualifying_fraction":qualifying/len(source),"schedule_trades":len(candidate_rows),"schedule_fraction":len(candidate_rows)/source.regime_start_ns.nunique()})
                        mo, ex=schedule_breakdowns(candidate_rows,meta); monthly_rows.extend(mo); exit_rows.extend(ex)
            if family == chosen["feature_set"] and name == chosen["model"]: selected_model = (s, model)
    assert selected_model is not None
    selected, _ = apply_cutoff(df, selected_model[0], float(chosen["cutoff"])); m = economic(selected)
    survival = {"net_positive": m["net"] > 0, "pertrade_90pct": m["per_trade"] >= .9 * baseline_2026["per_trade"], "pf_90pct": m["pf"] >= .9 * baseline_2026["pf"]}
    dt = pd.to_datetime(selected["exit_ts"], unit="ns", utc=True, errors="raise").dt.tz_convert("America/Chicago")
    monthly = selected.assign(_month=dt.dt.to_period("M")).groupby("_month", observed=True)["net_pnl"].sum()
    positive = monthly[monthly > 0]
    survival["positive_month_concentration"] = bool(positive.max() <= .75 * positive.sum()) if len(positive) else True
    overlay = overlay_status(selected, 2026)
    peers = [x for x in seal["result"].get("candidate_rows", []) if x["feature_set"] == "F0" and x["model"] == chosen["model"] and x["band"] == chosen["band"]]
    peer_checks = peers[0]["checks"] if peers else None
    try:
        base_2026 = sealed.load_trades()
    except sealed.ParityError as exc:
        decision = final_decision(False, chosen, peer_checks, {})
        atomic_json(RESULTS / "stage2_report.json", {"decision": decision, "parity_error": str(exc)})
        raise
    attribution, attribution_rows, _ = exact_attribution(selected, base_2026)
    base_monthly = base_2026.assign(_month=pd.to_datetime(base_2026.exit_ts, unit="ns", utc=True).dt.tz_convert("America/Chicago").dt.to_period("M")).groupby("_month").net_pnl.sum()
    survival["stop_savings_gate"] = attribution["stop_savings_exact"] >= 0
    survival["winner_clipping_exact"] = max(0., attribution["clipped_winners_exact"]) <= max(0., attribution["stop_savings_exact"])
    survival["monthly_worst_25pct"] = float(monthly.min()) >= 1.25 * float(base_monthly.min())
    survival["monthly_positive_share"] = ((monthly > 0).mean()) >= ((base_monthly > 0).mean() - .10)
    survival["monthly_abs_share"] = float(abs(monthly).max()) <= .75 * float(abs(monthly).sum())
    parity_ok = True
    decision = final_decision(parity_ok, chosen, peer_checks, survival)
    report = {"sealed_selection": chosen, "input_2026": info, "metrics": m, "survival": survival,
              "diagnostics": diagnostic, "monthly_ct": {str(k): float(v) for k, v in monthly.items()}, "overlay": overlay, "matching_f0_checks": peer_checks, "exact_baseline_attribution": attribution, "decision": decision}
    atomic_json(RESULTS / "stage2_report.json", report)
    selected.to_parquet(RESULTS / "selected_model_oos_2026_trades.parquet", index=False)
    diag_rows=[{"feature_set":k.split("__")[0],"model":k.split("__")[1],"split":split,**vals} for k, block in diagnostic.items() for split, vals in block.items() if split in ("train","2025","2026")]
    pd.DataFrame(diag_rows).to_csv(RESULTS / "model_diagnostics.csv", index=False)
    pd.DataFrame(econ_rows).to_csv(RESULTS / "economic_results.csv", index=False)
    pd.DataFrame(retention_rows).to_csv(RESULTS / "retention_band_results.csv", index=False)
    pd.DataFrame(monthly_rows).to_csv(RESULTS / "monthly_results.csv", index=False)
    pd.DataFrame(exit_rows).to_csv(RESULTS / "exit_reason_attribution.csv", index=False)
    all_frames={**{y:f for y,f in zip(range(2021,2025),frames)},2025:val,2026:df}
    pd.DataFrame(readiness_rows(all_frames,manifest,{**seal["inputs"],"2026":info})).to_csv(RESULTS / "data_readiness.csv", index=False)
    pd.DataFrame(top_features).to_csv(RESULTS / "top_features.csv", index=False)
    econ_by={(r["feature_set"],r["model"],r["band"],r["split"]):r for r in econ_rows}; contribution=[]
    for row in econ_rows:
        if row["feature_set"] == "F0": continue
        base=econ_by[("F0",row["model"],row["band"],row["split"])]
        contribution.append({"feature_set":row["feature_set"],"added_family":row["feature_set"],"model":row["model"],"band":row["band"],"split":row["split"],"selected":row["selected"],"net_pnl_delta":row["net"]-base["net"],"per_trade_delta":row["per_trade"]-base["per_trade"],"pf_delta":row["pf"]-base["pf"],"dd_delta":row["dd"]-base["dd"],"prestop_delta":row["prestop_rate"]-base["prestop_rate"],"oppflip_pnl_delta":row["oppflip_pnl"]-base["oppflip_pnl"],"improvement_checks_2025":sum((row["per_trade"]>base["per_trade"],row["pf"]>base["pf"],row["dd"]<base["dd"],row["prestop_rate"]<base["prestop_rate"],row["oppflip_pnl"]>=.9*base["oppflip_pnl"])) if row["split"]=="2025" else None})
    contribution_df = pd.DataFrame(contribution)
    contribution_df.to_csv(RESULTS / "feature_family_contribution.csv", index=False)
    pd.DataFrame(calibration_rows).to_csv(RESULTS / "calibration_deciles.csv", index=False)
    selected_2025 = next(r for r in econ_rows if r["schedule_id"] == chosen["schedule_id"] and r["split"] == "2025")
    selected_2026 = next(r for r in econ_rows if r["schedule_id"] == chosen["schedule_id"] and r["split"] == "2026")
    selected_contrib = contribution_df.loc[contribution_df["selected"]] if len(contribution_df) else contribution_df
    report_text = f"""# Enriched short-RTH retrain

## Executive summary

Decision: `{decision}`. Selected schedule: `{chosen['schedule_id']}`. This is a 1-second-OHLC research analysis of accepted, precomputed NT-derived Policy-A labels; it is not NT-native executable validation.

## Selected economics

| Split | Trades | Net PnL | PnL/trade | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| 2025 selection | {selected_2025['trades']} | {selected_2025['net']:.2f} | {selected_2025['per_trade']:.2f} | {selected_2025['pf']:.3f} | {selected_2025['dd']:.2f} |
| 2026 sealed | {selected_2026['trades']} | {selected_2026['net']:.2f} | {selected_2026['per_trade']:.2f} | {selected_2026['pf']:.3f} | {selected_2026['dd']:.2f} |

Baselines: A = 872 trades / $22,250 / $25.52 per trade / PF 1.129 / DD $18,686; B = 807 / $27,013 / $33.47 / PF 1.174 / DD $14,331; C NT benchmark = 807 / $23,270 / $28.84 / PF 1.149 / DD $15,000; D prior retrain selected GBT 35% and failed 2026 at -$10,970.

## Required questions

1. **Did enriched features improve over F0?** The selected family is `{chosen['feature_set']}`; matching-family deltas are in `results/feature_family_contribution.csv` ({len(selected_contrib)} selected comparison rows).
2. **Did volume/delta add signal?** See the frozen F1 and F3 versus F0 rows; no conclusion is based on 2026 selection.
3. **Did price-level context add signal?** See the frozen F2 and F3 versus F0 rows.
4. **Did the combined model improve 2025?** F3's 2025 improvement-check counts are reported in the contribution table; the chosen schedule passed {chosen['checks']} Baseline-A checks.
5. **Did improvement survive sealed 2026?** `{all(survival.values())}`; individual gates: `{json.dumps(survival, sort_keys=True)}`.
6. **Were stops avoided without excessive winner clipping?** Exact regime-key attribution: `{json.dumps(attribution, sort_keys=True)}`.
7. **Promote to NT schedule validation?** `{decision == 'ENRICHED_RETRAIN_PROMISING'}`.
8. **Otherwise keep current W4 Policy A?** `{decision != 'ENRICHED_RETRAIN_PROMISING'}`.

## Layer 3 and limitations

Fixed-807 overlay: `{overlay.get('status')}` — {overlay.get('reason', overlay.get('note', ''))}. The score-independent Layer-2 population is not identical to Baseline A, so only the regime-key matched Baseline-A attribution is used for promotion gates.

## Audit

Execution requires the latest independent audit summary to report zero CRITICAL and zero WARNING.
"""
    (HERE / "STUDY_REPORT.md").write_text(report_text, encoding="utf-8")
    artifacts = [{"path": f"results/{p.name}", "bytes": p.stat().st_size, "sha256": sha256(p)} for p in RESULTS.iterdir() if p.is_file() and p.name != "manifest.json"]
    for p in (HERE / "STUDY_REPORT.md", HERE / "SPEC.md", HERE / "REPRODUCE.md", HERE / "baseline_2025.json", HERE / "sealed_2026.py", LOCAL_AUDIT):
        artifacts.append({"path": str(p.relative_to(HERE)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha256(p)})
    artifacts.append({"path": "manifest.json", "bytes": None, "sha256": None, "self_reference": "written last"})
    atomic_json(RESULTS / "manifest.json", {"stage1_seal_sha256": sha256(seal_path), "selected": chosen, "inputs": {"2026": info}, "decision": decision, "artifacts": artifacts})


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("stage", choices=("select_2025", "finalize_2025", "evaluate_2026"));
    args = p.parse_args()
    if args.stage == "select_2025": stage1(args)
    elif args.stage == "finalize_2025": finalize_2025(args)
    else: stage2(args)


if __name__ == "__main__": main()
