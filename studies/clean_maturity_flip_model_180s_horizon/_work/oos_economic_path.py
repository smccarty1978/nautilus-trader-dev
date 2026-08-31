"""2024 OOS economic forward-path diagnostics at frozen first-crossing populations.

Descriptive only -- no rule is optimized on 2024. Mirrors _work/diag_economic_path.py
(governed engine research_workflow.forward_outcomes.compute_forward_outcomes; entry =
close of last 1s bar ts_init<=T; ATR = Wilder ATR(14) on completed 1m bars; forward
path on 1s bars). Frozen 180s native boosters vs previously-observed frozen 300s
parent benchmark.

Forward bars are admitted with ts_init strictly before 2025-01-01T00:00:00Z: all of
2024, zero 2025 bars. A 600s window from the last 2024 RTH bar completes well inside
2024.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, joblib
import lightgbm as lgb
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
from research_workflow.forward_outcomes import (
    compute_forward_outcomes, ForwardOutcomeSpec, ProposedEntry, Direction,
    ReferencePrice, OrderedBarrierSpec,
)

S180 = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
SPAR = ROOT / "studies" / "clean_maturity_flip_model_rolling_productivity"
CAT = ROOT / "data" / "catalog" / "NQ_v0_2020_2026" / "data" / "bar"
P1S = CAT / "NQ.XCME-1-SECOND-LAST-EXTERNAL"
P1M = CAT / "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
NS = 1_000_000_000
JOIN = ["observation_ts", "regime_start_ns", "checkpoint_index"]
ARM_C = ["arrival_velocity", "arrival_acceleration", "ema_slope",
         "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
         "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
         "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
         "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"]
LO = int(pd.Timestamp("2023-06-01", tz="UTC").value)   # ample 1m ATR warmup before 2024
HI = int(pd.Timestamp("2025-01-01", tz="UTC").value)   # strict: 2024 only, no 2025 bars

AGG = json.loads((S180 / "artifacts" / "train_experiment_freeze.json").read_text())
PAR_FZ = json.loads((SPAR / "artifacts" / "train_experiment_freeze_repaired.json").read_text())


def _load_bars(pdir):
    f = next(pdir.glob("*.parquet"))
    d = pq.read_table(f, columns=["high", "low", "close", "ts_event", "ts_init"]).to_pandas()
    for col in ("high", "low", "close"):
        d[col] = np.frombuffer(b"".join(d[col].values), dtype="<i8").astype(np.float64) / 1e9
    d["ts_event"] = d["ts_event"].astype(np.int64)
    d["ts_init"] = d["ts_init"].astype(np.int64)
    d = d[(d.ts_init >= LO) & (d.ts_init < HI)].sort_values("ts_init").reset_index(drop=True)
    return d


print("loading 1s bars...", flush=True); SEC = _load_bars(P1S); print(f"  {len(SEC):,}", flush=True)
print("loading 1m bars...", flush=True); MIN = _load_bars(P1M); print(f"  {len(MIN):,}", flush=True)
SEC_TI, SEC_TE = SEC.ts_init.values, SEC.ts_event.values
MIN_TI, MIN_H, MIN_L, MIN_C = MIN.ts_init.values, MIN.high.values, MIN.low.values, MIN.close.values


def _wilder_atr_at(T, period=14, warm=400):
    j = np.searchsorted(MIN_TI, T, side="right")
    if j < period + 5:
        return None
    i0 = max(0, j - warm)
    h, l, c = MIN_H[i0:j], MIN_L[i0:j], MIN_C[i0:j]
    tr = np.empty(len(h)); tr[0] = h[0] - l[0]; pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    if len(tr) < period:
        return None
    atr = tr[:period].mean()
    for x in tr[period:]:
        atr = (atr * (period - 1) + x) / period
    return float(atr)


SPEC = ForwardOutcomeSpec(
    spec_id="oos2024_econ_path", horizons_seconds=(180, 300), max_tracking_seconds=600,
    excursion_units=("points", "atr"), reference_price=ReferencePrice.DECISION_CLOSE,
    diagnostic_levels_atr=(1.0, 2.0, 3.0),
    ordered_barriers=(OrderedBarrierSpec(barrier_id="one_to_one", favorable_atr=1.0,
                                         adverse_atr=1.0, horizon_seconds=300),),
)


def build_and_compute(fc, direction, sid, fsha):
    recs = []
    for _, r in fc.iterrows():
        T = int(r["observation_ts"])
        si = np.searchsorted(SEC_TI, T, side="right")
        if si < 20:
            continue
        entry_price = float(SEC.close.values[si - 1])
        atr = _wilder_atr_at(T)
        if not atr or atr <= 0:
            continue
        fs = np.searchsorted(SEC_TE, T, side="right")
        fe = np.searchsorted(SEC_TE, T + 620 * NS, side="right")
        if fe - fs < 5:
            continue
        bars = list(zip(SEC_TE[fs:fe].tolist(), SEC_TI[fs:fe].tolist(),
                        SEC.high.values[fs:fe].tolist(), SEC.low.values[fs:fe].tolist(),
                        SEC.close.values[fs:fe].tolist()))
        e = ProposedEntry(
            study_id=sid, source_period="oos", candidate_key=str(int(r["regime_start_ns"])),
            decision_ts=T, entry_ts=T,
            direction=Direction("LONG") if direction == "LONG" else Direction("SHORT"),
            entry_price=entry_price, reference_price=ReferencePrice.DECISION_CLOSE,
            authorization_sha256="oos", source_freeze_sha256=fsha, entry_atr=atr,
        )
        out = compute_forward_outcomes([e], bars, SPEC)
        if out:
            rr = out[0]
            rr["_ttf"] = float(r["time_to_flip_seconds"]) if pd.notna(r["time_to_flip_seconds"]) else None
            rr["_flipped"] = 1 if pd.notna(r["time_to_flip_seconds"]) else 0
            recs.append(rr)
    return recs


def summarize(recs):
    if not recs:
        return {"n": 0}
    df = pd.DataFrame(recs)
    def num(n): return pd.to_numeric(df[n], errors="coerce") if n in df.columns else pd.Series([np.nan] * len(df))
    def mean(n):
        v = num(n); return float(v.mean()) if v.notna().any() else None
    def med(n):
        v = num(n); return float(v.median()) if v.notna().any() else None
    s = {"n": len(df), "n_flipped": int(num("_flipped").fillna(0).sum()), "median_ttf_s": med("_ttf")}
    for h in (180, 300):
        s[f"mfe_atr_{h}s_mean"] = mean(f"mfe_{h}s_atr"); s[f"mfe_atr_{h}s_median"] = med(f"mfe_{h}s_atr")
        s[f"mae_atr_{h}s_mean"] = mean(f"mae_{h}s_atr"); s[f"mae_atr_{h}s_median"] = med(f"mae_{h}s_atr")
        s[f"return_atr_{h}s_mean"] = mean(f"return_{h}s_atr")
    s["eventual_max_mfe_atr_mean"] = mean("max_mfe_atr"); s["eventual_max_mfe_atr_median"] = med("max_mfe_atr")
    s["eventual_max_mae_atr_mean"] = mean("max_mae_atr"); s["eventual_max_mae_atr_median"] = med("max_mae_atr")
    s["mfe_mae_ratio_180s_median"] = med("mfe_mae_ratio_180s")
    s["mfe_mae_ratio_300s_median"] = med("mfe_mae_ratio_300s")
    mm = num("max_mfe_atr")
    for k in (1, 2, 3):
        s[f"p_mfe_ge_{k}_atr"] = float((mm >= k).mean()) if mm.notna().any() else None
    ob = num("ordered_one_to_one_binary_label")
    s["one_to_one_resolved_n"] = int(ob.notna().sum())
    s["one_to_one_success_rate"] = float(ob.mean()) if ob.notna().any() else None
    fb = num("favorable_before_adverse_1atr")
    s["favorable_before_adverse_1atr_rate"] = float(fb.mean()) if fb.notna().any() else None
    return s


def score_180s(d, direction):
    mid = {r["model_role"]: r["model_id"] for r in AGG["model_artifacts"]}[f"{direction}_C"]
    bst = lgb.Booster(model_file=str(S180 / "artifacts" / "models" / f"{mid}.booster.txt"))
    return bst.predict(d[ARM_C].to_numpy(float)), AGG["freeze_sha256"]


def score_parent(d, direction):
    rec = joblib.load(SPAR / "artifacts" / "train_fitted_models.joblib")[f"{direction}_C"]
    return rec["estimator"].predict_proba(d[rec["provenance"]["ordered_features"]])[:, 1], "parent_repaired"


def run_cell(panel_c, panel_o, direction, thr_key):
    c = pd.read_parquet(panel_c); o = pd.read_parquet(panel_o)
    df = c.merge(o[JOIN + ["regime_direction", "target_flip_within_horizon", "disposition", "time_to_flip_seconds"]],
                 on=JOIN, how="inner")
    df = df[df.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    df = df[pd.to_datetime(df.observation_ts, unit="ns", utc=True).dt.year == 2024]
    d = df[df.regime_direction == (-1 if direction == "LONG" else 1)].reset_index(drop=True)
    is180 = "180s_horizon" in str(panel_c)
    if is180:
        s, fsha = score_180s(d, direction)
        thr = AGG["thresholds"][f"{direction}_C"][thr_key]["threshold"]
        sid = S180.name
    else:
        s, fsha = score_parent(d, direction)
        thr = PAR_FZ["thresholds"][f"{direction}_C"][thr_key]
        sid = SPAR.name
    dd = d.assign(score=s).sort_values(JOIN)
    fc = dd[dd.score >= thr].groupby("regime_start_ns", as_index=False).first()
    return summarize(build_and_compute(fc, direction, sid, fsha)), int(len(fc)), float(thr)


def main():
    outp = S180 / "artifacts" / "oos_2024_economic_path.json"
    result = json.loads(outp.read_text()) if outp.exists() else {
        "method_note": "post-hoc Wilder ATR(14) on 1m bars; points exact, ATR diagnostic; descriptive only",
        "population": "2024 first-crossing per regime at frozen TRAIN threshold; forward path on 1s bars; no 2025 bars",
    }
    p180 = (S180 / "artifacts" / "oos_candidates_merged.parquet", S180 / "artifacts" / "oos_observations_merged.parquet")
    ppar = (SPAR / "artifacts" / "oos2024_raw_candidates_reproduced.parquet",
            SPAR / "artifacts" / "oos2024_raw_observations_reproduced.parquet")
    for thr_key in ("p90", "p95"):
        result.setdefault(thr_key, {})
        for direction in ("LONG", "SHORT"):
            cell = result[thr_key].setdefault(direction, {})
            for tag, panel in (("180s", p180), ("300s", ppar)):
                if f"summary_{tag}" in cell:
                    print("skip", thr_key, direction, tag, flush=True); continue
                s, n, t = run_cell(panel[0], panel[1], direction, thr_key)
                cell[f"summary_{tag}"], cell[f"n_first_crossings_{tag}"], cell[f"threshold_{tag}"] = s, n, t
                outp.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
                print("done", thr_key, direction, tag, "n", n, flush=True)
    print("WROTE", outp.name, flush=True)


if __name__ == "__main__":
    main()
