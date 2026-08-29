"""TRAIN-only economic forward-path diagnostics at frozen first-crossing populations.

Governed metric engine: research_workflow.forward_outcomes.compute_forward_outcomes.
Bars read directly from the catalog parquet (fast path; the NT ParquetDataCatalog Bar-decode
loop is ~100x slower and this is a post-hoc _work diagnostic, not study collector code).

Entry price : close of the last 1s bar with ts_init <= T   (DECISION_CLOSE).
Entry ATR   : Wilder ATR(14) on completed 1m bars (ts_init <= T) -- matches
              collectors/collector_v2/regime_engine.py (Wilder ATR(14), 1m, SMA-seeded),
              the ATR the regime features are normalized against. Warmed from >=8h before T
              so the warmup-anchor difference has long converged. Points-denominated
              metrics are exact; ATR-denominated metrics carry this small method caveat.
Forward path: 1s bars.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, joblib
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
LO = int(pd.Timestamp("2020-12-01", tz="UTC").value)
HI = int(pd.Timestamp("2024-01-02", tz="UTC").value)


def _load_bars(pdir):
    f = next(pdir.glob("*.parquet"))
    t = pq.read_table(f, columns=["high", "low", "close", "ts_event", "ts_init"])
    d = t.to_pandas()
    for col in ("high", "low", "close"):
        d[col] = np.frombuffer(b"".join(d[col].values), dtype="<i8").astype(np.float64) / 1e9
    d["ts_event"] = d["ts_event"].astype(np.int64)
    d["ts_init"] = d["ts_init"].astype(np.int64)
    d = d[(d.ts_init >= LO) & (d.ts_init <= HI)].sort_values("ts_init").reset_index(drop=True)
    return d


print("loading 1s bars...", flush=True)
SEC = _load_bars(P1S)
print(f"  {len(SEC):,} 1s bars", flush=True)
print("loading 1m bars...", flush=True)
MIN = _load_bars(P1M)
print(f"  {len(MIN):,} 1m bars", flush=True)
SEC_TI = SEC.ts_init.values
SEC_TE = SEC.ts_event.values
MIN_TI = MIN.ts_init.values
MIN_H, MIN_L, MIN_C = MIN.high.values, MIN.low.values, MIN.close.values


def _wilder_atr_at(T, period=14, warm=400):
    j = np.searchsorted(MIN_TI, T, side="right")  # bars with ts_init <= T
    if j < period + 5:
        return None
    i0 = max(0, j - warm)
    h, l, c = MIN_H[i0:j], MIN_L[i0:j], MIN_C[i0:j]
    tr = np.empty(len(h))
    tr[0] = h[0] - l[0]
    pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    if len(tr) < period:
        return None
    atr = tr[:period].mean()
    for x in tr[period:]:
        atr = (atr * (period - 1) + x) / period
    return float(atr)


SPEC = ForwardOutcomeSpec(
    spec_id="econ_path_180s_vs_300s", horizons_seconds=(180, 300), max_tracking_seconds=600,
    excursion_units=("points", "atr"), reference_price=ReferencePrice.DECISION_CLOSE,
    diagnostic_levels_atr=(1.0, 2.0, 3.0),
    ordered_barriers=(OrderedBarrierSpec(barrier_id="one_to_one", favorable_atr=1.0,
                                         adverse_atr=1.0, horizon_seconds=300),),
)


def first_crossings(df_dir, scores, thr):
    d = df_dir.assign(score=scores)
    hi = d[d.score >= thr].sort_values(JOIN)
    return hi.groupby("regime_start_ns", as_index=False).first()


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
        fs = np.searchsorted(SEC_TE, T, side="right")  # bars with ts_event > T
        fe = np.searchsorted(SEC_TE, T + 620 * NS, side="right")
        if fe - fs < 5:
            continue
        bars = list(zip(SEC_TE[fs:fe].tolist(), SEC_TI[fs:fe].tolist(),
                        SEC.high.values[fs:fe].tolist(), SEC.low.values[fs:fe].tolist(),
                        SEC.close.values[fs:fe].tolist()))
        e = ProposedEntry(
            study_id=sid, source_period="train", candidate_key=str(int(r["regime_start_ns"])),
            decision_ts=T, entry_ts=T,
            direction=Direction("LONG") if direction == "LONG" else Direction("SHORT"),
            entry_price=entry_price, reference_price=ReferencePrice.DECISION_CLOSE,
            authorization_sha256="train", source_freeze_sha256=fsha, entry_atr=atr,
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
    def num(name):
        return pd.to_numeric(df[name], errors="coerce") if name in df.columns else pd.Series([np.nan] * len(df))
    def mean(n):
        v = num(n); return float(v.mean()) if v.notna().any() else None
    def med(n):
        v = num(n); return float(v.median()) if v.notna().any() else None
    s = {"n": len(df), "n_flipped": int(num("_flipped").fillna(0).sum()),
         "median_ttf_s": med("_ttf")}
    for h in (180, 300):
        s[f"mfe_atr_{h}s_mean"] = mean(f"mfe_{h}s_atr"); s[f"mfe_atr_{h}s_median"] = med(f"mfe_{h}s_atr")
        s[f"mae_atr_{h}s_mean"] = mean(f"mae_{h}s_atr"); s[f"mae_atr_{h}s_median"] = med(f"mae_{h}s_atr")
        s[f"return_atr_{h}s_mean"] = mean(f"return_{h}s_atr")
        s[f"mfe_pts_{h}s_mean"] = mean(f"mfe_{h}s")
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


def frozen_180s(d, direction, thr_key):
    dr = direction.lower()
    fz = json.loads((S180 / "artifacts" / f"train_experiment_freeze_{dr}.json").read_text())
    mid = fz["model_artifacts"][0]["model_id"]
    est = joblib.load(S180 / "artifacts" / "models" / f"{mid}.joblib")["C"]["estimator"]
    return est.predict_proba(d[ARM_C])[:, 1], fz["thresholds"]["C"][thr_key]["threshold"], fz["freeze_sha256"], S180.name


def frozen_300s(d, direction, thr_key):
    m = joblib.load(SPAR / "artifacts" / "train_fitted_models.joblib")
    rec = m[f"{direction}_C"]
    sc = rec["estimator"].predict_proba(d[rec["provenance"]["ordered_features"]])[:, 1]
    fz = json.loads((SPAR / "artifacts" / "train_experiment_freeze_repaired.json").read_text())
    tv = fz["thresholds"][f"{direction}_C"][thr_key]
    return sc, (tv["threshold"] if isinstance(tv, dict) else float(tv)), "parent_repaired", SPAR.name


def run_side(study, cn, on_, fz, direction, thr_key):
    c = pd.read_parquet(study / "artifacts" / cn)
    o = pd.read_parquet(study / "artifacts" / on_)
    df = c.merge(o[JOIN + ["regime_direction", "target_flip_within_horizon", "disposition", "time_to_flip_seconds"]],
                 on=JOIN, how="inner")
    df = df[df.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    d = df[df.regime_direction == (-1 if direction == "LONG" else 1)].reset_index(drop=True)
    sc, thr, fsha, sid = fz(d, direction, thr_key)
    fc = first_crossings(d, sc, thr)
    return summarize(build_and_compute(fc, direction, sid, fsha)), len(fc), float(thr)


def main():
    outp = S180 / "artifacts" / "diag_economic_path_180s_vs_300s.json"
    result = json.loads(outp.read_text()) if outp.exists() else {
        "method_note": "post-hoc Wilder ATR(14) on 1m bars (matches regime_engine); points exact, ATR diagnostic",
        "population": "first-crossing per regime at frozen threshold; forward path on 1s bars",
    }
    for thr_key in ("p90", "p95"):
        result.setdefault(thr_key, {})
        for direction in ("LONG", "SHORT"):
            cell = result[thr_key].setdefault(direction, {})
            for tag, study, cn, on_, fz in (
                ("180s", S180, "train_candidates_merged.parquet", "train_observations_merged.parquet", frozen_180s),
                ("300s", SPAR, "train_candidates_repaired_merged.parquet", "train_observations_repaired_merged.parquet", frozen_300s),
            ):
                if f"summary_{tag}" in cell:
                    print("skip", thr_key, direction, tag, flush=True); continue
                s, n, t = run_side(study, cn, on_, fz, direction, thr_key)
                cell[f"summary_{tag}"], cell[f"n_first_crossings_{tag}"], cell[f"threshold_{tag}"] = s, n, t
                outp.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
                print("done", thr_key, direction, tag, "n", n, flush=True)
    print("WROTE", outp.name, flush=True)


if __name__ == "__main__":
    main()
