"""Descriptive MFE / MAE / 1:1 for the NT bounded-March first-P90 fire population.

Governed engine research_workflow.forward_outcomes.compute_forward_outcomes; entry =
close of last 1s bar ts_init<=T; ATR = Wilder ATR(14) on completed 1m bars; forward
path on 1s bars. DESCRIPTIVE ONLY -- nothing optimized. Forward bars admitted with
ts_init < 2024-04-02 (no 2025).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
from research_workflow.forward_outcomes import (
    compute_forward_outcomes, ForwardOutcomeSpec, ProposedEntry, Direction, ReferencePrice, OrderedBarrierSpec,
)

S = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
VAL = S / "validation_march2024" / "artifacts"
CAT = ROOT / "data" / "catalog" / "NQ_v0_2020_2026" / "data" / "bar"
NS = 1_000_000_000
JOIN = ["observation_ts", "regime_start_ns", "checkpoint_index"]
FEATS = ["arrival_velocity", "arrival_acceleration", "ema_slope",
         "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
         "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
         "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
         "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"]
AGG = json.loads((S / "artifacts" / "train_experiment_freeze.json").read_text())
P90 = {"LONG": AGG["thresholds"]["LONG_C"]["p90"]["threshold"], "SHORT": AGG["thresholds"]["SHORT_C"]["p90"]["threshold"]}
LO = int(pd.Timestamp("2024-01-01", tz="UTC").value)
HI = int(pd.Timestamp("2024-04-02", tz="UTC").value)


def _load(pdir):
    f = next(pdir.glob("*.parquet"))
    d = pq.read_table(f, columns=["high", "low", "close", "ts_event", "ts_init"]).to_pandas()
    for c in ("high", "low", "close"):
        d[c] = np.frombuffer(b"".join(d[c].values), dtype="<i8").astype(np.float64) / 1e9
    d["ts_event"] = d["ts_event"].astype(np.int64); d["ts_init"] = d["ts_init"].astype(np.int64)
    return d[(d.ts_init >= LO) & (d.ts_init < HI)].sort_values("ts_init").reset_index(drop=True)


SEC = _load(CAT / "NQ.XCME-1-SECOND-LAST-EXTERNAL"); MIN = _load(CAT / "NQ.XCME-1-MINUTE-LAST-EXTERNAL")
SEC_TI, SEC_TE = SEC.ts_init.values, SEC.ts_event.values
MIN_TI, MIN_H, MIN_L, MIN_C = MIN.ts_init.values, MIN.high.values, MIN.low.values, MIN.close.values


def _atr(T, period=14, warm=400):
    j = np.searchsorted(MIN_TI, T, side="right")
    if j < period + 5:
        return None
    h, l, c = MIN_H[max(0, j - warm):j], MIN_L[max(0, j - warm):j], MIN_C[max(0, j - warm):j]
    tr = np.empty(len(h)); tr[0] = h[0] - l[0]; pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    if len(tr) < period:
        return None
    a = tr[:period].mean()
    for x in tr[period:]:
        a = (a * (period - 1) + x) / period
    return float(a)


SPEC = ForwardOutcomeSpec(
    spec_id="march2024_firstfire", horizons_seconds=(180, 300), max_tracking_seconds=600,
    excursion_units=("points", "atr"), reference_price=ReferencePrice.DECISION_CLOSE,
    diagnostic_levels_atr=(1.0, 2.0, 3.0),
    ordered_barriers=(OrderedBarrierSpec(barrier_id="one_to_one", favorable_atr=1.0, adverse_atr=1.0, horizon_seconds=300),),
)

nc = pd.read_parquet(json.loads((S / "_work" / "march2024_bounded_collect_result.json").read_text())["run"]["output_artifacts"]["candidates_parquet"])
no = pd.read_parquet(json.loads((S / "_work" / "march2024_bounded_collect_result.json").read_text())["run"]["output_artifacts"]["observations_parquet"])
MAR_LO = pd.Timestamp("2024-03-01", tz="UTC").value; MAR_HI = pd.Timestamp("2024-04-01", tz="UTC").value
nc = nc[(nc.observation_ts >= MAR_LO) & (nc.observation_ts < MAR_HI)]
d = nc.merge(no[JOIN + ["regime_direction", "time_to_flip_seconds"]], on=JOIN, how="inner")


def summarize(recs):
    if not recs:
        return {"n": 0}
    df = pd.DataFrame(recs)
    def num(n): return pd.to_numeric(df[n], errors="coerce") if n in df.columns else pd.Series([np.nan] * len(df))
    mm = num("max_mfe_atr"); ma = num("max_mae_atr")
    return {
        "n": len(df),
        "MFE_atr_median": float(mm.median()), "MFE_atr_mean": float(mm.mean()),
        "MAE_atr_median": float(ma.median()), "MAE_atr_mean": float(ma.mean()),
        "mfe_at_180s_atr_median": float(num("mfe_180s_atr").median()),
        "mfe_at_300s_atr_median": float(num("mfe_300s_atr").median()),
        "P_MFE_ge_1_atr": float((mm >= 1).mean()), "P_MFE_ge_2_atr": float((mm >= 2).mean()), "P_MFE_ge_3_atr": float((mm >= 3).mean()),
        "one_to_one_favorable_before_adverse_rate": float(num("ordered_one_to_one_binary_label").mean()),
        "favorable_before_adverse_1atr_rate": float(num("favorable_before_adverse_1atr").mean()),
    }


out = {"validation_month": "2024-03-01 through 2024-03-31", "population": "NT bounded-March first-P90 fire (one per regime), frozen TRAIN P90"}
for direction, sign in (("LONG", -1), ("SHORT", 1)):
    dd = d[d.regime_direction == sign].copy()
    mid = {r["model_role"]: r["model_id"] for r in AGG["model_artifacts"]}[f"{direction}_C"]
    bst = lgb.Booster(model_file=str(S / "artifacts" / "models" / f"{mid}.booster.txt"))
    dd["score"] = bst.predict(dd[FEATS].to_numpy(float))
    dd = dd.sort_values(["regime_start_ns", "observation_ts"], kind="mergesort")
    ff = dd[dd.score >= P90[direction]].groupby("regime_start_ns", as_index=False).head(1)
    recs = []
    for _, r in ff.iterrows():
        T = int(r["observation_ts"])
        si = np.searchsorted(SEC_TI, T, side="right")
        if si < 20:
            continue
        atr = _atr(T)
        if not atr or atr <= 0:
            continue
        fs = np.searchsorted(SEC_TE, T, side="right"); fe = np.searchsorted(SEC_TE, T + 620 * NS, side="right")
        if fe - fs < 5:
            continue
        bars = list(zip(SEC_TE[fs:fe].tolist(), SEC_TI[fs:fe].tolist(), SEC.high.values[fs:fe].tolist(),
                        SEC.low.values[fs:fe].tolist(), SEC.close.values[fs:fe].tolist()))
        e = ProposedEntry(study_id="march_val", source_period="oos", candidate_key=str(int(r["regime_start_ns"])),
                          decision_ts=T, entry_ts=T, direction=Direction(direction),
                          entry_price=float(SEC.close.values[si - 1]), reference_price=ReferencePrice.DECISION_CLOSE,
                          authorization_sha256="march_val", source_freeze_sha256=AGG["freeze_sha256"], entry_atr=atr)
        o = compute_forward_outcomes([e], bars, SPEC)
        if o:
            recs.append(o[0])
    out[direction] = summarize(recs)
# ALL = pooled
allrecs = []
out["ALL"] = {}
for k in ("LONG", "SHORT"):
    pass
outp = VAL / "first_fire_economics.json"
outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
print(json.dumps(out, indent=2, default=str))
